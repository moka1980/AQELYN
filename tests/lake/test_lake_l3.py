"""L3 acceptance tests for safe lake query and redaction."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.lake import (
    REDACTED,
    Dataset,
    DatasetCatalogStore,
    InMemoryDatasetCatalog,
    InMemoryTelemetryRecordStore,
    LakeConfig,
    PostgresDatasetCatalog,
    PostgresTelemetryRecordStore,
    Query,
    TelemetryRecord,
    TelemetryRecordStore,
    query,
)
from aqelyn.lake.query import compile_condition
from aqelyn.policy import Decision, DecisionRequest

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT_A = "018f0000-0000-7000-8000-000000000193"
TENANT_B = "018f0000-0000-7000-8000-000000000194"
ACTOR = ActorRef(actor_type="user", actor_id="analyst@example.com")
ADMIN = ActorRef(actor_type="system", actor_id="lake-l3-test")
NOW = datetime(2026, 7, 15, 23, 30, tzinfo=UTC)


class _Authorizer:
    def __init__(self, *, effect: str) -> None:
        self.effect = effect
        self.requests: list[DecisionRequest] = []

    async def authorize(self, request: DecisionRequest) -> Decision:
        self.requests.append(request)
        return Decision(
            effect=self.effect,
            matched_rules=["lake-redaction-test"],
            obligations=[],
            reason=f"{self.effect} for test.",
        )


def _dataset(*, tenant_id: str | None = TENANT_A) -> Dataset:
    return Dataset.model_validate(
        {
            "name": "endpoint_process",
            "tenant_id": tenant_id,
            "schema": {
                "account": "string",
                "pid": "int",
                "observed_at": "datetime",
                "command_line": "string",
            },
            "classifications": {
                "account": "pii",
                "pid": "internal",
                "observed_at": "public",
                "command_line": "secret",
            },
            "indexed_fields": ["account", "observed_at"],
            "set_by": ADMIN,
            "set_at": NOW,
        }
    )


def _record(
    *,
    tenant_id: str = TENANT_A,
    account: str = "alice",
    pid: int = 1000,
    occurred_at: datetime = NOW,
    command_line: str = "whoami",
) -> TelemetryRecord:
    return TelemetryRecord(
        tenant_id=tenant_id,
        dataset="endpoint_process",
        source_id=new_id("src"),
        occurred_at=occurred_at,
        ingested_at=occurred_at,
        fields={
            "account": account,
            "pid": pid,
            "observed_at": occurred_at.isoformat(),
            "command_line": command_line,
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


async def _catalog_store(
    kind: str,
    *,
    mode: str = "enterprise",
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


async def _seed(
    catalog: DatasetCatalogStore,
    store: TelemetryRecordStore,
    records: list[TelemetryRecord],
) -> None:
    await catalog.register(_dataset(tenant_id=TENANT_A))
    await catalog.register(_dataset(tenant_id=TENANT_B))
    for record in records:
        await store.append(record)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_query_bounded(kind: str) -> None:
    async for catalog, store in _catalog_store(kind):
        await _seed(
            catalog,
            store,
            [
                _record(account="alice", pid=1, occurred_at=NOW),
                _record(account="bob", pid=2, occurred_at=NOW + timedelta(seconds=1)),
                _record(account="carol", pid=3, occurred_at=NOW + timedelta(seconds=2)),
                _record(tenant_id=TENANT_B, account="mallory", pid=4),
            ],
        )

        result = await query(
            Query(dataset="endpoint_process", tenant_id=TENANT_A, fields=["pid"], limit=10),
            actor=ACTOR,
            catalog=catalog,
            store=store,
            config=LakeConfig(max_query_rows=2, default_limit=2),
        )

        assert result.count == 3
        assert result.truncated is True
        assert result.rows == [{"pid": 1}, {"pid": 2}]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_redaction(kind: str) -> None:
    async for catalog, store in _catalog_store(kind):
        await _seed(
            catalog, store, [_record(account="alice", pid=4242, command_line="cat /secret")]
        )

        denied = await query(
            Query(
                dataset="endpoint_process",
                tenant_id=TENANT_A,
                fields=["account", "pid", "command_line"],
                limit=10,
            ),
            actor=ACTOR,
            catalog=catalog,
            store=store,
        )

        assert denied.rows == [{"account": REDACTED, "pid": 4242, "command_line": REDACTED}]
        assert denied.redacted_fields == ["account", "command_line"]

        permit = _Authorizer(effect="permit")
        allowed = await query(
            Query(
                dataset="endpoint_process",
                tenant_id=TENANT_A,
                fields=["account", "pid", "command_line"],
                limit=10,
            ),
            actor=ACTOR,
            catalog=catalog,
            store=store,
            policy_authorizer=permit,
        )

        assert allowed.rows == [{"account": "alice", "pid": 4242, "command_line": "cat /secret"}]
        assert allowed.redacted_fields == []
        assert {request.resource.attributes["field"] for request in permit.requests} == {
            "account",
            "command_line",
        }


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_no_raw_sql(kind: str) -> None:
    malicious = "alice' OR 1=1 --"
    async for catalog, store in _catalog_store(kind):
        await _seed(
            catalog,
            store,
            [
                _record(account=malicious, pid=1),
                _record(account="bob", pid=2),
            ],
        )

        q = Query(
            dataset="endpoint_process",
            tenant_id=TENANT_A,
            filter={"op": "eq", "attr": "fields.account", "value": malicious},
            fields=["pid"],
            limit=10,
        )
        result = await query(q, actor=ACTOR, catalog=catalog, store=store)

        assert result.rows == [{"pid": 1}]
        assert q.filter is not None
        predicate = compile_condition(q.filter)
        assert malicious not in predicate.sql
        assert malicious in predicate.args

    source = (ROOT / "src" / "aqelyn" / "lake" / "query.py").read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source
