"""G3 acceptance tests for governance snapshot persistence."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict, SchemaValidationError
from aqelyn.governance import (
    ComplianceEngine,
    ComplianceSnapshot,
    ControlResult,
    GovernanceConfig,
    InMemorySnapshotStore,
    PostgresSnapshotStore,
    SnapshotStore,
)
from aqelyn.objects import AQObject, InMemoryObjectStore, SourceRef
from aqelyn.policy import Condition, Policy, PolicyEngine, Rule, Target

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="governance-g3-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _control_result(score: float = 1.0) -> ControlResult:
    failed = 0 if score == 1.0 else 1
    return ControlResult(
        control_id="control-mfa",
        evaluated=1,
        passed=1 - failed,
        failed=failed,
        failing_subject_ids=[] if failed == 0 else [new_id("obj")],
        score=score,
        reason=f"score {score}",
    )


def _snapshot(
    *,
    tenant_id: str | None = None,
    run_at: datetime,
    score: float = 1.0,
) -> ComplianceSnapshot:
    return ComplianceSnapshot(
        id=new_id("snap"),
        tenant_id=tenant_id,
        run_at=run_at,
        scope={"object_type": "generic"},
        overall_score=score,
        control_results=[_control_result(score)],
        framework_scores={},
        evidence_id=None,
    )


async def _postgres_store() -> PostgresSnapshotStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresSnapshotStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_compliance_snapshot")
    return store


async def _store(kind: str) -> AsyncIterator[SnapshotStore]:
    if kind == "inmemory":
        yield InMemorySnapshotStore()
        return
    store = await _postgres_store()
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_gov_snapshot_contract(kind: str) -> None:
    async for store in _store(kind):
        base = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
        older = _snapshot(run_at=base, score=0.25)
        newer = _snapshot(run_at=base + timedelta(minutes=5), score=0.75)
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

        assert await store.get(new_id("snap")) is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_gov_snapshot_history(kind: str) -> None:
    async for store in _store(kind):
        base = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
        older = await store.put(_snapshot(tenant_id=TENANT_A, run_at=base, score=0.25))
        newer = await store.put(
            _snapshot(tenant_id=TENANT_A, run_at=base + timedelta(minutes=5), score=0.75)
        )
        await store.put(_snapshot(tenant_id=TENANT_B, run_at=base + timedelta(minutes=10)))

        history = await store.history(tenant_id=TENANT_A)
        assert [snapshot.id for snapshot in history] == [older.id, newer.id]
        assert [snapshot.overall_score for snapshot in history] == [0.25, 0.75]

        limited = await store.history(tenant_id=TENANT_A, limit=1)
        assert [snapshot.id for snapshot in limited] == [older.id]

        since = await store.history(tenant_id=TENANT_A, since=base + timedelta(minutes=1))
        assert [snapshot.id for snapshot in since] == [newer.id]

        latest = await store.latest(tenant_id=TENANT_A)
        assert latest is not None
        assert latest.id == newer.id

        assert await store.latest(tenant_id=None) is None
        assert await store.get(new_id("snap")) is None
        with pytest.raises(SchemaValidationError):
            await store.history(tenant_id=TENANT_A, limit=0)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_gov_snapshot_append_only(kind: str) -> None:
    async for store in _store(kind):
        snapshot = _snapshot(run_at=datetime(2026, 7, 13, 12, 0, tzinfo=UTC), score=0.25)
        await store.put(snapshot)
        changed = snapshot.model_copy(update={"overall_score": 1.0}, deep=True)

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(changed)

        loaded = await store.get(snapshot.id)
        assert loaded is not None
        assert loaded.overall_score == 0.25


async def test_gov_snapshot_history_from_assess() -> None:
    object_store = InMemoryObjectStore()
    snapshot_store = InMemorySnapshotStore()
    await object_store.upsert(_obj("passing", attrs={"mfa_enabled": True}))
    await object_store.upsert(_obj("failing", attrs={"mfa_enabled": False}))
    engine = ComplianceEngine(
        object_store,
        PolicyEngine([_policy()]),
        config=_config(),
        snapshot_store=snapshot_store,
    )

    first = await engine.assess(tenant_id=None, record_evidence=False)
    second = await engine.assess(tenant_id=None, record_evidence=False)

    history = await snapshot_store.history(tenant_id=None)
    assert [snapshot.id for snapshot in history] == [first.id, second.id]
    assert all(snapshot.overall_score == 0.5 for snapshot in history)

    latest = await snapshot_store.latest(tenant_id=None)
    assert latest is not None
    assert latest.id == second.id

    trend = await engine.trend(tenant_id=None, since=first.run_at)
    assert [point["snapshot_id"] for point in trend] == [first.id, second.id]
    assert [point["overall_score"] for point in trend] == [0.5, 0.5]
    assert trend[0]["control_scores"] == {"control-mfa": 0.5}


def test_gov_snapshot_store_has_no_update_delete_paths() -> None:
    root = Path(__file__).parents[2]
    postgres_source = (root / "src/aqelyn/governance/postgres.py").read_text(encoding="utf-8")
    memory_source = (root / "src/aqelyn/governance/memory.py").read_text(encoding="utf-8")

    assert "UPDATE aq_compliance_snapshot" not in postgres_source
    assert "DELETE FROM aq_compliance_snapshot" not in postgres_source
    assert "async def update" not in memory_source
    assert "async def delete" not in memory_source


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "governance-g3-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


def _obj(name: str, *, attrs: dict[str, Any]) -> AQObject:
    now = _now()
    return AQObject(
        id="",
        object_type="generic",
        schema_version=1,
        display_name=name,
        attributes=attrs,
        sources=[_source(f"governance:{name}")],
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )


def _condition(payload: dict[str, object]) -> Condition:
    return Condition.model_validate(payload)


def _policy() -> Policy:
    return Policy(
        id="policy-mfa",
        version=1,
        name="MFA policy",
        description="Require MFA",
        rules=[
            Rule(
                id="require-mfa",
                kind="compliance",
                description="mfa_enabled must be true",
                target=Target(actions=None, resource_types=["generic"]),
                condition=_condition(
                    {"op": "eq", "attr": "resource.attributes.mfa_enabled", "value": True}
                ),
                effect="require",
                obligations=[],
                priority=0,
            )
        ],
        set_by=SYS,
        set_at=_now(),
    )


def _config() -> GovernanceConfig:
    return GovernanceConfig.model_validate(
        {
            "controls": [
                {
                    "id": "control-mfa",
                    "name": "MFA enabled",
                    "description": "Generic objects must have MFA enabled.",
                    "policy_ids": ["policy-mfa"],
                    "framework_refs": [{"framework": "AQ", "requirement": "AQ-1"}],
                    "severity": "high",
                }
            ],
            "frameworks": {"AQ": ["AQ-1"]},
            "batch_size": 100,
            "min_confidence": 0.0,
        },
        context={"known_policy_ids": {"policy-mfa"}},
    )
