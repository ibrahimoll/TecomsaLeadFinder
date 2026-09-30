"""Odoo import workflow, duplicate protection and relationship status (Phase 0 acceptance)."""

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.models import AuditLog, Company, CrmLead, OdooContact, OdooMatch
from app.models.enums import UserRole
from scripts.sample_odoo_files import (
    CONTACT_HEADERS,
    CONTACT_ROWS,
    CRM_HEADERS,
    CRM_ROWS,
    csv_bytes,
    xlsx_bytes,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(client, import_type: str, content: bytes, filename: str, mime: str = XLSX):
    return client.post("/imports", data={"import_type": import_type}, files={"file": (filename, content, mime)})


def run_import(client, import_type: str, content: bytes, filename: str):
    preview = upload(client, import_type, content, filename)
    assert preview.status_code == 201, preview.text
    confirmed = client.post(f"/imports/{preview.json()['run']['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    return preview.json(), confirmed.json()


def company_named(client, q: str) -> dict:
    items = client.get("/companies", params={"q": q}).json()["items"]
    assert len(items) == 1, [c["name"] for c in items]
    return client.get(f"/companies/{items[0]['id']}").json()


def test_crm_preview_detects_columns_duplicates_and_errors(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)

    response = upload(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")

    assert response.status_code == 201, response.text
    preview = response.json()
    run = preview["run"]
    assert run["status"] == "PREVIEW" and run["file_type"] == "xlsx"
    assert run["row_count"] == 6
    assert run["duplicate_count"] == 1
    assert run["error_count"] == 1
    assert run["valid_count"] == 4
    mapping = run["column_mapping"]
    assert mapping["opportunity_name"] == "Opportunity"
    assert mapping["company_name"] == "Customer"
    assert mapping["salesperson"] == "Salesperson" and mapping["stage"] == "Stage"
    assert mapping["odoo_id"] == "ID"
    assert preview["new_records"] == 4 and preview["companies_new"] == 4
    assert {r["status"] for r in preview["sample_rows"]} >= {"new", "duplicate", "error"}
    # Nothing is written before confirmation.
    assert db.scalar(select(func.count(CrmLead.id))) == 0
    assert db.scalar(select(func.count(Company.id))) == 0


def test_phase0_odoo_acceptance_scenario(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    # A company entered before any Odoo data exists cannot be called available yet.
    unrelated = admin.post("/companies", json={"name": "Unrelated Trading", "country": "Lebanon"}).json()
    assert unrelated["odoo_status"] == "NOT_CHECKED"

    _, crm = run_import(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")
    assert crm["status"] == "COMPLETED"
    assert (crm["inserted_count"], crm["updated_count"], crm["skipped_count"]) == (4, 0, 2)
    assert crm["companies_created"] == 4

    contacts_preview, contacts = run_import(
        admin, "ODOO_CONTACTS", xlsx_bytes(CONTACT_HEADERS, CONTACT_ROWS), "odoo_contacts.xlsx")
    assert contacts["inserted_count"] == 4
    # "ABC FOODS" matched the company created from the CRM file; only Mount Lebanon Pharma is new.
    assert contacts["companies_created"] == 1
    assert contacts_preview["companies_matched"] >= 1

    abc = company_named(admin, "ABC Foods")
    assert abc["name"] == "ABC Foods S.A.L."
    assert abc["odoo_status"] == "EXISTING_OPPORTUNITY"
    assert abc["is_protected"] is True
    assert "Nadine Haddad" in abc["crm_status_reason"] and "Proposition" in abc["crm_status_reason"]
    assert abc["salesperson"]["name"] == "Nadine Haddad"
    assert [r["stage"] for r in abc["relationship"]["crm_records"]] == ["Proposition"]
    assert {c["contact_name"] for c in abc["relationship"]["odoo_contacts"]} == {"ABC FOODS", "Rami Khoury"}
    assert abc["relationship"]["last_interaction"] is not None
    # Enriched from Odoo without inventing data.
    assert abc["domain"] == "abcfoods.example" and abc["source"] == "ODOO_IMPORT"

    assert company_named(admin, "Cedar Hotels")["odoo_status"] == "CUSTOMER"
    lost = company_named(admin, "Byblos Bakery")
    assert lost["odoo_status"] == "LOST_OPPORTUNITY" and "Too expensive" in lost["crm_status_reason"]
    assert company_named(admin, "Tripoli Traders")["odoo_status"] == "EXISTING_LEAD"
    assert company_named(admin, "Mount Lebanon Pharma")["odoo_status"] == "EXISTING_CONTACT"

    available = admin.get(f"/companies/{unrelated['id']}").json()
    assert available["odoo_status"] == "AVAILABLE" and available["is_protected"] is False

    history = admin.get("/imports").json()
    assert history["total"] == 2
    assert {r["import_type"] for r in history["items"]} == {"ODOO_CRM", "ODOO_CONTACTS"}
    assert all(r["status"] == "COMPLETED" and r["creator"] for r in history["items"])
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "import.completed")) == 2
    # Status history is kept.
    assert db.scalar(select(func.count(OdooMatch.id)).where(OdooMatch.company_id == unrelated["id"])) == 2


def test_manually_added_duplicate_is_protected_and_flagged(client_for):
    admin, _ = client_for(UserRole.ADMIN)
    agent, _ = client_for(UserRole.SALES_AGENT)
    run_import(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")

    candidates = agent.get("/companies/duplicates", params={"name": "abc foods"}).json()
    assert candidates and candidates[0]["company"]["name"] == "ABC Foods S.A.L."

    created = agent.post("/companies", json={"name": "ABC FOODS", "website": "https://abcfoods.example"}).json()
    assert created["odoo_status"] == "EXISTING_OPPORTUNITY" and created["is_protected"] is True
    detail = agent.get(f"/companies/{created['id']}").json()
    assert detail["possible_duplicates"][0]["company"]["name"] == "ABC Foods S.A.L."
    assert "name" in detail["possible_duplicates"][0]["reason"]
    # CRM contact details are not copied onto the company record.
    abc = agent.get(f"/companies/{candidates[0]['company']['id']}").json()
    assert abc["main_email"] is None and abc["main_phone"] is None


def test_reimport_updates_instead_of_duplicating(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    content = xlsx_bytes(CRM_HEADERS, CRM_ROWS)
    run_import(admin, "ODOO_CRM", content, "odoo_crm.xlsx")

    preview, second = run_import(admin, "ODOO_CRM", content, "odoo_crm_again.xlsx")

    assert preview["previous_import"] is not None
    assert preview["existing_records"] == 4 and preview["new_records"] == 0
    assert (second["inserted_count"], second["updated_count"]) == (0, 4)
    assert second["companies_created"] == 0
    assert db.scalar(select(func.count(CrmLead.id))) == 4
    assert db.scalar(select(func.count(Company.id))) == 4


def test_csv_import_and_manual_column_mapping(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    headers = ["Deal", "Client", "Owner", "Phase"]
    rows = [["Network upgrade", "Zahle Motors", "Karim Nassar", "Negotiation"],
            ["CCTV", "Sidon Port Services", "Nadine Haddad", "New"]]

    preview = upload(admin, "ODOO_CRM", csv_bytes(headers, rows), "export.csv", "text/csv").json()
    assert preview["run"]["file_type"] == "csv"
    assert preview["run"]["valid_count"] == 0  # nothing recognisable yet
    assert "Opportunity / lead name" in preview["missing_important"]

    remapped = admin.put(
        f"/imports/{preview['run']['id']}/mapping",
        json={"mapping": {"opportunity_name": "Deal", "company_name": "Client", "salesperson": "Owner",
                          "stage": "Phase"}},
    )
    assert remapped.status_code == 200, remapped.text
    assert remapped.json()["run"]["valid_count"] == 2

    bad = admin.put(f"/imports/{preview['run']['id']}/mapping", json={"mapping": {"stage": "Nope"}})
    assert bad.status_code == 422

    result = admin.post(f"/imports/{preview['run']['id']}/confirm").json()
    assert result["inserted_count"] == 2
    assert admin.post(f"/imports/{preview['run']['id']}/confirm").status_code == 409
    assert db.scalar(select(CrmLead.stage).where(CrmLead.company_name == "Zahle Motors")) == "Negotiation"


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("old.xls", b"\xd0\xcf\x11\xe0 legacy", "Legacy .xls"),
        ("notes.txt", b"hello", "Unsupported file type"),
        ("broken.xlsx", b"PK\x03\x04 not really a zip", "could not be opened"),
        ("fake.xlsx", b"not a zip at all", "not a valid Excel"),
        ("empty.csv", b"", "empty"),
        ("header_only.csv", b"Opportunity,Customer\n", "no data rows"),
    ],
)
def test_invalid_files_are_rejected_with_clear_messages(client_for, db, filename, content, message):
    admin, _ = client_for(UserRole.ADMIN)
    response = upload(admin, "ODOO_CRM", content, filename, "application/octet-stream")
    assert response.status_code == 422
    assert message.lower() in response.json()["detail"].lower()
    assert db.scalar(select(func.count(CrmLead.id))) == 0


def test_empty_worksheet_is_rejected(client_for):
    admin, _ = client_for(UserRole.ADMIN)
    buffer = io.BytesIO()
    Workbook().save(buffer)
    response = upload(admin, "ODOO_CONTACTS", buffer.getvalue(), "blank.xlsx")
    assert response.status_code == 422 and "empty" in response.json()["detail"]


def test_cancelled_import_cannot_be_confirmed(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    preview = upload(admin, "ODOO_CONTACTS", xlsx_bytes(CONTACT_HEADERS, CONTACT_ROWS), "c.xlsx").json()
    run_id = preview["run"]["id"]
    assert admin.post(f"/imports/{run_id}/cancel").json()["status"] == "CANCELLED"
    assert admin.post(f"/imports/{run_id}/confirm").status_code == 409
    assert db.scalar(select(func.count(OdooContact.id))) == 0


def test_import_and_crm_permissions(client_for):
    admin, _ = client_for(UserRole.ADMIN)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    agent, _ = client_for(UserRole.SALES_AGENT)
    content = xlsx_bytes(CRM_HEADERS, CRM_ROWS)

    assert upload(agent, "ODOO_CRM", content, "x.xlsx").status_code == 403
    assert upload(manager, "ODOO_CRM", content, "x.xlsx").status_code == 403  # MANAGERS_CAN_IMPORT=false
    assert agent.get("/imports").status_code == 403
    run_import(admin, "ODOO_CRM", content, "odoo_crm.xlsx")

    assert agent.get("/odoo/leads").status_code == 403
    assert agent.get("/salespeople").status_code == 403
    leads = manager.get("/odoo/leads", params={"state": "lost"}).json()
    assert [lead["company_name"] for lead in leads["items"]] == ["Byblos Bakery"]
    assert manager.get("/odoo/leads", params={"state": "open"}).json()["total"] == 2
    # Everyone can see WHY a company is protected on its profile.
    assert company_named(agent, "Cedar Hotels")["crm_status_reason"].startswith("Won opportunity")

    me = agent.get("/auth/me").json()["capabilities"]
    assert me == {"manage_users": False, "view_crm": False, "run_imports": False}
    assert admin.get("/auth/me").json()["capabilities"]["run_imports"] is True


def test_salespeople_are_created_from_imports_and_linkable(client_for, make_user):
    admin, _ = client_for(UserRole.ADMIN)
    run_import(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")
    rows = {r["salesperson"]["name"]: r for r in admin.get("/salespeople").json()}
    assert set(rows) == {"Nadine Haddad", "Karim Nassar"}
    assert rows["Nadine Haddad"]["crm_records"] == 2 and rows["Nadine Haddad"]["open_records"] == 1

    agent = make_user(UserRole.SALES_AGENT)
    sp_id = rows["Nadine Haddad"]["salesperson"]["id"]
    linked = admin.patch(f"/salespeople/{sp_id}", json={"user_id": agent.id, "odoo_user_id": 7})
    assert linked.status_code == 200 and linked.json()["user"]["id"] == agent.id
    other = rows["Karim Nassar"]["salesperson"]["id"]
    assert admin.patch(f"/salespeople/{other}", json={"user_id": agent.id}).status_code == 409


def test_dashboard_counts_come_from_real_data(client_for):
    admin, _ = client_for(UserRole.ADMIN)
    empty = admin.get("/dashboard").json()
    assert (empty["total_companies"], empty["odoo_crm_records"], empty["protected_companies"]) == (0, 0, 0)

    run_import(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")
    data = admin.get("/dashboard").json()
    assert data["odoo_crm_records"] == 4 and data["odoo_open_records"] == 2
    assert data["protected_companies"] == 4 and data["available_companies"] == 0
    assert len(data["latest_imports"]) == 1


def test_company_filters_and_sorting(client_for):
    admin, _ = client_for(UserRole.ADMIN)
    run_import(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")
    admin.post("/companies", json={"name": "Fresh Prospect"})

    assert admin.get("/companies", params={"protected": "true"}).json()["total"] == 4
    assert [c["name"] for c in admin.get("/companies", params={"protected": "false"}).json()["items"]] == [
        "Fresh Prospect"]
    assert admin.get("/companies", params={"crm_status": "CUSTOMER"}).json()["total"] == 1
    assert admin.get("/companies", params={"source": "ODOO_IMPORT"}).json()["total"] == 4
    names = [c["name"] for c in admin.get("/companies", params={"sort": "name"}).json()["items"]]
    assert names == sorted(names, key=str.lower)
