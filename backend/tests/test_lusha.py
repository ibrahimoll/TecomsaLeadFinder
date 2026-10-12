"""Lusha: a paid search / reveal only on a confirmed click, every call on the ledger, a double click pays once, the
monthly budget and privacy suppressions checked before Lusha is called. Lusha's HTTP is always mocked."""

import json

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.models import Company, CompanyPerson, Email, LushaRequest, Person, PersonSuppression, Phone
from app.models.enums import UserRole
from app.services import lusha, privacy

PREVIEW = {"id": "c-1", "firstName": "Rana", "lastName": "Saad",
           "jobTitle": {"title": "Sales Director", "departments": ["Sales"], "seniority": "Director"},
           "company": {"name": "Omega Foods", "domain": "www.omega.example"}, "has": ["emails", "phones"],
           "canReveal": [{"field": "emails", "credits": 1}, {"field": "phones", "credits": 5}]}

FILTER_VALUES = {"departments": ["Information Technology", "Marketing", "Finance"],
                 "seniority": [{"id": 6, "name": "director"}, {"id": 4, "name": "manager"}],
                 "existingDataPoints": ["work_email", "mobile_phone", "direct_phone"]}


@pytest.fixture
def api(monkeypatch):
    """Mocked Lusha: `api.calls` lists (method, path, body); `api.status` forces an error code."""
    state = type("Lusha", (), {"calls": [], "status": 200})()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["api_key"] == "test-key"
        body = json.loads(request.content) if request.content else None
        state.calls.append((request.method, request.url.path, body))
        if state.status != 200:
            return httpx.Response(state.status, json={"statusCode": state.status, "message": "no"})
        if request.url.path == "/v3/contacts/prospecting":
            return httpx.Response(200, json={"requestId": "r", "results": [PREVIEW, {"id": "c-2", "firstName": "Ali",
                                             "lastName": "Hamdan", "jobTitle": {"title": "IT Manager"}, "has": []}],
                                             "pagination": {"page": body["pagination"]["page"], "total": 60},
                                             "billing": {"creditsCharged": 2, "resultsReturned": 2}})
        if request.url.path.startswith("/v3/contacts/prospecting/filters/"):
            return httpx.Response(200, json={"values": FILTER_VALUES[request.url.path.rsplit("/", 1)[1]]})
        if request.url.path == "/v3/contacts/enrich":
            revealed = {"emails": [{"email": "Rana.Saad@omega.example", "type": "work"}]} if body["reveal"] == [
                "emails"] else {"phones": [{"number": "+961 3 123 456", "type": "mobile", "doNotCall": False}]}
            return httpx.Response(200, json={"results": [{"id": "c-1", "firstName": "Rana", "lastName": "Saad",
                                                          "jobTitle": {"title": "Sales Director"}, **revealed}],
                                             "billing": {"creditsCharged": 1 if "emails" in revealed else 5}})
        if request.url.path == "/v3/account/usage":
            return httpx.Response(200, json={"credits": {"total": 100, "used": 10, "remaining": 90}})
        return httpx.Response(404)

    monkeypatch.setattr(lusha, "_client", lambda: httpx.Client(base_url="https://api.lusha.com",
                                                                headers={"api_key": "test-key"},
                                                                transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(lusha.get_settings(), "lusha_api_key", SecretStr("test-key"))
    monkeypatch.setattr(lusha.get_settings(), "lusha_monthly_credit_budget", 0)
    monkeypatch.setattr(lusha.get_settings(), "lusha_phone_only", False)  # the mechanics: emails too, no daily cap
    monkeypatch.setattr(lusha.get_settings(), "lusha_user_daily_reveals", 0)
    monkeypatch.setattr(lusha, "_usage_cache", [0.0, None])
    monkeypatch.setattr(lusha, "_values_cache", {})
    return state


@pytest.fixture
def company(db) -> int:
    c = Company(name="Omega Foods", normalized_name="omega foods", domain="omega.example")
    db.add(c)
    db.commit()
    return c.id


def own(db, company_id, user) -> None:  # salespeople work their own companies only (permissions.can_see)
    db.get(Company, company_id).owner_user_id = user.id
    db.commit()


def searched(client, company_id) -> list[dict]:
    r = client.post(f"/companies/{company_id}/lusha/search", json={})
    assert r.status_code == 200, r.text
    return r.json()["people"]


def reveal(client, company_id, field, contact="c-1"):
    return client.post(f"/companies/{company_id}/lusha/reveal", json={"contact_id": contact, "field": field})


def test_off_without_key(client_for, company, monkeypatch, db):
    monkeypatch.setattr(lusha.get_settings(), "lusha_api_key", None)
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    assert agent.get(f"/companies/{company}/lusha").json()["configured"] is False
    assert agent.post(f"/companies/{company}/lusha/search", json={}).status_code == 422
    assert reveal(agent, company, "email").status_code == 422
    assert agent.get("/lusha/credits").json()["account"] is None


def test_search_is_cached_and_masked(client_for, company, api, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    assert agent.get(f"/companies/{company}/lusha").json()["people"] == []  # opening the page never calls Lusha
    assert api.calls == []
    people = searched(agent, company)
    assert api.calls == [("POST", "/v3/contacts/prospecting", {"pagination": {"page": 0, "size": 25},
                          "filters": {"companies": {"include": {"domains": ["omega.example"]}}}})]
    rana = people[0]
    assert rana["masked_email"] == "***@omega.example" and rana["masked_phone"] == "***"
    assert rana["has_email"] and rana["has_phone"] and (rana["email_credits"], rana["phone_credits"]) == (1, 5)
    assert rana["emails"] is None and "rana.saad" not in json.dumps(people).lower()
    assert people[1]["has_email"] is False and people[1]["masked_email"] is None
    searched(agent, company)
    agent.get(f"/companies/{company}/lusha")
    assert len(api.calls) == 1  # reused: no second paid search
    assert db.scalar(select(LushaRequest.credits).where(LushaRequest.action == "search")) == 2  # Lusha's billing


def test_reveal_saves_person_once_and_double_click_pays_once(client_for, company, api, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    searched(agent, company)
    r = reveal(agent, company, "email")
    assert r.status_code == 200, r.text
    assert r.json()["emails"] == [{"email": "rana.saad@omega.example", "type": "work"}] and r.json()["credits"] == 1
    assert api.calls[-1][2] == {"ids": ["c-1"], "reveal": ["emails"], "waterfallEnabled": False}
    email = db.scalar(select(Email).where(Email.email == "rana.saad@omega.example"))
    assert (email.provenance, email.visibility, email.company_id) == ("lusha", "organization", company)
    person = db.get(Person, email.person_id)
    assert person.full_name == "Rana Saad"
    assert db.scalar(select(CompanyPerson.job_title).where(CompanyPerson.person_id == person.id)) == "Sales Director"
    again = reveal(agent, company, "email")
    assert again.json()["already_revealed"] and again.json()["credits"] == 0
    assert sum(1 for c in api.calls if c[1] == "/v3/contacts/enrich") == 1  # paid once
    phone = reveal(agent, company, "phone").json()
    assert phone["credits"] == 5 and phone["person_id"] == person.id  # the same person (by name)
    row = db.scalar(select(Phone).where(Phone.person_id == person.id))
    assert (row.phone_type, row.provenance) == ("business_mobile", "lusha")
    listed = agent.get(f"/companies/{company}/lusha").json()["people"][0]
    assert listed["person_id"] == person.id and listed["phones"][0]["number"] == "+961 3 123 456"
    names = [p["person"]["full_name"] for p in agent.get(f"/companies/{company}/people").json()]
    assert names == ["Rana Saad"]  # in LeadFinder's normal people list
    assert lusha.spent_this_month(db) == 2 + 1 + 5
    assert "lusha" in privacy.PROTECTED


def test_live_request_blocks_second_click(client_for, company, api, db, make_user):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    searched(agent, company)
    db.add(LushaRequest(company_id=company, user_id=user.id, action="email", lusha_contact_id="c-1", status="pending",
                        credits=1))  # another tab's reveal, still running
    db.commit()
    assert reveal(agent, company, "email").status_code == 409
    assert not any(c[1] == "/v3/contacts/enrich" for c in api.calls)


def test_budget_cap_blocks_the_call(client_for, company, api, monkeypatch, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    searched(agent, company)  # 2 credits
    monkeypatch.setattr(lusha.get_settings(), "lusha_monthly_credit_budget", 6)
    r = reveal(agent, company, "phone")  # 2 + 5 > 6
    assert r.status_code == 422 and "budget" in r.json()["detail"]
    assert not any(c[1] == "/v3/contacts/enrich" for c in api.calls)
    assert reveal(agent, company, "email").status_code == 200  # 2 + 1 fits
    credits = agent.get("/lusha/credits").json()
    assert credits == {"configured": True, "monthly_budget": 6, "spent_this_month": 3, "budget_left": 3,
                       "account": {"total": 100, "used": 10, "remaining": 90}, "phone_only": False,
                       "daily_reveals": None, "reveals_left_today": None}


def test_suppressed_person_is_not_revealed(client_for, company, api, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    searched(agent, company)
    db.add(PersonSuppression(company_id=company, key_hash=privacy._key_hash(company, "Rana Saad"), reason="asked"))
    db.commit()
    r = reveal(agent, company, "email")
    assert r.status_code == 422 and "removed" in r.json()["detail"]
    assert not any(c[1] == "/v3/contacts/enrich" for c in api.calls)
    assert db.scalar(select(Person)) is None


def test_ledger_for_managers_only(client_for, company, api, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    searched(agent, company)
    reveal(agent, company, "email")
    assert agent.get("/lusha/ledger").status_code == 403
    rows = manager.get("/lusha/ledger").json()
    assert [(r["action"], r["status"], r["credits"], r["company"]) for r in rows] == [
        ("email", "done", 1, "Omega Foods"), ("search", "done", 2, "Omega Foods")]


@pytest.mark.parametrize("code,expected", [(402, 402), (403, 502), (429, 429), (401, 502)])
def test_lusha_errors_are_mapped_and_cost_nothing(client_for, company, api, db, code, expected):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    searched(agent, company)
    api.status = code
    r = reveal(agent, company, "email")
    assert r.status_code == expected and "test-key" not in r.text
    row = db.scalar(select(LushaRequest).where(LushaRequest.action == "email"))
    assert (row.status, row.credits) == ("failed", 0)
    api.status = 200
    assert reveal(agent, company, "email").status_code == 200  # a failed reveal does not block a retry


# ---- free-text search -----------------------------------------------------------------------------------------------


def test_typed_words_become_lusha_filters(api):
    f = lusha.contact_filters
    assert f("IT") == {"departments": ["Information Technology"]}  # a whole department (alias)
    assert f(" marketing ") == {"departments": ["Marketing"]}
    assert f("Director") == {"seniorityIds": [6]}
    assert f("IT  Manager") == {"jobTitles": ["IT Manager"]}  # anything else: a job title
    assert f("CFO", has_phone=True) == {"jobTitles": ["CFO"], "existingDataPoints": ["mobile_phone", "direct_phone"],
                                        "existingDataPointsCondition": "or"}
    api.status = 500  # value lists unavailable: the words are a job title
    lusha._values_cache.clear()
    assert f("finance") == {"jobTitles": ["finance"]}


def test_company_search_is_cached_per_query_and_toggles(client_for, company, api, db):
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    prospecting = lambda: [c for c in api.calls if c[1] == "/v3/contacts/prospecting"]  # noqa: E731
    url = f"/companies/{company}/lusha"
    first = agent.post(f"{url}/search", json={"q": "IT manager"})
    assert first.status_code == 200 and first.json()["total"] == 60 and first.json()["has_more"] is True
    assert prospecting()[-1][2]["filters"] == {"contacts": {"include": {"jobTitles": ["IT manager"]}},
                                               "companies": {"include": {"domains": ["omega.example"]}}}
    agent.post(f"{url}/search", json={"q": "it   MANAGER"})  # the same words: reused, free
    assert len(prospecting()) == 1
    assert agent.get(url, params={"q": "IT Manager"}).json()["fresh"] is True
    assert agent.get(url, params={"q": "IT Manager", "has_phone": True}).json()["searched_at"] is None
    agent.post(f"{url}/search", json={"q": "IT manager", "has_phone": True})
    assert prospecting()[-1][2]["filters"]["contacts"]["include"]["existingDataPoints"] == ["mobile_phone",
                                                                                            "direct_phone"]
    agent.post(f"{url}/search", json={"q": "IT manager", "page": 1})
    assert prospecting()[-1][2]["pagination"] == {"page": 1, "size": 25} and len(prospecting()) == 3
    keys = set(db.scalars(select(LushaRequest.search_key).where(LushaRequest.action == "search")))
    assert keys == {f"{company}|it manager|0|0", f"{company}|it manager|0|1", f"{company}|it manager|1|0"}



def test_one_seat_rules_phone_only_daily_cap_and_never_a_known_number(client_for, company, api, monkeypatch, db):
    monkeypatch.setattr(lusha.get_settings(), "lusha_phone_only", True)
    monkeypatch.setattr(lusha.get_settings(), "lusha_user_daily_reveals", 1)
    agent, user = client_for(UserRole.SALES_AGENT)
    own(db, company, user)
    searched(agent, company)
    paid = lambda: sum(c[1] != "/v3/account/usage" for c in api.calls)  # noqa: E731
    calls = paid()
    assert reveal(agent, company, "email").status_code == 422 and paid() == calls  # numbers only
    assert reveal(agent, company, "phone").status_code == 200  # 1 of 1 today
    assert agent.get("/lusha/credits").json()["reveals_left_today"] == 0
    r = reveal(agent, company, "phone", contact="c-2")
    assert r.status_code == 422 and "Daily limit" in r.text and paid() == calls + 1
    assert reveal(agent, company, "phone").json()["credits"] == 0  # already revealed: free, not capped
    # Ali already has a number in LeadFinder (another source): shown as such, and never paid for
    monkeypatch.setattr(lusha.get_settings(), "lusha_user_daily_reveals", 0)
    ali = Person(full_name="Ali Hamdan", normalized_name="ali hamdan")
    db.add(ali)
    db.flush()
    db.add_all([CompanyPerson(company_id=company, person_id=ali.id, job_title="IT Manager"),
                Phone(person_id=ali.id, company_id=company, phone="+961 3 999 999", provenance="licensed")])
    db.commit()
    people = {p["id"]: p for p in agent.get(f"/companies/{company}/lusha").json()["people"]}
    assert people["c-2"]["leadfinder_has_phone"] is True and people["c-1"]["leadfinder_has_phone"] is True
    r = reveal(agent, company, "phone", contact="c-2")
    assert r.status_code == 422 and "already has a number" in r.text and paid() == calls + 1
