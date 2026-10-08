"""Phase 1: automatic company discovery.

Sources are replaced by fakes here (no network in tests). The Overture provider itself
is tested against a small local GeoParquet file in Overture's schema.
"""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import Company, CompanySourceRecord, CrmLead, DiscoveryResult, DiscoveryRun, OdooMatch
from app.models.enums import UserRole
from app.services.discovery import service as discovery_service
from app.services.discovery.base import Candidate, ProviderError, SearchQuery, SearchResult
from app.services.discovery.geography import AREAS, COUNTRIES, canonical_city, in_area
from app.services.discovery.industries import INDUSTRY_BY_KEY, CustomProfile
from app.services.discovery.overture import OvertureProvider
from app.services.normalization import company_domain, normalize_company_name, normalize_phone
from scripts.sample_odoo_files import CONTACT_HEADERS, CONTACT_ROWS, CRM_HEADERS, CRM_ROWS, xlsx_bytes


def cand(external_id: str, name: str, **kw) -> Candidate:
    kw.setdefault("country", "Lebanon")
    kw.setdefault("score", 2.0)
    return Candidate(source=kw.pop("source", "OVERTURE"), external_id=external_id, name=name, **kw)


class FakeProvider:
    def __init__(self, key: str, candidates: list[Candidate] | None = None, error: str | None = None):
        self.key, self.label = key, {"OVERTURE": "Overture Maps", "OSM": "OpenStreetMap"}.get(key, key)
        self.candidates, self.error = candidates or [], error
        self.queries: list[SearchQuery] = []

    def search(self, query, progress):
        self.queries.append(query)
        if self.error:
            raise ProviderError(self.error)
        progress(self.label, f"{len(self.candidates)} matching places")
        return SearchResult(candidates=list(self.candidates), version="test-release")


@pytest.fixture
def providers(monkeypatch):
    """Set the discovery sources for a test: providers([FakeProvider(...), ...])."""
    def _set(items):
        monkeypatch.setattr(discovery_service, "provider_factory", lambda: items)
        return items
    return _set


FOODS = [
    cand("ov-1", "Cedar Valley Foods S.A.L.", phone="+961 8 540 082", website="https://www.cedarvalleyfoods.example/",
         city="Zahle", category="Manufacturer", latitude=33.846, longitude=35.902),
    cand("ov-2", "Beirut Dairy Industries", phone="01 444 555", city="Beirut", category="Dairy farm"),
    cand("ov-3", "CEDAR VALLEY FOODS SAL", phone="+961 8 540082", city="Zahle", category="Manufacturer"),  # same company
    cand("ov-4", "Tripoli Flour Mills", website="http://instagram.com/tripoliflour", city="Tripoli"),
    cand("ov-5", "Saida Sweets Factory", website="https://www.instagram.com/saidasweets", city="Saida"),
]


def start(client, **body):
    body.setdefault("industry", "food_manufacturing")
    body.setdefault("requested_count", 100)
    response = client.post("/discovery/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def results(client, run_id: int, **params) -> list[dict]:
    params.setdefault("page_size", 100)
    return client.get(f"/discovery/runs/{run_id}/results", params=params).json()["items"]


def test_run_saves_new_companies_with_provenance(client_for, db, providers):
    agent, user = client_for(UserRole.SALES_AGENT)
    providers([FakeProvider("OVERTURE", FOODS)])

    run = start(agent)

    assert run["status"] == "COMPLETED" and run["query_label"] == "Food Manufacturing · All Lebanon"
    assert (run["source_match_count"], run["raw_results_count"], run["new_company_count"], run["duplicate_count"]) == (5, 5, 4, 1)
    assert run["sources"] == ["OVERTURE"] and "Overture Maps test-release" in run["source_version"]
    assert [p["key"] for p in run["progress"]][-1] == "done"
    rows = {r["external_id"]: r for r in results(agent, run["id"])}
    assert rows["ov-1"]["state"] == "AVAILABLE" and rows["ov-3"]["state"] == "DUPLICATE"
    assert rows["ov-3"]["duplicate_of_id"] == rows["ov-1"]["id"]

    company = db.get(Company, rows["ov-1"]["company"]["id"])
    assert (company.name, company.source, company.industry, company.city) == (
        "Cedar Valley Foods S.A.L.", "DISCOVERY", "Food Manufacturing", "Zahle")
    assert company.domain == "cedarvalleyfoods.example" and company.main_phone_normalized == "+9618540082"
    assert company.created_by == user.id and company.source_label == "Overture Maps"
    record = db.scalar(select(CompanySourceRecord).where(CompanySourceRecord.external_id == "ov-1"))
    assert record.company_id == company.id and record.source == "OVERTURE" and record.first_seen_run_id == run["id"]
    detail = agent.get(f"/companies/{company.id}").json()
    assert detail["sources"][0]["source_label"] == "Overture Maps"
    # Instagram "websites" are kept as links but never used to match companies.
    ig = db.get(Company, rows["ov-4"]["company"]["id"])
    assert ig.website.startswith("http://instagram.com") and ig.domain is None
    assert rows["ov-5"]["state"] == "AVAILABLE"  # not merged with ov-4 on instagram.com
    # Discovery never creates CRM records.
    assert db.scalar(select(func.count(CrmLead.id))) == 0


def test_rerunning_the_same_search_creates_no_duplicates(client_for, db, providers):
    agent, _ = client_for(UserRole.SALES_AGENT)
    providers([FakeProvider("OVERTURE", FOODS)])
    first = start(agent)
    companies = db.scalar(select(func.count(Company.id)))

    second = start(agent)

    assert second["new_company_count"] == 0 and second["existing_company_count"] == 4 and second["duplicate_count"] == 1
    assert db.scalar(select(func.count(Company.id))) == companies
    reasons = {r["external_id"]: r["reason"] for r in results(agent, second["id"])}
    assert "source id" in reasons["ov-1"]
    record = db.scalar(select(CompanySourceRecord).where(CompanySourceRecord.external_id == "ov-1"))
    db.refresh(record)
    assert (record.first_seen_run_id, record.last_seen_run_id) == (first["id"], second["id"])
    assert "No new companies" in second["summary"] or second["summary"].startswith("0 new companies")


def test_existing_leadfinder_company_is_matched_not_duplicated(client_for, db, providers):
    agent, _ = client_for(UserRole.SALES_AGENT)
    manual = agent.post("/companies", json={"name": "Beirut Dairy Industries SARL", "city": "Beirut"}).json()
    providers([FakeProvider("OVERTURE", FOODS[:2])])

    run = start(agent)

    rows = {r["external_id"]: r for r in results(agent, run["id"])}
    assert rows["ov-2"]["state"] == "EXISTING_LEADFINDER" and rows["ov-2"]["company"]["id"] == manual["id"]
    assert "name" in rows["ov-2"]["reason"].lower()
    # The source's phone fills the blank on the existing company; nothing is overwritten.
    db.expire_all()
    assert db.get(Company, manual["id"]).main_phone == "01 444 555"
    assert db.get(Company, manual["id"]).source == "MANUAL"
    assert run["new_company_count"] == 1


def test_odoo_contact_and_crm_protection(client_for, db, providers):
    admin, _ = client_for(UserRole.ADMIN)
    for kind, headers, rows_ in (("ODOO_CRM", CRM_HEADERS, CRM_ROWS), ("ODOO_CONTACTS", CONTACT_HEADERS, CONTACT_ROWS)):
        preview = admin.post("/imports", data={"import_type": kind},
                             files={"file": ("f.xlsx", xlsx_bytes(headers, rows_), "application/octet-stream")}).json()
        assert admin.post(f"/imports/{preview['run']['id']}/confirm").status_code == 200
    companies_before = db.scalar(select(func.count(Company.id)))
    providers([FakeProvider("OVERTURE", [
        cand("p-1", "ABC Foods", city="Beirut"),                           # open opportunity in CRM
        cand("p-2", "Cedar Hotels", city="Beirut"),                        # won: customer
        cand("p-3", "Pharma Mount Lebanon Labs", phone="+961 5 777 888"),  # phone of an Odoo contact company
        cand("p-4", "Doe Consulting", phone="+961 70 123 456"),            # phone of an Odoo person, no company
        cand("p-5", "Brand New Bakery Industries", city="Tyre"),
    ])])

    run = start(admin, industry=None, custom_query="bakery")

    states = {r["external_id"]: r["state"] for r in results(admin, run["id"])}
    assert states == {"p-1": "OPEN_OPPORTUNITY", "p-2": "CUSTOMER", "p-3": "EXISTING_ODOO_CONTACT",
                      "p-4": "EXISTING_ODOO_CONTACT", "p-5": "AVAILABLE"}
    assert (run["odoo_protected_count"], run["new_company_count"]) == (4, 1)
    # Protected candidates are kept in the history but not saved as new companies.
    assert db.scalar(select(func.count(Company.id))) == companies_before + 1
    reason = next(r["reason"] for r in results(admin, run["id"]) if r["external_id"] == "p-4")
    assert reason.startswith("Existing Odoo contact")
    protected = results(admin, run["id"], group="protected")
    assert {r["external_id"] for r in protected} == {"p-1", "p-2", "p-3", "p-4"}
    assert db.scalar(select(func.count(CrmLead.id))) == 4  # still only the imported CRM records


def test_available_after_odoo_import_and_status_history(client_for, db, providers):
    admin, _ = client_for(UserRole.ADMIN)
    preview = admin.post("/imports", data={"import_type": "ODOO_CONTACTS"},
                         files={"file": ("c.xlsx", xlsx_bytes(CONTACT_HEADERS, CONTACT_ROWS), "application/octet-stream")}).json()
    admin.post(f"/imports/{preview['run']['id']}/confirm")
    providers([FakeProvider("OVERTURE", FOODS[:1])])

    run = start(admin)

    company_id = results(admin, run["id"])[0]["company"]["id"]
    detail = admin.get(f"/companies/{company_id}").json()
    assert detail["odoo_status"] == "AVAILABLE" and detail["is_protected"] is False
    assert db.scalar(select(func.count(OdooMatch.id)).where(OdooMatch.company_id == company_id)) == 1


def test_requested_count_stops_early_and_explains_shortfall(client_for, providers):
    agent, _ = client_for(UserRole.SALES_AGENT)
    providers([FakeProvider("OVERTURE", [cand(f"n-{i}", f"Factory Number {i} Foods", city="Zahle") for i in range(10)])])

    capped = start(agent, requested_count=3)
    assert capped["new_company_count"] == 3 and capped["raw_results_count"] == 3
    assert capped["summary"] == "3 new companies saved."

    more = start(agent, requested_count=25)
    assert more["new_company_count"] == 7 and more["existing_company_count"] == 3
    assert "of the 25 requested" in more["summary"] and "returned 10 places" in more["summary"]


def test_failed_and_partially_completed_runs(client_for, db, providers):
    agent, _ = client_for(UserRole.SALES_AGENT)
    providers([FakeProvider("OVERTURE", error="Overture data could not be queried (timeout). No companies were added.")])
    failed = start(agent)
    assert failed["status"] == "FAILED" and failed["new_company_count"] == 0
    assert failed["errors"][0].startswith("Overture Maps: Overture data could not be queried")
    assert db.scalar(select(func.count(Company.id))) == 0

    providers([FakeProvider("OVERTURE", FOODS[:2]), FakeProvider("OSM", error="OpenStreetMap could not be queried.")])
    partial = start(agent)
    assert partial["status"] == "PARTIAL" and partial["new_company_count"] == 2 and partial["error_count"] == 1
    assert partial["sources"] == ["OVERTURE"]


def test_sources_are_merged_across_providers(client_for, providers):
    agent, _ = client_for(UserRole.SALES_AGENT)
    providers([
        FakeProvider("OVERTURE", [cand("ov-9", "Liban Dairy", phone="+961 8 500 500", city="Zahle")]),
        FakeProvider("OSM", [cand("node/9", "Liban Dairy SAL", source="OSM", phone="08 500 500", city="Zahle", score=1.0)]),
    ])
    run = start(agent)
    rows = {r["external_id"]: r for r in results(agent, run["id"])}
    assert rows["ov-9"]["state"] == "AVAILABLE" and rows["node/9"]["state"] == "DUPLICATE"
    assert run["sources"] == ["OVERTURE", "OSM"]


def test_database_is_searched_too(client_for, providers):
    agent, _ = client_for(UserRole.SALES_AGENT)
    known = agent.post("/companies", json={"name": "Older Food Co", "industry": "Food Manufacturing", "country": "Lebanon"}).json()
    providers([FakeProvider("OVERTURE", FOODS[:1])])
    run = start(agent)
    rows = results(agent, run["id"])
    extra = next(r for r in rows if r["source"] == "LEADFINDER")
    assert extra["company"]["id"] == known["id"] and extra["state"] == "EXISTING_LEADFINDER"


def test_validation_permissions_history_and_delete(client_for, db, providers):
    admin, _ = client_for(UserRole.ADMIN)
    agent, _ = client_for(UserRole.SALES_AGENT)
    providers([FakeProvider("OVERTURE", FOODS)])
    assert agent.post("/discovery/runs", json={"country": "FR", "industry": "food_manufacturing"}).status_code == 422
    assert agent.post("/discovery/runs", json={"industry": "food_manufacturing", "custom_query": "x"}).status_code == 422
    assert agent.post("/discovery/runs", json={"industry": "nope"}).status_code == 422
    assert agent.post("/discovery/runs", json={"industry": "food_manufacturing", "city": "paris"}).status_code == 422
    options = agent.get("/discovery/options").json()
    assert options["countries"] == [{"code": "LB", "name": "Lebanon"}]
    assert "food_manufacturing" in [i["key"] for i in options["industries"]]

    run = start(agent)
    history = admin.get("/discovery/runs").json()
    assert history["total"] == 1 and history["items"][0]["creator"]["name"]
    assert agent.get("/discovery/runs", params={"mine": True}).json()["total"] == 1
    assert admin.get("/discovery/runs", params={"mine": True}).json()["total"] == 0

    # A company the user put in a campaign survives "delete with data".
    kept_id = results(agent, run["id"])[0]["company"]["id"]
    campaign = agent.post("/campaigns", json={"name": "Food push", "tecomsa_division": "ODOO", "country": "Lebanon",
                                             "target_company_count": 10}).json()
    assert agent.post(f"/campaigns/{campaign['id']}/companies/{kept_id}").status_code == 201

    assert agent.delete(f"/discovery/runs/{run['id']}").status_code == 403
    deleted = admin.delete(f"/discovery/runs/{run['id']}", params={"with_data": "true"}).json()
    assert (deleted["companies_removed"], deleted["companies_kept"]) == (3, 1)
    assert db.scalar(select(func.count(Company.id))) == 1
    assert db.scalar(select(func.count(DiscoveryResult.id))) == 0
    assert db.scalar(select(func.count(DiscoveryRun.id))) == 0
    assert db.scalar(select(func.count(CompanySourceRecord.id))) == 1  # the kept company keeps its provenance


def test_delete_without_data_keeps_companies(client_for, db, providers):
    admin, _ = client_for(UserRole.ADMIN)
    providers([FakeProvider("OVERTURE", FOODS[:2])])
    run = start(admin)
    result = admin.delete(f"/discovery/runs/{run['id']}").json()
    assert result == {"id": run["id"], "with_data": False, "companies_removed": 0, "companies_kept": 2}
    assert db.scalar(select(func.count(Company.id))) == 2


def test_results_filters_and_sorting(client_for, providers):
    agent, _ = client_for(UserRole.SALES_AGENT)
    providers([FakeProvider("OVERTURE", FOODS)])
    run = start(agent)
    page = agent.get(f"/discovery/runs/{run['id']}/results", params={"group": "available"}).json()
    assert page["total"] == 4 and page["counts"] == {"available": 4, "known": 0, "protected": 0, "duplicate": 1, "all": 5}
    assert [r["name"] for r in results(agent, run["id"], q="dairy")] == ["Beirut Dairy Industries"]
    names = [r["name"] for r in results(agent, run["id"], sort="name", group="available")]
    assert names == sorted(names, key=str.lower)
    assert results(agent, run["id"], source="OSM") == []


# ---- Overture provider on a real (small) GeoParquet file -------------------------------------


def _write_overture_extract(path: Path) -> None:
    import duckdb

    rows = [
        # id, name, primary, hierarchy, country, locality, lat, lon, phone, website, status
        ("o1", "Zahle Conserves Factory", "manufacturer", ["services_and_business", "b2b_service", "manufacturer"],
         "LB", "زحلة", 33.846, 35.902, "+9618540082", "http://zahleconserves.example", None),
        ("o2", "Beirut Burger", "burger_restaurant", ["food_and_drink", "restaurant", "burger_restaurant"],
         "LB", "بيروت", 33.89, 35.50, None, None, None),
        ("o3", "Tyre Dairy", "dairy_farm", ["services_and_business", "agricultural_service", "farm", "dairy_farm"],
         "LB", "صور", 33.27, 35.20, "+9617123456", None, None),
        ("o4", "Homs Foods Factory", "manufacturer", ["services_and_business", "b2b_service", "manufacturer"],
         "SY", "Homs", 34.7, 36.5, None, None, None),
        ("o5", "Closed Dairy", "dairy_farm", ["services_and_business", "agricultural_service", "farm", "dairy_farm"],
         "LB", None, 33.9, 35.5, None, None, "permanently_closed"),
    ]
    con = duckdb.connect()
    con.execute("""CREATE TABLE p (id VARCHAR, name VARCHAR, taxonomy STRUCT("primary" VARCHAR, hierarchy VARCHAR[], alternates VARCHAR[]),
        basic_category VARCHAR, confidence DOUBLE, operating_status VARCHAR, websites VARCHAR[], phones VARCHAR[], emails VARCHAR[],
        addresses STRUCT(freeform VARCHAR, locality VARCHAR, postcode VARCHAR, region VARCHAR, country VARCHAR)[],
        lon DOUBLE, lat DOUBLE, datasets VARCHAR[])""")
    for pid, name, primary, hierarchy, country, locality, lat, lon, phone, website, status in rows:
        con.execute(
            "INSERT INTO p VALUES (?, ?, {'primary': ?, 'hierarchy': ?, 'alternates': []}, ?, 0.8, ?, ?, ?, [], "
            "[{'freeform': 'Main road', 'locality': ?, 'postcode': NULL, 'region': NULL, 'country': ?}], ?, ?, ['meta'])",
            [pid, name, primary, hierarchy, primary, status, [website] if website else [], [phone] if phone else [],
             locality, country, lon, lat])
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY p TO '{path.as_posix()}' (FORMAT PARQUET)")
    con.close()


def test_overture_provider_parses_filters_country_industry_and_city(tmp_path):
    _write_overture_extract(tmp_path / "overture" / "TEST" / "places_LB.parquet")
    provider = OvertureProvider(tmp_path, "https://invalid.example/catalog.json", release="TEST")
    lb, food = COUNTRIES["LB"], INDUSTRY_BY_KEY["food_manufacturing"]
    stages = []

    everywhere = provider.search(SearchQuery(lb, None, food), lambda s, d: stages.append(d))
    assert [c.external_id for c in everywhere.candidates] == ["o3", "o1"]  # dairy_farm (strong) first; no SY, closed, restaurant
    top = everywhere.candidates[1]
    assert (top.name, top.city, top.country, top.phone, top.category) == (
        "Zahle Conserves Factory", "Zahle", "Lebanon", "+9618540082", "Manufacturer")
    assert top.data["release"] == "TEST" and everywhere.version == "TEST"
    assert "Using cached release TEST" in stages

    bekaa = provider.search(SearchQuery(lb, AREAS["LB"]["bekaa"], food), lambda *_: None)
    assert [c.external_id for c in bekaa.candidates] == ["o1"]
    tyre = provider.search(SearchQuery(lb, AREAS["LB"]["tyre"], food), lambda *_: None)
    assert [c.external_id for c in tyre.candidates] == ["o3"]


def test_overture_provider_reports_unreachable_catalog(tmp_path):
    provider = OvertureProvider(tmp_path, "https://invalid.invalid/catalog.json", timeout=2)
    with pytest.raises(ProviderError, match="no local copy"):
        provider.dataset(COUNTRIES["LB"], lambda *_: None)


# ---- Industry mapping, geography and normalisation ------------------------------------------


@pytest.mark.parametrize(("name", "nodes", "matches"), [
    ("Ghanem Frozen Foods", {"manufacturer"}, True),
    ("Linda Chocolate Factory", {"chocolatier", "shopping"}, True),
    ("Crown Flour Mills", {"food_and_drink"}, True),
    ("Rawabi Chtaura", {"dairy_farm"}, True),
    ("Beirut Burger", {"restaurant", "burger_restaurant"}, False),
    ("Chiraz Roastery", {"produce_store", "shopping"}, False),  # a roastery shop: one word is not both signals
    ("Hipco Paper Mills", {"manufacturer", "paper_mill"}, False),
    ("شركة زيتون للالمنيوم", {"metal_supplier"}, False),
    ("مصنع الأغذية الحديثة", {"manufacturer"}, True),
])
def test_food_manufacturing_mapping(name, nodes, matches):
    assert (INDUSTRY_BY_KEY["food_manufacturing"].score(name, nodes) is not None) is matches


def test_custom_industry_matches_words_in_name_and_category():
    profile = CustomProfile("Plastic packaging manufacturers in Lebanon")
    assert profile.words == ["plastic", "packag", "manufactur"]
    assert profile.score("Raznia", {"plastic_manufacturer", "manufacturer"}) is not None  # 2 of 3 words
    assert profile.score("Raznia", {"textile_manufacturer"}) is None


def test_areas_match_arabic_localities_and_coordinates():
    zahle = AREAS["LB"]["zahle"]
    assert in_area(zahle, None, None, ["زحلة البربارة"])
    assert in_area(zahle, 33.84, 35.90, [])
    assert not in_area(zahle, 33.89, 35.50, ["بيروت"])
    mount = AREAS["LB"]["mount_lebanon"]
    assert in_area(mount, 33.97, 35.61, []) and not in_area(mount, 33.894, 35.502, [])  # Beirut is carved out
    assert canonical_city("LB", 33.89, 35.50, "بيروت") == "Beirut"
    assert canonical_city("LB", 34.0, 35.7, "Bikfaya") == "Bikfaya"


def test_normalisation_used_by_discovery():
    assert {normalize_company_name(n) for n in ("ABC Foods SAL", "ABC Foods S.A.L.", "ABC FOODS S.A.L", "ABC Foods Holding",
                                                "ABC Foods ش.م.ل")} == {"abc foods"}
    assert {company_domain(u) for u in ("https://abcfoods.com", "http://abcfoods.com/", "www.abcfoods.com", "abcfoods.com")} == {"abcfoods.com"}
    assert company_domain("https://www.instagram.com/abcfoods") is None
    assert company_domain("https://abc-foods.business.site/") == "abc-foods.business.site"
    assert {normalize_phone(p, "Lebanon") for p in ("+961 3 123 456", "00961 3 123456", "03 123456")} == {"+9613123456"}
    assert normalize_phone("+33 1 23 45 67 89", "Lebanon") == "+33123456789"  # international numbers untouched


def test_settings_have_safe_defaults():
    s = get_settings()
    assert s.discovery_inline is True and s.osm_enabled is False  # test settings
    assert s.overture_stac_url.startswith("https://stac.overturemaps.org/")


def test_osm_provider_parses_cached_overpass_answer(tmp_path):
    import json

    from app.services.discovery.osm import OsmProvider

    (tmp_path / "osm").mkdir()
    (tmp_path / "osm" / "features_LB.json").write_text(json.dumps({"elements": [
        {"type": "way", "id": 1, "center": {"lat": 33.85, "lon": 35.90},
         "tags": {"name": "Liban Lait", "man_made": "works", "product": "dairy", "phone": "+961 8 900 900"}},
        {"type": "node", "id": 2, "lat": 33.86, "lon": 35.93, "tags": {"name": "Chateau Test", "craft": "winery"}},
        {"type": "node", "id": 3, "lat": 33.89, "lon": 35.50, "tags": {"name": "Some Office", "office": "company"}},
    ]}), encoding="utf-8")
    provider = OsmProvider(tmp_path, "https://invalid.invalid/api/interpreter")
    lb = COUNTRIES["LB"]

    food = provider.search(SearchQuery(lb, None, INDUSTRY_BY_KEY["food_manufacturing"]), lambda *_: None)
    assert [(c.external_id, c.name, c.city, c.phone) for c in food.candidates] == [("way/1", "Liban Lait", "Zahle", "+961 8 900 900")]
    drinks = provider.search(SearchQuery(lb, AREAS["LB"]["bekaa"], INDUSTRY_BY_KEY["beverage_manufacturing"]), lambda *_: None)
    assert [c.external_id for c in drinks.candidates] == ["node/2"]


def test_city_label_never_contradicts_coordinates():
    assert canonical_city("LB", 33.804, 35.806, "Beirut") is None  # text says Beirut, the place is in the Bekaa
    assert canonical_city("LB", 33.87, 35.52, "Beirut") == "Beirut"
