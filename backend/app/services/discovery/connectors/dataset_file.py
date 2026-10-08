"""Official / licensed company lists delivered as files: government registries, ministry industrial
directories, chamber and exporter directories, association member lists, licensed feeds (e.g. a 5INDEX
licence). This is how those sources join LeadFinder WITHOUT scraping: a person who is allowed to use the
data places the file (CSV, or JSON lines) on the server and maps its columns in connectors.json.

    {"key": "lb_industrial_directory", "kind": "dataset_file", "source_type": "government", "quality": 90,
     "countries": ["LB"], "label": "Ministry of Industry directory",
     "options": {"path": "storage/datasets/lb_industry.csv", "publisher": "Ministry of Industry",
                 "url": "https://...", "columns": {"company_name": "Name", "city": "Town",
                 "industry": "Sector", "registration_number": "Licence No", "phone": "Tel"}}}

Recognised column targets: company_name (required), external_id, legal_name, website, phone, email,
country, region, city, address, industry, description, employee_count, registration_number.
"""

import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.services.discovery.candidate import (CompanyCandidate, ConnectorConfig, ConnectorError, ConnectorResult,
                                              SearchQuery)
from app.services.discovery.geography import find_country, in_area, region_for
from app.services.discovery.industries import label_nodes

logger = logging.getLogger(__name__)

TARGETS = ("company_name", "external_id", "legal_name", "website", "phone", "email", "country", "region", "city",
           "address", "industry", "description", "employee_count", "registration_number")


def _records(path: Path) -> list[dict]:
    if path.suffix.lower() in (".jsonl", ".json"):
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class DatasetFileConnector:
    def __init__(self, config: ConnectorConfig, base_dir: str | Path = "."):
        self.config = config
        options = config.options
        self.path = Path(base_dir) / options.get("path", "")
        self.columns: dict[str, str] = options.get("columns", {})
        unknown = set(self.columns) - set(TARGETS)
        if "company_name" not in self.columns or unknown:
            raise ValueError(f"{config.key}: columns must map company_name and only {TARGETS} (got {sorted(unknown)})")
        self.publisher = options.get("publisher")
        self.url = options.get("url")

    def search_companies(self, query: SearchQuery) -> ConnectorResult:
        if not self.path.is_file():
            raise ConnectorError(f"The {self.config.label or self.config.key} file has not been provided.")
        try:
            records = _records(self.path)
        except Exception as exc:
            logger.exception("Reading %s failed", self.path)
            raise ConnectorError(f"The {self.config.label or self.config.key} file could not be read.") from exc
        observed = datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc)
        candidates = []
        for record in records:
            row = {target: str(record.get(column) or "").strip() or None for target, column in self.columns.items()}
            if row.get("country") and (country := find_country(row["country"])) and country.code != query.country.code:
                continue
            name = row.get("company_name") or ""
            labels = [v for v in (row.get("industry"), row.get("description")) if v]
            nodes = label_nodes(labels)
            matched = query.industry.score(f"{name} {' '.join(labels)}", nodes)
            if matched is None:
                continue
            texts = [t for t in (row.get("city"), row.get("region"), row.get("address")) if t]
            if query.area and not in_area(query.area, None, None, texts, query.country.code):
                continue
            employees = row.get("employee_count")
            external_id = row.get("external_id") or row.get("registration_number") or \
                hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()[:32]
            candidates.append(CompanyCandidate(
                connector=self.config.key,
                source_name=self.config.label or self.config.key,
                source_type=self.config.source_type,
                external_id=external_id,
                source_url=self.url,
                observed_at=observed,
                company_name=name,
                legal_name=row.get("legal_name"),
                website=row.get("website"),
                phone=row.get("phone"),
                email=row.get("email"),
                country=query.country.name,
                region=row.get("region") or region_for(query.country.code, None, None, row.get("city")),
                city=row.get("city"),
                address=row.get("address"),
                industry=row.get("industry"),
                categories=sorted(nodes),
                description=row.get("description"),
                employee_count=int(employees) if employees and employees.isdigit() else None,
                registration_number=row.get("registration_number"),
                score=matched.score,
                match_reason=matched.reason,
                tier=matched.tier,
                datasets=[self.config.label or self.config.key],
                raw_metadata={"record": {k: v for k, v in record.items() if v not in (None, "")},
                              "publisher": self.publisher},
            ))
        candidates.sort(key=lambda c: (-c.score, c.company_name.lower()))
        return ConnectorResult(candidates=candidates, version=observed.date().isoformat(), scanned=len(records))
