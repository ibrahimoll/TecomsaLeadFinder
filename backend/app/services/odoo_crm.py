"""Add to Odoo: the companies a user selected become CRM leads in TECOMSA's Odoo, each with a scheduled call.

    per company   a crm.lead (an opportunity in the pipeline), created now:
                  name = the title (default: the company name; "{company}" in a custom title is replaced),
                  partner_name, country, website, e-mail, phone (the company's own, never a person's), the tags
                  the user chose (created in Odoo when new), salesperson = the user's linked Odoo user
                  + a "Call" activity on the date the user chose, for that salesperson
    duplicates    a lead with the same company name or website already in Odoo (open or lost): not created again
    audit         every lead created is in LeadFinder's audit log (odoo.lead_created) with its Odoo id

Odoo's external API (XML-RPC, Python standard library), authenticated by login + API key. Nothing is ever read back
or changed in Odoo beyond creating these records and looking up countries, tags, activity types and duplicates.
"""

import logging
import xmlrpc.client
from datetime import date, datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError
from app.models import Company, Email, Phone, User
from app.services import audit_service

logger = logging.getLogger("leadfinder.odoo")
ACTION = "odoo.lead_created"


class Odoo(Protocol):
    uid: int

    def call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any: ...


class _Timeout(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class XmlRpcOdoo:
    """A live connection: login once, then model calls."""

    def __init__(self, url: str, database: str, username: str, api_key: str, timeout: float):
        transport = _Timeout(timeout) if url.startswith("https") else None
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", transport=transport, allow_none=True)
        self._models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", transport=transport, allow_none=True)
        self._db, self._key = database, api_key
        self.uid = common.authenticate(database, username, api_key, {})
        if not self.uid:
            raise BusinessRuleError("Odoo refused the login: check ODOO_USERNAME and ODOO_API_KEY.")

    def call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._models.execute_kw(self._db, self.uid, self._key, model, method, list(args), kwargs)


def configured() -> bool:
    s = get_settings()
    return bool(s.odoo_base_url and s.odoo_database and s.odoo_username and s.odoo_api_key)


def connect() -> Odoo:
    if not configured():
        raise BusinessRuleError("Odoo is not connected yet: an administrator must set ODOO_BASE_URL, ODOO_DATABASE, "
                                "ODOO_USERNAME and ODOO_API_KEY.")
    s = get_settings()
    try:
        return XmlRpcOdoo(s.odoo_base_url.rstrip("/"), s.odoo_database, s.odoo_username,
                          s.odoo_api_key.get_secret_value(), s.odoo_timeout_seconds)
    except (OSError, xmlrpc.client.Error) as exc:
        logger.warning("odoo login failed: %s", exc)
        raise BusinessRuleError("Odoo could not be reached. Check ODOO_BASE_URL and try again.") from exc


def _company_contacts(db: Session, company: Company) -> tuple[str | None, str | None]:
    """The company's own e-mail and phone (its main ones first; never a person's, never one known to be wrong)."""
    email = company.primary_email or db.scalar(select(Email.email).where(
        Email.company_id == company.id, Email.person_id.is_(None), Email.status != "invalid").order_by(Email.id))
    phone = company.primary_phone or db.scalar(select(Phone.phone).where(
        Phone.company_id == company.id, Phone.person_id.is_(None), Phone.status != "invalid").order_by(Phone.id))
    return email, phone


def _one(odoo: Odoo, model: str, domain: list) -> int | None:
    ids = odoo.call(model, "search", domain, limit=1)
    return ids[0] if ids else None


def _tag_ids(odoo: Odoo, names: list[str]) -> list[int]:
    ids = []
    for name in dict.fromkeys(n.strip() for n in names if n.strip()):  # unique, in order
        ids.append(_one(odoo, "crm.tag", [("name", "=ilike", name)]) or odoo.call("crm.tag", "create", {"name": name}))
    return ids


def _call_type(odoo: Odoo) -> int | None:
    """Odoo's built-in "Call" activity type."""
    found = odoo.call("ir.model.data", "search_read", [("module", "=", "mail"), ("name", "=", "mail_activity_data_call")],
                      fields=["res_id"], limit=1)
    return found[0]["res_id"] if found else _one(odoo, "mail.activity.type", [("name", "ilike", "call")])


def add_leads(db: Session, user: User, companies: list[Company], *, tags: list[str], call_on: date,
              title: str | None = None, odoo: Odoo | None = None) -> list[dict]:
    """Creates one lead + call per company. Returns, per company: created (with the Odoo id), exists or failed."""
    odoo = odoo or connect()
    salesperson = user.odoo_user_id or odoo.uid
    tag_ids = _tag_ids(odoo, tags)
    lead_model = _one(odoo, "ir.model", [("model", "=", "crm.lead")])
    call_type = _call_type(odoo)
    results = []
    for company in companies:
        try:
            dupe = [("partner_name", "=ilike", company.name)]
            if company.website:
                dupe = ["|", *dupe, ("website", "=", company.website)]
            existing = odoo.call("crm.lead", "search", ["|", ("active", "=", True), ("active", "=", False), *dupe],
                                 limit=1)
            if existing:
                company.odoo_lead_id = company.odoo_lead_id or existing[0]
                db.commit()
                results.append({"company_id": company.id, "name": company.name, "status": "exists",
                                "lead_id": existing[0]})
                continue
            email, phone = _company_contacts(db, company)
            country = company.headquarters_country and _one(
                odoo, "res.country", [("name", "=ilike", company.headquarters_country)])
            values = {"name": (title or "{company}").replace("{company}", company.name).strip() or company.name,
                      "type": "opportunity", "partner_name": company.name, "user_id": salesperson,
                      "tag_ids": [(6, 0, tag_ids)]}
            values |= {k: v for k, v in (("country_id", country), ("website", company.website), ("email_from", email),
                                         ("phone", phone)) if v}
            lead_id = odoo.call("crm.lead", "create", values)
            if lead_model and call_type:
                odoo.call("mail.activity", "create", {
                    "res_model_id": lead_model, "res_id": lead_id, "activity_type_id": call_type,
                    "date_deadline": call_on.isoformat(), "user_id": salesperson, "summary": f"Call {company.name}"})
            company.odoo_lead_id, company.odoo_outcome, company.odoo_stage = lead_id, "open", None
            company.odoo_synced_at = datetime.now(timezone.utc)
            audit_service.record(db, action=ACTION, user_id=user.id, entity_type="company", entity_id=company.id,
                                 metadata={"odoo_lead_id": lead_id, "call_on": call_on.isoformat(), "tags": tags})
            db.commit()
            results.append({"company_id": company.id, "name": company.name, "status": "created", "lead_id": lead_id})
        except (OSError, xmlrpc.client.Error) as exc:
            logger.warning("odoo lead for company=%s failed: %s", company.id, exc)
            message = exc.faultString.strip().splitlines()[-1] if isinstance(exc, xmlrpc.client.Fault) else str(exc)
            results.append({"company_id": company.id, "name": company.name, "status": "failed",
                            "error": message[:300]})
    return results


# ---- read back (hourly, services/agents/loop.py) -----------------------------------------------------------------
SYNC_LIMIT = 5000  # ponytail: reads every lead each hour; page by write_date when TECOMSA's CRM grows past this
PRODUCT_TAGS = (("frinzo", "working_frinzo"), ("odoo", "working_odoo"), ("it", "working_it"))


def _outcome(lead: dict, won_stages: set[int]) -> str:
    stage = lead["stage_id"][0] if lead.get("stage_id") else None
    if lead.get("active") and stage in won_stages:
        return "won"
    return "open" if lead.get("active") else "lost"


def _won_status(tags: list[str]) -> str:
    words = {w for t in tags for w in t.lower().replace("-", " ").split()}
    return next((status for word, status in PRODUCT_TAGS if word in words), "opportunity")


def sync(db: Session, odoo: Odoo | None = None) -> dict:
    """Odoo's CRM leads -> the LeadFinder companies they are about (by lead id, website domain or exact name): stage
    and outcome kept on the company. When an outcome CHANGES, the company's sales status follows (won -> working on
    the product its tags name, else opportunity; lost -> not interested; a new open lead on a 'new' company ->
    contacted), recorded in its status history 'from Odoo'. A status set by hand afterwards is not overwritten."""
    from app.models import CompanyStatusHistory
    from app.services.normalization import company_domain, normalize_company_name

    odoo = odoo or connect()
    won_stages = set(odoo.call("crm.stage", "search", [("is_won", "=", True)]))
    tag_names = {t["id"]: t["name"] for t in odoo.call("crm.tag", "search_read", [], fields=["name"])}
    leads = odoo.call("crm.lead", "search_read", ["|", ("active", "=", True), ("active", "=", False)],
                      fields=["partner_name", "name", "website", "stage_id", "active", "tag_ids"],
                      order="write_date desc", limit=SYNC_LIMIT)
    by_lead = {c.odoo_lead_id: c for c in db.scalars(select(Company).where(Company.odoo_lead_id.is_not(None)))}
    now, stats = datetime.now(timezone.utc), {"leads": len(leads), "matched": 0, "status_changed": 0}
    for lead in leads:
        company = by_lead.get(lead["id"])
        if company is None and (domain := company_domain(lead.get("website") or None)):
            company = db.scalar(select(Company).where(Company.domain == domain))
        if company is None and (name := lead.get("partner_name") or None):
            company = db.scalar(select(Company).where(Company.normalized_name == normalize_company_name(name))
                                .order_by(Company.id).limit(1))
        if company is None or (company.odoo_lead_id and company.odoo_lead_id != lead["id"]
                               and company.odoo_outcome == "won"):
            continue  # unknown to LeadFinder, or a company already won under another lead: left as it is
        stats["matched"] += 1
        outcome = _outcome(lead, won_stages)
        new_status = None
        if outcome != company.odoo_outcome:
            if outcome == "won":
                new_status = _won_status([tag_names.get(t, "") for t in lead.get("tag_ids") or []])
            elif outcome == "lost":
                new_status = "not_interested"
            elif company.status == "new":
                new_status = "contacted"
        stage = (lead.get("stage_id") or [None, None])[1]
        if new_status and new_status != company.status:
            db.add(CompanyStatusHistory(company_id=company.id, old_status=company.status, new_status=new_status,
                                        changed_by_user_id=None, reason=f"From Odoo: {stage or outcome}"[:500]))
            company.status, company.status_reason = new_status, f"Odoo: {stage or outcome}"
            stats["status_changed"] += 1
        company.odoo_lead_id, company.odoo_stage, company.odoo_outcome = lead["id"], (stage or "")[:80] or None, outcome
        company.odoo_synced_at = now
    db.commit()
    logger.info("odoo sync %s", stats)
    return stats


def lead_url(lead_id: int) -> str | None:
    base = get_settings().odoo_base_url
    return f"{base.rstrip('/')}/web#id={lead_id}&model=crm.lead&view_type=form" if base else None
