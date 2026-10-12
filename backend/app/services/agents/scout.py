"""Scout agent: learns from the sales team's own decisions what a good lead looks like, scores every company, and
starts lookalike searches for the best pattern by itself.

* Labels come only from sales statuses people set: leads (qualified, follow-up, meeting, opportunity, working)
  versus non-leads (not interested, do not contact, archived). "new" and "contacted" teach nothing.
* Model: naive Bayes over simple features (industry, city, size, website/phone, words of the Profiler's brief),
  Laplace-smoothed, retrained on every pass. Small, explainable (each score carries its top reasons), no GPU.
  ponytail: naive Bayes over counts; a real classifier when there are thousands of labelled outcomes.
* Nothing is scored before scout_min_labels leads AND non-leads exist: no score is better than a made-up one.
* Feeds itself: at most scout_daily_searches a day, a Find Leads search for the industry + city that converts best,
  started as the first administrator and skipped when the same search ran in the last 14 days.
"""

import logging
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Company, LeadSearch, User

logger = logging.getLogger("leadfinder.agents")
LEAD = {"qualified", "follow_up", "meeting_scheduled", "opportunity", "working_odoo", "working_frinzo", "working_it"}
NOT_LEAD = {"not_interested", "do_not_contact", "archived"}
_STOP = frozenset("their which these those other about company companies services service products solutions with "
                  "from that this have provides offers based leading".split())
SEARCH_ACTION = "agent.scout_search"  # audit entry per search the Scout starts (its daily cap counts these)
_LABEL = {"industry": "Industry", "city": "City", "size": "Size", "word": "Mentions", "has": "Has"}


def features(c: Company) -> set[str]:
    out = {f"industry:{c.industry or 'unknown'}", f"city:{(c.headquarters_city or 'unknown').strip()}"}
    n = c.employee_count_estimate
    out.add("size:" + ("unknown" if n is None else "1-10" if n <= 10 else "11-50" if n <= 50 else "51-200"
                       if n <= 200 else "200+"))
    if c.website:
        out.add("has:a website")
    if c.primary_phone:
        out.add("has:a phone number")
    for word in re.findall(r"[a-z]{5,}", (c.brief or "").lower()):
        if word not in _STOP:
            out.add(f"word:{word}")
    return out


def learn(samples: list[tuple[set[str], bool]]) -> dict | None:
    """Naive Bayes weights from (features, is_lead) samples; None until there are enough of both kinds."""
    pos = sum(1 for _, lead in samples if lead)
    neg = len(samples) - pos
    if min(pos, neg) < get_settings().scout_min_labels:
        return None
    count_pos, count_neg = Counter(), Counter()
    for feats, lead in samples:
        (count_pos if lead else count_neg).update(feats)
    weights = {f: math.log((count_pos[f] + 1) / (pos + 2)) - math.log((count_neg[f] + 1) / (neg + 2))
               for f in set(count_pos) | set(count_neg)}
    return {"prior": math.log(pos / neg), "weights": weights, "leads": pos, "not_leads": neg,
            "seen": {f: (count_pos[f], count_pos[f] + count_neg[f]) for f in weights}}


def score(model: dict, feats: set[str]) -> tuple[int, list[str]]:
    """0-100 and the (up to 3) features that raise it most, in words."""
    known = [f for f in feats if f in model["weights"]]
    # Dampened: naive Bayes adds up correlated features (industry and its typical words) as if independent.
    z = model["prior"] + sum(model["weights"][f] for f in known) / math.sqrt(max(1, len(known)))
    top = sorted((f for f in known if model["weights"][f] > 0), key=lambda f: -model["weights"][f])[:3]
    reasons = []
    for f in top:
        kind, value = f.split(":", 1)
        won, total = model["seen"][f]
        reasons.append(f"{_LABEL[kind]} {value}: {won} of {total} similar companies became leads")
    return round(100 / (1 + math.exp(-z))), reasons


def run(db: Session) -> dict:
    """Retrains, rescores every company, and maybe starts a lookalike search. Commits."""
    companies = db.scalars(select(Company)).all()
    samples = [(features(c), c.status in LEAD) for c in companies if c.status in LEAD | NOT_LEAD]
    model = learn(samples)
    pos = sum(1 for _, lead in samples if lead)
    if model is None:
        db.execute(update(Company).where(Company.scout_score.is_not(None)).values(scout_score=None,
                                                                                  scout_reasons=None))
        db.commit()
        return {"trained": False, "leads": pos, "not_leads": len(samples) - pos}
    for c in companies:
        c.scout_score, c.scout_reasons = score(model, features(c))
    db.commit()
    started = lookalike_search(db, model, [c for c in companies if c.status in LEAD])
    logger.info("scout trained leads=%s not_leads=%s search=%s", model["leads"], model["not_leads"], started)
    return {"trained": True, "leads": model["leads"], "not_leads": model["not_leads"], "search_started": started}


def best_pattern(model: dict, leads: list[Company]) -> tuple[str, str | None, str] | None:
    """(industry, city, country) shared by the most leads whose industry the model rates positively."""
    combos = Counter((c.industry, c.headquarters_city, c.headquarters_country) for c in leads
                     if c.industry and c.industry != "Other" and c.headquarters_country
                     and model["weights"].get(f"industry:{c.industry}", 0) > 0)
    return combos.most_common(1)[0][0] if combos else None


def lookalike_search(db: Session, model: dict, leads: list[Company]) -> int | None:
    from app.schemas.lead_search import LeadSearchCreate
    from app.services import audit_service, search_service

    s = get_settings()
    since = datetime.now(timezone.utc) - timedelta(days=1)
    if s.scout_daily_searches <= 0 or db.scalar(text(
            "SELECT count(*) FROM audit_logs WHERE action = :a AND created_at > :since"),
            {"a": SEARCH_ACTION, "since": since}) >= s.scout_daily_searches:
        return None
    pattern = best_pattern(model, leads)
    admin = db.scalar(select(User).where(User.role == "ADMIN", User.is_active.is_(True)).order_by(User.id))
    if pattern is None or admin is None:
        return None
    industry, city, country = pattern
    recent = db.scalar(select(LeadSearch.id).where(
        LeadSearch.industry == industry, LeadSearch.country == country, LeadSearch.city.is_not_distinct_from(city),
        LeadSearch.created_at > datetime.now(timezone.utc) - timedelta(days=14)))
    if recent:
        return None
    search = search_service.create_search(db, admin, LeadSearchCreate(
        country=country, city=city, industry=industry, requested_count=s.scout_search_size))
    audit_service.record(db, action=SEARCH_ACTION, user_id=None, entity_type="lead_search", entity_id=search.id,
                         metadata={"why": f"{industry} in {city or country} converts best"})
    db.commit()
    return search.id


def stats(db: Session) -> dict:
    statuses = dict(db.execute(text("SELECT status, count(*) FROM companies GROUP BY 1")).all())
    scored = db.scalar(text("SELECT count(*) FROM companies WHERE scout_score IS NOT NULL"))
    searches = db.scalar(text("SELECT count(*) FROM audit_logs WHERE action = :a"), {"a": SEARCH_ACTION})
    return {"leads": sum(statuses.get(k, 0) for k in LEAD), "not_leads": sum(statuses.get(k, 0) for k in NOT_LEAD),
            "min_labels": get_settings().scout_min_labels, "scored": scored, "searches_started": searches}
