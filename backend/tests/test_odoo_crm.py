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


class SyncOdoo:
    uid = 2

    def __init__(self, leads):
        self.leads = leads

    def call(self, model, method, *args, **kwargs):
        if model == "crm.stage":
            return [4]  # the "Won" stage
        if model == "crm.tag":
            return [{"id": 1, "name": "Odoo ERP"}, {"id": 2, "name": "Hot"}]
        if model == "crm.lead" and method == "search_read":
            return self.leads
        return []


def test_won_and_lost_deals_in_odoo_set_the_sales_status_once(db):
    from app.models import CompanyStatusHistory

    won = Company(name="Acme Foods", normalized_name="acme foods", odoo_lead_id=11)
    lost = Company(name="Beta Trading", normalized_name="beta trading", domain="beta.example")
    manual = Company(name="Gamma Hotel", normalized_name="gamma hotel", status="qualified")
    db.add_all([won, lost, manual])
    db.commit()
    leads = [
        {"id": 11, "partner_name": "Acme Foods", "website": False, "stage_id": [4, "Won"], "active": True,
         "tag_ids": [1, 2]},
        {"id": 12, "partner_name": "Beta Co", "website": "https://www.beta.example/", "stage_id": [2, "Proposition"],
         "active": False, "tag_ids": []},  # lost; matched by its website, not its name
        {"id": 13, "partner_name": "Gamma Hotel S.A.L.", "website": False, "stage_id": [1, "New"], "active": True,
         "tag_ids": []},  # open lead on a company someone already qualified by hand
        {"id": 14, "partner_name": "Nobody Known", "website": False, "stage_id": [1, "New"], "active": True,
         "tag_ids": []},
    ]
    stats = odoo_crm.sync(db, odoo=SyncOdoo(leads))
    assert stats == {"leads": 4, "matched": 3, "status_changed": 2}
    db.refresh(won), db.refresh(lost), db.refresh(manual)
    assert (won.status, won.odoo_outcome, won.odoo_stage) == ("working_odoo", "won", "Won")  # tag 'Odoo ERP'
    assert (lost.status, lost.odoo_lead_id, lost.odoo_outcome) == ("not_interested", 12, "lost")
    assert (manual.status, manual.odoo_lead_id, manual.odoo_outcome) == ("qualified", 13, "open")  # not downgraded
    assert db.scalar(select(CompanyStatusHistory.reason).where(CompanyStatusHistory.company_id == won.id)) == \
        "From Odoo: Won"
    won.status = "follow_up"  # a salesperson changes it afterwards: the next sync leaves it (same outcome)
    db.commit()
    assert odoo_crm.sync(db, odoo=SyncOdoo(leads))["status_changed"] == 0
