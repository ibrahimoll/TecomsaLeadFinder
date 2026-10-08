"""Import every model so Base.metadata is complete (used by Alembic)."""

from app.db.base import Base
from app.models.audit import AuditLog
from app.models.company import (Company, CompanyAlias, CompanyGapReason, CompanyIdentifier, CompanyLocation,
                                CompanyOffering, CompanyRelationship, CompanySignal, CompanyDomain, CompanyEmailPattern, CompanyLookup, SourceLookup,
                                CompanyStatusHistory, CompanyWebPage, DiscoverySuppression, ExternalDocument,
                                ExternalSearchCache, OpportunityAnalysis, PossibleDuplicate)
from app.models.integration import Integration
from app.models.people import CompanyPerson, ContactFeedback, Email, Person, Phone, PossibleDuplicatePerson
from app.models.provenance import Evidence, Source
from app.models.search import LeadSearch, LeadSearchResult, ResearchRun
from app.models.user import User, UserSession

__all__ = [
    "AuditLog",
    "Base",
    "Company",
    "CompanyIdentifier",
    "CompanyLocation",
    "CompanyOffering",
    "CompanyPerson",
    "CompanyAlias",
    "CompanyGapReason",
    "CompanyRelationship",
    "SourceLookup",
    "CompanyLookup",
    "CompanyDomain",
    "CompanyEmailPattern",
    "CompanySignal",
    "CompanyStatusHistory",
    "CompanyWebPage",
    "ContactFeedback",
    "DiscoverySuppression",
    "Email",
    "Evidence",
    "ExternalDocument",
    "ExternalSearchCache",
    "Integration",
    "LeadSearch",
    "LeadSearchResult",
    "OpportunityAnalysis",
    "Person",
    "Phone",
    "PossibleDuplicate",
    "PossibleDuplicatePerson",
    "ResearchRun",
    "Source",
    "User",
    "UserSession",
]
