"""What a found URL is, how much it is trusted, and whether LeadFinder may fetch it at all.

Never fetched: LinkedIn and other social networks (a profile URL may be kept as a reference, never visited),
job boards, people-data vendors (Apollo, Lusha, ZoomInfo, RocketReach...: their data is not LeadFinder's
evidence), search engines' own pages, login / share pages and file types without text.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.services.normalization import company_domain

# category: (tier, quality for "this person holds this role at this company", Source.source_type)
CATEGORIES = {
    "company_page": ("A", 92, "company_website"),  # the company's own site (pages Step 4 did not read)
    "company_document": ("A", 90, "public_pdf"),  # a PDF on the company's own site (annual report, brochure)
    "regulatory": ("A", 88, "government"),
    "conference": ("B", 82, "conference"),  # speaker / panelist pages, programmes
    "association": ("B", 80, "association"),  # boards, committees, chambers
    "case_study": ("B", 78, "case_study"),  # vendor / partner customer stories
    "publication": ("C", 74, "news"),  # business news, interviews, industry press
    "public_document": ("C", 72, "public_pdf"),  # other public PDFs / presentations
    "other": ("C", 62, "public_web"),
    "directory": ("D", 45, "public_directory"),  # alone never makes a credible current employee
    # Lebanon source pack / open data (each source's own quality is in lebanon/sources.json)
    "official_register": ("A", 92, "government"),  # ICC register, Ministry lists, official files
    "association_directory": ("A", 90, "association"),  # ABL Almanac of Banks
    "web_archive": ("A", 88, "web_archive"),  # the company's own pages as Common Crawl archived them
    "open_data": ("B", 75, "open_dataset"),  # Wikidata
}
_BLOCKED = re.compile(
    r"(^|\.)(linkedin\.com|lnkd\.in|facebook\.com|fb\.com|instagram\.com|twitter\.com|x\.com|tiktok\.com|"
    r"youtube\.com|threads\.net|pinterest\.com|reddit\.com|quora\.com|medium\.com|"
    r"zoominfo\.com|apollo\.io|lusha\.com|rocketreach\.co|signalhire\.com|contactout\.com|seamless\.ai|"
    r"leadiq\.com|cognism\.com|kaspr\.io|hunter\.io|clearbit\.com|people-search|truecaller\.com|"
    r"bayt\.com|indeed\.com|glassdoor\.com|wuzzuf\.net|naukrigulf\.com|monster\.com|hirelebanese\.com|"
    r"google\.[a-z.]+|bing\.com|duckduckgo\.com|yahoo\.com|yandex\.[a-z]+|baidu\.com|search\.brave\.com|"
    r"startpage\.com|ecosia\.org|qwant\.com|searx[\w.-]*|"
    # subscription directories: never fetched (their data is licensed; a licence plugs in as a file, see lebanon/)
    r"5index\.com|5index\.com\.lb|"
    r"wikidata\.org)$", re.IGNORECASE)
_BLOCKED_PATH = re.compile(r"/(login|signin|sign-in|register|share|sharer|intent|cart|checkout|jobs?/|careers?/apply)",
                           re.IGNORECASE)
_NO_TEXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|zip|rar|mp4|mp3|docx?|xlsx?|pptx?)(\?|$)", re.IGNORECASE)
_CONFERENCE = re.compile(r"conference|summit|forum|expo|exhibition|congress|symposium|speakers?|panel|agenda|"
                         r"programme|program|awards?|event", re.IGNORECASE)
_ASSOCIATION = re.compile(r"association|chamber|syndicate|federation|council|institute|society|order of|union|"
                          r"club|committee|board-of-directors|members|ccib|ccia|ali\.org|bankers", re.IGNORECASE)
_CASE_STUDY = re.compile(r"case[-_ ]?stud|customer[-_ ]?stor|success[-_ ]?stor|testimonial|references?/",
                         re.IGNORECASE)
_PUBLICATION = re.compile(r"news|article|press|magazine|interview|blog|story|/20\d{2}/|/\d{4}/\d{2}/|"
                          r"lorientlejour|executive-magazine|annahar|the961|businessnews|arabnews|zawya|"
                          r"al-monitor|nna-leb|dailystar|lbcgroup|mtv\.com\.lb|aljadeed|beirut\.com|"
                          r"thebusinessyear|economist|reuters|bloomberg|forbesmiddleeast|gulfnews|khaleejtimes",
                          re.IGNORECASE)
_DIRECTORY = re.compile(r"yellowpages|kompass|dnb\.com|opencorporates|crunchbase|bizdirlib|cybo|infobel|"
                        r"directory|listing|company-profile|companies/|lebanon-companies|ccib\.org\.lb/members",
                        re.IGNORECASE)
_REGULATORY = re.compile(r"\.gov\.|\.gov$|bdl\.gov\.lb|cma\.gov\.lb|economy\.gov\.lb|justice\.gov\.lb|"
                         r"commercial-register|registry", re.IGNORECASE)


@dataclass(frozen=True)
class Kind:
    category: str
    tier: str
    quality: int
    source_type: str


def blocked(url: str) -> str | None:
    """Why this URL is never fetched (None: it may be)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return "not a web address"
    if _BLOCKED.search(host):
        return f"{host} is never fetched (social network, job board, people-data vendor or search engine)"
    if _BLOCKED_PATH.search(parts.path) or _NO_TEXT.search(parts.path):
        return "a login / share / job-application page or a file without text"
    return None


def kind_of(url: str, title: str, company_domain_: str | None) -> Kind:
    pdf = urlsplit(url).path.lower().endswith(".pdf")
    if company_domain_ and company_domain(url) == company_domain_:
        category = "company_document" if pdf else "company_page"
    else:
        probe = f"{urlsplit(url).hostname} {urlsplit(url).path} {title}"
        category = next((c for c, pattern in (("regulatory", _REGULATORY), ("directory", _DIRECTORY),
                                              ("case_study", _CASE_STUDY), ("conference", _CONFERENCE),
                                              ("association", _ASSOCIATION), ("publication", _PUBLICATION))
                         if pattern.search(probe)), "public_document" if pdf else "other")
    tier, quality, source_type = CATEGORIES[category]
    return Kind(category, tier, quality, source_type)
