"""L1 acceptance tests for data lake models, catalog, and config validation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, is_valid, new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, LakeConfigInvalid
from aqelyn.evidence import BlobRef
from aqelyn.lake import (
    ArchiveRecord,
    Dataset,
    DatasetCatalog,
    LakeConfig,
    Quarantine,
    Query,
    QueryResult,
    RetentionPolicy,
    RetentionReport,
    TelemetryRecord,
)

NOW = datetime(2026, 7, 15, 22, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="lake-admin@example.com")
TENANT = "018f0000-0000-7000-8000-000000000019"


def _blob() -> BlobRef:
    return BlobRef(
        hash="sha256:" + ("a" * 64),
        size_bytes=128,
        media_type="application/json",
        uri="blob://telemetry/raw/1",
    )


def _dataset(**overrides: object) -> Dataset:
    data: dict[str, object] = {
        "name": "endpoint_process",
        "tenant_id": TENANT,
        "schema": {
            "account": "string",
            "pid": "int",
            "command_line": "string",
            "observed_at": "datetime",
        },
        "classifications": {
            "account": "pii",
            "pid": "internal",
            "command_line": "secret",
            "observed_at": "public",
        },
        "indexed_fields": ["account", "observed_at"],
        "set_by": ACTOR,
        "set_at": NOW,
        "version": 1,
    }
    data.update(overrides)
    return Dataset.model_validate(data)


def test_lake_config_invalid() -> None:
    invalid: list[Callable[[], object]] = [
        lambda: LakeConfig(batch_size=0),
        lambda: LakeConfig(max_query_rows=0),
        lambda: LakeConfig(default_limit=101, max_query_rows=100),
        lambda: _dataset(classifications={"account": "restricted"}),
        lambda: _dataset(schema={"account": "text"}, classifications={"account": "public"}),
        lambda: _dataset(classifications={"account": "pii"}),
        lambda: _dataset(indexed_fields=["missing"]),
        lambda: RetentionPolicy(dataset="endpoint_process", ttl_days=0, set_by=ACTOR),
        lambda: RetentionPolicy(dataset="endpoint_process", archive_after_days=0, set_by=ACTOR),
        lambda: RetentionPolicy(
            dataset="endpoint_process",
            condition={"op": "matches", "attr": "fields.account", "value": "alice"},
            set_by=ACTOR,
        ),
        lambda: Query(dataset="endpoint_process", limit=0),
        lambda: Query(
            dataset="endpoint_process",
            limit=10,
            filter={"script": "return true"},
        ),
    ]

    for factory in invalid:
        with pytest.raises(LakeConfigInvalid):
            factory()

    assert "LakeConfigInvalid" in ALL_ERROR_CODES
    assert "DatasetNotFound" in ALL_ERROR_CODES
    assert "RecordNotFound" in ALL_ERROR_CODES
    assert "ArchiveIntegrityError" in ALL_ERROR_CODES
    assert "RetentionBlocked" in ALL_ERROR_CODES


async def test_lake_catalog_registers_classified_dataset() -> None:
    catalog = DatasetCatalog()
    dataset = await catalog.register(_dataset(retention_policy_id=new_id("rtp")))

    assert dataset.name == "endpoint_process"
    assert dataset.classifications["account"] == "pii"
    assert dataset.classifications["command_line"] == "secret"

    fetched = await catalog.get("endpoint_process", tenant_id=TENANT)
    assert fetched == dataset

    [listed] = await catalog.list(tenant_id=TENANT)
    assert listed == dataset


def test_lake_l1_model_shapes() -> None:
    record = TelemetryRecord(
        tenant_id=TENANT,
        dataset="endpoint_process",
        source_id=new_id("src"),
        occurred_at=NOW,
        ingested_at=NOW,
        fields={"account": "alice", "pid": 4242, "command_line": "whoami"},
        raw_ref=_blob(),
        evidence_id=new_id("evd"),
    )
    policy = RetentionPolicy(
        dataset="endpoint_process",
        tenant_id=TENANT,
        ttl_days=90,
        archive_after_days=30,
        condition={"op": "eq", "attr": "fields.account", "value": "alice"},
        set_by=ACTOR,
    )
    query = Query(
        dataset="endpoint_process",
        tenant_id=TENANT,
        filter={"op": "exists", "attr": "fields.pid"},
        since=NOW,
        until=NOW,
        fields=["account", "pid"],
        limit=25,
    )
    result = QueryResult(
        rows=[{"account": "***", "pid": 4242}],
        count=1,
        truncated=False,
        redacted_fields=["account"],
    )
    archive = ArchiveRecord(
        dataset="endpoint_process",
        tenant_id=TENANT,
        range={"until": NOW.isoformat()},
        location=_blob(),
        record_count=1,
        content_hash="sha256:" + ("b" * 64),
        archived_at=NOW,
        evidence_id=new_id("evd"),
    )
    report = RetentionReport(
        dataset="endpoint_process",
        evaluated=10,
        archived=2,
        expired=3,
        skipped_held=1,
        skipped_referenced=4,
        evidence_id=new_id("evd"),
        reason="TTL policy applied.",
    )
    quarantine = Quarantine(
        source_id=new_id("src"),
        reason="missing field account",
        received_at=NOW,
        raw_ref=_blob(),
    )

    assert is_valid(record.id, "tlm")
    assert is_valid(policy.id, "rtp")
    assert is_valid(archive.id, "arc")
    assert query.filter is not None
    assert result.redacted_fields == ["account"]
    assert report.skipped_referenced == 4
    assert quarantine.reason == "missing field account"
