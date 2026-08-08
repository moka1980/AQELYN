"""ECR-0123: the Postgres runtime's evidence/finding stores are durable, not in-memory.

ECR-0120 made sessions shared, but the runtime factory still built `InMemoryEvidenceStore` /
`InMemoryFindingStore` on the Postgres path — so an upload ingested on worker A was invisible to
worker B and lost on restart (Codex review finding, 2026-08-08). The load-bearing witness is the
ECR-0120 shape: rows written through the runtime's stores are read back by *fresh store
instances* on the same database — another worker, or the process after a restart.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.evidence.postgres import PostgresEvidenceStore
from aqelyn.findings.models import FindingQuery
from aqelyn.findings.postgres import PostgresFindingStore
from aqelyn.kernel import AQELYNConfig, Runtime, create_runtime
from aqelyn.portal.ingest import ingest_posture_document

PG_URL = os.getenv("AQELYN_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="AQELYN_DATABASE_URL not set")


def _valid_posture(observation_id: str, *, ref: str) -> dict[str, Any]:
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


async def _close_stores(runtime: Runtime) -> None:
    # The stores are exercised directly (a full kernel start needs seeded engine providers);
    # close the pools this test opened.
    assert isinstance(runtime.evidence_store, PostgresEvidenceStore)
    assert isinstance(runtime.finding_store, PostgresFindingStore)
    await runtime.evidence_store.close()
    await runtime.finding_store.close()


async def test_ingested_findings_survive_a_new_store_instance() -> None:
    assert PG_URL is not None
    runtime = await create_runtime(
        AQELYNConfig(backend="postgres", database_url=PG_URL, tenant_mode="enterprise")
    )
    try:
        # The structural half of the reopened claim: the Postgres path no longer holds
        # process-memory evidence/finding stores.
        assert isinstance(runtime.evidence_store, PostgresEvidenceStore)
        assert isinstance(runtime.finding_store, PostgresFindingStore)

        tenant = str(uuid.uuid4())
        raised = await ingest_posture_document(
            runtime,
            _valid_posture(f"obs-{uuid.uuid4()}", ref=f"host-{tenant[:8]}"),
            tenant_id=tenant,
            digest=f"sha256:{'0' * 64}",
            observed_at=datetime.now(UTC),
            actor=ActorRef(actor_type="user", actor_id=new_id("acc")),
        )
        assert raised

        # A DIFFERENT store instance on the same database — i.e. another worker — reads it
        # back. An in-memory store passes every same-instance test and fails exactly this.
        fresh_findings = PostgresFindingStore(runtime.finding_store._pool, mode="enterprise")
        found, _ = await fresh_findings.query(FindingQuery(tenant_id=tenant, limit=10))
        assert sorted(f.id for f in found) == sorted(f.id for f in raised)

        evidence_ids = {eid for f in found for eid in f.evidence_ids}
        assert evidence_ids
        fresh_evidence = PostgresEvidenceStore(runtime.evidence_store._pool, mode="enterprise")
        for evidence_id in evidence_ids:
            assert await fresh_evidence.exists(evidence_id)
        # The positive control's twin: exists() must be a real lookup, not a yes-machine.
        assert not await fresh_evidence.exists(new_id("evd"))
    finally:
        await _close_stores(runtime)
