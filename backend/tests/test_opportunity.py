"""Opportunity fit (rules): points only from what LeadFinder stores, each with its evidence; nothing known = unknown,
not "no fit"; the people to call follow the solution and the company's size."""

from app.models import Company, Person
from app.services import opportunity


def sig(kind, value=None):
    return {"signal_type": kind, "signal_value": value}


def fit(company, signals, people=()):
    return {f["solution"]: f for f in opportunity.analyse(company, signals, list(people))}


def test_a_growing_factory_fits_odoo_with_reasons_and_pitch():
    c = Company(name="Fictional Foods", industry="Food manufacturing", employee_count_max=200)
    owner, cfo = Person(id=1, full_name="Rana Saad"), Person(id=2, full_name="Karim Aoun")
    people = [{"person": owner, "job_title": "Owner", "department": "executive", "title_rank": 2,
               "employment_status": "current"},
              {"person": cfo, "job_title": "CFO", "department": "finance", "title_rank": 1,
               "employment_status": "current"}]
    odoo = fit(c, [sig("factory"), sig("branches", "3"), sig("active_careers_page")], people)["odoo"]
    assert odoo["fit_level"] == "high" and odoo["points"] == 6  # factory 3 + branches 2 + hiring 1
    assert odoo["reasons"][0]["evidence"] == "factory" and "Manufacturing, Inventory, Quality" in odoo["pitch"]
    assert [p["name"] for p in odoo["people"]] == ["Rana Saad", "Karim Aoun"]  # owner, then finance (200 staff)


def test_frinzo_and_it_from_website_signals():
    c = Company(name="Fictional Clinic", industry="Clinic", instagram_url="https://instagram.com/x")
    f = fit(c, [sig("technology", "Meta Pixel"), sig("customer_support", "WhatsApp"), sig("appointment_booking"),
                sig("email_provider", "Self-hosted e-mail"), sig("email_security", "No DMARC policy")])
    assert f["frinzo"]["fit_level"] == "high"  # consumers 2 + ads 2 + WhatsApp support 2 + bookings 2 + Instagram 1
    assert f["it"]["points"] == 6 and f["it"]["fit_level"] == "high"  # basic host 2 + spoofable 2 + clinic 2
    assert any(r["evidence"] == "No DMARC policy" for r in f["it"]["reasons"])


def test_nothing_known_is_unknown_and_odoo_users_are_flagged():
    assert {f["fit_level"] for f in fit(Company(name="Blank"), []).values()} == {"unknown"}
    researched = fit(Company(name="Quiet"), [sig("email_provider", "Google Workspace")])
    assert researched["odoo"]["fit_level"] == "low"  # we looked and saw nothing: low, not unknown
    user = fit(Company(name="User", industry="Trading"), [sig("technology", "Odoo")])["odoo"]
    assert user["note"].startswith("Already uses Odoo")


def test_company_list_has_mobile_fit_filter_sort_and_clean_name_order(db):
    from app.models import CompanySignal, Phone, Source
    from app.services import company_service
    from app.services.pagination import PageParams

    factory = Company(name="( Zeta Mills Sarl)", normalized_name="zeta mills", industry="Manufacturing")
    shop = Company(name="Alpha Shop", normalized_name="alpha shop", industry="Retail")
    site = Source(source_type="company_website", name="Zeta Mills website", url="https://zeta.example")
    db.add_all([factory, shop, site])
    db.flush()
    db.add_all([CompanySignal(company_id=factory.id, signal_type="factory", source_id=site.id),
                CompanySignal(company_id=factory.id, signal_type="branches", signal_value="3", source_id=site.id),
                Phone(company_id=factory.id, phone="+961 03 - 123456", phone_type="unknown"),
                Phone(company_id=shop.id, phone="+961 1 500 600", phone_type="unknown")])
    db.commit()
    page = PageParams(page=1, page_size=10)
    names = [c.name for c in company_service.list_companies(db, page)[0]]
    assert names.index("Alpha Shop") < names.index("( Zeta Mills Sarl)")  # "(" no longer sorts first
    mobile, _ = company_service.list_companies(db, page, has_mobile=True)
    assert [c.name for c in mobile] == ["( Zeta Mills Sarl)"] and mobile[0].mobile_count == 1  # 03 = mobile
    odoo, total = company_service.list_companies(db, page, fit="odoo")
    assert total == 1 and odoo[0].name == "( Zeta Mills Sarl)"  # factory 3 + branches 2: medium
    assert {f["solution"]: f["fit_level"] for f in odoo[0].fit}["odoo"] == "medium"
