"""Deterministic extraction of company facts from a parsed website page (pages.Doc). No AI, no guessing:
every Fact carries the excerpt it was read from and a confidence by how it was read.

    structured data (JSON-LD Organization / LocalBusiness / Product / JobPosting)   85
    tel: / mailto: / social links on the official site                             85
    meta description, site name                                                    70-75
    labelled text (phones, emails, addresses, founded, employees)                  70-75
    headings / menu items (products, services)                                     65-70
    keywords in running text (operational signals)                                 55-70
    technology markers in the page source                                          90

Multiplied later by how sure LeadFinder is that the website is the company's (orchestrator.ownership).
Person-level data (team pages, people's emails) is deliberately not extracted: that is Step 5.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

from app.services.discovery.consolidation import _GENERIC, _NEIGHBOURHOODS, name_tokens
from app.services.discovery.geography import AREAS, _fold, region_for
from app.services.enrichment.pages import Doc, same_site
from app.services.normalization import FREE_EMAIL_DOMAINS, has_legal_form, normalize_domain, normalize_phone


@dataclass
class Fact:
    kind: str  # field | phone | email | social | location | offering | signal
    name: str  # field name / social network / signal type / offering kind
    value: Any
    confidence: int
    excerpt: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Context:
    company_name: str
    country_code: str | None
    country_name: str | None
    site_domain: str

    @property
    def tokens(self) -> set[str]:
        return {t for t in name_tokens(self.company_name) if len(t) >= 3 and t not in _GENERIC}

    @property
    def compact(self) -> str:
        return "".join(name_tokens(self.company_name))


def _excerpt(text: str, start: int, end: int, pad: int = 100) -> str:
    return ("…" if start > pad else "") + text[max(0, start - pad):end + pad].strip() + (
        "…" if end + pad < len(text) else "")


def _related(name: str | None, ctx: Context) -> bool:
    """A structured-data organisation is this company (not a partner, client or the web agency)."""
    if not name:
        return True
    tokens = set(name_tokens(name))
    return bool(tokens & ctx.tokens) or "".join(name_tokens(name)) in (ctx.compact, ctx.site_domain.split(".")[0])


# ---- structured data ---------------------------------------------------------------------------------------------

_NOT_ORG = {"WebSite", "WebPage", "BreadcrumbList", "ListItem", "Person", "Article", "BlogPosting", "NewsArticle",
            "ImageObject", "Product", "Offer", "SearchAction", "ItemList", "FAQPage", "Question", "Answer",
            "VideoObject", "CollectionPage", "SiteNavigationElement", "ReadAction", "Event", "Review",
            "AggregateRating", "JobPosting", "Service", "OfferCatalog", "Brand", "PostalAddress", "GeoCoordinates",
            "ContactPoint", "Place", "EntryPoint", "PropertyValue", "QuantitativeValue", "OpeningHoursSpecification",
            "Country", "City", "AboutPage", "ContactPage", "Thing", "WPHeader", "WPFooter", "Rating"}


def _types(item: dict) -> set[str]:
    kind = item.get("@type")
    return {kind} if isinstance(kind, str) else {k for k in (kind or []) if isinstance(k, str)}


def _walk(value, depth: int = 0) -> Iterator[dict]:
    if depth > 4:
        return
    if isinstance(value, list):
        for v in value:
            yield from _walk(v, depth + 1)
    elif isinstance(value, dict):
        if "@type" in value:
            yield value
        for v in value.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v, depth + 1)


def _str(value) -> str | None:
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str)), None)
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value")
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else None


def _organizations(doc: Doc, ctx: Context) -> list[dict]:
    return [i for i in _walk(doc.jsonld) if _types(i) and not _types(i) <= _NOT_ORG and _related(_str(i.get("name")), ctx)]


# ---- business profile --------------------------------------------------------------------------------------------

_FOUNDED = re.compile(r"\b(founded|established|incorporated|est\.|since|fondée?|créée?|depuis|تأسست|تأسس|منذ)"
                      r"\s*(?:in\s+|en\s+|عام\s+|سنة\s+)?((?:18|19|20)\d{2})\b", re.IGNORECASE)
_EMPLOYEE_WORDS = (r"(?:dedicated\s+|full[- ]time\s+|skilled\s+|qualified\s+)?(?:employees|staff(?:\s+members)?|"
                   r"team members|workers|professionals|employés|collaborateurs|salariés|موظفا?|موظفين|عاملا?|عامل)")
_EMPLOYEE_RANGE = re.compile(r"\b(\d{1,6})\s*(?:-|–|to|à)\s*(\d{1,6})\s+" + _EMPLOYEE_WORDS, re.IGNORECASE)
_EMPLOYEES = re.compile(r"(more than|over|plus de|أكثر من)?\s*\b(\d{1,3}(?:,\d{3})+|\d{1,6})\s*(\+)?\s+"
                        + _EMPLOYEE_WORDS, re.IGNORECASE)
_COPYRIGHT = re.compile(r"(?:©|copyright)\s*(?:\d{4}\s*(?:[-–]\s*\d{4})?)?\s*,?\s*([^.|©\n]{3,80}?)\s*"
                        r"(?:[.,|]|all rights|$)", re.IGNORECASE)
_LEGAL_TAIL = re.compile(r"\b(s\.?a\.?l\.?|s\.?a\.?r\.?l\.?|l\.?l\.?c\.?|ltd\.?|inc\.?|holding|ش\.م\.ل|ش\.م\.م)\s*$",
                         re.IGNORECASE)
_BOILERPLATE = re.compile(r"cookie|privacy|all rights reserved|javascript|copyright|©|terms of use", re.IGNORECASE)


def _year(value) -> int | None:
    found = re.search(r"(1[89]\d{2}|20\d{2})", str(value or ""))
    year = int(found[1]) if found else None
    return year if year and 1800 <= year <= date.today().year else None


def _employees(value) -> tuple[int | None, int | None, int | None]:
    """JSON-LD numberOfEmployees: a number or a QuantitativeValue -> (estimate, min, max)."""
    if isinstance(value, dict):
        def num(key):
            return int(v) if (v := re.sub(r"\D", "", str(value.get(key) or ""))) else None
        exact, low, high = num("value"), num("minValue"), num("maxValue")
        return exact, low, high
    digits = re.sub(r"\D", "", str(value or ""))
    return (int(digits), None, None) if digits else (None, None, None)


def _profile(doc: Doc, page_type: str, ctx: Context, orgs: list[dict]) -> list[Fact]:
    facts: list[Fact] = []
    for org in orgs:
        if desc := _str(org.get("description")):
            facts.append(Fact("field", "description", desc[:1500], 85, desc[:300]))
        if legal := _str(org.get("legalName")):
            facts.append(Fact("field", "legal_name", legal[:300], 85, f"legalName: {legal}"))
        if (name := _str(org.get("name"))) and name.lower() != ctx.company_name.lower():
            facts.append(Fact("field", "trading_name", name[:300], 80, f"name: {name}"))
        if year := _year(org.get("foundingDate")):
            facts.append(Fact("field", "founded_year", year, 85, f"foundingDate: {org.get('foundingDate')}"))
        if org.get("numberOfEmployees") is not None:
            exact, low, high = _employees(org["numberOfEmployees"])
            excerpt = f"numberOfEmployees: {org['numberOfEmployees']}"
            facts += [Fact("field", f, v, 85, excerpt) for f, v in (("employee_count_estimate", exact),
                      ("employee_count_min", low), ("employee_count_max", high)) if v and 1 <= v <= 500_000]
    if site := doc.meta.get("og:site_name"):
        if site.lower() != ctx.company_name.lower() and _related(site, ctx):
            facts.append(Fact("field", "trading_name", site[:300], 70, f"og:site_name: {site}"))
    if page_type in ("homepage", "about"):
        meta = doc.meta.get("description") or doc.meta.get("og:description")
        if meta and len(meta) >= 50 and not _BOILERPLATE.search(meta):
            facts.append(Fact("field", "description", meta[:1500], 75 if page_type == "about" else 72, meta[:300]))
    if page_type == "about":
        for text in doc.text(("body",)):
            if 120 <= len(text) <= 900 and not _BOILERPLATE.search(text) and (
                    set(name_tokens(text)) & ctx.tokens or re.search(r"\b(we|our|nous|notre)\b|نحن", text, re.I)):
                facts.append(Fact("field", "description", text, 70, text[:300]))
                break
    body = doc.text(("body", "footer")) if page_type in ("homepage", "about", "other") else doc.text(("body",))
    if page_type in ("homepage", "about"):
        body += [t for t in (doc.meta.get("description"), doc.meta.get("og:description")) if t]
    for text in body:
        for m in _FOUNDED.finditer(text):
            if year := _year(m[2]):
                strong = m[1].lower() not in ("since", "depuis", "منذ")
                facts.append(Fact("field", "founded_year", year, 75 if strong else 62, _excerpt(text, m.start(), m.end())))
        if page_type != "news":
            for m in _EMPLOYEE_RANGE.finditer(text):
                low, high = int(m[1]), int(m[2])
                if 1 <= low < high <= 500_000:
                    excerpt = _excerpt(text, m.start(), m.end())
                    facts += [Fact("field", "employee_count_min", low, 70, excerpt),
                              Fact("field", "employee_count_max", high, 70, excerpt)]
            for m in _EMPLOYEES.finditer(text):
                count = int(m[2].replace(",", ""))
                if 2 <= count <= 500_000:
                    at_least = bool(m[1] or m[3])
                    facts.append(Fact("field", "employee_count_min" if at_least else "employee_count_estimate", count,
                                      70, _excerpt(text, m.start(), m.end())))
    for text in doc.text(("footer", "body"))[-40:]:
        if (m := _COPYRIGHT.search(text)) and (legal := m[1].strip(" -–,")) and _LEGAL_TAIL.search(legal) \
                and _related(legal, ctx) and has_legal_form(legal):
            facts.append(Fact("field", "legal_name", legal[:300], 60, m[0][:300]))
            break
    return facts


# ---- contacts (company level only) -------------------------------------------------------------------------------

_PHONE_LABEL = re.compile(r"\b(tel|tél|téléphone|phone|mob(?:ile)?|cell|call|hotline|whats ?app|fax|t|p|m|f)\s*[.:]|"
                          r"\b(tel|phone|mobile|hotline|call us|whatsapp|fax)\b|هاتف|تلفون|خليوي|جوال|الهاتف|واتساب|"
                          r"فاكس|ت\s*:", re.IGNORECASE)
_NUMBER = re.compile(r"(?:\+|00)\s?\d{1,3}[\s\-./()]*\d(?:[\s\-./()]*\d){5,10}|(?<![\d+])0\d(?:[\s\-./]?\d){5,7}(?!\d)|"
                     r"(?<![\d+])(?:3|7[016-9]|81)[\s\-./]?\d{3}[\s\-./]?\d{3}(?!\d)")
_FAX = re.compile(r"\bfax\b|\bf\s*[.:]|فاكس", re.IGNORECASE)
_PURPOSE = [("sales", r"sales|\bsell|ventes?|commercial|مبيعات"),
            ("support", r"customer (service|care|support)|support|hotline|helpdesk|after[- ]sales|service client|"
                        r"خدمة العملاء|الدعم"),
            ("orders", r"orders?|delivery|commande|livraison|reservations?|booking|طلب|توصيل|حجز"),
            ("careers", r"careers?|jobs?|\bhr\b|human resources|recruit|توظيف|وظائف")]
_LB_MOBILE = re.compile(r"^\+961(3\d{6}|7[016-9]\d{6}|81\d{6})$")
_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
_ROLE_PURPOSE = {
    "info": "info", "information": "info", "contact": "general", "contacts": "general", "hello": "general",
    "hi": "general", "office": "general", "admin": "general", "mail": "general", "general": "general",
    "reception": "general", "enquiries": "general", "enquiry": "general", "inquiries": "general",
    "inquiry": "general", "team": "general",
    "sales": "sales", "sale": "sales", "export": "sales", "exports": "sales", "marketing": "sales",
    "business": "sales", "commercial": "sales",
    "support": "support", "help": "support", "service": "support", "services": "support",
    "customerservice": "support", "customercare": "support", "care": "support", "cs": "support",
    "orders": "orders", "order": "orders", "booking": "orders", "bookings": "orders", "reservations": "orders",
    "reservation": "orders", "delivery": "orders",
    "hr": "careers", "careers": "careers", "career": "careers", "jobs": "careers", "recruitment": "careers",
    "cv": "careers",
    "accounts": "other", "accounting": "other", "finance": "other", "procurement": "other", "purchasing": "other",
}
_NOT_EMAIL_TLD = {"png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js"}


def _purpose(context: str) -> str:
    return next((p for p, pattern in _PURPOSE if re.search(pattern, context, re.IGNORECASE)), "general")


def _phone(raw: str, ctx: Context) -> str | None:
    number = normalize_phone(raw, ctx.country_name)
    if number and number.startswith("+961") and len(number) not in (11, 12):
        return None  # not a Lebanese landline (7 digits) / mobile (7-8 digits)
    return number


def _phone_type(number: str, whatsapp: bool) -> str:
    if whatsapp:
        return "whatsapp"
    if number.startswith("+961"):
        return "mobile" if _LB_MOBILE.match(number) else "landline"
    return "unknown"


def _company_email(email: str, ctx: Context) -> str | None:
    """Only the company's own mailboxes (info@, sales@, the company's name...): never a person's address."""
    local, _, domain = email.lower().rpartition("@")
    domain = normalize_domain(domain) or ""
    if domain.rsplit(".", 1)[-1] in _NOT_EMAIL_TLD or domain.endswith(("example.com", "sentry.io", "wixpress.com")):
        return None
    role = _ROLE_PURPOSE.get(re.sub(r"[^a-z]", "", local))
    own = domain == ctx.site_domain or domain.endswith("." + ctx.site_domain)
    named = bool(ctx.compact) and len(ctx.compact) >= 4 and ctx.compact in re.sub(r"[^a-z0-9]", "", local)
    if (own and (role or named)) or (domain in FREE_EMAIL_DOMAINS and named):
        return role or "general"
    return None


def _contacts(doc: Doc, ctx: Context, orgs: list[dict]) -> list[Fact]:
    facts: list[Fact] = []

    def phone(raw: str, confidence: int, context: str, whatsapp: bool = False) -> None:
        if number := _phone(raw, ctx):
            facts.append(Fact("phone", "phone", number, confidence, context[:300],
                              {"published": raw.strip()[:50], "purpose": _purpose(context),
                               "phone_type": _phone_type(number, whatsapp)}))

    def email(address: str, confidence: int, context: str) -> None:
        address = address.strip().lower().rstrip(".")
        if purpose := _company_email(address, ctx):
            facts.append(Fact("email", "email", address, confidence, context[:300], {"purpose": purpose}))

    for org in orgs:
        if tel := _str(org.get("telephone")):
            phone(tel, 85, f"telephone: {tel}")
        if mail := _str(org.get("email")):
            email(mail.removeprefix("mailto:"), 85, f"email: {mail}")
    for url, text, area in doc.links:
        if url.startswith("tel:"):
            phone(url[4:], 85, f"{text} ({area})")
        elif url.startswith("mailto:"):
            email(url[7:].split("?")[0], 85, f"{text} ({area})")
        else:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            if host in ("wa.me", "api.whatsapp.com", "web.whatsapp.com", "whatsapp.com"):
                digits = parts.path.strip("/") if host == "wa.me" else (parse_qs(parts.query).get("phone") or [""])[0]
                if digits := re.sub(r"\D", "", digits):
                    phone("+" + digits, 85, f"WhatsApp link: {text}", whatsapp=True)
    for text in doc.text():
        if _PHONE_LABEL.search(text):
            last = 0
            for m in _NUMBER.finditer(text):
                label = text[max(last, m.start() - 40):m.start()]
                last = m.end()
                if not _FAX.search(label.split("|")[-1][-15:]):
                    phone(m[0], 72, _excerpt(text, m.start(), m.end(), 60),
                          whatsapp=bool(re.search(r"whats ?app|واتساب", label, re.I)))
        for m in _EMAIL.finditer(text):
            email(m[0], 75, _excerpt(text, m.start(), m.end(), 60))
    return facts


# ---- social profiles -----------------------------------------------------------------------------------------------

_SOCIAL = {  # network: (host pattern, path that must match, path that must not match)
    "facebook": (r"(^|\.)(facebook|fb)\.com$", r"^/[^/]+", r"^/(sharer|share|dialog|plugins|tr|login|groups)\b"),
    "instagram": (r"(^|\.)instagram\.com$", r"^/[^/]+", r"^/(p|explore|accounts|reel|stories)/"),
    "linkedin": (r"(^|\.)linkedin\.com$", r"^/(company|school|showcase)/[^/]+", r"^/(in|pub|shareArticle)/"),
    "youtube": (r"(^|\.)youtube\.com$", r"^/(channel/|c/|user/|@)[^/]+", r"^/(watch|embed|results)"),
    "tiktok": (r"(^|\.)tiktok\.com$", r"^/@[^/]+", r"^/(embed|share)"),
    "twitter": (r"(^|\.)(twitter|x)\.com$", r"^/[^/]+", r"^/(intent|share|home|search|hashtag)\b"),
}


def social_profile(url: str) -> tuple[str, str] | None:
    """(network, normalized company-page URL) of a social profile link; None for share buttons, posts or
    personal LinkedIn profiles. LeadFinder only stores the URL: it never fetches social networks."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    for network, (host_re, must, must_not) in _SOCIAL.items():
        if re.search(host_re, host) and re.match(must, parts.path or "/") and not re.match(must_not, parts.path,
                                                                                            re.IGNORECASE):
            segments = parts.path.rstrip("/").split("/")[:3 if network in ("linkedin", "youtube") else 2]
            return network, f"https://{'www.' if network != 'twitter' else ''}{host}{'/'.join(segments)}"
    return None


def _socials(doc: Doc, orgs: list[dict]) -> list[Fact]:
    urls = [(url, f"link on the company website: {text or url}") for url, text, _ in doc.links]
    urls += [(u, f"sameAs: {u}") for org in orgs for u in (org.get("sameAs") if isinstance(org.get("sameAs"), list)
                                                          else [org.get("sameAs")]) if isinstance(u, str)]
    facts, seen = [], set()
    for url, excerpt in urls:
        if (found := social_profile(url)) and found[0] not in seen:
            seen.add(found[0])
            facts.append(Fact("social", found[0], found[1], 85, excerpt[:300]))
    return facts


# ---- locations ---------------------------------------------------------------------------------------------------

# A postal address, not prose that happens to mention a street: short, with a strong address word.
_ADDRESS_MARKER = re.compile(
    r"\b(street|st\.|road|rd\.|highway|hwy|bldg\.?|building|blvd|boulevard|avenue|ave\.|p\.?\s?o\.?\s?box|rue|"
    r"immeuble|autostrade|industrial (zone|area|city)|\d+(st|nd|rd|th)? floor|floor \d+|square)\b|"
    r"شارع|بناية|طابق|مبنى|ص\.ب|طريق|اوتوستراد|أوتوستراد", re.IGNORECASE)
_PROSE = re.compile(r"[a-z]{2,}[.!?]\s+[A-Z]|\b(we|our|you|your|nous|notre|vous)\b", re.IGNORECASE)
_LOCATION_TYPES = [
    ("factory", r"\bfactor(y|ies)\b|\bplant\b|\busines?\b|\bmanufactur|production site|مصنع|معمل"),
    ("warehouse", r"warehouse|\bdepot\b|dépôt|storage|مستودع|مخزن"),
    ("showroom", r"showroom|show room|معرض"),
    ("headquarters", r"head ?office|headquarters|\bhq\b|main office|corporate office|siège|المركز الرئيسي|الإدارة العامة"),
    ("service_center", r"service cent(er|re)|after[- ]sales|مركز صيانة|مركز خدمة"),
    ("clinic", r"\bclinic\b|عيادة|clinique"),
    ("restaurant", r"\brestaurant\b|مطعم"),
    ("store", r"\bstore\b|\bshop\b|boutique|outlet|متجر|محل"),
    ("branch", r"\bbranch\b|فرع|succursale|agence"),
    ("office", r"\boffice\b|bureau|مكتب"),
]
_SCHEMA_LOCATION = {"Restaurant": "restaurant", "FoodEstablishment": "restaurant", "Store": "store",
                    "MedicalClinic": "clinic", "AutoRepair": "service_center"}  # an Organization's address: untyped
_CONTACT_TAIL = re.compile(r"\s*(?:[-–|]\s*)?\b(?:tel|tél|phone|mob(?:ile)?|fax|e-?mail|hotline)\b|"
                           r"\s*(?:[-–|]\s*)?(?:هاتف|تلفون|فاكس)", re.IGNORECASE)
# "Address:", "Shop and Factory:", "Head office -": a short label before the address (its words give the type).
_LABEL = re.compile(r"^\s*([^\W\d][^:：\d]{0,40}?)\s*[:：]\s*", re.IGNORECASE)


def _places(country_code: str | None) -> list[tuple[re.Pattern, str]]:
    if country_code != "LB":
        return []
    names = [(name, area.label) for area in AREAS["LB"].values() if area.kind == "city" for name in area.names]
    names += [(n, n.title()) for n in _NEIGHBOURHOODS if len(n) >= 5 and n not in ("lebanon", "liban", "beyrouth")]
    return [(re.compile(rf"(?<!\w){re.escape(_fold(name))}(?!\w)"), label) for name, label in names]


_PLACE_CACHE: dict[str | None, list] = {}


def _place(text: str, country_code: str | None) -> str | None:
    if country_code not in _PLACE_CACHE:
        _PLACE_CACHE[country_code] = _places(country_code)
    folded = _fold(text)
    return next((label for pattern, label in _PLACE_CACHE[country_code] if pattern.search(folded)), None)


def location_type(text: str) -> str | None:
    return next((t for t, pattern in _LOCATION_TYPES if re.search(pattern, text, re.IGNORECASE)), None)


def _locations(doc: Doc, page_type: str, ctx: Context, orgs: list[dict]) -> list[Fact]:
    facts: list[Fact] = []
    for org in orgs:
        address = org.get("address")
        if not address:
            continue
        if isinstance(address, dict):
            street, city = _str(address.get("streetAddress")), _str(address.get("addressLocality"))
            region = _str(address.get("addressRegion"))
            text = ", ".join(p for p in (street, city, region) if p)
        else:
            text = _str(address)
            street, city, region = None, _place(text or "", ctx.country_code), None
        geo = org.get("geo") if isinstance(org.get("geo"), dict) else {}
        try:
            lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
        except (TypeError, ValueError):
            lat = lon = None
        kind = next((_SCHEMA_LOCATION[t] for t in _types(org) if t in _SCHEMA_LOCATION), None)
        if text:
            facts.append(Fact("location", "location", {
                # The name / phone of the organisation itself are company-level, not this place's.
                "name": _str(org.get("name")) if kind else None,
                "address": (", ".join(p for p in (street, city) if p) or text)[:500], "city": city,
                "region": region or region_for(ctx.country_code or "", lat, lon, city), "latitude": lat,
                "longitude": lon, "phone": _phone(_str(org.get("telephone")) or "", ctx) if kind else None,
                "location_type": kind}, 85, f"structured address: {text}"[:300]))
    if page_type not in ("contact", "locations", "about", "manufacturing", "homepage"):
        return facts
    heading = None
    for tag, text, area in doc.blocks:
        if tag[0] == "h" and len(tag) == 2:
            heading = text if len(text) <= 80 else None
            continue
        if area == "nav" or len(text) > 200 or len(text.split()) > 30 or not _ADDRESS_MARKER.search(text) \
                or _PROSE.search(text):
            continue
        if not (city := _place(text, ctx.country_code)):
            continue
        number = next((n for m in _NUMBER.finditer(text) if (n := _phone(m[0], ctx))), None)
        address = _CONTACT_TAIL.split(_LABEL.sub("", text), 1)[0].strip(" ,-–|")
        label = (m[1] if (m := _LABEL.match(text)) else "") or ""
        kind = location_type(label) or location_type(text) or (location_type(heading) if heading else None)
        name = heading if heading and (location_type(heading) or _place(heading, ctx.country_code)) else None
        facts.append(Fact("location", "location", {
            "name": name, "address": address[:500], "city": city, "region": region_for(ctx.country_code or "", None,
                                                                                        None, city),
            "latitude": None, "longitude": None, "phone": number, "location_type": kind}, 70, text[:300]))
        if len(facts) >= 20:
            break
    return facts


# ---- products and services ----------------------------------------------------------------------------------------

_STOP = set("""home about|about us|contact|contact us|products|our products|product|product range|services|our services
service|solutions|our solutions|read more|learn more|more|view more|view all|see all|see more|discover more|discover
shop now|buy now|order now|newsletter|subscribe|follow us|quick links|useful links|links|categories|category|menu
search|cart|login|log in|sign in|register|my account|account|privacy policy|terms|terms and conditions|copyright
latest news|news|blog|gallery|careers|faq|faqs|testimonials|our clients|clients|partners|our partners|why choose us
get in touch|send message|send|submit|back|next|previous|close|all|all products|featured products|new arrivals
best sellers|sale|mission|vision|our mission|our vision|values|our values|our story|history|who we are|what we do
overview|details|description|reviews|related products|share|english|arabic|français|french|العربية|welcome
our catalogue|our catalog|download catalogue|download catalog|view catalogue|e-catalogue|shop all|shop by category
contact information|address|phone|email|location|locations|our locations|branches|our branches|download|brochure
catalogue|catalog|team|our team|events|media|press|certifications|quality|sitemap|help|support|social media
opening hours|working hours|map|directions|call us|email us|visit us|find us|location map|company|the company
our company|group|our group|introduction|products & services|products and services|services & solutions
store|shop|online shop|e-shop|our brands|brands|industries|sectors|projects|our projects|portfolio|news & events
latest products|top products|popular products|special offers|offers|promotions|recipes|tips""".replace("\n", "|")
            .split("|"))
_GENERIC_OFFERING = {"products", "product", "services", "service", "range", "collection", "collections", "brands",
                     "brand", "solutions", "solution", "our", "the", "all", "new", "items", "catalogue", "catalog"}
_OFFERING_PATH = re.compile(r"/(products?|produits?|catalog(ue)?|collections?|categor(y|ies)|shop|range|brands?|"
                            r"services?|solutions?|منتجات|خدمات)(/|$)", re.IGNORECASE)


def offering_name(text: str) -> str | None:
    """A published product / service name worth keeping: short, not navigation, not a sentence."""
    text = " ".join(text.split()).strip(" -–|•·:>»")
    words = text.split()
    if not (2 <= len(text) <= 60 and 1 <= len(words) <= 6) or not re.search(r"[^\W\d_]", text):
        return None
    if text.lower() in _STOP or text.endswith(("?", "!", ".")) or re.search(r"©|\d{3,}|\$|€|lbp|usd", text, re.I):
        return None
    return text


def normalize_offering(text: str) -> str:
    return re.sub(r"[^\w\s&+-]", "", text.casefold()).strip()[:200]


def _offerings(doc: Doc, page_type: str, ctx: Context) -> list[Fact]:
    facts: list[Fact] = []

    def add(kind: str, text: str, confidence: int, excerpt: str) -> None:
        # "Massabki Products", "Crown Range": only the company name and a generic word, not an offering.
        if (name := offering_name(text)) and set(name_tokens(name)) - ctx.tokens - _GENERIC_OFFERING:
            facts.append(Fact("offering", kind, name, confidence, excerpt[:300]))

    for item in _walk(doc.jsonld):
        kinds = _types(item)
        if kinds & {"Product", "ProductGroup", "ProductModel"} and (name := _str(item.get("name"))):
            add("product", name, 80, f"structured data Product: {name}")
        elif "Service" in kinds and (name := _str(item.get("name"))):
            add("service", name, 80, f"structured data Service: {name}")
        elif "OfferCatalog" in kinds and (name := _str(item.get("name"))):
            add("category", name, 75, f"structured data OfferCatalog: {name}")
    for url, text, area in doc.links:
        path = urlsplit(url).path
        if area == "nav" and same_site(url, ctx.site_domain) and (m := _OFFERING_PATH.search(path)) \
                and path.rstrip("/") != path[:m.end()].rstrip("/"):
            kind = "service" if re.match(r"/(services?|solutions?|خدمات)", m[0], re.I) else "category"
            add(kind, text, 70, f"menu item: {text}")
    if page_type in ("products", "services", "manufacturing"):
        kind = "service" if page_type == "services" else "product"
        for text in doc.headings("234"):
            add(kind, text, 65, f"heading on the {page_type} page: {text}")
        section = urlsplit(doc.url).path.rstrip("/")
        for url, text, area in doc.links:
            path = urlsplit(url).path.rstrip("/")
            if area == "body" and section and path.startswith(section + "/") and same_site(url, ctx.site_domain):
                add(kind, text, 65, f"link on the {page_type} page: {text}")
    return facts


# ---- operational signals ----------------------------------------------------------------------------------------

_SIGNALS = {
    "manufacturing": r"\bmanufactur(e|es|er|ers|ing)\b|production (line|facility|facilities|plant)|\bfabricant|"
                     r"\bfabrication\b|تصنيع|نصنع|تنتج|ننتج|إنتاج",
    "factory": r"\bfactor(y|ies)\b|\bproduction plant\b|\busines?\b|مصنع|معمل",
    "warehouse": r"\bwarehous(e|es|ing)\b|\bentrepôts?\b|مستودع",
    "distribution": r"\bdistribut(e|es|or|ors|ion|ing)\b|\bdistributeur|توزيع|موزع",
    "distribution_center": r"distribution (cent(er|re)|hub)|logistics (cent(er|re)|hub)|centre de distribution",
    "wholesale": r"\bwholesal(e|er|ers)\b|\bvente en gros\b|بالجملة",
    "retail": r"\bretail(er|ers|ing)?\b|\bvente au détail\b|بالتجزئة|بالمفرق",
    "retail_stores": r"\b(our|retail) (stores|shops|outlets|boutiques)\b|points de vente|متاجرنا|محلاتنا",
    "exporting": r"\bexport(s|ing|ed|er|ers)?\b|\bexportat(ion|eur)s?\b|تصدير|نصدر",
    "importing": r"\bimport(s|ing|ed|er|ers)\b|\bimportat(ion|eur)s?\b|استيراد|نستورد",
    "e_commerce": r"shop online|online (shop|store)|add to (cart|bag|basket)|ajouter au panier|\bcheckout\b",
    "online_ordering": r"order online|online order(ing|s)?|commander en ligne|اطلب (الآن|اونلاين)",
    "delivery": r"\bdeliver(y|ies)\b|\blivraison\b|توصيل",
    "fleet": r"\bfleet\b|our (trucks|vehicles)|\bflotte\b|أسطول",
    "field_sales": r"sales (force|representatives|reps)|field sales|merchandis(ers|ing)|force de vente|مندوبي المبيعات",
    "call_center": r"call cent(er|re)|centre d'appels|مركز اتصال",
    "customer_support": r"customer (service|support|care)|service client|after[- ]sales|خدمة العملاء",
    "appointment_booking": r"book (an|your) appointment|appointment booking|prendre rendez-vous|احجز موعد",
    "franchising": r"\bfranchis(e|es|ing|or|ees)\b|امتياز تجاري",
    "project_based": r"\bturnkey\b|\bprojects (delivered|completed|executed)\b|clé en main",
    "b2b": r"\bB2B\b|business[- ]to[- ]business|\b(corporate|industrial|wholesale) (clients|customers)\b",
    "b2c": r"\bB2C\b|business[- ]to[- ]consumer",
    "private_label": r"private[- ]label|white[- ]label|\bOEM\b|marque de distributeur",
    "hospitality": r"\bhotels?\b|\bresorts?\b|guest rooms|\bhospitality\b|فندق",
    "restaurants": r"\b(our|chain of) restaurants\b|مطاعمنا",
    "healthcare": r"\bhealthcare\b|\bmedical (center|centre|services)\b|\bpatients\b",
    "clinics": r"\bclinics?\b|polyclinic|عيادات",
    "hospitals": r"\bhospitals?\b|مستشفى",
    "construction": r"\bconstruction\b|\bcontracting\b|civil works|مقاولات",
    "professional_services": r"\bconsult(ing|ancy)\b|\badvisory\b|\baudit(ing)? services\b|legal services|استشارات",
    "service_center": r"service cent(er|re)s?|maintenance cent(er|re)|مركز صيانة",
    "showrooms": r"\bshowrooms?\b|معارضنا",
    "branches": r"\bbranches\b|\bsuccursales\b|فروعنا|فروع",
}
_SIGNAL_RE = {k: re.compile(v, re.IGNORECASE) for k, v in _SIGNALS.items()}
_NEGATED = re.compile(r"\b(no|not|without|non|pas de|aucun)\b\W+(\w+\W+){0,2}$|لا\s+$", re.IGNORECASE)
_NUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5}
_COUNT = re.compile(r"\b(\d{1,4}|" + "|".join(_NUM) + r")\+?\s+(?:[\w-]+\s+)?(branches|stores|shops|outlets|showrooms|"
                    r"factories|plants|production plants|warehouses|restaurants|clinics|locations|service cent(?:er|re)s)\b",
                    re.IGNORECASE)
_COUNT_SIGNAL = {"branches": "branches", "stores": "retail_stores", "shops": "retail_stores",
                 "outlets": "retail_stores", "showrooms": "showrooms", "factories": "factory", "plants": "factory",
                 "warehouses": "warehouse", "restaurants": "restaurants", "clinics": "clinics",
                 "locations": "multi_location", "service": "service_center"}
_SCHEMA_ACTIVITY = {"Restaurant": "hospitality", "FoodEstablishment": "hospitality", "Hotel": "hospitality",
                    "LodgingBusiness": "hospitality", "Store": "retail", "OnlineStore": "e_commerce",
                    "MedicalClinic": "healthcare", "Hospital": "healthcare", "MedicalOrganization": "healthcare",
                    "Dentist": "healthcare", "GeneralContractor": "construction",
                    "HomeAndConstructionBusiness": "construction", "ProfessionalService": "professional_services",
                    "LegalService": "professional_services", "AccountingService": "professional_services",
                    "Manufacturer": "manufacturing", "Wholesaler": "wholesale"}


def _signals(doc: Doc, page_type: str, orgs: list[dict]) -> list[Fact]:
    best: dict[tuple[str, str | None], Fact] = {}

    def add(fact: Fact) -> None:
        key = (fact.name, fact.value)
        if key not in best or best[key].confidence < fact.confidence:
            best[key] = fact

    for name in doc.technologies:
        add(Fact("signal", "technology", name, 90, f"{name} markers in the page source"))
    for org in orgs:
        for kind in _types(org):
            if activity := _SCHEMA_ACTIVITY.get(kind):
                add(Fact("signal", activity, None, 80, f"structured data type: {kind}"))
    if any(url.startswith(("https://wa.me", "https://api.whatsapp.com")) for url, _, _ in doc.links):
        add(Fact("signal", "customer_support", "WhatsApp", 85, "WhatsApp contact link on the website"))
    if page_type in ("careers", "news", "team"):
        return list(best.values())
    strong = page_type in ("about", "manufacturing", "services", "homepage")
    for text in doc.text(("body",)):
        for signal, pattern in _SIGNAL_RE.items():
            if (m := pattern.search(text)) and not _NEGATED.search(text[:m.start()]):
                add(Fact("signal", signal, None, 68 if strong else 58, _excerpt(text, m.start(), m.end())))
        for m in _COUNT.finditer(text):
            count = int(m[1]) if m[1].isdigit() else _NUM[m[1].lower()]
            signal = _COUNT_SIGNAL[m[2].lower().split()[-1] if not m[2].lower().startswith("service") else "service"]
            if 2 <= count <= 5000:
                add(Fact("signal", signal, str(count), 72, _excerpt(text, m.start(), m.end()),
                         {"count_field": f"{signal}_count"}))
    return list(best.values())


# ---- careers and news ------------------------------------------------------------------------------------------

_JOB_TITLE = re.compile(r"\b(engineer|developer|manager|officer|specialist|accountant|representative|technician|"
                        r"assistant|supervisor|coordinator|analyst|executive|operator|driver|cashier|chef|designer|"
                        r"administrator|agent|consultant|intern|merchandiser|pharmacist|nurse|storekeeper|"
                        r"controller|salesman|saleswoman|programmer)\b", re.IGNORECASE)
_DEPARTMENTS = [("it", r"developer|software|\bit\b|network|system|data|devops|helpdesk|programmer|web"),
                ("sales", r"sales|account manager|business development|merchandiser"),
                ("marketing", r"marketing|social media|brand|digital|content"),
                ("finance", r"accountant|finance|accounting|controller|treasury|audit"),
                ("hr", r"\bhr\b|human resources|recruit|talent"),
                ("customer_experience", r"customer (service|care|experience)|call cent|support agent"),
                ("procurement", r"procurement|purchasing|buyer"),
                ("supply_chain", r"logistics|supply chain|warehouse|storekeeper|driver"),
                ("manufacturing", r"production|technician|operator|quality|maintenance|plant"),
                ("operations", r"operations")]
_NEWS = [("news_new_branch", r"(new|open(s|ing)?|inaugurat\w*|launch\w*)\b.{0,25}\b(branch|store|showroom|outlet|"
                             r"restaurant)|افتتاح (فرع|معرض|متجر)"),
         ("news_new_factory", r"(new|open(s|ing)?|inaugurat\w*)\b.{0,25}\b(factory|plant|production line|facility)|"
                              r"افتتاح مصنع"),
         ("news_acquisition", r"\bacquir(es|ed|ition)\b|\bmerger\b|استحواذ"),
         ("news_partnership", r"\bpartner(s|ship|ed|ing)? with\b|\bpartnership\b|signs? (an )?agreement|شراكة"),
         ("news_new_market", r"\b(enters?|entering|expands? (in)?to|launch(es|ed)? in)\b.{0,30}\b(market|country)\b|"
                             r"\bnew markets?\b"),
         ("news_product_launch", r"\blaunch(es|ed|ing)?\b.{0,40}\b(product|range|line|collection)\b|new product"),
         ("news_expansion", r"\bexpan(d|ds|sion|ding)\b|توسع")]


def _careers(doc: Doc) -> list[Fact]:
    facts = [Fact("signal", "active_careers_page", None, 90, f"careers page: {doc.title or doc.url}"[:300])]
    postings = [i for i in _walk(doc.jsonld) if "JobPosting" in _types(i)]
    titles = [_str(p.get("title")) or "" for p in postings]
    confidence = 85
    if not titles:  # job-like headings / links on the careers page
        titles = list(dict.fromkeys(t for t in doc.headings("2345") + [x for _, x, a in doc.links if a == "body"]
                                    if len(t) <= 80 and _JOB_TITLE.search(t)))
        confidence = 60
    if titles:
        facts.append(Fact("signal", "job_openings", str(len(titles)), confidence,
                          ("Openings: " + "; ".join(titles[:8]))[:300]))
    for department, pattern in _DEPARTMENTS:
        if hits := [t for t in titles if re.search(pattern, t, re.IGNORECASE)]:
            facts.append(Fact("signal", "hiring_department", department, confidence - 5,
                              ("Openings: " + "; ".join(hits[:5]))[:300]))
    return facts


def _news(doc: Doc) -> list[Fact]:
    facts, seen = [], set()
    for text in doc.headings("1234") + [t for _, t, a in doc.links if a == "body"]:
        if len(text) > 200 or text in seen:
            continue
        seen.add(text)
        for signal, pattern in _NEWS:
            if re.search(pattern, text, re.IGNORECASE):
                facts.append(Fact("signal", signal, text[:300], 60, text[:300]))
                break
    return facts[:15]


def extract(doc: Doc, page_type: str, ctx: Context) -> list[Fact]:
    """All facts of one page. Team pages are stored for Step 5 (people) but nothing is extracted from them."""
    if page_type == "team":
        return []
    orgs = _organizations(doc, ctx)
    facts = (_profile(doc, page_type, ctx, orgs) + _contacts(doc, ctx, orgs) + _socials(doc, orgs)
             + _locations(doc, page_type, ctx, orgs) + _offerings(doc, page_type, ctx)
             + _signals(doc, page_type, orgs))
    if page_type == "careers":
        facts += _careers(doc)
    elif page_type == "news":
        facts += _news(doc)
    return facts
