"""Provenance: SOURCE -> EVIDENCE -> normalized data (companies, people, emails, ...).

A source is one retrieved document or record (a web page, a directory entry, a PDF, an imported file
row, a manual entry). Evidence is one fact observed in it about a company, a person or an employment.
Together they answer: where did this come from, when was it observed, how confident are we.

Sources are never deleted while anything cites them (every FK to `sources` is RESTRICT).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, confidence_check


class Source(CreatedAtMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (confidence_check("source_quality"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # enums.SOURCE_TYPES
    name: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(2000), index=True)
    external_reference: Mapped[str | None] = mapped_column(String(300))  # id in the publisher's system
    publisher: Mapped[str | None] = mapped_column(String(300))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_quality: Mapped[int | None] = mapped_column(SmallInteger)  # 0-100
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # e.g. sha256 of the retrieved body
    # `metadata` is reserved on declarative classes, hence the attribute name.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class Evidence(CreatedAtMixin, Base):
    """One observed fact, e.g. source abcfoods.example/team says person "Rami Khoury" has
    field_name="job_title", extracted_value="IT Manager" at company "ABC Foods"."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint("num_nonnulls(company_id, person_id, company_person_id) >= 1", name="subject_present"),
        confidence_check(),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Evidence is about its subject: it goes when the subject is deleted; the source stays.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    company_person_id: Mapped[int | None] = mapped_column(ForeignKey("company_people.id", ondelete="CASCADE"),
                                                          index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False)  # enums.EVIDENCE_TYPES
    field_name: Mapped[str | None] = mapped_column(String(100))
    extracted_value: Mapped[str | None] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text)
    structured_value: Mapped[Any | None] = mapped_column(JSONB)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
