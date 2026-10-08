"""V2 business model: companies, people, contact points, provenance, status history, lead searches."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (AuditLog, CompanyLocation, CompanyPerson, CompanyStatusHistory, Email, Evidence, Integration,
                        LeadSearch, LeadSearchResult, OpportunityAnalysis, Person, Phone, ResearchRun, Source)
from app.models.enums import UserRole

NOW = datetime.now(timezone.utc)


def create(client, name="ABC Foods SAL", **fields) -> dict:
    response = client.post("/companies", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def add_person(db, company_id: int, name: str, title: str, department: str, **role) -> tuple[Person, CompanyPerson]:
    person = Person(full_name=name, normalized_name=name.lower())
    db.add(person)
    db.flush()
    job = CompanyPerson(company_id=company_id, person_id=person.id, job_title=title, department=department, **role)
    db.add(job)
    db.commit()
    return person, job


# ---- 1-2: companies ---------------------------------------------------------------------------------------


def test_company_create_read_update_delete(client_for, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)

    company = create(agent, website="www.ABCFoods.example/about", headquarters_country="Lebanon",
                     primary_email="Info@ABCFoods.example", employee_count_estimate=120)
    assert company["normalized_name"] == "abc foods"
    assert company["website"] == "https://www.ABCFoods.example/about"
    assert company["domain"] == "abcfoods.example"
    assert company["primary_email"] == "info@abcfoods.example"
    assert company["status"] == "new" and company["created_by_user_id"] == user.id

    detail = agent.get(f"/companies/{company['id']}").json()
    assert detail["company"]["name"] == "ABC Foods SAL"
    assert detail["locations"] == detail["people"] == detail["opportunities"] == detail["sources"] == []

    updated = agent.patch(f"/companies/{company['id']}", json={"name": "ABC Foods Holding", "industry": "Food"})
    assert updated.status_code == 200
    assert updated.json()["normalized_name"] == "abc foods" and updated.json()["industry"] == "Food"

    assert agent.delete(f"/companies/{company['id']}").status_code == 403  # agents cannot delete
    assert manager.delete(f"/companies/{company['id']}").status_code == 204
    assert agent.get(f"/companies/{company['id']}").status_code == 404
    actions = set(db.scalars(select(AuditLog.action)).all())
    assert {"company.created", "company.updated", "company.deleted"} <= actions


def test_company_validation_and_domain_uniqueness(client_for):
    agent, _ = client_for(UserRole.SALES_AGENT)
    create(agent, "ABC Foods", website="https://abcfoods.example")
    # Same name is allowed (different companies share names); same domain is the same company.
    create(agent, "ABC Foods")
    assert agent.post("/companies", json={"name": "Copy", "domain": "WWW.abcfoods.example"}).status_code == 409
    # Social profiles are never a company's domain.
    social = create(agent, "Insta Only", website="https://instagram.com/instaonly")
    assert social["domain"] is None
    for bad in ({"name": ""}, {"name": "X", "founded_year": 1200}, {"name": "X", "employee_count_estimate": 0},
                {"name": "X", "primary_email": "not-an-email"}, {"name": "X", "domain": "instagram.com"},
                {"name": "X", "primary_phone": "call me"}):
        assert agent.post("/companies", json=bad).status_code == 422, bad


def test_company_listing_and_filters(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    abc = create(agent, "ABC Foods", headquarters_country="Lebanon", headquarters_city="Beirut", industry="Food")
    create(agent, "Cedar Logistics", headquarters_country="Lebanon", headquarters_city="Tripoli", industry="Logistics")
    create(agent, "Gulf Trading", headquarters_country="United Arab Emirates", industry="Trading")
    db.add(CompanyLocation(company_id=abc["id"], country="Lebanon", city="Zahle", location_type="factory"))
    db.commit()
    agent.patch(f"/companies/{abc['id']}/status", json={"status": "qualified"})

    def names(**params):
        return [c["name"] for c in agent.get("/companies", params=params).json()["items"]]

    assert names() == ["ABC Foods", "Cedar Logistics", "Gulf Trading"]
    assert names(q="cedar") == ["Cedar Logistics"]
    assert names(country="lebanon") == ["ABC Foods", "Cedar Logistics"]
    assert names(city="Zahle") == ["ABC Foods"]  # any location, not only the headquarters
    assert names(industry="logistics") == ["Cedar Logistics"]
    assert names(status="qualified") == ["ABC Foods"]
    assert agent.get("/companies", params={"status": "hot"}).status_code == 422
    page = agent.get("/companies", params={"page_size": 2, "page": 2}).json()
    assert page["total"] == 3 and [c["name"] for c in page["items"]] == ["Gulf Trading"]


# ---- 3-7: people, contact points, provenance ---------------------------------------------------------------


def test_people_by_department_with_their_contact_points(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = create(agent)["id"]
    rami, _ = add_person(db, cid, "Rami Khoury", "IT Manager", "it", seniority="manager", confidence=80)
    add_person(db, cid, "Nour Haddad", "Chief Financial Officer", "finance", seniority="c_level")
    add_person(db, cid, "Karim Saad", "Former Sales Director", "sales", is_current=False)
    db.add_all([Email(person_id=rami.id, company_id=cid, email="rami.khoury@abcfoods.example", status="discovered"),
                Email(person_id=rami.id, email="rami@personal.example", status="unknown"),
                Phone(person_id=rami.id, company_id=cid, phone="+961 3 000 001", normalized_phone="+9613000001",
                      phone_type="mobile")])
    db.commit()

    people = agent.get(f"/companies/{cid}/people").json()
    assert [(p["person"]["full_name"], p["department"], p["is_current"]) for p in people] == [
        ("Nour Haddad", "finance", True), ("Rami Khoury", "it", True), ("Karim Saad", "sales", False)]
    rami_row = people[1]
    assert rami_row["job_title"] == "IT Manager" and rami_row["confidence"] == 80
    assert {e["email"] for e in rami_row["emails"]} == {"rami.khoury@abcfoods.example", "rami@personal.example"}
    assert rami_row["phones"][0]["phone_type"] == "mobile"
    # The same person, a historical role at the same company: allowed (history), a duplicate current one is not.
    db.add(CompanyPerson(company_id=cid, person_id=rami.id, job_title="IT Officer", department="it", is_current=False))
    db.commit()
    db.add(CompanyPerson(company_id=cid, person_id=rami.id, job_title="IT Manager", department="it"))
    with pytest.raises(IntegrityError, match="uq_company_people_current_role"):
        db.commit()


def test_company_phone_and_sources_with_evidence(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = create(agent)["id"]
    person, job = add_person(db, cid, "Rami Khoury", "IT Manager", "it")
    page = Source(source_type="company_website", url="https://abcfoods.example/team", retrieved_at=NOW,
                  content_hash="a" * 64)
    directory = Source(source_type="public_directory", name="Example directory")
    db.add_all([page, directory])
    db.flush()
    db.add_all([
        Phone(company_id=cid, phone="01 234 567", normalized_phone="+9611234567", phone_type="landline",
              is_primary=True, is_public=True, source_id=directory.id),
        Evidence(source_id=page.id, company_id=cid, person_id=person.id, company_person_id=job.id,
                 evidence_type="employment", field_name="job_title", extracted_value="IT Manager",
                 excerpt="Rami Khoury, IT Manager", confidence=90, observed_at=NOW),
        Evidence(source_id=page.id, company_id=cid, evidence_type="company_fact", field_name="industry",
                 extracted_value="Food manufacturing"),
    ])
    db.commit()

    detail = agent.get(f"/companies/{cid}").json()
    assert [(p["phone"], p["is_primary"]) for p in detail["phones"]] == [("01 234 567", True)]
    sources = {s["source_type"]: s for s in detail["sources"]}
    assert sources["company_website"]["evidence_count"] == 2
    assert sources["public_directory"]["evidence_count"] == 0  # cited by the phone, not by evidence
    why = db.scalar(select(Evidence).where(Evidence.company_person_id == job.id))
    assert (why.field_name, why.extracted_value, db.get(Source, why.source_id).url) == (
        "job_title", "IT Manager", "https://abcfoods.example/team")


def test_database_refuses_inconsistent_intelligence(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = create(agent)["id"]
    source = Source(source_type="manual")
    db.add(source)
    db.flush()
    db.commit()
    cases = [
        (Email(company_id=cid, email="guess@abcfoods.example", status="predicted", last_verified_at=NOW),
         "predicted_not_verified"),
        (Email(company_id=cid, email="x@abcfoods.example", status="verified"), "verified_has_date"),
        (Email(email="orphan@abcfoods.example"), "owner_present"),
        (Email(company_id=cid, email="Upper@abcfoods.example"), "email_lowercase"),
        (Phone(phone="+961 1 000 000"), "owner_present"),
        (Evidence(source_id=source.id, evidence_type="other"), "subject_present"),
        (Email(company_id=cid, email="c@abcfoods.example", confidence=101), "confidence_range"),
        (OpportunityAnalysis(company_id=cid, solution="any", generated_at=NOW), "solution_valid"),
        (OpportunityAnalysis(company_id=cid, solution="odoo", fit_level="87%", generated_at=NOW), "fit_level_valid"),
    ]
    for row, constraint in cases:
        db.add(row)
        with pytest.raises(IntegrityError, match=constraint):
            db.commit()
        db.rollback()
    db.add_all([CompanyLocation(company_id=cid, country="Lebanon", is_headquarters=True),
                CompanyLocation(company_id=cid, country="Lebanon", is_headquarters=True)])
    with pytest.raises(IntegrityError, match="uq_company_locations_headquarters"):
        db.commit()
    db.rollback()
    with pytest.raises(ValueError, match="api_key"):
        Integration(integration_type="odoo", display_name="Odoo", configuration={"url": "https://x", "api_key": "k"})
    with pytest.raises(ValueError, match="auth.client_secret"):
        Integration(integration_type="x", display_name="X", configuration={"auth": {"client_secret": "s"}})
    assert Integration(integration_type="odoo", display_name="Odoo", configuration={"database": "prod"})


def test_latest_opportunity_analysis_per_solution(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    cid = create(agent)["id"]
    db.add_all([OpportunityAnalysis(company_id=cid, solution="odoo", fit_level="low", generated_at=datetime(2026, 1, 1,
                                                                                                           tzinfo=timezone.utc)),
                OpportunityAnalysis(company_id=cid, solution="odoo", fit_level="high", summary="ERP replacement",
                                    generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc)),
                OpportunityAnalysis(company_id=cid, solution="it", fit_level="unknown", generated_at=NOW)])
    db.commit()
    opportunities = agent.get(f"/companies/{cid}").json()["opportunities"]
    assert [(o["solution"], o["fit_level"]) for o in opportunities] == [("it", "unknown"), ("odoo", "high")]


# ---- 8: status history --------------------------------------------------------------------------------------


def test_status_change_creates_history(client_for, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    cid = create(agent)["id"]
    assert agent.patch(f"/companies/{cid}", json={"status": "qualified"}).status_code == 422  # only via /status
    moved = agent.patch(f"/companies/{cid}/status", json={"status": "contacted", "reason": "Called reception"})
    assert moved.status_code == 200 and moved.json()["status"] == "contacted"
    agent.patch(f"/companies/{cid}/status", json={"status": "contacted"})  # unchanged: no history row
    agent.patch(f"/companies/{cid}/status", json={"status": "working_odoo"})
    assert agent.patch(f"/companies/{cid}/status", json={"status": "won"}).status_code == 422
    history = db.scalars(select(CompanyStatusHistory).order_by(CompanyStatusHistory.id)).all()
    assert [(h.old_status, h.new_status, h.changed_by_user_id) for h in history] == [
        ("new", "contacted", user.id), ("contacted", "working_odoo", user.id)]
    assert history[0].reason == "Called reception"
    assert db.scalar(select(func.count()).where(AuditLog.action == "company.status_changed")) == 2


# ---- 9-10: lead searches ------------------------------------------------------------------------------------


def test_lead_search_is_persisted_and_queued(client_for, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    payload = {"country": "Lebanon", "region": None, "city": "Beirut", "industry": "Food Manufacturing",
               "solution": "odoo", "requested_count": 50}
    response = agent.post("/lead-searches", json=payload)
    assert response.status_code == 201, response.text
    search = response.json()
    assert {k: search[k] for k in payload if k != "region"} == {k: v for k, v in payload.items() if k != "region"}
    assert search["region"] == "Beirut"  # normalized: Beirut is a city in the Beirut governorate
    assert (search["status"], search["companies_found"], search["user_id"]) == ("researching", 0, user.id)
    assert db.scalar(select(func.count(ResearchRun.id)).where(ResearchRun.status == "queued")) == 1
    assert db.scalar(select(func.count(LeadSearchResult.id))) == 0  # nothing invented while the job waits
    assert agent.post("/lead-searches", json={"country": "Lebanon"}).json()["requested_count"] == 50
    for bad in ({"country": ""}, {"country": "Lebanon", "requested_count": 0},
                {"country": "Lebanon", "requested_count": 501}, {"country": "Lebanon", "solution": "sap"}):
        assert agent.post("/lead-searches", json=bad).status_code == 422, bad


def test_same_company_in_several_searches_without_duplicating_it(client_for, db, make_user):
    agent, user = client_for(UserRole.SALES_AGENT)
    cid = create(agent)["id"]
    first, second = LeadSearch(user_id=user.id, country="Lebanon", requested_count=50), \
        LeadSearch(user_id=user.id, country="Lebanon", industry="Food", requested_count=20)
    db.add_all([first, second])
    db.flush()
    db.add_all([LeadSearchResult(search_id=first.id, company_id=cid, rank=1),
                LeadSearchResult(search_id=second.id, company_id=cid, rank=3, relevance_score=0.7)])
    db.commit()
    assert db.scalar(select(func.count(LeadSearchResult.id)).where(LeadSearchResult.company_id == cid)) == 2
    assert agent.get("/companies").json()["total"] == 1
    db.add(LeadSearchResult(search_id=first.id, company_id=cid))
    with pytest.raises(IntegrityError, match="uq_lead_search_results_company"):
        db.commit()


# ---- 11: deletion keeps unrelated data --------------------------------------------------------------------


def test_deleting_a_company_keeps_people_sources_and_history(client_for, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    admin, _ = client_for(UserRole.ADMIN)
    cid = create(agent, "Doomed Co")["id"]
    other = create(agent, "Other Co")["id"]
    rami, job = add_person(db, cid, "Rami Khoury", "IT Manager", "it")
    db.add(CompanyPerson(company_id=other, person_id=rami.id, job_title="Advisor"))
    source = Source(source_type="company_website", url="https://doomed.example/team")
    db.add(source)
    db.flush()
    search = LeadSearch(user_id=user.id, country="Lebanon", requested_count=10)
    db.add(search)
    db.flush()
    db.add_all([
        CompanyLocation(company_id=cid, country="Lebanon", source_id=source.id),
        Email(company_id=cid, email="info@doomed.example", source_id=source.id),
        Email(company_id=cid, person_id=rami.id, email="rami@doomed.example"),
        Phone(company_id=cid, phone="+961 1 111 111"),
        Evidence(source_id=source.id, company_id=cid, person_id=rami.id, company_person_id=job.id,
                 evidence_type="employment"),
        Evidence(source_id=source.id, person_id=rami.id, evidence_type="person_fact", field_name="full_name"),
        LeadSearchResult(search_id=search.id, company_id=cid),
        ResearchRun(company_id=cid, search_id=search.id, research_type="company_enrichment"),
    ])
    db.commit()
    agent.patch(f"/companies/{cid}/status", json={"status": "archived"})

    assert admin.delete(f"/companies/{cid}").status_code == 204
    db.expire_all()
    assert db.get(Person, rami.id) is not None  # people never disappear with a company
    assert [j.company_id for j in db.scalars(select(CompanyPerson)).all()] == [other]
    assert db.get(Source, source.id) is not None  # provenance stays
    emails = db.scalars(select(Email)).all()
    assert [(e.email, e.company_id, e.person_id) for e in emails] == [("rami@doomed.example", None, rami.id)]
    assert db.scalar(select(func.count(Phone.id))) == 0
    assert [e.evidence_type for e in db.scalars(select(Evidence)).all()] == ["person_fact"]
    assert db.scalar(select(func.count(LeadSearchResult.id))) == 0 and db.get(LeadSearch, search.id) is not None
    assert db.scalar(select(ResearchRun.company_id)) is None  # run history kept, detached
    assert db.scalar(select(func.count(CompanyStatusHistory.id))) == 0
    assert db.scalar(select(func.count(CompanyLocation.id))) == 0
    assert agent.get(f"/companies/{other}/people").json()[0]["person"]["full_name"] == "Rami Khoury"
    # A source still cited by evidence cannot be deleted.
    db.delete(db.get(Source, source.id))
    with pytest.raises(IntegrityError, match="fk_evidence_source_id_sources"):
        db.commit()
