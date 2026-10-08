"""Connector configuration (connectors.json): which sources run, for which countries, in which order,
with which quality weight. Editing the file needs no code change; an admin UI can come later.

Each entry: key (unique), kind (implementation), label, enabled, countries (ISO codes, [] = any the
implementation supports), priority (lower first), source_type (enums.SOURCE_TYPES), quality (0-100,
stored on every source record), requests_per_minute, options (implementation-specific).
"""

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.models.enums import SOURCE_TYPES
from app.services.discovery.candidate import ConnectorConfig

KINDS = ("overture", "osm", "wikidata", "dataset_file", "public_web")


def parse_configs(entries: list[dict]) -> list[ConnectorConfig]:
    configs = []
    for entry in entries:
        config = ConnectorConfig(
            key=entry["key"], kind=entry["kind"], enabled=bool(entry.get("enabled", True)),
            countries=tuple(entry.get("countries", ())), priority=int(entry.get("priority", 50)),
            source_type=entry["source_type"], quality=int(entry["quality"]),
            requests_per_minute=int(entry.get("requests_per_minute", 30)), label=entry.get("label", entry["key"]),
            options=entry.get("options", {}),
        )
        if config.kind not in KINDS:
            raise ValueError(f"connector {config.key}: unknown kind {config.kind!r}")
        if config.source_type not in SOURCE_TYPES:
            raise ValueError(f"connector {config.key}: unknown source_type {config.source_type!r}")
        if not 0 <= config.quality <= 100:
            raise ValueError(f"connector {config.key}: quality must be 0-100")
        configs.append(config)
    if len({c.key for c in configs}) != len(configs):
        raise ValueError("connector keys must be unique")
    return sorted(configs, key=lambda c: (c.priority, c.key))


@lru_cache
def load_configs() -> tuple[ConnectorConfig, ...]:
    path = Path(get_settings().discovery_connectors_file)
    return tuple(parse_configs(json.loads(path.read_text(encoding="utf-8"))))
