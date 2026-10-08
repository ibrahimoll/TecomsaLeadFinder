"""Common Crawl: the company's own pages as the public web archive captured them (free; no search engine).

    company.domain -> Common Crawl URL index (CDX API): the company's own hosts (example.com/*, www.example.com/*),
                      newest crawl first, earlier crawls only while nothing useful has been found (bounded)
                   -> captures by priority: people pages (team, management, leadership, board, about), then news /
                      press / careers / contact, then operations pages (factory, warehouse, locations, branches,
                      products); the live research's pages skipped; deduplicated by content digest
                   -> each capture: one WARC record, by byte range (data.commoncrawl.org), never a whole file
                   -> the Step 5 extractor, as the company's own page
                   -> capture older than CURRENT_DAYS: the role is "not confirmed", never "current"

Bounded per company (crawls, lookups, captures, and time: every request's timeout is cut to the caller's deadline);
while the index is down (a lookup failed with a network error) it is skipped for every company for
COMMONCRAWL_DOWN_SECONDS, so an archive outage never holds people research hostage; index answers cached (provider "commoncrawl"; failures are not);
requests serialised and paced (COMMONCRAWL_MIN_INTERVAL_SECONDS); a failing lookup is retried with exponential
back-off. Every lookup is recorded (source_lookups: ok / NO_CAPTURE / NETWORK_ERROR / INDEX_ERROR / PARSE_ERROR /
NO_USEFUL_PAGE, timing, cache hit) so the archive's reliability is measured.
"""

import gzip
import io
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Company, CompanyWebPage, ExternalDocument, Source
from app.services.enrichment.pages import parse
from app.services.people.external.search import cached_json

logger = logging.getLogger("leadfinder.people.commoncrawl")
INDEX = "https://index.commoncrawl.org"
DATA = "https://data.commoncrawl.org"
ZIPNUM = f"{DATA}/cc-index/collections"  # the URL index as static files (the index server is unreachable from here)
MAX_INDEX_BLOCKS = 3  # index blocks read per host and crawl (3 x 3,000 index lines)
CURRENT_DAYS = 180  # a capture this recent is the company's site as it is now
PEOPLE_PATH = re.compile(r"team|management|leadership|leaders|board|directors|executive|our-people|/people|staff|"
                         r"founder|who-we-are|about|a-propos|qui-sommes|equipe|direction|من-نحن|فريق", re.IGNORECASE)
NEWS_ROLE = re.compile(r"(news|press|media|blog|article|post).*(ceo|chairman|general-manager|managing-director|"
                       r"director|manager|appoint|welcome|joins|founder|head-of|cfo|cto|cio|cmo|coo)", re.IGNORECASE)
CONTACT_PATH = re.compile(r"/(news|press|media|careers|jobs|contact|contact-us)(/|$)", re.IGNORECASE)
OPERATIONS_PATH = re.compile(r"factor|plant|warehouse|location|branch|store|showroom|project|product|service|"
                             r"facilit|usine|entrepot|succursale|فروع", re.IGNORECASE)
MAX_CRAWLS = 6  # index lookups go back at most this many crawls
RETRIES = 3
INDEX_TIMEOUT = 30  # seconds, one index request (never more than the caller's deadline leaves)
SKIP = re.compile(r"\.(jpe?g|png|gif|svg|webp|css|js|pdf|xml|json|txt|ico|woff2?)(\?|$)|/(wp-json|feed|tag|"
                  r"category|page/\d+|cart|checkout|product|shop)/", re.IGNORECASE)
_lock = threading.Lock()
_last = [0.0]
_down_until = [0.0]  # monotonic: the index failed with a network error; skipped until then (every company)


def available() -> bool:
    return time.monotonic() >= _down_until[0]


def _mark_down() -> None:
    _down_until[0] = time.monotonic() + get_settings().commoncrawl_down_seconds
    logger.warning("common crawl index unreachable: skipped for %ss", get_settings().commoncrawl_down_seconds)


def _timeout(deadline: float | None, cap: float = INDEX_TIMEOUT) -> httpx.Timeout:
    left = cap if deadline is None else deadline - time.monotonic()
    if left < 1:
        raise LookupError_("TIMEOUT")
    return httpx.Timeout(min(cap, left), connect=min(5, left))


def _paced(http, method: str, url: str, **kwargs):
    """One Common Crawl request at a time per process, spaced; one retry after a busy answer."""
    for attempt in range(2):
        with _lock:
            wait = _last[0] + get_settings().commoncrawl_min_interval_seconds - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            response = http.request(method, url, **kwargs)
            _last[0] = time.monotonic()
        if response.status_code in (429, 503, 504) and attempt == 0:
            time.sleep(5)
            continue
        return response
    return response


def crawls(db: Session, http, deadline: float | None = None) -> list[str]:
    """Crawl ids, newest first (at most MAX_CRAWLS are ever looked at for one company), from the static collections
    page on data.commoncrawl.org (the index server's collinfo.json is unreachable from here)."""
    def collections():
        try:
            r = http.get(f"{ZIPNUM}/index.html", timeout=_timeout(deadline))
        except LookupError_:
            raise
        except Exception:
            _mark_down()
            raise
        r.raise_for_status()
        return sorted(set(re.findall(r"CC-MAIN-\d{4}-\d{2}", r.text)), reverse=True)

    ids, _ = cached_json(db, "commoncrawl", "collections", 7, collections)
    return ids[:MAX_CRAWLS]


class LookupError_(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def canonical_domain(domain: str) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", (domain or "").strip().lower()).split("/")[0]


def surt_prefix(host: str) -> str:
    """'www.Example.com' -> 'com,example)/': the sort key of the host's captures in Common Crawl's URL index."""
    return ",".join(reversed(canonical_domain(host).split("."))) + ")/"


def _static(http, method: str, url: str, deadline: float | None, headers: dict | None = None):
    """One read of the static index (a CDN: connections are refused now and then): retried twice, then the archive
    is skipped for every company for COMMONCRAWL_DOWN_SECONDS."""
    for attempt in range(3):
        try:
            r = http.request(method, url, headers=headers, timeout=_timeout(deadline))
        except LookupError_:
            raise
        except httpx.HTTPError:
            if attempt == 2:
                _mark_down()
                raise LookupError_("NETWORK_ERROR") from None
            time.sleep(1 + attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(1 + attempt)
            continue
        if r.status_code not in (200, 206):
            raise LookupError_("INDEX_ERROR")
        return r
    raise LookupError_("INDEX_ERROR")


def _range(http, url: str, start: int, end: int, deadline: float | None) -> bytes:
    return _static(http, "GET", url, deadline, {"Range": f"bytes={start}-{end}"}).content


def _index(http, crawl: str, host: str, deadline: float | None = None) -> list[dict]:
    """One host's HTML captures in one crawl, from the crawl's static ZipNum index on data.commoncrawl.org:
    cluster.idx (sorted; one line per block of 3,000 index lines) binary-searched by byte ranges (~13 small
    requests), then only the compressed index blocks that can hold the host's key, by byte range. Never a whole
    index file."""
    import json

    prefix = surt_prefix(host)
    cluster = f"{ZIPNUM}/{crawl}/indexes/cluster.idx"
    try:
        size = int(_static(http, "HEAD", cluster, deadline).headers["content-length"])
    except (KeyError, ValueError):
        raise LookupError_("INDEX_ERROR") from None
    lo, hi = 0, size
    while hi - lo > 65536:  # the last cluster line at or before the prefix lies in [lo, hi)
        mid = (lo + hi) // 2
        lines = _range(http, cluster, mid, min(mid + 16383, size - 1), deadline).split(b"\n")
        key = lines[1].split(b" ", 1)[0].decode("utf-8", "replace") if len(lines) > 2 else None
        if key is None or key < prefix:
            lo = mid
        else:
            hi = mid
    lines = _range(http, cluster, lo, min(hi + 65536, size - 1), deadline).decode("utf-8", "replace").split("\n")
    lines = [line for line in (lines if lo == 0 else lines[1:]) if "\t" in line]
    entries = [(line.split(" ", 1)[0], line.split("\t")) for line in lines]
    blocks = []  # block i holds keys from its first key up to the next block's first key
    for i, (key, fields) in enumerate(entries):
        nxt = entries[i + 1][0] if i + 1 < len(entries) else None
        if key <= prefix + "￿" and (nxt is None or nxt >= prefix):
            blocks.append(fields)
    rows: list[dict] = []
    for fields in blocks[:MAX_INDEX_BLOCKS]:  # a giant site's index runs over many blocks: the first ones only
        name, offset, length = fields[1], int(fields[2]), int(fields[3])
        blob = _range(http, f"{ZIPNUM}/{crawl}/indexes/{name}", offset, offset + length - 1, deadline)
        try:
            text = gzip.decompress(blob).decode("utf-8", "replace")
        except (OSError, EOFError):
            raise LookupError_("PARSE_ERROR") from None
        for line in text.splitlines():
            if not line.startswith(prefix):
                continue
            try:
                row = json.loads(line.split(" ", 2)[2])
            except (IndexError, ValueError):
                raise LookupError_("PARSE_ERROR") from None
            if row.get("status") == "200" and "html" in (row.get("mime") or row.get("mime-detected") or ""):
                rows.append({k: row.get(k) for k in ("url", "digest", "filename", "offset", "length")} |
                            {"timestamp": line.split(" ", 2)[1]})
    return rows


def _record(db: Session, company_id: int | None, target: str, status: str, reason: str | None, items: int | None,
            useful: int | None, started: float, cached: bool) -> None:
    from app.models import SourceLookup

    db.add(SourceLookup(company_id=company_id, source_key="common_crawl", target=target[:500], status=status,
                        failure_reason=reason, items=items, useful_items=useful, cached=cached,
                        duration_ms=int((time.perf_counter() - started) * 1000)))
    db.commit()


def captures(db: Session, http, crawl: str, domain: str, stats, company_id: int | None = None,
             deadline: float | None = None) -> list[dict]:
    """Captures of the company's own hosts (example.com and www.example.com) in one crawl; every lookup recorded."""
    rows: list[dict] = []
    base = canonical_domain(domain)
    for host in (base,):  # www.example.com shares example.com's index key
        if not available():
            break  # went down meanwhile: not waited on again
        started = time.perf_counter()
        try:
            found, cached = cached_json(db, "commoncrawl", f"{crawl}:{host}/*", 365,
                                        lambda h=host: _index(http, crawl, h, deadline))
        except LookupError_ as exc:
            stats["commoncrawl_index_errors"] += 1
            _record(db, company_id, f"{crawl}:{host}", "failed", exc.reason, None, None, started, False)
            continue
        except Exception as exc:
            stats["commoncrawl_index_errors"] += 1
            logger.info("common crawl index %s %s: %s", crawl, host, exc.__class__.__name__)
            _record(db, company_id, f"{crawl}:{host}", "failed", "NETWORK_ERROR", None, None, started, False)
            continue
        stats["commoncrawl_index_cached" if cached else "commoncrawl_index_calls"] += 1
        useful = sum(1 for r in found if _rank(r.get("url", "")) is not None)
        _record(db, company_id, f"{crawl}:{host}", "ok", None if found and useful else (
            "NO_CAPTURE" if not found else "NO_USEFUL_PAGE"), len(found), useful, started, cached)
        rows += found
    return rows


def _rank(url: str) -> int | None:
    path = re.sub(r"^https?://[^/]+", "", url).split("?")[0].lower()
    if SKIP.search(path):
        return None
    if re.search(r"team|management|leadership|leaders|board|directors|executive|our-people|/people|staff|equipe|"
                 r"direction|فريق", path):
        return 0
    if PEOPLE_PATH.search(path):
        return 1
    if NEWS_ROLE.search(path) or CONTACT_PATH.search(path):
        return 2
    if OPERATIONS_PATH.search(path):
        return 3  # company facts (sites, products), not people
    return None


def own_host(url: str, domain: str) -> bool:
    """The company's own site only: example.com / www.example.com, never another subdomain (an agency's client
    sites, a hosting customer, a franchise)."""
    host = (re.match(r"^https?://([^/:]+)", url or "") or [None, ""])[1].lower()
    return host in (domain, f"www.{domain}")


def select_captures(db: Session, company: Company, rows: list[dict], limit: int) -> list[dict]:
    """The most useful captures: people pages first, the newest of each page, one per content digest, none the
    live research already read, on the company's own host only."""
    live = {re.sub(r"^https?://(www\.)?", "", u).rstrip("/").lower() for u in db.scalars(
        select(CompanyWebPage.url).where(CompanyWebPage.company_id == company.id,
                                         CompanyWebPage.content.is_not(None)))}
    best: dict[str, dict] = {}
    for row in rows:
        if not own_host(row.get("url", ""), company.domain or ""):
            continue
        rank = _rank(row.get("url", ""))
        key = re.sub(r"^https?://(www\.)?", "", row.get("url", "")).split("?")[0].rstrip("/").lower()
        if rank is None or key in live:
            continue
        if key not in best or row["timestamp"] > best[key]["timestamp"]:
            best[key] = {**row, "rank": rank}
    seen_digest: set[str] = set()
    chosen = []
    for row in sorted(best.values(), key=lambda r: (r["rank"], -int(r["timestamp"]))):
        if row.get("digest") in seen_digest:
            continue
        seen_digest.add(row.get("digest"))
        chosen.append(row)
        if len(chosen) >= limit:
            break
    return chosen


def warc_html(blob: bytes) -> str | None:
    """The HTML body of one gzipped WARC response record."""
    try:
        data = gzip.decompress(blob)
    except OSError:
        return None
    parts = data.split(b"\r\n\r\n", 2)  # WARC headers, HTTP headers, body
    if len(parts) < 3:
        return None
    http_headers, body = parts[1].decode("latin-1").lower(), parts[2]
    # (Common Crawl stores bodies decoded, the original header renamed X-Crawler-Content-Encoding)
    if re.search(r"(?m)^content-encoding:\s*gzip", http_headers):
        try:
            body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
        except OSError:
            return None
    charset = re.search(r"charset=([\w-]+)", http_headers)
    try:
        return body.decode(charset[1] if charset else "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def captured_at(timestamp: str) -> datetime:
    return datetime.strptime(timestamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def document(db: Session, http, capture: dict, stats):
    """(ExternalDocument, Source, Doc) of one capture, cached: an archived page never changes."""
    url = f"{capture['url']}#commoncrawl-{capture['timestamp']}"
    row = db.scalar(select(ExternalDocument).where(ExternalDocument.url == url[:2000]))
    if row is None:
        start, length = int(capture["offset"]), int(capture["length"])
        r = _paced(http, "GET", f"{DATA}/{capture['filename']}", timeout=INDEX_TIMEOUT,
                   headers={"Range": f"bytes={start}-{start + length - 1}"})
        stats["commoncrawl_records_fetched"] += 1
        html = warc_html(r.content) if r.status_code in (200, 206) else None
        if not html:
            stats["commoncrawl_records_unreadable"] += 1
            if r.status_code in (200, 206, 404, 416):  # unreadable / missing record: remembered, never refetched
                db.add(ExternalDocument(url=url[:2000], final_url=capture["url"][:2000], domain="commoncrawl.org",
                                        category="web_archive", doc_type="html", http_status=r.status_code,
                                        retrieved_at=datetime.now(timezone.utc),
                                        metadata_={"source": "common_crawl", "unreadable": True}))
                db.commit()
            return None
        doc = parse(html, capture["url"])
        when = captured_at(capture["timestamp"])
        source = Source(source_type="web_archive", name=f"{(doc.title or capture['url'])[:240]} (archived "
                                                         f"{when.date().isoformat()})",
                        url=url[:2000], publisher="commoncrawl.org", retrieved_at=datetime.now(timezone.utc),
                        published_at=when, source_quality=88, content_hash=capture.get("digest"),
                        metadata_={"connector": "common_crawl", "category": "web_archive",
                                   "original_url": capture["url"], "captured_at": when.isoformat(),
                                   "warc": capture["filename"]})
        db.add(source)
        db.flush()
        row = ExternalDocument(url=url[:2000], final_url=capture["url"][:2000], domain="commoncrawl.org",
                               category="web_archive", doc_type="html", title=(doc.title or "")[:500] or None,
                               content_hash=capture.get("digest"), http_status=200, published_at=when,
                               retrieved_at=datetime.now(timezone.utc),
                               fresh_until=datetime.now(timezone.utc) + timedelta(days=3650), source_id=source.id,
                               content=doc.to_json(), metadata_={"source": "common_crawl",
                                                                  "captured_at": when.isoformat()})
        db.add(row)
        db.commit()
    else:
        stats["commoncrawl_records_cached"] += 1
        if row.content is None:
            return None  # known unreadable
    from app.services.enrichment.pages import Doc

    return row, db.get(Source, row.source_id), Doc.from_json(row.content or {})
