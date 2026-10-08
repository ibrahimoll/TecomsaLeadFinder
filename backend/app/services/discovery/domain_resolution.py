"""Company website and domain resolution, offline (discovery).

resolve_website(url) normalizes what a source published ('www.ABCFoods.com.lb/about' -> website
'https://www.ABCFoods.com.lb/about', claimed domain 'abcfoods.com.lb') and separates social / link pages
(Facebook, Instagram, LinkedIn, Linktree, maps...) from company websites. A claimed domain is used for
matching, never stored as fact: companies.domain is only set once company research (services/enrichment)
has fetched the site and confirmed it is the company's own.
"""

import re
from dataclasses import dataclass, field

from app.services.normalization import company_domain, normalize_domain, normalize_website

_SOCIAL = {"facebook.com": "facebook_url", "fb.com": "facebook_url", "fb.me": "facebook_url",
           "instagram.com": "instagram_url", "linkedin.com": "linkedin_url"}
_PARKED = re.compile(r"domain (is )?for sale|buy this domain|parked (free|domain)|this domain (name )?(has expired|"
                     r"is parked)|godaddy|sedo|hugedomains|website coming soon|under construction", re.IGNORECASE)


@dataclass
class ResolvedWebsite:
    website: str | None = None  # the company's own website (normalized, with scheme)
    domain: str | None = None  # claimed (from the source), NOT verified
    social: dict[str, str] = field(default_factory=dict)  # e.g. {"facebook_url": "https://facebook.com/abc"}


def resolve_website(url: str | None) -> ResolvedWebsite:
    url = normalize_website(url)
    if not url or not re.match(r"^https?://[^\s/]+\.[^\s]+$", url, re.IGNORECASE):
        return ResolvedWebsite()
    host = normalize_domain(url)
    if host is None:
        return ResolvedWebsite()
    social = next((column for social_host, column in _SOCIAL.items()
                   if host == social_host or host.endswith("." + social_host)), None)
    if social:
        return ResolvedWebsite(social={social: url})
    domain = company_domain(url)
    return ResolvedWebsite(website=url, domain=domain) if domain else ResolvedWebsite()
