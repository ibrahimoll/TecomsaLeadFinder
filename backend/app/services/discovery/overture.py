"""Overture Maps Places as a discovery source.

How the data is reached (see docs/ARCHITECTURE.md, "Discovery"):
  1. The STAC catalog (https://stac.overturemaps.org/catalog.json) names the latest
     release and lists every Places GeoParquet file with its bounding box.
  2. Only the files whose bbox intersects the country are read, over HTTPS, with DuckDB.
     A bbox + country filter lets DuckDB fetch just the matching row groups
     (~6 MB / ~50,000 places for Lebanon, about a minute).
  3. That extract is cached on disk per release (DISCOVERY_CACHE_DIR). Every later
     search reads the local file; a new Overture release is fetched once, automatically.

No API key, no account and no paid service is involved. Data licences: mostly CDLA
Permissive 2.0, plus Apache 2.0 (Foursquare) and CC0 (AllThePlaces).
"""

import json
import logging
import threading
import urllib.request
from pathlib import Path

from app.services.discovery.base import Candidate, Progress, ProviderError, SearchQuery, SearchResult
from app.services.discovery.geography import Country, canonical_city, in_area

logger = logging.getLogger(__name__)

_CLOSED = {"permanently_closed", "closed", "temporarily_closed"}
_lock = threading.Lock()


def _get_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "TECOMSA-LeadFinder/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URLs
        return json.load(response)


def _intersects(a: list[float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class OvertureProvider:
    key = "OVERTURE"
    label = "Overture Maps"

    def __init__(self, cache_dir: str | Path, stac_url: str, release: str | None = None, timeout: float = 30):
        self.cache_dir = Path(cache_dir) / "overture"
        self.stac_url = stac_url
        self.pinned_release = release
        self.timeout = timeout

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

    def dataset(self, country: Country, progress: Progress) -> tuple[Path, str]:
        """Local Places extract for the country (downloaded once per release)."""
        release = self.pinned_release or self._latest_release()
        if release is None:
            cached = self._cached_releases(country)
            if not cached:
                raise ProviderError(
                    "Overture data could not be queried: the Overture catalog is unreachable and no local copy "
                    "exists yet. Check the server's internet access. No companies were added."
                )
            release = cached[-1]
            progress("Overture Maps", f"Catalog unreachable; using the cached release {release}")
        path = self.cache_dir / release / f"places_{country.code}.parquet"
        with _lock:
            if path.is_file():
                progress("Overture Maps", f"Using cached release {release}")
                return path, release
            progress("Overture Maps", f"Downloading {country.name} places from release {release} (first search of this release, about a minute)")
            try:
                self._download(country, release, path)
            except ProviderError:
                raise
            except Exception as exc:
                logger.exception("Overture download failed")
                raise ProviderError(
                    f"Overture data could not be queried ({exc.__class__.__name__}). No companies were added. "
                    "Try again, or check the server's internet access."
                ) from exc
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
            raise ProviderError(f"Overture release {release} has no Places data covering {country.name}.")

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        min_lon, min_lat, max_lon, max_lat = country.bbox
        con = duckdb.connect()
        try:
            ext_dir = (self.cache_dir.parent / "duckdb_extensions").as_posix()
            con.execute(f"SET extension_directory = {_sql_str(ext_dir)}")
            con.execute("INSTALL httpfs")
            con.execute("LOAD httpfs")
            files = "[" + ", ".join(_sql_str(u) for u in urls) + "]"
            con.execute(
                f"""COPY (
                    SELECT id, names.primary AS name, taxonomy, basic_category, confidence, operating_status,
                           websites, phones, emails, addresses, bbox.xmin AS lon, bbox.ymin AS lat,
                           [s.dataset FOR s IN sources] AS datasets
                    FROM read_parquet({files})
                    WHERE bbox.xmin BETWEEN {min_lon} AND {max_lon}
                      AND bbox.ymin BETWEEN {min_lat} AND {max_lat}
                      AND addresses[1].country = {_sql_str(country.code)}
                ) TO {_sql_str(tmp.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)"""
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

    def search(self, query: SearchQuery, progress: Progress) -> SearchResult:
        path, release = self.dataset(query.country, progress)
        try:
            rows = self._rows(path, query.country.code)
        except Exception as exc:
            logger.exception("Reading the Overture extract failed")
            raise ProviderError(
                f"The cached Overture data could not be read ({exc.__class__.__name__}). No companies were added."
            ) from exc

        candidates: list[Candidate] = []
        for (pid, name, primary, hierarchy, alternates, basic, confidence, status, websites, phones, emails,
             freeform, locality, lat, lon, datasets) in rows:
            if status in _CLOSED:
                continue
            nodes = {n for n in [primary, basic, *(hierarchy or []), *(alternates or [])] if n}
            matched = query.industry.score(name, nodes)
            if matched is None:
                continue
            if query.area and not in_area(query.area, lat, lon, [t for t in (locality, freeform) if t], query.country.code):
                continue
            score, reason = matched
            category = primary.replace("_", " ").capitalize() if primary else None
            candidates.append(Candidate(
                source=self.key,
                external_id=pid,
                name=" ".join(name.split())[:255],
                category=category,
                website=(websites or [None])[0],
                phone=(phones or [None])[0],
                email=(emails or [None])[0],
                address=freeform[:500] if freeform else None,
                city=canonical_city(query.country.code, lat, lon, locality),
                country=query.country.name,
                latitude=lat,
                longitude=lon,
                confidence=confidence,
                score=score,
                match_reason=reason,
                data={
                    "name": name, "category": primary, "taxonomy": list(hierarchy or []),
                    "websites": list(websites or []), "phones": list(phones or []), "emails": list(emails or []),
                    "address": freeform, "locality": locality, "confidence": confidence,
                    "datasets": sorted(set(datasets or [])), "release": release,
                },
            ))
        # Best first: industry fit, then the source's confidence, then contactability.
        candidates.sort(key=lambda c: (-c.score, -(c.confidence or 0), not c.phone, not c.website, c.name.lower()))
        progress("Overture Maps", f"{len(candidates):,} matching places among {len(rows):,} in {query.country.name}")
        return SearchResult(candidates=candidates, version=release)
