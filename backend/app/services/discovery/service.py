"""Discovery runs: search sources, normalise, dedupe, check LeadFinder + Odoo, save new companies.

    providers (Overture, OSM) ─► candidates, best first
        │  per candidate, in order:
        ├─ same company as an earlier result of this run?      -> DUPLICATE
        ├─ same source id already linked to a company?          -> known company
        ├─ deterministic match (domain, phone, email domain,
        │  name + city, name) against LeadFinder companies      -> known company
        │     known company protected by Odoo?                  -> protected state
        │     otherwise                                         -> EXISTING_LEADFINDER
        ├─ not in LeadFinder, but Odoo evidence (contacts / CRM)-> protected state (not saved)
        └─ otherwise                                            -> AVAILABLE: saved as a new company
    stop once `requested_count` new companies were saved; then add LeadFinder companies of
    the same industry/area that no source returned (the database is searched too).

Nothing here creates CRM leads or opportunities. Counts written to the run are the
real processing counts; progress is committed as it happens so the UI can follow it.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models import (
    CampaignCompany,
    Company,
    CompanySourceRecord,
    Contact,
    CrmLead,
    DiscoveryResult,
    DiscoveryRun,
    LeadActivity,
    LushaUsage,
    OdooContact,
    User,
)
from app.models.enums import (
    ACTIVE_DISCOVERY_STATUSES,
    DISCOVERY_STATE_FOR_STATUS,
    PROTECTED_DISCOVERY_STATES,
    CompanySource,
    DiscoveryState,
    DiscoveryStatus,
    OdooMatchStatus,
)
from app.services import audit_service, relationship_service
from app.services.discovery.base import Candidate, DiscoveryProvider, ProviderError, SearchQuery
from app.services.discovery.geography import AREAS, COUNTRIES, in_area
from app.services.discovery.industries import INDUSTRIES, INDUSTRY_BY_KEY, profile_for
from app.services.discovery.osm import OsmProvider
from app.services.discovery.overture import OvertureProvider
from app.services.matching_service import CompanyIndex, MatchSignals
from app.services.normalization import (
    company_domain,
    email_domain,
    normalize_company_name,
    normalize_phone,
    normalize_website,
)
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)

REQUEST_COUNTS = (25, 50, 100, 200)
COMMIT_EVERY = 20
SOURCE_LABELS = {"OVERTURE": "Overture Maps", "OSM": "OpenStreetMap", "LEADFINDER": "LeadFinder database"}


class DiscoveryAction:
    STARTED = "discovery.started"
    FINISHED = "discovery.finished"
    DELETED = "discovery.deleted"


def default_providers() -> list[DiscoveryProvider]:
    s = get_settings()
    providers: list[DiscoveryProvider] = [OvertureProvider(s.discovery_cache_dir, s.overture_stac_url, s.overture_release)]
    if s.osm_enabled:
        providers.append(OsmProvider(s.discovery_cache_dir, s.overpass_url, s.osm_cache_hours))
    return providers


# Replaced in tests with fakes; production always uses the real sources.
provider_factory = default_providers


def options() -> dict[str, Any]:
    return {
        "countries": [{"code": c.code, "name": c.name} for c in COUNTRIES.values()],
        "areas": {code: [{"key": a.key, "label": a.label, "kind": a.kind} for a in areas.values()]
                  for code, areas in AREAS.items()},
        "industries": [{"key": p.key, "label": p.label} for p in INDUSTRIES],
        "counts": list(REQUEST_COUNTS),
        "sources": [{"key": p.key, "label": p.label} for p in provider_factory()],
    }


# ---------------------------------------------------------------------------
# Start / run
# ---------------------------------------------------------------------------


def start_run(db: Session, actor: User, *, country: str, city: str | None, industry: str | None,
              custom_query: str | None, requested_count: int) -> DiscoveryRun:
    country_def = COUNTRIES.get(country)
    if country_def is None:
        raise BusinessRuleError(f"Discovery is not available for country '{country}' yet.")
    if city and city not in AREAS.get(country, {}):
        raise BusinessRuleError(f"Unknown area '{city}' for {country_def.name}.")
    custom = " ".join((custom_query or "").split()) or None
    if bool(industry) == bool(custom):
        raise BusinessRuleError("Choose an industry, or type a custom one (not both).")
    if industry and industry not in INDUSTRY_BY_KEY:
        raise BusinessRuleError(f"Unknown industry '{industry}'.")
    if custom and not profile_for(None, custom).words:
        raise BusinessRuleError("The custom industry needs at least one meaningful word, e.g. “plastic packaging”.")
    if not 1 <= requested_count <= get_settings().discovery_max_requested:
        raise BusinessRuleError(f"Ask for between 1 and {get_settings().discovery_max_requested} companies.")
    active = db.scalar(select(DiscoveryRun.id).where(DiscoveryRun.created_by == actor.id,
                                                     DiscoveryRun.status.in_(ACTIVE_DISCOVERY_STATUSES)))
    if active:
        raise ConflictError("You already have a search running. Wait for it to finish first.")

    profile = profile_for(industry, custom)
    area_label = AREAS[country][city].label if city else f"All {country_def.name}"
    run = DiscoveryRun(
        created_by=actor.id, country=country, city=city, industry=industry, custom_query=custom,
        query_label=f"{profile.label} · {area_label}", requested_count=requested_count,
        status=DiscoveryStatus.QUEUED, progress=[{"key": "queued", "label": "Queued", "detail": None, "state": "done"}],
        sources=[], errors=[],
    )
    db.add(run)
    db.flush()
    audit_service.record(db, action=DiscoveryAction.STARTED, user_id=actor.id, entity_type="discovery_run",
                         entity_id=run.id, metadata={"query": run.query_label, "requested": requested_count})
    db.commit()
    if get_settings().discovery_inline:
        execute(run.id, db)
        db.refresh(run)
    else:
        threading.Thread(target=execute, args=(run.id,), name=f"discovery-{run.id}", daemon=True).start()
    return run


def execute(run_id: int, db: Session | None = None) -> None:
    """Run a discovery (in a background thread in production)."""
    from app.db.session import SessionLocal

    own = db is None
    session = SessionLocal() if own else db
    try:
        run = session.get(DiscoveryRun, run_id)
        if run is not None:
            _Runner(session, run).execute()
    finally:
        if own:
            session.close()


def fail_interrupted_runs(db: Session) -> int:
    """At startup: runs left active by a stopped server can never finish."""
    runs = db.scalars(select(DiscoveryRun).where(DiscoveryRun.status.in_(ACTIVE_DISCOVERY_STATUSES))).all()
    for run in runs:
        run.status = DiscoveryStatus.PARTIAL if run.new_company_count else DiscoveryStatus.FAILED
        run.finished_at = datetime.now(timezone.utc)
        run.errors = [*run.errors, "Interrupted by a server restart."]
        run.error_count = len(run.errors)
        run.summary = "The search was interrupted by a server restart. Companies saved before that are kept."
    db.commit()
    return len(runs)


def _state_for(company: Company) -> DiscoveryState:
    return DISCOVERY_STATE_FOR_STATUS.get(OdooMatchStatus(company.crm_status), DiscoveryState.EXISTING_LEADFINDER)


def _transient(c: Candidate) -> Company:
    """Unsaved company carrying the candidate's matching keys (for Odoo evidence)."""
    return Company(
        name=c.name,
        normalized_name=normalize_company_name(c.name),
        domain=company_domain(c.website),
        email_domain=email_domain(c.email),
        main_phone_normalized=normalize_phone(c.phone, c.country),
        city=c.city,
    )


class _Runner:
    def __init__(self, db: Session, run: DiscoveryRun):
        self.db, self.run, self.run_id = db, run, run.id
        self.country = COUNTRIES[run.country]
        self.area = AREAS[run.country][run.city] if run.city else None
        self.profile = profile_for(run.industry, run.custom_query)
        self.providers = provider_factory()
        self.now = datetime.now(timezone.utc)
        self.position = 0
        self.company_results: dict[int, DiscoveryResult] = {}  # company id -> first result in this run
        self.local_keys: dict[tuple[str, str], DiscoveryResult] = {}  # keys of unsaved (protected) results

    # ---- progress ---------------------------------------------------------------------

    def stage(self, key: str, label: str, detail: str | None = None, state: str = "active") -> None:
        progress = [p for p in self.run.progress if p["key"] != key]
        for p in progress:
            if p["state"] == "active":
                p["state"] = "done"
        progress.append({"key": key, "label": label, "detail": detail, "state": state})
        self.run.progress = progress
        self.db.commit()

    # ---- main -------------------------------------------------------------------------

    def execute(self) -> None:
        run = self.run
        run.status = DiscoveryStatus.SEARCHING
        run.started_at = self.now
        self.db.commit()
        failures: list[str] = []
        try:
            candidates, versions = self._search(failures)
            if len(failures) == len(self.providers):
                self._finish(DiscoveryStatus.FAILED, failures, "No source could be queried. No companies were added.")
                return
            run.status = DiscoveryStatus.PROCESSING
            run.source_version = "; ".join(versions) or None
            self._process(candidates)
            self._database_extras()
            status = DiscoveryStatus.PARTIAL if failures else DiscoveryStatus.COMPLETED
            self._finish(status, failures, self._summary(failures))
        except Exception as exc:  # unexpected: keep what was committed, report honestly
            self.db.rollback()
            logger.exception("Discovery run %s failed", self.run_id)
            self.db.refresh(run)
            failures.append(f"Unexpected error while processing results ({exc.__class__.__name__}).")
            status = DiscoveryStatus.PARTIAL if run.new_company_count else DiscoveryStatus.FAILED
            kept = f" {run.new_company_count} companies saved before the error are kept." if run.new_company_count else ""
            self._finish(status, failures, f"The search stopped because of an error.{kept}")

    def _search(self, failures: list[str]) -> tuple[list[Candidate], list[str]]:
        query = SearchQuery(self.country, self.area, self.profile)
        found: list[Candidate] = []
        versions: list[str] = []
        succeeded: list[str] = []
        for provider in self.providers:
            label = f"Searching {provider.label}"
            self.stage(provider.key, label)
            try:
                result = provider.search(query, lambda _l, detail, k=provider.key, lab=label: self.stage(k, lab, detail))
            except ProviderError as exc:
                failures.append(f"{provider.label}: {exc}")
                self.stage(provider.key, label, str(exc), "failed")
                continue
            except Exception as exc:
                logger.exception("Provider %s failed", provider.key)
                failures.append(f"{provider.label} could not be queried ({exc.__class__.__name__}).")
                self.stage(provider.key, label, "The source could not be queried.", "failed")
                continue
            found.extend(result.candidates)
            succeeded.append(provider.key)
            if result.version:
                versions.append(f"{provider.label} {result.version}")
            self.stage(provider.key, label, f"{len(result.candidates):,} matching places", "done")
        self.run.sources = succeeded
        self.run.source_match_count = len(found)
        # Best first across sources (stable: Overture before OSM on ties).
        found.sort(key=lambda c: (-c.score, -(c.confidence or 0.5), not c.phone, not c.website))
        return found, versions

    def _process(self, candidates: list[Candidate]) -> None:
        run = self.run
        label = "Normalising, removing duplicates and checking LeadFinder and TECOMSA Odoo"
        self.stage("process", label, f"0 of {len(candidates):,} examined")
        self.index = CompanyIndex(self.db.scalars(select(Company)).all())
        self.odoo = relationship_service.OdooIndex(self.db)
        keys = [(c.source, c.external_id) for c in candidates]
        self.by_source: dict[tuple[str, str], Company] = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            rows = self.db.execute(
                select(CompanySourceRecord, Company)
                .join(Company, Company.id == CompanySourceRecord.company_id)
                .where(or_(*[(CompanySourceRecord.source == s) & (CompanySourceRecord.external_id == e) for s, e in chunk]))
            ).all() if chunk else []
            for record, company in rows:
                self.by_source[(record.source, record.external_id)] = company

        for i, candidate in enumerate(candidates, start=1):
            if run.new_company_count >= run.requested_count:
                break
            self._one(candidate)
            if i % COMMIT_EVERY == 0:
                self.stage("process", label, self._counts_text(i, len(candidates)))
        self.stage("process", label, self._counts_text(self.position, len(candidates)), "done")

    def _counts_text(self, examined: int, total: int) -> str:
        r = self.run
        return (f"{examined:,} of {total:,} examined · {r.new_company_count} new · {r.existing_company_count} already in "
                f"LeadFinder · {r.odoo_protected_count} protected · {r.duplicate_count} duplicates")

    def _record(self, c: Candidate, state: DiscoveryState, reason: str | None, company: Company | None = None,
                duplicate_of: DiscoveryResult | None = None) -> DiscoveryResult:
        self.position += 1
        result = DiscoveryResult(
            run_id=self.run.id, position=self.position, source=c.source, external_id=c.external_id,
            name=c.name, category=c.category, address=c.address, city=c.city, country=c.country,
            phone=c.phone[:50] if c.phone else None, website=c.website[:500] if c.website else None,
            email=c.email[:320] if c.email else None, latitude=c.latitude, longitude=c.longitude,
            state=state, reason=reason, match_reason=c.match_reason,
            company_id=company.id if company else None, duplicate_of_id=duplicate_of.id if duplicate_of else None,
        )
        self.db.add(result)
        self.db.flush()
        run = self.run
        run.raw_results_count += 1
        if state == DiscoveryState.DUPLICATE:
            run.duplicate_count += 1
        elif state == DiscoveryState.AVAILABLE:
            run.new_company_count += 1
        elif state in PROTECTED_DISCOVERY_STATES:
            run.odoo_protected_count += 1
        else:
            run.existing_company_count += 1
        if company is not None and company.id not in self.company_results:
            self.company_results[company.id] = result
        return result

    def _local_keys(self, c: Candidate) -> list[tuple[str, str]]:
        keys = []
        if d := company_domain(c.website):
            keys.append(("domain", d))
        if p := normalize_phone(c.phone, c.country):
            keys.append(("phone", p))
        if e := email_domain(c.email):
            keys.append(("email", e))
        keys.append(("name", normalize_company_name(c.name)))
        return keys

    def _one(self, c: Candidate) -> None:
        # 1. Same organisation as an unsaved (protected) result earlier in this run.
        local = self._local_keys(c)
        for key in local:
            if key in self.local_keys:
                first = self.local_keys[key]
                self._record(c, DiscoveryState.DUPLICATE, f"Same company as result #{first.position} ({key[0]})",
                             company=None, duplicate_of=first)
                return
        # 2. A LeadFinder company: by source id, then deterministic matching.
        company = self.by_source.get((c.source, c.external_id))
        reason = f"Same {SOURCE_LABELS.get(c.source, c.source)} record (source id)" if company else None
        if company is None:
            match = self.index.match(MatchSignals(name=c.name, website=c.website, email=c.email, phone=c.phone,
                                                  city=c.city, country=c.country))
            if match:
                company, reason = match.company, match.reason
        if company is not None:
            first = self.company_results.get(company.id)
            if first is not None:
                self._record(c, DiscoveryState.DUPLICATE, f"Same company as result #{first.position}: {reason}",
                             company=company, duplicate_of=first)
                return
            self._link_source(company, c)
            self._fill_blanks(company, c)
            decision = self.odoo.decide(company)
            relationship_service.apply_decision(self.db, company, decision)
            state = _state_for(company)
            why = f"{reason}. {company.crm_status_reason}" if state in PROTECTED_DISCOVERY_STATES else f"Already in LeadFinder: {reason}"
            self._record(c, state, why, company=company)
            return
        # 3. Not in LeadFinder: does TECOMSA's Odoo already know it?
        decision = self.odoo.decide(_transient(c))
        state = DISCOVERY_STATE_FOR_STATUS.get(decision.status)
        if state is not None:
            result = self._record(c, state, decision.reason)
            for key in local:
                self.local_keys.setdefault(key, result)
            return
        # 4. New company.
        company = self._create(c)
        relationship_service.apply_decision(self.db, company, decision)
        self._record(c, DiscoveryState.AVAILABLE, "No match in LeadFinder or TECOMSA's Odoo data", company=company)

    def _create(self, c: Candidate) -> Company:
        website = normalize_website(c.website)[:500] if c.website else None
        company = Company(
            name=c.name,
            normalized_name=normalize_company_name(c.name),
            website=website,
            domain=company_domain(c.website),
            country=c.country,
            city=c.city[:100] if c.city else None,
            address=c.address,
            industry=self.profile.label[:150],
            main_phone=c.phone[:50] if c.phone else None,
            main_phone_normalized=normalize_phone(c.phone, c.country),
            main_email=c.email,
            email_domain=email_domain(c.email),
            latitude=c.latitude,
            longitude=c.longitude,
            source=CompanySource.DISCOVERY,
            source_reference=f"{c.source.lower()}:{c.external_id}"[:255],
            created_by=self.run.created_by,
            created_by_discovery_run_id=self.run.id,
        )
        self.db.add(company)
        self.db.flush()
        self.index.add(company)
        self._link_source(company, c)
        return company

    def _link_source(self, company: Company, c: Candidate) -> None:
        record = self.db.scalar(select(CompanySourceRecord).where(
            CompanySourceRecord.source == c.source, CompanySourceRecord.external_id == c.external_id))
        if record is None:
            record = CompanySourceRecord(company_id=company.id, source=c.source, external_id=c.external_id,
                                         first_seen_run_id=self.run.id, first_seen_at=self.now)
            self.db.add(record)
        record.data = c.data
        record.source_version = (self.run.source_version or "")[:200] or None
        record.last_seen_run_id = self.run.id
        record.last_seen_at = self.now
        self.by_source[(c.source, c.external_id)] = company

    @staticmethod
    def _fill_blanks(company: Company, c: Candidate) -> None:
        """Add what the source knows without overwriting anything already on the company."""
        if c.phone and not company.main_phone:
            company.main_phone = c.phone[:50]
            company.main_phone_normalized = normalize_phone(c.phone, c.country)
        if c.website and not company.website:
            company.website = normalize_website(c.website)[:500]
            company.domain = company_domain(c.website)
        if c.email and not company.main_email:
            company.main_email = c.email
            company.email_domain = email_domain(c.email)
        for attr, value in (("city", c.city), ("address", c.address), ("latitude", c.latitude),
                            ("longitude", c.longitude), ("country", c.country)):
            if value is not None and getattr(company, attr) is None:
                setattr(company, attr, value)

    def _database_extras(self) -> None:
        """LeadFinder companies of this industry and area that no source returned this time."""
        label = "Checking the LeadFinder database"
        self.stage("database", label)
        stmt = select(Company).where(func.lower(Company.industry) == self.profile.label.lower(),
                                     or_(Company.country.is_(None), func.lower(Company.country) == self.country.name.lower()))
        if self.company_results:
            stmt = stmt.where(Company.id.not_in(list(self.company_results)))
        added = 0
        for company in self.db.scalars(stmt.order_by(Company.id)).all():
            if self.area and not in_area(self.area, company.latitude, company.longitude,
                                         [t for t in (company.city, company.address) if t], self.run.country):
                continue
            state = _state_for(company)
            reason = company.crm_status_reason if state in PROTECTED_DISCOVERY_STATES else "Already in the LeadFinder database"
            self._record(Candidate(source="LEADFINDER", external_id=str(company.id), name=company.name,
                                   category=company.industry, website=company.website, phone=company.main_phone,
                                   email=company.main_email, address=company.address, city=company.city,
                                   country=company.country, latitude=company.latitude, longitude=company.longitude,
                                   match_reason="Same industry in LeadFinder"), state, reason, company=company)
            added += 1
            if added >= self.run.requested_count:
                break
        self.stage("database", label, f"{added} more known {'company' if added == 1 else 'companies'} in LeadFinder", "done")

    def _summary(self, failures: list[str]) -> str:
        r = self.run
        sources = " and ".join(SOURCE_LABELS.get(s, s) for s in r.sources if s != "LEADFINDER") or "the sources"
        text = f"{r.new_company_count} new {'company' if r.new_company_count == 1 else 'companies'} saved"
        if r.new_company_count < r.requested_count:
            text += (f" of the {r.requested_count} requested: {sources} returned {r.source_match_count} places matching "
                     f"“{self.profile.label}” in {self.area.label if self.area else self.country.name}, and the others "
                     f"were already in LeadFinder ({r.existing_company_count}), protected by TECOMSA's Odoo data "
                     f"({r.odoo_protected_count}) or duplicates ({r.duplicate_count}).")
        else:
            text += "."
        if failures:
            text += " Some sources failed; see the errors."
        return text

    def _finish(self, status: DiscoveryStatus, failures: list[str], summary: str) -> None:
        run = self.run
        run.status = status
        run.errors = failures
        run.error_count = len(failures)
        run.summary = summary
        run.finished_at = datetime.now(timezone.utc)
        self.stage("done", {"COMPLETED": "Completed", "PARTIAL": "Partially completed", "FAILED": "Failed"}[status],
                   summary, "done" if status != DiscoveryStatus.FAILED else "failed")
        audit_service.record(self.db, action=DiscoveryAction.FINISHED, user_id=run.created_by,
                             entity_type="discovery_run", entity_id=run.id, metadata={
                                 "status": status, "new": run.new_company_count, "examined": run.raw_results_count,
                                 "protected": run.odoo_protected_count, "existing": run.existing_company_count,
                                 "duplicates": run.duplicate_count, "errors": failures})
        self.db.commit()


# ---------------------------------------------------------------------------
# Read / delete
# ---------------------------------------------------------------------------

STATE_GROUPS: dict[str, tuple[str, ...]] = {
    "available": (DiscoveryState.AVAILABLE,),
    "known": (DiscoveryState.EXISTING_LEADFINDER,),
    "protected": tuple(PROTECTED_DISCOVERY_STATES),
    "duplicate": (DiscoveryState.DUPLICATE,),
}


def get_run(db: Session, run_id: int) -> DiscoveryRun:
    run = db.get(DiscoveryRun, run_id)
    if run is None:
        raise NotFoundError("Discovery run not found")
    return run


def list_runs(db: Session, params: PageParams, *, mine_only: User | None = None) -> tuple[list[DiscoveryRun], int]:
    stmt = select(DiscoveryRun)
    if mine_only is not None:
        stmt = stmt.where(DiscoveryRun.created_by == mine_only.id)
    return paginate(db, stmt.order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc()), params)


def list_results(db: Session, run_id: int, params: PageParams, *, group: str | None = None, source: str | None = None,
                 q: str | None = None, sort: str = "rank") -> tuple[list[DiscoveryResult], int]:
    get_run(db, run_id)
    stmt = select(DiscoveryResult).where(DiscoveryResult.run_id == run_id)
    if group and group in STATE_GROUPS:
        stmt = stmt.where(DiscoveryResult.state.in_(STATE_GROUPS[group]))
    if source:
        stmt = stmt.where(DiscoveryResult.source == source)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(DiscoveryResult.name.ilike(like), DiscoveryResult.city.ilike(like),
                              DiscoveryResult.category.ilike(like)))
    order = {"name": (func.lower(DiscoveryResult.name),), "city": (DiscoveryResult.city.nulls_last(), DiscoveryResult.position),
             "category": (DiscoveryResult.category.nulls_last(), DiscoveryResult.position)}.get(sort, (DiscoveryResult.position,))
    return paginate(db, stmt.order_by(*order, DiscoveryResult.id), params)


def group_counts(db: Session, run_id: int) -> dict[str, int]:
    rows = dict(db.execute(select(DiscoveryResult.state, func.count()).where(DiscoveryResult.run_id == run_id)
                           .group_by(DiscoveryResult.state)).all())
    counts = {g: sum(rows.get(s, 0) for s in states) for g, states in STATE_GROUPS.items()}
    counts["all"] = sum(rows.values())
    return counts


def _company_in_use(db: Session, company_id: int, run_id: int) -> bool:
    checks = (
        exists().where(DiscoveryResult.company_id == company_id, DiscoveryResult.run_id != run_id),
        exists().where(CrmLead.company_id == company_id),
        exists().where(OdooContact.company_id == company_id),
        exists().where(Contact.company_id == company_id),
        exists().where(CampaignCompany.company_id == company_id),
        exists().where(LeadActivity.company_id == company_id),
        exists().where(LushaUsage.company_id == company_id),
    )
    return any(db.scalar(select(check)) for check in checks)


def delete_run(db: Session, actor: User, run_id: int, *, with_data: bool) -> dict[str, Any]:
    """Delete a run and its result history; optionally the companies only it brought in.

    Like deleting an import: a company is removed only when this run created it and
    nothing else uses it (another run found it too, or it has CRM/Odoo links, contacts,
    campaigns, notes or credits). Kept companies that another run also found are handed
    over to the newest such run.
    """
    run = get_run(db, run_id)
    if run.status in ACTIVE_DISCOVERY_STATUSES:
        raise ConflictError("This search is still running. Wait for it to finish before deleting it.")
    removed = kept = 0
    for company in db.scalars(select(Company).where(Company.created_by_discovery_run_id == run.id)).all():
        if with_data and not _company_in_use(db, company.id, run.id):
            db.delete(company)
            removed += 1
            continue
        newer = db.scalar(select(func.max(DiscoveryResult.run_id)).where(
            DiscoveryResult.company_id == company.id, DiscoveryResult.run_id != run.id))
        if newer:
            company.created_by_discovery_run_id = newer
        kept += 1
    details = {"query": run.query_label, "status": run.status, "with_data": with_data,
               "companies_removed": removed, "companies_kept": kept}
    db.delete(run)
    audit_service.record(db, action=DiscoveryAction.DELETED, user_id=actor.id, entity_type="discovery_run",
                         entity_id=run_id, metadata=details)
    db.commit()
    return {"id": run_id, "with_data": with_data, "companies_removed": removed, "companies_kept": kept}
