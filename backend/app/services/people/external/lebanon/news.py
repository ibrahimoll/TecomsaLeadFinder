"""Business news about a company, from Lebanese publications' own article indexes (no search engine).

    refresh (pack): each publication's sitemaps -> a LOCAL index of article URLs + dates (fetched once, re-read only
                    when a sitemap changes)
    per company:    its distinctive names as URL slugs ("bank-audi", "massabki") matched locally against that index
                    -> at most MAX_ARTICLES newest matching articles fetched (cached, shared)
                    -> people stated FOR the company (the strict external extractor: the article must name it)
                    -> dated business events (signals with event_date: the company timeline), classified by rules

A slug match only selects what to read; an event is kept only when the article's own title / lead says it about
the company. Never a generic news product: only company intelligence.
"""

import re
from datetime import timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Company, CompanySignal
from app.services.discovery.geography import _fold
from app.services.people.external.lebanon.records import Record

MAX_ARTICLES = 4
MAX_AGE = timedelta(days=5 * 365)
_GENERIC_SLUGS = {"bank", "group", "company", "lebanon", "beirut", "hotel", "school", "insurance", "foods", "food",
                  "the", "store", "shop", "pharmacy", "hospital", "center", "centre", "college"}
# event type <- what the article says (title / lead sentence naming the company); first match wins
EVENTS = (
    ("acquisition", r"\b(acquires?|acquired|acquisition of|takes over|buys)\b"),
    ("funding", r"\b(raises?|raised|funding round|investment round|secures? (?:\$|usd|funding|investment))\b"),
    ("procurement_award", r"\b(wins?|won|awarded|secures?) (?:a |the )?(?:[\w$€£.,-]+ ){0,3}(contract|tender|deal)\b"),
    ("management_change", r"\b(appoints?|appointed|names? (?:new )?|new (?:ceo|chief executive|general manager|"
                          r"managing director|chairman|cfo|cto|cio|coo)|steps down|takes the helm)\b"),
    ("factory_opening", r"\b(opens?|opened|inaugurates?|inaugurated|launch(?:es|ed)?) (?:a |its |the )?(?:new )?"
                        r"(factory|plant|production line|production facility)\b"),
    ("warehouse_opening", r"\b(opens?|opened|inaugurates?|inaugurated) (?:a |its |the )?(?:new )?(warehouse|"
                          r"distribution cent(?:er|re)|logistics hub)\b"),
    ("branch_opening", r"\b(opens?|opened|inaugurates?|inaugurated|unveils?) (?:a |its |the )?(?:new |first |second |"
                       r"\w+ )?(branch|store|showroom|outlet|office|restaurant|hotel|clinic|location)\b"),
    ("distribution_agreement", r"\b(exclusive distribut\w*|distribution (?:agreement|deal|partnership))\b"),
    ("partnership", r"\b(partners? with|partnership|joins? forces|memorandum of understanding|mou|signs? "
                    r"(?:an? )?agreement)\b"),
    ("ecommerce_launch", r"\b(launch(?:es|ed)? (?:an? |its )?(?:new )?(online store|e-?commerce|app|delivery "
                         r"(?:app|service)|website))\b"),
    ("new_market", r"\b(expands? (?:to|into)|enters? the \w+ market|new market|opens? in (?:dubai|riyadh|"
                   r"cairo|abu dhabi|doha|paris|london|kuwait|erbil|baghdad|amman|cyprus|iraq|ksa|uae|qatar))\b"),
    ("new_product", r"\b(launch(?:es|ed)?|unveils?|introduces?) (?:a |its |the )?new\b"),
    ("expansion", r"\b(expands? (?:its|into|to|operations)|expansion (?:plan|of its|into|to)|doubles? (?:its )?"
                  r"capacity)\b"),
    ("hiring", r"\b(is hiring|recruit(?:s|ing|ment drive)|job fair|new jobs)\b"),
)
_EVENT_RE = [(kind, re.compile(pattern, re.IGNORECASE)) for kind, pattern in EVENTS]


def slugs(aliases: list[str]) -> list[str]:
    """Distinctive Latin names of the company as URL slugs ('Bank Audi' -> 'bank-audi'); never a generic word."""
    out = []
    for alias in aliases:
        words = [w for w in _fold(alias).split() if w.isascii() and w.isalnum()]
        if not words or all(w in _GENERIC_SLUGS for w in words) or (len(words) == 1 and len(words[0]) < 5):
            continue
        out.append("-".join(words))
    return list(dict.fromkeys(out))


def matching_articles(records: list[Record], aliases: list[str], now) -> list[Record]:
    """Index entries whose article slug contains a company slug as whole words, newest first."""
    wanted = slugs(aliases)
    if not wanted:
        return []
    found = []
    for r in records:
        url = r.excerpt
        if re.search(r"/(brand-voice|sponsored|partner-content|advertorial)/", url):
            continue  # paid content: a company's own advertising, not reporting
        slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
        if any(f"-{s}-" in f"-{slug}-" for s in wanted):
            found.append(r)
    from app.services.people.external.lebanon.records import published_date

    found = [r for r in found if (d := published_date(r.published)) is None or now - d <= MAX_AGE]
    return sorted(found, key=lambda r: r.published or "", reverse=True)[:MAX_ARTICLES]


def classify(text: str) -> str | None:
    return next((kind for kind, rx in _EVENT_RE if rx.search(text)), None)


def events(doc, aliases: list[str]) -> list[tuple[str, str]]:
    """(event type, statement): the title, or a lead sentence that names the company, saying what happened."""
    texts = [doc.title or ""] + [t for _, t, area in doc.blocks[:40] if area == "body" and len(t) > 40][:6]
    out = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if not any(f" {_fold(a)} " in f" {_fold(sentence)} " for a in aliases):
                continue
            if kind := classify(sentence):
                out.append((kind, sentence.strip()[:500]))
                break
        if out:
            break
    return out


def store_event(db: Session, company: Company, kind: str, statement: str, url: str, source_id: int, when,
                confidence: int) -> None:
    stmt = insert(CompanySignal).values(
        company_id=company.id, signal_type=kind, signal_value=url[:300], confidence=confidence, source_id=source_id,
        observed_at=when, event_date=when.date() if when else None, description=statement[:1000],
        detail={"url": url, "rule": kind})
    db.execute(stmt.on_conflict_do_nothing())


def sitemap(xml: str) -> list[Record]:
    """A publication's (post) sitemap: article URL + last modification date."""
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block)
        if loc:
            out.append(Record(org=[], excerpt=loc[1], published=(mod[1][:10] if mod else None)))
    return out
