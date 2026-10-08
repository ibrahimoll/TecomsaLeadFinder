"""Coverage-gap classifier: WHY LeadFinder has no credible people for a company, measured from what is stored (no
network, no guessing). Several reasons can hold at once; they are stored (company_gap_reasons) so research targets
the cause and is never re-run blindly.

    NO_WEBSITE / WEBSITE_UNREACHABLE / WEBSITE_NO_PEOPLE        the company's own site
    GLOBAL_BRAND_AMBIGUITY / GROUP_ENTITY_AMBIGUITY            whose people would they be?
    NO_EXTERNAL_PERSON_SOURCE                                  no routed public source names anyone for it
    SOURCE_HAS_COMPANY_ONLY                                    a source knows the company, but names no one
    ARABIC_LATIN_MISMATCH / COMPANY_ALIAS_MISMATCH             a source probably names it, but not provably (a
                                                               transliteration or a phone alone: never applied)
    COMMON_CRAWL_NO_CAPTURE / COMMON_CRAWL_ERROR               the web archive has nothing / did not answer
    PERSON_REJECTED_COMPANY_MATCH / PERSON_REJECTED_LOW_CONFIDENCE   people were read, but not provably this company's
    HISTORICAL_ONLY                                            only former / not-confirmed / weak roles
    UNKNOWN                                                    none of the above explains it
"""

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Company, CompanyGapReason, CompanyPerson, CompanyWebPage, Evidence, Source, SourceLookup

GAP_REASONS = (
    "NO_WEBSITE", "WEBSITE_UNREACHABLE", "WEBSITE_NO_PEOPLE", "NO_EXTERNAL_PERSON_SOURCE", "SOURCE_HAS_COMPANY_ONLY",
    "COMPANY_ALIAS_MISMATCH", "ARABIC_LATIN_MISMATCH", "FRENCH_ENGLISH_MISMATCH", "GROUP_ENTITY_AMBIGUITY",
    "GLOBAL_BRAND_AMBIGUITY", "COMMON_CRAWL_NO_CAPTURE", "COMMON_CRAWL_ERROR", "SOURCE_FETCH_ERROR",
    "SOURCE_PARSE_ERROR", "PERSON_EXTRACTION_FAILED", "PERSON_REJECTED_COMPANY_MATCH", "PERSON_REJECTED_LOW_CONFIDENCE",
    "HISTORICAL_ONLY", "UNKNOWN",
)
CREDIBLE = 50


def credible_people(db: Session, company_id: int) -> int:
    return db.scalar(select(func.count(func.distinct(CompanyPerson.person_id))).where(
        CompanyPerson.company_id == company_id, CompanyPerson.employment_status != "former",
        CompanyPerson.confidence >= CREDIBLE)) or 0


def _directory_outcomes(db: Session, company: Company) -> dict[str, Counter]:
    """Dry run of the routed directory sources (read-only): per source, matched organisation / person records and
    weak (possible) matches."""
    from app.services.people.external.lebanon import identity, pack

    out: dict[str, Counter] = {}
    keys = pack.directory_sources(company)
    if not keys:
        return out
    ctx = identity.context(db, company)
    for key in keys:
        counts: Counter = Counter()
        for _, records in pack._loaded(db, key):
            decided: dict[tuple, tuple] = {}
            for record in records:
                if record.bio:
                    continue
                org = tuple(record.org)
                confidence, stage = decided.get(org) or identity.match(ctx, record)
                decided.setdefault(org, (confidence, stage))
                if confidence is not None:
                    counts["person" if record.person else "organisation"] += 1
                elif stage.startswith("possible") and not record.person:
                    counts[stage] += 1
        out[key] = counts
    return out


def classify(db: Session, company: Company, *, persist: bool = True) -> list[tuple[str, str | None, dict]]:
    """[(reason, source_key, details)] for a company with no credible people ([] when it has some)."""
    from app.services.enrichment.domain_intel import foreign_brand

    if credible_people(db, company.id):
        if persist:
            db.execute(delete(CompanyGapReason).where(CompanyGapReason.company_id == company.id))
        return []
    reasons: list[tuple[str, str | None, dict]] = []
    if not company.domain and not company.website:
        reasons.append(("NO_WEBSITE", None, {}))
    else:
        pages = db.scalar(select(func.count()).select_from(CompanyWebPage).where(
            CompanyWebPage.company_id == company.id, CompanyWebPage.content.is_not(None))) or 0
        if not pages:
            reasons.append(("WEBSITE_UNREACHABLE", None, {"enrichment_status": company.enrichment_status,
                                                          "message": company.enrichment_message}))
        else:
            reasons.append(("WEBSITE_NO_PEOPLE", None, {"pages_read": pages}))
    if foreign_brand(company):
        reasons.append(("GLOBAL_BRAND_AMBIGUITY", None, {"website": company.website}))
    if any(w in (company.name or "").lower().split() for w in ("group", "groupe", "holding", "holdings")):
        reasons.append(("GROUP_ENTITY_AMBIGUITY", None, {}))
    outcomes = _directory_outcomes(db, company)
    any_person_source = False
    for key, counts in outcomes.items():
        if counts["person"]:
            any_person_source = True
        if counts["organisation"] and not counts["person"]:
            reasons.append(("SOURCE_HAS_COMPANY_ONLY", key, {"records": counts["organisation"]}))
        if counts["possible:transliteration"]:
            reasons.append(("ARABIC_LATIN_MISMATCH", key, {"possible": counts["possible:transliteration"]}))
        if counts["possible:phone"]:
            reasons.append(("COMPANY_ALIAS_MISMATCH", key, {"possible": counts["possible:phone"]}))
    if not any_person_source and not any(r[0] in ("ARABIC_LATIN_MISMATCH", "COMPANY_ALIAS_MISMATCH")
                                         for r in reasons):
        reasons.append(("NO_EXTERNAL_PERSON_SOURCE", None, {"sources_routed": sorted(outcomes)}))
    lookups = db.execute(select(SourceLookup.status, SourceLookup.failure_reason, func.count())
                         .where(SourceLookup.company_id == company.id, SourceLookup.source_key == "common_crawl")
                         .group_by(SourceLookup.status, SourceLookup.failure_reason)).all()
    if lookups:
        failed = {reason: n for status, reason, n in lookups if status != "ok"}
        ok = sum(n for status, _, n in lookups if status == "ok")
        if failed and not ok:
            reasons.append(("COMMON_CRAWL_ERROR", "common_crawl", failed))
        elif ok and not db.scalar(select(func.count()).select_from(SourceLookup).where(
                SourceLookup.company_id == company.id, SourceLookup.source_key == "common_crawl",
                SourceLookup.useful_items > 0)):
            reasons.append(("COMMON_CRAWL_NO_CAPTURE", "common_crawl", {"lookups": ok}))
    stats = ((company.sources_attempted or {}).get("stats") or {})
    rejected_match = sum(stats.get(k, 0) for k in ("rejected_company_not_named", "rejected_weak_company_match",
                                                   "rejected_group_role", "rejected_ambiguous_name"))
    if rejected_match:
        reasons.append(("PERSON_REJECTED_COMPANY_MATCH", None, {"rejected": rejected_match}))
    roles = db.execute(select(CompanyPerson.employment_status, CompanyPerson.confidence).where(
        CompanyPerson.company_id == company.id)).all()
    if roles:
        weak = sum((c or 0) < CREDIBLE for _, c in roles)
        reasons.append(("HISTORICAL_ONLY" if weak < len(roles) or all(s != "current" for s, _ in roles)
                        else "PERSON_REJECTED_LOW_CONFIDENCE", None, {"roles": len(roles), "weak": weak}))
    failed = {k: stats[k] for k in ("sources_failed", "stopped_deadline", "commoncrawl_unavailable") if stats.get(k)}
    if failed:
        reasons.append(("SOURCE_FETCH_ERROR", None, failed))  # this attempt was incomplete: retried later
    if not reasons:
        reasons.append(("UNKNOWN", None, {}))
    if persist:
        db.execute(delete(CompanyGapReason).where(CompanyGapReason.company_id == company.id))
        now = datetime.now(timezone.utc)
        for reason, key, details in reasons:
            db.execute(insert(CompanyGapReason).values(company_id=company.id, gap_reason=reason, source_key=key,
                                                       details=details, detected_at=now).on_conflict_do_nothing())
    return reasons


def distribution(db: Session, company_ids: list[int]) -> Counter:
    counts: Counter = Counter()
    for (reason,) in db.execute(select(CompanyGapReason.gap_reason).where(
            CompanyGapReason.company_id.in_(company_ids))).all():
        counts[reason] += 1
    return counts


def website_people(db: Session, company_id: int) -> int:
    return db.scalar(select(func.count(func.distinct(CompanyPerson.person_id))).select_from(CompanyPerson)
                     .join(Evidence, Evidence.company_person_id == CompanyPerson.id)
                     .join(Source, Source.id == Evidence.source_id)
                     .where(CompanyPerson.company_id == company_id, Source.source_type == "company_website")) or 0
