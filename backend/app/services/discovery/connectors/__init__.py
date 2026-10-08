"""Discovery connectors: one module per kind of source, all returning CompanyCandidates."""

from app.core.config import get_settings
from app.services.discovery.candidate import Connector, ConnectorConfig


def build(config: ConnectorConfig) -> Connector:
    cache = get_settings().discovery_cache_dir
    if config.kind == "overture":
        from app.services.discovery.connectors.overture import OvertureConnector
        return OvertureConnector(config, cache)
    if config.kind == "osm":
        from app.services.discovery.connectors.osm import OsmConnector
        return OsmConnector(config, cache)
    if config.kind == "wikidata":
        from app.services.discovery.connectors.wikidata import WikidataConnector
        return WikidataConnector(config, cache)
    if config.kind == "dataset_file":
        from app.services.discovery.connectors.dataset_file import DatasetFileConnector
        return DatasetFileConnector(config)
    if config.kind == "public_web":
        from app.services.discovery.connectors.public_web import PublicWebConnector
        return PublicWebConnector(config)
    raise ValueError(f"unknown connector kind {config.kind!r}")
