"""A3 acceptance tests for Asset & Configuration Governance persistence."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from aqelyn.assetconfig import (
    ASSET_OBJECT_TYPE,
    ACGConfig,
    AssetConfigAnalyzer,
    AssetDrift,
    Baseline,
    BaselineStore,
    Check,
    DriftSnapshot,
    DriftSnapshotStore,
    InMemoryBaselineStore,
    InMemoryDriftSnapshotStore,
    PostgresBaselineStore,
    PostgresDriftSnapshotStore,
    new_drift_snapshot_id,
)
from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    BaselineConfigInvalid,
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    SchemaValidationError,
)
from aqelyn.findings.models import Severity
from aqelyn.objects import AQObject, InMemoryObjectStore, SourceRef

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="assetconfig-a3-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "assetconfig-a3-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


def _store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    store.registry.register(ASSET_OBJECT_TYPE, 1, None)
    return store


def _asset(
    name: str,
    *,
    tenant_id: str | None = None,
    observed: dict[str, Any] | None = None,
    attrs: dict[str, Any] | None = None,
) -> AQObject:
    now = _now()
    attributes = dict(attrs or {})
    attributes["observed_state"] = dict(observed or {})
    return AQObject(
        id="",
        object_type=ASSET_OBJECT_TYPE,
        schema_version=1,
        tenant_id=tenant_id,
        display_name=name,
        attributes=attributes,
        sources=[_source(f"asset:{name}")],
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )


def _check(
    check_id: str = "ssh-root",
    key: str = "ssh.root",
    expected: object = "no",
    *,
    severity: Severity = "high",
) -> Check:
    return Check(
        id=check_id,
        key=key,
        expected=expected,
        comparator="eq",
        severity=severity,
        rationale=f"{key} should satisfy {check_id}.",
        framework_refs=[],
    )


def _baseline(
    baseline_id: str,
    asset_class: str = "linux_server",
    *,
    tenant_id: str | None = None,
    version: int = 1,
    set_by: ActorRef = SYS,
    set_at: datetime | None = None,
) -> Baseline:
    return Baseline(
        id=baseline_id,
        name=f"Baseline {baseline_id}",
        asset_class=asset_class,
        version=version,
        checks=[_check()],
        tenant_id=tenant_id,
        set_by=set_by,
        set_at=set_at or _now(),
    )


def _asset_drift(asset_id: str | None = None, *, score: float = 1.0) -> AssetDrift:
    return AssetDrift(
        asset_id=asset_id or new_id("obj"),
        baseline_id="cis-linux",
        evaluated=1,
        passed=1 if score == 1.0 else 0,
        failed=0 if score == 1.0 else 1,
        score=score,
        items=[],
    )


def _snapshot(
    *,
    tenant_id: str | None = None,
    run_at: datetime,
    score: float = 1.0,
) -> DriftSnapshot:
    return DriftSnapshot(
        id=new_drift_snapshot_id(),
        tenant_id=tenant_id,
        run_at=run_at,
        scope={"object_type": ASSET_OBJECT_TYPE},
        baseline_ids=["cis-linux"],
        overall_score=score,
        asset_drifts=[_asset_drift(score=score)],
        evidence_id=None,
    )


def _config() -> ACGConfig:
    return ACGConfig(
        classification_rules=[
            {
                "asset_class": "linux_server",
                "condition": {
                    "op": "eq",
                    "attr": "attributes.os_family",
                    "value": "linux",
                },
            }
        ]
    )


async def _postgres_baseline_store() -> PostgresBaselineStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresBaselineStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_acg_drift_snapshot, aq_acg_baseline")
    return store


async def _postgres_snapshot_store() -> PostgresDriftSnapshotStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresDriftSnapshotStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_acg_drift_snapshot, aq_acg_baseline")
    return store


async def _baseline_store(kind: str) -> AsyncIterator[BaselineStore]:
    if kind == "inmemory":
        yield InMemoryBaselineStore()
        return
    store = await _postgres_baseline_store()
    try:
        yield store
    finally:
        await store.close()


async def _snapshot_store(kind: str) -> AsyncIterator[DriftSnapshotStore]:
    if kind == "inmemory":
        yield InMemoryDriftSnapshotStore()
        return
    store = await _postgres_snapshot_store()
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_acg_baseline_contract(kind: str) -> None:
    async for store in _baseline_store(kind):
        original = _baseline("cis-linux")
        stored = await store.put(original)

        assert stored.model_dump(mode="json") == original.model_dump(mode="json")
        assert stored is not original

        loaded = await store.get(original.id)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == original.model_dump(mode="json")
        loaded.checks[0].rationale = "mutated locally"
        reloaded = await store.get(original.id)
        assert reloaded is not None
        assert reloaded.checks[0].rationale == original.checks[0].rationale

        replacement_actor = ActorRef(actor_type="user", actor_id="baseline-owner")
        replacement_at = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
        replacement = _baseline(
            "cis-linux", version=2, set_by=replacement_actor, set_at=replacement_at
        )
        await store.put(replacement)
        latest = await store.get("cis-linux")
        assert latest is not None
        assert latest.version == 2
        assert latest.set_by == replacement_actor
        assert latest.set_at == replacement_at

        global_baseline = latest
        tenant_a = await store.put(_baseline("cis-linux-a", tenant_id=TENANT_A))
        tenant_b = await store.put(_baseline("cis-linux-b", tenant_id=TENANT_B))
        await store.put(_baseline("cis-windows", asset_class="windows_server"))

        rows_a = await store.list(tenant_id=TENANT_A, asset_class="linux_server")
        assert [baseline.id for baseline in rows_a] == [global_baseline.id, tenant_a.id]
        assert tenant_b.id not in [baseline.id for baseline in rows_a]

        rows_global = await store.list(tenant_id=None, asset_class="linux_server")
        assert [baseline.id for baseline in rows_global] == [global_baseline.id]

        with pytest.raises(SchemaValidationError):
            await store.list(tenant_id="not-a-uuid")

        with pytest.raises(CrossTenantReference):
            await store.put(_baseline("cis-linux", tenant_id=TENANT_B))

        invalid = Baseline.model_construct(
            id="invalid",
            name="Invalid",
            asset_class="linux_server",
            version=1,
            checks=[],
            tenant_id=None,
            set_by=SYS,
            set_at=_now(),
        )
        with pytest.raises(BaselineConfigInvalid):
            await store.put(invalid)

        assert await store.get("missing-baseline") is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_acg_snapshot_contract(kind: str) -> None:
    async for store in _snapshot_store(kind):
        base = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
        older = _snapshot(tenant_id=TENANT_A, run_at=base, score=0.25)
        newer = _snapshot(tenant_id=TENANT_A, run_at=base + timedelta(minutes=5), score=0.75)
        other_tenant = _snapshot(tenant_id=TENANT_B, run_at=base + timedelta(minutes=10))

        stored = await store.put(older)
        assert stored.model_dump(mode="json") == older.model_dump(mode="json")
        assert stored is not older

        loaded = await store.get(older.id)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == older.model_dump(mode="json")
        loaded.scope["mutated"] = True
        reloaded = await store.get(older.id)
        assert reloaded is not None
        assert reloaded.scope == older.scope

        await store.put(newer)
        await store.put(other_tenant)

        history = await store.history(tenant_id=TENANT_A)
        assert [snapshot.id for snapshot in history] == [older.id, newer.id]
        assert [snapshot.overall_score for snapshot in history] == [0.25, 0.75]

        latest = await store.latest(tenant_id=TENANT_A)
        assert latest is not None
        assert latest.id == newer.id

        since = await store.history(tenant_id=TENANT_A, since=base + timedelta(minutes=1))
        assert [snapshot.id for snapshot in since] == [newer.id]

        limited = await store.history(tenant_id=TENANT_A, limit=1)
        assert [snapshot.id for snapshot in limited] == [older.id]

        assert await store.latest(tenant_id=None) is None
        assert await store.get("missing-snapshot") is None
        with pytest.raises(BaselineConfigInvalid):
            await store.history(tenant_id=TENANT_A, limit=0)

        changed = older.model_copy(update={"overall_score": 1.0}, deep=True)
        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(changed)

        if isinstance(store, PostgresDriftSnapshotStore):
            async with store._pool.acquire() as conn:
                with pytest.raises(asyncpg.PostgresError):
                    await conn.execute(
                        "UPDATE aq_acg_drift_snapshot SET overall_score=1.0 WHERE id=$1",
                        older.id,
                    )


async def test_acg_snapshot_history() -> None:
    object_store = _store()
    baseline_store = InMemoryBaselineStore()
    snapshot_store = InMemoryDriftSnapshotStore()
    await baseline_store.put(_baseline("cis-linux"))
    await object_store.upsert(
        _asset("passing", attrs={"os_family": "linux"}, observed={"ssh.root": "no"})
    )
    await object_store.upsert(
        _asset("failing", attrs={"os_family": "linux"}, observed={"ssh.root": "yes"})
    )
    analyzer = AssetConfigAnalyzer(
        object_store,
        [],
        baseline_store=baseline_store,
        snapshot_store=snapshot_store,
        config=_config(),
    )

    first = await analyzer.assess(tenant_id=None, record_evidence=False)
    second = await analyzer.assess(tenant_id=None, record_evidence=False)

    history = await snapshot_store.history(tenant_id=None)
    assert [snapshot.id for snapshot in history] == [first.id, second.id]
    assert all(snapshot.overall_score == 0.5 for snapshot in history)

    latest = await snapshot_store.latest(tenant_id=None)
    assert latest is not None
    assert latest.id == second.id


def test_acg_snapshot_store_has_no_update_delete_paths() -> None:
    root = Path(__file__).parents[2]
    postgres_source = (root / "src/aqelyn/assetconfig/postgres.py").read_text(encoding="utf-8")
    memory_source = (root / "src/aqelyn/assetconfig/memory.py").read_text(encoding="utf-8")

    assert "UPDATE aq_acg_drift_snapshot" not in postgres_source
    assert "DELETE FROM aq_acg_drift_snapshot" not in postgres_source
    assert "async def update" not in memory_source
    assert "async def delete" not in memory_source
