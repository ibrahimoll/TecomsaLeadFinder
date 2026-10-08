"""Web discovery for direct company search (Step 5.4.1): finding the official website of a company no source
LeadFinder holds names, then verifying from the website itself that it IS that company.

    WebDiscoveryProvider     provider-neutral: search_company(name, country, city, industry, limit) -> candidate URLs
      DomainGuessDiscovery   ENABLED, $0: the domains a company with that name would use in that country
                             ('ABC Foods', Lebanon -> abcfoods.com.lb, abcfoods.com, abc-foods.com...), kept only when
                             they resolve in DNS. No search engine is involved.
      LicensedSearchDiscovery  the configured public web search API (services/people/external/search.py), OFF unless a
                             licensed provider is configured and approved; bounded query variants (expand)
    verify(name, url)        the site's own evidence: its name (title, og:site_name, structured data, headings,
                             footer), the country (TLD, +961 phone, Lebanese address / city words), and what it is NOT
                             (a parked / for-sale / default / demo page, a directory). A discovery result is never a
                             fact: only a verified site creates a company, and only with what it states.
    Breaker                  a failing source / provider is skipped for a while, for every lookup

A domain is never trusted because its spelling resembles the company: the site must name the company AND be in the
searched country (or the queried TLD's country). Same name abroad: rejected (FOREIGN_ENTITY).
"""

import html as html_lib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

from app.services.discovery.geography import AREAS, _fold
from app.services.normalization import company_domain

LEBANON_PHONE = re.compile(r"(?:\+|00)\s?961[\s\-/().]*\d(?:[\s\-/().]*\d){5,8}"
                           r"|\b0[1-9][\s\-/]?\d{3}[\s\-]?\d{3}\b|\(0[1-9]\)\s?\d{3}[\s\-]?\d{3}")
FOREIGN_PHONE = re.compile(r"(?:\+|00)\s?(?:1|44|33|49|971|966|974|965|962|20|90|39|34|61)[\s\-/().]*\d{2}")
PARKED = re.compile(r"domain (?:name )?(?:is )?for sale|buy this domain|this domain (?:may be|is) for sale|"
                    r"parked (?:free|domain)|domain parking|sedo|hugedomains|dan\.com|godaddy\.com/domainsearch|"
                    r"default web site page|it works!|index of /|welcome to nginx|apache2 (?:ubuntu|debian) default|"
                    r"account suspended|website is under construction|lorem ipsum dolor", re.IGNORECASE)
DIRECTORY = re.compile(r"\b(?:business directory|company directory|yellow pages|listings? of companies|"
                       r"find (?:a|any) (?:business|company)|browse (?:all )?(?:companies|categories))\b", re.IGNORECASE)
COUNTRY_WORDS = {"Lebanon": ("lebanon", "liban", "لبنان", "beirut", "beyrouth", "بيروت")}
TLDS = {"lb": "Lebanon", "ae": "United Arab Emirates", "sa": "Saudi Arabia", "qa": "Qatar", "kw": "Kuwait",
        "jo": "Jordan", "eg": "Egypt", "iq": "Iraq", "cy": "Cyprus", "fr": "France", "om": "Oman", "bh": "Bahrain"}
MAX_DOMAINS = 12  # DNS-checked only; a site is fetched for the few that resolve


@dataclass
class DiscoveryCandidate:
    url: str
    domain: str
    source: str  # provider key
    rank: int
    title: str = ""
    snippet: str = ""  # a hint only, never a fact
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class WebDiscoveryProvider(Protocol):
    key: str

    def search_company(self, name: str, *, country: str | None = None, city: str | None = None,
                       industry: str | None = None, limit: int = 5) -> list[DiscoveryCandidate]: ...


# ---- circuit breaker --------------------------------------------------------------------------------------------


class Breaker:
    """After `failures` consecutive failures a source is skipped for `cooldown` seconds (every lookup, this process)."""

    _lock = threading.Lock()
    _state: dict[str, tuple[int, float]] = {}  # key -> (consecutive failures, open until)

    def __init__(self, key: str, failures: int = 3, cooldown: float = 300):
        self.key, self.failures, self.cooldown = key, failures, cooldown

    def open(self) -> bool:
        with Breaker._lock:
            return time.monotonic() < Breaker._state.get(self.key, (0, 0.0))[1]

    def record(self, ok: bool) -> None:
        with Breaker._lock:
            count, until = Breaker._state.get(self.key, (0, 0.0))
            count = 0 if ok else count + 1
            Breaker._state[self.key] = (count, time.monotonic() + self.cooldown if count >= self.failures else until)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._state.clear()


# ---- providers ------------------------------------------------------------------------------------------------------


def _slugs(name: str) -> list[str]:
    """Domain labels a company with this name could use: 'ABC Foods SAL' -> abcfoods, abc-foods, abc."""
    from app.services.people.external.lebanon.records import _LEGAL

    words = [w for w in re.findall(r"[a-z0-9]+", _fold(name)) if w not in _LEGAL]
    if not words:
        return []
    slugs = ["".join(words)]
    if len(words) > 1 and len(words[0]) >= 4:
        slugs.append(words[0])  # 'Formatech Training' -> formatech
    slugs.append("-".join(words))
    initials = "".join(w[0] for w in words if w not in ("of", "and", "for", "the", "de", "du", "des", "et"))
    if len(initials) >= 3 and len(words) >= 3:
        slugs.append(initials)  # 'Lebanese American University' -> lau
    return [s for s in dict.fromkeys(slugs) if 3 <= len(s) <= 40]


def candidate_domains(name: str, country: str | None) -> list[str]:
    """Bounded: the country's own TLDs first ('.com.lb', '.lb'), then the generic ones."""
    tld = next((t for t, c in TLDS.items() if c == country), None)
    endings = ([f"com.{tld}", tld] if tld else []) + ["com", "net"] + (["org"] if tld else [])
    if tld == "lb":
        endings.insert(2, "com")
        endings = list(dict.fromkeys(endings))
    out = []
    for ending in endings:  # the likeliest endings first, for every spelling
        for slug in _slugs(name):
            out.append(f"{slug}.{ending}")
    if tld:
        out += [f"{slug}-{tld}.com" for slug in _slugs(name)[:1]]  # 'abc-lb.com', common in Lebanon
    return list(dict.fromkeys(out))[:MAX_DOMAINS]


class DomainGuessDiscovery:
    key = "domain_guess"

    def search_company(self, name: str, *, country: str | None = None, city: str | None = None,
                       industry: str | None = None, limit: int = 5) -> list[DiscoveryCandidate]:
        from app.services.discovery import fetch

        def resolves(domain: str) -> bool:
            try:
                return any(fetch.is_public(a) for a in fetch.resolve(domain))
            except Exception:  # does not resolve: not a candidate
                return False

        domains = candidate_domains(name, country)
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="dns") as pool:  # in parallel, order kept
            alive = list(pool.map(resolves, domains))
        return [DiscoveryCandidate(url=f"https://{d}/", domain=d, source=self.key, rank=rank)
                for rank, (d, ok) in enumerate(zip(domains, alive)) if ok][:limit]


def expand(name: str, *, country: str | None = None, city: str | None = None, industry: str | None = None,
           limit: int = 4) -> list[str]:
    """Bounded search variants of the user's own words (never invented names)."""
    quoted = f'"{name}"'
    variants = [f"{quoted} {city}" if city else None, f"{quoted} {country}" if country else None,
                f"{quoted} {industry.lower()}" if industry else None, f"{quoted} official website", quoted]
    return [v for v in dict.fromkeys(v for v in variants if v)][:limit]


class LicensedSearchDiscovery:
    """The configured public web search API, when one is licensed and configured (never a result page)."""

    key = "licensed_search"

    def __init__(self, engine):
        self.engine = engine

    def search_company(self, name: str, *, country: str | None = None, city: str | None = None,
                       industry: str | None = None, limit: int = 5) -> list[DiscoveryCandidate]:
        from app.services.people.external.sources import blocked

        out: dict[str, DiscoveryCandidate] = {}
        for variant in expand(name, country=country, city=city, industry=industry, limit=2):
            for rank, r in enumerate(self.engine.search(variant, limit=limit)):
                domain = company_domain(r.url)
                if domain and not blocked(r.url) and domain not in out:
                    out[domain] = DiscoveryCandidate(url=f"https://{urlsplit(r.url).hostname}/", domain=domain,
                                                     source=self.key, rank=rank, title=r.title, snippet=r.snippet)
        return list(out.values())[:limit]


def providers() -> list[WebDiscoveryProvider]:
    from app.services.people.external import search

    out: list[WebDiscoveryProvider] = [DomainGuessDiscovery()]
    if (engine := search.provider()) is not None:
        out.append(LicensedSearchDiscovery(engine))
    return out


# ---- verification ---------------------------------------------------------------------------------------------------


@dataclass
class Verification:
    status: str  # strong / possible / rejected
    domain: str
    url: str
    reason: str
    site_name: str | None = None
    country: str | None = None
    phone: str | None = None
    city: str | None = None


def _site_names(doc) -> list[str]:
    names = [doc.meta.get("og:site_name"), doc.meta.get("application-name")]
    names += [i.get("name") for i in doc.jsonld if isinstance(i.get("name"), str)
              and str(i.get("@type", "")).lower() in ("organization", "corporation", "localbusiness", "hotel",
                                                       "restaurant", "store", "website", "")]
    for part in re.split(r"\s+[|\-–—:·»]\s+", doc.title or ""):
        names.append(part)
    names += doc.headings("1")[:2]
    return [n.strip() for n in names if n and 2 <= len(n.strip()) <= 120]


_DESCRIPTIVE = {"boutique", "hotel", "hotels", "resort", "restaurant", "cafe", "group", "company", "co", "sal", "sarl",
                "lebanon", "liban", "international", "industries", "industry", "trading", "services", "solutions",
                "consulting", "training", "official", "website", "home", "lebanese", "beirut"}


def _names_company(site_name: str, name: str) -> bool:
    """The site's name is the company's: the same name keys, or the company's words followed only by descriptive
    words ('Aleph Boutique Hotel' for 'Aleph'). Another word makes it another company ('Aleph Dental')."""
    from app.services.company_search import name_keys
    from app.services.query_understanding import INDUSTRY_WORDS

    wanted = {k for k in name_keys(name) if k[0] not in "~^"}
    if {k for k in name_keys(site_name) if k[0] not in "~^"} & wanted:
        return True
    words, site = _fold(name).split(), _fold(site_name).split()
    rest = site[len(words):]
    return bool(words) and site[:len(words)] == words and bool(rest) and all(
        w in _DESCRIPTIVE or w in INDUSTRY_WORDS for w in rest)


def verify(name: str, url: str, *, country: str | None, fetcher=None) -> Verification:
    """Is this website the company named `name`, in `country`? Only the site's own evidence counts."""
    from app.services.enrichment import orchestrator as enrichment
    from app.services.enrichment.pages import parse

    domain = company_domain(url) or ""
    page = (fetcher or enrichment.website_fetcher()).get(url)
    final = company_domain(page.url) or domain
    if (page.status or 0) >= 400 or not page.html:
        return Verification("rejected", domain, url, f"HTTP {page.status}")
    doc = parse(page.html, page.url)
    # every visible word, loose footer text included (the parsed blocks keep paragraphs and headings only)
    visible = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page.html)
    text = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", visible)).split())[:300_000]
    if PARKED.search(text) or len(text) < 120:
        return Verification("rejected", final, page.url, "PARKED_OR_EMPTY")
    if DIRECTORY.search(" ".join([doc.title or "", *doc.headings("12")])):
        return Verification("rejected", final, page.url, "DIRECTORY")
    named = next((n for n in _site_names(doc) if _names_company(n, name)), None)
    if named is None:  # the name in the copyright line ('© 2025 ABC Foods SAL')
        named = next((m.strip(" ·-") for m in re.findall(r"(?:©|copyright)\s*(?:\d{4}\s*)?([^.|·\n]{2,80})", text,
                                                          re.IGNORECASE) if _names_company(m.strip(" ·-"), name)),
                     None)
    tld_country = TLDS.get(final.rsplit(".", 1)[-1])
    words = COUNTRY_WORDS.get(country or "", ())
    folded = _fold(text)
    cities = [a.label for a in AREAS.get("LB", {}).values() if a.kind == "city" and any(
        re.search(rf"\b{re.escape(k)}\b", folded) for k in a.keys)] if country == "Lebanon" else []
    phone = (LEBANON_PHONE.search(text) if country == "Lebanon" else None)
    in_country = bool(tld_country == country or (country and (phone or cities or any(
        re.search(rf"\b{re.escape(_fold(w))}\b", folded) for w in words))))
    foreign = bool(tld_country and country and tld_country != country) or (
        not in_country and FOREIGN_PHONE.search(text) is not None)
    if named is None:
        return Verification("rejected", final, page.url, "NAME_NOT_ON_SITE")
    if foreign and not in_country:
        return Verification("rejected", final, page.url, "FOREIGN_ENTITY", named, tld_country)
    status = "strong" if in_country or (country is None) else "possible"
    return Verification(status, final, page.url, "NAME_AND_COUNTRY" if in_country else "NAME_ONLY", named,
                        country if in_country else None, phone.group(0).strip() if phone else None,
                        cities[0] if cities else None)
