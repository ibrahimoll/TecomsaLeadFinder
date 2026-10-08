"""Lebanon source pack: Lebanese public sources ingested ONCE, kept locally, matched to every company.

    sources.json (ABL, ICC, Ministry of Industry, IDAL, RDCL, ALI, Syndicate of Hospitals, GLEIF, Public
    Procurement Authority, official / licensed files)
      -> refresh(): each source's public documents, fetched politely when due (robots-aware, paced)
           unchanged document (same content hash)  -> nothing parsed again
           new / changed document                  -> parsed into Records (parsers.py), kept with the document
                                                      (external_documents.content), applied to all companies
      -> apply(company): the routed sources' records matched LOCALLY (records.match: domain, legal name, core name;
         never a group for its subsidiary) -> PersonCandidate -> Step 5 engine (resolution, titles, confidence,
         evidence) ; organisation records: identity (company_identifiers), company FACTS (phones, e-mails,
         locations, exact employee counts, founding year, legal name -> the same evidence-first store as website
         facts), signals and dated events (procurement awards), relationships (GLEIF parents)
      -> every stored document is indexed for full-text search (corpus.py)

The router (route) decides which sources are worth matching for a company: a hotel never looks at the Almanac of
Banks, a bank never at the factory lists. Opening a company never waits for any of these sources.
"""

import hashlib
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (Company, CompanyIdentifier, CompanyRelationship, CompanySignal, ExternalDocument,
                        Source)
from app.services.discovery.fetch import USER_AGENT, FetchError, _PublicOnlyTransport
from app.services.discovery.geography import find_country
from app.services.enrichment.pages import parse
from app.services.people import persistence
from app.services.people.external import corpus, documents
from app.services.people.external.lebanon import configured, identity, news, parsers
from app.services.people.external.lebanon.records import (Record, candidate, company_names, keys_of, match,
                                                           published_date)
from app.services.people.external.sources import blocked
from app.services.people.resolution import MIN_COMPANY_MATCH, resolve
from app.services.people.titles import classify, fold

logger = logging.getLogger("leadfinder.people.lebanon")
CONFIG = Path(__file__).with_name("sources.json")

# What a company is, from its industry and name (folded words): which sources are worth matching.
SECTOR_RULES = {
    "bank": r"\bbank|\bbanque|banking|financial services|\bfinance house|\bbanca\b|مصرف|بنك",
    "insurance": r"insurance|assurance|reinsurance|takaful|تامين",
    "manufacturing": r"manufactur|industr|factory|factories|usine|\bplant\b|مصنع|معمل|صناع",
    "food": r"\bfood|dairy|dairies|laiterie|bakery|bakeries|beverage|chocolate|confection|\bmills?\b|roaster|"
            r"\bmeat|winery|\bcaves?\b|مطاحن|البان|حلويات",
    "pharma": r"pharma|laborator|\bdrug|medical products|serum",
    "technology": r"technolog|software|\bict\b|\bit services|computer|digital|informatique",
    "agriculture": r"agricultur|\bfarm|agro",
    "healthcare": r"\bhospitals?\b|\bclinics?\b|medical cent|healthcare|health care|مستشفى|مستشفي",
    "construction": r"construct|contracting|contractor|real estate|developer|engineering|مقاولات|تعهدات|متعهد",
}


@dataclass(frozen=True)
class SourceConfig:
    key: str
    name: str
    parser: str
    sectors: tuple[str, ...]
    category: str
    source_type: str
    quality: int
    refresh_days: int
    access: str  # automated | manual_file | disabled
    urls: tuple[str, ...] = ()
    index: str | None = None
    index_link: str | None = None
    extra_index: tuple[str, ...] = ()
    urls_from_sectors: str | None = None
    ali_sectors: tuple[str, ...] = ()
    max_pages: int = 0  # paged listings: newest pages read per refresh (0: all)
    role: str = "directory"  # directory: matched to companies locally; news: an article index (news.py)
    extract: dict | None = None  # parser "configured": how to read the page / document (configured.py)
    page_template: str | None = None  # paged listing: "https://.../page/{n}" for n = page_start..max_pages
    page_start: int = 1
    notes: str = ""


@lru_cache(maxsize=1)
def configs() -> dict[str, SourceConfig]:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))["sources"]
    fields = SourceConfig.__dataclass_fields__
    return {d["key"]: SourceConfig(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items() if k in fields})
            for d in data}


# ---- router ------------------------------------------------------------------------------------------------------


def sectors_of(company: Company) -> set[str]:
    text = fold(f"{company.industry or ''} {company.name or ''} {company.legal_name or ''}")
    return {sector for sector, rule in SECTOR_RULES.items() if re.search(rule, text)}


def is_lebanese(company: Company) -> bool:
    country = find_country(company.headquarters_country) if company.headquarters_country else None
    return company.headquarters_country is None or (country is not None and country.code == "LB")


def directory_sources(company: Company) -> list[str]:
    """The Lebanon source pack entries that apply to this company (enabled, its sector)."""
    if not is_lebanese(company):
        return []
    sectors = sectors_of(company)
    return [c.key for c in configs().values() if c.access != "disabled" and c.role == "directory" and (
        "*" in c.sectors or sectors & set(c.sectors))]


def route(company: Company, *, search_configured: bool = False) -> list[str]:
    """Every people source to use for this company, in order: local directories first (no request), then the
    company's own outgoing links and documents, Wikidata, Common Crawl (only while people are missing), and the
    optional search API."""
    from app.services.people.orchestrator import brand_page

    keys = directory_sources(company)
    if company.domain:
        keys.append("company_links")
    if not brand_page(company.website):  # a brand's store page: the brand's items / pages are not this company's
        keys.append("wikidata")
    if company.domain and not brand_page(company.website):
        keys.append("common_crawl")
    if search_configured:
        keys.append("web_search")
    return keys


# ---- ingestion: fetch once, parse once per version ----------------------------------------------------------------


def api_client() -> httpx.Client:
    """For public APIs and JSON endpoints (Common Crawl, Wikidata, ABL listing): public addresses only."""
    return httpx.Client(transport=_PublicOnlyTransport(retries=1), timeout=httpx.Timeout(30, connect=10),
                        headers={"User-Agent": USER_AGENT}, follow_redirects=False, trust_env=False)


@lru_cache(maxsize=1)
def bulk_fetcher():
    """Background ingestion of whole directories (a 2 MB almanac on a slow server): the same secure, robots-aware,
    paced fetcher as research, with a longer deadline. Replaced in tests."""
    from app.services.discovery.fetch import Fetcher
    from app.services.discovery.web import PoliteFetcher

    return PoliteFetcher(Fetcher(max_bytes=30_000_000, timeout=90, accept_pdf=True),
                         min_interval=get_settings().website_min_interval_seconds)


def _get(url: str):
    reason = blocked(url)
    if reason and not re.search(r"\.xlsx?(\?|$)", urlsplit(url).path, re.IGNORECASE):  # official spreadsheets
        raise FetchError("BLOCKED_ADDRESS", reason)
    page = bulk_fetcher().get(url)
    if page.status >= 400:
        raise FetchError("CONNECT", f"HTTP {page.status}")
    return page


def _year(text: str) -> int | None:
    years = [int(y) for y in re.findall(r"(?<!\d)(20[0-3]\d)(?!\d)", text) if int(y) <= datetime.now().year]
    return max(years) if years else None


def _index_links(cfg: SourceConfig) -> list[str]:
    found: list[str] = list(cfg.urls)
    for index in filter(None, (cfg.index, *cfg.extra_index)):
        page = _get(index)
        body = page.html or page.raw.decode("utf-8", "replace")
        links = re.findall(r'href=["\']([^"\'#]+)["\']', body) + re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
        for href in links:
            url = urljoin(page.url, href.strip())
            if cfg.index_link and re.search(cfg.index_link, url) and url not in found:
                found.append(url)
    if cfg.urls_from_sectors:
        found += [cfg.urls_from_sectors.format(sector=quote(s)) for s in cfg.ali_sectors]
    if cfg.page_template:
        found += [cfg.page_template.format(n=n) for n in range(cfg.page_start, (cfg.max_pages or 1) + 1)]
    return found


def _documents(cfg: SourceConfig):
    """(url, doc_type, raw bytes or text, records, published) for each current document of an automated source."""
    if cfg.parser == "abl_hr":
        with api_client() as http:
            entries, page = [], 1
            while page <= 20:
                r = http.post(cfg.urls[0], json={"currentpage": page, "pagesize": 12, "LanguageID": "1"})
                if r.status_code != 200 and entries:
                    break  # past the last page the site answers with its error page
                r.raise_for_status()
                data = r.json()
                entries += data.get("Data") or []
                if data.get("HideLoadMore") or not data.get("Data"):
                    break
                page += 1
                time.sleep(1.0)
        raw = json.dumps(entries, sort_keys=True)
        yield cfg.urls[0], "json", raw, lambda: parsers.abl_hr(entries), datetime.now(timezone.utc)
        return
    if cfg.parser == "gleif":
        yield from _gleif(cfg)
        return
    if cfg.parser == "ppa_awards":
        for n in range(1, (cfg.max_pages or 20) + 1):
            try:
                page = _get(f"{cfg.urls[0]}?page={n}")
            except FetchError as exc:
                logger.info("lebanon source %s: page %s not read (%s)", cfg.key, n, exc.kind)
                continue
            html = page.html
            yield f"{cfg.urls[0]}?page={n}", "html", _ppa_rows(html), lambda h=html: parsers.ppa_awards(h), None
        return
    if cfg.parser == "icc_register":
        first = _get(cfg.urls[0])
        _, pages = parsers.icc_register(first.html)
        for n in range(1, max(pages, 1) + 1):
            page = first if n == 1 else _get(f"{cfg.urls[0]}?page={n}")
            html = page.html
            yield (f"{cfg.urls[0]}?page={n}", "html", html, lambda h=html: parsers.icc_register(h)[0], None)
        return
    for url in _index_links(cfg):
        try:
            page = _get(url)
        except FetchError as exc:
            logger.info("lebanon source %s: %s not read (%s)", cfg.key, url, exc.kind)
            continue
        year = _year(url)
        if cfg.parser == "abl_almanac":
            pages, meta = documents.pdf_pages(page.raw, max_pages=400, max_chars=3_000_000)
            yield (url, "pdf", page.raw, lambda p=pages: parsers.abl_almanac(p),
                   documents._published(meta.get("created")))
        elif cfg.parser == "idal":
            pages, meta = documents.pdf_pages(page.raw, max_pages=400, max_chars=3_000_000)
            year = _year(" ".join(t[:300] for _, t in pages[:4])) or year
            yield url, "pdf", page.raw, lambda p=pages, y=year: parsers.idal(p, y), None
        elif cfg.parser == "ministry_xls":
            yield url, "xls", page.raw, lambda r=page.raw, y=year: parsers.ministry_xls(r, y), None
        elif cfg.parser == "member_list":
            yield url, "html", page.html, lambda h=page.html: parsers.member_list(h), None
        elif cfg.parser == "configured":
            spec = cfg.extract or {}
            if page.raw and (found := configured.files(url, page.raw, spec)) is not None:
                yield url, url.lower().split("?")[0].rsplit(".", 1)[-1][:10], page.raw, lambda r=found: r, None
            elif page.raw:  # a PDF catalogue / programme
                pages, meta = documents.pdf_pages(page.raw, max_pages=400, max_chars=3_000_000)
                yield (url, "pdf", page.raw, lambda p=pages, sp=spec: configured.lines(p, sp),
                       documents._published(meta.get("created")))
            elif spec.get("mode") == "table":
                yield url, "html", page.html, lambda h=page.html, sp=spec: configured.tables(h, sp), None
            elif spec.get("mode") == "xpath":
                yield url, "html", page.html, lambda h=page.html, sp=spec: configured.xpath_items(h, sp), \
                    _page_date(page)
            elif spec.get("mode") == "regex":
                yield url, "html", page.html, lambda h=page.html, sp=spec: configured.regex_people(h, sp), None
            elif spec.get("mode") == "bios":
                doc = parse(page.html, page.url)
                yield url, "html", page.html, lambda d=doc, sp=spec: configured.bios(d, sp), _page_date(page)
            else:
                text = "\n".join(b[1] for b in parse(page.html, page.url).blocks if b[2] != "nav")
                yield url, "html", page.html, lambda t=text, sp=spec: configured.lines([(None, t)], sp), None
        elif cfg.parser == "lcs_contractor":
            records = parsers.lcs_contractor(page.html)
            if records:  # most ids are unused: nothing stored for them
                yield url, "html", page.html, lambda r=records: r, None
        elif cfg.parser == "news_sitemap":
            xml = page.raw.decode("utf-8", "replace") if page.raw else page.html
            yield url, "xml", xml, lambda x=xml: news.sitemap(x), None
        elif cfg.parser == "hospital":
            doc = parse(page.html, page.url)
            yield url, "html", page.html, lambda d=doc: parsers.hospital(d), None
        elif cfg.parser == "profiles":
            doc = parse(page.html, page.url)
            modified = next((doc.meta.get(k) for k in ("article:modified_time", "og:updated_time",
                                                        "article:published_time") if doc.meta.get(k)), None)

            def read(d=doc, m=modified):
                record = parsers.profile(d, cfg.name.split(" - ")[0])
                if record:
                    record.published = (m or "")[:10] or None
                return [record] if record else []
            yield url, "html", page.html, read, None


def _page_date(page) -> datetime | None:
    """A page's own last-modified / published date (meta tags), when it publishes one."""
    doc = parse(page.html, page.url)
    value = next((doc.meta.get(k) for k in ("article:modified_time", "og:updated_time", "article:published_time")
                  if doc.meta.get(k)), None)
    return documents._published(value)


def _ppa_rows(html: str) -> str:
    """The awards table only: the page around it (menus, a session token) changes on every request."""
    return html[html.find("<tbody>"):html.find("</tbody>")]


def _gleif(cfg: SourceConfig):
    """Every active LEI of Lebanon (two pages of the free GLEIF API), with each one's reported parents."""
    entries, parents = [], {}
    with api_client() as http:
        headers = {"Accept": "application/vnd.api+json"}
        for page in range(1, 20):
            params = {"filter[entity.legalAddress.country]": "LB", "page[size]": 100, "page[number]": page}
            for attempt in range(3):  # the free API is sometimes slow: retried, never hammered
                try:
                    r = http.get(cfg.urls[0], headers=headers, params=params, timeout=90)
                    break
                except httpx.TimeoutException:
                    if attempt == 2:
                        raise
                    time.sleep(10)
            r.raise_for_status()
            data = r.json()
            entries += data.get("data") or []
            if page >= (data.get("meta", {}).get("pagination", {}).get("lastPage") or 1):
                break
            time.sleep(1.0)
        for item in entries:
            item["parents"] = []
            for kind in ("direct-parent", "ultimate-parent"):
                link = ((item.get("relationships") or {}).get(kind) or {}).get("links", {}).get("lei-record")
                if not link:
                    continue  # no parent reported (or a reporting exception): nothing to follow
                if link not in parents:
                    time.sleep(0.5)
                    try:
                        r = http.get(link, headers=headers, timeout=90)
                        parents[link] = r.json().get("data") if r.status_code == 200 else None
                    except httpx.HTTPError:
                        parents[link] = None  # a parent not read now is read on the next refresh
                parent = parents[link]
                if parent:
                    name = ((parent.get("attributes") or {}).get("entity") or {}).get("legalName", {}).get("name")
                    item["parents"].append({"type": "parent" if kind == "direct-parent" else "ultimate_parent",
                                            "lei": parent.get("id"), "name": name})
    raw = json.dumps([{k: e.get(k) for k in ("id", "attributes", "parents")} for e in entries], sort_keys=True)
    yield cfg.urls[0] + "?filter[entity.legalAddress.country]=LB", "json", raw, lambda: parsers.gleif(entries), None


def store(db: Session, cfg: SourceConfig, url: str, doc_type: str, raw, read, published: datetime | None,
          *, reparse: bool = False, stats: Counter | None = None) -> ExternalDocument | None:
    """Keeps one document version. Returns the row when its records are new / changed (to apply), else None.
    reparse: parse an unchanged document again (after a parser improvement)."""
    stats = stats if stats is not None else Counter()
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode("utf-8", "replace")).hexdigest()
    row = db.scalar(select(ExternalDocument).where(ExternalDocument.url == url[:2000]))
    if row is not None and row.content_hash == digest and not reparse:
        row.retrieved_at, row.fresh_until = now, now + timedelta(days=max(cfg.refresh_days, 1))
        stats["documents_unchanged"] += 1
        db.commit()
        return None
    records = [r for r in read() if r]
    if row is None:
        row = ExternalDocument(url=url[:2000], category=cfg.category, doc_type=doc_type)
        db.add(row)
    version = ((row.metadata_ or {}).get("version") or 0) + 1
    row.final_url, row.domain, row.http_status, row.retrieved_at = url[:2000], (
        urlsplit(url).hostname or cfg.key)[:253], 200, now
    row.category, row.doc_type, row.content_hash = cfg.category, doc_type, digest
    row.published_at = published or row.published_at
    row.title = f"{cfg.name}" + (f" ({urlsplit(url).path.rsplit('/', 1)[-1][:120]})" if doc_type in ("pdf", "xls")
                                 else "")
    row.content = {"records": [r.to_json() for r in records]}
    row.fresh_until = now + timedelta(days=max(cfg.refresh_days, 1))
    row.metadata_ = {"source": cfg.key, "version": version, "records": len(records),
                     "people": sum(1 for r in records if r.person)}
    source = db.scalar(select(Source).where(Source.content_hash == digest, Source.url == url[:2000]).limit(1))
    if source is None:
        source = Source(source_type=cfg.source_type, name=row.title[:300], url=url[:2000], publisher=row.domain,
                        retrieved_at=now, published_at=row.published_at, source_quality=cfg.quality,
                        content_hash=digest, metadata_={"connector": cfg.key, "category": cfg.category,
                                                         "doc_type": doc_type, "records": len(records)})
        db.add(source)
        db.flush()
    row.source_id = source.id
    db.flush()
    corpus.index(db, row)
    db.commit()
    stats["documents_changed" if version > 1 else "documents_new"] += 1
    stats["records"] += len(records)
    return row


def due(db: Session, cfg: SourceConfig, now: datetime | None = None) -> bool:
    if cfg.access != "automated":
        return False
    last = db.scalar(select(ExternalDocument.fresh_until).where(
        ExternalDocument.metadata_["source"].astext == cfg.key).order_by(ExternalDocument.fresh_until).limit(1))
    return last is None or last <= (now or datetime.now(timezone.utc))


def refresh(db: Session, keys: list[str] | None = None, *, force: bool = False, reparse: bool = False,
            apply_changes: bool = True) -> dict:
    """refresh_lebanon_sources: every due source (or `keys`, or all with `force`) read again; new / changed
    documents are parsed once and applied to all known companies they concern (an unchanged one is not, unless
    `reparse`). Callable from scripts/lebanon_sources.py; not scheduled."""
    report: dict = {}
    changed: set[str] = set()
    for cfg in configs().values():
        if keys and cfg.key not in keys:
            continue
        if cfg.access != "automated" or not (force or due(db, cfg)):
            report[cfg.key] = {"skipped": cfg.access if cfg.access != "automated" else "fresh"}
            continue
        stats: Counter = Counter()
        started = time.perf_counter()
        try:
            for url, doc_type, raw, read, published in _documents(cfg):
                if store(db, cfg, url, doc_type, raw, read, published, reparse=reparse, stats=stats) is not None:
                    changed.add(cfg.key)
        except Exception as exc:  # one source failing never stops the others
            db.rollback()
            logger.exception("lebanon source %s failed", cfg.key)
            stats["error"] = 1
            stats["error_kind"] = exc.__class__.__name__
        report[cfg.key] = {**stats, "seconds": round(time.perf_counter() - started, 1)}
    if apply_changes and changed:
        report["applied"] = apply_all(db, sorted(changed))
    return report


def ingest_file(db: Session, key: str, name: str, text: str) -> dict:
    """An official / licensed file supplied by an operator (manual_file sources): stored and applied like any
    other document. The file itself is never fetched by LeadFinder."""
    cfg = configs()[key]
    if cfg.access != "manual_file":
        raise ValueError(f"{key} does not accept files (access: {cfg.access})")
    stats: Counter = Counter()
    row = store(db, cfg, f"file://{key}/{name}", "csv", text, lambda: parsers.csv_file(text), None, stats=stats)
    return {**stats, "applied": apply_all(db, [key]) if row is not None else None}


# ---- local matching ----------------------------------------------------------------------------------------------

_RECORDS: dict[tuple[int, str], list[Record]] = {}


def _loaded(db: Session, key: str) -> list[tuple[ExternalDocument, list[Record]]]:
    """The source's documents and their records (parsed JSON kept in-process per document version)."""
    rows = db.scalars(select(ExternalDocument).where(ExternalDocument.metadata_["source"].astext == key)).all()
    return [(row, parsed_records(row)) for row in rows]


def parsed_records(row: ExternalDocument) -> list[Record]:
    """A stored document's records, parsed once per process (and again only when its content changes)."""
    cache_key = (row.id, row.content_hash or "")
    if cache_key not in _RECORDS:
        _RECORDS[cache_key] = [Record.from_json(r) for r in (row.content or {}).get("records", [])]
    return _RECORDS[cache_key]


def _identifier(db: Session, company_id: int, scheme: str, value: str, source_id: int | None) -> None:
    db.execute(insert(CompanyIdentifier).values(company_id=company_id, scheme=scheme[:60], value=value[:300],
                                                source_id=source_id).on_conflict_do_nothing())


_BIO_TITLE = r"(?P<t>[A-Z][\w&’'./-]*(?:\s+(?:[A-Z&][\w&’'./-]*|of|and|for|the))*)"
_FORMER = re.compile(r"\b(former|formerly|previously|ex-|until 20\d\d|retired)\b", re.IGNORECASE)


def bio_roles(record: Record, aliases: list[str]) -> list[tuple[str, str]]:
    """(title, sentence) of the company roles a profile's biography states FOR this company: the alias and the
    title in the same sentence, tied by 'position of', 'X of/at <company>', '<company>'s X' or 'founded <company>'.
    The person's office at the association itself is never one of them."""
    found: list[tuple[str, str]] = []
    office = fold(record.association_role or "")
    for sentence in re.split(r"(?<=[.;!?])\s+", record.bio or ""):
        for alias in aliases:
            a = re.escape(alias)
            if not re.search(rf"(?<!\w){a}(?!\w)", sentence, re.IGNORECASE):
                continue
            titles = re.findall(rf"(?:position|role|post|capacity|title) of (?:the )?{_BIO_TITLE}", sentence)
            titles += re.findall(rf"{_BIO_TITLE},? (?:of|at) (?:the )?{a}(?!\w)", sentence)
            titles += re.findall(rf"(?<!\w){a}(?:'s|’s)? {_BIO_TITLE}", sentence)
            if re.search(rf"\b(?:co-)?(?:founded|founder of|established) (?:the )?(?:company )?{a}(?!\w)", sentence,
                         re.IGNORECASE):
                titles.append("Founder")
            for raw in titles:
                words = raw.strip(" .,;:").split()
                title = next((" ".join(words[:k]) for k in range(len(words), 0, -1)
                              if (t := classify(" ".join(words[:k]))) and t.explicit), None)
                if title and fold(title) != office and (title, sentence) not in found:
                    found.append((title, sentence.strip()))
    return found


def apply(db: Session, company: Company, keys: list[str] | None = None, stats: Counter | None = None) -> int:
    """Matches the routed sources' local records to one company and stores what they state. No network."""
    from app.services.people.external import planner

    stats = stats if stats is not None else Counter()
    keys = [k for k in (keys or directory_sources(company)) if k in configs()]
    if not keys or BRANCH_RECORD.search(company.name or ""):
        stats["skipped_branch_record"] += bool(keys)
        return 0
    ctx = identity.context(db, company)
    aliases = planner.aliases(db, company)
    stored = 0
    now = datetime.now(timezone.utc)
    possible: list[dict] = []
    for key in keys:
        cfg = configs()[key]
        for row, records in _loaded(db, key):
            decided: dict[tuple, tuple] = {}  # an organisation's match, shared by its people in this document
            for record in records:
                pairs: list[tuple[Record, int, str | None, str | None]] = []
                if record.bio:  # an association profile: the biography must name the company
                    pairs = [(record, 80, title, f"{record.excerpt}: {sentence}")
                             for title, sentence in bio_roles(record, aliases)]
                else:
                    org = tuple(record.org)
                    confidence, stage = decided.get(org) or identity.match(ctx, record)
                    decided.setdefault(org, (confidence, stage))
                    if confidence is not None:
                        pairs = [(record, confidence, None, None)]
                        stats[f"stage_{stage}"] += not record.person
                        if not record.person:
                            stats["aliases_learned"] += identity.learn_aliases(db, company, record, row.source_id,
                                                                               confidence)
                    elif stage.startswith("possible") and not record.person and len(possible) < 20:
                        possible.append({"source": key, "stage": stage, "org": record.org[:2]})
                for rec, confidence, title, excerpt in pairs:
                    stats[f"matched_{key}"] += 1
                    if not rec.bio and confidence >= 88:  # the organisation's official numbers (bank list,
                        # registry, licence...): only from a strong match, else a weak one would become 'identifier'
                        for scheme, value in rec.identifiers.items():
                            _identifier(db, company.id, scheme, value, row.source_id)
                    if not rec.person:
                        if rec.facts:
                            stats["company_facts"] += company_facts(
                                db, company, rec, row, cfg, confidence,
                                published_date(rec.published) or row.published_at)
                        continue
                    stated = published_date(rec.published) or row.published_at
                    if rec.bio and _FORMER.search(excerpt or ""):
                        rec = Record(**{**rec.__dict__, "status": "former"})
                    if title == "Founder":
                        rec = Record(**{**rec.__dict__, "status": "unknown"})
                    c = candidate(rec, company_id=company.id, source_id=row.source_id, url=row.url,
                                  source_type=cfg.category, quality=cfg.quality, match_confidence=confidence,
                                  stated=stated, category=cfg.category, document=row.title, title=title,
                                  excerpt=excerpt)
                    if c is None or c.company_match_confidence < MIN_COMPANY_MATCH:
                        stats["rejected_not_person_or_title"] += 1
                        continue
                    if rec.association_role:
                        c.raw_metadata["association_role"] = rec.association_role
                    persistence.save(db, company, c, resolve(db, company.id, c), now)
                    stored += 1
    if possible:
        stats["possible_matches"] = possible  # weak signals, never applied: for the gap diagnosis
    if stored or stats:
        persistence.recompute(db, company)
    db.commit()
    stats["directory_roles"] += stored
    return stored


# A company e-mail from a directory only when it is a role mailbox; 'bernard.tannoury@...' is a person's address.
ROLE_MAILBOX = re.compile(r"^(info|contact|contactus|sales|export|exports|office|admin|administration|hello|enquir\w*|"
                          r"inquir\w*|marketing|support|mail|general|reception|customerservice|cs|hr|careers|jobs|"
                          r"procurement|purchasing|finance|accounts|management|webmaster|service|services|"
                          r"[a-z]{2,6}(?:hospital|bank|lb))[\w.-]*@", re.IGNORECASE)
def role_mailbox(email: str) -> bool:
    local, _, domain = email.lower().partition("@")
    return bool(ROLE_MAILBOX.match(email)) or local == domain.split(".")[0]  # 'mlh@mlh.com.lb'


# A record of one branch / agency of a company ("Cedrus Bank Dora Branch"): the head office's people and switchboard
# belong to the company's own record, not to the branch's.
BRANCH_RECORD = re.compile(r"\b(branch|agence|succursale|showroom)\b|فرع", re.IGNORECASE)


def company_facts(db: Session, company: Company, record: Record, row: ExternalDocument, cfg: SourceConfig,
                  match_confidence: int, stated: datetime | None) -> int:
    """The company facts an organisation record states, through the website facts' evidence-first store
    (conflicting values kept as evidence; a value a person typed in never overwritten)."""
    from app.services.enrichment import persistence as company_store
    from app.services.enrichment.extract import Context, Fact, _phone, _phone_type

    f, excerpt = record.facts, record.excerpt[:500]
    confidence = min(cfg.quality, match_confidence)
    observed = stated or datetime.now(timezone.utc)
    ctx = Context(company.name, "LB", "Lebanon", company.domain or "")
    facts: list[Fact] = []
    if f.get("phone") and (number := _phone(str(f["phone"]), ctx)):
        facts.append(Fact("phone", "phone", number, confidence, excerpt,
                          {"published": str(f["phone"]), "phone_type": _phone_type(number, False),
                           "purpose": "general"}))
    if "@" in (f.get("email") or "") and role_mailbox(f["email"].strip()):  # never a person's address
        facts.append(Fact("email", "email", f["email"].strip().lower(), confidence, excerpt, {"purpose": "general"}))
    if f.get("address"):
        facts.append(Fact("location", "location", {"address": f["address"][:500], "city": f.get("city"),
                                                   "location_type": f.get("location_type")}, confidence, excerpt))
    as_of = {"as_of": observed.date().isoformat(), "kind": "exact", "source": cfg.key}
    for name, column in (("employees", "employee_count_estimate"), ("founded", "founded_year"),
                         ("legal_name", "legal_name"), ("legal_form", "legal_form")):
        if f.get(name):
            facts.append(Fact("field", column, f[name], confidence, excerpt, as_of if name == "employees" else {}))
    if f.get("technology"):
        facts.append(Fact("signal", "technology", f["technology"], confidence, excerpt))
    if f.get("description"):
        facts.append(Fact("field", "description", f["description"], min(confidence, 70), excerpt))
    for name, signal in (("branches", "branches"), ("beds", "hospital_beds")):
        if f.get(name):
            facts.append(Fact("signal", signal, str(f[name]), confidence, excerpt))
    facts += [Fact("signal", s, None, confidence, excerpt) for s in f.get("signals") or []]
    if facts:
        company_store.save_facts(db, company, db.get(Source, row.source_id), facts, observed, "Lebanon")
    if award := f.get("award"):
        _award(db, company, award, row, confidence, observed)
    if event := f.get("event"):  # an exhibitor / sponsor / award entry: participation, dated by the edition
        year = event.get("year")
        stmt = insert(CompanySignal).values(
            company_id=company.id, signal_type="event_participation",
            signal_value=f"{event.get('name')} {year or ''}".strip()[:300], confidence=confidence,
            source_id=row.source_id, observed_at=observed,
            event_date=date(int(year), 1, 1) if year else None,
            description=f"Took part in {event.get('name')}{f' {year}' if year else ''}"
                        f"{' (' + f['sector'] + ')' if f.get('sector') else ''}"[:1000],
            detail={"event": event, "source": cfg.key})
        db.execute(stmt.on_conflict_do_nothing())
    for rel in f.get("relationships") or []:
        related = db.scalar(select(CompanyIdentifier.company_id).where(CompanyIdentifier.scheme == "lei",
                                                                       CompanyIdentifier.value == rel.get("lei")))
        stmt = insert(CompanyRelationship).values(
            company_id=company.id, related_company_id=related if related != company.id else None,
            related_name=(rel.get("name") or rel.get("lei") or "")[:300], relation_type=rel["type"],
            source_id=row.source_id, confidence=confidence, detail={"lei": rel.get("lei")}, observed_at=observed)
        db.execute(stmt.on_conflict_do_update(constraint="uq_company_relationships_company_relation",
                                              set_={"related_company_id": stmt.excluded.related_company_id,
                                                    "observed_at": stmt.excluded.observed_at}))
    return len(facts) + bool(award) + bool(event) + len(f.get("relationships") or [])


def _award(db: Session, company: Company, award: dict, row: ExternalDocument, confidence: int,
           observed: datetime) -> None:
    """A public contract won: a dated company signal (the timeline), never a person."""
    when = published_date(award.get("date"))
    stmt = insert(CompanySignal).values(
        company_id=company.id, signal_type="procurement_award", signal_value=f"tender {award['tender_id']}",
        confidence=confidence, source_id=row.source_id, observed_at=observed,
        event_date=when.date() if when else None,
        description=f"Won a public contract: {award.get('title') or 'tender'} ({award.get('amount') or 'amount not '
                                                                                    'published'})"[:1000],
        detail=award)
    db.execute(stmt.on_conflict_do_update(index_elements=["company_id", "signal_type", "signal_value"],
                                          set_={"detail": stmt.excluded.detail,
                                                "event_date": stmt.excluded.event_date}))


def apply_all(db: Session, keys: list[str]) -> dict:
    """Proactive use of new / changed source documents: every known company they concern."""
    stats: Counter = Counter()
    started = time.perf_counter()
    keys = [k for k in keys if configs()[k].role == "directory"]
    if not keys:
        return dict(stats)
    for company_id in db.scalars(select(Company.id).order_by(Company.id)).all():
        company = db.get(Company, company_id)
        routed = [k for k in keys if k in directory_sources(company)]
        if routed:
            stats["companies_checked"] += 1
            if apply(db, company, routed, stats):
                stats["companies_with_people"] += 1
    return {**stats, "seconds": round(time.perf_counter() - started, 1)}


