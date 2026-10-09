"""Within one batch: consolidate records of the same company (branches, duplicate listings) and assess
how credible each discovered company is (identity confidence).

Branch consolidation (deterministic, conservative). Records are the same company when
they share a website domain, a phone number, a company email domain, a brand, or the
same name once a trailing place name / "branch" is removed ("ABC Foods Jounieh" =
"ABC Foods"). A brand or name never merges records whose websites differ. Similar but
different names ("National Foods" / "National Food Company") are never merged. Within a
company, a record within 500 m of an existing location (or without coordinates) is a
duplicate listing of that place; further away it is another location (a branch).

Discovery confidence (deterministic, no AI). Points from the evidence:

  industry evidence   category 3 · generic manufacturing category + product 2 ·
                      producer category 1 · name only 1 · shop category + name 0
  website (own domain) +1    phone +1    street address +1    industrial facility +1
  2+ independent sources +1  2+ locations +1   source unsure it exists −1

  HIGH    ≥ 5 points, a manufacturing/industry category, and a website or phone
  MEDIUM  ≥ 3 points, and either a manufacturing/industry category with a website,
          phone or industrial facility, or (name-only / producer evidence) the
          company's own website
  LOW     otherwise; always LOW when the category is a shop and only the name says
          it manufactures

Confidence is about the evidence, not size, fit or sales readiness. The business-scale
signals collected alongside (locations, industrial site, brand…) are proxies for
later research, never a size claim.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace

from app.models.enums import IdentityConfidence
from app.services.discovery.candidate import CompanyCandidate as Candidate
from app.services.discovery.geography import AREAS
from app.services.discovery.industries import TIER_POINTS
from app.services.normalization import (
    company_domain,
    email_domain,
    has_legal_form,
    normalize_company_name,
    normalize_phone,
)

SAME_PLACE_KM = 0.5
# Words that name a location rather than the company ("ABC Foods Beirut Branch", "Patchi Downtown Boutique").
_BRANCH_WORDS = {"branch", "branche", "showroom", "outlet", "boutique", "kiosk", "factory", "plant", "فرع", "معرض"}
_LOCATION_FILLER = {"el", "al", "de", "du", "la", "st", "street", "road", "rd", "highway", "hwy", "main", "mall",
                    "center", "centre", "city", "downtown", "souk", "souks", "square", "old", "new"}
# Words that say nothing about which company it is: a name made only of these never merges.
_GENERIC = {
    "food", "foods", "dairy", "dairies", "sweets", "bakery", "bakeries", "factory", "company", "co", "group",
    "trading", "industries", "industry", "industrial", "the", "and", "for", "of", "al", "el", "est",
    "international", "mills", "mill", "roastery", "شركة", "مؤسسة", "مصنع", "معمل", "و", "لل",
}
# Common words that many unrelated Lebanese businesses start with: never a brand root on their own.
_COMMON = {"cedar", "cedars", "arz", "golden", "royal", "star", "sun", "green", "modern", "national", "lebanese",
           "crown", "white", "blue", "red", "grand", "super", "best", "first", "prime", "global", "united",
           "general", "oriental", "eastern", "middle", "phoenicia", "phoenician", "beirut", "lebanon", "new"}
# Neighbourhoods and towns that appear as branch suffixes, beyond the searchable areas in geography.py.
_NEIGHBOURHOODS = """hamra achrafieh ashrafieh ashrafiyeh verdun dbayeh dbaye jal el dib zalka antelias kaslik sin el fil
    mar mikhael gemmayzeh gemmayze badaro hazmieh baabda broummana beit mery dora daoura furn el chebbak raouche
    rawsheh mazraa ghobeiry choueifat khalde khaldeh damour chekka amioun ehden zgharta koura halba hermel
    rashaya marjayoun bint jbeil jezzine chouf metn matn keserwan kesrouan zouk mosbeh mikael ajaltoun faraya
    bikfaya mansourieh mkalles dekwaneh jdeideh bauchrieh sabtieh naccache rabieh mtayleb hadath kfarshima
    aramoun bchamoun sodeco jnah bliss adma sarba jdeidet nahr ibrahim amchit tabarja kfardebian
    elissar bourj hammoud hammoud saida sidon sour tyr tyre zahle zahleh jounieh jbeil byblos tripoli batroun
    nabatieh baalbek chtaura chtoura aley beirut beyrouth lebanon liban""".split()
_PLACE_WORDS = {
    word
    for areas in AREAS.values() for area in areas.values() for name in (area.key, *area.names)
    for word in normalize_company_name(name).split()
} | {"lebanon", "liban", "lb", "لبنان"} | set(_NEIGHBOURHOODS)
_SEPARATOR = re.compile(r"\s+[-–—|/]\s*|\s*[-–—|]\s+|\s*\(|\s*,\s*")
_LEGAL = {"sal": "sal", "شمل": "sal", "sarl": "sarl", "شمم": "sarl", "llc": "llc", "ltd": "ltd", "inc": "inc"}


def name_tokens(name: str) -> tuple[str, ...]:
    """Normalised name tokens; possessives joined ("McDonald's" and "McDonalds" -> "mcdonalds")."""
    return tuple(normalize_company_name(re.sub(r"['’`´]", "", name)).split())


def _distinctive(tokens: tuple[str, ...]) -> bool:
    if not any(t not in _GENERIC and len(t) >= 3 for t in tokens):
        return False
    return not (len(tokens) == 1 and tokens[0] in _COMMON)


def simple_root(name: str | None) -> str | None:
    """Name without trailing place / branch words ("McDonald's Lebanon" -> "mcdonalds"); for matching
    one known company name (a LeadFinder record) against a discovered company."""
    tokens = list(name_tokens(name or ""))
    while len(tokens) > 1 and (tokens[-1] in _PLACE_WORDS or tokens[-1] in _BRANCH_WORDS):
        tokens.pop()
    return " ".join(tokens) if _distinctive(tuple(tokens)) else None


def _own_place_words(c: Candidate) -> set[str]:
    """Words of the record's own location (city, address, the source's locality)."""
    texts = [c.city, c.address, c.data.get("locality") if c.data else None]
    return {t for text in texts if text for t in name_tokens(text) if len(t) >= 3}


def _domain_label(domain: str | None) -> str | None:
    """'mcdelivery.mcdonalds.com.lb' -> 'mcdonalds' (the registered name, without country/sub domains)."""
    if not domain:
        return None
    labels = domain.split(".")
    second_level = len(labels) >= 3 and labels[-2] in ("com", "org", "net", "edu", "gov", "co")
    return labels[-3] if second_level else labels[-2]


def own_domain(c: Candidate) -> str | None:
    """The record's website domain when it is about this company. A shared menu or ordering
    platform ("menu.omegasoftware.ca/kfclebanon") is not, and must never merge restaurants."""
    domain = company_domain(c.website)
    label = _domain_label(domain)
    if not label:
        return None
    compact = "".join(name_tokens(c.name))
    if label in compact or compact in label or any(len(t) >= 3 and t not in _GENERIC and t in label
                                                    for t in name_tokens(c.name)):
        return domain
    return None


def _legal_form(name: str) -> str | None:
    tokens = re.sub(r"[^\w\s]|_", " ", name.lower().replace(".", "")).split()
    return _LEGAL.get(tokens[-1]) if len(tokens) > 1 else None


def _roots(candidates: list[Candidate]) -> dict[int, tuple[str, ...]]:
    """The company name of each record, location suffix removed only when two signals agree:
    another record of the search carries that root name, AND the removed part is clearly a
    location (known place, a word of the record's own address, a branch word, or text after a
    " - " separator when another record has exactly the root name)."""
    tokens = {id(c): name_tokens(c.name) for c in candidates}
    names = set(tokens.values())
    prefixes = Counter(t[:k] for t in names for k in range(1, len(t) + 1))
    roots = {}
    for c in candidates:
        full = tokens[id(c)]
        roots[id(c)] = full
        parts = _SEPARATOR.split(c.name, maxsplit=1)
        left = name_tokens(parts[0]) if len(parts) == 2 else None
        own = _own_place_words(c)
        for k in range(len(full) - 1, 0, -1):
            root, suffix = full[:k], full[k:]
            if prefixes[root] < 2 or not _distinctive(root):
                continue
            located = all(t in _PLACE_WORDS or t in own or t in _BRANCH_WORDS or t in _LOCATION_FILLER for t in suffix) \
                and any(t not in _LOCATION_FILLER for t in suffix)
            separated = left == root and root in names and len(suffix) <= 4
            if located or separated:
                roots[id(c)] = root
                break
    return roots


def _km(a: Candidate, b: Candidate) -> float | None:
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _cut_to(raw: str, root: tuple[str, ...]) -> str | None:
    """The leading words of a raw name that spell the root, keeping their original form."""
    words = raw.split()
    for cut in range(len(words), 0, -1):
        text = " ".join(words[:cut]).rstrip(" -–—|/,(")
        if name_tokens(text) == root:
            return text
    return None


@dataclass
class Member:
    record: Candidate
    kind: str  # "DUPLICATE" (same place listed again) | "MERGED_BRANCH" (another location)
    via: str  # what links it: "phone number", "website", "name"…
    place: Candidate | None = None  # for a duplicate: the location it repeats


@dataclass
class Group:
    """One company: its best record first, then duplicate listings and other locations."""

    primary: Candidate
    root: tuple[str, ...] = ()  # company name tokens without a location suffix
    members: list[Member] = field(default_factory=list)
    locations: list[Candidate] = field(default_factory=list)  # one record per distinct place
    domain_labels: set[str] = field(default_factory=set)
    operators: set[str] = field(default_factory=set)
    legal_forms: set[str] = field(default_factory=set)

    @property
    def records(self) -> list[Candidate]:
        return [self.primary, *(m.record for m in self.members)]

    @property
    def name(self) -> str:
        """Company name: the brand the source gives, else the best record's name without its
        location suffix when the company has several locations ("McDonald's Hamra" -> "McDonald's")."""
        brand = next((c.brand for c in self.records if c.brand and name_tokens(c.brand) == self.root), None)
        if brand:
            return brand
        if len(self.locations) < 2:
            return self.primary.name
        # Each record's name cut back to the shared root ("McDonald’s Amchit" -> "McDonald’s"); the
        # spelling most records use wins ("Domino's Pizza" over one "Domino's pizza"), best record on ties.
        spellings = Counter(cut for c in self.records if (cut := _cut_to(c.name, self.root)))
        if not spellings:
            return self.primary.name
        primary = _cut_to(self.primary.name, self.root)
        return max(spellings, key=lambda s: (spellings[s], s == primary))

    def merged(self) -> Candidate:
        """The best record named as the company, with blanks filled from its other records (a
        company website is preferred over a social page). Used for the saved company and its row."""
        c = replace(self.primary, company_name=self.name)
        others = [m.record for m in self.members]
        if not company_domain(c.website):
            c.website = next((m.website for m in others if company_domain(m.website)), None) or c.website or next(
                (m.website for m in others if m.website), None)
        for attr in ("phone", "email", "address", "city"):
            if not getattr(c, attr):
                setattr(c, attr, next((getattr(m, attr) for m in others if getattr(m, attr)), None))
        return c

    def track(self, c: Candidate) -> None:
        if label := _domain_label(own_domain(c)):
            self.domain_labels.add(label)
        if c.operator:
            self.operators.add(" ".join(name_tokens(c.operator)))
        if form := _legal_form(c.name):
            self.legal_forms.add(form)

    def conflicts(self, c: Candidate) -> bool:
        """Evidence of a different legal entity: another company website, another operator
        (franchisee) or another legal form. Shared names never override it."""
        label = _domain_label(own_domain(c))
        if label and self.domain_labels and not any(label in g or g in label for g in self.domain_labels):
            return True
        operator = " ".join(name_tokens(c.operator)) if c.operator else None
        if operator and self.operators and operator not in self.operators:
            return True
        form = _legal_form(c.name)
        return bool(form and self.legal_forms and form not in self.legal_forms)

    def add(self, c: Candidate, via: str) -> None:
        near = [(d, place) for place in self.locations if (d := _km(c, place)) is None or d <= SAME_PLACE_KM]
        if near:
            self.members.append(Member(c, "DUPLICATE", via, near[0][1]))
        else:
            self.members.append(Member(c, "MERGED_BRANCH", via))
            self.locations.append(c)
        self.track(c)


def _keys(c: Candidate, root: tuple[str, ...]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(strong identity keys, name-like keys)."""
    strong = []
    if d := own_domain(c):
        strong.append(("domain", d))
    if p := normalize_phone(c.phone, c.country):
        strong.append(("phone", p))
    if e := email_domain(c.email):
        strong.append(("email", e))
    weak = []
    if c.brand and (b := simple_root(c.brand)):
        weak.append(("name", b))
    if any(t not in _GENERIC and len(t) >= 3 for t in root):  # stripped roots were already checked in _roots
        weak.append(("name", " ".join(root)))
    return strong, weak


def consolidate(candidates: list[Candidate]) -> list[Group]:
    """Group records of the same company (input best first, so each group's first record is its best).

    Strong keys (company website, phone, email domain) merge directly. Name keys (the name
    without a location suffix, the source's brand) merge only when nothing indicates another
    legal entity (see Group.conflicts). Phone numbers are not needed: branches have their own.
    """
    groups: list[Group] = []
    by_key: dict[tuple[str, str], Group] = {}
    labels = {"domain": "website", "phone": "phone number", "email": "email domain", "name": "name"}
    roots = _roots(candidates)
    for c in candidates:
        strong, weak = _keys(c, roots[id(c)])
        key = next((k for k in strong if k in by_key), None)
        if key is None:
            key = next((k for k in weak if k in by_key and not by_key[k].conflicts(c)), None)
        if key is None:
            group = Group(primary=c, root=roots[id(c)], locations=[c])
            group.track(c)
            groups.append(group)
        else:
            group = by_key[key]
            group.add(c, labels[key[0]])
        for k in strong + weak:
            by_key.setdefault(k, group)
    return groups


@dataclass
class Assessment:
    confidence: IdentityConfidence
    points: int
    reasons: list[str]
    concerns: list[str]
    signals: list[str]


def assess(group: Group) -> Assessment:
    records = group.records
    best = max(records, key=lambda c: TIER_POINTS.get(c.tier, 0))
    points = TIER_POINTS.get(best.tier, 0)
    reasons, concerns, signals = [], [], []
    if best.tier in ("category", "industrial"):
        reasons.append(f"Industry confirmed by category ({best.match_reason})")
    elif best.tier == "producer":
        reasons.append(f"Producer category ({best.match_reason})")
    else:
        concerns.append(f"Weak industry evidence: {best.match_reason}")

    domains = sorted({d for c in records if (d := company_domain(c.website))})
    phones = sorted({p for c in records if (p := normalize_phone(c.phone, c.country))})
    has_contact = bool(domains or phones)
    if domains:
        points += 1
        reasons.append(f"Website found ({domains[0]})")
    elif any(c.website for c in records):
        concerns.append("Only a social-media or link page, no company website")
    else:
        concerns.append("No website")
    if phones:
        points += 1
        reasons.append("Phone found")
    else:
        concerns.append("No phone")
    if any(c.address for c in records):
        points += 1
        reasons.append("Street address found")
    facility = next((c.facility for c in records if c.facility), None)
    if facility:
        points += 1
        reasons.append(facility)
    datasets = sorted({d for c in records for d in c.datasets})
    if len(datasets) >= 2:
        points += 1
        reasons.append(f"Listed by {len(datasets)} independent sources ({', '.join(datasets)})")
    if len(group.locations) >= 2:
        points += 1
        reasons.append(f"{len(group.locations)} locations discovered")
    notes = [n for c in records for n in c.notes]
    if any("unsure the place exists" in n for n in notes):
        points -= 1
    concerns.extend(dict.fromkeys(notes))
    if not has_contact and not any(c.address for c in records):
        concerns.append("Only a name and a map location")

    confirmed = best.tier in ("category", "industrial")
    if best.tier == "retail_name":
        confidence = IdentityConfidence.LOW
    elif points >= 5 and confirmed and has_contact:
        confidence = IdentityConfidence.HIGH
    elif points >= 3 and ((confirmed and (has_contact or facility)) or (not confirmed and domains)):
        confidence = IdentityConfidence.MEDIUM
    else:
        confidence = IdentityConfidence.LOW
        if not confirmed and not domains and has_contact:
            concerns.append("Industry only suggested by the name or a farm category, and no company website confirms it")

    # Business-scale proxies for later research: never turned into a size label here.
    if len(group.locations) >= 2:
        cities = sorted({c.city for c in group.locations if c.city})
        signals.append(f"{len(group.locations)} locations" + (f" ({', '.join(cities)})" if cities else ""))
    if facility:
        signals.append("Industrial / manufacturing site")
    if domains:
        signals.append("Own website")
    if len(phones) >= 2 or any(len(c.data.get("phones") or []) >= 2 for c in records):
        signals.append("Several phone numbers")
    brands = sorted({b for c in records for b in (c.brand, c.operator) if b})
    if brands:
        signals.append(f"Brand / operator: {', '.join(brands)}")
    if len(datasets) >= 2:
        signals.append(f"{len(datasets)} independent source listings")
    if any(has_legal_form(c.name) for c in records):
        signals.append("Legal form in the name (e.g. S.A.L.)")
    if any(re.search(r"distribut|wholesale|warehouse", (c.industry or "").lower()) for c in records):
        signals.append("Distribution / wholesale activity")
    return Assessment(confidence, points, reasons, concerns, signals)


CONFIDENCE_RANK = {IdentityConfidence.HIGH: 0, IdentityConfidence.MEDIUM: 1, IdentityConfidence.LOW: 2}

