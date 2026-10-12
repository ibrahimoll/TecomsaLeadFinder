from datetime import date, datetime
from typing import Any

from pydantic import EmailStr, Field, field_validator

from app.models.enums import DEPARTMENTS, SENIORITIES, CompanyStatus, EmploymentStatus, FitLevel, Solution
from app.schemas.common import InModel, OutModel, require_value, validate_http_url, validate_phone
from app.services.normalization import normalize_website


class _CompanyFields(InModel):
    """Basic, user-editable company fields. Status, provenance and research timestamps are not here:
    status changes go through PATCH /companies/{id}/status, the rest is written by the system."""

    legal_name: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    # Derived from `website` when omitted; must be the company's own domain (not a social/maps host).
    domain: str | None = Field(default=None, max_length=253)
    description: str | None = Field(default=None, max_length=5000)
    industry: str | None = Field(default=None, max_length=120)
    sub_industry: str | None = Field(default=None, max_length=120)
    company_type: str | None = Field(default=None, max_length=60)
    employee_count_estimate: int | None = Field(default=None, gt=0, le=10_000_000)
    founded_year: int | None = Field(default=None, ge=1700, le=2100)
    headquarters_country: str | None = Field(default=None, max_length=100)
    headquarters_region: str | None = Field(default=None, max_length=120)
    headquarters_city: str | None = Field(default=None, max_length=120)
    primary_phone: str | None = Field(default=None, max_length=50)
    primary_email: EmailStr | None = Field(default=None, max_length=320)
    linkedin_url: str | None = Field(default=None, max_length=500)
    instagram_url: str | None = Field(default=None, max_length=500)
    facebook_url: str | None = Field(default=None, max_length=500)

    @field_validator("website")
    @classmethod
    def _website(cls, v: str | None) -> str | None:
        return validate_http_url(normalize_website(v))

    @field_validator("linkedin_url", "instagram_url", "facebook_url")
    @classmethod
    def _urls(cls, v: str | None) -> str | None:
        return validate_http_url(v)

    @field_validator("primary_phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return validate_phone(v)

    @field_validator("primary_email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return v.lower() if v else v


class CompanyCreate(_CompanyFields):
    name: str = Field(min_length=1, max_length=300)


class CompanyUpdate(_CompanyFields):
    name: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("name")
    @classmethod
    def _not_null(cls, v, info):
        return require_value(v, info.field_name)


class CompanyOwnerUpdate(InModel):
    owner_user_id: int | None  # None: unassigned (managers / admins only)


class CompanyStatusUpdate(InModel):
    status: CompanyStatus
    reason: str | None = Field(default=None, max_length=500)


class CompanyOut(OutModel):
    id: int
    name: str
    legal_name: str | None
    normalized_name: str
    domain: str | None
    website: str | None
    description: str | None
    industry: str | None
    sub_industry: str | None
    company_type: str | None
    employee_count_estimate: int | None
    founded_year: int | None
    headquarters_country: str | None
    headquarters_region: str | None
    headquarters_city: str | None
    primary_phone: str | None
    primary_email: str | None
    linkedin_url: str | None
    instagram_url: str | None
    facebook_url: str | None
    youtube_url: str | None = None
    tiktok_url: str | None = None
    twitter_url: str | None = None
    employee_count_min: int | None = None
    employee_count_max: int | None = None
    status: CompanyStatus
    status_reason: str | None
    owner_user_id: int | None = None  # the lead generator who owns it (permissions.can_see)
    # the list's decoration (company_service.decorate): current people, mobiles / WhatsApp, rules-based fit
    people_count: int | None = None
    mobile_count: int | None = None
    fit: list[dict[str, Any]] | None = None
    identity_confidence: str | None
    # Company research (Step 4), separate from discovery and from the sales status.
    enrichment_status: str = "not_started"
    enrichment_message: str | None = None
    people_status: str = "not_started"  # people discovery, separate from company research
    people_message: str | None = None
    people_researched_at: datetime | None = None
    external_people_status: str = "not_started"  # people from public sources beyond the website
    external_people_researched_at: datetime | None = None
    contact_status: str = "not_started"
    contact_message: str | None = None
    contact_researched_at: datetime | None = None
    # Agents: the Profiler's brief / description (local model, from the website) and the Scout's learned score
    brief: str | None = None
    profile: str | None = None
    profiled_at: datetime | None = None
    scout_score: int | None = None
    scout_reasons: list[str] | None = None
    last_enriched_at: datetime | None = None
    website_confidence: int | None = None
    last_researched_at: datetime | None
    last_verified_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class LocationOut(OutModel):
    id: int
    location_type: str | None
    country: str
    region: str | None
    city: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    is_headquarters: bool
    name: str | None = None
    phone: str | None = None
    source_id: int | None
    confidence: int | None


class EmailOut(OutModel):
    id: int
    email: str
    email_type: str | None
    purpose: str | None = None
    status: str  # published / predicted / verified / catch_all / invalid / unknown: never mixed up
    provenance: str = "public"
    evidence: str | None = None
    is_primary: bool
    is_public: bool
    confidence: int | None
    source_id: int | None
    last_verified_at: datetime | None


class PhoneOut(OutModel):
    id: int
    phone: str
    normalized_phone: str | None
    phone_type: str | None  # business_mobile / direct_business_phone / office_extension / whatsapp / ...
    purpose: str | None = None
    status: str
    provenance: str = "public"
    evidence: str | None = None
    is_primary: bool
    is_public: bool
    confidence: int | None
    source_id: int | None
    last_verified_at: datetime | None


class PersonOut(OutModel):
    id: int
    full_name: str
    first_name: str | None
    last_name: str | None
    location_country: str | None
    location_city: str | None
    profile_url: str | None = None


class RoleSourceOut(OutModel):
    id: int
    name: str | None
    url: str | None
    page_type: str | None = None
    source_type: str | None = None  # company_website / conference / association / news / public_pdf...
    page: int | None = None  # PDF page


class ContactOut(OutModel):
    kind: str  # verified_email / published_email / business_mobile / direct_business_phone / whatsapp /
    #            office_extension / catch_all_email / predicted_email (strongest first)
    value: str
    label: str
    since: str | None = None  # last confirmed (else last seen), ISO date
    stale: bool = False  # older than two years: possibly outdated


class CompanyPersonOut(OutModel):
    """One role at the company, with the person and their contact points relevant to this company."""

    id: int
    person: PersonOut
    job_title: str
    normalized_title: str | None
    department: str | None
    seniority: str | None
    is_current: bool
    started_at: date | None
    ended_at: date | None
    confidence: int | None
    last_verified_at: datetime | None
    primary_source_id: int | None
    emails: list[EmailOut]
    phones: list[PhoneOut]
    # People discovery (Step 5)
    employment_status: EmploymentStatus = EmploymentStatus.CURRENT
    title_rank: int | None = None
    is_key: bool = False  # the department's first decision-maker (current, most senior, best evidence)
    sources: list[RoleSourceOut] = []  # where this role is stated
    contacts: list[ContactOut] = []  # how to reach the person, strongest first (labelled: published / predicted...)
    contactable: bool = False  # a usable business channel (a predicted address alone is not one)
    confirmed_at: datetime | None = None  # a colleague confirmed the person or a number (contact feedback)
    corrected_fields: list[str] | None = None  # corrected by hand: research does not change these
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class ContactFeedbackIn(InModel):
    """A sales feedback event: what real outreach / a call showed about a person or one of their contacts."""

    event: str = Field(max_length=30)
    email_id: int | None = None
    phone_id: int | None = None
    company_person_id: int | None = None
    value: str | None = Field(default=None, max_length=320)
    note: str | None = Field(default=None, max_length=500)
    event_key: str | None = Field(default=None, max_length=200)  # the notification's own id: applied once


class ContributionIn(InModel):
    """One business contact a user contributes on a company's page (a card, a signature, a meeting, by hand).
    `signature`: a pasted professional e-mail signature, read for the fields not given."""

    channel: str = Field(default="CONTRIBUTED_BUSINESS_CONTACT", max_length=40)
    person: str | None = Field(default=None, max_length=300)
    title: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    mobile: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=50)
    whatsapp: str | None = Field(default=None, max_length=50)
    extension: str | None = Field(default=None, max_length=10)
    signature: str | None = Field(default=None, max_length=3000)
    visibility: str = Field(default="organization", max_length=20)


class ContactEventIn(InModel):
    """A delivery / bounce / reply notification for an address (no company needed)."""

    event: str = Field(max_length=30)
    email: str = Field(min_length=3, max_length=320)
    event_key: str | None = Field(default=None, max_length=200)


class CompanyPersonCorrection(InModel):
    """A person's correction of a researched role; the corrected fields are protected from research."""

    job_title: str | None = Field(default=None, min_length=1, max_length=300)
    department: str | None = None
    seniority: str | None = None
    employment_status: EmploymentStatus | None = None

    @field_validator("department")
    @classmethod
    def _department(cls, v: str | None) -> str | None:
        if v is not None and v not in DEPARTMENTS:
            raise ValueError(f"department must be one of {', '.join(DEPARTMENTS)}")
        return v

    @field_validator("seniority")
    @classmethod
    def _seniority(cls, v: str | None) -> str | None:
        if v is not None and v not in SENIORITIES:
            raise ValueError(f"seniority must be one of {', '.join(SENIORITIES)}")
        return v


class OpportunityOut(OutModel):
    id: int
    solution: Solution
    fit_level: FitLevel | None
    summary: str | None
    reasoning: Any | None
    signals: Any | None
    recommended_modules_or_services: Any | None
    recommended_person_ids: list[int] | None
    confidence: int | None
    generated_at: datetime
    expires_at: datetime | None


class FitReasonOut(OutModel):
    why: str
    evidence: str
    points: int


class FitPersonOut(OutModel):
    id: int
    name: str
    title: str | None


class OpportunityFitOut(OutModel):
    """Rules-based fit for one solution (services/opportunity.py): every point with its evidence."""

    solution: Solution
    label: str
    fit_level: FitLevel
    points: int
    reasons: list[FitReasonOut]
    pitch: list[str]
    call: list[str]
    people: list[FitPersonOut]
    note: str | None = None


class SourceSummaryOut(OutModel):
    id: int
    source_type: str
    name: str | None
    url: str | None
    publisher: str | None
    retrieved_at: datetime | None
    source_quality: int | None
    evidence_count: int
    page_type: str | None = None  # for the company's own website pages
    facts: list[str] = []  # the fields this source supports (description, phone, factory...)


class SignalOut(OutModel):
    id: int
    signal_type: str
    group: str  # enums.SIGNAL_GROUPS: activity / operations / technology / hiring / news
    signal_value: str | None
    confidence: int | None
    source_id: int
    observed_at: datetime | None
    event_date: date | None = None  # dated business events (the timeline)
    description: str | None = None


class RelationshipOut(OutModel):
    relation_type: str  # parent / ultimate_parent / subsidiary / brand / branch / operating_entity / holding
    related_name: str
    related_company_id: int | None
    source_id: int


class RelatedGroupPersonOut(OutModel):
    """A person of the company's parent / group (their employer), shown as a possibly relevant group-level contact:
    never an employee of this company."""

    person_id: int
    full_name: str
    job_title: str
    department: str | None
    employment_status: str
    employer_id: int
    employer_name: str
    relation_type: str  # the employer is this company's parent / ultimate_parent


class OfferingOut(OutModel):
    id: int
    kind: str  # product / service / category
    raw_name: str
    confidence: int | None
    source_id: int


class ConflictOut(OutModel):
    field: str
    values: list[dict[str, Any]]  # [{value, confidence, source}], strongest first


class CompanySearchHit(OutModel):
    """A company (or a public-source candidate: company_id null, pick_index set) matching a direct search."""

    company_id: int | None = None
    name: str
    legal_name: str | None = None
    city: str | None = None
    country: str | None = None
    industry: str | None = None
    website: str | None = None
    domain: str | None = None
    match_type: str | None = None  # domain / identifier / exact_name / exact_alias / normalized_name / alias /
    #                                brand_core / transliteration / contains / fuzzy / source_* ...
    confidence: str | None = None  # exact / strong / possible / weak
    detail: str | None = None
    source: str | None = None  # a public-source candidate's source
    pick_index: int | None = None


class CompanyLookupIn(InModel):
    q: str = Field(min_length=2, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=120)


class CompanyLookupPick(InModel):
    index: int = Field(ge=0, le=50)


class CompanyLookupOut(OutModel):
    """found / created: open `company`; ambiguous: the user picks one of `candidates`; not_found / timed_out:
    nothing verified. Every lookup ends in one of these (no waiting on company research)."""

    lookup_id: int | None = None
    query: str
    status: str
    company: CompanySearchHit | None = None
    candidates: list[CompanySearchHit] = []
    match_type: str | None = None
    confidence: str | None = None
    external_used: bool = False
    created: bool = False
    sources: list[dict[str, Any]] = []
    parsed: dict[str, Any] = {}  # what the query was understood as (name, place, industry, domain...)
    resolved_from: str | None = None  # DB / ALIAS / DOMAIN / LOCAL_CORPUS:... / MAP / WEB_DISCOVERY / GLEIF...
    failure_reason: str | None = None  # NO_LOCAL_MATCH / NO_SOURCE_RESULT / SOURCE_TIMEOUT / WEAK_EVIDENCE...
    duration_ms: int | None = None


class PeopleResearchOut(OutModel):
    """The one people-research state the UI follows (services/people/orchestrator.research_state). It polls only
    while the state is website_* / deep_*; completed / partial / failed / timed_out / idle are final."""

    state: str
    stage: str  # website / deep: the stage running now, or the last one that ran
    website_status: str
    external_status: str
    people_count: int
    finished_at: datetime | None = None
    message: str | None = None
    gap_reasons: list[str] = []  # why no one was found (final state, zero people)


class CompanyDetail(OutModel):
    company: CompanyOut
    people_research: PeopleResearchOut | None = None
    locations: list[LocationOut]
    people: list[CompanyPersonOut]
    emails: list[EmailOut]  # the company's own (not a person's)
    phones: list[PhoneOut]
    opportunities: list[OpportunityOut]  # latest analysis per solution
    fit: list[OpportunityFitOut] = []  # rules-based fit per solution, computed live
    pitch_configured: bool = False  # Claude can write pitches (ANTHROPIC_API_KEY)
    sources: list[SourceSummaryOut]
    signals: list[SignalOut] = []
    relationships: list[RelationshipOut] = []  # parent / subsidiary... (entities are never merged)
    related_group_people: list[RelatedGroupPersonOut] = []  # the group's people (employed by the group, not here)
    offerings: list[OfferingOut] = []  # products / services / categories
    conflicts: list[ConflictOut] = []  # fields whose sources disagree
    overview: str | None = None  # factual summary built only from the stored fields (no AI)


class PersonRemovalIn(InModel):
    """A removal request (the person asked to be deleted, or no lawful basis to keep them): who asked, how."""

    reason: str = Field(min_length=3, max_length=300)
