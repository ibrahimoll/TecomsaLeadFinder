"""The real connectors, offline: each parses its source format into CompanyCandidates. Plus the SSRF and
resource limits of the website fetcher (every request to a company website goes through it)."""

import gzip
import json
import os
import threading
import time
from pathlib import Path

import httpx
import pytest

from app.services.discovery import fetch
from app.services.discovery.candidate import ConnectorConfig, ConnectorError, SearchQuery
from app.services.discovery.geography import find_area, find_country
from app.services.discovery.industries import profile_for

LB = find_country("Lebanon")
FOOD = profile_for("Food Manufacturing")


def cfg(kind: str, **options) -> ConnectorConfig:
    return ConnectorConfig(key=kind, kind=kind, enabled=True, countries=("LB",), priority=1,
                           source_type="open_dataset", quality=60, label=kind, options=options)


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
        ("o6", "Chicken Factory", "fast_food_restaurant", ["food_and_drink", "casual_eatery", "fast_food_restaurant"],
         "LB", "بيروت", 33.88, 35.51, "+9611999999", None, None),
    ]
    con = duckdb.connect()
    con.execute("""CREATE TABLE p (id VARCHAR, name VARCHAR, taxonomy STRUCT("primary" VARCHAR, hierarchy VARCHAR[],
        alternates VARCHAR[]), basic_category VARCHAR, confidence DOUBLE, operating_status VARCHAR, websites VARCHAR[],
        phones VARCHAR[], emails VARCHAR[], addresses STRUCT(freeform VARCHAR, locality VARCHAR, postcode VARCHAR,
        region VARCHAR, country VARCHAR)[], lon DOUBLE, lat DOUBLE, datasets VARCHAR[])""")
    for pid, name, primary, hierarchy, country, locality, lat, lon, phone, website, status in rows:
        con.execute(
            "INSERT INTO p VALUES (?, ?, {'primary': ?, 'hierarchy': ?, 'alternates': []}, ?, 0.8, ?, ?, ?, [], "
            "[{'freeform': 'Main road', 'locality': ?, 'postcode': NULL, 'region': NULL, 'country': ?}], ?, ?, "
            "['meta'])",
            [pid, name, primary, hierarchy, primary, status, [website] if website else [], [phone] if phone else [],
             locality, country, lon, lat])
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY p TO '{path.as_posix()}' (FORMAT PARQUET)")
    con.close()


def test_overture_connector(tmp_path):
    from app.services.discovery.connectors.overture import OvertureConnector

    _write_overture_extract(tmp_path / "overture" / "TEST" / "places_LB.parquet")
    connector = OvertureConnector(cfg("overture", stac_url="https://invalid.example/catalog.json", release="TEST"),
                                  tmp_path)
    result = connector.search_companies(SearchQuery(LB, None, FOOD, 10))
    assert [c.external_id for c in result.candidates] == ["o1", "o3", "o5", "o6"]  # no Syrian place, no burger
    top, dairy, closed, chicken = result.candidates
    assert (top.company_name, top.city, top.region, top.country, top.phone, top.tier, top.rejected) == (
        "Zahle Conserves Factory", "Zahle", "Bekaa", "Lebanon", "+9618540082", "industrial", None)
    assert top.source_name == "Overture Maps Places TEST" and top.raw_metadata["release"] == "TEST"
    assert (dairy.tier, dairy.datasets) == ("producer", ["meta"])
    assert (closed.rejected, closed.reject_reason) == ("CLOSED", "Overture marks it permanently closed.")
    assert chicken.rejected == "WRONG_INDUSTRY"
    tyre = connector.search_companies(SearchQuery(LB, find_area("LB", "Tyre"), FOOD, 10))
    assert [c.external_id for c in tyre.candidates] == ["o3"]
    with pytest.raises(ConnectorError):  # no catalog and no cache
        OvertureConnector(cfg("overture", stac_url="https://invalid.example/catalog.json"),
                          tmp_path / "empty").search_companies(SearchQuery(LB, None, FOOD, 10))


def test_osm_connector_from_cached_extract(tmp_path):
    from app.services.discovery.connectors.osm import OsmConnector

    elements = [
        {"type": "way", "id": 1, "lat": 33.89, "lon": 35.52, "tags": {"name": "Gandour Factory", "man_made": "works",
                                                                       "product": "chocolate", "phone": "01 234 567"}},
        {"type": "node", "id": 2, "lat": 33.90, "lon": 35.50, "tags": {"name": "Old Flour Mill", "craft": "bakery",
                                                                        "disused": "yes"}},
        {"type": "node", "id": 3, "lat": 33.89, "lon": 35.51, "tags": {"name": "BLOM Bank", "amenity": "bank"}},
        {"type": "node", "id": 4, "lat": 34.43, "lon": 35.85, "tags": {"name": "Tripoli Sweets Factory",
                                                                        "craft": "confectionery"}},
    ]
    (tmp_path / "osm").mkdir()
    (tmp_path / "osm" / "features_v2_LB.json").write_text(json.dumps({"elements": elements}), encoding="utf-8")
    connector = OsmConnector(cfg("osm"), tmp_path)
    beirut = connector.search_companies(SearchQuery(LB, find_area("LB", "Beirut"), FOOD, 10))
    assert [(c.company_name, c.rejected) for c in beirut.candidates] == [("Gandour Factory", None),
                                                                          ("Old Flour Mill", "CLOSED")]
    gandour = beirut.candidates[0]
    assert (gandour.source_url, gandour.facility, gandour.region) == (
        "https://www.openstreetmap.org/way/1", "Industrial site (OpenStreetMap: works)", "Beirut")
    banks = connector.search_companies(SearchQuery(LB, None, profile_for("Financial Services"), 10))
    assert [c.company_name for c in banks.candidates] == ["BLOM Bank"]


def test_wikidata_connector_parses_sparql_results(tmp_path):
    from app.services.discovery.connectors.wikidata import WikidataConnector

    def row(qid, name, type_label, website=None, hq=None, coord=None):
        r = {"c": {"value": f"http://www.wikidata.org/entity/{qid}"}, "cLabel": {"value": name},
             "typeLabel": {"value": type_label}}
        r |= {"website": {"value": website}} if website else {}
        r |= {"hqLabel": {"value": hq}} if hq else {}
        r |= {"coord": {"value": coord}} if coord else {}
        return r

    bindings = [row("Q1", "Château Musar", "winery", "https://chateaumusar.com", "Ghazir"),
                row("Q2", "Bank Audi", "bank", "https://www.bankaudi.com.lb", "Beirut", "Point(35.5 33.89)"),
                row("Q2", "Bank Audi", "business"),  # the same entity again: merged
                row("Q3", "Q3", "business")]  # no label in any language: skipped
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, json={"results": {"bindings": bindings}})

    connector = WikidataConnector(cfg("wikidata"), tmp_path, transport=httpx.MockTransport(handler))
    banks = connector.search_companies(SearchQuery(LB, find_area("LB", "Beirut"), profile_for("Financial Services"), 5))
    assert [(c.company_name, c.website, c.external_id) for c in banks.candidates] == [
        ("Bank Audi", "https://www.bankaudi.com.lb", "Q2")]
    assert banks.candidates[0].source_url == "https://www.wikidata.org/wiki/Q2"
    wine = connector.search_companies(SearchQuery(LB, None, profile_for("Food & Beverage"), 5))
    assert [c.company_name for c in wine.candidates] == ["Château Musar"]
    assert len(seen) == 1 and "LeadFinder" in seen[0]  # one query, cached, identifying user agent


def test_an_expired_cache_is_used_while_it_refreshes_in_the_background(tmp_path):
    from app.services.discovery.connectors import wikidata

    def bank(qid, name):
        return {"c": {"value": f"http://www.wikidata.org/entity/{qid}"}, "cLabel": {"value": name},
                "typeLabel": {"value": "bank"}}

    path = tmp_path / "wikidata" / "companies_LB.json"
    path.parent.mkdir()
    path.write_text(json.dumps([bank("Q8", "Old Bank")]), encoding="utf-8")
    os.utime(path, (0, 0))  # expired long ago
    gate = threading.Event()

    def handler(request):
        gate.wait(5)  # a slow query service
        return httpx.Response(200, json={"results": {"bindings": [bank("Q9", "New Bank")]}})

    connector = wikidata.WikidataConnector(cfg("wikidata"), tmp_path, transport=httpx.MockTransport(handler))
    banks = SearchQuery(LB, None, profile_for("Financial Services"), 5)
    started = time.monotonic()
    assert [c.company_name for c in connector.search_companies(banks).candidates] == ["Old Bank"]
    assert time.monotonic() - started < 2  # served from the cache, not waiting for the network
    gate.set()
    for _ in range(50):
        if not wikidata._refreshing.locked():
            break
        time.sleep(0.1)
    assert [c.company_name for c in connector.search_companies(banks).candidates] == ["New Bank"]


def test_public_web_connector_without_a_provider_and_with_one():
    from app.services.discovery.connectors.public_web import PublicWebConnector, WebResult

    config = ConnectorConfig(key="web", kind="public_web", enabled=True, countries=(), priority=90,
                             source_type="public_web", quality=30)
    with pytest.raises(ConnectorError):
        PublicWebConnector(config).search_companies(SearchQuery(LB, None, FOOD, 10))

    class Engine:
        def search(self, query, limit):
            return [WebResult("ABC Foods | Home", "https://www.abcfoods.example/"),
                    WebResult("ABC Foods on Facebook", "https://facebook.com/abcfoods")]

    result = PublicWebConnector(config, Engine()).search_companies(SearchQuery(LB, None, FOOD, 10))
    assert [(c.company_name, c.tier, c.source_type) for c in result.candidates] == [("ABC Foods", "name", "public_web")]


# ---- website fetcher: SSRF and resource limits -----------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1/", "http://[::1]/", "http://0.0.0.0/", "http://10.0.0.5/",
    "http://192.168.1.1/", "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/",
    "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::a9fe:a9fe]/", "http://[2002:7f00:1::]/", "http://[fd00::1]/",
    "http://[fe80::1]/", "http://2130706433/", "http://0x7f.1/", "http://017700000001/", "http://db/",
    "http://backend:8000/", "http://example.com:5432/", "https://user:pw@example.com/", "ftp://example.com/",
    "file:///etc/passwd", "gopher://example.com/", "http://intranet.local/", "http://metadata.google.internal/",
])
def test_ssrf_targets_are_blocked(url, monkeypatch):
    real = fetch.resolve
    monkeypatch.setattr(fetch, "resolve", lambda host: ["172.18.0.2"] if host in ("db", "backend") else real(host))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.check_url(url)
    assert exc.value.kind in ("BLOCKED_ADDRESS", "INVALID_URL", "DNS")


def test_redirect_to_internal_address_is_blocked(monkeypatch):
    monkeypatch.setattr(fetch, "resolve", lambda host: ["93.184.216.34"] if host == "public.example" else ["10.0.0.7"])
    hops = iter([httpx.Response(302, headers={"location": "http://public.example/2"}),
                 httpx.Response(302, headers={"location": "http://internal.example/admin"})])
    fetcher = fetch.Fetcher(max_bytes=10_000, timeout=5, transport=httpx.MockTransport(lambda r: next(hops)))
    with pytest.raises(fetch.FetchError) as exc:
        fetcher.get("http://public.example/")
    assert exc.value.kind == "BLOCKED_ADDRESS"


def test_fetcher_resource_limits(monkeypatch):
    monkeypatch.setattr(fetch, "resolve", lambda host: ["93.184.216.34"])
    html = {"content-type": "text/html"}

    def get(body, headers):
        handler = lambda r: httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))  # noqa: E731
        return fetch.Fetcher(max_bytes=50_000, timeout=5, transport=httpx.MockTransport(handler)).get("http://x.example/")

    def fails(body, headers):
        with pytest.raises(fetch.FetchError) as exc:
            get(body, headers)
        return exc.value.kind

    assert fails(gzip.compress(b"<p>" + b"A" * 20_000_000), {**html, "content-encoding": "gzip"}) == "TOO_LARGE"
    assert fails(b"x", {**html, "content-encoding": "br"}) == "NOT_HTML"
    assert fails(b"%PDF-1.7", {"content-type": "application/pdf"}) == "NOT_HTML"
    assert get(gzip.compress(b"<p>hello</p>"), {**html, "content-encoding": "gzip"}).html == "<p>hello</p>"
    # Company research cuts a large page at the limit instead (still never decompressing more than that).
    bomb = httpx.MockTransport(lambda r: httpx.Response(200, headers={**html, "content-encoding": "gzip"},
                                                        stream=httpx.ByteStream(gzip.compress(b"A" * 20_000_000))))
    cut = fetch.Fetcher(max_bytes=50_000, timeout=5, transport=bomb, truncate=True).get("http://x.example/")
    assert (len(cut.html), cut.truncated) == (50_000, True)
    loop = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": str(r.url)}))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.Fetcher(max_bytes=1000, timeout=5, transport=loop).get("http://x.example/")
    assert exc.value.kind == "REDIRECTS"


def test_dns_rebinding_guard_is_installed():
    transport = fetch._PublicOnlyTransport(retries=0)
    assert isinstance(transport._pool._network_backend, fetch._PublicOnlyBackend)
