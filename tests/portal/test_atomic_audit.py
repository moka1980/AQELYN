"""ECR-0124: an audited write and its audit event are one atomic unit.

Codex's review probe of ECR-0118 showed the two-step shape failing exactly as feared: a poisoned
audit log returned 500 while the consent record and the ingested findings stayed behind,
unaudited. These tests re-run that probe against the composites — on the memory backend through
the portal application, and on Postgres against the real single-transaction composite — and pair
every poison with a positive control on the same stores.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.findings.models import FindingQuery

PG_URL = os.getenv("AQELYN_DATABASE_URL")

TENANT_A = "11111111-1111-4111-8111-111111111111"


def _auth(cookie: str) -> dict[str, str]:
    return {"cookie": cookie, "content-type": "application/json"}


def _valid_posture(observation_id: str = "obs-1", *, ref: str = "host-a") -> dict[str, Any]:
    return {
        "observations": [
            {
                "observation_id": observation_id,
                "check": "listening_sockets_public",
                "what_happened": "A port is reachable from outside this machine.",
                "why_it_matters": "Anything reachable is something an attacker can try.",
                "how_determined": "Read the listening sockets and their bind addresses.",
                "risk_of_inaction": "The exposure stays open until it is closed.",
                "severity": "high",
                "severity_score": 70.0,
                "subject": {"ref": ref, "kind": "host"},
                "remediation": {
                    "summary": "Close the port or bind it to loopback.",
                    "expected_outcome": "The port is no longer reachable from outside.",
                    "difficulty": "medium",
                },
            }
        ]
    }


class _AuditDown(RuntimeError):
    pass


_UNIT_EVENT_TYPES = (
    "aqelyn.object.created",
    "aqelyn.object.updated",
    "aqelyn.evidence.recorded",
    "aqelyn.finding.raised",
)


async def _record_unit_events(runtime: Any) -> list[str]:
    """Subscribe to every event type an ingest unit can produce; return the live list."""

    seen: list[str] = []

    async def _on(event: Any) -> None:
        seen.append(event.event_type)

    for event_type in _UNIT_EVENT_TYPES:
        await runtime.event_bus.subscribe(event_type, _on)
    return seen


async def _consent(portal: Any, cookie: str) -> Any:
    return await portal.app.handle(
        "POST", "/api/v1/consent", _auth(cookie), json.dumps({"text_version": "v1"}).encode()
    )


async def _upload(portal: Any, cookie: str) -> Any:
    return await portal.app.handle(
        "POST", "/api/v1/scans", _auth(cookie), json.dumps(_valid_posture()).encode()
    )


def _poison_audit(portal: Any) -> None:
    async def _fail(**_kwargs: Any) -> Any:
        raise _AuditDown("audit log unavailable")

    portal.audit.append = _fail


async def test_memory_positive_control_consent_and_upload_audited(portal: Any) -> None:
    events = await _record_unit_events(portal.runtime)
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="ok@example.com")
    assert (await _consent(portal, cookie)).status == 201
    assert (await _upload(portal, cookie)).status == 201
    actions = [e.action for e in await portal.audit.list(tenant_id=TENANT_A)]
    assert actions == ["consent_granted", "scan_ingested"]
    # A committed unit DOES announce itself, in original write order.
    assert events == [
        "aqelyn.object.created",
        "aqelyn.evidence.recorded",
        "aqelyn.finding.raised",
    ]


async def test_memory_failed_audit_rolls_back_consent(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    _poison_audit(portal)
    response = await _consent(portal, cookie)
    assert response.status == 500
    # The write vanished with its audit event — no persisted-but-unaudited state.
    assert await portal.consent.active(tenant_id=TENANT_A, scope="store_scan") is None
    assert portal.audit._events == []


async def test_memory_failed_audit_rolls_back_the_whole_ingest(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="b@example.com")
    assert (await _consent(portal, cookie)).status == 201
    events = await _record_unit_events(portal.runtime)
    _poison_audit(portal)
    response = await _upload(portal, cookie)
    assert response.status == 500
    found, _ = await portal.runtime.finding_store.query(FindingQuery(tenant_id=TENANT_A, limit=10))
    assert found == []
    assert portal.runtime.evidence_store._by_id == {}
    assert portal.runtime.object_store._objs == {}
    assert [e.action for e in await portal.audit.list(tenant_id=TENANT_A)] == ["consent_granted"]
    # No phantom events: the bus never heard about the rolled-back rows.
    assert events == []


async def test_memory_failed_write_leaves_no_audit_event(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="c@example.com")
    assert (await _consent(portal, cookie)).status == 201

    events = await _record_unit_events(portal.runtime)

    async def _fail(_finding: Any) -> Any:
        raise RuntimeError("finding store down")

    # Poison the quiet write the composite's injected op actually calls.
    portal.runtime.finding_store._raise_quiet = _fail
    response = await _upload(portal, cookie)
    assert response.status == 500
    # The inverse direction: no audit event may claim an ingest that never happened,
    # and the partial writes (object, evidence) roll back with it — events included.
    assert [e.action for e in await portal.audit.list(tenant_id=TENANT_A)] == ["consent_granted"]
    assert portal.runtime.evidence_store._by_id == {}
    assert portal.runtime.object_store._objs == {}
    assert events == []


async def test_memory_rollback_spares_unrelated_concurrent_writes(portal: Any) -> None:
    """Codex's data-loss probe: an unrelated write lands WHILE the portal unit is in flight;
    the unit's rollback must erase only its own rows — not the bystander's."""

    from aqelyn.portal.ingest import PORTAL_SOURCE_ID
    from aqelyn.reporting.posture import ensure_posture_object_type, subject_object

    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="d@example.com")
    assert (await _consent(portal, cookie)).status == 201
    events = await _record_unit_events(portal.runtime)

    ensure_posture_object_type(portal.runtime.object_store)
    external = subject_object(
        _valid_posture(ref="bystander-host")["observations"][0],
        source_id=PORTAL_SOURCE_ID,
        observed_at=datetime.now(UTC),
        actor=ActorRef(actor_type="user", actor_id=new_id("acc")),
    ).model_copy(update={"tenant_id": "33333333-3333-4333-8333-333333333333"})
    external_ids: list[str] = []

    async def _fail_after_external_write(**_kwargs: Any) -> Any:
        # The bystander writes mid-unit, through the shared store's public API.
        stored = await portal.runtime.object_store.upsert(external)
        external_ids.append(stored.id)
        raise _AuditDown("audit log unavailable")

    portal.audit.append = _fail_after_external_write
    response = await _upload(portal, cookie)
    assert response.status == 500

    # The bystander's row survived the portal unit's rollback...
    assert external_ids
    survivor = await portal.runtime.object_store.get(external_ids[0])
    assert survivor is not None
    assert survivor.tenant_id == "33333333-3333-4333-8333-333333333333"
    # ...its event flowed normally (it was never part of the unit)...
    assert events == ["aqelyn.object.created"]
    # ...and the unit's own writes are fully gone.
    found, _ = await portal.runtime.finding_store.query(FindingQuery(tenant_id=TENANT_A, limit=10))
    assert found == []
    assert portal.runtime.evidence_store._by_id == {}
    assert set(portal.runtime.object_store._objs) == {external_ids[0]}


async def test_memory_rollback_spares_a_concurrent_update_to_the_same_row(portal: Any) -> None:
    """Codex's same-row probe: a concurrent writer updates the SAME object the unit already
    touched; the rollback must not overwrite their update with the unit's pre-image."""

    from aqelyn.portal.ingest import PORTAL_SOURCE_ID
    from aqelyn.reporting.posture import ensure_posture_object_type, subject_object

    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="e@example.com")
    assert (await _consent(portal, cookie)).status == 201
    # A committed first upload creates the object the second unit will UPDATE.
    assert (await _upload(portal, cookie)).status == 201
    found, _ = await portal.runtime.finding_store.query(FindingQuery(tenant_id=TENANT_A, limit=10))
    object_id = found[0].affected_object_ids[0]
    evidence_count = len(portal.runtime.evidence_store._by_id)

    ensure_posture_object_type(portal.runtime.object_store)
    concurrent = subject_object(
        _valid_posture()["observations"][0],
        source_id=PORTAL_SOURCE_ID,
        observed_at=datetime.now(UTC),
        actor=ActorRef(actor_type="user", actor_id=new_id("acc")),
    ).model_copy(update={"tenant_id": TENANT_A, "labels": {"kept": "yes"}})

    async def _fail_after_same_row_update(**_kwargs: Any) -> Any:
        # The concurrent writer lands on the SAME row (same tenant + natural key) after the
        # unit's own update, through the shared store's public API.
        await portal.runtime.object_store.upsert(concurrent)
        raise _AuditDown("audit log unavailable")

    portal.audit.append = _fail_after_same_row_update
    response = await _upload(portal, cookie)
    assert response.status == 500

    # The concurrent update survived the unit's rollback (LABEL_AFTER must stay 'kept')...
    survivor = await portal.runtime.object_store.get(object_id)
    assert survivor is not None
    assert survivor.labels.get("kept") == "yes"
    # ...while the unit's own additions rolled back: no new evidence, no new findings.
    assert len(portal.runtime.evidence_store._by_id) == evidence_count
    after, _ = await portal.runtime.finding_store.query(FindingQuery(tenant_id=TENANT_A, limit=10))
    assert sorted(f.id for f in after) == sorted(f.id for f in found)


@pytest.mark.skipif(not PG_URL, reason="AQELYN_DATABASE_URL not set")
async def test_postgres_composite_commits_and_rolls_back_as_one_unit() -> None:
    from aqelyn.consent.postgres import PostgresAuditLog, PostgresConsentStore, connect_pool
    from aqelyn.kernel import AQELYNConfig, create_runtime
    from aqelyn.portal.writes import PostgresAuditedWrites

    assert PG_URL is not None
    runtime = await create_runtime(
        AQELYNConfig(backend="postgres", database_url=PG_URL, tenant_mode="enterprise")
    )
    pool = await connect_pool(PG_URL)
    consent = PostgresConsentStore(pool)
    audit = PostgresAuditLog(pool)

    class _PoisonedAuditLog(PostgresAuditLog):
        async def _append_on(self, conn: Any, **_kwargs: Any) -> Any:
            raise _AuditDown("audit log unavailable")

    try:
        events = await _record_unit_events(runtime)
        # Positive control first: the composite commits consent, ingest, and audit together.
        good_tenant = str(uuid.uuid4())
        actor = ActorRef(actor_type="user", actor_id=new_id("acc"))
        writes = PostgresAuditedWrites(runtime, consent=consent, audit=audit)
        await writes.grant_consent(
            tenant_id=good_tenant, account_id=new_id("acc"), scope="store_scan", text_version="v1"
        )
        findings = await writes.ingest_scan(
            _valid_posture(ref=f"host-{good_tenant[:8]}"),
            tenant_id=good_tenant,
            account_id=new_id("acc"),
            digest=f"sha256:{'0' * 64}",
            observed_at=datetime.now(UTC),
            actor=actor,
        )
        assert findings
        assert await consent.active(tenant_id=good_tenant, scope="store_scan") is not None
        assert [e.action for e in await audit.list(tenant_id=good_tenant)] == [
            "consent_granted",
            "scan_ingested",
        ]
        # A committed unit announces itself, in original write order.
        assert events == [
            "aqelyn.object.created",
            "aqelyn.evidence.recorded",
            "aqelyn.finding.raised",
        ]
        events.clear()

        # The probe: a poisoned audit inside the transaction takes every row down with it.
        bad_tenant = str(uuid.uuid4())
        poisoned = PostgresAuditedWrites(runtime, consent=consent, audit=_PoisonedAuditLog(pool))
        with pytest.raises(_AuditDown):
            await poisoned.grant_consent(
                tenant_id=bad_tenant,
                account_id=new_id("acc"),
                scope="store_scan",
                text_version="v1",
            )
        assert await consent.active(tenant_id=bad_tenant, scope="store_scan") is None

        with pytest.raises(_AuditDown):
            await poisoned.ingest_scan(
                _valid_posture(ref=f"host-{bad_tenant[:8]}"),
                tenant_id=bad_tenant,
                account_id=new_id("acc"),
                digest=f"sha256:{'1' * 64}",
                observed_at=datetime.now(UTC),
                actor=actor,
            )
        found, _ = await runtime.finding_store.query(FindingQuery(tenant_id=bad_tenant, limit=10))
        assert found == []
        # No phantom events: the rolled-back unit never announced its objects/evidence/findings.
        assert events == []
        async with pool.acquire() as conn:
            for table in ("aq_object", "aq_evidence", "aq_finding", "aq_audit_event"):
                count = await conn.fetchval(
                    f"SELECT count(*) FROM {table} WHERE tenant_id=$1", bad_tenant
                )
                assert count == 0, f"{table} kept rows from the rolled-back unit"
    finally:
        await pool.close()
        # Close EVERY pool the factory opened, not just the two the test touches.
        await runtime.close()
