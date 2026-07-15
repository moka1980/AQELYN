"""Security Data Lake & Telemetry Platform (EA-0019)."""

from aqelyn.lake.catalog import DatasetCatalog
from aqelyn.lake.ingest import IngestResult, ingest
from aqelyn.lake.memory import InMemoryDatasetCatalog, InMemoryTelemetryRecordStore
from aqelyn.lake.models import (
    VALID_CLASSIFICATIONS,
    VALID_SCHEMA_TYPES,
    ArchiveRecord,
    Classification,
    Dataset,
    LakeConfig,
    Quarantine,
    Query,
    QueryResult,
    RetentionPolicy,
    RetentionReport,
    RetentionState,
    SchemaType,
    TelemetryRecord,
)
from aqelyn.lake.postgres import PostgresDatasetCatalog, PostgresTelemetryRecordStore
from aqelyn.lake.query import REDACTED, PolicyAuthorizer, count, query
from aqelyn.lake.store import DatasetCatalogStore, TelemetryRecordStore

__all__ = [
    "REDACTED",
    "VALID_CLASSIFICATIONS",
    "VALID_SCHEMA_TYPES",
    "ArchiveRecord",
    "Classification",
    "Dataset",
    "DatasetCatalog",
    "DatasetCatalogStore",
    "InMemoryDatasetCatalog",
    "InMemoryTelemetryRecordStore",
    "IngestResult",
    "LakeConfig",
    "PolicyAuthorizer",
    "PostgresDatasetCatalog",
    "PostgresTelemetryRecordStore",
    "Quarantine",
    "Query",
    "QueryResult",
    "RetentionPolicy",
    "RetentionReport",
    "RetentionState",
    "SchemaType",
    "TelemetryRecord",
    "TelemetryRecordStore",
    "count",
    "ingest",
    "query",
]
