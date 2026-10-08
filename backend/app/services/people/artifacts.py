"""Contact artifacts on the company's own site (Step 6.1): business cards (.vcf) and people documents (team /
management / staff / directory / company profile / brochure: PDF, Word, Excel, CSV) linked from its stored pages.

Each artifact is fetched once (robots-aware, paced, bounded: MAX_VCARDS + MAX_DOCUMENTS per site, re-checked after
ARTIFACT_DAYS), read into people + their published business contacts, and stored with the document as its source
(a person named in a document of the company's own site is the company's person only when the document says so:
its card's ORG / its rows' company is this company, or the document is the company's own team list).
"""

import hashlib
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.models import Company, CompanyWebPage
from app.services.discovery.fetch import FetchError
from app.services.enrichment.extract import Context, _related
from app.services.enrichment.pages import Doc
from app.services.people.external import documents, generic
from app.services.people.external.lebanon.records import candidate

logger = logging.getLogger("leadfinder.people.artifacts")
MAX_VCARDS, MAX_DOCUMENTS = 8, 3
ARTIFACT_DAYS = 60
_DOC_EXT = ("pdf", "docx", "xlsx", "xls", "csv")
_PEOPLE_DOC = re.compile(r"team|staff|management|leadership|directory|contacts?\b|profile|brochure|catalog|"
                         r"presentation|organi[sz]ation|annual[-_ ]?report|board|who[-_ ]we[-_ ]are|people|"
                         r"directors|executives", re.IGNORECASE)


def _ext(url: str) -> str:
    return urlsplit(url).path.lower().rsplit(".", 1)[-1] if "." in urlsplit(url).path else ""


def links(pages: list[CompanyWebPage], domain: str) -> tuple[list[str], list[str]]:
    """(.vcf links, people-document links) of the company's own site, best first, bounded."""
    vcards, docs = [], []
    for page in pages:
        for url, text, _area in (page.content or {}).get("links") or []:
            host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
            if host != domain and not host.endswith("." + domain):
                continue
            ext = _ext(url)
            if ext == "vcf" and url not in vcards:
                vcards.append(url)
            elif ext in _DOC_EXT and _PEOPLE_DOC.search(f"{url} {text}") and url not in docs:
                docs.append(url)
    return vcards[:MAX_VCARDS], docs[:MAX_DOCUMENTS]


def due(home: CompanyWebPage | None, now: datetime) -> bool:
    last = ((home.metadata_ or {}).get("artifacts_checked") if home else None)
    return last is None or datetime.fromisoformat(last) < now - timedelta(days=ARTIFACT_DAYS)


def run(db: Session, company: Company, pages: list[CompanyWebPage], ctx: Context, stats: Counter) -> list:
    """PersonCandidates read from the site's artifacts (the caller resolves and stores them)."""
    from app.services.enrichment.persistence import page_source
    from app.services.people.extract import extract

    now = datetime.now(timezone.utc)
    home = next((p for p in pages if p.page_type == "homepage"), None)
    if not company.domain or not due(home, now):
        return []
    vcards, docs = links(pages, company.domain)
    fetcher = documents.fetcher(pdf=True)
    found = []
    for url in vcards + docs:
        try:
            page = fetcher.get(url)
        except FetchError as exc:
            stats[f"artifact_{exc.kind.lower()}"] += 1
            continue
        if page.status >= 400:
            continue
        raw = page.raw or page.html.encode("utf-8")
        ext = _ext(url)
        source = page_source(db, company, url=page.url, digest=hashlib.sha256(raw).hexdigest(),
                             page_type="vcard" if ext == "vcf" else "document", title=url.rsplit("/", 1)[-1],
                             retrieved_at=now, quality=85)
        stats[f"artifact_{ext}"] += 1
        records = []
        if ext == "vcf":
            records = generic.vcard_records(raw.decode("utf-8", "replace"), default_company=company.name)
        elif ext in ("xlsx", "xls"):
            records = generic.rows_records(generic.xlsx_rows(raw), default_company=company.name)
        elif ext == "csv":
            records = generic.rows_records(generic.csv_rows(raw.decode("utf-8-sig", "replace")),
                                           default_company=company.name)
        else:  # PDF / Word: the website reader on the document's text, as the company's own page
            texts = [(n, t) for n, t in documents.pdf_pages(raw)[0]] if ext == "pdf" else [(1, generic.docx_text(raw))]
            kind = "team" if re.search(r"team|staff|management|leadership|board|directors|people", url, re.I) \
                else "about"
            for number, text in texts:
                doc: Doc = documents.pdf_doc(page.url, number, text, None)
                found += extract(doc, kind, ctx=ctx, source_id=source.id, url=page.url, observed_at=now,
                                 ownership=company.website_confidence)
            continue
        for record in records:
            if not record.person or not (record.org and _related(record.org[0], ctx)):
                continue  # the company's own card / list only (a dealer list names other companies' people)
            c = candidate(record, company_id=company.id, source_id=source.id, url=page.url,
                          source_type="company_document", quality=85, match_confidence=95, stated=now,
                          category="company_document", document=url.rsplit("/", 1)[-1])
            if c is not None:
                found.append(c)
    if home is not None:
        home.metadata_ = {**(home.metadata_ or {}), "artifacts_checked": now.isoformat()}
    db.commit()
    stats["artifact_people"] += len(found)
    return found
