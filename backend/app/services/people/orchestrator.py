"""People discovery (Step 5): a company's public evidence -> people and their roles, by department.

    Company
      -> stored website pages (Step 4: team / about / contact / news / careers / home), re-used as stored;
         a team / about page older than PAGE_STALE_DAYS is fetched again (politely, same fetcher)
      -> pages whose content or extractor changed since the last run   (unchanged pages: nothing to do)
      -> person candidates (extract.py) [+ external PeopleSourceConnectors, none configured yet]
      -> company match (official site, not "CEO of another firm")  -> resolution (resolution.py)
      -> people + company_people + evidence + public contacts (persistence.py), committed page by page
      -> recompute: confirmations, weak-role guard, decision-maker coverage

Runs as its own job (research_runs 'people_discovery', research lanes), chained after company research or
queued when someone opens a company / its people. Never AI, never LinkedIn, never guessed emails.
"""

import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Company, CompanyWebPage, ResearchRun, Source
from app.models.enums import EnrichmentStatus, ResearchRunStatus
from app.services import jobs
from app.services.discovery.geography import find_country
from app.services.enrichment import orchestrator as enrichment
from app.services.enrichment.extract import Context
from app.services.enrichment.pages import Doc, candidate_links
from app.services import completeness
from app.services.people import persistence
from app.services.people.candidate import CONNECTORS
from app.services.people.extract import extract
from app.services.people.resolution import MIN_COMPANY_MATCH, resolve

logger = logging.getLogger("leadfinder.people")

PEOPLE_VERSION = 6  # bump when extraction changes: stored pages are processed again (no fetching)
FRESH_DAYS = 14  # people age faster than company facts
PAGE_STALE_DAYS = 21  # a stored team / about page older than this is fetched again before reading people
RETRY_AFTER = timedelta(hours=1)
PAGE_ORDER = {"team": 0, "about": 1, "news": 2, "contact": 3, "homepage": 4, "careers": 5, "other": 6}
REFETCH_TYPES = ("team", "about")
_LANGUAGE_PATH = re.compile(r"^(?:[a-z]{2}(?:[-_][a-z]{2})?|index\.\w+|home)?$", re.IGNORECASE)


def brand_page(website: str | None) -> bool:
    """https://www.movenpick.com/beirut, a store page on nike.com: the company's "website" is one page of a larger
    brand / group site, whose people (brand executives) do not work for this company."""
    path = urlsplit(website or "").path.strip("/")
    return bool(path) and not _LANGUAGE_PATH.match(path)


def is_fresh(company: Company, now: datetime | None = None) -> bool:
    if company.people_researched_at is None:
        return False
    age = (now or datetime.now(timezone.utc)) - company.people_researched_at
    if company.people_status == EnrichmentStatus.FAILED or company.people_version is None:
        return age < RETRY_AFTER
    return company.people_version == PEOPLE_VERSION and age < timedelta(days=FRESH_DAYS)


def request(db: Session, company: Company, priority: int, *, force: bool = False, user_id: int | None = None) -> bool:
    """Queue people discovery unless it is fresh / already queued (then only its priority is raised)."""
    running = company.people_status in (EnrichmentStatus.QUEUED, EnrichmentStatus.RESEARCHING)
    if not force and (running or is_fresh(company)):
        if company.people_status == EnrichmentStatus.QUEUED:
            db.execute(text("UPDATE research_runs SET priority = LEAST(priority, :p) WHERE company_id = :c AND "
                            "research_type = :k AND status = 'queued'"),
                       {"p": priority, "c": company.id, "k": jobs.PEOPLE})
        return False
    stmt = insert(ResearchRun).values(company_id=company.id, research_type=jobs.PEOPLE,
                                      status=ResearchRunStatus.QUEUED.value, priority=priority,
                                      requested_by_user_id=user_id, metadata_={"force": force, **jobs.chained()})
    db.execute(stmt.on_conflict_do_update(
        index_elements=["company_id", "research_type"], index_where=text(jobs.ACTIVE),
        set_={"priority": func.least(ResearchRun.priority, priority),
              **({"metadata": stmt.excluded.metadata} if force else {})}))
    jobs.wake(db, jobs.PEOPLE)
    if company.people_status != EnrichmentStatus.RESEARCHING:
        company.people_status = EnrichmentStatus.QUEUED.value
    return True


def request_research(db: Session, company: Company, priority: int, *, user_id: int | None = None) -> None:
    """Opening a company / its people: company research if it is due (people, then external people follow it),
    else website people if due, else external people for the departments still missing. A stage already queued /
    running only has its priority raised: the stages after it are chained by it, never queued early (a website
    people job run before company research would mark people "fresh" and skip the new pages)."""
    from app.services.people import gaps
    from app.services.people.external import orchestrator as external

    if priority <= enrichment.OPENED and not gaps.credible_people(db, company.id):
        priority = min(priority, enrichment.OPENED_NO_PEOPLE)  # nobody known yet: never researched by hand
    if enrichment.request(db, company, priority, user_id=user_id) or company.enrichment_status in _ACTIVE:
        return
    if request(db, company, priority, user_id=user_id) or company.people_status in _ACTIVE:
        return
    if external.request(db, company, priority, user_id=user_id) or company.external_people_status in _ACTIVE:
        return
    from app.services import contact_intelligence

    contact_intelligence.request(db, company, priority, user_id=user_id)


_ACTIVE = (EnrichmentStatus.QUEUED, EnrichmentStatus.RESEARCHING)
_FINAL = {EnrichmentStatus.COMPLETED: "completed", EnrichmentStatus.PARTIAL: "partial",
          EnrichmentStatus.FAILED: "failed", EnrichmentStatus.TIMED_OUT: "timed_out"}
ACTIVE_STATES = ("website_queued", "website_researching", "deep_queued", "deep_researching")


def research_state(db: Session, company: Company) -> dict:
    """The one user-facing state of a company's people research (the frontend never infers it from several fields,
    nor from an empty people list):

        website_queued / website_researching   company research or website people discovery is pending / running
        deep_queued / deep_researching         website done; deep public-source research pending / running
        completed / partial / failed / timed_out   the LAST stage that ran finished so (zero people is a valid
                                               completed state); idle: never researched
    """
    from app.services.people import gaps
    from app.models import CompanyGapReason

    website = (company.enrichment_status, company.people_status)
    if any(s in _ACTIVE for s in website):
        state, stage = ("website_researching" if EnrichmentStatus.RESEARCHING in website else "website_queued"), "website"
    elif company.external_people_status in _ACTIVE:
        state, stage = ("deep_researching" if company.external_people_status == EnrichmentStatus.RESEARCHING
                        else "deep_queued"), "deep"
    else:
        deep_last = company.external_people_status != EnrichmentStatus.NOT_STARTED and \
            company.external_people_researched_at is not None and (
                company.people_researched_at is None
                or company.external_people_researched_at >= company.people_researched_at)
        stage = "deep" if deep_last else "website"
        state = _FINAL.get(company.external_people_status if deep_last else company.people_status, "idle")
    people = gaps.credible_people(db, company.id)
    finished = state not in ACTIVE_STATES and state != "idle"
    return {
        "state": state, "stage": stage, "website_status": company.people_status,
        "external_status": company.external_people_status, "people_count": people,
        "finished_at": (company.external_people_researched_at if stage == "deep" else company.people_researched_at)
        if finished else None,
        "message": (company.external_people_message if stage == "deep" else company.people_message) if finished else None,
        "gap_reasons": sorted(set(db.scalars(select(CompanyGapReason.gap_reason).where(
            CompanyGapReason.company_id == company.id)))) if finished and not people else [],
    }


def _refresh_stale(db: Session, company: Company, pages: list[CompanyWebPage], force: bool, stats: Counter) -> None:
    """Team / about pages are fetched again when stale (people change faster than company facts); a team page
    linked from the stored pages but never fetched (company research skipped it) is fetched once."""
    if not company.website or not company.domain or (company.website_confidence or 0) < enrichment.PLAUSIBLE:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=PAGE_STALE_DAYS)
    quality = enrichment.persistence.WEBSITE_QUALITY
    for page in pages:
        if page.page_type in REFETCH_TYPES and (force or (page.retrieved_at or cutoff) <= cutoff):
            enrichment._get_page(db, company, page.url, page.page_type, force=True, quality=quality, stats=stats)
    if not any(p.page_type == "team" for p in pages):
        known = {p.url for p in pages}
        team = next((url for page in pages if page.page_type in ("homepage", "about")
                     for _, url, kind in candidate_links(Doc.from_json(page.content), company.domain)
                     if kind == "team" and url not in known), None)
        if team:
            enrichment._get_page(db, company, team, "team", force=False, quality=quality, stats=stats)
        elif not any(p.metadata_ and p.metadata_.get("team_search") for p in pages):
            # no linked team page: the site's own sitemap, then a few usual addresses (bounded, once)
            for url in _team_pages(company, stats)[:MAX_TEAM_PAGES]:
                fetched = enrichment._get_page(db, company, url, "team", force=False, quality=quality, stats=stats)
                if fetched.doc is not None and (fetched.status or 0) < 400:
                    stats["team_pages_found"] += 1
            home = next((p for p in pages if p.page_type == "homepage"), None)
            if home is not None:
                home.metadata_ = {**(home.metadata_ or {}), "team_search": datetime.now(timezone.utc).isoformat()}
    db.commit()


_TEAM_PATH = re.compile(r"/(?:our[-_]?)?(?:team|people|management|leadership|leaders|board(?:[-_]of[-_]directors)?|"
                        r"directors|executives?|founders|who[-_]we[-_]are|equipe|direction|management[-_]team)"
                        r"(?:[-_/][^/]*)?/?$", re.IGNORECASE)
_TEAM_GUESSES = ("/team", "/our-team", "/management", "/leadership", "/about-us/team", "/board-of-directors")
MAX_TEAM_PAGES = 2


def _team_pages(company: Company, stats: Counter) -> list[str]:
    """Team / management pages of the company's own site its sitemap lists (one level of child sitemaps), else
    the usual addresses that exist (a 404 is skipped)."""
    from app.services.discovery.fetch import FetchError
    from app.services.normalization import company_domain

    fetcher = enrichment.website_fetcher()
    site = urlsplit(company.website or "")
    origin = f"{site.scheme or 'https'}://{site.hostname or company.domain}"  # the site's own host (www. kept)
    found: list[str] = []
    try:
        sitemap = fetcher.get(f"{origin}/sitemap.xml")
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap.html or "") if (sitemap.status or 0) < 400 else []
        children = [u for u in locs if u.endswith(".xml")][:2]
        for child in children:
            page = fetcher.get(child)
            locs += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", page.html or "") if (page.status or 0) < 400 else []
        listed = [u for u in locs if company_domain(u) == company.domain and _TEAM_PATH.search(u.split("?")[0])]
        stats["sitemap_urls"] += len(locs)
    except (FetchError, OSError):
        listed = []
        stats["sitemap_unavailable"] += 1
    for url in listed or [origin + path for path in _TEAM_GUESSES]:
        try:
            page = fetcher.get(url)
        except (FetchError, OSError):
            continue
        if _is_team_page(page, company.domain):
            found.append(page.url)
            if len(found) >= MAX_TEAM_PAGES:
                break
        else:
            stats["team_pages_rejected"] += 1
    return list(dict.fromkeys(found))


_TEAM_WORDS = re.compile(r"\b(team|management|leadership|leaders|board|directors|executives?|our people|founders|"
                         r"équipe|equipe|direction|dirigeants)\b|فريق|الإدارة|مجلس الإدارة", re.IGNORECASE)
_EMPTY = re.compile(r"no posts found|nothing found|page not found|404|coming soon", re.IGNORECASE)


def _is_team_page(page, domain: str) -> bool:
    """A real team page: still at a team address after redirects (a site answering every address with its home
    page is not one), its title / main headings say so, and it is not an empty listing."""
    from app.services.normalization import company_domain

    if (page.status or 0) >= 400 or not page.html or company_domain(page.url) != domain:
        return False
    if not _TEAM_PATH.search(urlsplit(page.url).path):
        return False
    doc = Doc.from_json(__import__("app.services.enrichment.pages", fromlist=["parse"]).parse(page.html, page.url)
                        .to_json())
    heading = " ".join([doc.title or "", *doc.headings("12")])
    return bool(_TEAM_WORDS.search(heading)) and not _EMPTY.search(heading) and doc.text_length >= 200


def run(db: Session, company_id: int, *, force: bool = False, queue_wait: float | None = None,
        priority: int = enrichment.SEARCH) -> dict:
    started = time.perf_counter()
    stats: Counter = Counter()
    timings: dict = {"queue_wait": round(queue_wait, 2) if queue_wait is not None else None}
    company = db.get(Company, company_id)
    if company is None:
        return {"status": "skipped"}
    company.people_status, company.people_message = EnrichmentStatus.RESEARCHING.value, None
    db.commit()

    def pages() -> list[CompanyWebPage]:
        rows = db.scalars(select(CompanyWebPage).where(
            CompanyWebPage.company_id == company.id, CompanyWebPage.content.is_not(None),
            CompanyWebPage.source_id.is_not(None), CompanyWebPage.http_status < 400,
            CompanyWebPage.page_type.in_(list(PAGE_ORDER)))).all()
        return sorted(rows, key=lambda p: PAGE_ORDER[p.page_type])

    t = time.perf_counter()
    _refresh_stale(db, company, pages(), force, stats)
    timings["page_refresh"] = round(time.perf_counter() - t, 2)
    country = find_country(company.headquarters_country)
    ctx = Context(company.name, country.code if country else None, country.name if country else
                  company.headquarters_country, company.domain or "")
    now = datetime.now(timezone.utc)
    # Only a website confirmed as the company's own (not a page of a brand's site) speaks for its people.
    shared_site = brand_page(company.website)
    stored = pages() if (company.website_confidence or 0) >= enrichment.PLAUSIBLE and not shared_site else []
    read_hashes: set[str] = set()  # the same page stored under two addresses is read once
    for page in stored:
        if page.content_hash in read_hashes:
            stats["pages_duplicate"] += 1
            continue
        read_hashes.add(page.content_hash)
        meta = page.metadata_ or {}
        done = meta.get("people") or {}
        if not force and done.get("version") == PEOPLE_VERSION and done.get("hash") == page.content_hash:
            stats["pages_unchanged"] += 1
            continue
        stats["pages_read"] += 1
        source = db.get(Source, page.source_id)
        t = time.perf_counter()
        candidates = extract(Doc.from_json(page.content), page.page_type, ctx=ctx, source_id=page.source_id,
                             url=source.url, observed_at=page.retrieved_at or now,
                             ownership=company.website_confidence)
        t1 = time.perf_counter()
        stats["extraction_seconds"] += t1 - t
        stats["candidates"] += len(candidates)
        seen: set[int] = set()
        for c in candidates:
            c.company_id = company.id
            if c.company_match_confidence < MIN_COMPANY_MATCH:
                stats["rejected_weak_company_match"] += 1
                continue
            t2 = time.perf_counter()
            match = resolve(db, company.id, c)
            t3 = time.perf_counter()
            stats["resolution_seconds"] += t3 - t2
            stats["merged" if match.person else "new_people"] += 1
            stats["possible_duplicates"] += len(match.possible)
            seen.add(persistence.save(db, company, c, match, now).id)
            stats["persistence_seconds"] += time.perf_counter() - t3
        if page.page_type == "team" and seen:
            stats["no_longer_listed"] += persistence.mark_absent(db, company, source.url, seen)
        page.metadata_ = {**meta, "people": {"version": PEOPLE_VERSION, "hash": page.content_hash,
                                             "candidates": len(candidates)}}
        persistence.recompute(db, company)
        db.commit()  # people appear on the company page as each page is read
        if seen and "first_person" not in timings:
            timings["first_person"] = round(time.perf_counter() - started, 2)
    if stored and not shared_site:  # the site's business cards and people documents (Step 6.1), bounded, re-checked
        from app.services.people import artifacts

        for c in artifacts.run(db, company, stored, ctx, stats):
            persistence.save(db, company, c, resolve(db, company.id, c), now)
        db.commit()
    for connector in CONNECTORS:  # permitted external sources (none configured yet)
        stats[f"connector_{connector.key}"] = len(connector.people(company))
    coverage = persistence.recompute(db, company)
    completeness.update(db, company)
    company.people_status = (EnrichmentStatus.COMPLETED if stored or not company.website
                             else EnrichmentStatus.PARTIAL).value
    company.people_message = None if stored else (
        "No company website to read people from yet." if not company.website
        else "The company's website is a page of a larger brand or group site; the people listed there may not "
             "work for this company, so they were not used." if shared_site
        else "The company's website could not be read or confirmed as its own, so no people could be found yet.")
    company.people_researched_at, company.people_version = datetime.now(timezone.utc), PEOPLE_VERSION
    db.commit()
    from app.services.people.external import orchestrator as external  # public sources for what is missing

    if external.request(db, company, priority, force=force and external.is_due(db, company)):
        db.commit()
    else:  # no deep research to wait for: how to reach the people found, now
        from app.services import contact_intelligence

        if contact_intelligence.request(db, company, priority):
            db.commit()
    timings["total"] = round(time.perf_counter() - started, 3)
    result = {"status": company.people_status, "message": company.people_message, "timings": timings,
              "coverage": coverage, "pages_stored": len(stored),
              **{k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()}}
    logger.info("company=%s people=%s %s", company.id, company.people_status, result)
    return result
