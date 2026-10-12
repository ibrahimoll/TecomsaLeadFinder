"""A company's own e-mails vs another business's (map data sometimes carries a neighbour's mailbox), and a page on a
listing / menu / link platform never taken as the company's own domain."""

import pytest

from app.models import Company, Email
from app.models.enums import UserRole
from app.services import company_service
from app.services.normalization import company_domain, related_domain


@pytest.mark.parametrize("name,domain,other,related", [
    ("Palms Beach House", None, "sushitsunami.com", False),          # a sushi bar's mailbox on a beach house
    ("Le Cedrus Boutique Hotel", "lecedrus.com", "cedrusbank.com", False),
    ("Iman Schools", "imanschools.edu.lb", "imanschools.com", True),   # the same school, another TLD
    ("Em Sherif SEA Cafe", "emsherif-cafe.com", "emsherifseacafe.com", True),
    ("University of Tripoli", "new.ut.edu.lb", "ut.edu.lb", True),
    ("Lilla Italy", "lillaitalypizzaria.com", "yahoo.fr", True),       # a personal mailbox: nothing to check
    ("Zeta Mills", None, "zetamills.com", True),
])
def test_related_domain(name, domain, other, related):
    assert related_domain(name, domain, other) is related


def test_platform_pages_are_not_company_domains():
    assert company_domain("https://beirut.ml/palmsbeachhouse/") is None
    assert company_domain("https://digitalmenu.applova.io/webstore/x/menu") is None
    assert company_domain("https://crepaway.com/landing/index.php") == "crepaway.com"  # its own site, with a path


def test_company_page_flags_and_export_skips_another_business_mailbox(client_for, db):
    manager, user = client_for(UserRole.SALES_MANAGER)
    c = Company(name="Palms Beach House", normalized_name="palms beach house", domain="beirut.ml",
                website="https://beirut.ml/palmsbeachhouse/", primary_email="info@sushitsunami.com")
    db.add(c)
    db.flush()
    db.add_all([Email(company_id=c.id, email="info@sushitsunami.com", email_type="generic", status="published"),
                Email(company_id=c.id, email="hello@palmsbeachhouse.com", email_type="generic", status="published")])
    db.commit()
    emails = manager.get(f"/companies/{c.id}").json()["emails"]
    assert [(e["email"], e["other_domain"]) for e in emails] == [
        ("hello@palmsbeachhouse.com", False), ("info@sushitsunami.com", True)]  # flagged, listed last
    assert "sushitsunami" not in company_service.export_csv(db, user)
    listed = manager.get("/companies", params={"q": "Palms"}).json()["items"][0]
    assert listed["domain"] == "beirut.ml" and listed["own_domain"] is None  # stored as given, shown as no domain
    assert manager.get(f"/companies/{c.id}").json()["company"]["own_domain"] is None


def test_a_number_shared_by_three_companies_is_flagged(client_for, db):
    from app.models import Phone

    manager, _ = client_for(UserRole.SALES_MANAGER)
    plots = [Company(name=f"31{n} Zekril Real Estate Sal", normalized_name=f"31{n} zekril") for n in range(3)]
    own = Company(name="Real Bakery", normalized_name="real bakery")
    db.add_all([*plots, own])
    db.flush()
    db.add_all([Phone(company_id=c.id, phone="+961 1 342 633", phone_type="unknown") for c in plots])
    db.add_all([Phone(company_id=own.id, phone="+961 1 342 633", phone_type="unknown"),
                Phone(company_id=own.id, phone="+961 3 111 222", phone_type="unknown")])
    db.commit()
    phones = manager.get(f"/companies/{own.id}").json()["phones"]
    assert [(p["phone"], p["shared_with"]) for p in phones] == [("+961 3 111 222", 0), ("+961 1 342 633", 3)]
