"""L2 acceptance tests for lake ingest and stores."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import TenantScopeRequired
from aqelyn.evidence import InMemoryBlobStore
from aqelyn.lake import (
    Dataset,
    DatasetCatalogStore,
    InMemoryDatasetCatalog,
    InMemoryTelemetryRecordStore,
    PostgresDatasetCatalog,
    PostgresTelemetryRecordStore,
    TelemetryRecord,
    TelemetryRecordStore,
    ingest,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT_A = "018f0000-0000-7000-8000-000000000191"
TENANT_B = "018f0000-0000-7000-8000-000000000192"
ACTOR = ActorRef(actor_type="system", actor_id="lake-l2-test")
NOW = datetime(2026, 7, 15, 23, 0, tzinfo=UTC)


class _Closable(Protocol):
    async def close(self) -> None: ...


def _dataset(*, tenant_id: str | None = None, name: str = "endpoint_process") -> Dataset:
    return Dataset.model_validate(
        {
            "name": name,
            "tenant_id": tenant_id,
            "schema": {
                "account": "string",
                "pid": "int",
                "observed_at": "datetime",
                "ok": "bool",
            },
            "classifications": {
                "account": "pii",
                "pid": "internal",
                "observed_at": "public",
                "ok": "internal",
            },
            "indexed_fields": ["account", "observed_at"],
            "set_by": ACTOR,
            "set_at": NOW,
        }
    )


def _record(
    *,
    tenant_id: str | None = None,
    dataset: str = "endpoint_process",
    fields: dict[str, object] | None = None,
) -> TelemetryRecord:
    return TelemetryRecord(
        tenant_id=tenant_id,
        dataset=dataset,
        source_id=new_id("src"),
        occurred_at=NOW,
        ingested_at=NOW,
        fields=fields
        or {
            "account": "alice",
            "pid": "4242",
            "observed_at": NOW.isoformat(),
            "ok": "true",
        },
    )


async def _postgres_catalog(*, mode: str = "local") -> PostgresDatasetCatalog:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    catalog = await PostgresDatasetCatalog.connect(PG_URL, mode=mode)
    async with catalog._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_lake_quarantine, aq_lake_record, aq_lake_dataset RESTART IDENTITY"
        )
    return catalog


async def _postgres_store(*, mode: str = "local") -> PostgresTelemetryRecordStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresTelemetryRecordStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_lake_quarantine, aq_lake_record RESTART IDENTITY")
    return store


async def _catalog(kind: str, *, mode: str = "local") -> AsyncIterator[DatasetCatalogStore]:
    if kind == "inmemory":
        yield InMemoryDatasetCatalog()
        return
    catalog = await _postgres_catalog(mode=mode)
    try:
        yield catalog
    finally:
        await catalog.close()


async def _store(kind: str, *, mode: str = "local") -> AsyncIterator[TelemetryRecordStore]:
    if kind == "inmemory":
        yield InMemoryTelemetryRecordStore(mode=mode)
        return
    store = await _postgres_store(mode=mode)
    try:
        yield store
    finally:
        await store.close()


async def _catalog_store(
    kind: str,
    *,
    mode: str = "local",
) -> AsyncIterator[tuple[DatasetCatalogStore, TelemetryRecordStore]]:
    if kind == "inmemory":
        yield InMemoryDatasetCatalog(), InMemoryTelemetryRecordStore(mode=mode)
        return
    catalog = await _postgres_catalog(mode=mode)
    store = await _postgres_store(mode=mode)
    try:
        yield catalog, store
    finally:
        await catalog.close()
        await store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_catalog_contract(kind: str) -> None:
    async for catalog in _catalog(kind, mode="enterprise"):
        global_ds = await catalog.register(_dataset())
        tenant_ds = await catalog.register(_dataset(tenant_id=TENANT_A, name="auth_log"))

        assert await catalog.get(global_ds.name, tenant_id=TENANT_A) == global_ds
        assert await catalog.get("auth_log", tenant_id=TENANT_A) == tenant_ds
        assert await catalog.get("auth_log", tenant_id=TENANT_B) is None

        rows = await catalog.list(tenant_id=TENANT_A)
        assert [row.name for row in rows] == ["endpoint_process", "auth_log"]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_store_contract(kind: str) -> None:
    async for store in _store(kind, mode="enterprise"):
        stored = await store.append(_record(tenant_id=TENANT_A))
        other = await store.append(_record(tenant_id=TENANT_B))

        loaded = await store.get(stored.id, tenant_id=TENANT_A)
        assert loaded == stored
        assert loaded is not stored
        assert await store.get(stored.id, tenant_id=TENANT_B) is None

        rows = await store.query(dataset="endpoint_process", tenant_id=TENANT_A)
        assert [row.id for row in rows] == [stored.id]
        assert other.id not in [row.id for row in rows]
        with pytest.raises(TenantScopeRequired):
            await store.query(dataset="endpoint_process", tenant_id=None)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_quarantine(kind: str) -> None:
    async for catalog, store in _catalog_store(kind, mode="enterprise"):
        await catalog.register(_dataset(tenant_id=TENANT_A))
        blob_store = InMemoryBlobStore()
        result = await ingest(
            [
                _record(
                    tenant_id=TENANT_A,
                    fields={
                        "account": "alice",
                        "observed_at": NOW.isoformat(),
                        "ok": True,
                    },
                )
            ],
            catalog=catalog,
            store=store,
            blob_store=blob_store,
            tenant_id=TENANT_A,
        )

        assert result.accepted_count == 0
        assert result.quarantined_count == 1
        [quarantined] = await store.list_quarantine(tenant_id=TENANT_A)
        assert "missing fields: pid" in quarantined.reason
        assert quarantined.raw_ref is not None
        assert await store.query(dataset="endpoint_process", tenant_id=TENANT_A) == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_raw_by_ref(kind: str) -> None:
    async for catalog, store in _catalog_store(kind, mode="enterprise"):
        await catalog.register(_dataset(tenant_id=TENANT_A))
        blob_store = InMemoryBlobStore()
        result = await ingest(
            [_record(tenant_id=TENANT_A)],
            catalog=catalog,
            store=store,
            blob_store=blob_store,
            tenant_id=TENANT_A,
        )

        assert result.accepted_count == 1
        [record] = await store.query(dataset="endpoint_process", tenant_id=TENANT_A)
        assert record.raw_ref is not None
        assert record.fields["pid"] == 4242
        assert record.fields["ok"] is True
        raw = await blob_store.get(record.raw_ref)
        assert b"endpoint_process" in raw


def test_lake_ingest_no_network() -> None:
    # S1: ingestion is handed-in only — no network client, no collector/agent code.
    # The guard is the absence of any network mechanism (a collector cannot reach
    # out without one). The bare word "collector" is not forbidden because EA-0004
    # `EvidenceRecord.collector` is a required, legitimate field for the lifecycle
    # audit evidence the lake must write (D6/FR-12).
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "aqelyn" / "lake").glob("*.py")
        if path.name != "postgres.py"
    )
    forbidden = ["socket", "requests", "httpx", "aiohttp", "urllib", "credential"]
    assert not any(token in source for token in forbidden)


def test_lake_not_a_second_store() -> None:
    # S2 / FR-13: the lake is not a second object store, event log, or evidence
    # store, and it never creates entities, findings, or platform events. It MAY
    # write lifecycle audit evidence via the injected EA-0004 EvidenceStore
    # (D6/FR-12) and reference evidence ids — that is required, not forbidden, so
    # `EvidenceStore`/`EvidenceRecord` are intentionally not in this list.
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "src" / "aqelyn" / "lake").glob("*.py")
    )
    forbidden = [
        "ObjectStore",
        "AQObject",
        "EventBus",
        "raise_finding",
    ]
    assert not any(token in source for token in forbidden)
