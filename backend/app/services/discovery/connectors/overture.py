"""Overture Maps Places: an open dataset of businesses and places (no API key, no account).

How the data is reached:
  1. The STAC catalog (https://stac.overturemaps.org/catalog.json) names the latest release and lists
     every Places GeoParquet file with its bounding box.
  2. Only the files whose bbox intersects the country are read, over HTTPS, with DuckDB. A bbox + country
     filter lets DuckDB fetch just the matching row groups (~6 MB / ~50,000 places for Lebanon).
  3. That extract is cached on disk per release; every later search reads the local file. The catalog is
     checked for a new release at most every `catalog_hours`, in the background: searches keep using the
     cached release meanwhile and never wait for the network once a copy exists.

Licences: mostly CDLA Permissive 2.0, plus Apache 2.0 (Foursquare) and CC0 (AllThePlaces). One signal
among several: LeadFinder's master data never depends on it.
"""

import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

from app.services.discovery.candidate import (CompanyCandidate, ConnectorConfig, ConnectorError, ConnectorResult,
                                              SearchQuery, closed_reason, refresh_in_background)
from app.services.discovery.geography import Country, canonical_city, in_area, region_for

logger = logging.getLogger(__name__)

# Only explicit closure is a rejection; "temporarily_closed" is a concern, unknown is not evidence.
_CLOSED = {"permanently_closed", "closed"}
# Overture's own conflation layers, not independent sources of the place.
_OVERTURE_OWN = {"Overture", "Overture-signals"}
_lock = threading.Lock()  # one download at a time
_refreshing = threading.Lock()  # one background catalog check at a time
_checked: dict[str, float] = {}  # country code -> last catalog check (time.monotonic)
USER_AGENT = "TECOMSA-LeadFinder/1.0 (company discovery)"


def _get_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URLs
        return json.load(response)


def _intersects(a: list[float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class OvertureConnector:
    def __init__(self, config: ConnectorConfig, cache_dir: str | Path):
        self.config = config
        self.cache_dir = Path(cache_dir) / "overture"
        self.stac_url = config.options.get("stac_url", "https://stac.overturemaps.org/catalog.json")
        self.pinned_release = config.options.get("release") or None
        self.timeout = float(config.options.get("timeout_seconds", 30))
        self.catalog_hours = float(config.options.get("catalog_hours", 24))

    # ---- dataset -------------------------------------------------------------------

    def _latest_release(self) -> str | None:
        try:
            return _get_json(self.stac_url, self.timeout)["latest"]
        except Exception as exc:  # network or catalog problem: fall back to the cache
            logger.warning("Overture STAC catalog unavailable: %s", exc)
            return None

    def _cached_releases(self, country: Country) -> list[str]:
        if not self.cache_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self.cache_dir.glob(f"*/places_{country.code}.parquet"))

    def _refresh(self, country: Country) -> None:
        if release := self._latest_release():
            self._ensure(country, release)

    def dataset(self, country: Country) -> tuple[Path, str]:
        """Local Places extract for the country (downloaded once per release)."""
        if self.pinned_release:
            return self._ensure(country, self.pinned_release)
        if cached := self._cached_releases(country):
            last = _checked.get(country.code)
            if last is None or time.monotonic() - last >= self.catalog_hours * 3600:
                _checked[country.code] = time.monotonic()
                refresh_in_background(_refreshing, lambda: self._refresh(country), f"overture-{country.code}")
            return self.cache_dir / cached[-1] / f"places_{country.code}.parquet", cached[-1]
        release = self._latest_release()
        if release is None:
            raise ConnectorError("Overture Maps is unreachable and no local copy exists yet.")
        return self._ensure(country, release)

    def _ensure(self, country: Country, release: str) -> tuple[Path, str]:
        path = self.cache_dir / release / f"places_{country.code}.parquet"
        with _lock:
            if path.is_file():
                return path, release
            logger.info("Downloading Overture places for %s, release %s", country.code, release)
            try:
                self._download(country, release, path)
            except ConnectorError:
                raise
            except Exception as exc:
                logger.exception("Overture download failed")
                cached = self._cached_releases(country)
                if cached:  # a failed refresh keeps the previous release usable
                    return self.cache_dir / cached[-1] / f"places_{country.code}.parquet", cached[-1]
                raise ConnectorError("Overture Maps data could not be downloaded.") from exc
        return path, release

    def _download(self, country: Country, release: str, path: Path) -> None:
        import duckdb  # imported lazily: only the discovery worker needs it

        base = self.stac_url.rsplit("/", 1)[0]
        collection = _get_json(f"{base}/{release}/places/place/collection.json", self.timeout)
        urls = []
        for link in collection.get("links", []):
            if link.get("rel") != "item":
                continue
            item = _get_json(link["href"], self.timeout)
            if _intersects(item["bbox"], country.bbox):
                urls.append(item["assets"]["aws"]["href"])
        if not urls:
            raise ConnectorError(f"Overture release {release} has no places covering {country.name}.")

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        min_lon, min_lat, max_lon, max_lat = country.bbox
        con = duckdb.connect()
        try:
            ext_dir = (self.cache_dir.parent / "duckdb_extensions").as_posix()
            con.execute(f"SET extension_directory = {sql_str(ext_dir)}")
            con.execute("INSTALL httpfs")
            con.execute("LOAD httpfs")
            files = "[" + ", ".join(sql_str(u) for u in urls) + "]"
            con.execute(
                f"""COPY (
                    SELECT id, names.primary AS name, taxonomy, basic_category, confidence, operating_status,
                           websites, phones, emails, addresses, bbox.xmin AS lon, bbox.ymin AS lat,
                           [s.dataset FOR s IN sources] AS datasets
                    FROM read_parquet({files})
                    WHERE bbox.xmin BETWEEN {min_lon} AND {max_lon}
                      AND bbox.ymin BETWEEN {min_lat} AND {max_lat}
                      AND addresses[1].country = {sql_str(country.code)}
                ) TO {sql_str(tmp.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)"""
            )
        finally:
            con.close()
        tmp.replace(path)

    # ---- search --------------------------------------------------------------------

    def _rows(self, path: Path, country: str):
        import duckdb

        con = duckdb.connect()
        try:
            return con.execute(
                """SELECT id, name, taxonomy.primary, taxonomy.hierarchy, taxonomy.alternates, basic_category,
                          confidence, operating_status, websites, phones, emails,
                          addresses[1].freeform, addresses[1].locality, lat, lon, datasets
                   FROM read_parquet(?) WHERE name IS NOT NULL AND addresses[1].country = ?""",
                [path.as_posix(), country],
            ).fetchall()
        finally:
            con.close()

    def search_companies(self, query: SearchQuery) -> ConnectorResult:
        path, release = self.dataset(query.country)
        try:
            rows = self._rows(path, query.country.code)
        except Exception as exc:
            logger.exception("Reading the Overture extract failed")
            raise ConnectorError("The cached Overture Maps data could not be read.") from exc

        candidates: list[CompanyCandidate] = []
        for (pid, name, primary, hierarchy, alternates, basic, confidence, status, websites, phones, emails,
             freeform, locality, lat, lon, datasets) in rows:
            nodes = {n for n in [primary, basic, *(hierarchy or []), *(alternates or [])] if n}
            matched = query.industry.score(name, nodes)
            wrong = None if matched else query.industry.reject(name, nodes)
            if matched is None and wrong is None:
                continue
            if query.area and not in_area(query.area, lat, lon, [t for t in (locality, freeform) if t],
                                          query.country.code):
                continue
            closed = closed_reason(name) or (
                f"Overture marks it {status.replace('_', ' ')}." if status in _CLOSED else None)
            notes = ["Overture marks it temporarily closed."] if status == "temporarily_closed" else []
            if confidence is not None and confidence < 0.3:
                notes.append(f"Overture is unsure the place exists (confidence {confidence:.2f}).")
            city = canonical_city(query.country.code, lat, lon, locality)
            candidates.append(CompanyCandidate(
                connector=self.config.key,
                source_name=f"Overture Maps Places {release}",
                source_type=self.config.source_type,
                external_id=pid,
                company_name=name,
                website=(websites or [None])[0],
                phone=(phones or [None])[0],
                email=(emails or [None])[0],
                address=freeform[:500] if freeform else None,
                city=city,
                region=region_for(query.country.code, lat, lon, city),
                country=query.country.name,
                latitude=lat,
                longitude=lon,
                industry=primary.replace("_", " ").capitalize() if primary else None,
                categories=sorted(nodes),
                source_confidence=confidence,
                score=matched.score if matched else 0.0,
                match_reason=matched.reason if matched else None,
                tier=matched.tier if matched else "name",
                rejected="CLOSED" if closed else None if matched else "WRONG_INDUSTRY",
                reject_reason=closed or wrong,
                datasets=sorted(set(datasets or []) - _OVERTURE_OWN),
                notes=notes,
                raw_metadata={
                    "name": name, "category": primary, "taxonomy": list(hierarchy or []),
                    "websites": list(websites or []), "phones": list(phones or []), "emails": list(emails or []),
                    "address": freeform, "locality": locality, "confidence": confidence,
                    "operating_status": status, "datasets": sorted(set(datasets or [])), "release": release,
                },
            ))
        # Best first: industry fit, then the source's confidence, then contactability.
        candidates.sort(key=lambda c: (-c.score, -(c.source_confidence or 0), not c.phone, not c.website,
                                       c.company_name.lower()))
        return ConnectorResult(candidates=candidates, version=release, scanned=len(rows))
