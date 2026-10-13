"""Sales pitch (Opportunity, step 2): on a click, Claude writes why the company needs an Odoo / Frinzo / IT offer,
the points to make, a call opener, a first WhatsApp message and the likely objections with answers - from what
LeadFinder already stores (the rules-based fit and its evidence, the company's description, industry, signals,
people's names and titles). Contact details are never sent. The pitch is saved per company and solution
(opportunity_analysis) and reused for PITCH_CACHE_DAYS, so opening it again costs nothing.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError, BusinessRuleError
from app.models import CompanySignal, OpportunityAnalysis, User
from app.services import audit_service, opportunity

logger = logging.getLogger("leadfinder.pitch")
# TECOMSA's own product briefs (sales team, 2026-10): what each solves, who buys it, the signs, who decides, bad fit.
PRODUCTS = {
    "odoo": (
        "Odoo ERP, implemented by TECOMSA: sales, purchasing, inventory, accounting, manufacturing, HR, projects and "
        "operations in one system. Solves: companies running these across Excel, disconnected software or an "
        "outdated ERP. Ideal: manufacturers, distributors, wholesalers, retailers, service and construction "
        "companies, multi-branch businesses, about 20-500+ employees. Signs: several warehouses or branches, "
        "growing volume, manual reporting, duplicate data entry, weak stock visibility, many Excel files, "
        "disconnected departments, an old ERP. Decides: owner / CEO / GM / CFO / finance, IT or operations manager. "
        "Bad fit: very small simple businesses, basic invoicing only, highly specialised core systems, no budget or "
        "process commitment."),
    "frinzo": (
        "Frinzo (frinzo.com): the official WhatsApp Business API plus Instagram messaging - shared inbox for many "
        "agents, automation and AI customer service, campaigns, appointment / order flows, OTPs and notifications, "
        "reporting, CRM / ERP / e-commerce integration. Solves: many customer messages handled manually on "
        "individual phones, slow replies, no automation or reporting. Ideal: retail, restaurants, automotive, "
        "hospitals and clinics, e-commerce, delivery, education, real estate, travel, hospitality, financial "
        "services, customer-service-heavy companies with 20+ employees or high message volume. Decides: CEO / GM, "
        "marketing, customer service, call center, e-commerce, IT or digital transformation manager. Bad fit: few "
        "customer messages, one person handling customers, unwilling to use the official WhatsApp Business API."),
    "it": (
        "TECOMSA IT services: networks and Wi-Fi, servers and cloud, cybersecurity, CCTV, telephony / PBX, "
        "connectivity, installation, modernisation, integration and ongoing support. Ideal: offices, hospitals, "
        "hotels, schools, factories, warehouses, retail chains, malls, corporate groups, multi-site organisations, "
        "about 20-1,000+ employees. Signs: new office or branch, poor Wi-Fi, old network equipment, server problems, "
        "downtime, expanding CCTV, moving to cloud, replacing the PBX, no internal IT team. Decides: IT manager / CTO "
        "/ CIO / infrastructure, GM, operations or procurement manager, owner. Bad fit: tiny offices needing consumer "
        "equipment, lowest-price hardware buyers with no interest in support, everything locked with another "
        "provider long-term."),
}
SYSTEM = (
    "You write sales pitches for TECOMSA, a Lebanese company selling Odoo ERP, Frinzo and IT solutions to "
    "Lebanese businesses. Use only the facts given about the company; never invent numbers, clients, systems or "
    "people. Where a fact is missing, keep the point general rather than guessing. Write in English, plainly, "
    "the way a Lebanese salesperson talks to a business owner: short sentences, no hype."
)


class Objection(BaseModel):
    objection: str
    answer: str


class Pitch(BaseModel):
    why: str = Field(description="2-3 sentences: why this company needs the product, from the facts given")
    points: list[str] = Field(description="3-5 short pitch points tied to the company's own situation")
    opener: str = Field(description="The first two sentences to say on a cold call to the person to ask for")
    whatsapp: str = Field(description="A first WhatsApp message, under 60 words, polite, ends with a question")
    objections: list[Objection] = Field(description="The 2-3 most likely objections, each with a short answer")


class PitchError(AppError):
    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(detail)
        self.detail, self.status_code = detail, status_code


def configured() -> bool:
    return bool(get_settings().anthropic_api_key and get_settings().anthropic_api_key.get_secret_value())


def _client():  # tests replace this
    import anthropic

    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key.get_secret_value())


def latest(db: Session, company_id: int, solution: str) -> OpportunityAnalysis | None:
    return db.scalar(select(OpportunityAnalysis).where(
        OpportunityAnalysis.company_id == company_id, OpportunityAnalysis.solution == solution)
        .order_by(OpportunityAnalysis.generated_at.desc(), OpportunityAnalysis.id.desc()).limit(1))


def view(row: OpportunityAnalysis | None) -> dict | None:
    if row is None or not (row.reasoning or {}).get("opener"):
        return None
    r = row.reasoning
    return {"solution": row.solution, "why": row.summary, "points": row.recommended_modules_or_services or [],
            "opener": r.get("opener"), "whatsapp": r.get("whatsapp"), "objections": r.get("objections") or [],
            "generated_at": row.generated_at, "fresh": bool(row.expires_at and row.expires_at > datetime.now(
                timezone.utc))}


def _facts(company, fit: dict, signals: list[dict], people: list[dict]) -> str:
    lines = [f"Company: {company.name}",
             f"Industry: {', '.join(filter(None, (company.industry, company.sub_industry))) or 'unknown'}",
             f"Location: {', '.join(filter(None, (company.headquarters_city, company.headquarters_country))) or 'Lebanon'}"]
    if company.brief or company.description:
        lines.append(f"What it does: {company.brief or ''} {company.description or ''}".strip())
    if company.employee_count_max or company.employee_count_estimate:
        lines.append(f"Employees: about {company.employee_count_estimate or company.employee_count_max}")
    lines.append(f"LeadFinder's fit for this product: {fit['fit_level']} ({fit['points']} points)")
    lines += [f"- {r['why']} (evidence: {r['evidence']})" for r in fit["reasons"]]
    if fit["pitch"]:
        lines.append(f"Modules / services that match: {'; '.join(fit['pitch'])}")
    if fit.get("note"):
        lines.append(f"Note: {fit['note']}")
    other = sorted({f"{s['signal_type'].replace('_', ' ')}{': ' + str(s['signal_value']) if s.get('signal_value') else ''}"
                    for s in signals})[:25]
    if other:
        lines.append(f"Other facts from the website: {', '.join(other)}")
    who = [f"{p['name']} ({p['title']})" for p in fit["people"]]
    lines.append(f"Person to ask for: {', '.join(who) if who else ' or '.join(fit['call'])}")
    return "\n".join(lines)


def write(db: Session, user: User, company, solution: str, people: list[dict], *, refresh: bool = False) -> dict:
    """The saved pitch when it is still fresh (free), else a new one from Claude (paid, about a few cents)."""
    if solution not in PRODUCTS:
        raise BusinessRuleError("solution must be odoo, frinzo or it")
    current = view(latest(db, company.id, solution))
    if current and current["fresh"] and not refresh:
        return current
    if not configured():
        raise BusinessRuleError("Claude is not configured (ANTHROPIC_API_KEY)")
    s = get_settings()
    signals = [{"signal_type": t, "signal_value": v} for t, v in db.execute(
        select(CompanySignal.signal_type, CompanySignal.signal_value).where(CompanySignal.company_id == company.id))]
    fit = next(f for f in opportunity.analyse(company, signals, people) if f["solution"] == solution)
    prompt = (f"Product: {PRODUCTS[solution]}\n\nWhat LeadFinder knows about the company:\n"
              f"{_facts(company, fit, signals, people)}\n\nWrite the pitch for this product to this company.")
    schema = Pitch.model_json_schema()
    import anthropic

    try:
        response = _client().beta.messages.create(
            model=s.pitch_model, max_tokens=16000, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": s.pitch_effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    except anthropic.AuthenticationError:
        raise PitchError("Claude refused the API key (check ANTHROPIC_API_KEY)") from None
    except anthropic.RateLimitError:
        raise PitchError("Claude is busy (rate limit): try again in a minute", 429) from None
    except anthropic.APIStatusError as exc:
        raise PitchError(f"Claude error {exc.status_code}: {exc.message}"[:300]) from None
    except anthropic.APIConnectionError:
        raise PitchError("Claude could not be reached (network)") from None
    if response.stop_reason == "refusal":
        raise PitchError("Claude declined to write this pitch", 422)
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    try:
        pitch = Pitch.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError):
        logger.warning("pitch for company %s: unreadable answer (stop=%s)", company.id, response.stop_reason)
        raise PitchError("Claude's answer could not be read: try again") from None
    now = datetime.now(timezone.utc)
    row = OpportunityAnalysis(
        company_id=company.id, solution=solution, fit_level=fit["fit_level"], summary=pitch.why,
        reasoning={"opener": pitch.opener, "whatsapp": pitch.whatsapp,
                   "objections": [o.model_dump() for o in pitch.objections], "model": s.pitch_model,
                   "usage": {"input": response.usage.input_tokens, "output": response.usage.output_tokens}},
        signals=fit["reasons"], recommended_modules_or_services=pitch.points,
        recommended_person_ids=[p["id"] for p in fit["people"]], generated_at=now,
        expires_at=now + timedelta(days=s.pitch_cache_days))
    db.add(row)
    audit_service.record(db, action="company.pitch_written", user_id=user.id, entity_type="company",
                         entity_id=company.id, metadata={"solution": solution, "model": s.pitch_model,
                                                         "input_tokens": response.usage.input_tokens,
                                                         "output_tokens": response.usage.output_tokens})
    db.commit()
    return view(row)
