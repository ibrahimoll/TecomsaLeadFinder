from collections import defaultdict
from typing import Any

from sqlalchemy import delete, exists, func, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from sqlalchemy.dialects.postgresql import insert

from app.services.permissions import is_privileged
from app.models import (Company, CompanyIdentifier, CompanyLocation, CompanyOffering, CompanyPerson, CompanyRelationship,
                        CompanySignal,
                        CompanyStatusHistory, DiscoverySuppression, Email, Evidence, OpportunityAnalysis, Person,
                        Phone, Source, User)
from app.models.enums import SIGNAL_GROUPS, CompanyStatus
from app.schemas.company import CompanyCreate, CompanyStatusUpdate, CompanyUpdate
from app.services import audit_service
from app.services.audit_service import AuditAction
from app.services.normalization import company_domain, normalize_company_name
from app.services.pagination import PageParams, paginate


def _normalized_name(name: str) -> str:
    return normalize_company_name(name) or name.strip().lower()


def _resolve_domain(values: dict[str, Any]) -> None:
    """An explicit domain is normalized; otherwise a new website sets the domain. Mutates `values`."""
    if values.get("domain") is not None:
        values["domain"] = company_domain(values["domain"])
        if values["domain"] is None:
            raise BusinessRuleError("Domain must be the company's own website domain (e.g. example.com)")
    elif "website" in values and "domain" not in values:
        values["domain"] = company_domain(values["website"])  # None for social / maps hosts


def _check_domain_free(db: Session, domain: str | None, exclude_id: int | None = None) -> None:
    if domain is None:
        return
    stmt = select(Company.id, Company.name).where(Company.domain == domain)
    if exclude_id is not None:
        stmt = stmt.where(Company.id != exclude_id)
    if (row := db.execute(stmt).first()) is not None:
        raise ConflictError(f"{row.name} (#{row.id}) already uses the domain {domain}")


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:  # a concurrent request took the domain between check and insert
        db.rollback()
        if "uq_companies_domain" in str(exc.orig):
            raise ConflictError("Another company already uses this domain") from None
        raise


def list_companies(
    db: Session,
    params: PageParams,
    *,
    q: str | None = None,
    status: CompanyStatus | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    owner_id: int | None = None,
) -> tuple[list[Company], int]:
    stmt = select(Company)
    if owner_id is not None:
        stmt = stmt.where(Company.owner_user_id == owner_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.normalized_name.ilike(f"%{_normalized_name(q)}%"),
                              Company.legal_name.ilike(like), Company.domain.ilike(like)))
    if status:
        stmt = stmt.where(Company.status == status)
    # Location filters match the headquarters or any other known location of the company.
    for value, hq_column, location_column in ((country, Company.headquarters_country, CompanyLocation.country),
                                              (region, Company.headquarters_region, CompanyLocation.region),
                                              (city, Company.headquarters_city, CompanyLocation.city)):
        if value and value.strip():
            wanted = value.strip().lower()
            stmt = stmt.where(or_(func.lower(hq_column) == wanted, exists().where(
                CompanyLocation.company_id == Company.id, func.lower(location_column) == wanted)))
    if industry and industry.strip():
        stmt = stmt.where(func.lower(Company.industry) == industry.strip().lower())
    return paginate(db, stmt.order_by(Company.name, Company.id), params)


def get_company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise NotFoundError("Company not found")
    return company


def create_company(db: Session, user: User | None, data: CompanyCreate) -> Company:
    values = data.model_dump(exclude_unset=True)
    _resolve_domain(values)
    _check_domain_free(db, values.get("domain"))
    company = Company(**values, normalized_name=_normalized_name(data.name),
                      created_by_user_id=user.id if user else None)
    db.add(company)
    db.flush()
    audit_service.record(db, action=AuditAction.COMPANY_CREATED, user_id=user.id if user else None,
                         entity_type="company", entity_id=company.id, metadata={"name": company.name})
    _commit(db)
    return company


def update_company(db: Session, user: User, company_id: int, data: CompanyUpdate) -> Company:
    company = get_company(db, company_id)
    values = data.model_dump(exclude_unset=True)
    _resolve_domain(values)
    if "domain" in values:
        _check_domain_free(db, values["domain"], exclude_id=company.id)
    changed = {k: {"from": getattr(company, k), "to": v} for k, v in values.items() if getattr(company, k) != v}
    for field in changed:
        setattr(company, field, values[field])
    if "name" in changed:
        company.normalized_name = _normalized_name(company.name)
    if changed:
        audit_service.record(db, action=AuditAction.COMPANY_UPDATED, user_id=user.id, entity_type="company",
                             entity_id=company.id, metadata={"changes": changed})
    _commit(db)
    db.refresh(company)
    return company


def change_status(db: Session, user: User, company_id: int, data: CompanyStatusUpdate) -> Company:
    """Every status change is recorded in company_status_history (same status again: no-op)."""
    company = get_company(db, company_id)
    if company.status == data.status:
        return company
    db.add(CompanyStatusHistory(company_id=company.id, old_status=company.status, new_status=data.status,
                                changed_by_user_id=user.id, reason=data.reason))
    audit_service.record(db, action=AuditAction.COMPANY_STATUS_CHANGED, user_id=user.id, entity_type="company",
                         entity_id=company.id, metadata={"from": company.status, "to": data.status.value})
    company.status, company.status_reason = data.status, data.reason
    db.commit()
    db.refresh(company)
    return company


def delete_company(db: Session, user: User, company_id: int) -> None:
    """Deletes the company and what only describes it (locations, roles, status history, evidence, search
    results, opportunity analyses: ON DELETE CASCADE). People, sources and research runs remain; a person's
    email/phone at this company stays with the person (company_id SET NULL). The company's own email/phone
    rows would be left without an owner, so they are deleted here first.

    The company's source identifiers and domain are kept as discovery suppressions, so the next Find Leads
    search does not silently re-create a company someone deliberately deleted. (To only hide a company,
    set its status to `archived` instead: everything is kept.)"""
    company = get_company(db, company_id)
    keys = db.execute(select(CompanyIdentifier.scheme, CompanyIdentifier.value)
                      .where(CompanyIdentifier.company_id == company.id)).all()
    keys += [("domain", company.domain)] if company.domain else []
    for scheme, value in keys:
        db.execute(insert(DiscoverySuppression).values(scheme=scheme, value=value, company_name=company.name,
                                                       deleted_by_user_id=user.id).on_conflict_do_nothing())
    for model in (Email, Phone):
        db.execute(delete(model).where(model.company_id == company.id, model.person_id.is_(None)))
    audit_service.record(db, action=AuditAction.COMPANY_DELETED, user_id=user.id, entity_type="company",
                         entity_id=company.id, metadata={"name": company.name, "domain": company.domain})
    db.delete(company)
    db.commit()


# ---- read models -------------------------------------------------------------------------------------------


_STATUS_ORDER = {"current": 0, "unknown": 1, "former": 2}


def _key_roles(roles: list[CompanyPerson]) -> set[int]:
    """Per department, the decision-maker shown first: current over unknown (never former), then the title's
    rank (CIO before IT Manager), then confidence, then the newest evidence. The others stay listed."""
    best: dict[str, int] = {}
    for role in sorted(roles, key=lambda r: (_STATUS_ORDER.get(r.employment_status, 1), r.title_rank or 99,
                                             -(r.confidence or 0), -(r.last_seen_at.timestamp() if r.last_seen_at
                                                                     else 0))):
        if role.employment_status != "former" and (role.department or "other") != "other":
            best.setdefault(role.department, role.id)
    return set(best.values())


def company_people(db: Session, company_id: int, user: User | None = None) -> list[dict[str, Any]]:
    """Every role at the company (current and most senior first), each with the person's public emails/phones
    for this company, the sources stating it and whether it is the department's key decision-maker. TECOMSA
    internal / contributed contacts follow their visibility: organization, managers (owner + managers / admins),
    private (owner only)."""
    get_company(db, company_id)

    def visible(row) -> bool:
        if row.visibility == "organization" or user is None or row.owner_user_id == user.id:
            return True
        return row.visibility == "managers" and is_privileged(user)  # private: the owner only
    rows = db.execute(
        select(CompanyPerson, Person).join(Person, Person.id == CompanyPerson.person_id)
        .where(CompanyPerson.company_id == company_id)
        .order_by(CompanyPerson.is_current.desc(), CompanyPerson.department.nulls_last(),
                  CompanyPerson.title_rank.nulls_last(), Person.full_name, CompanyPerson.id)
    ).all()
    rows = [(role, person) for role, person in rows if visible(role)]
    key_roles = _key_roles([role for role, _ in rows])
    role_sources: dict[int, list] = defaultdict(list)
    for role_id, source, structured in db.execute(
            select(Evidence.company_person_id, Source, Evidence.structured_value)
            .join(Source, Source.id == Evidence.source_id)
            .where(Evidence.company_id == company_id, Evidence.company_person_id.is_not(None))):
        if all(s["url"] != source.url or not source.url for s in role_sources[role_id]):  # once per page
            role_sources[role_id].append({"id": source.id, "name": source.name, "url": source.url,
                                          "page_type": (source.metadata_ or {}).get("page_type"),
                                          "source_type": source.source_type,
                                          "page": (structured or {}).get("page")})
    person_ids = {person.id for _, person in rows}
    contact: dict[str, dict[int, list]] = {"emails": defaultdict(list), "phones": defaultdict(list)}
    for key, model in (("emails", Email), ("phones", Phone)):
        points = db.scalars(select(model).where(
            model.person_id.in_(person_ids), or_(model.company_id.is_(None), model.company_id == company_id))
            .order_by(model.is_primary.desc(), model.id)).all() if person_ids else []
        for point in points:
            if visible(point):
                contact[key][point.person_id].append(point)
    from app.services.contact_intelligence import USABLE, channels
    from app.models import ContactEvidence

    corroborated = set()  # contact points two or more independent sources state
    for column, kind in ((ContactEvidence.email_id, "email"), (ContactEvidence.phone_id, "phone")):
        ids = [p.id for points in contact[f"{kind}s"].values() for p in points]
        for contact_id, n in db.execute(select(column, func.count(func.distinct(ContactEvidence.source_id)))
                                        .where(column.in_(ids or [0]), ContactEvidence.source_id.is_not(None))
                                        .group_by(column)):
            if n >= 2:
                corroborated.add((kind, contact_id))

    out = []
    for role, person in rows:
        ranked = channels(contact["emails"][person.id], contact["phones"][person.id], frozenset(corroborated))
        out.append({**_columns(role), "person": person, "emails": contact["emails"][person.id],
                    "phones": contact["phones"][person.id], "is_key": role.id in key_roles,
                    "sources": role_sources[role.id], "contacts": ranked,
                    "contactable": any(c["kind"] in USABLE for c in ranked)})
    return out


def correct_person(db: Session, user: User, company_id: int, role_id: int, data) -> dict[str, Any]:
    """A person's correction of a researched role: applied, audited, and protected from later research."""
    role = db.get(CompanyPerson, role_id)
    if role is None or role.company_id != company_id:
        raise NotFoundError("Person not found at this company")
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    before = {field: getattr(role, field) for field in changes}
    for field, value in changes.items():
        setattr(role, field, value.value if hasattr(value, "value") else value)
    if "employment_status" in changes:
        role.is_current = role.employment_status == "current"
    role.corrected_fields = sorted(set(role.corrected_fields or []) | set(changes))
    role.corrected_by_user_id, role.corrected_at = user.id, func.now()
    audit_service.record(db, action=AuditAction.COMPANY_PERSON_CORRECTED, user_id=user.id,
                         entity_type="company_person", entity_id=role.id,
                         metadata={"company_id": company_id, "before": {k: str(v) for k, v in before.items()},
                                   "after": {k: str(getattr(role, k)) for k in changes}})
    db.commit()
    return next(p for p in company_people(db, company_id, user) if p["id"] == role_id)


def company_detail(db: Session, company_id: int) -> dict[str, Any]:
    company = get_company(db, company_id)

    def own(model):  # the company's own contact points, not its people's
        return db.scalars(select(model).where(model.company_id == company_id, model.person_id.is_(None))
                          .order_by(model.is_primary.desc(), model.id)).all()

    from app.services.enrichment.persistence import conflicts

    locations = db.scalars(select(CompanyLocation).where(CompanyLocation.company_id == company_id)
                           .order_by(CompanyLocation.is_headquarters.desc(), CompanyLocation.id)).all()
    signals = [{**_columns(s), "group": _GROUP.get(s.signal_type, "activity")} for s in db.scalars(
        select(CompanySignal).where(CompanySignal.company_id == company_id)
        .order_by(CompanySignal.signal_type, CompanySignal.confidence.desc().nulls_last()))]
    offerings = db.scalars(select(CompanyOffering).where(CompanyOffering.company_id == company_id)
                           .order_by(CompanyOffering.kind, CompanyOffering.confidence.desc().nulls_last(),
                                     CompanyOffering.raw_name)).all()
    relationships = db.scalars(select(CompanyRelationship).where(CompanyRelationship.company_id == company_id)
                               .order_by(CompanyRelationship.relation_type, CompanyRelationship.related_name)).all()
    groups = {r.related_company_id: r.relation_type for r in relationships
              if r.related_company_id and r.relation_type in ("parent", "ultimate_parent")}
    related_group_people = []
    for employer_id, relation in groups.items():
        employer = db.get(Company, employer_id)
        for role, person in db.execute(
                select(CompanyPerson, Person).join(Person, Person.id == CompanyPerson.person_id)
                .where(CompanyPerson.company_id == employer_id, CompanyPerson.employment_status != "former",
                       CompanyPerson.confidence >= 50, CompanyPerson.title_rank.is_not(None))
                .order_by(CompanyPerson.title_rank, Person.full_name).limit(10)):
            related_group_people.append({
                "person_id": person.id, "full_name": person.full_name, "job_title": role.job_title,
                "department": role.department, "employment_status": role.employment_status,
                "employer_id": employer_id, "employer_name": employer.name, "relation_type": relation})
    from app.services.people.orchestrator import research_state

    return {
        "company": company,
        "people_research": research_state(db, company),
        "locations": locations,
        "signals": signals,
        "relationships": relationships,
        "related_group_people": related_group_people,
        "offerings": offerings,
        "conflicts": conflicts(db, company_id),
        "overview": overview(company, signals, offerings, locations),
        "people": company_people(db, company_id),
        "emails": own(Email),
        "phones": own(Phone),
        "opportunities": db.scalars(  # DISTINCT ON (solution): the latest analysis per solution
            select(OpportunityAnalysis).where(OpportunityAnalysis.company_id == company_id)
            .order_by(OpportunityAnalysis.solution, OpportunityAnalysis.generated_at.desc(),
                      OpportunityAnalysis.id.desc())
            .distinct(OpportunityAnalysis.solution)).all(),
        "sources": sources_summary(db, company_id),
    }


_GROUP = {t: group for group, types in SIGNAL_GROUPS.items() for t in types}
_ACTIVITY_WORDS = {"manufacturing": "manufacturing", "distribution": "distribution", "wholesale": "wholesale",
                   "retail": "retail", "exporting": "exports", "importing": "imports", "e_commerce": "online sales",
                   "franchising": "franchising", "private_label": "private-label production",
                   "hospitality": "hospitality", "healthcare": "healthcare", "construction": "construction",
                   "professional_services": "professional services", "project_based": "project work"}


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def overview(company: Company, signals: list[dict], offerings: list, locations: list) -> str | None:
    """A factual summary assembled only from stored, evidence-backed fields: no AI, no adjectives."""
    sentences = []
    place = company.headquarters_city or company.headquarters_country
    if company.industry and place:
        sentences.append(f"{company.name} is a {company.industry.lower()} company based in {place}.")
    activities = list(dict.fromkeys(_ACTIVITY_WORDS[s["signal_type"]] for s in signals
                                    if s["signal_type"] in _ACTIVITY_WORDS and (s["confidence"] or 0) >= 60))
    if activities:
        sentences.append(f"Its website describes {_join(activities[:5])} activity.")
    named = [o.raw_name for o in offerings][:4]
    if named:
        more = len(offerings) - len(named)
        sentences.append(f"Products and services on its website include {_join(named)}"
                         + (f", among {len(offerings)} listed." if more else "."))
    cities = list(dict.fromkeys(loc.city for loc in locations if loc.city))
    if len(locations) >= 2:
        sentences.append(f"LeadFinder has {len(locations)} locations on record" +
                         (f", in {_join(cities[:4])}." if cities else "."))
    return " ".join(sentences) or None


def sources_summary(db: Session, company_id: int) -> list[dict[str, Any]]:
    """Every source cited by the company's evidence, locations, contact points or roles."""
    cited = union_all(
        select(Evidence.source_id.label("source_id")).where(Evidence.company_id == company_id),
        select(CompanyLocation.source_id).where(CompanyLocation.company_id == company_id),
        select(Email.source_id).where(Email.company_id == company_id),
        select(Phone.source_id).where(Phone.company_id == company_id),
        select(CompanyPerson.primary_source_id).where(CompanyPerson.company_id == company_id),
    ).subquery()
    counts = (select(Evidence.source_id, func.count().label("n")).where(Evidence.company_id == company_id)
              .group_by(Evidence.source_id).subquery())
    rows = db.execute(
        select(Source, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.source_id == Source.id)
        .where(Source.id.in_(select(cited.c.source_id)))  # IN ignores the NULLs
        .order_by(Source.retrieved_at.desc().nulls_last(), Source.id)
    ).all()
    facts: dict[int, list[str]] = defaultdict(list)
    for source_id, field in db.execute(select(Evidence.source_id, Evidence.field_name).distinct()
                                       .where(Evidence.company_id == company_id, Evidence.field_name.is_not(None))
                                       .order_by(Evidence.field_name)):
        facts[source_id].append(field)
    return [{**_columns(source), "evidence_count": n, "facts": facts[source.id],
             "page_type": (source.metadata_ or {}).get("page_type") if source.source_type == "company_website"
             else None} for source, n in rows]


def _columns(row: Any) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__mapper__.column_attrs}


EXPORT_MAX = 2000  # ponytail: companies per export (company_people per company); page the export if a list grows past it
EXPORT_COLUMNS = ["Company", "Industry", "City", "Website", "Company mobile", "Company phone", "Company email",
                  "Person", "Title", "Department", "Seniority", "Mobile", "Direct line / extension", "Email"]


def export_csv(db: Session, user: User, **filters) -> str:
    """The filtered company list as a CSV a lead generator opens in Excel: one row per current person (the company's
    own numbers repeated), one row for a company without people. Same companies and contact visibility as the app.
    UTF-8 with a BOM, so Excel shows Arabic / accents."""
    import csv
    import io

    from app.services.contact_intelligence import LEBANON_MOBILE, national

    companies, _ = list_companies(db, PageParams(page=1, page_size=EXPORT_MAX), **filters)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EXPORT_COLUMNS)
    for company in companies:
        own_phones = [p.phone for p in db.scalars(select(Phone).where(Phone.company_id == company.id,
                                                                      Phone.person_id.is_(None)))]
        if company.primary_phone and company.primary_phone not in own_phones:
            own_phones.insert(0, company.primary_phone)
        mobile = [p for p in own_phones if LEBANON_MOBILE.match(national(p) or "")]
        base = [company.name, company.industry or "", company.headquarters_city or "", company.website or "",
                " / ".join(mobile), " / ".join(p for p in own_phones if p not in mobile), company.primary_email or ""]
        people = [p for p in company_people(db, company.id, user) if p["is_current"]]
        for p in people:
            phones = [x for x in p["phones"] if x.status != "invalid"]
            mobiles = [x.phone for x in phones if x.phone_type in ("business_mobile", "whatsapp")]
            direct = [x.phone for x in phones if x.phone_type not in ("business_mobile", "whatsapp", "company_switchboard")]
            emails = [e.email for e in p["emails"] if e.status not in ("invalid", "predicted")]
            writer.writerow(base + [p["person"].full_name, p["job_title"], p["department"] or "", p["seniority"] or "",
                                    " / ".join(mobiles), " / ".join(direct), " / ".join(emails)])
        if not people:
            writer.writerow(base + [""] * 7)
    return "﻿" + out.getvalue()
