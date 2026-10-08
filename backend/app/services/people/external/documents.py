"""External public documents: fetched once (same secure, robots-aware, rate-limited fetcher as company research),
cached in external_documents and shared by every company / person they mention.

    HTML  -> parsed page (pages.Doc), as for company websites
    PDF   -> native text per page (pypdf; no OCR), page numbers kept for the evidence

A document is a Source (type by category: conference, association, news, public_pdf...), so its people's
evidence points to it and the Sources tab explains every external person.
"""

import hashlib
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ExternalDocument, Source
from app.services.discovery.fetch import Fetcher, FetchError
from app.services.discovery.web import PoliteFetcher
from app.services.enrichment.pages import Doc, parse
from app.services.people.external.sources import Kind, blocked

logger = logging.getLogger("leadfinder.people.documents")

FRESH_DAYS = {"html": 30, "pdf": 90}
MAX_PDF_PAGES = 80
MAX_PDF_CHARS = 400_000
PDF_MAX_BYTES = 12_000_000


@lru_cache(maxsize=2)
def fetcher(pdf: bool) -> PoliteFetcher:
    """One per kind per process (robots.txt and per-host pacing shared across jobs). Replaced in tests."""
    s = get_settings()
    inner = Fetcher(max_bytes=PDF_MAX_BYTES, timeout=s.website_timeout_seconds * 2, accept_pdf=True) if pdf else \
        Fetcher(max_bytes=s.website_max_bytes, timeout=s.website_timeout_seconds, truncate=True)
    return PoliteFetcher(inner, min_interval=s.website_min_interval_seconds)


@dataclass
class Document:
    row: ExternalDocument
    pages: list[tuple[int | None, Doc]]  # (page number for PDFs, parsed text)
    source: Source
    cached: bool


def pdf_pages(raw: bytes, *, max_pages: int = MAX_PDF_PAGES, max_chars: int = MAX_PDF_CHARS
              ) -> tuple[list[tuple[int, str]], dict]:
    """Native text of each page, and the document's own metadata (title, creation date). A whole directory
    (ABL almanac, IDAL) is read with higher limits: it is parsed once, not per company."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw))
        meta = reader.metadata or {}
        pages, total = [], 0
        for number, page in enumerate(reader.pages[:max_pages], 1):
            text = page.extract_text() or ""
            total += len(text)
            pages.append((number, text))
            if total > max_chars:
                break
        return pages, {"title": str(meta.get("/Title") or "") or None, "created": str(meta.get("/CreationDate") or "")}
    except Exception as exc:  # an unreadable / encrypted PDF is a failed source, never a crash
        logger.info("PDF not readable: %s", exc.__class__.__name__)
        return [], {}


def pdf_doc(url: str, number: int, text: str, title: str | None) -> Doc:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return Doc(url=url, title=title, blocks=[["p", line, "body"] for line in lines if len(line) >= 2])


def _published(text: str | None) -> datetime | None:
    """2026-03-05 / 2026-03-05T10:00:00Z / D:20260305... -> date (the first plausible one)."""
    if not text:
        return None
    m = re.search(r"(19[89]\d|20\d{2})[-/]?(\d{2})[-/]?(\d{2})", str(text))
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
    except ValueError:
        return None


def _pages_of(row: ExternalDocument) -> list[tuple[int | None, Doc]]:
    content = row.content or {}
    if row.doc_type == "pdf":
        return [(n, pdf_doc(row.final_url or row.url, n, text, row.title)) for n, text in content.get("pages", [])]
    return [(None, Doc.from_json(content))] if content else []


def get(db: Session, url: str, kind: Kind, *, published_hint: str | None = None, stats=None,
        connector: str | None = None) -> Document | None:
    """The document, from the cache when fresh, else fetched (None: blocked, unreachable or empty)."""
    if blocked(url):  # defence in depth: filtering already happened before
        return None
    now = datetime.now(timezone.utc)
    row = db.scalar(select(ExternalDocument).where(ExternalDocument.url == url[:2000]))
    if row and row.fresh_until and row.fresh_until > now and row.source_id:
        if stats is not None:
            stats["documents_cached"] += 1
        return Document(row, _pages_of(row), db.get(Source, row.source_id), True) if row.content else None
    pdf_first = urlsplit(url).path.lower().endswith(".pdf")
    try:
        try:
            page = fetcher(pdf_first).get(url)
        except FetchError as exc:
            if exc.kind != "NOT_HTML" or pdf_first:
                raise
            page = fetcher(True).get(url)  # the address did not say .pdf
    except FetchError as exc:
        if stats is not None:
            stats[f"fetch_{exc.kind.lower()}"] += 1
        return None
    if stats is not None:
        stats["documents_fetched"] += 1
    if row is None:
        row = ExternalDocument(url=url[:2000], category=kind.category, doc_type="html")
        db.add(row)
    row.final_url, row.domain, row.http_status, row.retrieved_at = page.url[:2000], (
        urlsplit(page.url).hostname or "")[:253], page.status, now
    if page.status >= 400:
        row.content, row.fresh_until = None, now + timedelta(days=7)
        db.commit()
        return None
    if page.raw:
        pages, meta = pdf_pages(page.raw)
        row.doc_type, row.title = "pdf", (meta.get("title") or urlsplit(page.url).path.rsplit("/", 1)[-1])[:500]
        row.content = {"pages": pages}
        row.published_at = _published(meta.get("created")) or _published(published_hint)
        digest = hashlib.sha256(page.raw).hexdigest()
        if stats is not None:
            stats["pdfs_read"] += 1
    else:
        doc = parse(page.html, page.url)
        row.doc_type, row.title, row.content = "html", (doc.title or "")[:500] or None, doc.to_json()
        published = next((doc.meta[k] for k in ("article:published_time", "date", "dc.date", "pubdate",
                                                "og:updated_time", "article:modified_time") if doc.meta.get(k)), None)
        published = published or next((i.get("datePublished") for i in doc.jsonld if isinstance(i, dict)
                                       and i.get("datePublished")), None)
        row.published_at = _published(published) or _published(published_hint)
        digest = hashlib.sha256(page.html.encode("utf-8", "replace")).hexdigest()
    row.category, row.content_hash = kind.category, digest
    row.fresh_until = now + timedelta(days=FRESH_DAYS[row.doc_type])
    row.metadata_ = {"truncated": page.truncated, "redirects": page.redirects,
                     "pages": len(row.content.get("pages", [])) if row.doc_type == "pdf" else None}
    source = db.scalar(select(Source).where(Source.content_hash == digest, Source.url == page.url[:2000]).limit(1))
    if source is None:
        source = Source(source_type=kind.source_type, name=(row.title or row.domain or page.url)[:300],
                        url=page.url[:2000], publisher=row.domain, retrieved_at=now, published_at=row.published_at,
                        source_quality=kind.quality, content_hash=digest,
                        metadata_={"connector": connector, "category": kind.category, "tier": kind.tier,
                                   "doc_type": row.doc_type,
                                   "pages": row.metadata_["pages"]})
        db.add(source)
        db.flush()
    row.source_id = source.id
    db.commit()
    pages = _pages_of(row)
    return Document(row, pages, source, False) if pages else None
