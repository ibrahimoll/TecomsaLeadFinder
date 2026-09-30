"""Odoo CSV/XLSX import workflow.

upload → (parse, auto-map, validate, detect duplicates) → preview
       → optional mapping change → preview again
       → confirm → upsert records, link/create companies, recompute relationships
Nothing is written to the Odoo tables before the user confirms.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models import Company, CrmLead, ImportRun, OdooContact, User
from app.models.enums import CompanySource, CrmLeadType, ImportStatus, ImportType
from app.services import audit_service, relationship_service
from app.services.audit_service import AuditAction
from app.services.import_fields import (
    FIELDS,
    FieldSpec,
    auto_map,
    convert,
    odoo_external_id,
    odoo_int_id,
    source_key,
)
from app.services.import_parser import ParsedFile, detect_file_type, parse_file
from app.services.matching_service import CompanyIndex, MatchSignals
from app.services.normalization import (
    email_domain,
    normalize_company_name,
    normalize_domain,
    normalize_phone,
    normalize_website,
)
from app.services.pagination import PageParams, paginate
from app.services.salesperson_service import SalespersonResolver

logger = logging.getLogger(__name__)

MAX_ISSUES = 200
SAMPLE_ROWS = 25
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


def _analyse_contact(row: RowResult) -> None:
    r = row.record
    if not r["contact_name"]:
        row.errors.append("Missing contact name")
        return
    if r["is_company"] is None:
        # Odoo convention: a partner without a parent company is usually the company itself.
        r["is_company"] = not r["parent_company"]
    if r["is_customer"] is None:
        r["is_customer"] = False
    row.key = source_key(r["odoo_id"], r["contact_name"], r["parent_company"], r["email"], r["phone"])
    row.company_name = r["contact_name"] if r["is_company"] else r["parent_company"]
    row.signals = MatchSignals(
        name=row.company_name,
        website=r["website"],
        email=r["email"],
        phone=(r["phone"] or r["mobile"]) if r["is_company"] else None,
        city=r["city"],
        country=r["country"],
        odoo_contact_id=odoo_int_id(r["odoo_id"]) if r["is_company"] else None,
    )


def _analyse(import_type: str, parsed: ParsedFile, mapping: dict[str, str]) -> list[RowResult]:
    specs = FIELDS[import_type]
    analyse = _analyse_crm if import_type == ImportType.ODOO_CRM else _analyse_contact
    required = [s for s in specs if s.required]
    missing_required = [s.label for s in required if s.key not in mapping]
    seen: dict[str, int] = {}
    rows = []
    for i, raw in enumerate(parsed.rows, start=1):
        row = _convert_row(specs, mapping, raw, i)
        # The CRM name falls back to the customer, so only block when neither is mapped.
        if missing_required and not (import_type == ImportType.ODOO_CRM and "company_name" in mapping):
            row.errors.append(f"Required column not mapped: {', '.join(missing_required)}")
        else:
            analyse(row)
        if row.key and not row.errors:
            if row.key in seen:
                row.duplicate_of = seen[row.key]
            else:
                seen[row.key] = i
        rows.append(row)
    return rows


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
        column_mapping=auto_map(import_type, parsed.columns),
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
                "values": {k: _jsonable(v) for k, v in r.record.items() if k in {s.key for s in specs}},
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
    return {
        "run": run,
        "type_label": TYPE_LABEL[run.import_type],
        "fields": [
            {"key": s.key, "label": s.label, "required": s.required, "important": s.important,
             "column": run.column_mapping.get(s.key)}
            for s in specs
        ],
        "unmapped_columns": [c for c in run.detected_columns if c not in mapped_columns],
        "missing_important": [s.label for s in specs if (s.required or s.important) and s.key not in run.column_mapping],
        "new_records": sum(1 for r in rows if r.valid and r.key not in existing),
        "existing_records": sum(1 for r in rows if r.valid and r.key in existing),
        "companies_matched": len(matched_companies),
        "companies_new": len(new_companies),
        "sample_rows": sample,
        "previous_import": ({"id": previous.id, "completed_at": previous.completed_at} if previous else None),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return value.get("external")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def update_mapping(db: Session, actor: User, run_id: int, mapping: dict[str, str | None]) -> ImportRun:
    run = get_run(db, run_id)
    if run.status != ImportStatus.PREVIEW:
        raise ConflictError("This import has already been processed; its mapping can no longer change.")
    valid_keys = {s.key for s in FIELDS[run.import_type]}
    cleaned: dict[str, str] = {}
    for key, column in mapping.items():
        if key not in valid_keys:
            raise BusinessRuleError(f"Unknown field '{key}'")
        if column is None or column == "":
            continue
        if column not in run.detected_columns:
            raise BusinessRuleError(f"Column '{column}' does not exist in the file")
        if column in cleaned.values():
            raise BusinessRuleError(f"Column '{column}' is mapped to more than one field")
        cleaned[key] = column
    run.column_mapping = cleaned
    _store_counts(run, _analyse(run.import_type, _read(run), cleaned))
    audit_service.record(db, action=AuditAction.IMPORT_MAPPING_CHANGED, user_id=actor.id,
                         entity_type="import_run", entity_id=run.id, metadata={"mapping": cleaned})
    db.commit()
    db.refresh(run)
    return run


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
        self.salespeople = SalespersonResolver(db)
        self.index = CompanyIndex(db.scalars(select(Company)).all())
        self.created: set[int] = set()
        self.linked: set[int] = set()

    def company_for(self, row: RowResult, *, create: bool, extra: dict[str, Any]) -> Company | None:
        match = self.index.match(row.signals) if row.signals else None
        if match:
            company = match.company
            if company.id not in self.created:
                self.linked.add(company.id)
            self._fill_blanks(company, extra)
            return company
        if not (create and row.company_name):
            return None
        signals = row.signals
        company = Company(
            name=row.company_name,
            normalized_name=signals.normalized_name or normalize_company_name(row.company_name),
            source=CompanySource.ODOO_IMPORT,
            source_reference=f"odoo-import:{self.run.id}",
            created_by=self.actor.id,
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
            company.domain = normalize_domain(website)
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
            record = model(source_key=key, **values)
            self.db.add(record)
            self.run.inserted_count += 1
        else:
            for attr, value in values.items():
                setattr(record, attr, value)
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
            "domain": normalize_domain(r["website"]) if r["website"] else None,
            "email_domain": email_domain(r["email"]),
            "phone_normalized": normalize_phone(phone, r["country"]),
            "company_id": company.id if company else None,
            "import_run_id": self.run.id,
            "imported_at": self.now,
        })

    def write_contact(self, row: RowResult) -> None:
        r = row.record
        person = self.salespeople.resolve(r["salesperson"])
        phone = r["phone"] or r["mobile"]
        is_company = bool(r["is_company"])
        company = self.company_for(row, create=True, extra={
            "website": r["website"],
            "phone": phone if is_company else None,
            "email": r["email"] if is_company else None,
            "city": r["city"], "country": r["country"],
            "address": r["address"] if is_company else None,
            "odoo_contact_id": odoo_int_id(r["odoo_id"]) if is_company else None,
        })
        self.upsert(OdooContact, row.key, {
            "odoo_contact_id": odoo_int_id(r["odoo_id"]),
            "odoo_external_id": odoo_external_id(r["odoo_id"]),
            "contact_name": r["contact_name"],
            "is_company": is_company,
            "parent_company": r["parent_company"],
            "website": r["website"],
            "domain": normalize_domain(r["website"]) if r["website"] else None,
            "email": r["email"],
            "phone": r["phone"],
            "mobile": r["mobile"],
            "phone_normalized": normalize_phone(phone, r["country"]),
            "address": r["address"],
            "country": r["country"],
            "city": r["city"],
            "is_customer": bool(r["is_customer"]),
            "salesperson_name": person.name if person else None,
            "salesperson_id": person.id if person else None,
            "company_key": normalize_company_name(row.company_name) if row.company_name else None,
            "email_domain": email_domain(r["email"]),
            "company_id": company.id if company else None,
            "import_run_id": self.run.id,
            "imported_at": self.now,
        })


def confirm(db: Session, actor: User, run_id: int) -> ImportRun:
    run = get_run(db, run_id)
    if run.status != ImportStatus.PREVIEW:
        raise ConflictError(f"This import is already {run.status.lower()}.")
    try:
        rows = _analyse(run.import_type, _read(run), run.column_mapping)
        valid = [r for r in rows if r.valid]
        if not valid:
            raise BusinessRuleError("No valid rows to import. Check the column mapping and the file contents.")
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


def list_runs(db: Session, params: PageParams, *, import_type: ImportType | None = None,
              status: ImportStatus | None = None) -> tuple[list[ImportRun], int]:
    stmt = select(ImportRun)
    if import_type:
        stmt = stmt.where(ImportRun.import_type == import_type)
    if status:
        stmt = stmt.where(ImportRun.status == status)
    return paginate(db, stmt.order_by(ImportRun.created_at.desc(), ImportRun.id.desc()), params)
