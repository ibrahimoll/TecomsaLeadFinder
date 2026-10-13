"""Licensed directory import (a 5INDEX export): columns detected from French / English headers, a dry run that is
exactly the apply, companies LeadFinder lacks created once (never duplicated), people with their titles and mobiles,
a company row's contact points, 'licensed' provenance, idempotent re-import, removal of an import, the API."""

import io

from openpyxl import Workbook
from sqlalchemy import func, select

from app.models import Company, CompanyPerson, Email, Person, Phone, Source
from app.models.enums import UserRole
from app.services import contributions

FRENCH = ["Raison sociale", "Gérant", "Téléphone", "Portable", "Fax", "E-mail", "Site web", "Activité", "Ville",
          "Remarques"]


def xlsx(header: list[str], *rows: list) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(["Export 5INDEX - fictional sample"])  # a title line above the header
    for row in (header, *rows):
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def sample() -> bytes:
    return xlsx(FRENCH,
                ["Zeta Plastics SARL", "Karim Haddad", "01 234 567", "03 123 456", "01 234 568",
                 "karim@zetaplastics.example", "www.zetaplastics.example", "Plastics manufacturing", "Beirut", "x"],
                ["Zeta Plastics SARL", "Rita Saliba", "01 234 567", "71 222 333", "", "", "www.zetaplastics.example",
                 "Plastics manufacturing", "Beirut", ""],  # the same company again: one company
                ["Nour Bakery", "", "05 444 555", "", "", "info@nourbakery.example", "", "Bakery", "Aley", ""],
                ["Delta Trading", "Sami Kassab", "", "76 111 222", "", "", "", "Trading", "Beirut", ""])


def counts(db) -> tuple:
    return tuple(db.scalar(select(func.count()).select_from(m)) for m in (Company, Person, CompanyPerson, Email, Phone))


def test_directory_import_dry_run_apply_reimport_and_removal(db, make_user):
    owner = make_user(UserRole.SALES_MANAGER)
    delta = Company(name="Delta Trading", normalized_name="delta trading", headquarters_country="Lebanon")
    db.add(delta)
    db.commit()
    before = counts(db)
    dry = contributions.import_directory(db, file_name="5index.xlsx", raw=sample(), directory="5INDEX",
                                         user_id=owner.id)
    assert counts(db) == before and dry["import_id"] is None  # a dry run writes nothing
    assert dry["columns"]["detected"] == {
        "email": "E-mail", "mobile": "Portable", "website": "Site web", "phone": "Téléphone",
        "company": "Raison sociale", "person": "Gérant", "sector": "Activité", "city": "Ville"}
    assert (dry["columns"]["ignored"], dry["columns"]["unrecognised"]) == (["Fax"], ["Remarques"])
    assert dry["summary"] == {"rows": 4, "companies_new": 2, "companies_existing": 1, "people": 3, "people_new": 3,
                              "mobiles": 3, "whatsapp": 0, "phones": 2, "emails": 2,
                              "rows_skipped": 0}

    applied = contributions.import_directory(db, file_name="5index.xlsx", raw=sample(), directory="5INDEX",
                                             user_id=owner.id, apply=True)
    assert {k: v for k, v in applied.items() if k not in ("applied", "review", "import_id")} == {
        k: v for k, v in dry.items() if k not in ("applied", "review", "import_id")}  # the preview was the import
    zeta = db.scalar(select(Company).where(Company.name == "Zeta Plastics SARL"))
    assert db.scalar(select(func.count()).select_from(Company).where(Company.name.like("Zeta%"))) == 1
    assert (zeta.headquarters_country, zeta.primary_phone) == ("Lebanon", "01 234 567")
    karim = db.scalar(select(CompanyPerson).join(Person).where(Person.full_name == "Karim Haddad"))
    assert (karim.company_id, karim.job_title) == (zeta.id, "Gérant")  # the column's role is his title
    mobile = db.scalar(select(Phone).where(Phone.person_id == karim.person_id))
    assert (mobile.normalized_phone, mobile.phone_type, mobile.provenance) == ("+9613123456", "business_mobile",
                                                                               "licensed")
    switchboard = db.scalar(select(Phone).where(Phone.company_id == zeta.id, Phone.person_id.is_(None)))
    assert (switchboard.phone_type, switchboard.provenance) == ("company_switchboard", "licensed")
    nour = db.scalar(select(Company).where(Company.name == "Nour Bakery"))
    assert db.scalar(select(Email.email).where(Email.company_id == nour.id, Email.person_id.is_(None))) == \
        "info@nourbakery.example"  # a row naming nobody: the company's contact points
    sami = db.scalar(select(CompanyPerson).join(Person).where(Person.full_name == "Sami Kassab"))
    assert sami.company_id == delta.id  # the company LeadFinder knew: reused, never duplicated
    assert {s.name for s in db.scalars(select(Source).where(Source.source_type == "licensed_directory"))} == {
        "5INDEX (licensed directory)"}
    assert contributions.coverage(db) == [{
        "directory": "5INDEX", "people": 3, "people_with_mobile": 3, "people_with_whatsapp": 0, "people_with_email": 1,
        "companies_with_number": 2}]

    after = counts(db)
    again = contributions.import_directory(db, file_name="5index.xlsx", raw=sample(), directory="5INDEX",
                                           user_id=owner.id, apply=True)
    assert counts(db) == after and again["summary"]["companies_new"] == 0  # idempotent

    assert [i["import_id"] for i in contributions.imports(db)] == [again["import_id"], applied["import_id"]]
    other = contributions.import_directory(db, file_name="yelleb.xlsx", raw=sample(), directory="Yelleb",
                                           user_id=owner.id, apply=True)
    assert counts(db) == after and other["summary"]["companies_new"] == 0  # the same records: corroborated
    assert [c["directory"] for c in contributions.coverage(db)] == ["5INDEX", "Yelleb"]
    contributions.remove_import(db, other["import_id"], user_id=owner.id)  # one directory removed alone
    assert counts(db) == after and [c["directory"] for c in contributions.coverage(db)] == ["5INDEX"]
    first = contributions.remove_import(db, applied["import_id"], user_id=owner.id)
    assert first == {"companies_kept": 2}  # the re-import still states everything
    assert counts(db) == after
    removed = contributions.remove_import(db, again["import_id"], user_id=owner.id)
    assert removed["companies_removed"] == 2 and db.get(Company, delta.id) is not None
    assert db.get(CompanyPerson, sami.id) is None  # known only from the import
    assert db.scalar(select(func.count()).select_from(Phone)) == 0
    assert all(i["removed_at"] for i in contributions.imports(db))


def test_english_headers_and_the_import_api(client_for, db):
    agent, _ = client_for(UserRole.SALES_AGENT)
    manager, _ = client_for(UserRole.SALES_MANAGER)
    raw = xlsx(["Company", "Contact Person", "Position", "Tel", "Mobile", "WhatsApp Number", "Email", "Website",
                "Sector", "City"],
               ["Omicron Steel", "Lina Nasr", "Purchasing Manager", "09 222 333", "81 555 666", "+961 3 777 888",
                "lina@omicronsteel.example", "omicronsteel.example", "Steel", "Jbeil"],
               ["Omicron Steel", "John Doe", "", "", "70 999 888", "", "", "", "", ""])  # no title: not a person
    files = {"file": ("export.xlsx", raw, "application/octet-stream")}
    yelleb = {"directory": "Yelleb"}
    assert agent.post("/imports/directory/preview", files=files, data=yelleb).status_code == 403
    assert manager.post("/imports/directory/preview", files=files, data={"directory": " "}).status_code == 422
    preview = manager.post("/imports/directory/preview", files=files, data=yelleb).json()
    assert preview["columns"]["detected"]["title"] == "Position" and preview["columns"]["unrecognised"] == []
    assert preview["columns"]["detected"]["whatsapp"] == "WhatsApp Number"  # its own channel, not the mobile
    assert (preview["summary"]["people"], preview["summary"]["mobiles"], preview["summary"]["whatsapp"]) == (1, 1, 1)
    assert any("no job title" in r["reason"] for r in preview["review"])
    assert manager.post("/imports/directory", files=files, data=yelleb).status_code == 422  # preview, then confirm
    done = manager.post("/imports/directory", files=files, data={**yelleb, "confirm": "true"})
    assert done.status_code == 201
    history = manager.get("/imports/directory").json()
    assert history[0]["import_id"] == done.json()["import_id"] and history[0]["summary"]["companies_new"] == 1
    assert history[0]["directory"] == "Yelleb"
    assert manager.get("/imports/directory/coverage").json() == [{
        "directory": "Yelleb", "people": 1, "people_with_mobile": 1, "people_with_whatsapp": 1, "people_with_email": 1,
        "companies_with_number": 1}]
    assert manager.post("/imports/directory/preview", files={"file": ("x.pdf", b"%PDF", "application/pdf")},
                        data=yelleb).status_code == 422
    assert manager.delete(f"/imports/directory/{done.json()['import_id']}").status_code == 204
    assert manager.delete(f"/imports/directory/{done.json()['import_id']}").status_code == 422  # already removed
    assert db.scalar(select(func.count()).select_from(Company)) == 0
    assert manager.get("/auth/me").json()["capabilities"]["run_imports"] is True


def test_5index_html_xls_and_father_name_left_out_of_the_mobile_label():
    # 5INDEX's "Excel" export: an HTML table written as '<td/>text</td>'; a mobile labelled without the father's name
    cells = ["ID #", "Company Name", "Mobile", "Executives"], [
        "1", "Fictional Trading Sarl", "+961 03 - 014500 (Mr. Minas  Avakian)",
        "Mr. Minas Antoun Avakian (Authorized Signatory) || Mr. Ara Antoun Avakian (Owner(s))"]
    raw = "<html><table>" + "".join("<tr>" + "".join(f"<td/>{c}</td>" for c in row) + "</tr>" for row in cells) + \
          "</table></html>"
    entries, info = contributions.directory_entries("5INDEX export.xls", raw.encode())
    assert info["detected"]["person"] == "Executives" and not info["review"]
    minas = next(e for e in entries if e.get("person") == "Minas Antoun Avakian")
    assert [n for n, _ in minas["phones"]] and "3014500" in "".join(filter(str.isdigit, minas["phones"][0][0]))


def test_rows_with_only_n_a_create_nothing(db, make_user):
    owner = make_user(UserRole.SALES_MANAGER)
    raw = xlsx(FRENCH,
               ["Empty Co", "N/A", "N/A", "n/a", "N/A", "N/A", "-", "Trading", "Beirut", ""],
               ["Labelled Co", "", "N/A (Store)", "", "", "", "", "Trading", "Beirut", ""],
               ["Real Co", "N/A", "01 234 567", "N/A", "", "N/A", "", "Trading", "Beirut", ""])
    before = db.scalar(select(func.count()).select_from(Company))
    report = contributions.import_directory(db, file_name="5index.xlsx", raw=raw, directory="5INDEX",
                                            user_id=owner.id, apply=True)
    names = set(db.scalars(select(Company.name)))
    assert db.scalar(select(func.count()).select_from(Company)) == before + 1 and "Real Co" in names
    assert report["rows_no_data"] == 2
    assert report["summary"]["rows"] == 3 and report["summary"]["rows_skipped"] == 2
    assert report["summary"]["people"] == 0 and report["summary"]["emails"] == 0


def test_second_mobile_and_person_columns_are_read():
    cells = ["Company Name", "Contact", "Title", "Mobile", "Mobile 2", "Phone #2"], [
        "Fictional Mills Sal", "Mr. Sami Fakhoury", "General Manager", "+961 3 111 222 (Mr. Sami Fakhoury)",
        "+961 70 333 444 (Mr. Sami Fakhoury)", "+961 1 555 666"]
    raw = "<html><table>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in cells) + \
          "</table></html>"
    entries, _ = contributions.directory_entries("export.xls", raw.encode())
    sami = next(e for e in entries if e.get("person") == "Sami Fakhoury")
    digits = {"".join(filter(str.isdigit, n)) for n, _ in sami["phones"]}
    assert any(d.endswith("3111222") for d in digits) and any(d.endswith("70333444") for d in digits)


def test_directory_people_are_not_shown_as_verified_and_the_reachable_one_leads(db, make_user):
    from app.models import ContactFeedback
    from app.services import company_service

    owner = make_user(UserRole.SALES_MANAGER)
    raw = xlsx(["Company Name", "Executives", "Mobile"],
               ["Fictional Metals Sarl", "Mr. Harma Jaghlasian (Owner(s)) || Mr. Harout Jaghlasian (Authorized Signatory)",
                "+961 71 - 951391 (Mr. Harout Jaghlasian)"])
    contributions.import_directory(db, file_name="5index.xlsx", raw=raw, directory="5INDEX", user_id=owner.id,
                                   apply=True)
    cid = db.scalar(select(Company.id).where(Company.name == "Fictional Metals Sarl"))
    people = {p["person"].full_name: p for p in company_service.company_people(db, cid, owner)}
    harma, harout = people["Harma Jaghlasian"], people["Harout Jaghlasian"]
    assert harout["is_key"] and not harma["is_key"]  # the one with a mobile leads, though an owner ranks higher
    assert harout["confirmed_at"] is None and harout["confidence"] <= 70  # a directory says so: not verified
    db.add(ContactFeedback(event="number_confirmed", company_id=cid, person_id=harout["person"].id,
                           phone_id=harout["phones"][0].id, user_id=owner.id))
    db.commit()
    harout = next(p for p in company_service.company_people(db, cid, owner) if p["person"].full_name == "Harout Jaghlasian")
    assert harout["confirmed_at"] is not None and harout["confidence"] > 70  # a colleague confirmed it


def test_a_row_with_only_names_never_creates_a_company(db, make_user):
    owner = make_user(UserRole.SALES_MANAGER)
    delta = Company(name="Delta Trading", normalized_name="delta trading", headquarters_country="Lebanon")
    db.add(delta)
    db.commit()
    raw = xlsx(FRENCH,
               ["Ghost Holding SAL", "Nadim Ghosn", "", "", "", "", "", "Holding", "", ""],  # a name and a person only
               ["Delta Trading", "Lina Aoun", "", "", "", "", "", "Trading", "Beirut", ""])  # known company: kept
    report = contributions.import_directory(db, file_name="5index.xlsx", raw=raw, directory="5INDEX",
                                            user_id=owner.id, apply=True)
    assert db.scalar(select(Company).where(Company.name == "Ghost Holding SAL")) is None
    assert report["summary"]["companies_new"] == 0 and report["summary"]["rows_skipped"] == 1
    assert any("not added as a new company" in r["reason"] for r in report["review"])
    assert db.scalar(select(func.count()).select_from(CompanyPerson).where(CompanyPerson.company_id == delta.id)) == 1
