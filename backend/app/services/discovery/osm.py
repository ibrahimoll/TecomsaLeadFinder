"""OpenStreetMap (via the public Overpass API) as a second discovery source.

Overture Places does not include OpenStreetMap, and OSM explicitly tags many Lebanese
factories, wineries and industrial sites (man_made=works, industrial=*, craft=winery…).
One Overpass query per country fetches the named business/industrial features; the
answer is cached on disk for OSM_CACHE_HOURS (default 24 h) to respect the Overpass
fair-use policy. Data © OpenStreetMap contributors, ODbL.
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.services.discovery.base import Candidate, Progress, ProviderError, SearchQuery, SearchResult
from app.services.discovery.geography import Country, canonical_city, in_area

logger = logging.getLogger(__name__)
_lock = threading.Lock()
# After Overpass fails, skip it for a while instead of making every search wait for timeouts.
_BACKOFF_SECONDS = 15 * 60
_last_failure: dict[str, float] = {}

_QUERY = """[out:json][timeout:90];
area["ISO3166-1"="{code}"][admin_level=2]->.c;
(
  nwr(area.c)["man_made"="works"]["name"];
  nwr(area.c)["industrial"]["name"];
  nwr(area.c)["landuse"="industrial"]["name"];
  nwr(area.c)["craft"~"^(bakery|confectionery|brewery|winery|distillery|cheese|caterer|coffee_roaster|oil_mill|carpenter|cabinet_maker|upholsterer|metal_construction|plastic|printer|tailor|dressmaker|glass|soap|beverages|food)$"]["name"];
  nwr(area.c)["office"="company"]["name"];
);
out center tags;"""

# Tags that mean "a place where things are made" (-> the generic manufacturer category).
_INDUSTRIAL_TAGS = (("man_made", "works"), ("landuse", "industrial"))


class OsmProvider:
    key = "OSM"
    label = "OpenStreetMap"

    def __init__(self, cache_dir: str | Path, overpass_url: str, cache_hours: float = 24, timeout: float = 60):
        self.cache_dir = Path(cache_dir) / "osm"
        # One or more Overpass instances (comma-separated), tried in order.
        self.overpass_urls = [u.strip() for u in overpass_url.split(",") if u.strip()]
        self.cache_hours = cache_hours
        self.timeout = timeout

    def _elements(self, country: Country, progress: Progress) -> tuple[list[dict], str]:
        path = self.cache_dir / f"features_{country.code}.json"
        with _lock:
            fresh = path.is_file() and (time.time() - path.stat().st_mtime) < self.cache_hours * 3600
            failed_at = _last_failure.get(country.code)
            if not fresh and failed_at and time.time() - failed_at < _BACKOFF_SECONDS and not path.is_file():
                minutes = int((time.time() - failed_at) // 60)
                raise ProviderError(
                    f"OpenStreetMap was unavailable {minutes} min ago, so it was skipped this time "
                    "(it is retried automatically after 15 minutes). Its results are missing from this search."
                )
            if not fresh:
                progress("OpenStreetMap", f"Querying OpenStreetMap (Overpass) for {country.name}")
                try:
                    payload = self._fetch(country)
                    _last_failure.pop(country.code, None)
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".part")
                    tmp.write_text(json.dumps(payload), encoding="utf-8")
                    tmp.replace(path)
                except Exception as exc:
                    _last_failure[country.code] = time.time()
                    if not path.is_file():
                        raise ProviderError(
                            f"OpenStreetMap could not be queried ({exc.__class__.__name__}). "
                            "Its results are missing from this search."
                        ) from exc
                    logger.warning("Overpass unavailable, using the older cache: %s", exc)
                    progress("OpenStreetMap", "Overpass unavailable; using the last cached answer")
            else:
                progress("OpenStreetMap", "Using the cached OpenStreetMap answer (less than a day old)")
            payload = json.loads(path.read_text(encoding="utf-8"))
            stamp = time.strftime("%Y-%m-%d", time.gmtime(path.stat().st_mtime))
        return payload.get("elements", []), stamp

    def _fetch(self, country: Country) -> dict:
        body = urllib.parse.urlencode({"data": _QUERY.format(code=country.code)}).encode()
        error: Exception | None = None
        for url in self.overpass_urls:
            try:
                request = urllib.request.Request(url, data=body, headers={"User-Agent": "TECOMSA-LeadFinder/1.0"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    return json.load(response)
            except Exception as exc:  # busy (429/504) or unreachable: try the next instance
                logger.warning("Overpass instance %s failed: %s", url, exc)
                error = exc
        raise error or RuntimeError("no Overpass URL configured")

    def search(self, query: SearchQuery, progress: Progress) -> SearchResult:
        elements, stamp = self._elements(query.country, progress)
        candidates: list[Candidate] = []
        for el in elements:
            tags = el.get("tags") or {}
            name = tags.get("name:en") or tags.get("name")
            if not name:
                continue
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            nodes = {v.strip() for k in ("craft", "industrial", "office", "shop", "amenity") for v in tags.get(k, "").split(";") if v}
            if any(tags.get(k) == v for k, v in _INDUSTRIAL_TAGS) or "industrial" in tags:
                nodes.add("manufacturer")
            product = tags.get("product", "").replace(";", " ").replace("_", " ")
            matched = query.industry.score(f"{name} {product}".strip(), nodes)
            if matched is None:
                continue
            locality = tags.get("addr:city") or tags.get("addr:place")
            street = " ".join(filter(None, (tags.get("addr:street"), tags.get("addr:housenumber")))) or None
            if query.area and not in_area(query.area, lat, lon, [t for t in (locality, street) if t], query.country.code):
                continue
            score, reason = matched
            category = (tags.get("craft") or tags.get("industrial") or tags.get("product") or tags.get("man_made")
                        or tags.get("office") or "")
            candidates.append(Candidate(
                source=self.key,
                external_id=f"{el['type']}/{el['id']}",
                name=" ".join(name.split())[:255],
                category=category.replace("_", " ").capitalize() or None,
                website=tags.get("website") or tags.get("contact:website"),
                phone=tags.get("phone") or tags.get("contact:phone"),
                email=tags.get("email") or tags.get("contact:email"),
                address=street,
                city=canonical_city(query.country.code, lat, lon, locality),
                country=query.country.name,
                latitude=lat,
                longitude=lon,
                confidence=None,
                score=score,
                match_reason=reason,
                data={"name": name, "tags": {k: v for k, v in tags.items() if not k.startswith("name:")}, "retrieved": stamp},
            ))
        candidates.sort(key=lambda c: (-c.score, not c.phone, not c.website, c.name.lower()))
        progress("OpenStreetMap", f"{len(candidates):,} matching places among {len(elements):,} mapped features")
        return SearchResult(candidates=candidates, version=f"overpass {stamp}")
