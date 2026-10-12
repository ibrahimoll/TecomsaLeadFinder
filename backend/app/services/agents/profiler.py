"""Profiler agent: a one-line brief and a short description of what each company does, written by the local model
from the company's own website pages (the ones company research already cached; nothing is fetched here).

* Only the page text is given to the model, and it is told to leave the brief empty when the pages do not say what
  the company does: no website text, no profile (never invented from the name).
* A company stuck in industry "Other" (or none) gets the industry the model picks from LeadFinder's own list.
* Re-profiled only when its pages are re-fetched later (profiled_at < newest page).
* Feeds itself: companies with a website that were never researched get research queued (low priority, a few per
  hour), so their pages are there to profile next time.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Company
from app.models.company import CompanyWebPage
from app.services.agents import llm
from app.services.enrichment.pages import Doc

logger = logging.getLogger("leadfinder.agents")
BACKGROUND = 90  # research priority: after anything a user asked for (enrichment OPENED 10 ... STALE 40)
PAGE_ORDER = {"homepage": 0, "about": 1, "products": 2, "services": 2}
MAX_CHARS = 5000

SYSTEM = (
    "You write company profiles for the sales team of TECOMSA, which sells Odoo ERP, the Frinzo app and IT "
    "services. Use ONLY the website text you are given. Write in English even if the website is in French or "
    "Arabic. brief: one sentence, at most 25 words, saying what the company does and for whom. description: 2 to "
    "4 factual sentences: main activity, products or services, customers or markets, locations if stated. "
    "offerings: up to 6 short product or service names. industry: the best match from the allowed list. If the "
    "text does not make clear what the company does, return an empty brief and description."
)


def page_text(db: Session, company_id: int) -> tuple[str, list[str]]:
    """The readable body text of the company's cached pages, homepage and about first; and the URLs read."""
    pages = db.scalars(select(CompanyWebPage).where(
        CompanyWebPage.company_id == company_id, CompanyWebPage.content.is_not(None),
        CompanyWebPage.http_status < 400, CompanyWebPage.page_type.in_(PAGE_ORDER))).all()
    pages.sort(key=lambda p: PAGE_ORDER[p.page_type])
    seen: set[str] = set()
    parts: list[str] = []
    urls: list[str] = []
    for page in pages:
        doc = Doc.from_json(page.content)
        lines = [doc.title or "", doc.meta.get("description", "")]
        lines += [t for _, t, area in doc.blocks if area == "body"]
        for line in (ln.strip() for ln in lines):
            if len(line) > 2 and line not in seen:
                seen.add(line)
                parts.append(line)
        urls.append(page.url)
        if sum(map(len, parts)) > MAX_CHARS:
            break
    return "\n".join(parts)[:MAX_CHARS], urls


def industries(db: Session) -> list[str]:
    """LeadFinder's industries in use (the model must pick one of these, so filters keep working)."""
    used = db.scalars(select(Company.industry).where(Company.industry.is_not(None), Company.industry != "Other")
                      .group_by(Company.industry).order_by(func.count().desc()).limit(60)).all()
    return sorted(used)


def clean(answer: dict | None, allowed: list[str]) -> dict | None:
    """The model's answer, validated; None when it has nothing usable."""
    if not isinstance(answer, dict):
        return None
    brief = " ".join(str(answer.get("brief") or "").split())[:300]
    description = " ".join(str(answer.get("description") or "").split())[:1500]
    if len(brief) < 15:
        return None
    offerings = [" ".join(str(o).split())[:60] for o in answer.get("offerings") or [] if str(o).strip()][:6]
    industry = answer.get("industry") if answer.get("industry") in allowed else None
    return {"brief": brief, "description": description or None, "offerings": offerings, "industry": industry}


def next_company(db: Session) -> Company | None:
    """A company with cached pages that has no profile yet, or whose pages were re-fetched since."""
    newest = (select(func.max(CompanyWebPage.retrieved_at)).where(
        CompanyWebPage.company_id == Company.id, CompanyWebPage.content.is_not(None),
        CompanyWebPage.http_status < 400).scalar_subquery())
    return db.scalar(select(Company).where(newest.is_not(None), (Company.profiled_at.is_(None))
                                           | (Company.profiled_at < newest))
                     .order_by(Company.profiled_at.is_not(None), Company.id).limit(1)
                     .with_for_update(skip_locked=True))


def profile(db: Session, company: Company) -> str:
    """Profiles one company and commits. Returns the outcome: profiled | no_text | unclear | model_down."""
    body, urls = page_text(db, company.id)
    now = datetime.now(timezone.utc)
    if len(body) < 80:
        outcome, result = "no_text", None
    else:
        allowed = industries(db)
        schema = {"type": "object", "required": ["brief", "description", "offerings", "industry"], "properties": {
            "brief": {"type": "string"}, "description": {"type": "string"},
            "offerings": {"type": "array", "items": {"type": "string"}},
            "industry": {"type": "string", "enum": allowed or ["Other"]}}}
        answer = llm.chat_json(SYSTEM, f"Company: {company.name}\nAllowed industries: {', '.join(allowed)}\n\n"
                                       f"Website text:\n{body}", schema)
        if answer is None:
            db.rollback()
            return "model_down"  # not marked: retried when the model is back
        result = clean(answer, allowed)
        outcome = "profiled" if result else "unclear"
    meta = {"outcome": outcome, "model": get_settings().ollama_model, "pages": urls}
    if result:
        company.brief, company.profile = result["brief"], result["description"]
        meta["offerings"] = result["offerings"]
        if result["industry"] and company.industry in (None, "Other"):
            meta["industry_from"] = company.industry
            company.industry = result["industry"]
    company.profiled_at, company.profile_meta = now, meta
    db.commit()
    logger.info("profiler company=%s outcome=%s", company.id, outcome)
    return outcome


def feed(db: Session) -> int:
    """Queues research for a few never-researched companies with a website, so they can be profiled later."""
    from app.services.enrichment import orchestrator as enrichment

    todo = db.scalars(select(Company).where(Company.website.is_not(None), Company.enrichment_status == "not_started")
                      .order_by(Company.scout_score.desc().nulls_last(), Company.id)
                      .limit(get_settings().profiler_enrich_per_hour)).all()
    queued = sum(enrichment.request(db, c, BACKGROUND) for c in todo)
    db.commit()
    return queued


def stats(db: Session) -> dict:
    row = db.execute(text(
        "SELECT count(*) FILTER (WHERE brief IS NOT NULL), "
        " count(*) FILTER (WHERE profiled_at IS NOT NULL AND brief IS NULL), "
        " count(*) FILTER (WHERE profiled_at IS NULL AND EXISTS (SELECT 1 FROM company_web_pages p "
        "   WHERE p.company_id = companies.id AND p.content IS NOT NULL AND p.http_status < 400)), "
        " count(*) FILTER (WHERE website IS NOT NULL AND enrichment_status = 'not_started'), "
        " count(*) FILTER (WHERE profile_meta ? 'industry_from'), max(profiled_at) "
        "FROM companies")).one()
    return {"profiled": row[0], "unclear": row[1], "waiting": row[2], "to_research": row[3],
            "industries_fixed": row[4], "last_run_at": row[5]}
