"""Public web search, provider-neutral. A provider only LOCATES public pages: LeadFinder fetches each page itself,
reads the statement from the page and stores the page as the source. A search snippet is never a fact.

OPTIONAL and OFF by default: LeadFinder's people research needs no search API (the Lebanon source pack, Common Crawl
and Wikidata are free). Providers use a permitted API (never a search engine's result pages). PEOPLE_SEARCH_PROVIDER:

    none    (default) no web search
    brave   Brave Search API (paid; https://api.search.brave.com), key in BRAVE_SEARCH_API_KEY
    tavily  Tavily Search API (1,000 free searches a month, no card; https://tavily.com), key in TAVILY_API_KEY
    langsearch  LangSearch Web Search API (free plan: a daily allowance, $0; https://langsearch.com; reachable from
            Lebanon), key in LANGSEARCH_API_KEY

COMPANY_SEARCH_PROVIDER (default auto: the first key set of langsearch, tavily, brave) is the one Find Leads' direct company search uses; people research keeps
PEOPLE_SEARCH_PROVIDER (default none), so background research never spends the free monthly searches.

Results are cached (external_search_cache) for SEARCH_CACHE_DAYS: the same query is not sent twice. The same table
caches other public APIs' answers by provider (cached_json: Common Crawl index, Wikidata).
"""

import hashlib
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ExternalSearchCache

logger = logging.getLogger("leadfinder.people.search")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str  # a hint for filtering only
    domain: str
    published: str | None = None  # ISO date when the provider knows it


class SearchError(Exception):
    """The provider could not answer (timeout, quota, outage): the research goes on without it."""


class PublicWebSearchProvider(Protocol):
    key: str
    supports_quotes: bool  # "exact phrase"; no provider is assumed to support OR

    def search(self, query: str, *, limit: int, country: str | None = None,
               language: str | None = None) -> list[SearchResult]: ...


_TAGS = re.compile(r"<[^>]+>")


class BraveSearchProvider:
    key = "brave"
    supports_quotes = True
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
    _lock = threading.Lock()
    _next_call = 0.0

    def __init__(self, api_key: str, *, timeout: float, min_interval: float,
                 transport: httpx.BaseTransport | None = None):
        self._api_key, self.timeout, self.min_interval, self.transport = api_key, timeout, min_interval, transport

    def _pace(self) -> None:
        """The plan's rate limit, across every thread of this process."""
        with BraveSearchProvider._lock:
            now = time.monotonic()
            wait = BraveSearchProvider._next_call - now
            BraveSearchProvider._next_call = max(now, BraveSearchProvider._next_call) + self.min_interval
        if wait > 0:
            time.sleep(wait)

    def search(self, query: str, *, limit: int, country: str | None = None,
               language: str | None = None) -> list[SearchResult]:
        self._pace()
        params = {"q": query, "count": min(limit, 20), "safesearch": "moderate"}
        if language:
            params["search_lang"] = language
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.get(self.ENDPOINT, params=params, headers={
                    "Accept": "application/json", "X-Subscription-Token": self._api_key})
        except httpx.HTTPError as exc:
            raise SearchError(f"search provider unreachable ({exc.__class__.__name__})") from None
        if response.status_code != 200:  # 401 bad key, 422 bad query, 429 quota: never logs the key
            raise SearchError(f"search provider answered HTTP {response.status_code}")
        results = []
        for item in ((response.json().get("web") or {}).get("results") or [])[:limit]:
            url = item.get("url") or ""
            if not url.startswith(("http://", "https://")):
                continue
            results.append(SearchResult(
                title=_TAGS.sub("", item.get("title") or "")[:300], url=url,
                snippet=_TAGS.sub("", item.get("description") or "")[:500],
                domain=(urlsplit(url).hostname or "").lower(), published=item.get("page_age") or None))
        return results


class TavilySearchProvider:
    key = "tavily"
    supports_quotes = True
    ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str, *, timeout: float, transport: httpx.BaseTransport | None = None):
        self._api_key, self.timeout, self.transport = api_key, timeout, transport

    def search(self, query: str, *, limit: int, country: str | None = None,
               language: str | None = None) -> list[SearchResult]:
        body = {"query": query, "max_results": min(limit, 20), "search_depth": "basic"}  # basic = 1 credit
        if country:
            body.update(topic="general", country=country.lower())  # boosts that country's pages
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(self.ENDPOINT, json=body, headers={"Authorization": f"Bearer {self._api_key}"})
        except httpx.HTTPError as exc:
            raise SearchError(f"search provider unreachable ({exc.__class__.__name__})") from None
        if response.status_code != 200:  # 401 bad key, 432/433 monthly credits used up: never logs the key
            raise SearchError(f"search provider answered HTTP {response.status_code}")
        results = []
        for item in (response.json().get("results") or [])[:limit]:
            url = item.get("url") or ""
            if url.startswith(("http://", "https://")):
                results.append(SearchResult(
                    title=_TAGS.sub("", item.get("title") or "")[:300], url=url,
                    snippet=_TAGS.sub("", item.get("content") or "")[:500],
                    domain=(urlsplit(url).hostname or "").lower(), published=item.get("published_date") or None))
        return results


class LangSearchProvider:
    key = "langsearch"
    supports_quotes = True
    ENDPOINT = "https://api.langsearch.com/v1/web-search"

    def __init__(self, api_key: str, *, timeout: float, transport: httpx.BaseTransport | None = None):
        self._api_key, self.timeout, self.transport = api_key, timeout, transport

    def search(self, query: str, *, limit: int, country: str | None = None,
               language: str | None = None) -> list[SearchResult]:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(self.ENDPOINT, json={"query": query, "count": min(limit, 10)},
                                       headers={"Authorization": f"Bearer {self._api_key}"})
        except httpx.HTTPError as exc:
            raise SearchError(f"search provider unreachable ({exc.__class__.__name__})") from None
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code != 200 or str(body.get("code", 200)) != "200":  # missing / bad key, daily allowance
            raise SearchError(f"search provider answered HTTP {response.status_code} / {body.get('code')}")
        results = []
        for item in (((body.get("data") or {}).get("webPages") or {}).get("value") or [])[:limit]:
            url = item.get("url") or ""
            if url.startswith(("http://", "https://")):
                results.append(SearchResult(
                    title=_TAGS.sub("", item.get("name") or "")[:300], url=url,
                    snippet=_TAGS.sub("", item.get("snippet") or "")[:500],
                    domain=(urlsplit(url).hostname or "").lower(), published=item.get("datePublished") or None))
        return results


def provider(purpose: str = "people") -> PublicWebSearchProvider | None:
    """The provider configured for people research (PEOPLE_SEARCH_PROVIDER) or for the direct company search
    (purpose="company": COMPANY_SEARCH_PROVIDER), or None (no search)."""
    s = get_settings()
    secrets = {"langsearch": s.langsearch_api_key, "tavily": s.tavily_api_key, "brave": s.brave_search_api_key}
    keys = {n: v.get_secret_value().strip() for n, v in secrets.items() if v and v.get_secret_value().strip()}
    name = s.company_search_provider if purpose == "company" else s.people_search_provider
    if name == "auto":
        name = next(iter(keys), "none")
    key = keys.get(name)
    if not key:
        return None
    if name == "brave":
        return BraveSearchProvider(key, timeout=s.search_timeout_seconds, min_interval=s.search_min_interval_seconds)
    if name == "langsearch":
        return LangSearchProvider(key, timeout=s.search_timeout_seconds)
    return TavilySearchProvider(key, timeout=s.search_timeout_seconds)


def cached_search(db: Session, engine: PublicWebSearchProvider, query: str, *, limit: int,
                  language: str | None = None, country: str | None = None) -> tuple[list[SearchResult], bool]:
    """(results, from cache). A fresh cached answer is reused; a failure raises SearchError."""
    digest = hashlib.sha256(f"{query}|{limit}|{language}{'|' + country if country else ''}".encode()).hexdigest()
    row = db.scalar(select(ExternalSearchCache).where(ExternalSearchCache.provider == engine.key,
                                                      ExternalSearchCache.query_hash == digest))
    fresh_after = datetime.now(timezone.utc) - timedelta(days=get_settings().search_cache_days)
    if row is not None and row.created_at > fresh_after:
        return [SearchResult(**r) for r in row.results], True
    results = engine.search(query, limit=limit, language=language, **({"country": country} if country else {}))
    stmt = insert(ExternalSearchCache).values(provider=engine.key, query=query[:500], query_hash=digest,
                                              results=[asdict(r) for r in results])
    db.execute(stmt.on_conflict_do_update(constraint="uq_external_search_cache_query",
                                          set_={"results": stmt.excluded.results,
                                                "created_at": datetime.now(timezone.utc)}))
    db.commit()
    return results, False


def cached_json(db: Session, provider: str, key: str, days: float, fetch) -> tuple[Any, bool]:
    """(value, from cache): a public API's answer kept `days` (Common Crawl index, Wikidata), so the same question
    is never asked twice. `fetch()` raises on failure (nothing cached)."""
    digest = hashlib.sha256(key.encode()).hexdigest()
    row = db.scalar(select(ExternalSearchCache).where(ExternalSearchCache.provider == provider,
                                                      ExternalSearchCache.query_hash == digest))
    if row is not None and row.created_at > datetime.now(timezone.utc) - timedelta(days=days):
        return row.results[0], True
    value = fetch()
    stmt = insert(ExternalSearchCache).values(provider=provider, query=key[:500], query_hash=digest, results=[value])
    db.execute(stmt.on_conflict_do_update(constraint="uq_external_search_cache_query",
                                          set_={"results": stmt.excluded.results,
                                                "created_at": datetime.now(timezone.utc)}))
    db.commit()
    return value, False
