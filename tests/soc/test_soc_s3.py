"""S3 acceptance tests for SOC correlation, case work, and investigation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.evidence import EvidenceStore, InMemoryEvidenceStore
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph, PostgresKnowledgeGraph
from aqelyn.mission import MISSION_OBJECT_TYPE, MissionEngine
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    InMemoryObjectStore,
    ObjectStore,
    SourceRef,
)
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.risk import Risk, SignalRef
from aqelyn.soc import (
    Alert,
    InMemorySOCStore,
    PostgresSOCStore,
    SecurityOperationsEngine,
    SOCStore,
    correlate_alerts,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000351"
SYS = ActorRef(actor_type="system", actor_id="soc-s3-test")
ANALYST = ActorRef(actor_type="user", actor_id="analyst-1")
NOW = datetime(2026, 7, 14, 19, 0, tzinfo=UTC)


@dataclass
class SOCHarness:
    kind: str
    store: SOCStore
    evidence: EvidenceStore
    object_store: ObjectStore
    graph: KnowledgeGraph


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def soc_harness(request: pytest.FixtureRequest) -> AsyncIterator[SOCHarness]:
    if request.param == "inmemory":
        object_store = InMemoryObjectStore(registry=_registry())
        yield SOCHarness(
            kind="inmemory",
            store=InMemorySOCStore(),
            evidence=InMemoryEvidenceStore(),
            object_store=object_store,
            graph=InMemoryKnowledgeGraph(object_store),
        )
        return

    if PG_URL is None:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.evidence.postgres import PostgresEvidenceStore
    from aqelyn.objects.postgres import PostgresObjectStore

    soc_store = await PostgresSOCStore.connect(PG_URL)
    evidence_store = await PostgresEvidenceStore.connect(PG_URL)
    postgres_object_store = await PostgresObjectStore.connect(PG_URL, registry=_registry())
    async with soc_store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_soc_incident, aq_soc_alert RESTART IDENTITY")
    async with evidence_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_evidence_custody, aq_evidence_package, aq_evidence RESTART IDENTITY"
        )
    async with postgres_object_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield SOCHarness(
            kind="postgres",
            store=soc_store,
            evidence=evidence_store,
            object_store=postgres_object_store,
            graph=PostgresKnowledgeGraph(postgres_object_store._pool),
        )
    finally:
        await postgres_object_store.close()
        await evidence_store.close()
        await soc_store.close()


def _registry() -> ObjectTypeRegistry:
    registry = ObjectTypeRegistry()
    registry.register(MISSION_OBJECT_TYPE, 1, None)
    return registry


def _source(method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=NOW,
        method=method,
    )


async def _add_object(
    store: ObjectStore,
    display_name: str,
    *,
    object_type: str = "generic",
    attributes: dict[str, object] | None = None,
) -> AQObject:
    return await store.upsert(
        AQObject(
            id="",
            object_type=object_type,
            schema_version=1,
            display_name=display_name,
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


async def _add_relation(
    store: ObjectStore,
    from_obj: AQObject,
    to_obj: AQObject,
    relation_type: str,
) -> AQRelationship:
    return await store.relate(
        AQRelationship(
            id="",
            from_id=from_obj.id,
            to_id=to_obj.id,
            relation_type=relation_type,
            sources=[_source(f"relationship:{relation_type}")],
            created_at=NOW,
            updated_at=NOW,
            created_by=SYS,
            updated_by=SYS,
        )
    )


async def _seed_mission_graph(harness: SOCHarness) -> tuple[AQObject, AQObject, AQObject]:
    asset = await _add_object(harness.object_store, "payments-db")
    service = await _add_object(harness.object_store, "payments-api")
    mission = await _add_object(
        harness.object_store,
        "Process payments",
        object_type=MISSION_OBJECT_TYPE,
        attributes={"criticality_tier": 1},
    )
    await _add_relation(harness.object_store, service, asset, "runs_on")
    await _add_relation(harness.object_store, mission, service, "depends_on")
    return asset, service, mission


def _alert(
    *,
    source_kind: str = "finding",
    source_ref: str | None = None,
    correlation_key: str,
    severity: str = "high",
    evidence_id: str | None = None,
) -> Alert:
    return Alert.model_validate(
        {
            "tenant_id": None,
            "source_kind": source_kind,
            "source_ref": source_ref or new_id("fnd"),
            "evidence_id": evidence_id or new_id("evd"),
            "severity": severity,
            "correlation_key": correlation_key,
            "created_at": NOW,
        }
    )


def _risk(*, risk_id: str, correlation_key: str, asset_id: str, score: float = 65.0) -> Risk:
    evidence_id = new_id("evd")
    return Risk(
        id=risk_id,
        correlation_key=correlation_key,
        title="SOC correlated operational risk",
        category="soc",
        likelihood=0.6,
        impact=0.5,
        score=score,
        band="elevated",
        signals=[
            SignalRef(
                kind="finding",
                ref_id=new_id("fnd"),
                weight=0.7,
                evidence_id=evidence_id,
            )
        ],
        affected_object_ids=[asset_id],
        reason="Risk context for SOC priority.",
        first_seen_at=NOW,
        last_scored_at=NOW,
    )


def _engine(
    harness: SOCHarness,
    *,
    mission: MissionEngine | None = None,
) -> SecurityOperationsEngine:
    return SecurityOperationsEngine(
        harness.store,
        harness.evidence,
        graph=harness.graph,
        mission_engine=mission,
        actor=SYS,
        source_id=new_id("src"),
    )


async def test_soc_correlate_incidents(soc_harness: SOCHarness) -> None:
    asset, _, _ = await _seed_mission_graph(soc_harness)
    key = f"asset:{asset.id}"
    risk = _risk(risk_id="risk:soc-s3", correlation_key=key, asset_id=asset.id, score=65.0)
    alerts = [
        _alert(correlation_key=key, severity="high"),
        _alert(source_kind="risk", source_ref=risk.id, correlation_key=key, severity="medium"),
    ]
    mission = MissionEngine(soc_harness.object_store, soc_harness.graph)
    engine = _engine(soc_harness, mission=mission)

    incidents = await engine.correlate(tenant_id=None, alerts=alerts, risks=[risk], by=SYS)

    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.alert_ids == sorted(alert.id for alert in alerts)
    assert incident.affected_object_ids == [asset.id]
    assert incident.risk_score == 65.0
    assert incident.timeline[0].kind == "correlated"
    assert incident.timeline[0].evidence_id is not None
    record = await soc_harness.evidence.get(incident.timeline[0].evidence_id, actor=SYS)
    assert record.method == "soc.correlate/v1"
    assert record.content is not None
    assert record.content["alert_ids"] == incident.alert_ids

    first = await correlate_alerts(alerts, tenant_id=None, by=SYS, risks=[risk], now=NOW)
    second = await correlate_alerts(
        list(reversed(alerts)),
        tenant_id=None,
        by=SYS,
        risks=[risk],
        now=NOW,
    )
    assert [_without_generated_id(item) for item in first] == [
        _without_generated_id(item) for item in second
    ]


async def test_soc_priority(soc_harness: SOCHarness) -> None:
    asset, _, mission = await _seed_mission_graph(soc_harness)
    key = f"asset:{asset.id}"
    risk = _risk(risk_id="risk:soc-priority", correlation_key=key, asset_id=asset.id, score=65.0)
    alert = _alert(source_kind="risk", source_ref=risk.id, correlation_key=key)
    engine = _engine(
        soc_harness,
        mission=MissionEngine(soc_harness.object_store, soc_harness.graph),
    )

    [incident] = await engine.correlate(tenant_id=None, alerts=[alert], risks=[risk], by=SYS)

    assert incident.risk_score == 65.0
    assert incident.top_mission_id == mission.id
    assert incident.priority == 100.0
    details = engine.explain(incident)
    assert details["method"] == "soc.correlation/v1"
    assert details["risk_score"] == 65.0
    assert details["top_mission_id"] == mission.id


async def test_soc_assign(soc_harness: SOCHarness) -> None:
    incident = await _seed_incident(soc_harness)
    engine = _engine(soc_harness)

    assigned = await engine.assign(
        incident.id,
        to=ANALYST,
        by=SYS,
        expected_version=incident.version,
    )

    assert assigned.version == incident.version + 1
    assert assigned.assignee == ANALYST
    assert assigned.timeline[-1].kind == "assigned"
    evidence_id = assigned.timeline[-1].evidence_id
    assert evidence_id is not None
    record = await soc_harness.evidence.get(evidence_id, actor=SYS)
    assert record.method == "soc.assign/v1"
    assert record.content is not None
    assert record.content["to"] == ANALYST.model_dump()
    assert (await soc_harness.evidence.verify(evidence_id)).ok


async def test_soc_transition_evidence(soc_harness: SOCHarness) -> None:
    incident = await _seed_incident(soc_harness)
    engine = _engine(soc_harness)

    transitioned = await engine.transition(
        incident.id,
        "triaged",
        by=ANALYST,
        note="Confirmed as actionable.",
        expected_version=incident.version,
    )

    assert transitioned.status == "triaged"
    assert transitioned.version == incident.version + 1
    assert transitioned.timeline[-1].kind == "status_changed"
    evidence_id = transitioned.timeline[-1].evidence_id
    assert evidence_id is not None
    record = await soc_harness.evidence.get(evidence_id, actor=SYS)
    assert record.method == "soc.transition/v1"
    assert record.content is not None
    assert record.content["from_status"] == "new"
    assert record.content["to_status"] == "triaged"
    assert record.content["note"] == "Confirmed as actionable."


async def test_soc_investigate_pivot(soc_harness: SOCHarness) -> None:
    asset, service, _ = await _seed_mission_graph(soc_harness)
    incident = await _seed_incident(soc_harness, asset_id=asset.id)
    engine = _engine(soc_harness)

    investigated = await engine.investigate(
        incident.id,
        pivot={"start_id": asset.id, "direction": "in", "max_depth": 1},
        by=ANALYST,
        expected_version=incident.version,
    )

    assert investigated.status == "investigating"
    assert investigated.timeline[-1].kind == "investigated"
    assert investigated.timeline[-1].detail["node_count"] == 2
    evidence_id = investigated.timeline[-1].evidence_id
    assert evidence_id is not None
    record = await soc_harness.evidence.get(evidence_id, actor=SYS)
    assert record.method == "soc.investigate/v1"
    assert record.content is not None
    nodes = {node["id"] for node in record.content["subgraph"]["nodes"]}
    assert {asset.id, service.id}.issubset(nodes)


async def test_soc_case_auditable(soc_harness: SOCHarness) -> None:
    asset, _, _ = await _seed_mission_graph(soc_harness)
    incident = await _seed_incident(soc_harness, asset_id=asset.id)
    engine = _engine(soc_harness)

    assigned = await engine.assign(
        incident.id,
        to=ANALYST,
        by=SYS,
        expected_version=incident.version,
    )
    transitioned = await engine.transition(
        assigned.id,
        "investigating",
        by=ANALYST,
        note="Starting graph pivot.",
        expected_version=assigned.version,
    )
    investigated = await engine.investigate(
        transitioned.id,
        pivot={"start_id": asset.id, "direction": "both", "max_depth": 1},
        by=ANALYST,
        expected_version=transitioned.version,
    )

    assert len(investigated.timeline) == 4
    evidence_ids = [entry.evidence_id for entry in investigated.timeline]
    assert all(evidence_ids)
    for evidence_id in evidence_ids:
        assert evidence_id is not None
        record = await soc_harness.evidence.get(evidence_id, actor=SYS)
        assert record.evidence_type == "soc.case_step"
        assert record.content is not None
        assert record.content["incident_id"] == investigated.id
        assert (await soc_harness.evidence.verify(evidence_id)).ok


async def _seed_incident(soc_harness: SOCHarness, *, asset_id: str | None = None) -> Any:
    selected_asset = asset_id or new_id("obj")
    key = f"asset:{selected_asset}"
    alert = _alert(correlation_key=key)
    engine = _engine(soc_harness)
    [incident] = await engine.correlate(tenant_id=None, alerts=[alert], by=SYS)
    return incident


def _without_generated_id(incident: Any) -> dict[str, Any]:
    dumped = incident.model_dump(mode="json")
    dumped["id"] = "<generated>"
    return cast(dict[str, Any], dumped)
