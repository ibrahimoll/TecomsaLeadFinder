"""Entity resolution: does a discovered company already exist in LeadFinder's master database?

Evidence, strongest first (the first that decides wins):

  STRONG  the same source record seen before            company_identifiers (connector, external id)
          the same official registration number         company_identifiers ("registry:LB", number)
          the same verified domain                      companies.domain
          the same claimed website domain               company_identifiers ("web", domain)
          the same phone number, and compatible names   phones.normalized_phone (company phones)
  MEDIUM  the same normalized name in the same city     companies / company_locations
          (or at the same street address), and exactly one such company exists
  WEAK    the same normalized name only                 never merged: recorded as a possible duplicate

Shared phones (a mall switchboard, a distributor's number) do not merge different names: a phone match
whose names share no distinctive word is only a possible duplicate. Several equally good matches are
ambiguous: nothing is merged, every candidate pair is recorded for review.
"""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import Company, CompanyIdentifier, CompanyLocation, DiscoverySuppression, Phone
from app.services.discovery.candidate import CompanyCandidate
from app.services.discovery.consolidation import _GENERIC, Group, name_tokens, simple_root
from app.services.discovery.normalizer import Normalized

MAX_POSSIBLE = 5


@dataclass
class Resolution:
    company: Company | None = None  # the existing canonical company, when one matched
    via: str | None = None  # which evidence matched
    possible: list[tuple[Company, str]] = field(default_factory=list)  # weak matches to record, not merge
    suppressed: str | None = None  # why discovery must skip the group (a deleted company)


def identifiers(c: CompanyCandidate, n: Normalized, country_code: str) -> list[tuple[str, str]]:
    keys = []
    if c.external_id:
        keys.append((c.connector, c.external_id[:300]))
    if c.registration_number:
        keys.append((f"registry:{country_code}", c.registration_number.strip()[:300]))
    if n.domain:
        keys.append(("web", n.domain))
    return keys


def _distinctive(name: str) -> set[str]:
    return {t for t in name_tokens(name) if len(t) >= 3 and t not in _GENERIC}


def compatible_names(a: str, b: str) -> bool:
    return bool(_distinctive(a) & _distinctive(b)) or (simple_root(a) is not None and simple_root(a) == simple_root(b))


def resolve(db: Session, group: Group, norms: dict[int, Normalized], country_code: str) -> Resolution:
    records = group.records
    keys = [k for c in records for k in identifiers(c, norms[id(c)], country_code)]
    domains = sorted({n.domain for c in records if (n := norms[id(c)]).domain})

    # A deleted company stays deleted: its identifiers / domain are suppressed.
    suppression_keys = keys + [("domain", d) for d in domains]
    if suppression_keys and (name := db.scalar(select(DiscoverySuppression.company_name).where(
            tuple_(DiscoverySuppression.scheme, DiscoverySuppression.value).in_(suppression_keys)).limit(1))):
        return Resolution(suppressed=f"“{name}” was deleted from LeadFinder; it is not re-added")

    if keys:
        hits = Counter(db.scalars(select(CompanyIdentifier.company_id).where(
            tuple_(CompanyIdentifier.scheme, CompanyIdentifier.value).in_(keys))).all())
        if hits:
            best_id = hits.most_common(1)[0][0]
            others = [db.get(Company, cid) for cid in hits if cid != best_id]
            return Resolution(db.get(Company, best_id), "source identifier",
                              [(o, "Shares a source identifier with this company") for o in others if o])

    if domains:
        company = db.scalar(select(Company).where(Company.domain.in_(domains)).limit(1))
        if company:
            return Resolution(company, "domain")

    phones = sorted({n.phone for c in records if (n := norms[id(c)]).phone})
    possible: list[tuple[Company, str]] = []
    if phones:
        ids = set(db.scalars(select(Phone.company_id).where(
            Phone.normalized_phone.in_(phones), Phone.person_id.is_(None), Phone.company_id.is_not(None))).all())
        owners = [c for cid in ids if (c := db.get(Company, cid))]
        same_name = [c for c in owners if compatible_names(group.name, c.name)]
        if len(same_name) == 1:
            return Resolution(same_name[0], "phone")
        possible += [(c, "Same phone number") for c in owners]

    names = {norms[id(c)].normalized_name for c in records} | {r for c in records if (r := simple_root(c.name))}
    names.discard("")
    if names:
        named = db.scalars(select(Company).where(Company.normalized_name.in_(names)).limit(50)).all()
        if named:
            cities = {c.city.lower() for c in records if c.city}
            addresses = {" ".join(c.address.lower().split()) for c in records if c.address}
            located = db.execute(select(CompanyLocation.company_id, CompanyLocation.city, CompanyLocation.address)
                                 .where(CompanyLocation.company_id.in_([c.id for c in named]))).all()
            places = {c.id: {(c.headquarters_city or "").lower()} for c in named}
            streets: dict[int, set[str]] = {c.id: set() for c in named}
            for cid, city, address in located:
                places[cid].add((city or "").lower())
                if address:
                    streets[cid].add(" ".join(address.lower().split()))
            same_place = [c for c in named if places[c.id] & cities or streets[c.id] & addresses]
            if len(same_place) == 1:
                return Resolution(same_place[0], "name and city")
            reason = "Same name in the same city (ambiguous)" if same_place else "Same name, different or unknown city"
            possible += [(c, reason) for c in (same_place or named)]
    return Resolution(possible=possible[:MAX_POSSIBLE])

