"""Odoo import workflow, duplicate protection and relationship status (Phase 0 acceptance)."""

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from pathlib import Path

from app.core.config import get_settings
from app.models import AuditLog, Company, Contact, CrmLead, ImportRun, OdooContact, OdooMatch, Salesperson
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
    assert contacts["inserted_count"] == 5
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
    people = {c["contact_name"]: c for c in abc["relationship"]["odoo_contacts"]}
    assert set(people) == {"ABC FOODS", "Rami Khoury", "Mohammad Hassan"}
    assert people["Mohammad Hassan"]["job_position"] == "General Manager"
    assert people["Mohammad Hassan"]["is_company"] is False
    assert abc["relationship"]["last_interaction"] is not None
    # Enriched from the Odoo company record without inventing data; a person is never a company.
    assert abc["main_email"] == "info@abcfoods.example" and abc["source"] == "ODOO_IMPORT"
    assert admin.get("/companies", params={"q": "Mohammad Hassan"}).json()["total"] == 0
    assert db.scalar(select(OdooContact.company_id).where(OdooContact.contact_name == "Jane Doe")) is None

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


def test_crm_file_without_recognisable_columns_is_rejected(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    headers = ["Deal", "Client", "Owner", "Phase"]
    rows = [["Network upgrade", "Zahle Motors", "Karim Nassar", "Negotiation"]]

    response = upload(admin, "ODOO_CRM", csv_bytes(headers, rows), "export.csv", "text/csv")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "no Opportunity or Lead name column was detected" in detail and "Deal" in detail
    assert db.scalar(select(func.count(ImportRun.id))) == 0


def test_contacts_columns_are_detected_automatically(client_for, db):
    """Header variants, company/person split, Mobile preferred, no 'Is a company' column."""
    admin, _ = client_for(UserRole.ADMIN)
    headers = ["company_name", "CONTACT NAME", "Job-Title", "Mobile Number", "Tel", "Email Address", "Country Name",
               "Town", "Notes"]
    rows = [
        ["Zahle Motors SAL", "Karim Aoun", "Sales Director", "+961 3 111 000", "08 800 800",
         "karim@zahlemotors.example", "Lebanon", "Zahle", "x"],
        ["Zahle Motors SAL", None, None, None, "08 800 800", "info@zahlemotors.example", "Lebanon", "Zahle", None],
        [None, "Sidon Port Services SARL", None, None, "07 700 700", None, "Lebanon", "Sidon", None],
        [None, "Lina Fares", "Consultant", None, None, "lina.fares@gmail.com", "Lebanon", None, None],
        [None, None, "Driver", None, "03 000 000", None, None, None, None],
    ]

    response = upload(admin, "ODOO_CONTACTS", csv_bytes(headers, rows), "contacts.csv", "text/csv")
    assert response.status_code == 201, response.text
    preview = response.json()
    detected = {f["key"]: f["column"] for f in preview["fields"]}
    assert detected == {"company_name": "company_name", "contact_name": "CONTACT NAME", "job_position": "Job-Title",
                        "mobile": "Mobile Number", "phone": "Tel", "email": "Email Address",
                        "country": "Country Name", "city": "Town"}
    assert preview["unmapped_columns"] == ["Notes"]
    run = preview["run"]
    assert (run["row_count"], run["valid_count"], run["error_count"], run["warning_count"]) == (5, 4, 1, 1)
    first = preview["sample_rows"][0]["values"]
    assert first == {"company": "Zahle Motors SAL", "contact": "Karim Aoun", "position": "Sales Director",
                     "phone": "+961 3 111 000", "email": "karim@zahlemotors.example", "country": "Lebanon",
                     "city": "Zahle"}
    assert preview["sample_rows"][4]["status"] == "error"

    result = admin.post(f"/imports/{run['id']}/confirm").json()
    assert result["inserted_count"] == 4 and result["companies_created"] == 2
    names = sorted(c["name"] for c in admin.get("/companies").json()["items"])
    assert names == ["Sidon Port Services SARL", "Zahle Motors SAL"]  # people never become companies
    karim = db.scalar(select(OdooContact).where(OdooContact.contact_name == "Karim Aoun"))
    assert karim.parent_company == "Zahle Motors SAL" and karim.job_position == "Sales Director"
    assert karim.mobile == "+961 3 111 000" and karim.phone == "08 800 800" and karim.company_id is not None
    lina = db.scalar(select(OdooContact).where(OdooContact.contact_name == "Lina Fares"))
    assert lina.company_id is None and lina.parent_company is None


def test_contacts_file_without_names_is_rejected(client_for):
    admin, _ = client_for(UserRole.ADMIN)
    response = upload(admin, "ODOO_CONTACTS", csv_bytes(["Email", "Phone"], [["a@b.example", "01 111"]]),
                      "c.csv", "text/csv")
    assert response.status_code == 422
    assert response.json()["detail"].startswith(
        "The file could not be imported because no Company Name or Contact Name column was detected")


def _stored_file(db, run_id: int) -> Path:
    return Path(get_settings().import_storage_dir) / db.get(ImportRun, run_id).stored_filename


def test_delete_import_only_keeps_the_data(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    _, run = run_import(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")
    stored = _stored_file(db, run["id"])
    assert stored.is_file()

    response = admin.delete(f"/imports/{run['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["removed"] == {"crm_records": 0, "odoo_contacts": 0, "companies": 0, "salespeople": 0}
    assert admin.get(f"/imports/{run['id']}").status_code == 404
    assert not stored.exists()
    db.expire_all()
    assert db.scalar(select(func.count(CrmLead.id))) == 4
    assert db.scalar(select(func.count(CrmLead.id)).where(CrmLead.import_run_id.is_not(None))) == 0
    # The data is still there, so companies stay protected rather than becoming "not checked".
    assert company_named(admin, "Cedar Hotels")["odoo_status"] == "CUSTOMER"
    assert db.scalar(select(AuditLog.action).where(AuditLog.entity_id == str(run["id"]))
                     .order_by(AuditLog.id.desc())) == "import.deleted"


def test_delete_import_with_data_then_reimport(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    manual = admin.post("/companies", json={"name": "Manual Prospect"}).json()
    _, crm = run_import(admin, "ODOO_CRM", xlsx_bytes(CRM_HEADERS, CRM_ROWS), "odoo_crm.xlsx")
    contacts_bytes = xlsx_bytes(CONTACT_HEADERS, CONTACT_ROWS)
    _, contacts = run_import(admin, "ODOO_CONTACTS", contacts_bytes, "odoo_contacts.xlsx")
    # A company the user put in a campaign must survive.
    campaign = admin.post("/campaigns", json={"name": "Pharma push", "tecomsa_division": "ODOO",
                                              "country": "Lebanon", "target_company_count": 10}).json()
    pharma = company_named(admin, "Mount Lebanon Pharma")
    assert admin.post(f"/campaigns/{campaign['id']}/companies/{pharma['id']}").status_code == 201

    result = admin.delete(f"/imports/{contacts['id']}", params={"with_data": "true"}).json()

    assert result["removed"]["odoo_contacts"] == 5 and result["removed"]["companies"] == 0
    assert result["kept"]["companies"] == 1  # Mount Lebanon Pharma is in a campaign
    db.expire_all()
    assert db.scalar(select(func.count(OdooContact.id))) == 0
    assert company_named(admin, "Mount Lebanon Pharma")["odoo_status"] == "AVAILABLE"
    assert company_named(admin, "ABC Foods")["odoo_status"] == "EXISTING_OPPORTUNITY"  # CRM data untouched

    _, again = run_import(admin, "ODOO_CONTACTS", contacts_bytes, "odoo_contacts.xlsx")
    assert again["inserted_count"] == 5 and again["companies_created"] == 0

    # Deleting the CRM import with its data removes its records, companies and salespeople...
    result = admin.delete(f"/imports/{crm['id']}", params={"with_data": "true"}).json()
    assert result["removed"] == {"crm_records": 4, "odoo_contacts": 0, "companies": 3, "salespeople": 2}
    db.expire_all()
    assert db.scalar(select(func.count(CrmLead.id))) == 0
    assert db.scalar(select(func.count(Salesperson.id))) == 0
    # ...but ABC Foods is still linked to the contacts import, which now owns it.
    assert company_named(admin, "ABC Foods")["odoo_status"] == "EXISTING_CONTACT"

    admin.delete(f"/imports/{again['id']}", params={"with_data": "true"})
    db.expire_all()
    assert {c.name for c in db.scalars(select(Company))} == {"Manual Prospect", "Mount Lebanon Pharma"}
    assert db.scalar(select(func.count(OdooContact.id))) == 0
    assert db.scalar(select(func.count(ImportRun.id))) == 0
    assert db.scalar(select(func.count(OdooMatch.id)).where(OdooMatch.company_id.not_in(
        select(Company.id)))) == 0
    assert admin.get(f"/companies/{manual['id']}").json()["odoo_status"] == "NOT_CHECKED"


@pytest.mark.parametrize("first_deleted", ["older", "newer"])
def test_deleting_one_of_two_identical_imports(client_for, db, first_deleted):
    admin, _ = client_for(UserRole.ADMIN)
    content = xlsx_bytes(CRM_HEADERS, CRM_ROWS)
    _, older = run_import(admin, "ODOO_CRM", content, "odoo_crm.xlsx")
    _, newer = run_import(admin, "ODOO_CRM", content, "odoo_crm.xlsx")
    first, second = (older, newer) if first_deleted == "older" else (newer, older)

    result = admin.delete(f"/imports/{first['id']}", params={"with_data": "true"}).json()

    # The other import still contains every record, so nothing is removed yet.
    assert result["removed"] == {"crm_records": 0, "odoo_contacts": 0, "companies": 0, "salespeople": 0}
    db.expire_all()
    assert db.scalar(select(func.count(CrmLead.id))) == 4
    result = admin.delete(f"/imports/{second['id']}", params={"with_data": "true"}).json()
    assert result["removed"] == {"crm_records": 4, "odoo_contacts": 0, "companies": 4, "salespeople": 2}
    db.expire_all()
    assert db.scalar(select(func.count(Company.id))) == 0


def test_delete_only_then_reimport_then_delete_with_data(client_for, db):
    """Upload -> delete import only -> import again -> delete import + data leaves nothing behind."""
    admin, _ = client_for(UserRole.ADMIN)
    content = xlsx_bytes(CONTACT_HEADERS, CONTACT_ROWS)
    _, first = run_import(admin, "ODOO_CONTACTS", content, "odoo_contacts.xlsx")
    admin.delete(f"/imports/{first['id']}")
    db.expire_all()
    assert db.scalar(select(func.count(OdooContact.id))) == 5

    _, second = run_import(admin, "ODOO_CONTACTS", content, "odoo_contacts.xlsx")
    assert (second["inserted_count"], second["updated_count"]) == (0, 5)
    result = admin.delete(f"/imports/{second['id']}", params={"with_data": "true"}).json()

    assert result["removed"]["odoo_contacts"] == 5 and result["removed"]["companies"] == 2
    db.expire_all()
    assert db.scalar(select(func.count(OdooContact.id))) == 0
    assert db.scalar(select(func.count(Company.id))) == 0


def test_preview_can_be_deleted_and_permissions(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    agent, _ = client_for(UserRole.SALES_AGENT)
    preview = upload(admin, "ODOO_CONTACTS", xlsx_bytes(CONTACT_HEADERS, CONTACT_ROWS), "c.xlsx").json()
    run_id = preview["run"]["id"]
    assert agent.delete(f"/imports/{run_id}").status_code == 403
    assert admin.delete(f"/imports/{run_id}", params={"with_data": "true"}).status_code == 200
    assert admin.delete(f"/imports/{run_id}").status_code == 404
    assert db.scalar(select(func.count(OdooContact.id))) == 0


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
    assert company_named(agent, "Cedar Hotels")["crm_status_reason"].startswith("Existing customer: won opportunity")

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


# ---- Contacts-list regression (Company / Contact / Position / Phone / Email / Country / City / Status) ----

LIST_HEADERS = ["Company", "Contact", "Position", "Phone", "Email", "Country", "City", "Status"]
LIST_ROWS = [
    ["Levant Retail Supply", "Samer Habib", "Managing Director", "+961 3 555 120", "samer.habib@levantretail.test",
     "Lebanon", "Beirut", "Ready"],
    ["Cedars Food Industries SAL", "Karim Haddad", "General Manager", "+961 3 555 101",
     "karim.haddad@cedarsfood.test", "Lebanon", "Beirut", "Ready"],
    ["Mount Lebanon Trading Co.", "Joseph Nassar", "Managing Director", "+961 3 555 104",
     "joseph.nassar@mltrading.test", "Lebanon", "Baabda", "Ready"],
]


def test_contacts_list_persists_every_field_and_links_the_contact(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    preview, run = run_import(admin, "ODOO_CONTACTS", xlsx_bytes(LIST_HEADERS, LIST_ROWS), "list.xlsx")
    assert preview["unmapped_columns"] == ["Status"]  # import metadata, ignored
    assert (run["inserted_count"], run["warning_count"], run["companies_created"]) == (3, 0, 3)

    levant = company_named(admin, "Levant Retail Supply")
    # Company: identity, location, phone and email from the row; labelled as a contacts import.
    assert (levant["country"], levant["city"]) == ("Lebanon", "Beirut")
    assert levant["main_phone"] == "+961 3 555 120"
    assert levant["main_email"] == "samer.habib@levantretail.test"
    assert levant["source_label"] == "Odoo contact import"
    # Contact: linked to the company with every field.
    assert len(levant["contacts"]) == 1
    samer = levant["contacts"][0]
    assert (samer["full_name"], samer["job_title"], samer["business_phone"], samer["business_email"]) == (
        "Samer Habib", "Managing Director", "+961 3 555 120", "samer.habib@levantretail.test")
    assert samer["company_id"] == levant["id"] and samer["source"] == "ODOO_IMPORT"
    odoo = levant["relationship"]["odoo_contacts"][0]
    assert (odoo["contact_name"], odoo["job_position"], odoo["city"], odoo["country"]) == (
        "Samer Habib", "Managing Director", "Beirut", "Lebanon")
    # A person is never a company.
    assert admin.get("/companies", params={"q": "Samer"}).json()["total"] == 0
    assert db.scalar(select(func.count(Company.id))) == 3


def test_contacts_import_never_creates_crm_records(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    run_import(admin, "ODOO_CONTACTS", xlsx_bytes(LIST_HEADERS, LIST_ROWS), "list.xlsx")

    assert db.scalar(select(func.count(CrmLead.id))) == 0
    levant = company_named(admin, "Levant Retail Supply")
    assert levant["odoo_status"] == "EXISTING_CONTACT" and levant["is_protected"] is True
    assert levant["crm_status_reason"].startswith("Existing Odoo contact")
    assert "opportunity" not in levant["crm_status_reason"].replace("No CRM lead or opportunity", "").lower()
    assert levant["relationship"]["crm_records"] == []
    assert admin.get("/odoo/leads").json()["total"] == 0


def test_contacts_list_uploaded_as_crm_is_rejected(client_for, db):
    """The same file in the CRM panel must not become opportunities named after companies."""
    admin, _ = client_for(UserRole.ADMIN)
    response = upload(admin, "ODOO_CRM", xlsx_bytes(LIST_HEADERS, LIST_ROWS), "list.xlsx")
    assert response.status_code == 422
    assert "upload it under Odoo contacts" in response.json()["detail"]
    assert db.scalar(select(func.count(CrmLead.id))) == 0 and db.scalar(select(func.count(Company.id))) == 0


def test_contacts_reimport_updates_instead_of_duplicating_contacts(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    content = xlsx_bytes(LIST_HEADERS, LIST_ROWS)
    run_import(admin, "ODOO_CONTACTS", content, "list.xlsx")
    _, again = run_import(admin, "ODOO_CONTACTS", content, "list.xlsx")

    assert (again["inserted_count"], again["updated_count"], again["companies_created"]) == (0, 3, 0)
    assert db.scalar(select(func.count(Contact.id))) == 3
    assert db.scalar(select(func.count(OdooContact.id))) == 3
    assert len(company_named(admin, "Levant Retail Supply")["contacts"]) == 1


def test_existing_company_values_are_not_overwritten_and_manual_contacts_stay(client_for, db):
    admin, _ = client_for(UserRole.ADMIN)
    created = admin.post("/companies", json={"name": "Levant Retail Supply SAL", "main_phone": "01 999 999",
                                             "country": "Lebanon"}).json()
    assert admin.post("/contacts", json={"company_id": created["id"], "first_name": "Manual", "last_name": "Person"}).status_code == 201
    _, run = run_import(admin, "ODOO_CONTACTS", xlsx_bytes(LIST_HEADERS, LIST_ROWS[:1]), "list.xlsx")

    detail = admin.get(f"/companies/{created['id']}").json()
    assert detail["main_phone"] == "01 999 999"  # kept
    assert detail["main_email"] == "samer.habib@levantretail.test"  # was empty, filled
    assert sorted(c["full_name"] for c in detail["contacts"]) == ["Manual Person", "Samer Habib"]

    admin.delete(f"/imports/{run['id']}", params={"with_data": "true"})
    detail = admin.get(f"/companies/{created['id']}").json()
    assert [c["full_name"] for c in detail["contacts"]] == ["Manual Person"]  # imported contact removed
