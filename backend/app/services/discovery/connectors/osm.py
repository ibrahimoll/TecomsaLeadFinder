"""OpenStreetMap (from the Geofabrik country extract) as an open discovery source.

Overture Places does not include OpenStreetMap, and OSM explicitly tags many Lebanese factories,
wineries and industrial sites (man_made=works, industrial=*, craft=winery…). The country extract
(.osm.pbf, ~50 MB for Lebanon, rebuilt daily by Geofabrik) is downloaded, the named business /
industrial features are pulled out with DuckDB's spatial extension, and only that small list is
cached for `cache_hours`. Bulk extracts are the politeness-friendly way to use OSM (one download a
week, instead of hammering the public Overpass API). Data © OpenStreetMap contributors, ODbL.
"""

import json
import logging
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path

from app.services.discovery.candidate import (CompanyCandidate, ConnectorConfig, ConnectorError, ConnectorResult,
                                              SearchQuery, closed_reason, refresh_in_background)
from app.services.discovery.connectors.overture import USER_AGENT, sql_str
from app.services.discovery.geography import Country, canonical_city, in_area, region_for

logger = logging.getLogger(__name__)
_lock = threading.Lock()  # one first download at a time
_refreshing = threading.Lock()  # one background refresh at a time
# After a failed download, skip OSM for a while instead of making every search wait for it.
_BACKOFF_SECONDS = 15 * 60
_last_failure: dict[str, float] = {}

_CRAFTS = ("bakery|confectionery|brewery|winery|distillery|cheese|caterer|coffee_roaster|oil_mill|carpenter|"
           "cabinet_maker|upholsterer|metal_construction|plastic|printer|tailor|dressmaker|glass|soap|beverages|food")

# Named business/industrial nodes and ways (relations are skipped); a way gets the average of its
# nodes' coordinates as its centre.
_EXTRACT = f"""
CREATE TEMP TABLE feat AS
  SELECT kind, id, tags, lat, lon, refs FROM ST_ReadOSM($pbf)
  WHERE kind IN ('node', 'way') AND tags['name'] IS NOT NULL AND (
    tags['man_made'] = 'works' OR tags['industrial'] IS NOT NULL OR tags['landuse'] = 'industrial'
    OR regexp_full_match(tags['craft'], '{_CRAFTS}') OR tags['office'] IS NOT NULL OR tags['shop'] IS NOT NULL
    OR tags['amenity'] IN ('restaurant', 'cafe', 'fast_food', 'bank', 'clinic', 'hospital', 'pharmacy', 'school',
                           'university', 'college'));
SELECT f.kind, f.id, map_keys(f.tags), map_values(f.tags), coalesce(f.lat, c.lat), coalesce(f.lon, c.lon)
FROM feat f LEFT JOIN (
  SELECT w.id, avg(n.lat) AS lat, avg(n.lon) AS lon
  FROM (SELECT id, unnest(refs) AS ref FROM feat WHERE kind = 'way') w
  JOIN ST_ReadOSM($pbf) n ON n.kind = 'node' AND n.id = w.ref
  GROUP BY w.id
) c ON f.kind = 'way' AND c.id = f.id
"""

_VENUES = {"restaurant", "cafe", "fast_food", "bar", "pub", "ice_cream", "food_court", "marketplace"}
# OSM tags -> the place-taxonomy nodes LeadFinder's industry profiles understand.
_AMENITY_NODES = {"bank": {"financial_service", "bank"}, "clinic": {"health_care"}, "hospital": {"health_care"},
                  "pharmacy": {"health_care", "shopping"}, "school": {"education"}, "university": {"education"},
                  "college": {"education"}}
_OFFICE_NODES = {"company": {"corporate_or_business_office"}, "it": {"information_technology_company"},
                 "telecommunication": {"telecommunications_service"}, "insurance": {"insurance_agency"},
                 "financial": {"financial_service"}, "estate_agent": {"real_estate_service"},
                 "lawyer": {"legal_service", "professional_service"}, "accountant": {"professional_service"},
                 "logistics": {"logistics_service"}, "construction_company": {"construction_company"}}
_PHONE_TAGS = ("phone", "contact:phone", "contact:mobile", "mobile")


def _value(v: str) -> str:
    return v.strip().lower()


def _facility(tags: dict) -> str | None:
    """Tags that mean "a place where things are made" (also the generic manufacturer category)."""
    if tags.get("man_made") == "works":
        return "Industrial site (OpenStreetMap: works)"
    if tags.get("building") in ("industrial", "factory", "manufacture"):
        return f"Factory building (OpenStreetMap: building={tags['building']})"
    if "industrial" in tags:
        return f"Industrial site (OpenStreetMap: industrial={tags['industrial']})"
    if tags.get("landuse") == "industrial":
        return "Industrial land (OpenStreetMap: landuse=industrial)"
    return None


def _closed(tags: dict) -> str | None:
    """Explicit OpenStreetMap lifecycle evidence that the business no longer operates."""
    for key in ("disused", "abandoned"):
        if tags.get(key) == "yes":
            return f"OpenStreetMap marks it {key}."
    if tags.get("end_date"):
        return f"OpenStreetMap gives an end date ({tags['end_date']})."
    if tags.get("opening_hours", "").strip().lower() in ("closed", "off"):
        return "OpenStreetMap opening hours say it is closed."
    return None


def _nodes(tags: dict) -> set[str]:
    nodes = {_value(v) for k in ("craft", "industrial") for v in tags.get(k, "").split(";") if v.strip()}
    if _facility(tags) or (tags.get("craft") and not tags.get("shop")):
        nodes.add("manufacturer")  # a craft workshop makes things; with a shop tag it is a store
    if tags.get("shop"):
        nodes |= {"shopping", *(_value(v) for v in tags["shop"].split(";") if v.strip())}
    if tags.get("amenity") in _VENUES:
        nodes |= {"food_and_drink", tags["amenity"]}
    nodes |= _AMENITY_NODES.get(tags.get("amenity", ""), set())
    office = tags.get("office")
    if office:
        nodes |= _OFFICE_NODES.get(office, {"corporate_or_business_office"})
    return nodes


class OsmConnector:
    def __init__(self, config: ConnectorConfig, cache_dir: str | Path):
        self.config = config
        self.cache_dir = Path(cache_dir) / "osm"
        self.download_url = config.options.get("download_url", "https://download.geofabrik.de").rstrip("/")
        self.cache_hours = float(config.options.get("cache_hours", 168))
        self.timeout = float(config.options.get("timeout_seconds", 60))

    def _refresh(self, country: Country, path: Path) -> None:
        logger.info("Downloading the OpenStreetMap extract for %s", country.code)
        try:
            payload = self._fetch(country)
            if not payload.get("elements"):  # never replace a working cache with an empty extract
                raise RuntimeError("the OpenStreetMap extract was empty")
        except Exception:
            _last_failure[country.code] = time.time()
            raise
        _last_failure.pop(country.code, None)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)

    def _elements(self, country: Country) -> tuple[list[dict], str]:
        """The cached extract; an expired one is used as is while a new one is built in the background."""
        path = self.cache_dir / f"features_v2_{country.code}.json"
        failed_at = _last_failure.get(country.code)
        backing_off = failed_at is not None and time.time() - failed_at < _BACKOFF_SECONDS
        if not path.is_file():
            with _lock:
                if not path.is_file():
                    if backing_off:
                        raise ConnectorError("OpenStreetMap was unavailable a few minutes ago; it is retried "
                                             "automatically.")
                    try:
                        self._refresh(country, path)
                    except Exception as exc:
                        logger.warning("OpenStreetMap download failed: %s", exc)
                        raise ConnectorError("OpenStreetMap data could not be downloaded.") from exc
        elif time.time() - path.stat().st_mtime >= self.cache_hours * 3600 and not backing_off:
            refresh_in_background(_refreshing, lambda: self._refresh(country, path), f"osm-{country.code}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("elements", []), time.strftime("%Y-%m-%d", time.gmtime(path.stat().st_mtime))

    def _fetch(self, country: Country) -> dict:
        import duckdb

        if not country.geofabrik:
            raise RuntimeError(f"no OpenStreetMap extract configured for {country.code}")
        region = country.geofabrik
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        pbf = self.cache_dir / f"{country.code}.osm.pbf"
        part = self.cache_dir / f"{country.code}.osm.pbf.part"
        headers = {"User-Agent": USER_AGENT}
        # The newest dated file listed on the region page ("-latest" is sometimes a redirect loop).
        with urllib.request.urlopen(urllib.request.Request(f"{self.download_url}/{region}.html", headers=headers),
                                    timeout=self.timeout) as response:  # noqa: S310
            page = response.read().decode("utf-8", "replace")
        name = region.rsplit("/", 1)[-1]
        dated = sorted(set(re.findall(rf'href="({re.escape(name)}-\d{{6}}\.osm\.pbf)"', page)))
        file = dated[-1] if dated else f"{name}-latest.osm.pbf"
        request = urllib.request.Request(f"{self.download_url}/{region.rsplit('/', 1)[0]}/{file}", headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response, part.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out)
        part.replace(pbf)
        con = duckdb.connect()
        try:
            ext_dir = (self.cache_dir.parent / "duckdb_extensions").as_posix()
            con.execute(f"SET extension_directory = {sql_str(ext_dir)}")
            con.execute("INSTALL spatial")
            con.execute("LOAD spatial")
            create, select = _EXTRACT.replace("$pbf", sql_str(pbf.as_posix())).split(";\n", 1)
            con.execute(create)
            rows = con.execute(select).fetchall()
        finally:
            con.close()
            pbf.unlink(missing_ok=True)  # only the extracted features are kept
        return {"elements": [
            {"type": kind, "id": osm_id, "lat": lat, "lon": lon, "tags": dict(zip(keys, values))}
            for kind, osm_id, keys, values, lat, lon in rows
        ]}

    def search_companies(self, query: SearchQuery) -> ConnectorResult:
        elements, stamp = self._elements(query.country)
        candidates: list[CompanyCandidate] = []
        for el in elements:
            tags = el.get("tags") or {}
            name = tags.get("name:en") or tags.get("name")
            if not name:
                continue
            lat, lon = el.get("lat"), el.get("lon")
            nodes = _nodes(tags)
            products = [_value(v).replace("_", " ") for v in tags.get("product", "").split(";") if v.strip()]
            text = " ".join([name, *products])
            matched = query.industry.score(text, nodes)
            wrong = None if matched else query.industry.reject(text, nodes)
            # The product tag is structured evidence: its first value is the main product.
            if matched and products and not query.industry.mentions(products[0]):
                matched, wrong = None, f"OpenStreetMap lists its main product as {products[0]}."
            if matched is None and wrong is None:
                continue
            locality = tags.get("addr:city") or tags.get("addr:place")
            street = " ".join(filter(None, (tags.get("addr:street"), tags.get("addr:housenumber")))) or None
            if query.area and not in_area(query.area, lat, lon, [t for t in (locality, street) if t],
                                          query.country.code):
                continue
            closed = _closed(tags) or closed_reason(name)
            category = (tags.get("craft") or tags.get("industrial") or tags.get("product") or tags.get("man_made")
                        or tags.get("office") or tags.get("shop") or tags.get("amenity") or "")
            city = canonical_city(query.country.code, lat, lon, locality)
            candidates.append(CompanyCandidate(
                connector=self.config.key,
                source_name=f"OpenStreetMap (extract {stamp})",
                source_type=self.config.source_type,
                external_id=f"{el['type']}/{el['id']}",
                source_url=f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
                company_name=name,
                website=tags.get("website") or tags.get("contact:website"),
                phone=next((tags[k] for k in _PHONE_TAGS if tags.get(k)), None),
                email=tags.get("email") or tags.get("contact:email"),
                address=street,
                city=city,
                region=region_for(query.country.code, lat, lon, city),
                country=query.country.name,
                latitude=lat,
                longitude=lon,
                industry=category.replace("_", " ").replace(";", ", ").capitalize() or None,
                categories=sorted(nodes),
                score=matched.score if matched else 0.0,
                match_reason=matched.reason if matched else None,
                tier=matched.tier if matched else "name",
                rejected="CLOSED" if closed else None if matched else "WRONG_INDUSTRY",
                reject_reason=closed or wrong,
                facility=_facility(tags),
                datasets=["OpenStreetMap"],
                brand=tags.get("brand"),
                operator=tags.get("operator"),
                raw_metadata={"name": name, "tags": {k: v for k, v in tags.items() if not k.startswith("name:")},
                              "retrieved": stamp},
            ))
        candidates.sort(key=lambda c: (-c.score, not c.phone, not c.website, c.company_name.lower()))
        return ConnectorResult(candidates=candidates, version=f"osm {stamp}", scanned=len(elements))
