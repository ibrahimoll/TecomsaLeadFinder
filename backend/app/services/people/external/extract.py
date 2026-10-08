"""People of ONE company in an external document: Step 5's extractor (cards, "Name - Title", sentences,
structured data) plus a strict company check, since an external page talks about many organisations.

A candidate is kept only when its own entry / sentence names this company (an alias, word for word):
    "Joseph Haddad — IT Director, ABC Foods"          yes
    "ABC Foods CEO Michel Haddad said..."              yes (news form, read here)
    "Michel Haddad discussed ABC Foods..."             no  (no role at the company is stated)
    "Group CIO, ABC Group" for company "ABC Foods"     no  (another entity; roles never cascade over a group)
    a speaker of another company on the same page     no
Short / common names also need the document to place it in the company's country.

Status from the evidence's date: within 18 months -> current; older or undated -> not confirmed (unknown);
explicit former stays former. The company's own pages keep Step 5's rules (they speak for the company).
"""

import re
from datetime import datetime, timedelta, timezone

from app.services.discovery.consolidation import name_tokens
from app.services.enrichment.extract import Context
from app.services.people import extract as people_extract
from app.services.people.candidate import PersonCandidate
from app.services.people.external.documents import Document
from app.services.people.external.sources import Kind
from app.services.people.titles import fold

RECENT = timedelta(days=548)  # ~18 months
_GROUP_WORDS = ("group", "holding", "holdings", "groupe", "global", "international", "worldwide", "regional")
_YEAR = re.compile(r"\b(20[0-3]\d)\b")


def _contains(text: str, alias: str) -> bool:
    return f" {fold(alias)} " in f" {fold(text)} "


def company_in(context: str, aliases: list[str], company_name: str) -> str | None:
    """The alias of this company that the person's own entry names, unless it names the company's GROUP / parent
    instead ('ABC Foods Group CEO' when the company is 'ABC Foods Lebanon' -> None)."""
    own_group = any(w in fold(company_name).split() for w in _GROUP_WORDS)
    for alias in aliases:
        if not _contains(context, alias):
            continue
        after = fold(context).split(fold(alias), 1)[1].split()[:1]
        if after and after[0] in _GROUP_WORDS and not own_group:
            return None  # "<alias> Group": the group, not this company
        return alias
    return None


def _status(c: PersonCandidate, published: datetime | None, context: str) -> str:
    if c.status == "former":
        return "former"
    now = datetime.now(timezone.utc)
    if published is None:
        years = [int(y) for y in _YEAR.findall(context) if int(y) <= now.year]
        published = datetime(max(years), 12, 31, tzinfo=timezone.utc) if years else None
    return "current" if published and now - published <= RECENT else "unknown"


def candidates(document: Document, kind: Kind, *, company, aliases: list[str], country: tuple[str | None, str | None],
               official: bool, stats) -> list[PersonCandidate]:
    ctx = Context(company.name, country[0], country[1], company.domain or "")
    text_all = " ".join(" ".join(b[1] for b in doc.blocks[:400]) for _, doc in document.pages)
    placed = any(_contains(text_all, p) for p in (country[1] or "Lebanon", "Liban", "لبنان",
                                                  company.headquarters_city or "Beirut"))
    page_type = "news" if kind.category == "publication" else "team"  # layout rules (cards, inline, sentences)
    found: list[PersonCandidate] = []
    for page_no, doc in document.pages:
        page = people_extract._Page(doc, page_type, ctx, document.source.id, document.source.url,
                                    document.row.retrieved_at or datetime.now(timezone.utc), 100 if official else 60)
        page.structured()
        page.blocks()
        _news_form(page, doc, aliases)
        for c in page.found.values():
            context = c.raw_metadata.get("context") or c.evidence_excerpt
            c.source_type, c.source_confidence = kind.category, kind.quality
            c.raw_metadata.update({"page": page_no, "category": kind.category, "document": document.row.title})
            if page_no:
                c.evidence_excerpt = f"Page {page_no}: {c.evidence_excerpt}"[:600]
            if official:  # the company's own pages / PDFs speak for it (Step 5 rules)...
                c.company_match_confidence = kind.quality
                if kind.category == "company_document":  # ...but a 2019 profile PDF is not today's management
                    c.status = _status(c, document.row.published_at,
                                       f"{context} {document.row.title or ''} {document.row.url}")
                found.append(c)
                continue
            alias = company_in(context, aliases, company.name)
            if alias is None:
                stats["rejected_company_not_named"] += 1
                continue
            if c.raw_title and fold(c.raw_title).split()[0] in ("group", "global", "regional", "groupe") and not any(
                    w in fold(company.name).split() for w in _GROUP_WORDS):
                stats["rejected_group_role"] += 1  # "Group CIO": a role at the group, not at this company
                continue
            single = len(name_tokens(alias)) < 2
            if single and not placed:
                stats["rejected_ambiguous_name"] += 1
                continue
            # "Sales Director, ABC Foods" -> "Sales Director": the company is known, the title is the role
            c.raw_title = re.sub(rf"\s*(?:,|-|–|—|\||@|\bat\b|\bof\b|\bchez\b)?\s*{re.escape(alias)}.*$", "",
                                 c.raw_title or "", flags=re.IGNORECASE).strip(" ,-–—|") or c.raw_title
            exact = _contains(context, company.name) or (company.legal_name and _contains(context, company.legal_name))
            c.company_match_confidence = (85 if exact else 78) - (8 if single else 0)
            c.status = _status(c, document.row.published_at, context)
            found.append(c)
    return found


def _news_form(page, doc, aliases: list[str]) -> None:
    """'ABC Foods CEO Michel Haddad said...', 'ABC Foods' Marketing Director, Sarah Khoury, ...'."""
    for _, text, area in doc.blocks:
        if area == "nav" or len(text) < 20:
            continue
        for alias in aliases:
            for m in re.finditer(rf"(?<!\w){re.escape(alias)}(?:['’]s)?\s+", text, re.IGNORECASE):
                after = " ".join(text[m.end():].replace(",", " ").split()[:9])
                if found := page._split_title_name(after):
                    name, title = found
                    page.add(name, title, text)
