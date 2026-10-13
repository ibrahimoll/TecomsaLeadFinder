"""External people discovery (Step 5.1): people of a company from free public sources beyond its own website.

    Company -> current coverage -> missing priority departments -> source router (lebanon/pack.route)
      -> sources, cheapest first (none needs a paid API):
           Lebanon source pack  ABL, ICC, Ministry of Industry, IDAL, RDCL, ALI, official files: ingested ONCE
                                (lebanon/pack.refresh), matched here LOCALLY, no request
           company_documents    reports / PDFs on the company's site, and the professional pages it links to
                                (associations, chambers, conferences, regulators, customer stories)
           wikidata             the company's own Wikidata item (strictly resolved): CEO, chair, founder, board
           common_crawl         the company's own past pages (team / management / about) from the public web archive,
                                only while priority departments are still missing
           web_search           OPTIONAL, off by default (a paid search API; never a search engine's pages)
      -> secure fetch + cache (documents.py) -> people of THIS company in each document (extract.py)
      -> Step 5 engine: company match, resolution, title / department / seniority, confidence, evidence,
         people + company_people (persistence.py), committed document by document
      -> recompute coverage; stop early when the priority departments are covered or nothing new appears

Budgets per company (queries, results per query, fetches, PDFs, time) are settings. One failing source / provider
never stops the others. Search snippets are never facts. LinkedIn & co. are never fetched (sources.py).
Runs as its own job (research_runs 'external_people', its own lanes), after website people discovery, only while
priority departments are missing; again only after EXTERNAL_FRESH_DAYS.
"""

import logging
from urllib.parse import urlsplit
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Company, CompanyWebPage, ResearchRun
from app.models.enums import EnrichmentStatus, ResearchRunStatus
from app.services import completeness, jobs
from app.services.discovery.geography import find_country
from app.services.enrichment.pages import Doc
from app.services.normalization import company_domain
from app.services.people import persistence
from app.services.people.external import documents, planner, search
from app.services.people.external.extract import candidates
from app.services.people.external.lebanon import commoncrawl, news, pack, wikidata
from app.services.people.external.lebanon.records import published_date
from app.services.people.external.sources import CATEGORIES, Kind, blocked, kind_of
from app.services.people.resolution import MIN_COMPANY_MATCH, resolve
from app.services.people.titles import fold

logger = logging.getLogger("leadfinder.people.external")
VERSION = 1
NO_GAIN_STOP = 3  # consecutive queries without a new credible role
_REPORT_LINK = re.compile(r"annual|report|rapport|brochure|profile|profil|board|management|governance|leadership|"
                          r"financial[-_ ]statements|corporate|catalog|catalogue|presentation|organi[sz]ation|"
                          r"org[-_ ]?chart|our[-_ ]team|team|company|about|plaquette|تقرير|ملف", re.IGNORECASE)


def _own_site(url: str, domain: str | None) -> bool:
    """The company's own domain or one of its subdomains (files.example.com), never another site."""
    host = (urlsplit(url).hostname or "").lower()
    return bool(domain) and (host == domain or host.endswith("." + domain))


@dataclass
class SourceDocument:
    url: str
    kind: Kind
    origin: str  # connector key
    published: str | None = None
    hint: str = ""  # search title / link text (filtering only)


class PeopleSourceConnector(Protocol):
    """Locates public documents that may name the company's people. Never writes people."""

    key: str

    def documents(self, db: Session, company: Company, plan: planner.Plan, budget: "Budget") -> list[SourceDocument]:
        ...


class Budget:
    def __init__(self):
        s = get_settings()
        self.max_queries, self.per_query = s.external_max_queries, s.external_results_per_query
        self.max_fetches, self.max_pdfs = s.external_max_fetches, s.external_max_pdfs
        self.deadline = time.monotonic() + s.external_job_seconds
        self.queries = self.fetches = self.pdfs = 0

    def out_of_time(self) -> bool:
        return time.monotonic() > self.deadline

    def seconds_left(self) -> float:
        return self.deadline - time.monotonic()


class CompanyDocumentsConnector:
    """Without any search: PDFs / reports on the company's own site, and the professional pages its site links to
    (association / chamber memberships, conference appearances, regulators, customer stories): the company itself
    points at them. Never uncontrolled crawling: links of the stored pages only, high-value categories only."""

    key = "company_documents"
    LINK_CATEGORIES = ("association", "conference", "regulatory", "case_study")
    MAX_LINKS = 5

    def documents(self, db, company, plan, budget):
        if not company.domain:
            return []
        found: dict[str, SourceDocument] = {}
        links: dict[str, SourceDocument] = {}
        for content in db.scalars(select(CompanyWebPage.content).where(CompanyWebPage.company_id == company.id,
                                                                       CompanyWebPage.content.is_not(None))):
            for url, label, _ in Doc.from_json(content).links:
                if blocked(url):
                    continue
                if url.lower().split("?")[0].endswith(".pdf") and _own_site(url, company.domain) \
                        and _REPORT_LINK.search(f"{url} {label}"):
                    found.setdefault(url, SourceDocument(url, kind_of(url, label, company.domain), self.key,
                                                         hint=label))
                elif company_domain(url) not in (None, company.domain):
                    kind = kind_of(url, label, company.domain)
                    if kind.category in self.LINK_CATEGORIES:
                        links.setdefault(url, SourceDocument(url, kind, "company_links", hint=label))
        return list(found.values())[:budget.max_pdfs] + list(links.values())[:self.MAX_LINKS]


class WebSearchConnector:
    """The configured public search API: grouped queries for the missing departments, filtered results."""

    key = "web_search"

    def __init__(self, engine: search.PublicWebSearchProvider):
        self.engine = engine

    def run_query(self, db, company, query: planner.Query, plan: planner.Plan, budget: Budget, stats: Counter,
                  seen: set[str]) -> list[SourceDocument]:
        results, cached = search.cached_search(db, self.engine, query.text, limit=budget.per_query * 2)
        budget.queries += 1
        stats["search_queries"] += 1
        stats["search_cached"] += cached
        docs = []
        for r in results:
            if r.url in seen:
                continue
            seen.add(r.url)
            if blocked(r.url):
                stats["results_blocked"] += 1
                continue
            hint = f"{r.title} {r.snippet}"
            if not any(f" {fold(a)} " in f" {fold(hint)} " for a in plan.aliases) and \
                    company_domain(r.url) != company.domain:
                stats["results_not_about_company"] += 1  # another company with a similar name, unrelated page
                continue
            docs.append(SourceDocument(r.url, kind_of(r.url, r.title, company.domain), self.key, r.published,
                                       r.title))
            if len(docs) >= budget.per_query:
                break
        return docs


# ---- queueing ------------------------------------------------------------------------------------------------------


ZERO_PEOPLE_COOLDOWN_DAYS = 30  # a company still without people is researched again after this (or on new data)


def is_due(db: Session, company: Company, now: datetime | None = None) -> bool:
    """External research is useful (priority departments missing) and not done recently. A company with no people
    is retried only after its cooldown, or as soon as something it depends on changed: a public source document, a
    new alias. Never endlessly re-run on every open."""
    from app.models import CompanyAlias, ExternalDocument
    from app.services.people import gaps
    from app.services.people.orchestrator import brand_page

    if not get_settings().external_people_enabled or brand_page(company.website):
        return False
    if not set(persistence.PRIORITY_DEPARTMENTS) - planner.covered_departments(db, company.id):
        return False
    now = now or datetime.now(timezone.utc)
    last = company.deep_research_at or company.external_people_researched_at
    if last is None:
        return True
    if not gaps.credible_people(db, company.id):
        if company.next_research_eligible_at and now >= company.next_research_eligible_at:
            return True
        changed = db.scalar(select(func.max(ExternalDocument.updated_at)).where(
            ExternalDocument.metadata_["source"].astext.in_(pack.directory_sources(company))))
        alias = db.scalar(select(func.max(CompanyAlias.created_at)).where(CompanyAlias.company_id == company.id))
        return bool((changed and changed > last) or (alias and alias > last))
    return now - last > timedelta(days=get_settings().external_fresh_days)


def request(db: Session, company: Company, priority: int, *, force: bool = False, user_id: int | None = None) -> bool:
    running = company.external_people_status in (EnrichmentStatus.QUEUED, EnrichmentStatus.RESEARCHING)
    if running or not (force or is_due(db, company)):
        if company.external_people_status == EnrichmentStatus.QUEUED:
            db.execute(text("UPDATE research_runs SET priority = LEAST(priority, :p) WHERE company_id = :c AND "
                            "research_type = :k AND status = 'queued'"),
                       {"p": priority, "c": company.id, "k": jobs.EXTERNAL})
        return False
    stmt = insert(ResearchRun).values(company_id=company.id, research_type=jobs.EXTERNAL,
                                      status=ResearchRunStatus.QUEUED.value, priority=priority,
                                      requested_by_user_id=user_id, metadata_={"force": force, **jobs.chained()})
    db.execute(stmt.on_conflict_do_update(  # already queued or running: one active job, its priority raised
        index_elements=["company_id", "research_type"], index_where=text(jobs.ACTIVE),
        set_={"priority": func.least(ResearchRun.priority, priority)}))
    jobs.wake(db, jobs.EXTERNAL)
    if company.external_people_status != EnrichmentStatus.RESEARCHING:
        company.external_people_status = EnrichmentStatus.QUEUED.value
    return True


# ---- one company ------------------------------------------------------------------------------------------------------


def run(db: Session, company_id: int, *, force: bool = False, queue_wait: float | None = None,
        priority: int = 50) -> dict:
    started = time.perf_counter()
    stats: Counter = Counter()
    timings: dict = {"queue_wait": round(queue_wait, 2) if queue_wait is not None else None}
    company = db.get(Company, company_id)
    if company is None:
        return {"status": "skipped"}
    company.external_people_status, company.external_people_message = EnrichmentStatus.RESEARCHING.value, None
    db.commit()
    budget = Budget()
    from app.services.enrichment.orchestrator import OPENED

    # PEOPLE_SEARCH_PROVIDER for every research; the direct search's engine (SearXNG...) only when a person asked
    engine = search.provider() or (search.provider("company") if priority <= OPENED else None)
    plan = planner.plan(db, company, max_queries=budget.max_queries, quotes=getattr(engine, "supports_quotes", True))
    stats["missing_departments_at_start"] = len(plan.missing)
    country = find_country(company.headquarters_country)
    country_ctx = (country.code if country else None, country.name if country else company.headquarters_country)
    read: set[str] = set()
    problems: list[str] = []

    def process(docs: list[SourceDocument]) -> int:
        """Read the documents, store their people of this company; returns new credible roles."""
        before = _credible_roles(db, company.id)
        for d in docs:
            if budget.out_of_time():
                stats["stopped_deadline"] += 1
                break
            if budget.fetches >= budget.max_fetches or d.url in read:
                continue
            is_pdf = d.url.lower().split("?")[0].endswith(".pdf")
            if is_pdf and budget.pdfs >= budget.max_pdfs:
                continue
            read.add(d.url)
            budget.fetches += 1
            budget.pdfs += is_pdf
            t = time.perf_counter()
            try:
                document = documents.get(db, d.url, d.kind, published_hint=d.published, stats=stats,
                                         connector=d.origin)
            except Exception:  # one bad document never stops the research
                db.rollback()
                logger.exception("company=%s external document failed: %s", company.id, d.url)
                stats["documents_failed"] += 1
                continue
            stats["fetch_seconds"] += time.perf_counter() - t
            if document is None:
                continue
            stats[f"documents_{d.kind.category}"] += 1
            t = time.perf_counter()
            official = d.kind.category in ("company_page", "company_document")
            found = candidates(document, d.kind, company=company, aliases=plan.aliases, country=country_ctx,
                               official=official, stats=stats)
            stats["extraction_seconds"] += time.perf_counter() - t
            stats["candidates"] += len(found)
            now = datetime.now(timezone.utc)
            for c in found:
                c.company_id = company.id
                if c.company_match_confidence < MIN_COMPANY_MATCH:
                    stats["rejected_weak_company_match"] += 1
                    continue
                persistence.save(db, company, c, resolve(db, company.id, c), now)
            persistence.recompute(db, company)
            db.commit()  # people appear as each document is read
            if found and "first_person" not in timings:
                timings["first_person"] = round(time.perf_counter() - started, 2)
        return len(_credible_roles(db, company.id) - before)

    routed = pack.route(company, search_configured=engine is not None)
    stats["sources_routed"] = ",".join(routed)
    t = time.perf_counter()
    try:  # 1. the Lebanon source pack: local records, no request
        before = _credible_roles(db, company.id)
        pack.apply(db, company, [k for k in routed if k in pack.configs()], stats)
        if _credible_roles(db, company.id) - before and "first_person" not in timings:
            timings["first_person"] = round(time.perf_counter() - started, 2)
    except Exception:
        db.rollback()
        logger.exception("company=%s lebanon sources failed", company.id)
        problems.append("One public source could not be read.")
        stats["sources_failed"] += 1
    timings["lebanon_sources"] = round(time.perf_counter() - t, 2)
    connectors: list = [CompanyDocumentsConnector()]
    if "wikidata" in routed:
        connectors.append("wikidata")
    connectors.append("news")
    if "common_crawl" in routed:
        connectors.append("common_crawl")
    if engine is not None:
        connectors.append(WebSearchConnector(engine))
    for connector in connectors:
        if budget.out_of_time():  # the stage's deadline: what was found is kept, the rest waits for a later run
            stats["stopped_deadline"] += 1
            break
        if connector in ("wikidata", "common_crawl", "news"):
            t = time.perf_counter()
            try:
                if connector == "wikidata":
                    _wikidata(db, company, stats)
                elif connector == "news":
                    _news(db, company, plan, country_ctx, stats)
                elif stats.get("foreign_brand_domain"):
                    stats["common_crawl_skipped_foreign_brand"] += 1  # e.g. nespresso.com for a Beirut boutique
                elif set(persistence.PRIORITY_DEPARTMENTS) - planner.covered_departments(db, company.id):
                    _common_crawl(db, company, plan, country_ctx, stats, timings, started, budget)
                else:
                    stats["common_crawl_skipped_covered"] += 1
            except Exception:
                db.rollback()
                logger.exception("company=%s %s failed", company.id, connector)
                problems.append("One public source could not be read.")
                stats["sources_failed"] += 1
            timings[connector] = round(time.perf_counter() - t, 2)
            continue
        if isinstance(connector, WebSearchConnector):
            seen: set[str] = set()
            no_gain = failures = 0
            for query in plan.queries:
                missing = set(query.departments) - planner.covered_departments(db, company.id)
                if not missing:
                    stats["queries_skipped_covered"] += 1  # found meanwhile: early stop for this department
                    continue
                if budget.out_of_time() or budget.queries >= budget.max_queries or budget.fetches >= budget.max_fetches:
                    stats["stopped_budget"] += 1
                    break
                if no_gain >= NO_GAIN_STOP:
                    stats["stopped_no_new_evidence"] += 1
                    break
                try:
                    docs = connector.run_query(db, company, query, plan, budget, stats, seen)
                    failures = 0
                except search.SearchError as exc:
                    failures += 1
                    stats["search_errors"] += 1
                    if failures >= 2:
                        problems.append(f"The public search provider was unavailable ({exc}).")
                        break
                    continue
                gained = process(docs)
                no_gain = 0 if gained else no_gain + 1
        else:
            try:
                process(connector.documents(db, company, plan, budget))
            except Exception:
                db.rollback()
                logger.exception("company=%s connector %s failed", company.id, connector.key)
                problems.append("One public source could not be read.")
                stats["sources_failed"] += 1
    coverage = persistence.recompute(db, company)
    coverage = {k: v for k, v in coverage.items() if k != "foreign_brand_domain"}
    if stats.get("foreign_brand_domain"):
        coverage["foreign_brand_domain"] = True  # read by DNS intelligence: the brand's, not ours
    company.people_coverage = {**coverage, "external_sources_checked": len(read),
                               "last_external_research_at": datetime.now(timezone.utc).isoformat()}
    if stats.get("stopped_deadline"):
        company.external_people_status = EnrichmentStatus.TIMED_OUT.value
        company.external_people_message = jobs.TIMED_OUT_MESSAGE
    else:
        company.external_people_status = (EnrichmentStatus.PARTIAL if problems else EnrichmentStatus.COMPLETED).value
        company.external_people_message = " ".join(problems)[:300] or None
    company.external_people_researched_at = datetime.now(timezone.utc)
    completeness.update(db, company)
    _remember_attempt(db, company, routed, stats)
    db.commit()
    from app.services import contact_intelligence  # how to reach the people found

    if contact_intelligence.request(db, company, priority=5):
        db.commit()
    timings["total"] = round(time.perf_counter() - started, 2)
    result = {"status": company.external_people_status, "message": company.external_people_message,
              "timings": timings, "aliases": plan.aliases, "missing_at_start": plan.missing,
              "queries_planned": [q.text for q in plan.queries], "documents_checked": len(read),
              "coverage": {k: coverage.get(k) for k in ("found", "people", "website_people", "external_people",
                                                         "departments_missing")},
              **{k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()}}
    logger.info("company=%s external_people=%s %s", company.id, company.external_people_status, result)
    return result


_ATTEMPT_STATS = ("directory_roles", "company_facts", "wikidata_entity", "wikidata_roles", "foreign_brand_domain",
                  "news_articles_matched", "news_roles", "news_events", "commoncrawl_index_calls",
                  "commoncrawl_index_errors", "commoncrawl_captures_selected", "commoncrawl_roles", "commoncrawl_facts",
                  "documents_fetched", "candidates", "rejected_company_not_named", "rejected_weak_company_match",
                  "rejected_group_role", "rejected_ambiguous_name", "sources_failed", "stopped_deadline",
                  "commoncrawl_unavailable")


def _remember_attempt(db: Session, company: Company, routed: list[str], stats: Counter) -> None:
    """What this deep research tried and why it may have found no one (gap reasons), and when it may run again."""
    from app.services.people import gaps

    now = datetime.now(timezone.utc)
    company.deep_research_at = now
    company.sources_attempted = {"at": now.isoformat(), "sources": routed,
                                 "stats": {k: stats[k] for k in _ATTEMPT_STATS if stats.get(k)}}
    reasons = gaps.classify(db, company)
    company.next_research_eligible_at = now + timedelta(
        days=ZERO_PEOPLE_COOLDOWN_DAYS if reasons else get_settings().external_fresh_days)
    stats["gap_reasons"] = sorted({r for r, _, _ in reasons})


def _wikidata(db: Session, company: Company, stats: Counter) -> None:
    with pack.api_client() as http:
        found = wikidata.people(db, http, company, stats)
    now = datetime.now(timezone.utc)
    for c in found:
        persistence.save(db, company, c, resolve(db, company.id, c), now)
    stats["wikidata_roles"] += len(found)
    persistence.recompute(db, company)
    db.commit()


def _news(db: Session, company: Company, plan, country_ctx, stats: Counter) -> None:
    """Articles of the local news index whose URL names the company: people stated for it, dated events."""
    records = [r for key, cfg in pack.configs().items() if cfg.role == "news" and cfg.access == "automated"
               for _, rs in pack._loaded(db, key) for r in rs]
    articles = news.matching_articles(records, plan.aliases, datetime.now(timezone.utc))
    stats["news_articles_matched"] += len(articles)
    kind = Kind("publication", *CATEGORIES["publication"])
    now = datetime.now(timezone.utc)
    for article in articles:
        document = documents.get(db, article.excerpt, kind, published_hint=article.published, stats=stats,
                                 connector="news")
        if document is None:
            continue
        stats["news_articles_read"] += 1
        found = candidates(document, kind, company=company, aliases=plan.aliases, country=country_ctx,
                           official=False, stats=stats)
        for c in found:
            c.company_id = company.id
            if c.company_match_confidence >= MIN_COMPANY_MATCH:
                persistence.save(db, company, c, resolve(db, company.id, c), now)
                stats["news_roles"] += 1
        when = document.row.published_at or (published_date(article.published))
        for event_kind, statement in news.events(document.pages[0][1], plan.aliases):
            news.store_event(db, company, event_kind, statement, article.excerpt, document.source.id, when,
                             kind.quality)
            stats["news_events"] += 1
        persistence.recompute(db, company)
        db.commit()


def _archived_facts(db: Session, company: Company, doc, source, when: datetime, url: str) -> int:
    """Company facts of an archived operations page (sites, products, activities), through the website facts' store,
    observed at the capture date (an old page's address may no longer be current: evidence keeps its date)."""
    from app.services.enrichment import extract as company_extract
    from app.services.enrichment import persistence as company_store

    path = url.lower()
    page_type = ("manufacturing" if re.search(r"factor|plant|usine", path) else "locations" if re.search(
        r"location|branch|store|showroom|succursale", path) else "products" if "product" in path else
        "services" if "service" in path else "other")
    country = find_country(company.headquarters_country)
    ctx = company_extract.Context(company.name, country.code if country else None,
                                  country.name if country else company.headquarters_country, company.domain or "")
    facts = [f for f in company_extract.extract(doc, page_type, ctx) if f.kind in ("location", "signal", "offering")]
    for f in facts:
        f.confidence = min(f.confidence, 70)  # archived: weaker than the live site
    if facts:
        company_store.save_facts(db, company, source, [f for f in facts if f.kind != "offering"], when,
                                 company.headquarters_country or "Lebanon")
        for f in facts:
            if f.kind == "offering":
                company_store.evidence(db, source, company, f, when)
                company_store.offering(db, company, f, source)
        db.commit()
    return len(facts)


def _common_crawl(db: Session, company: Company, plan, country_ctx, stats: Counter, timings: dict,
                  started: float, budget: Budget | None = None) -> None:
    """The company's own past people pages from the public web archive; stops once departments are covered, at
    its own time budget (COMMONCRAWL_BUDGET_SECONDS) or the stage's deadline, and at once while the archive is
    known to be down (commoncrawl.available)."""
    s = get_settings()
    kind = Kind("web_archive", *CATEGORIES["web_archive"])
    deadline = time.monotonic() + min(s.commoncrawl_budget_seconds,
                                      budget.seconds_left() if budget else s.commoncrawl_budget_seconds)
    if not commoncrawl.available():
        stats["commoncrawl_unavailable"] += 1  # failed moments ago for another company: not waited on again
        return
    with pack.api_client() as http:
        rows: list[dict] = []
        for crawl in commoncrawl.crawls(db, http, deadline):  # newest first; earlier crawls only while nothing useful
            if time.monotonic() > deadline or not commoncrawl.available():
                stats["commoncrawl_stopped_budget"] += 1
                break
            rows += commoncrawl.captures(db, http, crawl, company.domain, stats, company.id, deadline)
            if sum(1 for r in rows if commoncrawl._rank(r.get("url", "")) in (0, 1, 2)) >= s.commoncrawl_max_captures:
                break
            if stats.get("commoncrawl_index_errors", 0) >= 6:
                break  # the index is failing now: stop, retried on a later run (recorded per lookup)
        chosen = commoncrawl.select_captures(db, company, rows, s.commoncrawl_max_captures)
        stats["commoncrawl_captures_found"] += len(rows)
        stats["commoncrawl_captures_selected"] += len(chosen)
        for capture in chosen:
            if time.monotonic() > deadline:
                stats["commoncrawl_stopped_budget"] += 1
                break
            if capture.get("rank") != 3 and not set(persistence.PRIORITY_DEPARTMENTS) - \
                    planner.covered_departments(db, company.id):
                stats["commoncrawl_stopped_covered"] += 1
                continue
            got = commoncrawl.document(db, http, capture, stats)
            if got is None:
                continue
            row, source, doc = got
            when = commoncrawl.captured_at(capture["timestamp"])
            if capture.get("rank") == 3:  # an operations page: company facts (sites, products), dated by the capture
                stats["commoncrawl_facts"] += _archived_facts(db, company, doc, source, when, capture["url"])
                continue
            document = documents.Document(row, [(None, doc)], source, True)
            found = candidates(document, kind, company=company, aliases=plan.aliases, country=country_ctx,
                               official=True, stats=stats)
            now = datetime.now(timezone.utc)
            for c in found:
                c.company_id, c.observed_at = company.id, when
                c.raw_metadata["captured_at"] = when.date().isoformat()
                if c.status == "current" and now - when > timedelta(days=commoncrawl.CURRENT_DAYS):
                    c.status = "unknown"  # an old capture is history: not proof of today's team
                persistence.save(db, company, c, resolve(db, company.id, c), now)
            stats["commoncrawl_roles"] += len(found)
            persistence.recompute(db, company)
            db.commit()
            if found and "first_person" not in timings:
                timings["first_person"] = round(time.perf_counter() - started, 2)


def _credible_roles(db: Session, company_id: int) -> set[tuple]:
    from app.models import CompanyPerson

    return set(db.execute(select(CompanyPerson.person_id, CompanyPerson.normalized_title, CompanyPerson.job_title)
                          .where(CompanyPerson.company_id == company_id, CompanyPerson.confidence >= 50,
                                 CompanyPerson.employment_status != "former")).all())
