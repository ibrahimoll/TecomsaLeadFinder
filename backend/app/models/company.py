from datetime import date, datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer,
                        SmallInteger, String, Text, UniqueConstraint, event, false, text)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, confidence_check
from app.models.enums import (CompanyStatus, DuplicateStatus, EnrichmentStatus, FitLevel, IdentityConfidence,
                              OfferingKind, Solution, sql_in)


class Company(TimestampMixin, Base):
    """The canonical company record. Facts researched later point back here through `evidence`.

    Names are not unique (different companies share names); `normalized_name` is the blocking key for
    future entity resolution. `domain` is the company's own registrable host (never a social/maps host) and
    is unique when present: one website, one company record.
    """

    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(sql_in("status", CompanyStatus), name="status_valid"),
        CheckConstraint("employee_count_estimate IS NULL OR employee_count_estimate > 0", name="employees_positive"),
        CheckConstraint("founded_year IS NULL OR founded_year BETWEEN 1700 AND 2100", name="founded_year_range"),
        CheckConstraint(f"identity_confidence IS NULL OR {sql_in('identity_confidence', IdentityConfidence)}",
                        name="identity_confidence_valid"),
        CheckConstraint(sql_in("enrichment_status", EnrichmentStatus), name="enrichment_status_valid"),
        CheckConstraint(sql_in("people_status", EnrichmentStatus), name="people_status_valid"),
        CheckConstraint(sql_in("external_people_status", EnrichmentStatus), name="external_people_status_valid"),
        CheckConstraint(sql_in("contact_status", EnrichmentStatus), name="contact_status_valid"),
        CheckConstraint("employee_count_min IS NULL OR employee_count_max IS NULL OR "
                        "employee_count_min <= employee_count_max", name="employee_range_ordered"),
        confidence_check("website_confidence"),
        # direct company search (services/company_search.py): name keys, and typo-tolerant normalized names
        Index("ix_companies_search_keys", "search_keys", postgresql_using="gin"),
        Index("ix_companies_normalized_name_trgm", "normalized_name", postgresql_using="gin",
              postgresql_ops={"normalized_name": "gin_trgm_ops"}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Search keys of the name / legal name (legal forms, word order, French-English forms ignored; '~' consonant
    # skeletons: Arabic ~ Latin). Kept up to date on every save (before_insert / before_update below).
    search_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    legal_name: Mapped[str | None] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    domain: Mapped[str | None] = mapped_column(String(253), unique=True)
    website: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(120), index=True)
    sub_industry: Mapped[str | None] = mapped_column(String(120))
    company_type: Mapped[str | None] = mapped_column(String(60))
    employee_count_estimate: Mapped[int | None] = mapped_column(Integer)
    founded_year: Mapped[int | None] = mapped_column(SmallInteger)
    headquarters_country: Mapped[str | None] = mapped_column(String(100), index=True)
    headquarters_region: Mapped[str | None] = mapped_column(String(120))
    headquarters_city: Mapped[str | None] = mapped_column(String(120), index=True)
    primary_phone: Mapped[str | None] = mapped_column(String(50))
    primary_email: Mapped[str | None] = mapped_column(String(320))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    instagram_url: Mapped[str | None] = mapped_column(String(500))
    facebook_url: Mapped[str | None] = mapped_column(String(500))
    youtube_url: Mapped[str | None] = mapped_column(String(500))
    tiktok_url: Mapped[str | None] = mapped_column(String(500))
    twitter_url: Mapped[str | None] = mapped_column(String(500))
    # A range when only a range is published ("more than 500 employees": min 500, no max).
    employee_count_min: Mapped[int | None] = mapped_column(Integer)
    employee_count_max: Mapped[int | None] = mapped_column(Integer)
    # Company research (services/enrichment): separate from discovery and from the sales status.
    enrichment_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                                   server_default=EnrichmentStatus.NOT_STARTED.value)
    enrichment_message: Mapped[str | None] = mapped_column(String(300))  # why research is partial, for the user
    enrichment_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last successful research
    enrichment_version: Mapped[int | None] = mapped_column(SmallInteger)  # extractor version that produced it
    website_confidence: Mapped[int | None] = mapped_column(SmallInteger)  # 0-100: the website is the company's
    # People discovery (Step 5), separate from company research and from the sales status.
    people_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                               server_default=EnrichmentStatus.NOT_STARTED.value)
    people_message: Mapped[str | None] = mapped_column(String(300))
    people_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    people_version: Mapped[int | None] = mapped_column(SmallInteger)
    # Internal: which priority departments have a current decision-maker ({"executive": true, ...}).
    people_coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # field completeness per area (identity, operations, locations, people...) and what is missing: not a score
    completeness: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # deep people research (Step 5.3): when it last ran, when it may run again, what it tried
    deep_research_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_research_eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sources_attempted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # External people discovery (Step 5.1): public sources beyond the company's own website.
    external_people_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                                        server_default=EnrichmentStatus.NOT_STARTED.value)
    external_people_message: Mapped[str | None] = mapped_column(String(300))
    external_people_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Contact research (Step 6): published / predicted / verified contact points of the company's people
    contact_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                                server_default=EnrichmentStatus.NOT_STARTED.value)
    contact_message: Mapped[str | None] = mapped_column(String(300))
    contact_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Profiler agent (services/agents/profiler.py): written by a local model from the cached website pages only.
    brief: Mapped[str | None] = mapped_column(String(300))  # one line: what the company does
    profile: Mapped[str | None] = mapped_column(Text)  # a few sentences: activity, offerings, customers
    profiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # model, pages read, offerings, outcome
    # Scout agent (services/agents/scout.py): 0-100 likelihood of becoming a lead, learned from sales statuses.
    scout_score: Mapped[int | None] = mapped_column(SmallInteger)
    scout_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=CompanyStatus.NEW.value,
                                        index=True)
    status_reason: Mapped[str | None] = mapped_column(String(500))
    # Deterministic, from the evidence (services/discovery/consolidation.py); NULL for companies typed in by hand.
    identity_confidence: Mapped[str | None] = mapped_column(String(8))
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # The lead generator who found it first (permissions.can_see); defaults to its creator, managers reassign.
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True,
        default=lambda ctx: ctx.get_current_parameters().get("created_by_user_id"))


class CompanyLocation(TimestampMixin, Base):
    __tablename__ = "company_locations"
    __table_args__ = (
        confidence_check(),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"),
        # At most one headquarters per company.
        Index("uq_company_locations_headquarters", "company_id", unique=True, postgresql_where=text("is_headquarters")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    location_type: Mapped[str | None] = mapped_column(String(32))  # enums.LOCATION_TYPES, validated by the API
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    address: Mapped[str | None] = mapped_column(String(500))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    is_headquarters: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    name: Mapped[str | None] = mapped_column(String(200))  # e.g. "Zahle factory", "ABC Hamra branch"
    phone: Mapped[str | None] = mapped_column(String(50))  # E.164 when derivable
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)


class CompanyIdentifier(CreatedAtMixin, Base):
    """An identifier a source uses for this company: an Overture GERS id, an OpenStreetMap element, a
    Wikidata item, a commercial-registry number. Each (scheme, value) belongs to exactly one company, so
    seeing the same source record again always resolves to the same canonical company."""

    __tablename__ = "company_identifiers"
    __table_args__ = (UniqueConstraint("scheme", "value", name="uq_company_identifiers_scheme_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    scheme: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. "overture", "osm", "registry:LB"
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)


class PossibleDuplicate(CreatedAtMixin, Base):
    """Two companies that may be the same, on evidence too weak to merge them (e.g. the same name in
    another city). Recorded instead of merging: master data is never corrupted by a guess."""

    __tablename__ = "possible_duplicates"
    __table_args__ = (
        UniqueConstraint("company_id", "other_company_id", name="uq_possible_duplicates_pair"),
        CheckConstraint(sql_in("status", DuplicateStatus), name="status_valid"),
        CheckConstraint("company_id <> other_company_id", name="distinct_companies"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    other_company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
                                                  index=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=DuplicateStatus.OPEN.value)


class DiscoverySuppression(CreatedAtMixin, Base):
    """A source identifier or domain of a company someone deleted. Discovery skips matching records, so a
    deleted company is not silently re-created by the next search."""

    __tablename__ = "discovery_suppressions"
    __table_args__ = (UniqueConstraint("scheme", "value", name="uq_discovery_suppressions_scheme_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(String(60), nullable=False)  # an identifier scheme, or "domain"
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    deleted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CompanyStatusHistory(CreatedAtMixin, Base):
    """Append-only. Values are not CHECK-constrained: history must survive a status being retired."""

    __tablename__ = "company_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(String(500))


class OpportunityAnalysis(TimestampMixin, Base):
    """Future Sales AI output, one row per (company, solution, generation). The latest row per solution is
    current; older rows are kept as history. `fit_level` is qualitative: no scoring model exists yet."""

    __tablename__ = "opportunity_analysis"
    __table_args__ = (
        CheckConstraint(sql_in("solution", Solution), name="solution_valid"),
        CheckConstraint(f"fit_level IS NULL OR {sql_in('fit_level', FitLevel)}", name="fit_level_valid"),
        confidence_check(),
        Index("ix_opportunity_analysis_latest", "company_id", "solution", "generated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    solution: Mapped[str] = mapped_column(String(16), nullable=False)
    fit_level: Mapped[str | None] = mapped_column(String(16))
    summary: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[Any | None] = mapped_column(JSONB)
    signals: Mapped[Any | None] = mapped_column(JSONB)
    recommended_modules_or_services: Mapped[Any | None] = mapped_column(JSONB)
    # ponytail: JSON list of people.id, not FK-enforced; a bridge table when Sales AI writes these.
    recommended_person_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanySignal(Base):
    """A factual, evidence-backed characteristic of a company (enums.SIGNAL_GROUPS): it manufactures, runs a
    warehouse, uses Shopify, hires in IT, opened a branch. Never a sales judgement."""

    __tablename__ = "company_signals"
    __table_args__ = (
        Index("uq_company_signals_company_type_value", "company_id", "signal_type", "signal_value", unique=True,
              postgresql_nulls_not_distinct=True),
        Index("ix_company_signals_company_event_date", "company_id", "event_date"),
        confidence_check(),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)  # enums.SIGNAL_TYPES
    signal_value: Mapped[str | None] = mapped_column(String(300))  # "Shopify", "IT", "3", a headline
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # dated events (the company timeline): when it happened, what happened, and the event's own facts
    event_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CompanyRelationship(Base):
    """A relationship between two legal / commercial entities (parent, subsidiary, brand, branch...), from a source.
    related_company_id is set when the other entity is known to LeadFinder; entities are never merged."""

    __tablename__ = "company_relationships"
    __table_args__ = (
        UniqueConstraint("company_id", "relation_type", "related_name", name="uq_company_relationships_company_relation"),
        CheckConstraint("relation_type IN ('parent', 'ultimate_parent', 'subsidiary', 'brand', 'branch', "
                        "'operating_entity', 'holding')", name="relation_type_valid"),
        confidence_check(),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    related_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    related_name: Mapped[str] = mapped_column(String(300), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CompanyGapReason(Base):
    """Why LeadFinder has no (or few) people for a company: measured, so research targets the real cause and never
    re-runs blindly. people/gaps.py GAP_REASONS."""

    __tablename__ = "company_gap_reasons"
    __table_args__ = (Index("uq_company_gap_reasons_company_reason_source", "company_id", "gap_reason", "source_key",
                            unique=True, postgresql_nulls_not_distinct=True),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    gap_reason: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


@event.listens_for(Company, "before_insert")
@event.listens_for(Company, "before_update")
def _search_keys(mapper, connection, company: Company) -> None:
    from app.services.company_search import company_keys

    company.search_keys = company_keys(company)


class CompanyAlias(Base):
    """A name the company is known by (legal / brand / Arabic / French / abbreviation / a source's spelling). The
    canonical name is never rewritten; normalized_alias is a matching aid. A manual alias is never overwritten."""

    __tablename__ = "company_aliases"
    __table_args__ = (
        UniqueConstraint("company_id", "normalized_alias", name="uq_company_aliases_company_normalized"),
        Index("ix_company_aliases_normalized_alias_trgm", "normalized_alias", postgresql_using="gin",
              postgresql_ops={"normalized_alias": "gin_trgm_ops"}),
        CheckConstraint("alias_type IN ('legal', 'brand', 'trading', 'arabic', 'english', 'french', 'abbreviation', "
                        "'historical', 'source_variant')", name="alias_type_valid"),
        confidence_check(),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    skeleton_key: Mapped[str | None] = mapped_column(String(300), index=True)  # Arabic ~ Latin (company_search)
    language: Mapped[str | None] = mapped_column(String(8))
    alias_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CompanyDomain(Base):
    """Every domain a company is known by: its current one, others its sources list (alternate) and former ones
    (historical). One domain belongs to one company; a search for any of them finds it."""

    __tablename__ = "company_domains"
    __table_args__ = (CheckConstraint("status IN ('current', 'alternate', 'historical')", name="status_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
                                            index=True)
    domain: Mapped[str] = mapped_column(String(253), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="alternate")
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                    server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                   server_default=text("now()"))


@event.listens_for(Company, "after_insert")
@event.listens_for(Company, "after_update")
def _domains(mapper, connection, company: Company) -> None:
    """company_domains follows companies.domain: the new domain is current, a replaced one becomes historical
    (still found by search, never another company's)."""
    from sqlalchemy import inspect, update
    from sqlalchemy.dialects.postgresql import insert

    history = inspect(company).attrs.domain.history
    for old in history.deleted or ():
        if old and old != company.domain:
            connection.execute(update(CompanyDomain).where(CompanyDomain.domain == old,
                                                           CompanyDomain.company_id == company.id)
                               .values(status="historical", last_seen_at=text("now()")))
    if company.domain and (history.added or mapper is None or not history.unchanged):
        stmt = insert(CompanyDomain).values(company_id=company.id, domain=company.domain, status="current")
        connection.execute(stmt.on_conflict_do_update(
            index_elements=["domain"], set_={"status": "current", "last_seen_at": text("now()")},
            where=CompanyDomain.company_id == company.id))


class CompanyEmailPattern(Base):
    """How a company forms its people's addresses (first.last, flast...), observed on REAL published addresses of
    its people at its verified domain: the evidence behind a predicted address. Never an address itself."""

    __tablename__ = "company_email_patterns"
    __table_args__ = (UniqueConstraint("company_id", "domain", "pattern",
                                       name="uq_company_email_patterns_company_domain_pattern"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    pattern: Mapped[str] = mapped_column(String(40), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CompanyLookup(Base):
    """One direct company search (Find Leads > Search for a company): what was typed, how it resolved, how long
    it took. Product analytics, a short-lived negative cache of public-source lookups that found nothing, and the
    public-source candidates of an ambiguous lookup (the user picks one: company_lookup.select)."""

    __tablename__ = "company_lookups"
    __table_args__ = (Index("ix_company_lookups_query", "normalized_query", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_query: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    country: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # found / created / ambiguous / not_found...
    result_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    match_type: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[str | None] = mapped_column(String(12))
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    external_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    company_created: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    candidates: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    resolved_from: Mapped[str | None] = mapped_column(String(30))  # DB / ALIAS / DOMAIN / LOCAL_CORPUS / MAP...
    failure_reason: Mapped[str | None] = mapped_column(String(40))  # NO_SOURCE_RESULT / SOURCE_TIMEOUT...
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SourceLookup(Base):
    """One lookup against a public source for a company (a Common Crawl index call...): outcome and timing, so
    reliability is measured and failures are explained (failure_reason: NO_CAPTURE, NETWORK_ERROR, INDEX_ERROR,
    PARSE_ERROR, NO_USEFUL_PAGE)."""

    __tablename__ = "source_lookups"
    __table_args__ = (Index("ix_source_lookups_source_created", "source_key", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(60), nullable=False)
    target: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # ok / failed
    failure_reason: Mapped[str | None] = mapped_column(String(40))
    items: Mapped[int | None] = mapped_column(Integer)
    useful_items: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CompanyOffering(TimestampMixin, Base):
    """A product / service / category the company itself publishes (categories, not every SKU)."""

    __tablename__ = "company_products_services"
    __table_args__ = (
        CheckConstraint(sql_in("kind", OfferingKind), name="kind_valid"),
        UniqueConstraint("company_id", "kind", "normalized_name", name="uq_company_products_services_name"),
        confidence_check(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)  # as published
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)


class CompanyWebPage(TimestampMixin, Base):
    """A page of the company's website as LeadFinder last fetched it: the parsed structure (text blocks, links,
    headings, structured data; never the raw HTML) so it can be re-extracted without fetching again."""

    __tablename__ = "company_web_pages"
    __table_args__ = (UniqueConstraint("company_id", "url", name="uq_company_web_pages_company_url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)  # as requested
    canonical_url: Mapped[str | None] = mapped_column(String(2000))  # final URL / rel=canonical
    title: Mapped[str | None] = mapped_column(String(500))
    page_type: Mapped[str] = mapped_column(String(30), nullable=False)  # enums.PAGE_TYPES
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    content_hash: Mapped[str | None] = mapped_column(String(64))  # sha256 of the body
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # re-fetched after this
    extractor_version: Mapped[int | None] = mapped_column(SmallInteger)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # parsed page (services/enrichment/pages.py)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)  # error, needs_javascript, ...


class ExternalDocument(TimestampMixin, Base):
    """A public page or document outside a company's own website (conference programme, association board, news
    article, annual report PDF...), fetched once and shared by every company and person it mentions. The parsed
    text is kept (HTML: the parsed page; PDF: text per page) so it is never fetched again while fresh."""

    __tablename__ = "external_documents"
    __table_args__ = (Index("ix_external_documents_search_vector", "search_vector", postgresql_using="gin"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    url: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True)
    final_url: Mapped[str | None] = mapped_column(String(2000))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # people/external/sources.py CATEGORIES
    doc_type: Mapped[str] = mapped_column(String(10), nullable=False)  # html / pdf
    title: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)  # error, pages, truncated...
    # the local source index: full text of the document (PostgreSQL full-text search, 'simple' configuration)
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR)


class ExternalSearchCache(CreatedAtMixin, Base):
    """Results of one query to a public web search API (discovery hints only, never facts)."""

    __tablename__ = "external_search_cache"
    __table_args__ = (UniqueConstraint("provider", "query_hash", name="uq_external_search_cache_query"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
