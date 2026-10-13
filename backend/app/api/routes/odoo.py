from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError
from app.models import Company
from app.services import odoo_crm
from app.services.permissions import can_see

router = APIRouter(prefix="/odoo", tags=["odoo"])


class AddLeads(BaseModel):
    company_ids: list[int] = Field(min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=10)
    call_on: date
    title: str | None = Field(default=None, max_length=200)  # "{company}" is replaced by each company's name


@router.get("/status")
def status(_: CurrentUser) -> dict:
    # the base URL builds "open in Odoo" links (not a secret)
    return {"configured": odoo_crm.configured(), "url": get_settings().odoo_base_url if odoo_crm.configured() else None}


@router.get("/tags")
def tags(_: CurrentUser) -> list[str]:
    """Odoo's CRM tags, for suggestions (empty when Odoo is not connected)."""
    if not odoo_crm.configured():
        return []
    odoo = odoo_crm.connect()
    return [t["name"] for t in odoo.call("crm.tag", "search_read", [], fields=["name"], order="name", limit=200)]


@router.post("/leads")
def add_leads(body: AddLeads, user: CurrentUser, db: DbSession) -> dict:
    """The selected companies -> Odoo CRM leads with a scheduled call. Only companies the user can see."""
    if body.call_on < date.today():
        raise BusinessRuleError("The call date is in the past.")
    companies = [c for c in db.scalars(select(Company).where(Company.id.in_(body.company_ids))) if can_see(user, c)]
    if not companies:
        raise BusinessRuleError("None of the selected companies can be sent.")
    results = odoo_crm.add_leads(db, user, companies, tags=[t[:60] for t in body.tags], call_on=body.call_on,
                                 title=body.title)
    for r in results:
        if r.get("lead_id"):
            r["url"] = odoo_crm.lead_url(r["lead_id"])
    return {"results": results, "created": sum(r["status"] == "created" for r in results),
            "exists": sum(r["status"] == "exists" for r in results),
            "failed": sum(r["status"] == "failed" for r in results)}
