"""Provider-neutral public-web discovery.

Business logic never talks to a search engine directly: a WebSearchProvider (any engine with an
official API, used within its terms) returns plain results, and this connector turns them into
low-tier CompanyCandidates that go through the same normalization / deduplication as every other
source. Web results only say "a page with this title exists": they are never trusted for industry or
location on their own (tier "name", lowest source quality).

No provider is configured in this release: scraping search-result pages is not an option, and an
engine API needs a key and terms review first. Register one in PROVIDERS when that is done.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.services.discovery.candidate import CompanyCandidate, ConnectorConfig, ConnectorError, ConnectorResult, SearchQuery
from app.services.normalization import company_domain


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str = ""


class WebSearchProvider(Protocol):
    def search(self, query: str, limit: int) -> list[WebResult]: ...


PROVIDERS: dict[str, Callable[[ConnectorConfig], WebSearchProvider]] = {}

# "ABC Foods | Home", "ABC Foods - Official Website", "Welcome to ABC Foods"
_TITLE_NOISE = re.compile(r"\s*[|\-–—:]\s*(home|homepage|official (web)?site|welcome|accueil).*$|^welcome to\s+",
                          re.IGNORECASE)


def company_name_from_title(title: str) -> str:
    name = _TITLE_NOISE.sub("", title.strip())
    return re.split(r"\s+[|–—]\s+", name)[0].strip()


class PublicWebConnector:
    def __init__(self, config: ConnectorConfig, provider: WebSearchProvider | None = None):
        self.config = config
        factory = PROVIDERS.get(config.options.get("provider", ""))
        self.provider = provider or (factory(config) if factory else None)

    def search_companies(self, query: SearchQuery) -> ConnectorResult:
        if self.provider is None:
            raise ConnectorError("No public-web search provider is configured.")
        place = query.area.label if query.area else query.country.name
        text = f"{query.industry.label} company {place} {query.country.name}"
        candidates = []
        results = self.provider.search(text, min(query.limit, 50))
        for result in results:
            domain = company_domain(result.url)
            if domain is None:  # social / maps / link pages are not company websites
                continue
            candidates.append(CompanyCandidate(
                connector=self.config.key,
                source_name=self.config.label or "Public web search",
                source_type=self.config.source_type,
                external_id=domain,
                source_url=result.url,
                company_name=company_name_from_title(result.title),
                website=result.url,
                country=query.country.name,
                description=result.snippet[:500] or None,
                tier="name",
                match_reason="Public web result for the search terms",
                raw_metadata={"title": result.title, "url": result.url, "snippet": result.snippet[:500]},
            ))
        return ConnectorResult(candidates=candidates, version=None, scanned=len(results))
