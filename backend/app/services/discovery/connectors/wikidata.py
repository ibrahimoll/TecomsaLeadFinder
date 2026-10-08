"""Wikidata (CC0 open knowledge base): notable companies with their official website and headquarters.

Coverage is narrow (for Lebanon: ~300 businesses, mostly banks, publishers, telecoms, wineries) but the
data is curated, so it is a strong identity signal: official name, official website, inception date.
One SPARQL query per country, cached for `cache_hours` (Wikidata's query service asks for an identifying
User-Agent and modest request volumes).
"""

import json
import logging
import re
import threading
import time
from pathlib import Path

import httpx

from app.services.discovery.candidate import (CompanyCandidate, ConnectorConfig, ConnectorError, ConnectorResult,
                                              SearchQuery, refresh_in_background)
from app.services.discovery.geography import Country, canonical_city, in_area, region_for
from app.services.discovery.industries import label_nodes

logger = logging.getLogger(__name__)
_lock = threading.Lock()  # one first download at a time
_refreshing = threading.Lock()  # one background refresh at a time
ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "TECOMSA-LeadFinder/1.0 (https://tecomsa.me; company discovery)"

# Instance-of classes treated as businesses (direct P31 only: the transitive closure times out).
# business, company, enterprise, public company, corporation, privately held company, subsidiary, bank,
# winery, publishing house, ... (direct types only).
_TYPES = " ".join(f"wd:{q}" for q in ("Q4830453 Q783794 Q6881511 Q891723 Q167037 Q1589009 Q658255 Q22687 Q156362 "
                                       "Q2085381 Q15911314 Q210167").split())
_QUERY = """SELECT ?c ?cLabel ?typeLabel ?industryLabel ?website ?hqLabel ?coord ?inception ?employees WHERE {
  VALUES ?type { %s }
  ?c wdt:P31 ?type.
  { ?c wdt:P17 wd:%s } UNION { ?c wdt:P159 ?h. ?h wdt:P17 wd:%s }
  FILTER NOT EXISTS { ?c wdt:P576 ?dissolved }
  OPTIONAL { ?c wdt:P452 ?industry }
  OPTIONAL { ?c wdt:P856 ?website }
  OPTIONAL { ?c wdt:P159 ?hq }
  OPTIONAL { ?c wdt:P625 ?coord }
  OPTIONAL { ?c wdt:P571 ?inception }
  OPTIONAL { ?c wdt:P1128 ?employees }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,ar". }
}"""

def _point(wkt: str | None) -> tuple[float | None, float | None]:
    match = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", wkt or "")
    return (float(match[2]), float(match[1])) if match else (None, None)


class WikidataConnector:
    def __init__(self, config: ConnectorConfig, cache_dir: str | Path, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.cache_dir = Path(cache_dir) / "wikidata"
        self.cache_hours = float(config.options.get("cache_hours", 168))
        self.timeout = float(config.options.get("timeout_seconds", 60))
        self.transport = transport

    def _query(self, country: Country, path: Path) -> None:
        with httpx.Client(transport=self.transport, timeout=self.timeout,
                          headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}) as client:
            response = client.get(ENDPOINT, params={"query": _QUERY % (_TYPES, country.wikidata, country.wikidata)})
            response.raise_for_status()
            rows = response.json()["results"]["bindings"]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps(rows), encoding="utf-8")
        tmp.replace(path)

    def _rows(self, country: Country) -> tuple[list[dict], str]:
        """The cached query result; an expired cache is used as is while a refresh runs in the background."""
        if not country.wikidata:
            raise ConnectorError(f"Wikidata is not configured for {country.name}.")
        path = self.cache_dir / f"companies_{country.code}.json"
        if not path.is_file():
            with _lock:
                if not path.is_file():
                    try:
                        self._query(country, path)
                    except Exception as exc:
                        logger.warning("Wikidata query failed: %s", exc)
                        raise ConnectorError("Wikidata could not be queried.") from exc
        elif time.time() - path.stat().st_mtime >= self.cache_hours * 3600:
            refresh_in_background(_refreshing, lambda: self._query(country, path), f"wikidata-{country.code}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        return rows, time.strftime("%Y-%m-%d", time.gmtime(path.stat().st_mtime))

    def search_companies(self, query: SearchQuery) -> ConnectorResult:
        rows, stamp = self._rows(query.country)
        # One entity can come back several times (one row per website / industry / hq): merge them.
        entities: dict[str, dict] = {}
        for row in rows:
            qid = row["c"]["value"].rsplit("/", 1)[-1]
            value = lambda key: row.get(key, {}).get("value")  # noqa: E731
            entity = entities.setdefault(qid, {"name": value("cLabel"), "labels": set(), "websites": [],
                                               "hq": value("hqLabel"), "coord": value("coord"),
                                               "inception": value("inception"), "employees": value("employees")})
            entity["labels"] |= {v for v in (value("typeLabel"), value("industryLabel")) if v}
            if (site := value("website")) and site not in entity["websites"]:
                entity["websites"].append(site)
        candidates = []
        for qid, e in entities.items():
            name = e["name"]
            if not name or re.fullmatch(r"Q\d+", name):  # no label in any of our languages
                continue
            labels = sorted(e["labels"])
            nodes = label_nodes(labels)
            matched = query.industry.score(f"{name} {' '.join(labels)}", nodes)
            if matched is None:
                continue
            lat, lon = _point(e["coord"])
            if query.area and not in_area(query.area, lat, lon, [t for t in (e["hq"],) if t], query.country.code):
                continue
            city = canonical_city(query.country.code, lat, lon, e["hq"])
            employees = e["employees"]
            founded = (e["inception"] or "")[:4]
            candidates.append(CompanyCandidate(
                connector=self.config.key,
                source_name=f"Wikidata ({stamp})",
                source_type=self.config.source_type,
                external_id=qid,
                source_url=f"https://www.wikidata.org/wiki/{qid}",
                company_name=name,
                website=(e["websites"] or [None])[0],
                city=city,
                region=region_for(query.country.code, lat, lon, city),
                country=query.country.name,
                latitude=lat,
                longitude=lon,
                industry=", ".join(labels)[:120] or None,
                categories=sorted(nodes),
                employee_count=int(float(employees)) if employees else None,
                score=matched.score,
                match_reason=matched.reason,
                tier=matched.tier,
                datasets=["Wikidata"],
                raw_metadata={"qid": qid, "labels": labels, "websites": e["websites"], "headquarters": e["hq"],
                              "inception": founded or None, "employees": employees},
            ))
        candidates.sort(key=lambda c: (-c.score, not c.website, c.company_name.lower()))
        return ConnectorResult(candidates=candidates, version=f"wikidata {stamp}", scanned=len(entities))
