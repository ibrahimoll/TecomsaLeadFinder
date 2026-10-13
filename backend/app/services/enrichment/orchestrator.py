"""Company research (Step 4): one company's official website -> evidence -> structured company intelligence.

    Company (website from discovery or typed in)
      -> enrichment queue (research_runs 'company_enrichment', by priority: opened company > search results)
      -> homepage: reachable? parked? ownership validation (is this really the company's site?)
      -> page discovery (navigation links + known page types, same site only, crawl budget)
      -> page fetching (SSRF-safe, robots.txt, per-host pacing; unchanged & fresh pages are not fetched again)
      -> raw source per page version (company_web_pages + sources) -> deterministic extraction (extract.py)
      -> evidence -> contacts / locations / signals / products -> canonical company fields (persistence.py)

Each page is committed as soon as it is processed, so the company page fills in progressively. A website that
is down, blocks robots or needs JavaScript gives a `partial` result, never a failed company. Never people
(team pages are stored for Step 5), never AI, never anything not read from the company's own pages.
"""

import hashlib
import re
import logging
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlsplit

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (Company, CompanyLocation, CompanySignal, CompanyWebPage, Evidence, Phone, PossibleDuplicate,
                        ResearchRun, Source)
from app.models.enums import EnrichmentStatus, IdentityConfidence, ResearchRunStatus
from app.services import jobs
from app.services.discovery.consolidation import name_tokens
from app.services.discovery.domain_resolution import _PARKED
from app.services.discovery.fetch import Fetcher, FetchError
from app.services.discovery.geography import _fold, find_country
from app.services.discovery.web import PoliteFetcher
from app.services import completeness
from app.services.enrichment import persistence
from app.services.enrichment.extract import Context, Fact, _NUMBER, _phone, extract, normalize_offering
from app.services.enrichment.pages import (MAX_PER_TYPE, Doc, candidate_links, classify, needs_javascript,
                                           normalize_url, parse)
from app.services.normalization import company_domain, normalize_website

logger = logging.getLogger("leadfinder.enrichment")

EXTRACTOR_VERSION = 1  # bump when extraction changes: stored pages are re-extracted without fetching again
# How long a fetched page is trusted before it is fetched again, by page type (news and careers age fastest).
PAGE_TTL_DAYS = {"homepage": 14, "about": 60, "contact": 30, "locations": 30, "products": 30, "services": 30,
                 "manufacturing": 60, "careers": 7, "news": 7, "team": 30, "other": 30}
# Job priorities (lower first): the company a user is looking at (opened or refreshed), then search results,
# then (later) background refreshes of stale data.
OPENED, SEARCH, STALE = 10, 20, 40
OPENED_NO_PEOPLE = 5  # a salesperson opened a company LeadFinder knows no one at: researched first
RETRY_AFTER = timedelta(hours=1)  # research that crashed / was interrupted is not retried on every page view
CONFIRMED, PLAUSIBLE = 60, 45  # website ownership score thresholds
_GUESSES = ("/about", "/about-us", "/contact", "/contact-us")


@lru_cache(maxsize=1)
def website_fetcher() -> PoliteFetcher:
    """One per worker process: robots.txt, page cache and per-host pacing span jobs. Replaced in tests."""
    s = get_settings()
    return PoliteFetcher(Fetcher(max_bytes=s.website_max_bytes, timeout=s.website_timeout_seconds, truncate=True),
                         min_interval=s.website_min_interval_seconds)


# ---- queueing ----------------------------------------------------------------------------------------------------


def is_fresh(company: Company, now: datetime | None = None) -> bool:
    """Recently researched: not researched again when opened (a manual refresh still can)."""
    if company.enrichment_completed_at is None:
        return False
    age = (now or datetime.now(timezone.utc)) - company.enrichment_completed_at
    if company.enrichment_status == EnrichmentStatus.FAILED or company.enrichment_version is None:
        return age < RETRY_AFTER  # crashed / interrupted: retried later, not on every page view
    if company.enrichment_version != EXTRACTOR_VERSION:
        return False  # researched by an older extractor
    return age < timedelta(days=get_settings().enrichment_fresh_days)


def can_find_website(priority: int) -> bool:
    """A company without a website is researched only when a person asked (searched, opened, refreshed it): its
    website is then looked for on the web first (never for background research: the search engines' patience)."""
    from app.services.people.external import search

    return priority <= OPENED and search.provider("company") is not None


def find_website(db: Session, company: Company, stats: Counter) -> bool:
    """The company's own website from a web search, verified on the site (its name and country), as the direct
    search does; its Facebook / Instagram / LinkedIn pages from the same results fill the empty social links (only
    when one page per network carries its whole name). Returns whether a website was found (set on the company)."""
    from types import SimpleNamespace

    from app.services import company_lookup, company_search
    from app.services.discovery.domain_resolution import resolve_website

    country = find_country(company.headquarters_country or "Lebanon")
    intent = SimpleNamespace(city=company.headquarters_city, industry=None, country=country.name if country else None)
    found = company_lookup.web_search(company_search.parse(company.name), country, intent)
    pages: dict[str, set[str]] = {}
    for f in found:
        if f.candidate.source_type == "public_web" and f.candidate.source_url:
            for column, url in resolve_website(f.candidate.source_url).social.items():
                pages.setdefault(column, set()).add(url)
    for column, urls in pages.items():
        if len(urls) == 1 and not getattr(company, column):  # two different pages: not sure which is theirs
            setattr(company, column, urls.pop())
            stats["social_found"] += 1
    own = re.sub(r"[^a-z0-9]", "", _fold(company.name))
    sites = [f for f in found if f.candidate.source_type == "company_website" and f.candidate.website]
    # a known company's site that names it without saying where (no Lebanon on its home page) is enough when the
    # domain is its name ('malakaltawouk.com'): the ownership check below still decides whether it is used
    site = next((f.candidate.website for f in sites if f.strength == "strong"), None) or next(
        (f.candidate.website for f in sites if len(own) >= 5
         and own in (company_domain(f.candidate.website) or "").replace("-", "")), None)
    if site:
        company.website = normalize_website(site) or site
        stats["website_found"] = 1
    db.commit()
    return bool(site)


def request(db: Session, company: Company, priority: int, *, force: bool = False, user_id: int | None = None,
            search_id: int | None = None) -> bool:
    """Queue research of the company unless it is fresh / already queued (then only its priority is raised).
    The caller commits. Returns whether a research run is (now) queued for it."""
    if not get_settings().enrichment_enabled or not (company.website or can_find_website(priority)):
        return False
    running = company.enrichment_status in (EnrichmentStatus.QUEUED, EnrichmentStatus.RESEARCHING)
    if not force and (running or is_fresh(company)):
        if company.enrichment_status == EnrichmentStatus.QUEUED:
            db.execute(text("UPDATE research_runs SET priority = LEAST(priority, :p) WHERE company_id = :c AND "
                            "research_type = :k AND status = 'queued'"),
                       {"p": priority, "c": company.id, "k": jobs.ENRICHMENT})
        return False
    stmt = insert(ResearchRun).values(company_id=company.id, search_id=search_id, research_type=jobs.ENRICHMENT,
                                      status=ResearchRunStatus.QUEUED.value, priority=priority,
                                      requested_by_user_id=user_id, metadata_={"force": force, **jobs.chained()})
    db.execute(stmt.on_conflict_do_update(
        index_elements=["company_id", "research_type"], index_where=text(jobs.ACTIVE),
        set_={"priority": func.least(ResearchRun.priority, priority),
              **({"metadata": stmt.excluded.metadata} if force else {})}))
    jobs.wake(db, jobs.ENRICHMENT)
    if company.enrichment_status != EnrichmentStatus.RESEARCHING:
        company.enrichment_status = EnrichmentStatus.QUEUED.value
    return True


# ---- website ownership ---------------------------------------------------------------------------------------------


def ownership(db: Session, company: Company, doc: Doc, domain: str, ctx: Context) -> tuple[int, list[str]]:
    """0-100: how sure LeadFinder is that this website is the company's own. Below PLAUSIBLE it is not used."""
    tokens, compact = ctx.tokens, ctx.compact
    names = " ".join(filter(None, [doc.title, doc.meta.get("og:site_name"), doc.meta.get("og:title")]
                            + [str(i.get("name")) for i in doc.jsonld if isinstance(i.get("name"), str)]))
    label = domain.split(".")[0].replace("-", "")
    score, reasons = 0, []
    if tokens & set(name_tokens(names)) or (compact and compact in "".join(name_tokens(names))):
        score, reasons = score + 40, reasons + ["company name in the site title"]
    if compact and (compact in label or (len(label) >= 4 and label in compact)):
        score, reasons = score + 40, reasons + ["company name in the domain"]
    elif tokens and any(t in label for t in tokens if len(t) >= 4):
        score, reasons = score + 20, reasons + ["part of the name in the domain"]
    if tokens & set(name_tokens(" ".join(doc.text()))):
        score, reasons = score + 20, reasons + ["company name on the page"]
    known = set(db.scalars(select(Phone.normalized_phone).where(Phone.company_id == company.id,
                                                                Phone.person_id.is_(None))))
    page_phones = {_phone(m[0], ctx) for t in doc.text() for m in _NUMBER.finditer(t)}
    page_phones |= {_phone(url[4:], ctx) for url, _, _ in doc.links if url.startswith("tel:")}
    if known & (page_phones - {None}):
        score, reasons = score + 40, reasons + ["published phone matches"]
    if company.headquarters_city and _fold(company.headquarters_city) in _fold(" ".join(doc.text())):
        score, reasons = score + 10, reasons + ["city matches"]
    if db.scalar(select(Evidence.id).join(Source, Source.id == Evidence.source_id).where(
            Evidence.company_id == company.id, Evidence.field_name == "website",
            Source.source_type != "company_website").limit(1)):
        score, reasons = score + 10, reasons + ["a directory links to it"]
    return min(score, 100), reasons


def _claim_domain(db: Session, company: Company, domain: str) -> None:
    """Sets the verified domain, unless another company already owns it (then flagged, never merged)."""
    owner = db.scalar(select(Company).where(Company.domain == domain, Company.id != company.id).limit(1))
    if owner is None:
        company.domain = domain
        return
    low, high = sorted((company.id, owner.id))
    if not db.scalar(select(PossibleDuplicate.id).where(PossibleDuplicate.company_id == low,
                                                        PossibleDuplicate.other_company_id == high)):
        db.add(PossibleDuplicate(company_id=low, other_company_id=high, reason="Same verified website domain"))


# ---- fetching ----------------------------------------------------------------------------------------------------


@dataclass
class Fetched:
    doc: Doc | None = None
    source: Source | None = None
    status: int | None = None
    error: str | None = None
    changed: bool = False  # new content (or a new extractor): extract it
    cached: bool = False  # not fetched: the stored copy is still fresh
    final_url: str | None = None
    digest: str | None = None


def _get_page(db: Session, company: Company, url: str, page_type: str, *, force: bool, quality: int,
              stats: Counter) -> Fetched:
    now = datetime.now(timezone.utc)
    row = db.scalar(select(CompanyWebPage).where(CompanyWebPage.company_id == company.id, CompanyWebPage.url == url))
    if row and not force and row.content and row.fresh_until and row.fresh_until > now and (row.http_status or 0) < 400:
        stats["pages_cached"] += 1
        return Fetched(Doc.from_json(row.content), db.get(Source, row.source_id), row.http_status,
                       changed=row.extractor_version != EXTRACTOR_VERSION, cached=True,
                       final_url=row.canonical_url or url, digest=row.content_hash)
    started = time.perf_counter()
    try:
        page = website_fetcher().get(url)
    except FetchError as exc:
        stats["fetch_seconds"] += time.perf_counter() - started
        stats[f"rejected_{exc.kind.lower()}"] += 1
        return Fetched(error=exc.kind)
    stats["fetch_seconds"] += time.perf_counter() - started
    stats["pages_fetched"] += 1
    if row is None:
        row = CompanyWebPage(company_id=company.id, url=url[:2000], page_type=page_type)
        db.add(row)
    digest = hashlib.sha256(page.html.encode("utf-8", "replace")).hexdigest()
    unchanged = row.content_hash == digest and row.content is not None and row.extractor_version == EXTRACTOR_VERSION
    doc = Doc.from_json(row.content) if unchanged else parse(page.html, page.url)
    source = None
    if page.status < 400:
        source = persistence.page_source(db, company, url=page.url, digest=digest, page_type=page_type,
                                         title=doc.title, retrieved_at=now, quality=quality)
        row.source_id = source.id
    row.canonical_url = (doc.meta.get("canonical") or page.url)[:2000]
    row.title = (doc.title or "")[:500] or None
    row.page_type, row.http_status, row.content_hash, row.retrieved_at = page_type, page.status, digest, now
    row.fresh_until = now + timedelta(days=PAGE_TTL_DAYS.get(page_type, 30))
    row.extractor_version, row.content = EXTRACTOR_VERSION, doc.to_json()
    row.metadata_ = {"final_url": page.url, "redirects": page.redirects, "bytes": len(page.html),
                     "truncated": page.truncated,
                     "language": doc.lang, "needs_javascript": needs_javascript(doc)}
    db.flush()
    if page.status >= 400:
        stats["rejected_http"] += 1
    return Fetched(doc, source, page.status, changed=not unchanged, final_url=page.url, digest=digest)


# ---- one company ----------------------------------------------------------------------------------------------------


def _finish(db: Session, company: Company, status: EnrichmentStatus, message: str | None) -> None:
    now = datetime.now(timezone.utc)
    company.enrichment_status, company.enrichment_message = status.value, message
    company.enrichment_completed_at = now
    company.enrichment_version = EXTRACTOR_VERSION
    if status in (EnrichmentStatus.COMPLETED, EnrichmentStatus.PARTIAL):
        company.last_enriched_at = now
        company.last_researched_at = now
    completeness.update(db, company)
    db.commit()


def _site_offerings(pages: list[tuple[str, Doc, list[Fact], Source | None]]) -> list[Fact]:
    """Products / services kept site-wide: a name that is a heading on pages of several kinds is site furniture
    ("Newsletter", "Our brands"), not an offering."""
    seen_on: dict[str, set[str]] = {}
    for page_type, doc, _, _ in pages:
        for heading in doc.headings():
            seen_on.setdefault(normalize_offering(heading), set()).add(page_type)
    best: dict[tuple[str, str], Fact] = {}
    for _, _, facts, _ in pages:
        for f in (f for f in facts if f.kind == "offering"):
            key = (f.name, normalize_offering(f.value))
            if len(seen_on.get(key[1], ())) < 2 and (
                    key not in best or best[key].confidence < f.confidence):
                best[key] = f
    kept = sorted(best.values(), key=lambda f: -f.confidence)
    return [f for kind in ("product", "category", "service") for f in [x for x in kept if x.name == kind][:40]]


def run(db: Session, company_id: int, *, force: bool = False, queue_wait: float | None = None,
        priority: int = SEARCH) -> dict:
    """Researches one company. Returns the timings / counters (stored on the research run)."""
    settings = get_settings()
    started = time.perf_counter()
    stats: Counter = Counter()
    timings: dict = {"queue_wait": round(queue_wait, 2) if queue_wait is not None else None}
    company = db.get(Company, company_id)
    if company is None or not (company.website or can_find_website(priority)):
        if company is not None:  # the website was removed since it was queued
            company.enrichment_status = EnrichmentStatus.NOT_STARTED.value
            db.commit()
        return {"status": "skipped", "message": "no website"}
    company.enrichment_status, company.enrichment_message = EnrichmentStatus.RESEARCHING.value, None
    company.enrichment_started_at = datetime.now(timezone.utc)
    db.commit()
    country = find_country(company.headquarters_country)
    ctx_country = (country.code if country else None, country.name if country else company.headquarters_country)

    def done(status: EnrichmentStatus, message: str | None) -> dict:
        _finish(db, company, status, message)
        from app.services.people import orchestrator as people  # people discovery follows company research

        if people.request(db, company, priority, force=force):
            db.commit()
        timings["total"] = round(time.perf_counter() - started, 2)
        result = {"status": status.value, "message": message, "timings": timings,
                  **{k: round(v, 2) if isinstance(v, float) else v for k, v in stats.items()}}
        logger.info("company=%s enrichment=%s %s", company.id, status.value, result)
        return result

    if not company.website:
        t = time.perf_counter()
        found = find_website(db, company, stats)
        timings["website_search"] = round(time.perf_counter() - t, 2)
        if not found:
            return done(EnrichmentStatus.PARTIAL, "No website of its own was found on the web" + (
                "; its social pages were added." if stats["social_found"] else "."))
    home_url = normalize_website(company.website) or company.website
    t = time.perf_counter()
    home = _get_page(db, company, home_url, "homepage", force=force, quality=persistence.WEBSITE_QUALITY, stats=stats)
    timings["homepage_fetch"] = round(time.perf_counter() - t, 2)
    if home.error or home.doc is None:
        return done(EnrichmentStatus.PARTIAL, f"The website could not be reached ({(home.error or 'error').lower()}).")
    if home.status >= 400:
        return done(EnrichmentStatus.PARTIAL, f"The website answered HTTP {home.status}.")
    domain = company_domain(home.final_url)
    if domain is None:
        return done(EnrichmentStatus.PARTIAL, "The website redirects to a social or link page.")
    if _PARKED.search(f"{home.doc.title or ''} {' '.join(home.doc.text()[:30])}"):
        return done(EnrichmentStatus.PARTIAL, "The domain looks parked or unused.")
    ctx = Context(company.name, ctx_country[0], ctx_country[1], domain)
    score, reasons = ownership(db, company, home.doc, domain, ctx)
    company.website_confidence = score
    stats["ownership_score"] = score
    if score < PLAUSIBLE:
        return done(EnrichmentStatus.PARTIAL, "The website could not be confirmed as this company's own, so it was "
                                              "not used.")
    _claim_domain(db, company, domain)
    if home.source is not None:
        persistence.evidence(db, home.source, company, Fact("field", "domain", domain, score, "; ".join(reasons)),
                             datetime.now(timezone.utc))
    company.last_verified_at = datetime.now(timezone.utc)
    if company.identity_confidence in (None, IdentityConfidence.LOW):
        company.identity_confidence = IdentityConfidence.MEDIUM.value  # its own website names it
    factor = 1.0 if score >= CONFIRMED else 0.9
    quality = round(persistence.WEBSITE_QUALITY * factor)
    country_name = company.headquarters_country or ctx_country[1] or ""
    pages: list[tuple[str, Doc, list[Fact], Source | None]] = []

    def process(page_type: str, fetched: Fetched) -> None:
        t0 = time.perf_counter()
        facts = [] if not fetched.changed else extract(fetched.doc, page_type, ctx)
        for f in facts:
            f.confidence = round(f.confidence * factor)
        t1 = time.perf_counter()
        stats["extraction_seconds"] += t1 - t0
        pages.append((page_type, fetched.doc, facts, fetched.source))
        if fetched.source is not None and facts:
            persistence.save_facts(db, company, fetched.source, [f for f in facts if f.kind != "offering"],
                                   datetime.now(timezone.utc), country_name)
            stats["facts"] += len(facts)
        db.commit()  # visible on the company page now
        stats["persist_seconds"] += time.perf_counter() - t1
        if facts and "first_useful_field" not in timings:
            timings["first_useful_field"] = round(time.perf_counter() - started, 2)

    process("homepage", home)
    js_only = needs_javascript(home.doc)
    t = time.perf_counter()
    queue = candidate_links(home.doc, domain)
    if not any(kind in ("about", "contact") for _, _, kind in queue):
        origin = f"{urlsplit(home.final_url).scheme}://{urlsplit(home.final_url).netloc}"
        queue += [(1, normalize_url(origin + path), classify(origin + path)) for path in _GUESSES]
    timings["page_discovery"] = round(time.perf_counter() - t, 3)
    stats["pages_discovered"] = len(queue)
    visited = {normalize_url(home_url), normalize_url(home.final_url)}
    digests = {home.digest}  # the same page under two URLs (/contact and /contact.php) is read once
    per_type: Counter = Counter()
    deadline = started + settings.enrichment_job_seconds
    timed_out = False
    while queue and stats["pages_fetched"] + stats["pages_cached"] < settings.enrichment_page_budget:
        if time.perf_counter() > deadline:
            timed_out = True
            break
        queue.sort(key=lambda c: -c[0])
        _, url, kind = queue.pop(0)
        if url in visited or per_type[kind] >= MAX_PER_TYPE.get(kind, 2):
            continue
        visited.add(url)
        fetched = _get_page(db, company, url, kind, force=force, quality=quality, stats=stats)
        if fetched.doc is None or (fetched.status or 0) >= 400:
            continue
        if company_domain(fetched.final_url) != domain:
            stats["rejected_offsite"] += 1
            continue
        if fetched.digest in digests:
            stats["rejected_duplicate"] += 1
            continue
        digests.add(fetched.digest)
        per_type[kind] += 1
        process(kind, fetched)
        for score_, link, link_kind in candidate_links(fetched.doc, domain):
            if link not in visited and per_type[link_kind] < MAX_PER_TYPE.get(link_kind, 2):
                queue.append((score_ - 10, link, link_kind))  # second level: after the first level's pages
    stats["pages_skipped_budget"] = len({u for _, u, _ in queue if u not in visited})

    kept = {id(f) for f in _site_offerings(pages)}
    for _, _, facts, source in pages:
        for f in facts:
            if id(f) in kept and source is not None:
                persistence.evidence(db, source, company, f, datetime.now(timezone.utc))
                persistence.offering(db, company, f, source)
    _multi_location(db, company)
    db.commit()
    stats["offerings"] = len(kept)
    try:  # passive DNS / RDAP technology intelligence: never fails the research
        from app.services.enrichment import domain_intel
        from app.services.people.external.lebanon import pack

        with pack.api_client() as http:
            stats["domain_signals"] = domain_intel.run(db, company, http)
    except Exception:
        db.rollback()
        logger.exception("company=%s domain intelligence failed", company.id)
        stats["domain_signals_failed"] = 1
    if js_only:
        return done(EnrichmentStatus.PARTIAL, "The website needs JavaScript to show its content; only what it "
                                              "publishes without JavaScript was read.")
    if timed_out:
        return done(EnrichmentStatus.PARTIAL, "Research stopped at its time limit; more pages can be read on refresh.")
    return done(EnrichmentStatus.COMPLETED, None)


def _multi_location(db: Session, company: Company) -> None:
    """Several distinct places on record (any source): a multi-location operation."""
    count = db.scalar(select(func.count()).where(CompanyLocation.company_id == company.id)) or 0
    if count < 2:
        return
    source_id = db.scalar(select(CompanyLocation.source_id).where(CompanyLocation.company_id == company.id,
                                                                  CompanyLocation.source_id.is_not(None)).limit(1))
    if source_id is None:
        return
    stmt = insert(CompanySignal).values(company_id=company.id, signal_type="multi_location", signal_value=None,
                                        confidence=70, source_id=source_id, observed_at=datetime.now(timezone.utc))
    db.execute(stmt.on_conflict_do_nothing(index_elements=["company_id", "signal_type", "signal_value"]))
