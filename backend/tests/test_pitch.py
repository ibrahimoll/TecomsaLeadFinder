"""Sales pitch: Claude is called only on a click, gets the company's facts but never a phone / e-mail, the pitch is
saved and reused while fresh (no second call), a refusal or an unreadable answer stores nothing. Claude is mocked."""

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.models import Company, CompanyPerson, CompanySignal, Person, Phone, Source
from app.models.enums import UserRole
from app.services import pitch

PITCH = {"why": "A food factory with branches runs stock and costing across sites.",
         "points": ["One stock across branches", "Production costing", "Accounting in USD and LBP"],
         "opener": "Hello, I'm calling from TECOMSA about stock across your branches.",
         "whatsapp": "Hello Rana, TECOMSA here. Could Odoo help you follow stock across your branches?",
         "objections": [{"objection": "We have Excel", "answer": "Excel breaks with several branches."}]}


@pytest.fixture
def claude(monkeypatch):
    state = SimpleNamespace(calls=[], stop="end_turn", text=json.dumps(PITCH))

    def create(**kw):
        state.calls.append(kw)
        return SimpleNamespace(stop_reason=state.stop, content=[SimpleNamespace(type="text", text=state.text)],
                               usage=SimpleNamespace(input_tokens=900, output_tokens=300))
    monkeypatch.setattr(pitch, "_client", lambda: SimpleNamespace(beta=SimpleNamespace(
        messages=SimpleNamespace(create=create))))
    monkeypatch.setattr(pitch.get_settings(), "anthropic_api_key", SecretStr("test-key"))
    return state


def company(db, owner_id) -> int:
    c = Company(name="Fictional Foods", normalized_name="fictional foods", industry="Food Manufacturing",
                owner_user_id=owner_id)
    site = Source(source_type="company_website", name="site", url="https://fictional.example")
    db.add_all([c, site])
    db.flush()
    rana = Person(full_name="Rana Saad", normalized_name="rana saad")
    db.add(rana)
    db.flush()
    db.add_all([CompanySignal(company_id=c.id, signal_type="factory", source_id=site.id),
                CompanySignal(company_id=c.id, signal_type="branches", signal_value="4", source_id=site.id),
                CompanyPerson(company_id=c.id, person_id=rana.id, job_title="Owner", department="executive",
                              title_rank=2),
                Phone(person_id=rana.id, company_id=c.id, phone="+961 3 123 456", phone_type="business_mobile")])
    db.commit()
    return c.id


def test_pitch_is_written_once_saved_and_never_sends_contacts(client_for, db, claude):
    agent, user = client_for(UserRole.SALES_AGENT)
    cid = company(db, user.id)
    r = agent.post(f"/companies/{cid}/pitch", json={"solution": "odoo"})
    assert r.status_code == 200, r.text
    assert r.json()["opener"] == PITCH["opener"] and r.json()["points"] == PITCH["points"]
    sent = claude.calls[0]["messages"][0]["content"]
    assert "factory" in sent and "Rana Saad (Owner)" in sent and "123 456" not in sent  # facts, never a number
    assert claude.calls[0]["model"] == "claude-opus-5-5" and claude.calls[0]["fallbacks"] == "default"
    again = agent.post(f"/companies/{cid}/pitch", json={"solution": "odoo"})
    assert again.json()["why"] == PITCH["why"] and len(claude.calls) == 1  # saved: free, no new call
    agent.post(f"/companies/{cid}/pitch", json={"solution": "odoo", "refresh": True})
    assert len(claude.calls) == 2  # asked for a new one
    detail = agent.get(f"/companies/{cid}").json()
    assert detail["pitch_configured"] is True and detail["opportunities"][0]["summary"] == PITCH["why"]


def test_refusal_unreadable_unconfigured_and_access(client_for, db, claude, monkeypatch):
    agent, user = client_for(UserRole.SALES_AGENT)
    cid = company(db, user.id)
    claude.stop = "refusal"
    assert agent.post(f"/companies/{cid}/pitch", json={"solution": "it"}).status_code == 422
    claude.stop, claude.text = "end_turn", "not json"
    assert agent.post(f"/companies/{cid}/pitch", json={"solution": "it"}).status_code == 502
    assert agent.get(f"/companies/{cid}").json()["opportunities"] == []  # nothing stored
    other, _ = client_for(UserRole.SALES_AGENT)
    assert other.post(f"/companies/{cid}/pitch", json={"solution": "odoo"}).status_code == 404  # not theirs
    monkeypatch.setattr(pitch.get_settings(), "anthropic_api_key", None)
    r = agent.post(f"/companies/{cid}/pitch", json={"solution": "odoo"})
    assert r.status_code == 422 and "not configured" in r.text
