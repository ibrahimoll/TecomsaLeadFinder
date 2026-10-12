"""Lusha (paid): on a company's People tab, a free-text search of the people Lusha has there ("IT manager", "CFO",
"marketing") and one person's email or phone revealed, each on a user's confirmed click. Never in bulk, never
automatic, never from background research (nothing else imports this module).

Lusha API V3 (https://docs.lusha.com/apis/openapi; header `api_key`, base https://api.lusha.com):
    POST /v3/contacts/prospecting   filters.contacts.include (jobTitles | departments | seniorityIds,
                                    existingDataPoints) + companies.include (domains, else names): names / titles
                                    only, no email or phone; billed per result (api_search). Each result says what
                                    it `has` and `canReveal` [{field: emails | phones, credits}] (0 = already
                                    revealed for the account: free)
    POST /v3/contacts/enrich        {ids, reveal: ["emails"] | ["phones"], waterfallEnabled: false}: billed per
                                    revealed field (billing.creditsCharged); the waterfall (third-party providers,
                                    extra credits, async jobs) is turned off so the cost stays the one shown
    GET  /v3/contacts/prospecting/filters/{departments | seniority | existingDataPoints}: valid filter values
    GET  /v3/account/usage          credits {total, used, remaining}; free, 5 requests / minute (cached 60 s here)
    errors: 401 bad key, 402 out of credits, 403 inactive account / plan or V3 access lacking, 429 rate limit,
            451 legal (GDPR) block

Every paid call is a row of `lusha_requests`, written BEFORE the call (status pending, the estimated credits)
under an advisory lock that also checks LUSHA_MONTHLY_CREDIT_BUDGET: a double click / second tab hits the
partial unique index and pays nothing; a reveal already done is answered from the ledger at no cost; then the
row gets Lusha's own credit count. Revealed data is saved through contributions (channel LUSHA, provenance
'lusha', visible to the organization: TECOMSA paid for it) and kept by retention (privacy.PROTECTED).
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError, BusinessRuleError, ConflictError, NotFoundError
from app.models import Company, CompanyPerson, LushaRequest, Person, Phone, User
from app.services import audit_service, privacy
from app.services.contact_intelligence import classify_phone
from app.services.people.names import name_key

logger = logging.getLogger("leadfinder.lusha")
_LOCK = 7_301_951  # pg advisory lock: one budget check + ledger insert at a time
FIELDS = {"email": "emails", "phone": "phones"}
DEFAULT_CREDITS = {"email": 1, "phone": 5}  # Lusha's documented per-data-point cost, when a result does not say
SEARCH_BLOCK = 25  # contactSearch: 1 credit per block of up to 25 people found (GET /v3/account/usage pricing)


def search_estimate() -> int:
    """The most one page of a people search costs: 1 credit per started block of 25 results."""
    return -(-get_settings().lusha_search_size // SEARCH_BLOCK)
STALE_MINUTES = 10  # a pending row older than this was interrupted: it no longer blocks a retry
_ERRORS = {401: (502, "Lusha refused the API key (check LUSHA_API_KEY)"),
           402: (402, "The Lusha account is out of credits"),
           403: (502, "The Lusha plan does not allow this (inactive account, or no API / V3 access)"),
           429: (429, "Lusha's rate limit was reached: try again in a minute"),
           451: (451, "Lusha cannot return this person's data for legal reasons (GDPR)")}
_usage_cache: list = [0.0, None]  # [fetched at (monotonic), account usage]


class LushaError(AppError):
    status_code = 502


def configured() -> bool:
    key = get_settings().lusha_api_key
    return bool(key and key.get_secret_value().strip())


def _client() -> httpx.Client:  # tests replace this with a mock transport
    s = get_settings()
    return httpx.Client(base_url=s.lusha_base_url, timeout=s.lusha_timeout_seconds,
                        headers={"api_key": s.lusha_api_key.get_secret_value().strip()})


def _call(method: str, path: str, json: dict | None = None) -> dict:
    if not configured():
        raise BusinessRuleError("Lusha is not configured (LUSHA_API_KEY)")
    try:
        with _client() as client:
            r = client.request(method, path, json=json)
    except httpx.HTTPError as exc:
        raise LushaError(f"Lusha could not be reached ({type(exc).__name__})") from exc
    if r.status_code >= 400:
        status, message = _ERRORS.get(r.status_code, (502, f"Lusha answered HTTP {r.status_code}"))
        logger.warning("lusha %s %s: HTTP %s", method, path, r.status_code)  # never the key, never the body
        error = LushaError(message)
        error.status_code = status
        raise error
    return r.json()


# ---- ledger --------------------------------------------------------------------------------------------------------


def _month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(db: Session) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(LushaRequest.credits), 0))
                         .where(LushaRequest.created_at >= _month_start())) or 0)


def _reserve(db: Session, user: User, company_id: int, action: str, estimate: int,
             contact_id: str | None = None, search_key: str | None = None, params: dict | None = None) -> LushaRequest:
    """The ledger row, written before Lusha is called: budget checked under the lock, one live request per contact
    and field (or per search key)."""
    db.execute(select(func.pg_advisory_xact_lock(_LOCK)))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)
    for stale in db.scalars(select(LushaRequest).where(LushaRequest.status == "pending",
                                                       LushaRequest.created_at < cutoff)):
        stale.status, stale.error = "failed", "interrupted (credits kept as estimated)"
    db.flush()
    budget = get_settings().lusha_monthly_credit_budget
    if budget > 0 and spent_this_month(db) + estimate > budget:
        db.rollback()
        raise BusinessRuleError(f"This would pass LeadFinder's monthly Lusha budget ({budget} credits): "
                                "ask an admin to raise LUSHA_MONTHLY_CREDIT_BUDGET")
    row = LushaRequest(company_id=company_id, user_id=user.id, action=action, lusha_contact_id=contact_id,
                       search_key=search_key, params=params, status="pending", credits=estimate)
    db.add(row)
    try:
        db.commit()  # also releases the lock
    except IntegrityError:
        db.rollback()
        raise ConflictError("This Lusha request is already running (another click or tab): nothing was spent "
                            "twice") from None
    return row


def _fail(db: Session, row: LushaRequest, user: User, exc: LushaError) -> None:
    row.status, row.error, row.credits = "failed", exc.detail[:300], 0  # Lusha bills no error
    audit_service.record(db, action=f"lusha.{row.action}_failed", user_id=user.id, entity_type="company",
                         entity_id=row.company_id, metadata={"request_id": row.id, "error": exc.detail[:300]})
    db.commit()


# ---- people at a company -------------------------------------------------------------------------------------------

# Typed words that name a Lusha department / seniority under another name (matched against Lusha's own value lists).
ALIASES = {"it": "information technology", "tech": "information technology", "hr": "human resources",
           "ops": "operations", "bd": "business development", "c level": "c-suite", "c-level": "c-suite",
           "vp": "vice president"}
_values_cache: dict = {}  # filter type -> (fetched at (monotonic), values)


def _fold(text: str | None) -> str:
    return " ".join((text or "").lower().replace("&", " and ").split())


def _name(value) -> str:
    return str(value.get("name") or "") if isinstance(value, dict) else str(value)


def _filter_values(kind: str) -> list:
    """Lusha's valid values for a contact filter (GET /v3/contacts/prospecting/filters/{kind}: departments, seniority
    [{id, name}], existingDataPoints; the docs bill only prospecting itself). Cached a day; [] when unavailable."""
    hit = _values_cache.get(kind)
    if hit and time.monotonic() - hit[0] < 86_400:
        return hit[1]
    try:
        values = _call("GET", f"/v3/contacts/prospecting/filters/{kind}").get("values") or []
    except AppError:
        return []  # not cached: asked again next time
    _values_cache[kind] = (time.monotonic(), values)
    return values


def contact_filters(query: str, *, has_phone: bool = False) -> dict:
    """The typed words -> Lusha contact filters. Words that ARE a Lusha department ("IT", "finance", "marketing") or
    seniority ("director", "manager", "c-level") use that filter: the whole department, more than the titles
    containing the word. Anything else ("IT manager", "CFO", "head of sales") is a job title. Lusha ANDs filter
    types, so a query is never both."""
    q = _fold(query)
    wanted = {q, ALIASES.get(q, q)}
    include: dict = {}
    if q:
        dept = next((_name(v) for v in _filter_values("departments") if _fold(_name(v)) in wanted), None)
        level = None if dept else next((v for v in _filter_values("seniority")
                                        if isinstance(v, dict) and v.get("id") is not None
                                        and _fold(_name(v)) in wanted), None)
        if dept:
            include["departments"] = [dept]
        elif level:
            include["seniorityIds"] = [int(level["id"])]
        else:
            include["jobTitles"] = [" ".join(query.split())[:200]]
    if has_phone:
        points = [_name(v) for v in _filter_values("existingDataPoints") if "phone" in _name(v)] or ["phone"]
        include |= {"existingDataPoints": points, "existingDataPointsCondition": "or"}
    return include


def search_key(company_id: int, query: str, has_phone: bool, page: int) -> str:
    return f"{company_id}|{_fold(query)}|{int(has_phone)}|{page}"[:300]


def _cached(db: Session, key: str) -> LushaRequest | None:
    return db.scalar(select(LushaRequest).where(LushaRequest.search_key == key, LushaRequest.action == "search",
                                                LushaRequest.status == "done")
                     .order_by(LushaRequest.created_at.desc(), LushaRequest.id.desc()).limit(1))


def _fresh(row: LushaRequest | None) -> bool:
    days = get_settings().lusha_search_cache_days
    return bool(row and row.created_at > datetime.now(timezone.utc) - timedelta(days=days))


def mask_email(domain: str | None) -> str:
    return f"***@{domain.removeprefix('www.')}" if domain else "***"  # Lusha's preview gives no address to mask


def _preview(item: dict) -> dict:
    title = item.get("jobTitle") or {}
    reveal = {c.get("field"): c.get("credits") for c in item.get("canReveal") or [] if c.get("field")}
    return {"id": str(item.get("id")), "name": " ".join(filter(None, (item.get("firstName"), item.get("lastName")))),
            "title": title.get("title"), "departments": title.get("departments") or [],
            "seniority": title.get("seniority"), "linkedin": (item.get("socialLinks") or {}).get("linkedin"),
            "has": item.get("has") or [], "email_credits": reveal.get("emails"), "phone_credits": reveal.get("phones"),
            "domain": (item.get("company") or {}).get("domain")}


def _view(db: Session, company_id: int, row: LushaRequest | None) -> dict:
    """A search's people (never calls Lusha): masked, with what can be revealed, what was revealed already (shown in
    clear: the organization paid for it) and the LeadFinder person of the same name."""
    s = get_settings()
    params = (row.params or {}) if row else {}
    total, page = params.get("total"), params.get("page", 0)
    out = {"configured": configured(), "searched_at": row.created_at if row else None, "fresh": _fresh(row),
           "search_credits_estimate": search_estimate(), "page": page, "total": total,
           "has_more": bool(total and total > (page + 1) * s.lusha_search_size), "people": []}
    if row is None:
        return out
    items = row.result or []
    done = {(r.lusha_contact_id, r.action): r for r in db.scalars(select(LushaRequest).where(
        LushaRequest.lusha_contact_id.in_([i["id"] for i in items] or [""]),
        LushaRequest.status.in_(("done", "not_found"))))}
    known = {}
    for pid, full_name in db.execute(select(Person.id, Person.full_name).join(CompanyPerson).where(
            CompanyPerson.company_id == company_id)):
        known.setdefault(tuple(name_key(full_name)), pid)
    numbered = set(db.scalars(select(Phone.person_id).where(Phone.person_id.in_(set(known.values()) or {0}),
                                                            Phone.status != "invalid")))
    for i in items:
        email, phone = done.get((i["id"], "email")), done.get((i["id"], "phone"))
        has_email = i["email_credits"] is not None or "emails" in i["has"]
        has_phone = i["phone_credits"] is not None or "phones" in i["has"]
        out["people"].append({
            **{k: i[k] for k in ("id", "name", "title", "departments", "seniority", "linkedin")},
            "has_email": has_email, "has_phone": has_phone,
            "email_credits": DEFAULT_CREDITS["email"] if i["email_credits"] is None else i["email_credits"],
            "phone_credits": DEFAULT_CREDITS["phone"] if i["phone_credits"] is None else i["phone_credits"],
            "masked_email": mask_email(i.get("domain")) if has_email else None,
            "masked_phone": "***" if has_phone else None,  # the country is not known before the reveal
            "emails": (email.result or {}).get("emails") if email else None,
            "phones": (phone.result or {}).get("phones") if phone else None,
            "person_id": (pid := known.get(tuple(name_key(i["name"]))) if name_key(i["name"]) else None),
            "leadfinder_has_phone": pid in numbered})  # no paid reveal: LeadFinder already has a number
    return out


def results(db: Session, company, query: str = "", has_phone: bool = False, page: int = 0) -> dict:
    """The cached result of this search at the company (words + toggle + page); never calls Lusha."""
    return _view(db, company.id, _cached(db, search_key(company.id, query, has_phone, page)))


def search(db: Session, user: User, company, query: str = "", has_phone: bool = False, page: int = 0) -> dict:
    """Paid (per result): Lusha's people at the company for the typed words ("" = everyone). The same search younger
    than LUSHA_SEARCH_CACHE_DAYS is reused at no cost; each further page is its own (confirmed) search."""
    if not configured():
        raise BusinessRuleError("Lusha is not configured (LUSHA_API_KEY)")
    key = search_key(company.id, query, has_phone, page)
    current = _cached(db, key)
    if _fresh(current):
        return _view(db, company.id, current)
    s = get_settings()
    include = contact_filters(query, has_phone=has_phone)
    filters = {"contacts": {"include": include}} if include else {}
    filters["companies"] = {"include": {"domains": [company.domain]} if company.domain else {"names": [company.name]}}
    params = {"query": " ".join(query.split()), "has_phone": has_phone, "page": page, "filters": filters}
    row = _reserve(db, user, company.id, "search", search_estimate(), search_key=key, params=params)
    try:
        data = _call("POST", "/v3/contacts/prospecting", {"pagination": {"page": page, "size": s.lusha_search_size},
                                                          "filters": filters})
    except LushaError as exc:
        _fail(db, row, user, exc)
        raise
    found = [_preview(i) for i in data.get("results") or [] if i.get("id") and not i.get("error")]
    billed = (data.get("billing") or {}).get("creditsCharged")
    row.status, row.result, row.credits = "done", found, len(found) if billed is None else int(billed)
    row.params = {**params, "total": (data.get("pagination") or {}).get("total")}
    audit_service.record(db, action="lusha.search", user_id=user.id, entity_type="company", entity_id=company.id,
                         metadata={"request_id": row.id, "people": len(found), "credits": row.credits,
                                   "query": params["query"], "has_phone": has_phone, "page": page})
    db.commit()
    return _view(db, company.id, row)


def reveal(db: Session, user: User, company, contact_id: str, field: str) -> dict:
    """Paid: one Lusha person's email or phone (a person from one of the company's searches). Already revealed = the
    stored data, free. A person removed on request is never revealed (checked before anything is spent)."""
    if field not in FIELDS:
        raise BusinessRuleError("field must be email or phone")
    if not configured():
        raise BusinessRuleError("Lusha is not configured (LUSHA_API_KEY)")
    source = db.scalar(select(LushaRequest).where(
        LushaRequest.company_id == company.id, LushaRequest.action == "search", LushaRequest.status == "done",
        LushaRequest.result.contains([{"id": contact_id}])).order_by(LushaRequest.created_at.desc()).limit(1))
    item = next((i for i in source.result if i["id"] == contact_id), None) if source else None
    if item is None:
        raise NotFoundError("This person is not in the company's Lusha results")
    done = db.scalar(select(LushaRequest).where(LushaRequest.lusha_contact_id == contact_id,
                                                LushaRequest.action == field, LushaRequest.status == "done"))
    if done is not None:
        return {"field": field, **(done.result or {}), "credits": 0, "already_revealed": True,
                "person_id": done.person_id}
    if privacy.is_suppressed(db, company.id, item["name"]):
        raise BusinessRuleError("This person was removed from LeadFinder on request: not revealed")
    s = get_settings()
    if field == "email" and s.lusha_phone_only:
        raise BusinessRuleError("Lusha is used for phone numbers only (LUSHA_PHONE_ONLY)")
    if field == "phone" and (pid := contributions_person(db, company.id, item["name"])) and db.scalar(
            select(Phone.id).where(Phone.person_id == pid, Phone.status != "invalid").limit(1)):
        raise BusinessRuleError(f"LeadFinder already has a number for {item['name']}: no credits spent")
    if s.lusha_user_daily_reveals and reveals_today(db, user) >= s.lusha_user_daily_reveals:
        raise BusinessRuleError(f"Daily limit reached ({s.lusha_user_daily_reveals} Lusha reveals per person per day): "
                                "try again tomorrow or ask an admin")
    credits = item.get(f"{field}_credits")
    estimate = DEFAULT_CREDITS[field] if credits is None else int(credits)
    row = _reserve(db, user, company.id, field, estimate, contact_id)
    try:
        data = _call("POST", "/v3/contacts/enrich", {"ids": [contact_id], "reveal": [FIELDS[field]],
                                                     "waterfallEnabled": False})
    except LushaError as exc:
        _fail(db, row, user, exc)
        raise
    contact = next((r for r in data.get("results") or [] if str(r.get("id")) == contact_id), {})
    if field == "email":
        values = [{"email": e["email"].strip().lower(), "type": e.get("type")} for e in contact.get("emails") or []
                  if e.get("email")]
    else:
        values = [{"number": p["number"], "type": p.get("type"), "do_not_call": bool(p.get("doNotCall"))}
                  for p in contact.get("phones") or [] if p.get("number")]
    billed = (data.get("billing") or {}).get("creditsCharged")
    row.status, row.result = ("done" if values else "not_found"), {FIELDS[field]: values}
    row.credits = int(billed) if billed is not None else (estimate if values else 0)
    db.commit()  # paid data recorded first: whatever happens next, nobody pays for it again
    person_id = _save(db, user, company, item, contact, field, values) if values else None
    row.person_id = person_id
    audit_service.record(db, action=f"lusha.{field}_revealed", user_id=user.id, entity_type="company",
                         entity_id=company.id, metadata={"request_id": row.id, "lusha_contact_id": contact_id,
                                                         "found": bool(values), "credits": row.credits,
                                                         "person_id": person_id})
    db.commit()
    return {"field": field, FIELDS[field]: values, "credits": row.credits, "already_revealed": False,
            "person_id": person_id}


def _save(db: Session, user: User, company, item: dict, contact: dict, field: str, values: list[dict]) -> int | None:
    """The revealed person + title + work email / phones into LeadFinder (the same name = the same person)."""
    from app.services import contributions

    title = (contact.get("jobTitle") or {}).get("title") or item.get("title")
    entry = {"person": item["name"], "title": title, "record_id": f"lusha:{item['id']}", "phones": []}
    if field == "email":
        work = [v["email"] for v in values if v.get("type") != "private"]  # business contacts only
        entry["email"] = work[0] if work else None
    else:
        entry["phones"] = [(v["number"], "business_mobile" if v.get("type") == "mobile" else
                            classify_phone(v["number"], company_numbers=set())) for v in values
                           if not v["do_not_call"]]
    if not entry.get("email") and not entry["phones"]:
        return None
    contributions.contribute(db, [entry], channel="LUSHA", contributor_id=user.id, visibility="organization",
                             apply=True, company_id=company.id, label="revealed from Lusha")
    return contributions._known_person(db, company.id, entry.get("email"), item["name"])


# ---- credits / ledger for the UI -----------------------------------------------------------------------------------


def account_usage() -> dict | None:
    """Lusha's own balance (free endpoint, 5 requests / minute: cached 60 s); None when unavailable."""
    if not configured():
        return None
    if _usage_cache[1] is not None and time.monotonic() - _usage_cache[0] < 60:
        return _usage_cache[1]
    try:
        credits = _call("GET", "/v3/account/usage").get("credits") or {}
    except AppError:
        return None
    _usage_cache[:] = [time.monotonic(), {k: credits.get(k) for k in ("total", "used", "remaining")}]
    return _usage_cache[1]


def contributions_person(db: Session, company_id: int, name: str) -> int | None:
    from app.services import contributions

    return contributions._known_person(db, company_id, None, name)


def reveals_today(db: Session, user: User) -> int:
    """The user's paid reveals since midnight UTC (a failed call costs nothing and does not count)."""
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(db.scalar(select(func.count()).select_from(LushaRequest).where(
        LushaRequest.user_id == user.id, LushaRequest.action.in_(tuple(FIELDS)),
        LushaRequest.status.in_(("pending", "done", "not_found")), LushaRequest.credits > 0,
        LushaRequest.created_at >= midnight)) or 0)


def credits(db: Session, user: User | None = None) -> dict:
    s = get_settings()
    budget = s.lusha_monthly_credit_budget
    spent = spent_this_month(db)
    daily = s.lusha_user_daily_reveals or None
    return {"configured": configured(), "monthly_budget": budget or None, "spent_this_month": spent,
            "budget_left": max(budget - spent, 0) if budget else None, "account": account_usage(),
            "phone_only": s.lusha_phone_only, "daily_reveals": daily,
            "reveals_left_today": max(daily - reveals_today(db, user), 0) if daily and user else None}


def ledger(db: Session, limit: int = 200) -> list[dict]:
    rows = db.execute(select(LushaRequest, User.name, Company.name).outerjoin(User, User.id == LushaRequest.user_id)
                      .outerjoin(Company, Company.id == LushaRequest.company_id)
                      .order_by(LushaRequest.created_at.desc(), LushaRequest.id.desc()).limit(limit)).all()
    return [{"id": r.id, "at": r.created_at, "user": user, "company_id": r.company_id, "company": company,
             "action": r.action, "status": r.status, "credits": r.credits, "person_id": r.person_id,
             "query": (r.params or {}).get("query"), "error": r.error} for r, user, company in rows]
