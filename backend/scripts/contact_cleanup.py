"""Step 6 clean-up: predicted e-mail addresses that a later run read back from the database and relabelled PUBLISHED.

    python -m scripts.contact_cleanup                         # dry run: report only, nothing changes
    python -m scripts.contact_cleanup --apply --backup FILE   # FILE: a pg_dump of this database taken just before

AFFECTED (certain): status published, provenance public, attached to a person, NO source, evidence
"published at stored..." - the signature of the bug: a genuinely published address always has the page / document
it was published on as its source, and "stored" means the address came from LeadFinder's own table, i.e. its prediction.
SUSPECT (reported, never changed): a person's published address with no source and no evidence.
Human-confirmed, TECOMSA CRM, verified and sourced published addresses are never touched.
Correction: back to PREDICTED (provenance predicted); deleted instead when the person already has a prediction (one
predicted address per person). Every change is written to the audit log. Validation re-counts AFFECTED (must be 0).
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import and_, select

from app.db.session import SessionLocal
from app.models import Email
from app.services.audit_service import record

AFFECTED = and_(Email.status == "published", Email.provenance == "public", Email.person_id.is_not(None),
                Email.source_id.is_(None), Email.evidence.like("published at stored%"))
SUSPECT = and_(Email.status.in_(("published", "discovered")), Email.provenance == "public",
               Email.person_id.is_not(None), Email.source_id.is_(None), Email.evidence.is_(None))


def report(db) -> dict:
    rows = lambda cond: [{"id": e.id, "email": e.email, "person_id": e.person_id, "company_id": e.company_id,
                          "evidence": e.evidence} for e in db.scalars(select(Email).where(cond).order_by(Email.id))]
    affected, suspect = rows(AFFECTED), rows(SUSPECT)
    return {"affected": len(affected), "suspect_report_only": len(suspect), "affected_rows": affected,
            "suspect_rows": suspect}


def apply(db) -> dict:
    changed = {"to_predicted": 0, "deleted_duplicate": 0}
    for e in db.scalars(select(Email).where(AFFECTED).order_by(Email.id)).all():
        before = {"status": e.status, "provenance": e.provenance, "evidence": e.evidence}
        other = db.scalar(select(Email.id).where(Email.person_id == e.person_id, Email.id != e.id,
                                                 Email.provenance == "predicted").limit(1))
        if other:
            db.delete(e)
            changed["deleted_duplicate"] += 1
            action = "contact_cleanup.deleted_duplicate_prediction"
        else:
            e.status, e.provenance = "predicted", "predicted"
            e.evidence = "corrected (Step 6 clean-up): a LeadFinder prediction, never published"
            changed["to_predicted"] += 1
            action = "contact_cleanup.published_to_predicted"
        record(db, action=action, user_id=None, entity_type="email", entity_id=e.id,
               metadata={"before": before, "email": e.email})
    db.commit()
    return changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", help="the pg_dump taken just before applying (must exist and not be empty)")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        found = report(db)
        print(json.dumps({k: v for k, v in found.items() if not k.endswith("_rows")}))
        for row in found["affected_rows"] + found["suspect_rows"]:
            print(json.dumps(row, ensure_ascii=False))
        if not args.apply:
            print("dry run: nothing changed")
            return 0
        if not args.backup or not Path(args.backup).is_file() or Path(args.backup).stat().st_size == 0:
            print("refused: --apply needs --backup pointing at the database dump taken just before", file=sys.stderr)
            return 2
        print("backup confirmed:", Path(args.backup).name, Path(args.backup).stat().st_size, "bytes")
        print(json.dumps(apply(db)))
        remaining = report(db)["affected"]
        print(json.dumps({"validation_remaining_affected": remaining}))
        return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
