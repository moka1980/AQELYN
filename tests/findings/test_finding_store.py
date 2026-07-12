"""T5 acceptance tests for the Finding model (§11). In-memory and Postgres."""

from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import (
    EvidenceRequired,
    InvalidFindingTransition,
    SchemaValidationError,
)
from aqelyn.events import InMemoryEventBus
from aqelyn.findings import (
    Automation,
    Finding,
    FindingQuery,
    InMemoryFindingStore,
    Remediation,
    register_finding_events,
)

SYS = ActorRef(actor_type="user", actor_id="analyst")


def _finding(**kw: Any) -> Finding:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "id": "",
        "finding_type": "aqelyn.finding.device.open_port",
        "schema_version": 1,
        "dedup_key": "dev1:port22",
        "title": "SSH exposed to the internet",
        "severity": "high",
        "severity_score": 80.0,
        "what_happened": "Port 22 is reachable from any address.",
        "why_it_matters": "Attackers can attempt to brute-force SSH.",
        "how_determined": "A TCP connect scan observed an open port 22.",
        "risk_of_inaction": "Unauthorized access is likely over time.",
        "evidence_ids": [new_id("evd")],
        "affected_object_ids": [new_id("obj")],
        "remediation": Remediation(
            summary="Restrict SSH to trusted networks.",
            steps=["Add a firewall rule", "Verify access"],
            difficulty="easy",
            expected_outcome="Port 22 no longer reachable publicly.",
        ),
        "automation": Automation(eligibility="assisted"),
        "source_engine": "port-scanner",
        "first_detected_at": now,
        "last_detected_at": now,
    }
    base.update(kw)
    return Finding(**base)


async def test_finding_requires_explanation(finding_store: Any) -> None:
    with pytest.raises(SchemaValidationError):
        await finding_store.raise_finding(_finding(why_it_matters="  "))


async def test_finding_requires_evidence(finding_store: Any) -> None:
    with pytest.raises(EvidenceRequired):
        await finding_store.raise_finding(_finding(evidence_ids=[]))


async def test_finding_persisted_ids_are_typed(finding_store: Any) -> None:
    saved = await finding_store.raise_finding(_finding())
    assert parse_id(saved.id)[0] == "fnd"
    assert all(parse_id(evidence_id)[0] == "evd" for evidence_id in saved.evidence_ids)
    assert all(parse_id(object_id)[0] == "obj" for object_id in saved.affected_object_ids)


async def test_finding_malformed_typed_id_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        _finding(evidence_ids=["evd_not-a-uuid"])


async def test_finding_non_uuid_tenant_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        _finding(tenant_id="not-a-uuid")


async def test_finding_dedup(finding_store: Any) -> None:
    first_evidence_id = new_id("evd")
    second_evidence_id = new_id("evd")
    a = await finding_store.raise_finding(_finding(evidence_ids=[first_evidence_id]))
    b = await finding_store.raise_finding(_finding(evidence_ids=[second_evidence_id]))
    assert a.id == b.id
    assert set(b.evidence_ids) == {first_evidence_id, second_evidence_id}


async def test_finding_regression_reopen(finding_store: Any) -> None:
    a = await finding_store.raise_finding(_finding())
    await finding_store.transition(
        a.id, "in_progress", by=SYS, note=None, expected_version=a.version
    )
    cur = await finding_store.get(a.id)
    await finding_store.transition(
        cur.id, "resolved", by=SYS, note=None, expected_version=cur.version
    )
    reopened = await finding_store.raise_finding(_finding())
    assert reopened.status == "open"


async def test_finding_invalid_transition(finding_store: Any) -> None:
    a = await finding_store.raise_finding(_finding())
    with pytest.raises(InvalidFindingTransition):
        await finding_store.transition(
            a.id, "resolved", by=SYS, note=None, expected_version=a.version
        )


async def test_finding_transition_audited(finding_store: Any) -> None:
    a = await finding_store.raise_finding(_finding())
    updated = await finding_store.transition(
        a.id, "acknowledged", by=SYS, note="seen", expected_version=a.version
    )
    actions = [e.action for e in updated.audit]
    assert "raised" in actions
    assert "transition" in actions


async def test_finding_postgres_audit_table_append_only(finding_store: Any) -> None:
    if not hasattr(finding_store, "_pool"):
        pytest.skip("Postgres schema check")
    a = await finding_store.raise_finding(_finding())
    await finding_store.transition(
        a.id, "acknowledged", by=SYS, note="seen", expected_version=a.version
    )
    async with finding_store._pool.acquire() as conn:
        audit_rows = await conn.fetchval(
            "SELECT count(*) FROM aq_finding_audit WHERE finding_id=$1", a.id
        )
        mutable_audit_columns = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='aq_finding' AND column_name='audit'"
        )
    assert audit_rows == 2
    assert mutable_audit_columns == 0


async def test_finding_raised_event() -> None:
    bus = InMemoryEventBus()
    register_finding_events(bus.registry)

    async def yes(_e: str) -> bool:
        return True

    store = InMemoryFindingStore(event_bus=bus, evidence_exists=yes)
    f = await store.raise_finding(_finding())
    assert any(
        e.event_type == "aqelyn.finding.raised" and e.subject.finding_id == f.id for e in bus.log
    )


async def test_finding_evidence_exists() -> None:
    async def no(_e: str) -> bool:
        return False

    store = InMemoryFindingStore(evidence_exists=no)
    with pytest.raises(EvidenceRequired):
        await store.raise_finding(_finding(evidence_ids=[new_id("evd")]))


async def test_finding_query_by_severity(finding_store: Any) -> None:
    await finding_store.raise_finding(_finding())
    rows, _ = await finding_store.query(FindingQuery(severity=("high",)))
    assert len(rows) == 1
    assert rows[0].severity == "high"
