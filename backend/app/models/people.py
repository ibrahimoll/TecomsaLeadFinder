from datetime import date, datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, String,
                        UniqueConstraint, false, text, true)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base, CreatedAtMixin, TimestampMixin, confidence_check
from app.models.enums import PROVENANCES, VISIBILITIES, DuplicateStatus, EmailStatus, EmploymentStatus, PhoneStatus, sql_in


class Person(TimestampMixin, Base):
    """A person, independent of any employer. Jobs live in `company_people` (one row per role)."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(300), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(150))
    last_name: Mapped[str | None] = mapped_column(String(150))
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    location_country: Mapped[str | None] = mapped_column(String(100))
    location_city: Mapped[str | None] = mapped_column(String(120))
    # A public professional profile URL published by a permitted source (never fetched).
    profile_url: Mapped[str | None] = mapped_column(String(500))


class CompanyPerson(TimestampMixin, Base):
    """Employment: a person's role at a company. Several rows per person (history, several jobs).

    Deleting a company removes these rows, never the people themselves."""

    __tablename__ = "company_people"
    __table_args__ = (
        confidence_check(),
        CheckConstraint("ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at", name="dates_ordered"),
        # The same current role twice is a duplicate; past roles with the same title are history.
        Index("uq_company_people_current_role", "company_id", "person_id", "job_title", unique=True,
              postgresql_where=text("is_current")),
        CheckConstraint(sql_in("employment_status", EmploymentStatus), name="employment_status_valid"),
        CheckConstraint("is_current = (employment_status = 'current')", name="is_current_matches_status"),
        CheckConstraint(f"visibility IN ({', '.join(repr(v) for v in VISIBILITIES)})", name="visibility_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True)
    job_title: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_title: Mapped[str | None] = mapped_column(String(300))
    department: Mapped[str | None] = mapped_column(String(40), index=True)  # enums.DEPARTMENTS
    seniority: Mapped[str | None] = mapped_column(String(40))  # enums.SENIORITIES
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    started_at: Mapped[date | None] = mapped_column(Date)
    ended_at: Mapped[date | None] = mapped_column(Date)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    # People discovery (Step 5): current / former / unknown (is_current mirrors 'current').
    employment_status: Mapped[str] = mapped_column(String(10), nullable=False,
                                                   server_default=EmploymentStatus.CURRENT.value)
    title_rank: Mapped[int | None] = mapped_column(SmallInteger)  # decision-maker order within the department
    confidence_components: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # how `confidence` was reached
    # Fields a person corrected by hand (job_title, department, seniority, employment_status): research never
    # overwrites them.
    corrected_fields: Mapped[list[str] | None] = mapped_column(JSONB)
    corrected_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, server_default="organization")

    # is_current and employment_status always agree (also a CHECK constraint): code that only sets is_current
    # (older callers) gets the matching status; research sets employment_status, then is_current.
    @validates("is_current")
    def _sync_status(self, _, value: bool) -> bool:
        status = self.__dict__.get("employment_status")
        if value and status != EmploymentStatus.CURRENT:
            self.employment_status = EmploymentStatus.CURRENT.value
        elif not value and status in (None, EmploymentStatus.CURRENT):
            self.employment_status = EmploymentStatus.FORMER.value
        return value


class PossibleDuplicatePerson(CreatedAtMixin, Base):
    """Two people at one company who may be the same person ("J. Haddad" / "John Haddad" with different roles):
    flagged for a person to decide, never merged automatically."""

    __tablename__ = "possible_duplicate_people"
    __table_args__ = (
        UniqueConstraint("person_id", "other_person_id", name="uq_possible_duplicate_people_pair"),
        CheckConstraint("person_id < other_person_id", name="ordered_pair"),
        CheckConstraint(sql_in("status", DuplicateStatus), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True)
    other_person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=DuplicateStatus.OPEN.value)


# Emails and phones belong to a person, a company, or both (a person's work address at that company).
# company_id is SET NULL so deleting a company keeps its people's contact points; a contact point that
# belongs ONLY to the company would then have no owner and is refused by `owner_present`, so
# company_service.delete_company removes those first.
_OWNER_PRESENT = "company_id IS NOT NULL OR person_id IS NOT NULL"


class Email(TimestampMixin, Base):
    __tablename__ = "emails"
    __table_args__ = (
        CheckConstraint(_OWNER_PRESENT, name="owner_present"),
        CheckConstraint(sql_in("status", EmailStatus), name="status_valid"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        # A guessed address never carries a verification date, and "verified" always does.
        CheckConstraint("status NOT IN ('predicted', 'high_confidence_predicted') OR last_verified_at IS NULL",
                        name="predicted_not_verified"),
        CheckConstraint("status <> 'verified' OR last_verified_at IS NOT NULL", name="verified_has_date"),
        CheckConstraint(f"provenance IN ({', '.join(repr(p) for p in PROVENANCES)})", name="provenance_valid"),
        CheckConstraint(f"visibility IN ({', '.join(repr(v) for v in VISIBILITIES)})", name="visibility_valid"),
        confidence_check(),
        Index("uq_emails_person_email", "person_id", "email", unique=True,
              postgresql_where=text("person_id IS NOT NULL")),
        Index("uq_emails_company_email", "company_id", "email", unique=True,
              postgresql_where=text("person_id IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    email_type: Mapped[str | None] = mapped_column(String(20))  # enums.EMAIL_TYPES
    purpose: Mapped[str | None] = mapped_column(String(20))  # enums.CONTACT_PURPOSES (company contacts)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=EmailStatus.UNKNOWN.value)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # public / predicted / verified / human_confirmed / internal_crm: research never overwrites the last two
    provenance: Mapped[str] = mapped_column(String(20), nullable=False, server_default="public")
    # TECOMSA / contributed contacts: whose they are and who sees them (enums.VISIBILITIES)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, server_default="organization")
    evidence: Mapped[str | None] = mapped_column(String(500))  # why it belongs to the person / company
    # how the address was checked: {"syntax", "mx", "provider", "catch_all", "smtp", "checked_at"}
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Phone(TimestampMixin, Base):
    __tablename__ = "phones"
    __table_args__ = (
        CheckConstraint(_OWNER_PRESENT, name="owner_present"),
        CheckConstraint(sql_in("status", PhoneStatus), name="status_valid"),
        CheckConstraint("status <> 'verified' OR last_verified_at IS NOT NULL", name="verified_has_date"),
        CheckConstraint(f"provenance IN ({', '.join(repr(p) for p in PROVENANCES)})", name="provenance_valid"),
        CheckConstraint(f"visibility IN ({', '.join(repr(v) for v in VISIBILITIES)})", name="visibility_valid"),
        confidence_check(),
        Index("uq_phones_person_phone", "person_id", "normalized_phone", unique=True,
              postgresql_where=text("person_id IS NOT NULL AND normalized_phone IS NOT NULL")),
        Index("uq_phones_company_phone", "company_id", "normalized_phone", unique=True,
              postgresql_where=text("person_id IS NULL AND normalized_phone IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)  # as published
    normalized_phone: Mapped[str | None] = mapped_column(String(20), index=True)  # E.164 when derivable
    phone_type: Mapped[str | None] = mapped_column(String(30))  # enums.PHONE_TYPES
    purpose: Mapped[str | None] = mapped_column(String(20))  # enums.CONTACT_PURPOSES (company contacts)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=PhoneStatus.UNKNOWN.value)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # public / predicted / verified / human_confirmed / internal_crm: research never overwrites the last two
    provenance: Mapped[str] = mapped_column(String(20), nullable=False, server_default="public")
    # TECOMSA / contributed contacts: whose they are and who sees them (enums.VISIBILITIES)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, server_default="organization")
    evidence: Mapped[str | None] = mapped_column(String(500))  # why it belongs to the person / company


FEEDBACK_EVENTS = ("delivered", "hard_bounce", "soft_bounce", "replied", "human_confirmed", "number_confirmed",
                   "wrong_number", "company_switchboard", "extension_confirmed", "correct_person", "wrong_person",
                   "person_left_company", "title_changed")


class ContactFeedback(Base):
    """What real sales activity showed about a person / contact point (an e-mail delivered, bounced or answered, a
    number confirmed or wrong, a person who left): recorded as it happened, applied to the contact graph at once
    (contact_feedback.apply), never generated by probing."""

    __tablename__ = "contact_feedback"
    __table_args__ = (CheckConstraint(f"event IN ({', '.join(repr(e) for e in FEEDBACK_EVENTS)})",
                                      name="event_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
                                            index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"))
    company_person_id: Mapped[int | None] = mapped_column(ForeignKey("company_people.id", ondelete="SET NULL"))
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id", ondelete="SET NULL"))
    phone_id: Mapped[int | None] = mapped_column(ForeignKey("phones.id", ondelete="SET NULL"))
    value: Mapped[str | None] = mapped_column(String(320))  # e.g. the new title
    note: Mapped[str | None] = mapped_column(String(500))
    effect: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # what it changed
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # a delivery / bounce / reply notification's own id: the same event is never applied twice
    event_key: Mapped[str | None] = mapped_column(String(200), index=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ContactEvidence(Base):
    """One observation of an e-mail / phone (its evidence trail): published by a source, predicted from a pattern,
    imported from TECOMSA, delivered, replied, bounced, confirmed by a person. Accumulated, never replaced: the
    contact's status is the strongest; its history is all of them."""

    __tablename__ = "contact_evidence"
    __table_args__ = (CheckConstraint("num_nonnulls(email_id, phone_id) = 1", name="one_contact"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"), index=True)
    phone_id: Mapped[int | None] = mapped_column(ForeignKey("phones.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    feedback_id: Mapped[int | None] = mapped_column(ForeignKey("contact_feedback.id", ondelete="SET NULL"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    detail: Mapped[str | None] = mapped_column(String(300))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  server_default=text("now()"))


class PersonSuppression(CreatedAtMixin, Base):
    """A person removed on request (privacy / right to erasure): never researched or imported again at that company.
    Only a hash of the company and the person's name key is kept, never the name."""

    __tablename__ = "person_suppressions"
    __table_args__ = (UniqueConstraint("company_id", "key_hash", name="uq_person_suppressions_company_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
