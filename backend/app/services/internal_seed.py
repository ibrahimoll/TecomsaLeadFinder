"""TECOMSA internal contact seeds (Step 6.1): an authorized export (Odoo CRM contacts, customers, historical leads,
meeting participants, business-card exports) -> people + their business contacts in LeadFinder, with TECOMSA's
provenance (source type internal_seed, source system, source record id, owner) and record-level visibility.

    company   the row's website / e-mail domain = a LeadFinder company's verified domain, else the exact
              normalised name (legal forms, Arabic / French equivalents folded) of exactly one company;
              never created, never matched on a fuzzy name: unmatched rows are reported
    person    the Step 5 resolution (no duplicate person; a same-name person in another role is flagged)
    contacts  provenance internal_crm (research never overwrites or deletes it), status published, the phone
              classified (business mobile / direct / WhatsApp / extension); restricted rows are shown only to
              their owner and to managers / admins
"""

import logging
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyDomain, Email, Phone, Source
from app.services import contact_intelligence as contacts
from app.services.normalization import normalize_domain, normalize_phone
from app.services.people import persistence
from app.services.people.external import generic
from app.services.people.external.lebanon.records import candidate, org_key
from app.services.people.resolution import resolve

logger = logging.getLogger("leadfinder.internal_seed")
SEED_COLUMNS = {**generic.DEFAULT_COLUMNS,
                "record_id": r"^(?:id|record id|external id|contact id|partner id|reference|ref)\b"}


def _rows(name: str, raw: bytes) -> list[list]:
    if name.lower().endswith((".xlsx", ".xls")):
        return generic.xlsx_rows(raw)
    return generic.csv_rows(raw.decode("utf-8-sig", "replace"))


def _company_index(db: Session) -> tuple[dict[str, int], dict[str, set[int]]]:
    domains = {d: cid for cid, d in db.execute(select(Company.id, Company.domain).where(Company.domain.is_not(None)))}
    domains |= {d: cid for cid, d in db.execute(select(CompanyDomain.company_id, CompanyDomain.domain))}
    names: dict[str, set[int]] = {}
    for cid, name, legal in db.execute(select(Company.id, Company.name, Company.legal_name)):
        for n in (name, legal):
            if n and (key := org_key(n)):
                names.setdefault(key, set()).add(cid)
    return {normalize_domain(d) or d: cid for d, cid in domains.items()}, names


def ingest(db: Session, *, system: str, file_name: str, raw: bytes, owner_user_id: int | None = None,
           restricted: bool = False) -> dict:
    """One authorized internal file -> LeadFinder people / contacts. Re-ingesting the same file changes nothing."""
    now = datetime.now(timezone.utc)
    rows = [[generic._clean(c) for c in r] for r in _rows(file_name, raw)]
    header_at = next((i for i, r in enumerate(rows[:10]) if {"company", "person"} <= set(
        generic.header_map(r, SEED_COLUMNS))), None)
    if header_at is None:
        raise ValueError("no header row with a company and a person column")
    mapping = generic.header_map(rows[header_at], SEED_COLUMNS)
    by_domain, by_name = _company_index(db)
    stats: Counter = Counter()
    unmatched: list[str] = []
    company_ids: set[int] = set()
    for row in rows[header_at + 1:]:
        entry = {f: row[i] for f, i in mapping.items() if i < len(row) and row[i]}
        stats["rows"] += 1
        records = generic.entry_records(entry, excerpt=f"{system}: " + " | ".join(c for c in row if c))
        record = next((r for r in records if r.person), None)
        if record is None:
            stats["rows_without_person_and_title"] += 1
            continue
        email_domain = (record.email or "").rpartition("@")[2]
        domain = (record.domains[:1] or [None])[0] or (email_domain if email_domain not in contacts.FREE_MAIL else None)
        company_id = by_domain.get(normalize_domain(domain or "") or "")
        if company_id is None:
            ids = by_name.get(org_key(record.org[0]), set())
            company_id = next(iter(ids)) if len(ids) == 1 else None
        if company_id is None:
            stats["unmatched_company"] += 1
            if len(unmatched) < 50:
                unmatched.append(record.org[0])
            continue
        company = db.get(Company, company_id)
        record_id = entry.get("record_id") or f"{record.org[0]}|{record.person}"
        source = db.scalar(select(Source).where(Source.source_type == "internal_seed", Source.publisher == system,
                                                Source.external_reference == record_id[:300]))
        if source is None:
            source = Source(source_type="internal_seed", name=f"TECOMSA {system}", publisher=system,
                            external_reference=record_id[:300], retrieved_at=now, source_quality=95,
                            metadata_={"file": file_name, "owner_user_id": owner_user_id, "restricted": restricted})
            db.add(source)
            db.flush()
        c = candidate(record, company_id=company_id, source_id=source.id, url=None, source_type="internal",
                      quality=95, match_confidence=95, stated=now, category="internal_seed", document=file_name)
        if c is None:
            stats["rejected_not_person_or_title"] += 1
            continue
        email, phone, context = c.email, c.phone, c.raw_metadata.get("context") or ""
        c.email = c.phone = None  # stored below as TECOMSA CRM contacts (never as public ones)
        match = resolve(db, company_id, c)
        role = persistence.save(db, company, c, match, now)
        role.owner_user_id, role.restricted = owner_user_id, restricted
        stats["people_new" if match.person is None else "people_matched"] += 1
        if email and not db.scalar(select(Email.id).where(Email.person_id == role.person_id, Email.email == email)):
            db.add(Email(person_id=role.person_id, company_id=company_id, email=email, email_type="work",
                         status="published", confidence=95, source_id=source.id, first_seen_at=now, last_seen_at=now,
                         provenance="internal_crm", owner_user_id=owner_user_id, restricted=restricted,
                         evidence=f"TECOMSA {system} record {record_id}"[:500]))
            stats["emails"] += 1
        number = normalize_phone(phone, company.headquarters_country) if phone else None
        if number and not db.scalar(select(Phone.id).where(Phone.person_id == role.person_id,
                                                           Phone.normalized_phone == number)):
            db.add(Phone(person_id=role.person_id, company_id=company_id, phone=phone, normalized_phone=number,
                         phone_type=contacts.classify_phone(number, company_numbers=set(), context=context),
                         confidence=95, source_id=source.id, first_seen_at=now, last_seen_at=now,
                         provenance="internal_crm", owner_user_id=owner_user_id, restricted=restricted,
                         evidence=f"TECOMSA {system} record {record_id}"[:500]))
            stats["phones"] += 1
        db.flush()
        persistence.recompute(db, company)
        db.commit()
        company_ids.add(company_id)
    logger.info("internal seed %s %s: %s", system, file_name, dict(stats))
    return {**dict(stats), "companies": len(company_ids), "unmatched_examples": unmatched}


def ingest_path(db: Session, path: str, **kw) -> dict:
    with open(path, "rb") as f:
        return ingest(db, file_name=path, raw=f.read(), **kw)


if __name__ == "__main__":  # python -m app.services.internal_seed FILE SYSTEM [OWNER_USER_ID] [--restricted]
    import json
    import sys

    from app.db.session import SessionLocal

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    with SessionLocal() as session:
        print(json.dumps(ingest_path(session, args[0], system=args[1],
                                     owner_user_id=int(args[2]) if len(args) > 2 else None,
                                     restricted="--restricted" in sys.argv), ensure_ascii=False))
