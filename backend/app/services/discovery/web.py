"""Polite, safe web access for discovery: every request LeadFinder makes to a company website goes here.

* SSRF-safe transport, byte caps, bounded redirects (fetch.py).
* Identifies itself (fetch.USER_AGENT) and honours robots.txt for that agent (cached per host).
* At most one request per host every `min_interval` seconds (per process), or the robots.txt Crawl-delay
  when that is longer (capped at MAX_CRAWL_DELAY).
* One retry with backoff on timeouts / connection errors; HTTP errors are not retried.
* A host whose robots.txt times out / refuses the connection / has no DNS is unreachable: its pages are not tried too.
* Results are cached (`ttl`, at most MAX_CACHED pages), so a repeated search does not re-fetch a site.
"""

import threading
import time
import urllib.robotparser
from urllib.parse import urlsplit

from app.services.discovery.fetch import USER_AGENT, Fetcher, FetchError, Page

_RETRYABLE = {"TIMEOUT", "CONNECT"}
_UNREACHABLE = _RETRYABLE | {"DNS"}
MAX_CACHED = 2000
MAX_CRAWL_DELAY = 10.0


class PoliteFetcher:
    def __init__(self, fetcher: Fetcher, *, min_interval: float = 2.0, retries: int = 1, backoff: float = 2.0,
                 ttl: float = 24 * 3600):
        self.fetcher = fetcher
        self.min_interval, self.retries, self.backoff, self.ttl = min_interval, retries, backoff, ttl
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}
        self._delay: dict[str, float] = {}  # robots.txt Crawl-delay per host
        # None: no robots.txt (allowed); FetchError: the host did not answer at all.
        self._robots: dict[str, urllib.robotparser.RobotFileParser | FetchError | None] = {}
        self._cache: dict[str, tuple[float, Page | FetchError]] = {}

    def _wait_for_slot(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + max(self.min_interval, self._delay.get(host, 0.0))
        if slot > now:
            time.sleep(slot - now)

    def _get(self, url: str) -> Page:
        host = urlsplit(url).hostname or ""
        for attempt in range(self.retries + 1):
            self._wait_for_slot(host)
            try:
                return self.fetcher.get(url)
            except FetchError as exc:
                if exc.kind not in _RETRYABLE or attempt == self.retries:
                    raise
                time.sleep(self.backoff * (attempt + 1))
        raise AssertionError("unreachable")

    def allowed(self, url: str) -> bool:
        """robots.txt for LeadFinder's user agent. No robots.txt (404 / unreachable) = allowed;
        401/403 on robots.txt = the site disallows crawlers."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            try:
                page = self._get(f"{origin}/robots.txt")
                if page.status in (401, 403):
                    parser.disallow_all = True
                elif page.status >= 400:
                    parser = None
                else:
                    parser.parse(page.html.splitlines())
                    if delay := parser.crawl_delay(USER_AGENT):
                        self._delay[parts.hostname or ""] = min(float(delay), MAX_CRAWL_DELAY)
            except FetchError as exc:
                parser = exc if exc.kind in _UNREACHABLE else None
            self._robots[origin] = parser
        parser = self._robots[origin]
        if isinstance(parser, FetchError):
            raise parser
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> Page:
        cached = self._cache.get(url)
        if cached and time.monotonic() - cached[0] < self.ttl:
            if isinstance(cached[1], FetchError):
                raise cached[1]
            return cached[1]
        if len(self._cache) > MAX_CACHED:
            self._cache.clear()
        try:
            if not self.allowed(url):
                raise FetchError("ROBOTS", "the site's robots.txt does not allow LeadFinder")
            page = self._get(url)
        except FetchError as exc:
            self._cache[url] = (time.monotonic(), exc)
            raise
        self._cache[url] = (time.monotonic(), page)
        return page
