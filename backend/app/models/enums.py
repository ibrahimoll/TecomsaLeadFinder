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
    NOT_CHECKED = "NOT_CHECKED"
    NEW = "NEW"
    EXISTING_CONTACT = "EXISTING_CONTACT"
    EXISTING_CUSTOMER = "EXISTING_CUSTOMER"
    ACTIVE_OPPORTUNITY = "ACTIVE_OPPORTUNITY"
    PREVIOUSLY_CONTACTED = "PREVIOUSLY_CONTACTED"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    CHECK_FAILED = "CHECK_FAILED"


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
    """Where a contact came from. Phase 0 only creates MANUAL contacts."""

    MANUAL = "MANUAL"


def sql_in(column: str, enum_cls: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"
