"""Source inventory and contribution (Step 6.1): every source LeadFinder already has, what it holds and what it
actually produced, ranked by NEW DIRECTLY CONTACTABLE COMPANIES.

    python -m scripts.source_inventory LABEL      -> benchmarks/source_inventory_LABEL.json (+ a table on stdout)

Configured connectors (people/external/lebanon/sources.json) are measured through the sources their documents
created (sources.metadata.connector); every other origin (company websites, the web archive, Wikidata, internal
seeds...) by source type. Counts are over the whole database, and separately over the fixed-100 benchmark.
"""

import json
import sys

from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.contact_intelligence import DM_DEPARTMENTS, DM_SENIORITY
from app.services.people.external.lebanon import pack

BENCHMARKS = Path(__file__).resolve().parent.parent / "benchmarks"
USABLE_EMAIL = ("published", "discovered", "verified", "confirmed")
USABLE_PHONE = ("direct_business_phone", "office", "landline", "business_mobile", "mobile", "whatsapp",
                "office_extension")

SQL = """
WITH src AS (
  SELECT id, COALESCE(metadata->>'connector', 'type:' || source_type) AS origin FROM sources
), dm AS (
  SELECT cp.id, cp.company_id, cp.person_id FROM company_people cp
  WHERE cp.employment_status = 'current' AND cp.confidence >= 50
    AND cp.department = ANY(:departments) AND cp.seniority = ANY(:seniorities)
), role_origin AS (
  SELECT DISTINCT s.origin, e.company_person_id AS role_id, e.company_id FROM evidence e JOIN src s ON s.id = e.source_id
  WHERE e.company_person_id IS NOT NULL
), usable AS (
  SELECT s.origin, x.person_id, x.company_id, x.kind FROM (
    SELECT source_id, person_id, company_id, 'email' AS kind FROM emails
      WHERE person_id IS NOT NULL AND status = ANY(:emails)
    UNION ALL
    SELECT source_id, person_id, company_id, CASE WHEN phone_type IN ('business_mobile', 'mobile') THEN 'mobile'
      WHEN phone_type = 'whatsapp' THEN 'whatsapp' ELSE 'direct' END FROM phones
      WHERE person_id IS NOT NULL AND phone_type = ANY(:phones) AND status <> 'invalid'
  ) x JOIN src s ON s.id = x.source_id
)
SELECT o.origin,
  (SELECT count(DISTINCT company_id) FROM role_origin r WHERE r.origin = o.origin) AS companies_with_people,
  (SELECT count(*) FROM role_origin r WHERE r.origin = o.origin) AS roles,
  (SELECT count(*) FROM role_origin r JOIN dm ON dm.id = r.role_id WHERE r.origin = o.origin) AS current_dms,
  (SELECT count(DISTINCT r.company_id) FROM role_origin r JOIN dm ON dm.id = r.role_id WHERE r.origin = o.origin)
     AS dm_companies,
  (SELECT count(*) FROM usable u WHERE u.origin = o.origin AND u.kind = 'email') AS person_emails,
  (SELECT count(*) FROM usable u WHERE u.origin = o.origin AND u.kind = 'direct') AS direct_phones,
  (SELECT count(*) FROM usable u WHERE u.origin = o.origin AND u.kind = 'mobile') AS mobiles,
  (SELECT count(*) FROM usable u WHERE u.origin = o.origin AND u.kind = 'whatsapp') AS whatsapp,
  (SELECT count(DISTINCT u.company_id) FROM usable u JOIN dm ON dm.person_id = u.person_id
     AND dm.company_id = u.company_id WHERE u.origin = o.origin) AS contactable_companies,
  (SELECT count(DISTINCT u.company_id) FROM usable u JOIN dm ON dm.person_id = u.person_id
     AND dm.company_id = u.company_id WHERE u.origin = o.origin AND u.company_id = ANY(:bench))
     AS contactable_fixed100,
  (SELECT count(DISTINCT r.company_id) FROM role_origin r JOIN dm ON dm.id = r.role_id WHERE r.origin = o.origin
     AND r.company_id = ANY(:bench)) AS dm_companies_fixed100
FROM (SELECT DISTINCT origin FROM src) o
"""

DOCS = """
SELECT metadata->>'source' AS key, count(*) AS documents, max(retrieved_at) AS last_success,
  sum((metadata->>'records')::int) AS records, sum((metadata->>'people')::int) AS person_records,
  sum((SELECT count(*) FROM jsonb_array_elements(content->'records') r WHERE r ? 'person' AND r ? 'email')) AS
    person_records_with_email,
  sum((SELECT count(*) FROM jsonb_array_elements(content->'records') r WHERE r ? 'person' AND r ? 'phone')) AS
    person_records_with_phone,
  sum((SELECT count(*) FROM jsonb_array_elements(content->'records') r WHERE r ? 'person' AND r ? 'published')) AS
    dated_person_records
FROM external_documents WHERE metadata ? 'source' GROUP BY 1
"""


def run(label: str) -> dict:
    data = json.loads((BENCHMARKS / "people_coverage_set.json").read_text(encoding="utf-8"))
    data = data if isinstance(data, list) else data.get("companies", data)
    bench = [r["id"] if isinstance(r, dict) else int(r) for r in data]
    configs = pack.configs()
    with SessionLocal() as db:
        produced = {r.origin: dict(r._mapping) for r in db.execute(text(SQL), {
            "departments": list(DM_DEPARTMENTS), "seniorities": list(DM_SENIORITY), "emails": list(USABLE_EMAIL),
            "phones": list(USABLE_PHONE), "bench": bench})}
        docs = {r.key: dict(r._mapping) for r in db.execute(text(DOCS))}
    rows = []
    for key, cfg in configs.items():
        rows.append({"source": key, "name": cfg.name, "kind": cfg.category, "parser": cfg.parser, "access": cfg.access,
                     "sectors": list(cfg.sectors), **{k: v for k, v in (docs.get(key) or {}).items() if k != "key"},
                     **{k: v for k, v in (produced.get(key) or {}).items() if k != "origin"}})
    for origin, values in produced.items():
        if origin.startswith("type:"):
            rows.append({"source": origin, "name": origin[5:], "kind": "source type",
                         **{k: v for k, v in values.items() if k != "origin"}})
    rows.sort(key=lambda r: (-(r.get("contactable_companies") or 0), -(r.get("dm_companies") or 0),
                             -(r.get("documents") or 0)))
    report = {"label": label, "sources": rows}
    (BENCHMARKS / f"source_inventory_{label}.json").write_text(json.dumps(report, indent=1, default=str),
                                                               encoding="utf-8")
    return report


if __name__ == "__main__":
    out = run(sys.argv[1] if len(sys.argv) > 1 else "latest")
    cols = ("source", "access", "documents", "person_records", "person_records_with_email", "person_records_with_phone",
            "dm_companies", "current_dms", "person_emails", "direct_phones", "mobiles", "whatsapp",
            "contactable_companies", "contactable_fixed100", "dm_companies_fixed100")
    print(" | ".join(cols))
    for r in out["sources"]:
        print(" | ".join(str(r.get(c) if r.get(c) is not None else "-") for c in cols))

