"""Enumerated values.

Two kinds, by how often they change:
* Workflow states (company status, email status, ...) are StrEnums stored as VARCHAR + CHECK constraint:
  the database refuses anything else. Adding a value = add the member + one migration that swaps the
  CHECK (no native PG enum, so no ALTER TYPE or table rewrite).
* Open taxonomies that grow with every new source or market (departments, location types, source types,
  ...) are plain VARCHAR columns validated by the API against the tuples below. Adding a value needs no
  migration.
"""

from enum import StrEnum


def sql_in(column: str, enum_cls: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    SALES_MANAGER = "SALES_MANAGER"
    SALES_AGENT = "SALES_AGENT"


# ---- workflow states (CHECK-constrained) ------------------------------------------------------------------


class CompanyStatus(StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    FOLLOW_UP = "follow_up"
    MEETING_SCHEDULED = "meeting_scheduled"
    OPPORTUNITY = "opportunity"
    WORKING_ODOO = "working_odoo"
    WORKING_FRINZO = "working_frinzo"
    WORKING_IT = "working_it"
    NOT_INTERESTED = "not_interested"
    DO_NOT_CONTACT = "do_not_contact"
    ARCHIVED = "archived"


class EmailStatus(StrEnum):
    """`predicted` (a guessed pattern such as first.last@domain) is never `verified`: they are distinct
    values of one column, and the database also refuses a predicted email with a verification date."""

    UNKNOWN = "unknown"
    DISCOVERED = "discovered"  # legacy (migrated to published)
    PUBLISHED = "published"  # explicitly published by a source (the person's own entry, a company page)
    PREDICTED = "predicted"
    # a prediction backed by >= 2 real published addresses of the company with the same pattern (still a guess)
    HIGH_CONFIDENCE_PREDICTED = "high_confidence_predicted"
    VERIFIED = "verified"  # a mailbox check said the mailbox exists
    CONFIRMED = "confirmed"  # real activity: the person replied / a colleague confirmed it
    INVALID = "invalid"
    CATCH_ALL = "catch_all"
    STALE = "stale"


class PhoneStatus(StrEnum):
    UNKNOWN = "unknown"
    DISCOVERED = "discovered"
    VERIFIED = "verified"
    INVALID = "invalid"
    STALE = "stale"


class Solution(StrEnum):
    """What TECOMSA sells. Opportunity analyses are per concrete solution (no ANY)."""

    ODOO = "odoo"
    FRINZO = "frinzo"
    IT = "it"


class SearchSolution(StrEnum):
    ANY = "any"
    ODOO = "odoo"
    FRINZO = "frinzo"
    IT = "it"


class LeadSearchStatus(StrEnum):
    PENDING = "pending"
    RESEARCHING = "researching"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ResearchRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FitLevel(StrEnum):
    """Qualitative on purpose: there is no scoring model behind it yet."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IdentityConfidence(StrEnum):
    """How sure LeadFinder is that the company exists as recorded (deterministic, from the evidence)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EnrichmentStatus(StrEnum):
    """Company research (Step 4), separate from discovery and from the sales status."""

    NOT_STARTED = "not_started"
    QUEUED = "queued"
    RESEARCHING = "researching"
    PARTIAL = "partial"  # some of the website could be used (unreachable pages, JavaScript-only, not confirmed...)
    COMPLETED = "completed"
    FAILED = "failed"  # the research itself crashed (never because a website is down)
    TIMED_OUT = "timed_out"  # stopped at its deadline: what was found is kept, the stage is finished


class EmploymentStatus(StrEnum):
    """What the evidence says about a role: listed now, ended, or not established (old / indirect evidence)."""

    CURRENT = "current"
    FORMER = "former"
    UNKNOWN = "unknown"


class OfferingKind(StrEnum):
    PRODUCT = "product"
    SERVICE = "service"
    CATEGORY = "category"


class DuplicateStatus(StrEnum):
    OPEN = "open"  # waiting for a person (or a later engine) to decide
    MERGED = "merged"
    DISTINCT = "distinct"


class IntegrationStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED = "configured"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


# ---- open taxonomies (validated by the API, not the database) ---------------------------------------------

LOCATION_TYPES = ("headquarters", "branch", "factory", "warehouse", "office", "store", "showroom", "clinic",
                  "restaurant", "service_center", "other")

DEPARTMENTS = (
    "executive", "it", "marketing", "sales", "finance", "hr", "operations", "procurement", "supply_chain",
    "customer_experience", "e_commerce", "manufacturing", "legal", "administration", "other",
)

SENIORITIES = ("owner", "c_level", "vp", "director", "head", "manager", "senior", "individual_contributor", "entry",
               "unknown", "other")

EMAIL_TYPES = ("work", "generic", "personal", "other")

PHONE_TYPES = ("landline", "mobile", "whatsapp", "office", "extension", "unknown", "direct_business_phone",
               "business_mobile", "office_extension", "company_switchboard", "unknown_business")
# where a contact point comes from: a public source, a prediction, a verification, a person, TECOMSA's own CRM
PROVENANCES = ("public", "predicted", "verified", "human_confirmed", "internal_crm", "contributed")
# who sees a TECOMSA / contributed contact or role: everyone, its owner + managers / admins, or its owner only
VISIBILITIES = ("organization", "managers", "private")

# What a company's own phone / email is published for (emails.purpose, phones.purpose).
CONTACT_PURPOSES = ("general", "info", "sales", "support", "orders", "careers", "other")

# Pages of a company website (company_web_pages.page_type).
PAGE_TYPES = ("homepage", "about", "contact", "locations", "products", "services", "manufacturing", "careers",
              "news", "team", "other")

# company_signals.signal_type: factual company intelligence from public evidence (never a sales judgement).
SIGNAL_GROUPS = {
    "activity": ("manufacturing", "distribution", "wholesale", "retail", "services", "exporting", "importing",
                 "e_commerce", "franchising", "project_based", "b2b", "b2c", "hospitality", "healthcare",
                 "construction", "professional_services", "private_label"),
    "operations": ("factory", "warehouse", "distribution_center", "branches", "retail_stores", "restaurants",
                   "clinics", "hospitals", "delivery", "field_sales", "fleet", "call_center", "customer_support",
                   "online_ordering", "appointment_booking", "multi_location", "franchise_network",
                   "service_center", "showrooms", "hospital_beds"),
    "technology": ("technology", "email_provider", "email_sending_service", "email_security", "dns_provider"),
    "hiring": ("active_careers_page", "job_openings", "hiring_department"),
    "news": ("news_new_branch", "news_new_factory", "news_expansion", "news_new_market", "news_acquisition",
             "news_product_launch", "news_partnership"),
    # dated business events (company_signals.event_date): the company timeline
    "events": ("procurement_award", "acquisition", "funding", "management_change", "factory_opening",
               "warehouse_opening", "branch_opening", "distribution_agreement", "partnership", "ecommerce_launch",
               "new_market", "new_product", "expansion", "hiring", "domain_registered", "event_participation"),
}
SIGNAL_TYPES = tuple(t for group in SIGNAL_GROUPS.values() for t in group)

SOURCE_TYPES = (
    "company_website", "government", "licensed_directory", "public_directory", "open_dataset", "public_web", "news",
    "press_release", "event", "conference", "association", "public_pdf", "review", "user_contribution",
    "imported_file", "manual", "case_study", "web_archive", "other",
    # Step 6.1 acquisition
    "exhibition", "public_document", "vcard", "internal_seed",
    # Step 6.3 contributions (what a user explicitly contributed, and how)
    "business_card", "email_signature", "meeting_contact", "contributed_contact",
)

EVIDENCE_TYPES = ("company_fact", "person_fact", "employment", "contact_point", "location", "signal", "other")

RESEARCH_TYPES = (
    "company_discovery", "company_enrichment", "people_discovery", "external_people", "contact_discovery", "reviews",
    "deep_research", "refresh",
)
