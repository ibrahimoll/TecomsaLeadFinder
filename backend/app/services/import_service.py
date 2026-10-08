"""Odoo CSV/XLSX import workflow.

upload → (parse, detect columns, validate, detect duplicates) → preview
       → confirm → upsert records, link/create companies, recompute relationships
Nothing is written to the Odoo tables before the user confirms. Columns are detected
from the headers; there is no manual mapping step.

Every record, company and salesperson remembers the import that owns it
(`created_by_import_id`: the one that created it, or the next import containing it once
its owner was deleted), so an import can later be deleted with or without its data.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models import (
    CampaignCompany,
    Company,
    Contact,
    CrmLead,
    ImportRun,
    LeadActivity,
    LushaUsage,
    OdooContact,
    Salesperson,
    User,
)
from app.models.enums import CompanySource, ContactSource, CrmLeadType, ImportStatus, ImportType
from app.services import audit_service, relationship_service
from app.services.audit_service import AuditAction
from app.services.import_fields import (
    FIELDS,
    FieldSpec,
    auto_map,
    convert,
    missing_essentials,
    odoo_external_id,
    odoo_int_id,
    source_key,
)
from app.services.import_parser import ParsedFile, detect_file_type, parse_file
from app.services.matching_service import CompanyIndex, MatchSignals
from app.services.normalization import (
    company_domain,
    email_domain,
    has_legal_form,
    normalize_company_name,
    normalize_domain,
    normalize_phone,
    normalize_website,
)
from app.services.pagination import PageParams, paginate
from app.services.salesperson_service import SalespersonResolver

logger = logging.getLogger(__name__)

MAX_ISSUES = 200
SAMPLE_ROWS = 50
SOURCE_PREFIX = {ImportType.ODOO_CRM: "odoo-crm-import", ImportType.ODOO_CONTACTS: "odoo-contacts-import"}
TYPE_LABEL = {ImportType.ODOO_CRM: "Odoo CRM leads / opportunities", ImportType.ODOO_CONTACTS: "Odoo contacts"}


# ---------------------------------------------------------------------------
# Row analysis (shared by preview and confirm)
# ---------------------------------------------------------------------------


@dataclass
class RowResult:
    number: int  # 1-based data row number (header excluded)
    record: dict[str, Any]
    key: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_of: int | None = None
    company_name: str | None = None
    signals: MatchSignals | None = None

    @property
    def valid(self) -> bool:
        return not self.errors and self.duplicate_of is None


def _convert_row(specs: tuple[FieldSpec, ...], mapping: dict[str, str], raw: dict[str, Any], number: int) -> RowResult:
    result = RowResult(number=number, record={})
    for spec in specs:
        column = mapping.get(spec.key)
        value, warning = convert(spec, raw.get(column)) if column else (None, None)
        result.record[spec.key] = value
        if warning:
            result.warnings.append(warning)
    return result


def _analyse_crm(row: RowResult) -> None:
    r = row.record
    if not r["opportunity_name"]:
        if r["company_name"]:
            r["opportunity_name"] = r["company_name"]
            row.warnings.append("No opportunity name; the customer name was used")
        else:
            row.errors.append("Missing both opportunity name and customer")
            return
    if r["lead_type"] is None:
        r["lead_type"] = CrmLeadType.OPPORTUNITY
    stage = (r["stage"] or "").lower()
    r["is_won"] = "won" in stage or (r["probability"] is not None and r["probability"] >= 100)
    if r["active"] is None:
        r["active"] = True
    row.key = source_key(r["odoo_id"], r["opportunity_name"], r["company_name"], r["email"],
                         r["created_date"].isoformat() if r["created_date"] else None)
    row.company_name = r["company_name"]
    row.signals = MatchSignals(name=r["company_name"], website=r["website"], email=r["email"],
                               phone=r["phone"] or r["mobile"], city=r["city"], country=r["country"])


def _analyse_contact(row: RowResult, company_keys: set[str]) -> None:
    """Split an Odoo contact row into its company and its person.

    Company = Company Name, else the related company. A row is the organisation itself
    when Odoo says so ('Is a company'), or, when the export has no such column, when it
    has no company and its name is used as another row's company or carries a legal
    form (SAL, LLC, ...). A person without a company is kept, but no company is invented.
    """
    r = row.record
    company = r["company_name"] or r["parent_company"]
    name = r["contact_name"]
    if not company and not name:
        row.errors.append("No company or contact name")
        return
    is_company = r["is_company"]
    if is_company is None and name and not company:
        is_company = normalize_company_name(name) in company_keys or has_legal_form(name)
    if is_company and name:
        company, person = name, None
    elif name:
        person = name
    else:
        person = None
    if person and not company:
        row.warnings.append("No company name: kept as a contact without a company")
    phone = r["mobile"] or r["phone"]  # mobile first, as salespeople call it
    r["is_company"] = person is None
    r["company"], r["person"] = company, person
    row.key = source_key(r["odoo_id"], person or company, company if person else None, r["email"], phone)
    row.company_name = company
    row.signals = MatchSignals(
        name=company,
        email=r["email"],
        phone=phone if person is None else None,
        city=r["city"],
        country=r["country"],
        odoo_contact_id=odoo_int_id(r["odoo_id"]) if person is None else None,
    )


def _analyse(import_type: str, parsed: ParsedFile, mapping: dict[str, str]) -> list[RowResult]:
    specs = FIELDS[import_type]
    converted = [_convert_row(specs, mapping, raw, i) for i, raw in enumerate(parsed.rows, start=1)]
    if import_type == ImportType.ODOO_CRM:
        analyse = _analyse_crm
    else:
        company_keys = {normalize_company_name(c) for row in converted
                        if (c := row.record["company_name"] or row.record["parent_company"])}
        def analyse(row: RowResult) -> None:
            _analyse_contact(row, company_keys)
    seen: dict[str, int] = {}
    for row in converted:
        analyse(row)
        if row.key and not row.errors:
            if row.key in seen:
                row.duplicate_of = seen[row.key]
            else:
                seen[row.key] = row.number
    return converted


# ---------------------------------------------------------------------------
# Upload / preview
# ---------------------------------------------------------------------------


def _storage_dir() -> Path:
    path = Path(get_settings().import_storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name  # strip any client-side path
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"/\\|?*').strip(". ")
    return cleaned[:255] or "upload"


def _read(run: ImportRun) -> ParsedFile:
    path = _storage_dir() / run.stored_filename
    if not path.is_file():
        raise ConflictError("The uploaded file is no longer available. Upload it again.")
    return parse_file(path.read_bytes(), run.file_type, get_settings().import_max_rows)


def create_upload(db: Session, actor: User, import_type: ImportType, filename: str, content: bytes) -> ImportRun:
    settings = get_settings()
    if not content:
        raise BusinessRuleError("The uploaded file is empty.")
    if len(content) > settings.import_max_bytes:
        raise BusinessRuleError(f"The file is larger than {settings.import_max_bytes // (1024 * 1024)} MB.")
    original = _safe_filename(filename)
    file_type = detect_file_type(original, content[:8])
    parsed = parse_file(content, file_type, settings.import_max_rows)  # validates before storing
    mapping = auto_map(import_type, parsed.columns)
    missing = missing_essentials(import_type, mapping)
    if missing:
        found = ", ".join(parsed.columns[:12]) + ("…" if len(parsed.columns) > 12 else "")
        hint = ""
        if import_type == ImportType.ODOO_CRM and not missing_essentials(
                ImportType.ODOO_CONTACTS, auto_map(ImportType.ODOO_CONTACTS, parsed.columns)):
            hint = " It looks like a contacts list: upload it under Odoo contacts instead."
        raise BusinessRuleError(
            f"The file could not be imported because no {missing} was detected. Columns found: {found}.{hint}"
        )

    stored = f"{datetime.now(timezone.utc):%Y%m}/{uuid.uuid4().hex}.{file_type}"
    target = _storage_dir() / stored
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    run = ImportRun(
        import_type=import_type,
        status=ImportStatus.PREVIEW,
        original_filename=original,
        stored_filename=stored,
        file_type=file_type,
        file_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        detected_columns=parsed.columns,
        column_mapping=mapping,
        created_by=actor.id,
    )
    db.add(run)
    db.flush()
    _store_counts(run, _analyse(import_type, parsed, run.column_mapping))
    audit_service.record(db, action=AuditAction.IMPORT_UPLOADED, user_id=actor.id, entity_type="import_run",
                         entity_id=run.id, metadata={"type": ImportType(import_type).value, "filename": original,
                                                     "rows": run.row_count})
    db.commit()
    db.refresh(run)
    return run


def _store_counts(run: ImportRun, rows: list[RowResult]) -> None:
    run.row_count = len(rows)
    run.valid_count = sum(1 for r in rows if r.valid)
    run.warning_count = sum(1 for r in rows if r.warnings and not r.errors)
    run.duplicate_count = sum(1 for r in rows if r.duplicate_of is not None)
    run.error_count = sum(1 for r in rows if r.errors)
    run.issues = _issues(rows)


def _issues(rows: list[RowResult]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for r in rows:
        for message in r.errors:
            issues.append({"row": r.number, "level": "error", "message": message})
        if r.duplicate_of is not None:
            issues.append({"row": r.number, "level": "duplicate",
                           "message": f"Same record as row {r.duplicate_of}; it will be skipped"})
        for message in r.warnings:
            issues.append({"row": r.number, "level": "warning", "message": message})
        if len(issues) >= MAX_ISSUES:
            break
    return issues[:MAX_ISSUES]


def get_run(db: Session, run_id: int) -> ImportRun:
    run = db.get(ImportRun, run_id)
    if run is None:
        raise NotFoundError("Import not found")
    return run


def build_preview(db: Session, run: ImportRun) -> dict[str, Any]:
    """Everything the preview screen needs. Recomputed from the stored file each time."""
    parsed = _read(run)
    rows = _analyse(run.import_type, parsed, run.column_mapping)
    specs = FIELDS[run.import_type]
    model = CrmLead if run.import_type == ImportType.ODOO_CRM else OdooContact

    keys = [r.key for r in rows if r.valid and r.key]
    existing: set[str] = set()
    for start in range(0, len(keys), 1000):
        existing |= set(db.scalars(select(model.source_key).where(model.source_key.in_(keys[start:start + 1000]))))

    index = CompanyIndex(db.scalars(select(Company)).all())
    new_companies: set[str] = set()
    matched_companies: set[int] = set()
    sample = []
    for r in rows:
        match = index.match(r.signals) if (r.valid and r.signals) else None
        if match:
            matched_companies.add(match.company.id)
        elif r.valid and r.company_name:
            new_companies.add(normalize_company_name(r.company_name))
        if len(sample) < SAMPLE_ROWS:
            status = ("error" if r.errors else "duplicate" if r.duplicate_of is not None
                      else "update" if r.key in existing else "warning" if r.warnings else "new")
            sample.append({
                "row": r.number,
                "status": status,
                "values": {k: _jsonable(v) for k, v in _display(run.import_type, r).items()},
                "messages": r.errors + r.warnings + (
                    [f"Duplicate of row {r.duplicate_of}"] if r.duplicate_of is not None else []),
                "company_match": ({"id": match.company.id, "name": match.company.name, "reason": match.reason}
                                  if match else None),
            })

    previous = db.scalar(
        select(ImportRun).where(ImportRun.sha256 == run.sha256, ImportRun.status == ImportStatus.COMPLETED,
                                ImportRun.id != run.id).order_by(ImportRun.completed_at.desc())
    )
    mapped_columns = set(run.column_mapping.values())
    shown = [s for s in specs if not s.internal]
    return {
        "run": run,
        "type_label": TYPE_LABEL[run.import_type],
        "fields": [
            {"key": s.key, "label": s.label, "required": s.required, "important": s.important,
             "column": run.column_mapping.get(s.key)}
            for s in shown
        ],
        "unmapped_columns": [c for c in run.detected_columns if c not in mapped_columns],
        "missing_important": [s.label for s in shown if (s.required or s.important) and s.key not in run.column_mapping],
        "new_records": sum(1 for r in rows if r.valid and r.key not in existing),
        "existing_records": sum(1 for r in rows if r.valid and r.key in existing),
        "companies_matched": len(matched_companies),
        "companies_new": len(new_companies),
        "sample_rows": sample,
        "previous_import": ({"id": previous.id, "completed_at": previous.completed_at} if previous else None),
    }


def _display(import_type: str, row: RowResult) -> dict[str, Any]:
    """The values shown in the preview table."""
    r = row.record
    if import_type == ImportType.ODOO_CRM:
        return {"opportunity": r["opportunity_name"], "company": r["company_name"], "contact": r["contact_name"],
                "salesperson": r["salesperson"], "stage": r["stage"]}
    return {
        "company": r.get("company", r["company_name"] or r["parent_company"]),
        "contact": r.get("person", r["contact_name"]),
        "position": r["job_position"],
        "phone": r["mobile"] or r["phone"],
        "email": r["email"],
        "country": r["country"],
        "city": r["city"],
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return value.get("external")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def cancel(db: Session, actor: User, run_id: int) -> ImportRun:
    run = get_run(db, run_id)
    if run.status != ImportStatus.PREVIEW:
        raise ConflictError("Only imports awaiting confirmation can be cancelled.")
    run.status = ImportStatus.CANCELLED
    run.completed_at = datetime.now(timezone.utc)
    audit_service.record(db, action=AuditAction.IMPORT_CANCELLED, user_id=actor.id, entity_type="import_run",
                         entity_id=run.id)
    db.commit()
    return run


# ---------------------------------------------------------------------------
# Confirm (write to the database)
# ---------------------------------------------------------------------------


class _Writer:
    def __init__(self, db: Session, run: ImportRun, actor: User):
        self.db, self.run, self.actor = db, run, actor
        self.now = datetime.now(timezone.utc)
        self.salespeople = SalespersonResolver(db, import_run_id=run.id)
        self.index = CompanyIndex(db.scalars(select(Company)).all())
        self.created: set[int] = set()
        self.linked: set[int] = set()

    def company_for(self, row: RowResult, *, create: bool, extra: dict[str, Any]) -> Company | None:
        match = self.index.match(row.signals) if row.signals else None
        if match:
            company = match.company
            if company.id not in self.created:
                self.linked.add(company.id)
            if company.source == CompanySource.ODOO_IMPORT and company.created_by_import_id is None:
                company.created_by_import_id = self.run.id  # its import was deleted; this one adopts it
            self._fill_blanks(company, extra)
            return company
        if not (create and row.company_name):
            return None
        signals = row.signals
        company = Company(
            name=row.company_name,
            normalized_name=signals.normalized_name or normalize_company_name(row.company_name),
            source=CompanySource.ODOO_IMPORT,
            source_reference=f"{SOURCE_PREFIX[self.run.import_type]}:{self.run.id}",
            created_by=self.actor.id,
            created_by_import_id=self.run.id,
        )
        self._fill_blanks(company, extra)
        self.db.add(company)
        self.db.flush()
        self.index.add(company)
        self.created.add(company.id)
        return company

    @staticmethod
    def _fill_blanks(company: Company, extra: dict[str, Any]) -> None:
        """Enrich from Odoo without overwriting anything a user already entered."""
        website = extra.get("website")
        if website and not company.website and normalize_domain(website):
            company.website = normalize_website(website)[:500]
            company.domain = company_domain(website)
        phone = extra.get("phone")
        if phone and not company.main_phone:
            company.main_phone = phone[:50]
            company.main_phone_normalized = normalize_phone(phone, extra.get("country") or company.country)
        email = extra.get("email")
        if email and not company.main_email:
            company.main_email = email
            company.email_domain = email_domain(email)
        for attr in ("city", "country", "address", "odoo_contact_id"):
            if extra.get(attr) and not getattr(company, attr):
                setattr(company, attr, extra[attr])

    def upsert(self, model, key: str, values: dict[str, Any]):
        record = self.db.scalar(select(model).where(model.source_key == key))
        if record is None:
            record = model(source_key=key, created_by_import_id=self.run.id, **values)
            self.db.add(record)
            self.run.inserted_count += 1
        else:
            for attr, value in values.items():
                setattr(record, attr, value)
            if record.created_by_import_id is None:
                record.created_by_import_id = self.run.id  # kept from a deleted import; adopted
            self.run.updated_count += 1
        return record

    def write_crm(self, row: RowResult) -> None:
        r = row.record
        person = self.salespeople.resolve(r["salesperson"])
        phone = r["phone"] or r["mobile"]
        # CRM email/phone belong to the contact person, not the company: they are used for
        # matching but never copied onto the company record.
        company = self.company_for(row, create=True, extra={
            "website": r["website"], "city": r["city"], "country": r["country"]})
        self.upsert(CrmLead, row.key, {
            "odoo_lead_id": odoo_int_id(r["odoo_id"]),
            "odoo_external_id": odoo_external_id(r["odoo_id"]),
            "opportunity_name": r["opportunity_name"],
            "company_name": r["company_name"],
            "contact_name": r["contact_name"],
            "email": r["email"],
            "phone": r["phone"],
            "mobile": r["mobile"],
            "website": r["website"],
            "city": r["city"],
            "country": r["country"],
            "salesperson_name": person.name if person else None,
            "salesperson_id": person.id if person else None,
            "sales_team": r["sales_team"],
            "stage": r["stage"],
            "lead_type": r["lead_type"],
            "expected_revenue": r["expected_revenue"],
            "probability": r["probability"],
            "active": r["active"],
            "is_won": r["is_won"],
            "lost_reason": r["lost_reason"],
            "created_date": r["created_date"],
            "updated_date": r["updated_date"],
            "last_activity": r["last_activity"],
            "company_key": normalize_company_name(r["company_name"]) if r["company_name"] else None,
            "domain": company_domain(r["website"]),
            "email_domain": email_domain(r["email"]),
            "phone_normalized": normalize_phone(phone, r["country"]),
            "company_id": company.id if company else None,
            "import_run_id": self.run.id,
            "imported_at": self.now,
        })

    def write_contact(self, row: RowResult) -> None:
        r = row.record
        person = self.salespeople.resolve(r.get("salesperson"))
        phone = r["mobile"] or r["phone"]
        is_company = bool(r["is_company"])
        # The row's phone and email also become the company's main phone/email when the
        # company has none yet (never overwriting what is already there).
        company = self.company_for(row, create=True, extra={
            "phone": phone,
            "email": r["email"],
            "city": r["city"], "country": r["country"],
            "odoo_contact_id": odoo_int_id(r["odoo_id"]) if is_company else None,
        })
        record = self.upsert(OdooContact, row.key, {
            "odoo_contact_id": odoo_int_id(r["odoo_id"]),
            "odoo_external_id": odoo_external_id(r["odoo_id"]),
            "contact_name": r["company"] if is_company else r["person"],
            "is_company": is_company,
            "parent_company": None if is_company else r["company"],
            "job_position": None if is_company else r["job_position"],
            "email": r["email"],
            "phone": r["phone"],
            "mobile": r["mobile"],
            "phone_normalized": normalize_phone(phone, r["country"]),
            "country": r["country"],
            "city": r["city"],
            "salesperson_name": person.name if person else None,
            "salesperson_id": person.id if person else None,
            "company_key": normalize_company_name(row.company_name) if row.company_name else None,
            "email_domain": email_domain(r["email"]),
            "company_id": company.id if company else None,
            "import_run_id": self.run.id,
            "imported_at": self.now,
        })
        self.write_person(record, company, phone)

    def write_person(self, record: OdooContact, company: Company | None, phone: str | None) -> None:
        """A person with a company is also a LeadFinder contact of that company (one per Odoo record)."""
        self.db.flush()
        person = self.db.scalar(select(Contact).where(Contact.odoo_contact_id == record.id))
        if record.is_company or company is None:
            if person is not None:  # the Odoo record is no longer a person at a company
                self.db.delete(person)
            return
        first, _, last = record.contact_name.partition(" ")
        values = {
            "company_id": company.id,
            "first_name": first[:100],
            "last_name": last.strip()[:100] or None,
            "job_title": record.job_position,
            "business_email": record.email,
            "business_phone": phone,
            "source": ContactSource.ODOO_IMPORT,
            "source_reference": f"odoo:{record.odoo_contact_id}" if record.odoo_contact_id else None,
        }
        if person is None:
            self.db.add(Contact(odoo_contact_id=record.id, created_by=self.actor.id, **values))
        else:
            for attr, value in values.items():
                setattr(person, attr, value)


def confirm(db: Session, actor: User, run_id: int) -> ImportRun:
    run = get_run(db, run_id)
    if run.status != ImportStatus.PREVIEW:
        raise ConflictError(f"This import is already {run.status.lower()}.")
    try:
        rows = _analyse(run.import_type, _read(run), run.column_mapping)
        valid = [r for r in rows if r.valid]
        if not valid:
            raise BusinessRuleError("No rows can be imported. Every row is a duplicate or is missing a name.")
        writer = _Writer(db, run, actor)
        write = writer.write_crm if run.import_type == ImportType.ODOO_CRM else writer.write_contact
        run.inserted_count = run.updated_count = 0
        for row in valid:
            write(row)
        _store_counts(run, rows)
        run.skipped_count = len(rows) - len(valid)
        run.companies_created = len(writer.created)
        run.companies_linked = len(writer.linked)
        # Mark completed first: the refresh treats "an Odoo import has completed" as
        # the condition for calling unmatched companies AVAILABLE.
        run.status = ImportStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        changed = relationship_service.refresh_all(db)
        audit_service.record(db, action=AuditAction.IMPORT_COMPLETED, user_id=actor.id, entity_type="import_run",
                             entity_id=run.id, metadata={
                                 "type": run.import_type, "filename": run.original_filename,
                                 "inserted": run.inserted_count, "updated": run.updated_count,
                                 "skipped": run.skipped_count, "companies_created": run.companies_created,
                                 "companies_linked": run.companies_linked, "status_changes": changed})
        db.commit()
    except BusinessRuleError:
        db.rollback()
        raise
    except Exception as exc:  # record the failure, then surface a clear message
        db.rollback()
        logger.exception("Import %s failed", run_id)
        run = get_run(db, run_id)
        run.status = ImportStatus.FAILED
        run.completed_at = datetime.now(timezone.utc)
        run.failure_reason = f"{exc.__class__.__name__}: {str(exc)[:900]}"
        audit_service.record(db, action=AuditAction.IMPORT_FAILED, user_id=actor.id, entity_type="import_run",
                             entity_id=run.id, metadata={"error": exc.__class__.__name__})
        db.commit()
        raise BusinessRuleError(
            "The import failed and no records were saved. The error has been recorded in the import history."
        ) from exc
    db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def _company_in_use(db: Session, company_id: int) -> bool:
    """True when anything besides the import's own records refers to the company."""
    checks = (
        exists().where(CrmLead.company_id == company_id),
        exists().where(OdooContact.company_id == company_id),
        # Contacts entered in LeadFinder; imported ones go with their Odoo record.
        exists().where(Contact.company_id == company_id, Contact.odoo_contact_id.is_(None)),
        exists().where(CampaignCompany.company_id == company_id),
        exists().where(LeadActivity.company_id == company_id),
        exists().where(LushaUsage.company_id == company_id),
    )
    return any(db.scalar(select(check)) for check in checks)


def _salesperson_in_use(db: Session, person: Salesperson) -> bool:
    if person.user_id or person.odoo_user_id or person.email:
        return True  # linked or edited by an administrator
    return any(db.scalar(select(check)) for check in (
        exists().where(CrmLead.salesperson_id == person.id),
        exists().where(OdooContact.salesperson_id == person.id),
        exists().where(Company.salesperson_id == person.id),
    ))


def _latest_import_using(db: Session, column_name: str, value: int, excluding: int) -> int | None:
    """The newest other import whose Odoo records point at this company/salesperson."""
    newest = None
    for model in (CrmLead, OdooContact):
        found = db.scalar(select(func.max(model.import_run_id)).where(
            getattr(model, column_name) == value, model.import_run_id != excluding))
        if found and (newest is None or found > newest):
            newest = found
    return newest


def _hand_over(db: Session, run_id: int) -> None:
    """Records, companies and salespeople this import created but a later import still
    contains now belong to that import, so deleting it later with its data removes them."""
    for model in (CrmLead, OdooContact):
        for record in db.scalars(select(model).where(model.created_by_import_id == run_id,
                                                     model.import_run_id.is_not(None),
                                                     model.import_run_id != run_id)):
            record.created_by_import_id = record.import_run_id
    for model, column_name in ((Company, "company_id"), (Salesperson, "salesperson_id")):
        for owned in db.scalars(select(model).where(model.created_by_import_id == run_id)):
            newer = _latest_import_using(db, column_name, owned.id, run_id)
            if newer:
                owned.created_by_import_id = newer
    db.flush()


def delete_run(db: Session, actor: User, run_id: int, *, with_data: bool) -> dict[str, Any]:
    """Delete an import from the history, optionally with the data only it brought in.

    Import only: the history entry and stored file go; imported records stay.
    With data: also removes the Odoo records this import created that no later import
    contains, then the companies and salespeople it created that nothing else uses.
    Companies used in campaigns or with contacts, notes or credits are always kept.
    Whatever is kept but also belongs to a later import is handed over to that import.
    """
    run = get_run(db, run_id)
    removed = {"crm_records": 0, "odoo_contacts": 0, "companies": 0, "salespeople": 0}
    kept = {"records": 0, "companies": 0}
    if with_data and run.status == ImportStatus.COMPLETED:
        for model, label in ((CrmLead, "crm_records"), (OdooContact, "odoo_contacts")):
            for record in db.scalars(select(model).where(model.created_by_import_id == run.id)).all():
                if record.import_run_id not in (None, run.id):
                    kept["records"] += 1  # a later import also contains it
                    continue
                db.delete(record)
                removed[label] += 1
        db.flush()
        db.expire_all()  # the database cascaded to the LeadFinder contacts of deleted Odoo contacts
        for company in db.scalars(select(Company).where(Company.created_by_import_id == run.id)).all():
            if _company_in_use(db, company.id):
                kept["companies"] += 1
                continue
            db.delete(company)
            removed["companies"] += 1
        db.flush()
    _hand_over(db, run.id)

    # Read before the run is deleted: the database then clears created_by_import_id.
    own_salespeople = (db.scalars(select(Salesperson).where(Salesperson.created_by_import_id == run.id)).all()
                       if with_data else [])
    stored = _storage_dir() / run.stored_filename
    details = {"filename": run.original_filename, "type": run.import_type, "status": run.status}
    db.delete(run)
    db.flush()
    # Owners and statuses depend on the remaining Odoo data.
    relationship_service.refresh_all(db)
    db.flush()
    for person in own_salespeople:
        if not _salesperson_in_use(db, person):
            db.delete(person)
            removed["salespeople"] += 1
    audit_service.record(db, action=AuditAction.IMPORT_DELETED, user_id=actor.id, entity_type="import_run",
                         entity_id=run_id, metadata={**details, "with_data": with_data, "removed": removed,
                                                     "kept": kept})
    db.commit()
    stored.unlink(missing_ok=True)
    return {"id": run_id, "with_data": with_data, "removed": removed, "kept": kept}


def list_runs(db: Session, params: PageParams, *, import_type: ImportType | None = None,
              status: ImportStatus | None = None) -> tuple[list[ImportRun], int]:
    stmt = select(ImportRun)
    if import_type:
        stmt = stmt.where(ImportRun.import_type == import_type)
    if status:
        stmt = stmt.where(ImportRun.status == status)
    return paginate(db, stmt.order_by(ImportRun.created_at.desc(), ImportRun.id.desc()), params)
