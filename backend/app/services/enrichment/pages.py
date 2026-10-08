"""Company website pages: parsing, page classification, link discovery for the crawl, JavaScript-only detection.

A page is parsed once (lxml) into a `Doc`: text blocks in document order, links with where they sit (navigation,
footer, body), headings, structured data (JSON-LD), meta tags and passive technology markers. The Doc is what
LeadFinder stores (company_web_pages.content) and what every extractor reads, so a page can be re-extracted
later without fetching it again. Raw HTML is never stored.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import lxml.html
from lxml import etree

from app.services.normalization import company_domain

MAX_BLOCKS = 600
MAX_BLOCK_CHARS = 1000
MAX_TEXT_CHARS = 60_000
MAX_LINKS = 400
_BLOCK_TAGS = {"p", "li", "address", "td", "th", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
               "figcaption", "label", "div", "section", "article"}
_CONTAINERS = {"div", "section", "article", "li", "td"}  # used only when they hold no other block
_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "form", "select", "button"}

# Passive technology markers in the page source (never probing: only what the public page itself loads).
TECHNOLOGIES = [
    ("Shopify", r"cdn\.shopify\.com|Shopify\.theme"),
    ("WooCommerce", r"woocommerce"),
    ("WordPress", r"/wp-content/|/wp-includes/|<meta[^>]+generator[^>]+WordPress"),
    ("Magento", r"Magento_|/static/version\d+/frontend/|mage/cookies"),
    ("Odoo", r"<meta[^>]+generator[^>]+Odoo|data-oe-model=|/web/assets/\d"),
    ("Wix", r"static\.wixstatic\.com|<meta[^>]+generator[^>]+Wix"),
    ("Squarespace", r"static1\.squarespace\.com"),
    ("Joomla", r"<meta[^>]+generator[^>]+Joomla"),
    ("Drupal", r"<meta[^>]+generator[^>]+Drupal|Drupal\.settings"),
    ("PrestaShop", r"<meta[^>]+generator[^>]+PrestaShop|var prestashop"),
    ("OpenCart", r"catalog/view/theme/"),
    ("Webflow", r"<meta[^>]+generator[^>]+Webflow|assets\.website-files\.com"),
    ("Google Analytics", r"google-analytics\.com/|googletagmanager\.com/gtag/js"),
    ("Google Tag Manager", r"googletagmanager\.com/gtm\.js"),
    ("Meta Pixel", r"connect\.facebook\.net/[^\"']*/fbevents\.js"),
    ("Hotjar", r"static\.hotjar\.com"),
    ("Tawk.to", r"embed\.tawk\.to"),
    ("Intercom", r"widget\.intercom\.io"),
    ("Zendesk", r"static\.zdassets\.com"),
    ("HubSpot", r"js\.hs-scripts\.com"),
    ("Zoho SalesIQ", r"salesiq\.zoho"),
    ("Crisp", r"client\.crisp\.chat"),
    ("Calendly", r"assets\.calendly\.com|calendly\.com/[\w-]+"),
]
_TECH = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in TECHNOLOGIES]


@dataclass
class Doc:
    url: str
    title: str | None = None
    lang: str | None = None
    meta: dict[str, str] = field(default_factory=dict)  # description, og:site_name, generator, canonical...
    # [tag, text, area: nav | footer | body] in document order (headings included)
    blocks: list[list[str]] = field(default_factory=list)
    links: list[list[str]] = field(default_factory=list)  # [absolute url, text, area: nav | footer | body]
    jsonld: list[dict] = field(default_factory=list)  # flattened structured-data objects
    technologies: list[str] = field(default_factory=list)
    scripts: int = 0
    app_shell: bool = False  # an empty single-page-app root (<div id="root|app|__next">)

    @property
    def text_length(self) -> int:
        return sum(len(b[1]) for b in self.blocks)

    def headings(self, levels: str = "123456") -> list[str]:
        return [b[1] for b in self.blocks if len(b[0]) == 2 and b[0][0] == "h" and b[0][1] in levels]

    def text(self, areas: tuple[str, ...] = ("body", "nav", "footer")) -> list[str]:
        return [b[1] for b in self.blocks if b[2] in areas]

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Doc":
        return cls(**data)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _area(el) -> str:
    for parent in el.iterancestors():
        tag = parent.tag if isinstance(parent.tag, str) else ""
        marker = f"{parent.get('class', '')} {parent.get('id', '')} {parent.get('role', '')}".lower()
        if tag == "footer" or "footer" in marker or "contentinfo" in marker:
            return "footer"
        if tag in ("nav", "header") or re.search(r"\b(nav|menu|navbar|navigation)\b", marker):
            return "nav"
    return "body"


def _flatten(data) -> list[dict]:
    """JSON-LD objects, @graph and lists unrolled (nested objects stay inside their parent)."""
    if isinstance(data, list):
        return [item for entry in data for item in _flatten(entry)]
    if isinstance(data, dict):
        return _flatten(data["@graph"]) if "@graph" in data else [data]
    return []


def parse(html: str, url: str) -> Doc:
    doc = Doc(url=url)
    source = html[:2_000_000]
    doc.technologies = [name for name, pattern in _TECH if pattern.search(source)]
    try:
        root = lxml.html.fromstring(source)
    except (etree.ParserError, ValueError):
        return doc
    doc.lang = (root.get("lang") or "").split("-")[0].lower() or None
    title = root.find(".//title")
    doc.title = _clean(title.text_content())[:500] if title is not None else None
    for meta in root.iter("meta"):
        key = (meta.get("name") or meta.get("property") or "").lower()
        if key in ("description", "og:description", "og:site_name", "og:title", "og:type", "generator",
                   "article:published_time", "article:modified_time", "og:updated_time", "date",
                   "dc.date", "pubdate") and meta.get("content"):
            doc.meta[key] = _clean(meta.get("content"))[:1000]
    for link in root.iter("link"):
        if (link.get("rel") or "").lower() == "canonical" and link.get("href"):
            doc.meta["canonical"] = urljoin(url, link.get("href").strip())
    for script in root.iter("script"):
        doc.scripts += 1
        if (script.get("type") or "").lower() == "application/ld+json" and script.text:
            try:
                doc.jsonld.extend(_flatten(json.loads(script.text, strict=False)))
            except ValueError:
                pass
    doc.jsonld = doc.jsonld[:50]
    doc.app_shell = any(len(_clean(el.text_content())) < 20 for el in root.xpath(
        "//div[@id='root' or @id='app' or @id='__next' or @id='__nuxt']"))
    for el in root.xpath("|".join(f"//{tag}" for tag in _SKIP)):
        el.drop_tree()
    for a in root.iter("a"):
        href = (a.get("href") or "").strip()
        if href and len(doc.links) < MAX_LINKS:
            text = _clean(a.text_content()) or _clean(a.get("aria-label") or a.get("title"))
            doc.links.append([href if href.startswith(("tel:", "mailto:")) else urljoin(url, href), text[:200],
                              _area(a)])
    seen: set[str] = set()
    total = 0
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag not in _BLOCK_TAGS or (tag in _CONTAINERS and any(
                isinstance(c.tag, str) and c.tag in _BLOCK_TAGS for c in el.iterdescendants())):
            continue
        text = _clean(el.text_content())[:MAX_BLOCK_CHARS]
        if len(text) < 2 or text in seen:
            continue
        seen.add(text)
        doc.blocks.append([tag, text, _area(el)])
        total += len(text)
        if len(doc.blocks) >= MAX_BLOCKS or total >= MAX_TEXT_CHARS:
            break
    return doc


def needs_javascript(doc: Doc) -> bool:
    """The page only renders in a browser: almost no text, but scripts / an app root / a 'enable JavaScript'
    notice. LeadFinder does not render pages (see the Step 4 report); the page is recorded as such."""
    if doc.text_length >= 250:
        return False
    notice = any(re.search(r"enable javascript|javascript (is )?required", t, re.I) for t in doc.text())
    return doc.app_shell or notice or doc.scripts >= 5


# ---- classification -------------------------------------------------------------------------------------------

# A page type is only given when every word of a URL segment (or of the link text) belongs to that type's
# vocabulary: "/contact-us", "/en/about-us", "/products/bread-flour" (parent segment), "من نحن"; never a shop's
# "/cpu-contact-brackets" or "/presentation-remotes". First type wins.
_VOCABULARY = [
    ("contact", "contact contacts contactus touch get in reach write call email form contacte contactez nous "
                "اتصل اتصلوا بنا تواصل معنا اتصال"),
    ("careers", "career careers job jobs vacancies vacancy join work with recruitment opportunities openings "
                "emploi emplois carriere carrieres recrutement وظائف توظيف"),
    ("locations", "location locations branch branches store stores locator showroom showrooms outlet outlets network "
                  "find where map points vente de succursales agences boutiques فروع فروعنا مواقعنا"),
    ("manufacturing", "factory factories manufacturing production plant plants facility facilities usine usines "
                      "industrial industry fabrication مصنع مصانع تصنيع"),
    ("products", "product products catalog catalogue collection collections brands brand range ranges produits "
                 "nos منتجات منتجاتنا"),
    ("services", "service services solution solutions what do expertise prestations خدمات خدماتنا"),
    ("news", "news press media blog events event actualites actualite announcements awards newsroom centre center "
             "releases أخبار الأخبار"),
    ("team", "team management leadership board people founders equipe direction directors executives فريق فريقنا"),
    ("about", "about who we are company story history profile mission vision values presentation propos qui sommes "
              "overview group corporate من نحن نبذة عن الشركة عنا"),
]
_VOCAB = [(kind, set(words.split())) for kind, words in _VOCABULARY]
_FILLER = {"us", "our", "the", "page", "html", "htm", "php", "aspx", "asp", "jsp", "index", "en", "ar", "fr", "a",
           "le", "la", "les", "et", "and", "&", "s"}
_WORD = re.compile(r"[^\W_]+")


def _kind_of(text: str) -> str | None:
    words = {w for w in _WORD.findall(text.lower()) if not w.isdigit()} - _FILLER
    if not words:
        return None
    return next((kind for kind, vocab in _VOCAB if words <= vocab), None)


# Team / management pages rank high since Step 5: people discovery reads them.
PAGE_PRIORITY = {"contact": 100, "about": 95, "team": 90, "locations": 85, "manufacturing": 82, "products": 80,
                 "services": 78, "careers": 60, "news": 50}
MAX_PER_TYPE = {"products": 3, "services": 2, "news": 1, "team": 1, "careers": 1}
_SKIP_PATH = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|rar|docx?|xlsx?|pptx?|mp4|mp3|xml|json|css|js)$|"
                        r"/(cart|checkout|my-account|account|login|signin|register|wp-login|wp-admin|feed|search|"
                        r"tag|author|privacy|terms|cookie)", re.IGNORECASE)
_LANG_SEGMENT = re.compile(r"^/([a-z]{2})(/|$)")


def _path(url: str) -> str:
    return unquote(urlsplit(url).path or "/").lower()


def classify(url: str, text: str = "", title: str | None = None) -> str:
    path = _path(url)
    if path.strip("/") in ("", "index.html", "index.php", "home", "en", "fr", "ar"):
        return "homepage"
    segments = [seg for seg in path.split("/") if seg and not _LANG_SEGMENT.match(f"/{seg}/")]
    for segment in reversed(segments):  # the page's own slug first, then its section ("/products/bread-flour")
        if kind := _kind_of(segment):
            return kind
    return _kind_of(text) or _kind_of(title or "") or "other"


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path.rstrip("/") or "/", parts.query, ""))


def same_site(url: str, site_domain: str) -> bool:
    return urlsplit(url).scheme in ("http", "https") and company_domain(url) == site_domain


def candidate_links(doc: Doc, site_domain: str) -> list[tuple[int, str, str]]:
    """(score, url, page type) of the links worth fetching, best first: same site, a known page type, in the
    language of the start page, navigation links first. Never every page of the site."""
    start_lang = _LANG_SEGMENT.match(_path(doc.url))
    found: dict[str, tuple[int, str, str]] = {}
    for url, text, area in doc.links:
        if not same_site(url, site_domain) or _SKIP_PATH.search(urlsplit(url).path) or len(url) > 500:
            continue
        url = normalize_url(url)
        kind = classify(url, text)
        if kind in ("other", "homepage"):
            continue
        score = PAGE_PRIORITY[kind] + {"nav": 6, "footer": 3}.get(area, 0) - _path(url).count("/")
        lang = _LANG_SEGMENT.match(_path(url))
        if lang and start_lang and lang[1] != start_lang[1]:
            score -= 40  # the same page in another language
        if url not in found or found[url][0] < score:
            found[url] = (score, url, kind)
    return sorted(found.values(), reverse=True)
