"""S4 acceptance tests for SOC response coordination and hunting."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.evidence import EvidenceStore, InMemoryEvidenceStore
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    InMemoryObjectStore,
    ObjectQuery,
    ObjectStore,
    SourceRef,
)
from aqelyn.soc import (
    Alert,
    Hunt,
    Incident,
    InMemorySOCStore,
    PostgresSOCStore,
    ResponseAction,
    SecurityOperationsEngine,
    SOCConfig,
    SOCStore,
    TimelineEntry,
)
from aqelyn.workflow import (
    ActionSpec,
    InMemoryActionRegistry,
    InMemoryRunStore,
    PostgresRunStore,
    RunStore,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="soc-s4-test")
ANALYST = ActorRef(actor_type="user", actor_id="analyst-1")
NOW = datetime(2026, 7, 14, 20, 0, tzinfo=UTC)


@dataclass
class _TrackingHandler:
    spec: ActionSpec
    simulated: int = 0
    executed: int = 0
    rolled_back: int = 0

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        self.simulated += 1
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        raise AssertionError("SOC S4 must propose Workflow runs, never execute them")

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        self.rolled_back += 1
        raise AssertionError("SOC S4 must not rollback actions")


@dataclass
class SOCHarness:
    kind: str
    store: SOCStore
    evidence: EvidenceStore
    object_store: ObjectStore
    workflow_store: RunStore
    workflow_engine: WorkflowEngine
    handler: _TrackingHandler


class _ObjectStoreSpy:
    def __init__(self, inner: ObjectStore) -> None:
        self.inner = inner
        self.mutations = 0

    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        return await self.inner.get(object_id, resolve_merged=resolve_merged)

    async def upsert(self, obj: AQObject) -> AQObject:
        self.mutations += 1
        return await self.inner.upsert(obj)

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        self.mutations += 1
        return await self.inner.update(obj, expected_version=expected_version)

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        return await self.inner.query(q)

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        self.mutations += 1
        return await self.inner.relate(rel)

    async def relationships(
        self, object_id: str, *, direction: str = "both", relation_type: str | None = None
    ) -> list[AQRelationship]:
        return await self.inner.relationships(
            object_id, direction=direction, relation_type=relation_type
        )

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        self.mutations += 1
        return await self.inner.merge(survivor_id, duplicate_id, by=by)

    async def set_state(
        self, object_id: str, state: str, *, by: ActorRef, expected_version: int
    ) -> AQObject:
        self.mutations += 1
        return await self.inner.set_state(
            object_id, state, by=by, expected_version=expected_version
        )

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        return await self.inner.history(object_id)


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def soc_harness(request: pytest.FixtureRequest) -> AsyncIterator[SOCHarness]:
    handler = _TrackingHandler(
        ActionSpec(
            action_type="soc.notify_owner",
            capability="soc.response.notify",
            effect="reversible",
            reversible=True,
            description="Notify a mission owner through the Workflow Engine.",
        )
    )
    registry = InMemoryActionRegistry()
    registry.register(handler)

    if request.param == "inmemory":
        evidence = InMemoryEvidenceStore()
        workflow_store: RunStore = InMemoryRunStore()
        yield SOCHarness(
            kind="inmemory",
            store=InMemorySOCStore(),
            evidence=evidence,
            object_store=InMemoryObjectStore(),
            workflow_store=workflow_store,
            workflow_engine=WorkflowEngine(
                store=workflow_store,
                registry=registry,
                evidence_store=evidence,
            ),
            handler=handler,
        )
        return

    if PG_URL is None:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.evidence.postgres import PostgresEvidenceStore
    from aqelyn.objects.postgres import PostgresObjectStore

    soc_store = await PostgresSOCStore.connect(PG_URL)
    evidence_store = await PostgresEvidenceStore.connect(PG_URL)
    object_store = await PostgresObjectStore.connect(PG_URL)
    workflow_store = await PostgresRunStore.connect(PG_URL)
    async with soc_store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_soc_incident, aq_soc_alert RESTART IDENTITY")
    async with evidence_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_evidence_custody, aq_evidence_package, aq_evidence RESTART IDENTITY"
        )
    async with object_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    async with workflow_store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
    try:
        yield SOCHarness(
            kind="postgres",
            store=soc_store,
            evidence=evidence_store,
            object_store=object_store,
            workflow_store=workflow_store,
            workflow_engine=WorkflowEngine(
                store=workflow_store,
                registry=registry,
                evidence_store=evidence_store,
            ),
            handler=handler,
        )
    finally:
        await workflow_store.close()
        await object_store.close()
        await evidence_store.close()
        await soc_store.close()


async def test_soc_response_delegates(soc_harness: SOCHarness) -> None:
    asset = await _add_object(soc_harness.object_store, "payments-db")
    incident = await _seed_incident(soc_harness, asset_id=asset.id)
    engine = _engine(soc_harness)

    run_ids = await engine.propose_response(
        incident.id,
        actions=[
            ResponseAction(
                action_type="soc.notify_owner",
                inputs={"asset_id": asset.id, "message": "Review containment."},
            )
        ],
        by=ANALYST,
        expected_version=incident.version,
    )

    assert len(run_ids) == 1
    run = await soc_harness.workflow_store.get(run_ids[0])
    assert run is not None
    assert run.status == "proposed"
    assert run.tenant_id is None
    assert soc_harness.handler.simulated == 0
    assert soc_harness.handler.executed == 0
    assert soc_harness.handler.rolled_back == 0

    updated = await soc_harness.store.get_incident(incident.id)
    assert updated is not None
    assert updated.version == incident.version + 1
    assert updated.timeline[-1].kind == "response_proposed"
    evidence_id = updated.timeline[-1].evidence_id
    assert evidence_id is not None
    evidence = await soc_harness.evidence.get(evidence_id, actor=SYS)
    assert evidence.method == "soc.propose_response/v1"
    assert evidence.content is not None
    assert evidence.content["workflow_run_id"] == run.id
    assert evidence.content["response_action"]["workflow_run_id"] == run.id
    assert evidence.content["response_action"]["status"] == "proposed"
    assert (await soc_harness.evidence.verify(evidence_id)).ok


async def test_soc_response_status(soc_harness: SOCHarness) -> None:
    asset = await _add_object(soc_harness.object_store, "identity-provider")
    incident = await _seed_incident(soc_harness, asset_id=asset.id)
    engine = _engine(soc_harness)

    run_ids = await engine.propose_response(
        incident.id,
        actions=[
            ResponseAction(action_type="soc.notify_owner", inputs={"asset_id": asset.id}),
            ResponseAction(
                action_type="soc.notify_owner",
                inputs={"asset_id": asset.id, "channel": "mission-owner"},
            ),
        ],
        by=ANALYST,
        expected_version=incident.version,
    )

    updated = await soc_harness.store.get_incident(incident.id)
    assert updated is not None
    response_entries = [entry for entry in updated.timeline if entry.kind == "response_proposed"]
    assert len(response_entries) == 2
    assert updated.version == incident.version + 2
    for entry, run_id in zip(response_entries, run_ids, strict=True):
        run = await soc_harness.workflow_store.get(run_id)
        assert run is not None
        action = entry.detail["response_action"]
        assert action["workflow_run_id"] == run.id
        assert action["status"] == run.status
        assert entry.detail["workflow_status"] == run.status


async def test_soc_hunt_readonly(soc_harness: SOCHarness) -> None:
    await _add_object(
        soc_harness.object_store,
        "payments-db",
        labels={"env": "prod"},
        attributes={"os": "linux", "tier": "database"},
    )
    await _add_object(
        soc_harness.object_store,
        "payments-api",
        labels={"env": "prod"},
        attributes={"os": "linux", "tier": "service"},
    )
    await _add_object(
        soc_harness.object_store,
        "sandbox-db",
        labels={"env": "dev"},
        attributes={"os": "linux", "tier": "database"},
    )
    spy = _ObjectStoreSpy(soc_harness.object_store)
    engine = _engine(soc_harness, object_store=spy, config=SOCConfig(batch_size=1))

    matches = await engine.hunt(
        Hunt(
            tenant_id=None,
            name="Prod Linux exposure",
            hypothesis="Find prod Linux objects for investigation.",
            query={
                "object_type": "generic",
                "labels": {"env": "prod"},
                "attribute_equals": {"os": "linux"},
                "limit": 20,
            },
            saved_by=ANALYST,
        )
    )

    assert len(matches) == 1
    assert matches[0]["kind"] == "object"
    assert matches[0]["object_type"] == "generic"
    assert matches[0]["labels"] == {"env": "prod"}
    attributes = matches[0]["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["os"] == "linux"
    assert spy.mutations == 0


async def test_soc_no_side_effects(soc_harness: SOCHarness) -> None:
    asset = await _add_object(
        soc_harness.object_store,
        "crown-jewel-db",
        labels={"criticality": "high"},
        attributes={"contains_pii": True},
    )
    incident = await _seed_incident(soc_harness, asset_id=asset.id)
    before_history = await soc_harness.object_store.history(asset.id)
    spy = _ObjectStoreSpy(soc_harness.object_store)
    engine = _engine(soc_harness, object_store=spy)

    await engine.propose_response(
        incident.id,
        actions=[ResponseAction(action_type="soc.notify_owner", inputs={"asset_id": asset.id})],
        by=ANALYST,
        expected_version=incident.version,
    )
    await engine.hunt(
        Hunt(
            tenant_id=None,
            name="High criticality review",
            hypothesis="Read-only hunt over critical assets.",
            query={"labels": {"criticality": "high"}, "limit": 5},
            saved_by=ANALYST,
        )
    )

    after = await soc_harness.object_store.get(asset.id)
    after_history = await soc_harness.object_store.history(asset.id)
    assert after is not None
    assert after.lifecycle_state == "active"
    assert after.version == asset.version
    assert after.attributes == asset.attributes
    assert before_history == after_history
    assert spy.mutations == 0
    assert soc_harness.handler.executed == 0
    assert soc_harness.handler.rolled_back == 0


def _engine(
    harness: SOCHarness,
    *,
    object_store: ObjectStore | None = None,
    config: SOCConfig | None = None,
) -> SecurityOperationsEngine:
    return SecurityOperationsEngine(
        harness.store,
        harness.evidence,
        workflow_engine=harness.workflow_engine,
        object_store=object_store or harness.object_store,
        config=config,
        actor=SYS,
        source_id=new_id("src"),
    )


async def _seed_incident(harness: SOCHarness, *, asset_id: str) -> Incident:
    alert = await harness.store.upsert_alert(
        Alert(
            tenant_id=None,
            source_kind="finding",
            source_ref=new_id("fnd"),
            evidence_id=new_id("evd"),
            severity="high",
            correlation_key=f"asset:{asset_id}",
            created_at=NOW,
        )
    )
    return await harness.store.upsert_incident(
        Incident(
            tenant_id=None,
            title="SOC S4 response incident",
            status="investigating",
            priority=90.0,
            alert_ids=[alert.id],
            affected_object_ids=[asset_id],
            risk_score=80.0,
            timeline=[
                TimelineEntry(
                    at=NOW,
                    actor=SYS,
                    kind="correlated",
                    detail={"alert_ids": [alert.id]},
                    evidence_id=new_id("evd"),
                )
            ],
            created_by=SYS,
            created_at=NOW,
            updated_at=NOW,
        )
    )


async def _add_object(
    store: ObjectStore,
    display_name: str,
    *,
    labels: dict[str, str] | None = None,
    attributes: dict[str, object] | None = None,
) -> AQObject:
    return await store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            display_name=display_name,
            labels=labels or {},
            attributes=attributes or {},
            sources=[_source(f"object:{display_name}")],
            first_seen_at=NOW,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            created_by=SYS,
            updated_by=SYS,
        )
    )


def _source(method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=NOW,
        method=method,
    )
