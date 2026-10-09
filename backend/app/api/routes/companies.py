from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, ManagerOrAdmin, Pagination
from app.models.enums import CompanyStatus
from app.schemas.common import Page
from app.schemas.company import (CompanyCreate, CompanyDetail, CompanyLookupIn, CompanyLookupOut, CompanyLookupPick,
                                 CompanyOut, CompanyPersonCorrection, CompanyPersonOut, CompanySearchHit,
                                 CompanyStatusUpdate, CompanyUpdate, ContactEventIn, ContactFeedbackIn,
                                 ContributionIn, PersonRemovalIn)
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.services import audit_service, company_search, company_service
from app.services.audit_service import AuditAction
from app.services.enrichment import orchestrator as enrichment
from app.services.people import orchestrator as people
from app.services.pagination import page_response

router = APIRouter(prefix="/companies", tags=["companies"])

Text = Annotated[str | None, Query(max_length=200)]


@router.get("", response_model=Page[CompanyOut])
def list_companies(user: CurrentUser, db: DbSession, params: Pagination, q: Text = None,
                   status: CompanyStatus | None = None, country: Text = None, region: Text = None,
                   city: Text = None, industry: Text = None):
    items, total = company_service.list_companies(db, params, q=q, status=status, country=country, region=region,
                                                  city=city, industry=industry)
    return page_response(items, total, params)


@router.get("/search", response_model=list[CompanySearchHit])
def search_companies(user: CurrentUser, db: DbSession, q: Annotated[str, Query(min_length=2, max_length=200)],
                     country: Text = None, city: Text = None, industry: Text = None,
                     limit: Annotated[int, Query(ge=1, le=10)] = 8):
    """Autocomplete: LeadFinder's own companies matching a name, legal / brand / Arabic / French name, domain or
    URL, best first, each with its match type and confidence. Database only: never a public-source request."""
    return [h.out() for h in company_search.search(db, q, country=country, city=city, industry=industry,
                                                   limit=limit)]


@router.post("/lookup", response_model=CompanyLookupOut)
def lookup_company(payload: CompanyLookupIn, user: CurrentUser, db: DbSession):
    """Search for a company (the explicit Search): LeadFinder's database first; when nothing strong is known, the
    permitted public sources (bounded, about 20 s at most). One strong company: found (opened, its research
    queued when stale) or created from source evidence; several: ambiguous (pick one); else not_found."""
    return company_search.lookup(db, payload.q, user_id=user.id, country=payload.country, city=payload.city,
                                 industry=payload.industry)


@router.post("/lookup/{lookup_id}/select", response_model=CompanyLookupOut)
def select_lookup_candidate(lookup_id: int, payload: CompanyLookupPick, user: CurrentUser, db: DbSession):
    """The user's pick among an ambiguous lookup's public-source candidates: created (or reused) and researched."""
    try:
        return company_search.select_candidate(db, lookup_id, payload.index, user_id=user.id)
    except LookupError:
        raise NotFoundError("This search result is no longer available. Search again.") from None


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, user: CurrentUser, db: DbSession):
    return company_service.create_company(db, user, payload)


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: int, user: CurrentUser, db: DbSession):
    """The company with everything known about it. Opening a company whose research (company or people) is
    missing or stale queues it first in line (never waits for it): the page fills in as research progresses."""
    people.request_research(db, company_service.get_company(db, company_id), enrichment.OPENED, user_id=user.id)
    db.commit()
    return company_service.company_detail(db, company_id)


@router.post("/{company_id}/refresh", response_model=CompanyOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_research(company_id: int, user: CurrentUser, db: DbSession):
    """Refresh Research: research the company's website again now (pages are re-fetched; unchanged pages add
    nothing). Returns at once with enrichment_status `queued` / `researching`."""
    company = company_service.get_company(db, company_id)
    if not company.website:
        raise BusinessRuleError("LeadFinder has no website for this company yet, so there is nothing to research.")
    enrichment.request(db, company, enrichment.OPENED, force=company.enrichment_status != "researching",
                       user_id=user.id)
    audit_service.record(db, action=AuditAction.COMPANY_RESEARCH_REQUESTED, user_id=user.id, entity_type="company",
                         entity_id=company.id)
    db.commit()
    db.refresh(company)
    return company


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, payload: CompanyUpdate, user: CurrentUser, db: DbSession):
    return company_service.update_company(db, user, company_id, payload)


@router.patch("/{company_id}/status", response_model=CompanyOut)
def change_status(company_id: int, payload: CompanyStatusUpdate, user: CurrentUser, db: DbSession):
    return company_service.change_status(db, user, company_id, payload)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(company_id: int, user: ManagerOrAdmin, db: DbSession) -> Response:
    company_service.delete_company(db, user, company_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{company_id}/people", response_model=list[CompanyPersonOut])
def company_people(company_id: int, user: CurrentUser, db: DbSession):
    """The company's people, key decision-maker per department marked; queues people discovery if due."""
    people.request_research(db, company_service.get_company(db, company_id), enrichment.OPENED, user_id=user.id)
    db.commit()
    return company_service.company_people(db, company_id, user)


@router.post("/{company_id}/contact-feedback", status_code=status.HTTP_201_CREATED)
def contact_feedback(company_id: int, payload: ContactFeedbackIn, user: CurrentUser, db: DbSession) -> dict:
    """What real sales activity showed (e-mail delivered / bounced / replied, number confirmed / wrong, person
    left...): applied to the contact graph at once and kept as an event."""
    from app.services import contact_feedback as feedback

    row, applied = feedback.record_feedback(db, user, company_id, **payload.model_dump())
    return {"id": row.id, "event": row.event, "effect": row.effect, "applied": applied}


@router.post("/{company_id}/contributions", status_code=status.HTTP_201_CREATED)
def contribute(company_id: int, payload: ContributionIn, user: CurrentUser, db: DbSession) -> dict:
    """A business contact the user explicitly contributes to this company (attributed to them, with its
    visibility). Resolved like every contribution: the same e-mail is the same person, a person without a title is
    only attached when already known, a colleague-confirmed title is never overwritten."""
    from app.services import contributions

    company_service.get_company(db, company_id)
    entry = {k: v for k, v in payload.model_dump(exclude={"channel", "signature", "visibility"}).items() if v}
    if payload.signature:
        entry = {**(contributions.parse_signature(payload.signature) or {}), **entry}
    try:
        report = contributions.contribute(db, [entry], channel=payload.channel, contributor_id=user.id,
                                          visibility=payload.visibility, apply=True, company_id=company_id,
                                          label="added on the company page")
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc
    if not report.get("unique_people"):
        raise BusinessRuleError((report.get("review") or [{}])[0].get("reason") or "Nothing could be added")
    return {k: v for k, v in report.items() if k != "review"}


@router.post("/contact-events", status_code=status.HTTP_201_CREATED)
def contact_event(payload: ContactEventIn, user: CurrentUser, db: DbSession) -> dict:
    """A delivery / bounce / reply notification for an e-mail address (e.g. from the mail system): applied once per
    event_key to every LeadFinder record of that address."""
    from app.services import contact_feedback as feedback

    return {"applied": feedback.record_email_event(db, user, payload.email, payload.event, event_key=payload.event_key)}


@router.patch("/{company_id}/people/{role_id}", response_model=CompanyPersonOut)
def correct_person(company_id: int, role_id: int, payload: CompanyPersonCorrection, user: CurrentUser,
                   db: DbSession):
    """Correct a researched role (title, department, seniority, current / former). Research never changes a
    corrected field again; the change is audited."""
    return company_service.correct_person(db, user, company_id, role_id, payload)


@router.post("/{company_id}/people/{person_id}/remove")
def remove_person(company_id: int, person_id: int, payload: PersonRemovalIn, user: ManagerOrAdmin, db: DbSession):
    """Delete a person on request (privacy): their roles, emails, phones and evidence go, and research or imports
    never add them at this company again. Irreversible; audited without the name."""
    from app.services import privacy

    return privacy.forget_person(db, user, company_id, person_id, payload.reason)
