"""Enumerated values. Stored as VARCHAR + CHECK constraint (easier to evolve than native PG enums)."""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    SALES_MANAGER = "SALES_MANAGER"
    SALES_AGENT = "SALES_AGENT"


class Division(StrEnum):
    FRINZO = "FRINZO"
    ODOO = "ODOO"
    IT = "IT"


class CampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CampaignCompanyStatus(StrEnum):
    ADDED = "ADDED"
    REVIEW = "REVIEW"
    REMOVED = "REMOVED"


class QualificationStatus(StrEnum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class OdooMatchStatus(StrEnum):
    """A company's relationship with TECOMSA according to Odoo data.

    NOT_CHECKED means no Odoo data has been imported yet, so LeadFinder cannot
    honestly say whether the company is new. AVAILABLE means Odoo data exists
    and nothing in it matches this company.
    """

    NOT_CHECKED = "NOT_CHECKED"
    AVAILABLE = "AVAILABLE"
    EXISTING_CONTACT = "EXISTING_CONTACT"
    EXISTING_LEAD = "EXISTING_LEAD"
    EXISTING_OPPORTUNITY = "EXISTING_OPPORTUNITY"
    CUSTOMER = "CUSTOMER"
    LOST_OPPORTUNITY = "LOST_OPPORTUNITY"
    PREVIOUSLY_CONTACTED = "PREVIOUSLY_CONTACTED"
    CHECK_FAILED = "CHECK_FAILED"


# Statuses that mean TECOMSA already has a relationship: never treat as a new prospect.
PROTECTED_STATUSES = frozenset(
    {
        OdooMatchStatus.EXISTING_CONTACT,
        OdooMatchStatus.EXISTING_LEAD,
        OdooMatchStatus.EXISTING_OPPORTUNITY,
        OdooMatchStatus.CUSTOMER,
        OdooMatchStatus.LOST_OPPORTUNITY,
        OdooMatchStatus.PREVIOUSLY_CONTACTED,
    }
)


class CompanySource(StrEnum):
    MANUAL = "MANUAL"
    ODOO_IMPORT = "ODOO_IMPORT"
    DEMO = "DEMO"
    DISCOVERY = "DISCOVERY"  # found automatically by a discovery run (e.g. Overture Maps)


class ImportType(StrEnum):
    ODOO_CRM = "ODOO_CRM"
    ODOO_CONTACTS = "ODOO_CONTACTS"


class ImportStatus(StrEnum):
    PREVIEW = "PREVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CrmLeadType(StrEnum):
    LEAD = "LEAD"
    OPPORTUNITY = "OPPORTUNITY"


class LushaActionType(StrEnum):
    COMPANY_SEARCH = "COMPANY_SEARCH"
    CONTACT_SEARCH = "CONTACT_SEARCH"
    EMAIL_REVEAL = "EMAIL_REVEAL"
    PHONE_REVEAL = "PHONE_REVEAL"
    OTHER = "OTHER"


class ActivityType(StrEnum):
    COMPANY_CREATED = "COMPANY_CREATED"
    CAMPAIGN_CREATED = "CAMPAIGN_CREATED"
    COMPANY_ADDED_TO_CAMPAIGN = "COMPANY_ADDED_TO_CAMPAIGN"
    CONTACT_ADDED = "CONTACT_ADDED"
    NOTE_ADDED = "NOTE_ADDED"


class ContactSource(StrEnum):
    """Where a contact came from."""

    MANUAL = "MANUAL"
    ODOO_IMPORT = "ODOO_IMPORT"  # a person from an Odoo contacts import


def sql_in(column: str, enum_cls: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"


class DiscoveryStatus(StrEnum):
    QUEUED = "QUEUED"
    SEARCHING = "SEARCHING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"  # partially completed: some results were saved but a source failed
    FAILED = "FAILED"


ACTIVE_DISCOVERY_STATUSES = frozenset(
    {DiscoveryStatus.QUEUED, DiscoveryStatus.SEARCHING, DiscoveryStatus.PROCESSING}
)


class DiscoveryState(StrEnum):
    """What LeadFinder concluded about one discovered candidate."""

    AVAILABLE = "AVAILABLE"  # new company with no known relationship: saved to LeadFinder
    EXISTING_LEADFINDER = "EXISTING_LEADFINDER"  # already in LeadFinder, not protected
    EXISTING_ODOO_CONTACT = "EXISTING_ODOO_CONTACT"
    EXISTING_CRM_LEAD = "EXISTING_CRM_LEAD"
    OPEN_OPPORTUNITY = "OPEN_OPPORTUNITY"
    CUSTOMER = "CUSTOMER"
    LOST_OPPORTUNITY = "LOST_OPPORTUNITY"
    PROTECTED = "PROTECTED"  # another protected relationship (e.g. previously contacted)
    DUPLICATE = "DUPLICATE"  # the same company as an earlier result in this run


PROTECTED_DISCOVERY_STATES = frozenset(
    {
        DiscoveryState.EXISTING_ODOO_CONTACT,
        DiscoveryState.EXISTING_CRM_LEAD,
        DiscoveryState.OPEN_OPPORTUNITY,
        DiscoveryState.CUSTOMER,
        DiscoveryState.LOST_OPPORTUNITY,
        DiscoveryState.PROTECTED,
    }
)

# TECOMSA relationship status -> discovery state.
DISCOVERY_STATE_FOR_STATUS = {
    OdooMatchStatus.EXISTING_CONTACT: DiscoveryState.EXISTING_ODOO_CONTACT,
    OdooMatchStatus.EXISTING_LEAD: DiscoveryState.EXISTING_CRM_LEAD,
    OdooMatchStatus.EXISTING_OPPORTUNITY: DiscoveryState.OPEN_OPPORTUNITY,
    OdooMatchStatus.CUSTOMER: DiscoveryState.CUSTOMER,
    OdooMatchStatus.LOST_OPPORTUNITY: DiscoveryState.LOST_OPPORTUNITY,
    OdooMatchStatus.PREVIOUSLY_CONTACTED: DiscoveryState.PROTECTED,
}
