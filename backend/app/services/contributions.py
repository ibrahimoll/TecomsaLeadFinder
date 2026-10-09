"""Contributions (Steps 6.1-6.3): authorized business contacts entering LeadFinder's proprietary contact graph -
TECOMSA CRM exports, salesperson-confirmed contacts, business cards, professional e-mail signatures, meeting contacts
and contacts a user adds by hand. One pipeline: explicit (a user contributes, never harvested), attributed (the
contributor, the channel, the source record), scoped (visibility), reversible (suppress), dry run first.

    python -m app.services.contributions FILE CHANNEL [--owner EMAIL] [--visibility organization|managers|private]
                                                  [--apply]
    FILE: .csv / .xlsx (rows), .vcf (business cards), .txt (e-mail signatures, blank-line separated)

    channel                     source type          contact provenance   e-mail status
    ODOO_CRM / CSV_IMPORT       internal_seed        internal_crm         published (confirmed when the row says so)
    SALES_CONFIRMED             internal_seed        human_confirmed      confirmed
    BUSINESS_CARD               business_card        contributed          published
    EMAIL_SIGNATURE             email_signature      contributed          published
    MEETING_CONTACT             meeting_contact      contributed          published (attendance: person <-> e-mail,
                                                                          never a title)
    CONTRIBUTED_BUSINESS_CONTACT contributed_contact contributed          published

Resolution (company EXACT / STRONG / POSSIBLE, person EXACT / STRONG / POSSIBLE / NEW, conflicts with colleague-
confirmed titles flagged) and the trail of every contact (contact_evidence) are shared by all channels.
Corroboration: the same work e-mail / phone from another source raises its confidence and is counted; a prediction
attested by a real card / signature / CRM record becomes published (the prediction stays in its trail). A row
without a job title attaches its contacts to a person LeadFinder already knows at the company (same e-mail, else
the same name) and never creates a person. Nothing private: role mailboxes go to nobody, home numbers are not read,
notes are never imported.
"""

import logging
import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Company, CompanyAlias, CompanyDomain, CompanyPerson, ContactEvidence, Email, Evidence, Person,
                        Phone, Source, User)
from app.services import audit_service
from app.services import contact_intelligence as contacts
from app.services.discovery.geography import find_country
from app.services.normalization import normalize_domain, normalize_phone
from app.services.people import persistence
from app.services.people.external import generic
from app.services.people.external.lebanon.records import Record, candidate, org_key, published_date
from app.services.people.names import name_key
from app.services.people.resolution import Match, resolve
from app.services.people.titles import classify, fold

logger = logging.getLogger("leadfinder.contributions")
CHANNELS = {  # channel: (source type, contact provenance, every e-mail confirmed)
    "ODOO_CRM": ("internal_seed", "internal_crm", False),
    "CSV_IMPORT": ("internal_seed", "internal_crm", False),
    "SALES_CONFIRMED": ("internal_seed", "human_confirmed", True),
    "BUSINESS_CARD": ("business_card", "contributed", False),
    "EMAIL_SIGNATURE": ("email_signature", "contributed", False),
    "MEETING_CONTACT": ("meeting_contact", "contributed", False),
    "CONTRIBUTED_BUSINESS_CONTACT": ("contributed_contact", "contributed", False),
}
SYSTEMS = tuple(CHANNELS)
VISIBILITIES = ("organization", "managers", "private")
SEED_COLUMNS = {
    **generic.DEFAULT_COLUMNS,
    "company": r"^(?:company|company name|related company|parent company|account|organi[sz]ation|customer|"
               r"soci[eé]t[eé]|entreprise|الشركة|اسم الشركة)\b",
    "person": r"^(?:contact name|contact|name|display name|full name|person|attendee|participant|nom|الاسم)\b",
    "first_name": r"^(?:first name|given name|pr[eé]nom)\b",
    "last_name": r"^(?:last name|surname|family name|nom de famille)\b",
    "website": r"(?:company domain|domain|website|web site|site web|الموقع)",
    "company_phone": r"^(?:company phone|main phone|switchboard|standard)\b",
    "phone": r"^(?:phone|business phone|work phone|office|tel|telephone|t[eé]l[eé]phone|direct|الهاتف)\b",
    "extension": r"^(?:ext|extension|poste)\b",
    "record_id": r"^(?:id|record id|external id|contact id|partner id|reference|ref)\b",
    "owner": r"^(?:salesperson|sales person|sales owner|owner|organizer|organiser|user|responsible|commercial)\b",
    "last_seen": r"^(?:last interaction|last activity|last contact|last updated|meeting date|write date|date)\b",
    "contact_status": r"^(?:contact status|email status|status)\b",
    "employment": r"^(?:current|former|active|employment|still at company)\b",
}
CONFIRMED = re.compile(r"^(confirmed|verified|valid|replied|active customer)$", re.IGNORECASE)
INVALID = re.compile(r"^(invalid|bounced|wrong|do not use)$", re.IGNORECASE)
FORMER = re.compile(r"^(former|left|no|false|inactive|ex[- ]?employee|0)$", re.IGNORECASE)
WEAK_STATUSES = ("unknown", "predicted", "high_confidence_predicted", "catch_all")


# ---- input formats -------------------------------------------------------------------------------------------------


_SIG_PHONE = re.compile(r"(?P<label>mob(?:ile)?|cell|gsm|whats\s?app|tel|phone|office|direct|t|m|w)?\s*[.:]?\s*"
                        r"(?P<number>\+?\(?\d[\d\s().-]{6,}\d)(?:\s*(?:ext\.?|x|poste)\s*(?P<ext>\d{1,6}))?",
                        re.IGNORECASE)


def parse_signature(text: str) -> dict | None:
    """A professional e-mail signature -> {person, title, company, email, mobile, phone, whatsapp, extension, website}.
    Only the signature block is read (the caller contributes it, never a mailbox): the first line is the name, a line
    the title taxonomy recognises is the title, the e-mail's domain / a website line names the company's site."""
    lines = [" ".join(line.split()).strip(" |-–") for line in text.strip().splitlines()]
    lines = [line for line in lines if line and not re.match(r"^(regards|best|thanks|kind regards|sincerely)", line,
                                                            re.IGNORECASE)]
    if not lines:
        return None
    entry: dict = {"person": lines[0]}
    for line in lines[1:]:
        if m := generic._EMAIL.search(line):
            entry.setdefault("email", m[0])
            continue
        if re.search(r"(https?://|www\.)\S+", line, re.IGNORECASE):
            entry.setdefault("website", re.search(r"(https?://|www\.)\S+", line, re.IGNORECASE)[0])
            continue
        phones = list(_SIG_PHONE.finditer(line))
        if phones and sum(c.isdigit() for c in line) >= 7:
            for m in phones:
                label = (m["label"] or "").lower()
                key = "whatsapp" if "whats" in label else "mobile" if label in ("mob", "mobile", "cell", "gsm", "m") \
                    else "phone"
                entry.setdefault(key, m["number"].strip())
                if m["ext"]:
                    entry.setdefault("extension", m["ext"])
            continue
        if "title" not in entry and classify(line) is not None:
            entry["title"] = line
        elif "company" not in entry:
            entry["company"] = line
    return entry if entry.get("email") or entry.get("mobile") or entry.get("phone") else None


def _entries(name: str, raw: bytes) -> tuple[list[dict], list[str]]:
    """(rows as {field: value}, the source's columns) of a contributed file."""
    lower = name.lower()
    if lower.endswith(".vcf"):
        cards = []
        for record in generic.vcard_records(raw.decode("utf-8", "replace")):
            if record.person:
                cards.append({"company": record.org[0], "person": record.person, "title": record.title,
                              "email": record.email, "mobile": record.phone,
                              "whatsapp": record.facts.get("whatsapp"),
                              "website": (record.domains or [None])[0]})
        return cards, ["vCard"]
    if lower.endswith((".txt", ".eml")):
        blocks = re.split(r"\n\s*\n|\n-{2,}\s*\n", raw.decode("utf-8", "replace"))
        return [e for e in (parse_signature(b) for b in blocks) if e], ["signature"]
    rows = [[generic._clean(c) for c in r] for r in (generic.xlsx_rows(raw) if lower.endswith((".xlsx", ".xls"))
                                                     else generic.csv_rows(raw.decode("utf-8-sig", "replace")))]
    header_at = next((i for i, r in enumerate(rows[:10]) if ("company" in (m := generic.header_map(r, SEED_COLUMNS))
                                                              or "website" in m or "email" in m)
                      and ("person" in m or "first_name" in m)), None)
    if header_at is None:
        raise ValueError("no header row with a contact name column and a company / website / e-mail column")
    mapping = generic.header_map(rows[header_at], SEED_COLUMNS)
    out = []
    for row in rows[header_at + 1:]:
        entry = {f: row[i] for f, i in mapping.items() if i < len(row) and row[i]}
        if entry.get("first_name"):
            entry["person"] = " ".join(x for x in (entry.pop("first_name"), entry.get("last_name") or "") if x)
        elif entry.get("last_name") and entry.get("person"):
            entry["person"] = f"{entry['person']} {entry['last_name']}"
        out.append(entry)
    return out, rows[header_at]


# ---- resolution ------------------------------------------------------------------------------------------------------


class _Index:
    """Every LeadFinder company by verified domain, normalised name / alias and phone (built once per import)."""

    def __init__(self, db: Session):
        self.domains = {normalize_domain(d) or d: cid for cid, d in db.execute(
            select(Company.id, Company.domain).where(Company.domain.is_not(None)))}
        self.domains |= {normalize_domain(d) or d: cid for cid, d in db.execute(
            select(CompanyDomain.company_id, CompanyDomain.domain))}
        self.names: dict[str, set[int]] = {}
        self.phones: dict[str, set[int]] = {}
        self.country: dict[int, str | None] = {}
        for cid, name, legal, phone, country in db.execute(select(
                Company.id, Company.name, Company.legal_name, Company.primary_phone, Company.headquarters_country)):
            self.country[cid] = country
            for n in (name, legal):
                if n and (key := org_key(n)):
                    self.names.setdefault(key, set()).add(cid)
            if phone and (k := contacts.national(phone)):
                self.phones.setdefault(k, set()).add(cid)
        for cid, alias in db.execute(select(CompanyAlias.company_id, CompanyAlias.alias)):
            if alias and (key := org_key(alias)):
                self.names.setdefault(key, set()).add(cid)

    def match(self, entry: dict, email: str | None) -> tuple[str, int | None]:
        domains = [d for d in ((generic._domains_of(entry.get("website")) or [None])[0],
                               (email or "").rpartition("@")[2] or None) if d and d not in contacts.FREE_MAIL]
        for d in domains:
            if (cid := self.domains.get(normalize_domain(d) or d)) is not None:
                return "exact", cid
        country = entry.get("country")

        def compatible(cid: int) -> bool:  # a country that disagrees rules a candidate out
            theirs = self.country.get(cid)
            if not country or not theirs:
                return True
            a, b = find_country(country), find_country(theirs)
            return a.code == b.code if a and b else fold(country) == fold(theirs)

        named = {c for c in self.names.get(org_key(entry.get("company") or ""), set()) if compatible(c)}
        if len(named) == 1:
            return "strong", next(iter(named))
        phoned = {c for c in self.phones.get(contacts.national(entry.get("company_phone")) or "-", set())
                  if compatible(c)}
        if len(phoned) == 1:
            return "strong", next(iter(phoned))
        return ("possible", None) if len(named) > 1 or len(phoned) > 1 else ("unmatched", None)


def _phone(raw: str | None, country: str | None) -> tuple[str, str | None] | None:
    """(as given, E.164 when the country is known or the number carries its own code: never an assumed code)."""
    if not raw:
        return None
    return raw, normalize_phone(raw, country) if (country or raw.strip().startswith(("+", "00"))) else None


def _known_person(db: Session, company_id: int, email: str | None, name: str | None) -> int | None:
    """A person LeadFinder already knows at the company: the same work e-mail, else exactly one same name."""
    if email and (pid := db.scalar(select(Email.person_id).where(Email.email == email,
                                                                 Email.company_id == company_id))):
        return pid
    key = name_key(name or "")
    same = {p.id for p in db.scalars(select(Person).join(CompanyPerson).where(CompanyPerson.company_id == company_id))
            if key and name_key(p.full_name) == key}
    return next(iter(same)) if len(same) == 1 else None


# ---- the pipeline ----------------------------------------------------------------------------------------------------


def contribute(db: Session, entries: list[dict], *, channel: str, contributor_id: int | None = None,
               visibility: str = "organization", apply: bool = False, label: str = "contribution",
               company_id: int | None = None) -> dict:
    """Entries -> the contact graph. company_id: the entries are this company's (a contribution made on its page).
    The report is exactly what an apply does; it is written only when apply=True (a dry run rolls back)."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    if visibility not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {', '.join(VISIBILITIES)}")
    source_type, provenance, all_confirmed = CHANNELS[channel]
    now = datetime.now(timezone.utc)
    index = _Index(db) if company_id is None else None
    users = {key.lower(): u.id for u in db.scalars(select(User)) for key in (u.email, u.name) if key}  # Odoo: names
    stats: Counter = Counter()
    review: list[dict] = []
    companies, people_seen = set(), set()
    for line, entry in enumerate(entries, start=1):
        if not entry:
            continue
        stats["rows"] += 1
        email = (generic._EMAIL.findall(entry.get("email") or "") or [None])[0]
        email = email.strip().lower() if email else None
        if email and generic.ROLE_MAILBOX.match(email):
            email = None  # info@ / sales@: never a person's
        level, cid = ("given", company_id) if company_id else index.match(entry, email)
        stats[f"company_{level}"] += 1
        if cid is None:
            if len(review) < 100:
                review.append({"line": line, "company": entry.get("company"), "reason": f"company {level}"})
            continue
        company = db.get(Company, cid)
        country = entry.get("country") or company.headquarters_country
        owner = users.get((entry.get("owner") or "").lower(), contributor_id)
        record_id = entry.get("record_id") or "|".join(fold(entry.get(k) or "") for k in ("person", "email"))
        stated = published_date(entry.get("last_seen")) or now
        source = db.scalar(select(Source).where(Source.source_type == source_type, Source.publisher == channel,
                                                Source.external_reference == f"{cid}:{record_id}"[:300]))
        if source is not None and (source.metadata_ or {}).get("suppressed"):
            stats["suppressed_skipped"] += 1  # removed on request: never imported again
            continue
        stats["source_records_seen_before" if source else "source_records_new"] += 1
        if source is None:
            source = Source(source_type=source_type, name=f"TECOMSA {channel.replace('_', ' ').title()}",
                            publisher=channel, external_reference=f"{cid}:{record_id}"[:300], retrieved_at=now,
                            published_at=stated, source_quality=95,
                            metadata_={"contributor_user_id": owner, "visibility": visibility, "label": label,
                                       "channel": channel, "contributed_at": now.isoformat()})
            db.add(source)
            db.flush()
        title = entry.get("title") or ""
        if entry.get("department") and title and fold(entry["department"]) not in fold(title):
            title = f"{title}, {entry['department']}"
        if not title:  # attendance / a card without a title: contacts of a person already known, never a new one
            person_id = _known_person(db, cid, email, entry.get("person"))
            if person_id is None:
                stats["rejected_no_title_unknown_person"] += 1
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "person": entry.get("person"),
                                   "reason": "no job title and not a known person: not created"})
                continue
            stats["person_exact"] += 1
        else:
            status = "former" if FORMER.match(entry.get("employment") or "") else None
            record = Record(org=[company.name], person=entry.get("person"), title=title, email=email, status=status,
                            published=stated.date().isoformat(), excerpt=f"{channel} record {record_id}")
            c = candidate(record, company_id=cid, source_id=source.id, url=None, source_type="internal",
                          quality=95, match_confidence=95, stated=stated, category=source_type, document=label)
            if c is None:
                stats["rejected_not_person_or_title"] += 1
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "reason": "no person name / job title"})
                continue
            c.email = c.phone = None  # stored below with this channel's provenance
            same = _known_person(db, cid, email, None) or db.scalar(select(CompanyPerson.person_id).join(
                Evidence, Evidence.company_person_id == CompanyPerson.id).where(Evidence.source_id == source.id)
                .limit(1))
            match = resolve(db, cid, c)
            if same is not None:
                match = Match(db.get(Person, same), "same work e-mail / same contributed record")
                stats["person_exact"] += 1
            elif match.person is not None:
                stats["person_strong"] += 1
            elif match.possible:
                stats["person_possible"] += 1
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "person": c.full_name,
                                   "reason": f"possibly {match.possible[0].full_name} (another role): review"})
                continue
            else:
                stats["person_new"] += 1
            confirmed = [r for r in db.scalars(select(CompanyPerson).where(
                CompanyPerson.company_id == cid, CompanyPerson.person_id == match.person.id))
                if "job_title" in (r.corrected_fields or [])] if match.person else []
            if confirmed and all(fold(r.job_title) != fold(c.raw_title or "") for r in confirmed):
                stats["conflicts"] += 1  # a colleague-confirmed title outranks the contribution: flagged, kept
                if len(review) < 100:
                    review.append({"line": line, "company": company.name, "person": c.full_name,
                                   "reason": f"title conflict: confirmed '{confirmed[0].job_title}' vs "
                                             f"'{c.raw_title}' (not changed)"})
                person_id = match.person.id
            else:
                known = set(db.scalars(select(CompanyPerson.id).where(CompanyPerson.company_id == cid)))
                role = persistence.save(db, company, c, match, now)
                if role is None:
                    stats["suppressed_person"] += 1  # removed on request: never imported again
                    continue
                if role.id not in known:  # only a role the contribution creates is TECOMSA's (public stays public)
                    role.owner_user_id, role.visibility = owner, visibility
                person_id = role.person_id
        companies.add(cid)
        people_seen.add(person_id)
        stats[f"visibility_{visibility}"] += 1
        _contacts(db, entry, email, person_id, company, country, source, owner, visibility, provenance,
                  all_confirmed, record_id, channel, stated, stats)
        persistence.recompute(db, company)
    report = {**dict(stats), "companies_matched": len(companies), "unique_people": len(people_seen),
              "review": review, "applied": apply, "channel": channel, "label": label}
    if apply:
        audit_service.record(db, action="contribution.applied", user_id=contributor_id, entity_type="contribution",
                             entity_id=label[:100], metadata={k: v for k, v in report.items() if k != "review"})
        db.commit()
    else:
        db.rollback()  # a dry run: exactly what an apply would do, nothing written
    logger.info("contribution %s %s (%s): %s", channel, label, "applied" if apply else "dry run",
                {k: v for k, v in report.items() if k != "review"})
    return report


def ingest(db: Session, *, system: str, file_name: str, raw: bytes, owner_user_id: int | None = None,
           visibility: str = "organization", apply: bool = False, user_id: int | None = None) -> dict:
    """A contributed file (CSV / XLSX rows, .vcf cards, .txt signatures) through the pipeline."""
    entries, columns = _entries(file_name, raw)
    report = contribute(db, entries, channel=system, contributor_id=owner_user_id, visibility=visibility,
                        apply=apply, label=file_name)
    return {**report, "file": file_name, "columns": columns}


def _contacts(db: Session, entry: dict, email: str | None, person_id: int, company: Company, country: str | None,
              source: Source, owner: int | None, visibility: str, provenance: str, all_confirmed: bool,
              record_id: str, channel: str, stated: datetime, stats: Counter) -> None:
    evidence = f"TECOMSA {channel} record {record_id}"[:500]
    status_text = entry.get("contact_status") or ""
    if email:
        status = "confirmed" if all_confirmed or CONFIRMED.match(status_text) else \
            "invalid" if INVALID.match(status_text) else "published"
        row = db.scalar(select(Email).where(Email.person_id == person_id, Email.email == email))
        if row is None:
            row = Email(person_id=person_id, company_id=company.id, email=email, email_type="work", status=status,
                        confidence=95 if status != "invalid" else 0, source_id=source.id, first_seen_at=stated,
                        last_seen_at=stated, provenance=provenance, owner_user_id=owner, visibility=visibility,
                        evidence=evidence, last_verified_at=stated if status == "confirmed" else None)
            db.add(row)
            stats["emails_added"] += 1
            stats["emails_confirmed"] += status == "confirmed"
        else:
            stats["emails_already_known"] += 1  # a duplicate avoided: its evidence is added, the row kept
            others = set(db.scalars(select(ContactEvidence.source_id).where(ContactEvidence.email_id == row.id)))
            if source.id not in others:
                stats["emails_corroborated"] += 1  # another source states the same address
                row.confidence = min(95, (row.confidence or 60) + 5)
            if row.status in WEAK_STATUSES and status != "invalid":
                stats["predicted_to_corroborated"] += row.status != "unknown"
                row.status, row.provenance, row.last_verified_at = status, provenance, (
                    stated if status == "confirmed" else None)  # a real record attests the guess
            elif status == "confirmed" and row.status != "confirmed" and row.provenance != "human_confirmed":
                row.status, row.last_verified_at, row.confidence = "confirmed", stated, 95
                stats["emails_confirmed"] += 1
            row.last_seen_at = max(row.last_seen_at or stated, stated)
        db.flush()
        if not db.scalar(select(ContactEvidence.id).where(ContactEvidence.email_id == row.id,
                                                          ContactEvidence.source_id == source.id)):
            db.add(ContactEvidence(email_id=row.id, kind=f"{channel.lower()}_{status}", source_id=source.id,
                                   user_id=owner, detail=evidence[:300], observed_at=stated))
    for raw, kind in ((entry.get("mobile"), "business_mobile"), (entry.get("whatsapp"), "whatsapp"),
                      (entry.get("phone"), None)):
        parsed = _phone(raw, country)
        if not parsed:
            continue
        given, number = parsed
        if entry.get("extension") and kind is None:
            given, kind = f"{given} ext. {entry['extension']}", "office_extension"
        if number and contacts.national(number) in {contacts.national(company.primary_phone)} - {None}:
            stats["phones_company_line_skipped"] += 1  # the company's main line is never the person's number
            continue
        kind = kind or contacts.classify_phone(number or given, company_numbers=set(), context=given)
        existing = db.scalar(select(Phone).where(Phone.person_id == person_id, (
            Phone.normalized_phone == number) if number else (Phone.phone == given)))
        if existing is None:
            existing = Phone(person_id=person_id, company_id=company.id, phone=given[:50], normalized_phone=number,
                             phone_type=kind, confidence=95, source_id=source.id, first_seen_at=stated,
                             last_seen_at=stated, provenance=provenance, owner_user_id=owner, visibility=visibility,
                             evidence=evidence)
            db.add(existing)
            stats["phones_added"] += 1
            stats[f"phones_added_{kind}"] += 1
            stats["phones_without_country_code"] += number is None
        else:
            stats["phones_already_known"] += 1
            if source.id not in set(db.scalars(select(ContactEvidence.source_id).where(
                    ContactEvidence.phone_id == existing.id))):
                stats["phones_corroborated"] += 1
        db.flush()
        if not db.scalar(select(ContactEvidence.id).where(ContactEvidence.phone_id == existing.id,
                                                          ContactEvidence.source_id == source.id)):
            db.add(ContactEvidence(phone_id=existing.id, kind=channel.lower(), source_id=source.id, user_id=owner,
                                   detail=evidence[:300], observed_at=stated))


# ---- connectors ------------------------------------------------------------------------------------------------------


class BusinessContactConnector:
    """A source of explicitly authorized business-contact intelligence (a CRM, a mail / calendar account a user
    connected on purpose). Connector-neutral: an implementation only returns plain entries / events; LeadFinder's
    rules (resolution, provenance, visibility, feedback) stay here. None is configured: no credentials exist yet."""

    channel_contacts = "CONTRIBUTED_BUSINESS_CONTACT"

    def business_contacts(self) -> list[dict]:  # CRM / address-book business contacts the user authorized
        return []

    def meeting_participants(self) -> list[dict]:  # {person, email, company / website, last_seen (meeting date)}
        return []

    def signatures(self) -> list[str]:  # signature blocks of business e-mails the user chose to share
        return []

    def delivery_events(self) -> list[dict]:  # {event: delivered / hard_bounce / soft_bounce / replied, email, event_key}
        return []


def sync(db: Session, connector: BusinessContactConnector, user: User, *, visibility: str = "managers",
         apply: bool = False) -> dict:
    """One connector's authorized data through the same pipeline (dry run unless apply) and its mail events through
    the feedback rules (applied once per event key; only when apply)."""
    from app.services import contact_feedback

    report = {
        "contacts": contribute(db, connector.business_contacts(), channel=connector.channel_contacts,
                               contributor_id=user.id, visibility=visibility, apply=apply, label="connector"),
        "meetings": contribute(db, connector.meeting_participants(), channel="MEETING_CONTACT",
                               contributor_id=user.id, visibility=visibility, apply=apply, label="connector"),
        "signatures": contribute(db, [e for e in map(parse_signature, connector.signatures()) if e],
                                 channel="EMAIL_SIGNATURE", contributor_id=user.id, visibility=visibility, apply=apply,
                                 label="connector"),
    }
    events = connector.delivery_events()
    report["events_applied"] = sum(contact_feedback.record_email_event(
        db, user, e["email"], e["event"], event_key=e.get("event_key")) for e in events) if apply else 0
    report["events_received"] = len(events)
    return report


# ---- removal ---------------------------------------------------------------------------------------------------------


def suppress(db: Session, source_id: int, *, user_id: int | None, reason: str) -> dict:
    """Remove one contributed / internal source's contribution (a correction, a deletion request, a retention
    rule): its evidence goes; a contact or role known ONLY from it goes; anything another source also states (public
    evidence included) stays. The source is kept, marked suppressed, and never imported again."""
    source = db.get(Source, source_id)
    channels = {t for t, _, _ in CHANNELS.values()}
    if source is None or source.source_type not in channels:
        raise ValueError("not a contributed / internal source")
    removed = Counter()
    for model, column in ((Email, ContactEvidence.email_id), (Phone, ContactEvidence.phone_id)):
        ids = set(db.scalars(select(column).where(ContactEvidence.source_id == source_id, column.is_not(None))))
        for row in db.scalars(select(model).where(model.id.in_(ids or {0}))).all():
            others = set(db.scalars(select(ContactEvidence.source_id).where(column == row.id))) - {source_id}
            if not others and row.provenance in ("internal_crm", "contributed", "human_confirmed"):
                db.delete(row)
                removed[f"{model.__tablename__}_removed"] += 1
            else:
                for ev in db.scalars(select(ContactEvidence).where(column == row.id,
                                                                   ContactEvidence.source_id == source_id)):
                    db.delete(ev)
                removed[f"{model.__tablename__}_kept_other_evidence"] += 1
    for role in db.scalars(select(CompanyPerson).join(Evidence, Evidence.company_person_id == CompanyPerson.id)
                           .where(Evidence.source_id == source_id).distinct()).all():
        sources = set(db.scalars(select(Evidence.source_id).where(Evidence.company_person_id == role.id)))
        if sources == {source_id}:
            db.delete(role)
            removed["roles_removed"] += 1
        else:
            for ev in db.scalars(select(Evidence).where(Evidence.company_person_id == role.id,
                                                        Evidence.source_id == source_id)):
                db.delete(ev)
            removed["roles_kept_other_evidence"] += 1
    source.metadata_ = {**(source.metadata_ or {}), "suppressed": True, "suppressed_reason": reason[:300],
                        "suppressed_at": datetime.now(timezone.utc).isoformat()}
    audit_service.record(db, action="contribution.suppressed", user_id=user_id, entity_type="source",
                         entity_id=source_id, metadata={"reason": reason, **removed})
    db.commit()
    return dict(removed)


if __name__ == "__main__":
    import argparse
    import json

    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("channel", choices=SYSTEMS)
    parser.add_argument("--owner", help="the e-mail of the LeadFinder user contributing / owning these contacts")
    parser.add_argument("--visibility", choices=VISIBILITIES, default="organization")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args()
    with SessionLocal() as session, open(args.file, "rb") as f:
        owner_id = session.scalar(select(User.id).where(User.email == args.owner)) if args.owner else None
        print(json.dumps(ingest(session, system=args.channel, file_name=args.file, raw=f.read(),
                                owner_user_id=owner_id, visibility=args.visibility, apply=args.apply),
                         ensure_ascii=False, indent=1, default=str))
