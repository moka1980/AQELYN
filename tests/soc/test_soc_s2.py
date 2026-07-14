"""S2 acceptance tests for SOCStore persistence."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import ActorRef, is_valid, new_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict, TenantScopeRequired
from aqelyn.findings.models import Severity
from aqelyn.soc import (
    Alert,
    Incident,
    IncidentStatus,
    InMemorySOCStore,
    PostgresSOCStore,
    SOCStore,
    TimelineEntry,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000251"
TENANT_B = "018f0000-0000-7000-8000-000000000252"
SYS = ActorRef(actor_type="system", actor_id="soc-store-test")
NOW = datetime(2026, 7, 14, 18, 0, tzinfo=UTC)


def _alert(
    *,
    alert_id: str = "",
    tenant_id: str | None = None,
    source_ref: str = "finding:f1",
    evidence_id: str | None = None,
    severity: Severity = "high",
    state: str = "new",
    created_at: datetime = NOW,
) -> Alert:
    return Alert.model_validate(
        {
            "id": alert_id,
            "tenant_id": tenant_id,
            "source_kind": "finding",
            "source_ref": source_ref,
            "evidence_id": evidence_id,
            "severity": severity,
            "state": state,
            "correlation_key": "soc:store-contract",
            "created_at": created_at,
            "version": 1,
        }
    )


def _incident(
    *,
    incident_id: str = "",
    tenant_id: str | None = None,
    status: IncidentStatus = "new",
    priority: float = 50.0,
    alert_ids: list[str] | None = None,
    affected_object_ids: list[str] | None = None,
    updated_at: datetime = NOW,
) -> Incident:
    return Incident(
        id=incident_id,
        tenant_id=tenant_id,
        title="SOC store contract incident",
        status=status,
        priority=priority,
        alert_ids=alert_ids or [],
        affected_object_ids=affected_object_ids or [],
        risk_score=priority,
        timeline=[
            TimelineEntry(
                at=NOW,
                actor=SYS,
                kind="created",
                detail={"source": "test"},
                evidence_id=new_id("evd"),
            )
        ],
        created_by=SYS,
        created_at=NOW,
        updated_at=updated_at,
        version=1,
    )


async def _postgres_store(*, mode: str = "local") -> PostgresSOCStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresSOCStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_soc_incident, aq_soc_alert RESTART IDENTITY")
    return store


async def _store(kind: str, *, mode: str = "local") -> AsyncIterator[SOCStore]:
    if kind == "inmemory":
        yield InMemorySOCStore(mode=mode)
        return
    store = await _postgres_store(mode=mode)
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_soc_store_contract(kind: str) -> None:
    async for store in _store(kind):
        created_alert = await store.upsert_alert(
            _alert(evidence_id=new_id("evd"), created_at=NOW - timedelta(minutes=5))
        )

        assert is_valid(created_alert.id, "alt")
        assert created_alert.version == 1

        triaged_alert = await store.upsert_alert(
            created_alert.model_copy(update={"state": "triaged"}, deep=True)
        )
        assert triaged_alert.id == created_alert.id
        assert triaged_alert.created_at == created_alert.created_at
        assert triaged_alert.version == 2

        created_incident = await store.upsert_incident(
            _incident(alert_ids=[triaged_alert.id], affected_object_ids=[new_id("obj")])
        )
        assert is_valid(created_incident.id, "inc")
        assert created_incident.version == 1

        loaded = await store.get_incident(created_incident.id)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == created_incident.model_dump(mode="json")
        assert loaded is not created_incident
        loaded.timeline[0].detail["mutated"] = True
        reloaded = await store.get_incident(created_incident.id)
        assert reloaded is not None
        assert reloaded.model_dump(mode="json") == created_incident.model_dump(mode="json")

        changed = created_incident.model_copy(
            update={
                "status": "triaged",
                "priority": 80.0,
                "risk_score": 80.0,
                "updated_at": NOW + timedelta(minutes=1),
            },
            deep=True,
        )
        updated = await store.upsert_incident(changed)
        assert updated.version == 2
        assert updated.created_at == created_incident.created_at
        assert updated.updated_at >= changed.updated_at
        assert updated.status == "triaged"

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.upsert_incident(changed)

        await store.upsert_incident(_incident(priority=20.0, updated_at=NOW + timedelta(minutes=2)))
        rows = await store.query_incidents(tenant_id=None, status=["triaged"])
        assert [incident.id for incident in rows] == [updated.id]
        assert await store.get_incident(new_id("inc")) is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_soc_tenant_isolation(kind: str) -> None:
    async for store in _store(kind, mode="enterprise"):
        alert_a = await store.upsert_alert(
            _alert(tenant_id=TENANT_A, source_ref="finding:a", evidence_id=new_id("evd"))
        )
        alert_b = await store.upsert_alert(
            _alert(tenant_id=TENANT_B, source_ref="finding:b", evidence_id=new_id("evd"))
        )
        incident_a = await store.upsert_incident(
            _incident(tenant_id=TENANT_A, alert_ids=[alert_a.id], priority=90.0)
        )
        incident_b = await store.upsert_incident(
            _incident(tenant_id=TENANT_B, alert_ids=[alert_b.id], priority=10.0)
        )

        assert await store.get_incident(incident_a.id, tenant_id=TENANT_A) is not None
        assert await store.get_incident(incident_b.id, tenant_id=TENANT_A) is None

        rows_a = await store.query_incidents(tenant_id=TENANT_A)
        assert [incident.id for incident in rows_a] == [incident_a.id]
        assert incident_b.id not in [incident.id for incident in rows_a]

        with pytest.raises(TenantScopeRequired):
            await store.query_incidents(tenant_id=None)
