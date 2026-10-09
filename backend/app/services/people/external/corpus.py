"""LeadFinder's local source index: every public document it has read (directories, PDFs, archived pages, news),
searchable with PostgreSQL full-text search ('simple' configuration: names and Arabic / French text kept as written).

    index(db, row)          (re)computes a document's search vector from its stored content
    search(db, "Head of HR") documents that mention it, best first, with a highlighted excerpt

Searching the corpus never fetches anything: it is LeadFinder's own accumulated data.
"""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import ExternalDocument

MAX_CHARS = 1_000_000  # PostgreSQL tsvector limit is 1 MB; directories are indexed by their records' text


def document_text(row: ExternalDocument) -> str:
    content = row.content or {}
    parts = [row.title or ""]
    if "records" in content:
        for r in content["records"]:
            parts += [" ".join(r.get("org") or []), r.get("person") or "", r.get("title") or "", r.get("excerpt") or "",
                      r.get("bio") or ""]
    elif "pages" in content:
        parts += [t for _, t in content["pages"]]
    else:
        parts += [b[1] for b in content.get("blocks") or [] if len(b) > 1]
    return " ".join(p for p in parts if p)[:MAX_CHARS]


def index(db: Session, row: ExternalDocument) -> None:
    db.execute(text("UPDATE external_documents SET search_vector = to_tsvector('simple', :t) WHERE id = :id"),
               {"t": document_text(row), "id": row.id})


def search(db: Session, query: str, *, limit: int = 20) -> list[dict]:
    q = func.websearch_to_tsquery("simple", query)
    rows = db.execute(select(ExternalDocument.id, ExternalDocument.url, ExternalDocument.title,
                             ExternalDocument.category, func.ts_rank(ExternalDocument.search_vector, q).label("rank"))
                      .where(ExternalDocument.search_vector.op("@@")(q))
                      .order_by(text("rank DESC")).limit(limit)).all()
    return [{"id": r.id, "url": r.url, "title": r.title, "category": r.category, "rank": round(r.rank, 4)}
            for r in rows]

