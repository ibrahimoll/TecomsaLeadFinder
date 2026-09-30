"""TECOMSA relationship status: is this company already known in Odoo?

Evidence for a company is every imported Odoo record that is linked to it OR shares a
strong/medium identity signal with it (Odoo partner id, website/email domain, phone,
normalised name). Matching on signals, not only on the import link, means duplicate
company records are protected together.

Precedence (first match wins):
  CUSTOMER > EXISTING_OPPORTUNITY > EXISTING_LEAD > LOST_OPPORTUNITY > EXISTING_CONTACT > AVAILABLE
NOT_CHECKED is used while no Odoo import has completed: without Odoo data LeadFinder
cannot honestly call a company available.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models import Company, CrmLead, ImportRun, OdooContact, OdooMatch
from app.models.enums import CrmLeadType, ImportStatus, OdooMatchStatus


@dataclass
class Evidence:
    leads: list[CrmLead] = field(default_factory=list)
    contacts: list[OdooContact] = field(default_factory=list)


@dataclass
class Decision:
    status: OdooMatchStatus
    reason: str
    salesperson_id: int | None = None
    odoo_partner_id: int | None = None
    odoo_lead_id: int | None = None


class _Index:
    """In-memory lookup of Odoo records by every matching signal."""

    def __init__(self, leads: Iterable[CrmLead], contacts: Iterable[OdooContact]):
        self.by_key: dict[tuple[str, object], list[object]] = defaultdict(list)
        for lead in leads:
            for key in (("company", lead.company_id), ("name", lead.company_key), ("domain", lead.domain),
                        ("domain", lead.email_domain), ("phone", lead.phone_normalized)):
                if key[1]:
                    self.by_key[key].append(lead)
        for contact in contacts:
            for key in (("company", contact.company_id), ("partner", contact.odoo_contact_id),
                        ("name", contact.company_key), ("domain", contact.domain),
                        ("domain", contact.email_domain), ("phone", contact.phone_normalized)):
                if key[1]:
                    self.by_key[key].append(contact)

    def evidence(self, company: Company) -> Evidence:
        keys = [("company", company.id), ("partner", company.odoo_contact_id), ("name", company.normalized_name),
                ("domain", company.domain), ("domain", company.email_domain),
                ("phone", company.main_phone_normalized)]
        seen: dict[int, object] = {}
        for key in keys:
            if key[1]:
                for record in self.by_key.get(key, ()):
                    seen[id(record)] = record
        ev = Evidence()
        for record in seen.values():
            (ev.leads if isinstance(record, CrmLead) else ev.contacts).append(record)
        ev.leads.sort(key=lambda r: (r.updated_date or r.created_date or r.imported_at), reverse=True)
        return ev


def _owner(lead: CrmLead) -> str:
    return f", owned by {lead.salesperson_name}" if lead.salesperson_name else ""


def decide(evidence: Evidence, has_odoo_data: bool) -> Decision:
    leads, contacts = evidence.leads, evidence.contacts
    others = len(leads) - 1
    more = f" (+{others} other CRM record{'s' if others != 1 else ''})" if others > 0 else ""

    won = next((lead for lead in leads if lead.is_won), None)
    if won:
        return Decision(OdooMatchStatus.CUSTOMER,
                        f"Won opportunity '{won.opportunity_name}' ({won.stage or 'won'}){_owner(won)}.{more}",
                        won.salesperson_id, odoo_lead_id=won.odoo_lead_id)
    customer = next((c for c in contacts if c.is_customer), None)
    if customer:
        return Decision(OdooMatchStatus.CUSTOMER, f"Marked as a customer in Odoo contact '{customer.contact_name}'.",
                        customer.salesperson_id, odoo_partner_id=customer.odoo_contact_id)
    for lead_type, status in ((CrmLeadType.OPPORTUNITY, OdooMatchStatus.EXISTING_OPPORTUNITY),
                              (CrmLeadType.LEAD, OdooMatchStatus.EXISTING_LEAD)):
        lead = next((x for x in leads if x.is_open and x.lead_type == lead_type), None)
        if lead:
            kind = "opportunity" if lead_type == CrmLeadType.OPPORTUNITY else "lead"
            stage = f" in stage {lead.stage}" if lead.stage else ""
            return Decision(status, f"Open {kind} '{lead.opportunity_name}'{stage}{_owner(lead)}.{more}",
                            lead.salesperson_id, odoo_lead_id=lead.odoo_lead_id)
    lost = next((lead for lead in leads if lead.is_lost), None)
    if lost:
        why = lost.lost_reason or "archived"
        return Decision(OdooMatchStatus.LOST_OPPORTUNITY,
                        f"Lost opportunity '{lost.opportunity_name}' ({why}){_owner(lost)}.{more}",
                        lost.salesperson_id, odoo_lead_id=lost.odoo_lead_id)
    if contacts:
        contact = next((c for c in contacts if c.is_company), contacts[0])
        ref = f" (#{contact.odoo_contact_id})" if contact.odoo_contact_id else ""
        sp = next((c.salesperson_id for c in contacts if c.salesperson_id), None)
        return Decision(OdooMatchStatus.EXISTING_CONTACT,
                        f"Exists in Odoo contacts as '{contact.contact_name}'{ref}.", sp,
                        odoo_partner_id=contact.odoo_contact_id)
    if leads:  # e.g. an active record with no usable state; still protect it
        lead = leads[0]
        return Decision(OdooMatchStatus.EXISTING_LEAD, f"CRM record '{lead.opportunity_name}'{_owner(lead)}.",
                        lead.salesperson_id, odoo_lead_id=lead.odoo_lead_id)
    if has_odoo_data:
        return Decision(OdooMatchStatus.AVAILABLE, "No match in imported Odoo contacts or CRM records.")
    return Decision(OdooMatchStatus.NOT_CHECKED, "No Odoo data has been imported yet.")


def has_odoo_data(db: Session) -> bool:
    return bool(db.scalar(select(exists().where(ImportRun.status == ImportStatus.COMPLETED))))


def _apply(db: Session, company: Company, decision: Decision, now: datetime) -> bool:
    """Persist a decision. Returns True when the status changed (a history row is written)."""
    changed = company.crm_status != decision.status or company.crm_status_reason != decision.reason
    company.crm_status = decision.status
    company.crm_status_reason = decision.reason
    company.salesperson_id = decision.salesperson_id
    if decision.status != OdooMatchStatus.NOT_CHECKED:
        company.crm_checked_at = now
    if changed:
        db.add(OdooMatch(
            company_id=company.id,
            match_status=decision.status,
            match_reason=decision.reason,
            odoo_partner_id=decision.odoo_partner_id,
            odoo_lead_id=decision.odoo_lead_id,
            match_confidence=None,
            checked_at=now if decision.status != OdooMatchStatus.NOT_CHECKED else None,
        ))
    return changed


def evidence_for(db: Session, company: Company) -> Evidence:
    """Evidence for one company, fetched with targeted queries."""

    def signal_filter(model):
        conds = [model.company_id == company.id]
        if company.normalized_name:
            conds.append(model.company_key == company.normalized_name)
        if company.domain:
            conds.append(model.email_domain == company.domain)
            if hasattr(model, "domain"):
                conds.append(model.domain == company.domain)
        if company.email_domain:
            conds.append(model.email_domain == company.email_domain)
            if hasattr(model, "domain"):
                conds.append(model.domain == company.email_domain)
        if company.main_phone_normalized:
            conds.append(model.phone_normalized == company.main_phone_normalized)
        if model is OdooContact and company.odoo_contact_id:
            conds.append(model.odoo_contact_id == company.odoo_contact_id)
        return or_(*conds)

    leads = db.scalars(select(CrmLead).where(signal_filter(CrmLead))).all()
    contacts = db.scalars(select(OdooContact).where(signal_filter(OdooContact))).all()
    return _Index(leads, contacts).evidence(company)


def refresh_company(db: Session, company: Company) -> Decision:
    """Recompute one company (after manual create/edit). Caller commits."""
    db.flush()
    decision = decide(evidence_for(db, company), has_odoo_data(db))
    _apply(db, company, decision, datetime.now(timezone.utc))
    return decision


def refresh_all(db: Session) -> int:
    """Recompute every company (after an import). Caller commits. Returns changed count."""
    db.flush()
    index = _Index(db.scalars(select(CrmLead)).all(), db.scalars(select(OdooContact)).all())
    available = has_odoo_data(db)
    now = datetime.now(timezone.utc)
    changed = 0
    for company in db.scalars(select(Company)).all():
        changed += _apply(db, company, decide(index.evidence(company), available), now)
    return changed
