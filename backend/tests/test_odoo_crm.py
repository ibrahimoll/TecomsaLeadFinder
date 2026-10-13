"""Add to Odoo: a CRM lead per selected company (title, company, country, website, e-mail, phone, tags) with a
scheduled call for the user's Odoo salesperson; existing leads are never duplicated; each creation is audited."""

from datetime import date

from sqlalchemy import select

from app.models import AuditLog, Company, Phone
from app.models.enums import UserRole
from app.services import odoo_crm


class FakeOdoo:
    uid = 2

    def __init__(self, existing=()):
        self.created: list[tuple[str, dict]] = []
        self.existing = set(existing)
        self.tags = {"Hot": 7}

    def call(self, model, method, *args, **kwargs):
        domain = args[0] if args else []
        if method == "create":
            self.created.append((model, args[0]))
            return 100 + len(self.created)
        if model == "crm.tag" and method == "search":
            return [self.tags[c[2]] for c in domain if isinstance(c, tuple) and c[2] in self.tags]
        if model == "crm.lead" and method == "search":
            names = {c[2] for c in domain if isinstance(c, tuple) and c[0] == "partner_name"}
            return [55] if names & self.existing else []
        if model == "ir.model.data":
            return [{"res_id": 4}]  # mail.mail_activity_data_call
        if model == "ir.model":
            return [300]
        if model == "res.country":
            return [119]  # Lebanon
        return []


def test_selected_companies_become_leads_with_a_scheduled_call(db, make_user):
    user = make_user(UserRole.SALES_AGENT)
    user.odoo_user_id = 9
    acme = Company(name="Acme Foods", normalized_name="acme foods", website="https://acme.example",
                   headquarters_country="Lebanon", primary_email="info@acme.example", owner_user_id=user.id)
    known = Company(name="Known Co", normalized_name="known co", owner_user_id=user.id)
    db.add_all([acme, known])
    db.flush()
    db.add(Phone(company_id=acme.id, phone="+961 1 234 567", phone_type="landline"))
    db.commit()
    odoo = FakeOdoo(existing={"Known Co"})

    results = odoo_crm.add_leads(db, user, [acme, known], tags=["Hot", "Odoo", "Hot"], call_on=date(2030, 1, 2),
                                 title="Odoo – {company}", odoo=odoo)

    assert [r["status"] for r in results] == ["created", "exists"]  # Known Co is already in Odoo: not duplicated
    assert ("crm.tag", {"name": "Odoo"}) in odoo.created  # a new tag is created once; 'Hot' already exists
    lead = next(v for m, v in odoo.created if m == "crm.lead")
    assert lead["name"] == "Odoo – Acme Foods" and lead["partner_name"] == "Acme Foods"
    assert (lead["country_id"], lead["website"], lead["email_from"], lead["phone"]) == (
        119, "https://acme.example", "info@acme.example", "+961 1 234 567")
    assert lead["user_id"] == 9 and lead["tag_ids"] == [(6, 0, [7, 101])]  # the user's Odoo salesperson
    call = next(v for m, v in odoo.created if m == "mail.activity")
    assert (call["date_deadline"], call["activity_type_id"], call["user_id"], call["res_model_id"]) == (
        "2030-01-02", 4, 9, 300)
    audit = db.scalar(select(AuditLog).where(AuditLog.action == odoo_crm.ACTION))
    assert audit.entity_id == str(acme.id) or audit.entity_id == acme.id
