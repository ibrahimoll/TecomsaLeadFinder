"""Lebanon source pack, operated by hand (not scheduled):

    python -m scripts.lebanon_sources refresh [--force] [--reparse] [KEY ...]
                                                                    refresh_lebanon_sources: due sources (or KEYs) read
                                                                    again; new / changed documents parsed once and
                                                                    applied to every known company they concern
    python -m scripts.lebanon_sources ingest-file KEY FILE.csv      an official / licensed file (Commercial Register
                                                                    extract...): company,person,title,published,url,
                                                                    domain,registration_number,email,phone
    python -m scripts.lebanon_sources apply [KEY ...]               the stored records matched to all companies again
    python -m scripts.lebanon_sources status                        documents, versions, records per source
"""

import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import ExternalDocument
from app.services.people.external.lebanon import pack


def main(argv: list[str]) -> None:
    command, args = (argv[0] if argv else "status"), argv[1:]
    with SessionLocal() as db:
        if command == "refresh":
            force = "--force" in args
            keys = [a for a in args if not a.startswith("--")] or None
            print(json.dumps(pack.refresh(db, keys, force=force, reparse="--reparse" in args), indent=2, default=str))
        elif command == "ingest-file":
            key, path = args[0], Path(args[1])
            print(json.dumps(pack.ingest_file(db, key, path.name, path.read_text(encoding="utf-8-sig")), indent=2))
        elif command == "apply":
            print(json.dumps(pack.apply_all(db, args or list(pack.configs())), indent=2))
        elif command == "status":
            for cfg in pack.configs().values():
                rows = db.execute(select(func.count(), func.max(ExternalDocument.retrieved_at),
                                         func.min(ExternalDocument.fresh_until))
                                  .where(ExternalDocument.metadata_["source"].astext == cfg.key)).one()
                records = sum((r or 0) for r in db.scalars(select(
                    ExternalDocument.metadata_["records"].as_integer()).where(
                    ExternalDocument.metadata_["source"].astext == cfg.key)))
                print(f"{cfg.key:20} {cfg.access:12} documents={rows[0]:<4} records={records:<6} "
                      f"last={rows[1]} due={rows[2]}")
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
