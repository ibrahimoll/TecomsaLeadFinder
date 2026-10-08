"""Target fields for Odoo imports, header auto-detection and value conversion.

Aliases cover Odoo's default export labels (English UI) plus common variants. Headers
are compared ignoring case, spaces, underscores and hyphens. There is no manual
mapping: columns that match no alias are ignored.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from email_validator import EmailNotValidError, EmailSyntaxError, validate_email

from app.models.enums import CrmLeadType, ImportType
from app.services.normalization import normalize_company_name


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str  # text | odoo_id | bool | customer | company_type | date | decimal | email | lead_type
    aliases: tuple[str, ...]
    required: bool = False
    important: bool = False
    max_length: int | None = None
    internal: bool = False  # detected and used, but not shown in the preview


CRM_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("odoo_id", "Odoo ID", "odoo_id", ("id", "external id", "lead id", "opportunity id", "record id"), important=True),
    FieldSpec("opportunity_name", "Opportunity / lead name", "text",
              ("opportunity", "name", "lead", "subject", "title", "opportunity name", "lead name"), required=True, max_length=500),
    FieldSpec("company_name", "Customer / company", "text",
              ("customer", "company name", "company", "partner", "customer name", "customer/name", "partner/name",
               "partner name", "customer/display name"), important=True, max_length=255),
    FieldSpec("contact_name", "Contact name", "text", ("contact name", "contact", "contact person"), max_length=255),
    FieldSpec("email", "Email", "email", ("email", "email from", "e-mail", "customer email")),
    FieldSpec("phone", "Phone", "text", ("phone", "telephone", "phone number"), max_length=50),
    FieldSpec("mobile", "Mobile", "text", ("mobile", "mobile phone", "cell"), max_length=50),
    FieldSpec("website", "Website", "text", ("website", "web site", "url"), max_length=500),
    FieldSpec("city", "City", "text", ("city",), max_length=100),
    FieldSpec("country", "Country", "text", ("country", "country/name"), max_length=100),
    FieldSpec("salesperson", "Salesperson", "text",
              ("salesperson", "sales person", "user", "assigned to", "salesperson/name", "user/name"), important=True, max_length=200),
    FieldSpec("sales_team", "Sales team", "text", ("sales team", "team", "sales team/name"), max_length=200),
    FieldSpec("stage", "Stage", "text", ("stage", "stage/name", "pipeline stage"), important=True, max_length=200),
    FieldSpec("lead_type", "Type (lead / opportunity)", "lead_type", ("type", "lead type")),
    FieldSpec("expected_revenue", "Expected revenue", "decimal", ("expected revenue", "planned revenue", "revenue")),
    FieldSpec("probability", "Probability (%)", "decimal", ("probability", "success rate")),
    FieldSpec("active", "Active", "bool", ("active",)),
    FieldSpec("lost_reason", "Lost reason", "text", ("lost reason", "lost reason/name", "lost_reason")),
    FieldSpec("created_date", "Created on", "date", ("created on", "create date", "creation date", "created")),
    FieldSpec("updated_date", "Last updated on", "date", ("last updated on", "last update", "updated on", "write date",
                                                           "last modified")),
    FieldSpec("last_activity", "Last activity / stage update", "date",
              ("last activity", "last stage update", "date of last activity", "last action")),
)

# Odoo contacts: only what TECOMSA needs from the export. `odoo_id`, `parent_company` and
# `is_company` are read silently when present (stable re-imports, company fallback,
# telling company rows from people) and are not shown in the preview.
CONTACT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("company_name", "Company Name", "text",
              ("company name", "company", "organisation", "organization", "organisation name", "organization name",
               "parent company", "company/name", "company_id", "company id"), max_length=255, important=True),
    FieldSpec("contact_name", "Contact Name", "text",
              ("name", "contact name", "contact", "full name", "display name", "complete name", "partner name",
               "contact/name"), max_length=255, important=True),
    FieldSpec("job_position", "Job Position", "text",
              ("job position", "position", "job title", "function", "title", "job"), max_length=200, important=True),
    FieldSpec("mobile", "Mobile", "text", ("mobile", "mobile number", "mobile phone", "cell", "cell phone"),
              max_length=50),
    FieldSpec("phone", "Phone", "text", ("phone", "phone number", "telephone", "tel", "telephone number"),
              max_length=50),
    FieldSpec("email", "Email", "email", ("email", "email address", "work email", "e-mail", "mail"), important=True),
    FieldSpec("country", "Country", "text", ("country", "country name", "country/name", "country_id", "country id"),
              max_length=100, important=True),
    FieldSpec("city", "City", "text", ("city", "town"), max_length=100, important=True),
    FieldSpec("odoo_id", "Odoo ID", "odoo_id", ("id", "external id", "partner id", "contact id", "record id"),
              internal=True),
    FieldSpec("parent_company", "Related company", "text",
              ("related company", "parent", "parent company", "parent/name", "parent/display name", "parent_id",
               "parent id", "company"), max_length=255, internal=True),
    FieldSpec("is_company", "Is a company", "company_type", ("is a company", "company type", "is company"),
              internal=True),
)

FIELDS: dict[str, tuple[FieldSpec, ...]] = {ImportType.ODOO_CRM: CRM_FIELDS, ImportType.ODOO_CONTACTS: CONTACT_FIELDS}


def _norm_header(value: str) -> str:
    """'Company Name', 'company_name', 'COMPANY-NAME' -> 'companyname'."""
    return re.sub(r"[^a-z0-9/]", "", value.lower())


def auto_map(import_type: str, columns: list[str]) -> dict[str, str]:
    """Map target fields to source columns by alias (first alias match wins, one column per field).

    Odoo relational headers such as 'Country/Name' also match on their first part ('Country').
    """
    by_norm = {_norm_header(c): c for c in columns}
    for c in columns:
        if "/" in c:
            by_norm.setdefault(_norm_header(c.split("/", 1)[0]), c)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for spec in FIELDS[import_type]:
        for alias in (spec.label, *spec.aliases):
            column = by_norm.get(_norm_header(alias))
            if column and column not in used:
                mapping[spec.key] = column
                used.add(column)
                break
    return mapping


# ---- value conversion -------------------------------------------------------

_SIMPLE_EMAIL = re.compile(r"^[^@\s]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")
_TRUE = {"true", "1", "yes", "y", "x", "t", "✓", "vrai", "oui"}
_FALSE = {"false", "0", "no", "n", "f", "", "faux", "non"}
_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                 "%d/%m/%Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d")


def _as_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def convert(spec: FieldSpec, value: Any) -> tuple[Any, str | None]:
    """Returns (converted value, warning). Empty cells convert to None without warning."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    kind = spec.kind
    if kind == "text":
        text = " ".join(_as_text(value).split())
        if spec.max_length and len(text) > spec.max_length:
            return text[: spec.max_length], f"{spec.label} truncated to {spec.max_length} characters"
        return text, None
    if kind == "odoo_id":
        if isinstance(value, (int, float)) and float(value).is_integer():
            return int(value), None
        text = _as_text(value)
        if text.isdigit():
            return int(text), None
        match = re.search(r"_(\d+)(?:_[0-9a-f]+)?$", text)  # e.g. __export__.crm_lead_42_ab12cd
        return {"external": text[:255], "id": int(match.group(1)) if match else None}, None
    if kind in ("bool", "company_type", "customer"):
        if isinstance(value, bool):
            return value, None
        if isinstance(value, (int, float)):
            return value > 0, None
        text = _as_text(value).lower()
        if kind == "company_type":
            if text in ("company", "is a company", "organisation", "organization"):
                return True, None
            if text in ("individual", "person", "contact"):
                return False, None
        if kind == "customer" and text.replace(".", "", 1).isdigit():
            return float(text) > 0, None
        if text in _TRUE:
            return True, None
        if text in _FALSE:
            return False, None
        return None, f"{spec.label}: '{text[:40]}' is not a yes/no value"
    if kind == "date":
        if isinstance(value, datetime):
            return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)), None
        text = _as_text(value)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc), None
            except ValueError:
                continue
        return None, f"{spec.label}: '{text[:40]}' is not a recognised date"
    if kind == "decimal":
        if isinstance(value, (int, float)):
            return Decimal(str(value)), None
        text = re.sub(r"[^\d.,\-]", "", _as_text(value))
        if text.count(",") and text.count("."):
            text = text.replace(",", "")
        elif text.count(",") == 1 and len(text.split(",")[1]) != 3:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
        try:
            return Decimal(text), None
        except InvalidOperation:
            return None, f"{spec.label}: '{_as_text(value)[:40]}' is not a number"
    if kind == "email":
        text = _as_text(value).lower()
        try:
            return validate_email(text, check_deliverability=False).normalized.lower(), None
        except EmailSyntaxError as exc:
            # Reserved domains (.test, .local, .internal...) are syntactically fine but "not
            # deliverable"; keep them: they are what the Odoo record says.
            if "special-use or reserved" in str(exc) and _SIMPLE_EMAIL.match(text):
                return text, None
            return None, f"Email '{text[:60]}' is not valid and was ignored"
        except EmailNotValidError:
            return None, f"Email '{text[:60]}' is not valid and was ignored"
    if kind == "lead_type":
        text = _as_text(value).lower()
        if text.startswith("lead"):
            return CrmLeadType.LEAD, None
        if text.startswith("opportunit"):
            return CrmLeadType.OPPORTUNITY, None
        return None, f"Type '{text[:40]}' is not Lead or Opportunity; treated as Opportunity"
    raise AssertionError(f"unknown kind {kind}")


def source_key(odoo_id: Any, *parts: Any) -> str:
    """Stable identity for idempotent re-imports."""
    if isinstance(odoo_id, int):
        return f"id:{odoo_id}"
    if isinstance(odoo_id, dict) and odoo_id.get("external"):
        return f"xid:{odoo_id['external']}"[:128]
    material = "|".join(
        normalize_company_name(str(p)) if isinstance(p, str) else ("" if p is None else str(p)) for p in parts
    )
    return "h:" + hashlib.sha1(material.encode("utf-8")).hexdigest()


def odoo_int_id(odoo_id: Any) -> int | None:
    if isinstance(odoo_id, int):
        return odoo_id
    if isinstance(odoo_id, dict):
        return odoo_id.get("id")
    return None


def odoo_external_id(odoo_id: Any) -> str | None:
    return odoo_id.get("external") if isinstance(odoo_id, dict) else None


# What must be detected for a file to be importable at all.
ESSENTIAL: dict[str, tuple[tuple[str, ...], str]] = {
    # A CRM record needs its own name: a file with only company/contact columns is a
    # contacts list and must never be turned into opportunities.
    ImportType.ODOO_CRM: (("opportunity_name",), "Opportunity or Lead name column"),
    ImportType.ODOO_CONTACTS: (("company_name", "contact_name", "parent_company"),
                               "Company Name or Contact Name column"),
}


def missing_essentials(import_type: str, mapping: dict[str, str]) -> str | None:
    """A readable description of what is missing, or None when the file can be imported."""
    keys, description = ESSENTIAL[import_type]
    return None if any(k in mapping for k in keys) else description
