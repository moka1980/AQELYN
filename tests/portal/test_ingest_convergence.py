"""ECR-0123: two tenants uploading the SAME hostname must not converge on one object.

The object store resolves natural keys per tenant, and ingest stamps ``tenant_id`` on the object,
the evidence, and the finding — but until now no test uploaded an identical subject ref from two
tenants and looked at the object ids. The cross-tenant isolation matrix proved *findings* isolate;
this is the object-level adversarial case the review of ECR-0115…0121 asked for, on both backends.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime, create_runtime
from aqelyn.portal.ingest import ingest_posture_document

PG_URL = os.getenv("AQELYN_DATABASE_URL")


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


async def _runtime(backend: str) -> Runtime:
    config = AQELYNConfig(tenant_mode="enterprise")
    if backend == "memory":
        return create_inmemory_runtime(config)
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    return await create_runtime(
        config.model_copy(update={"backend": "postgres", "database_url": PG_URL})
    )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_same_hostname_from_two_tenants_gets_separate_objects(backend: str) -> None:
    runtime = await _runtime(backend)
    try:
        shared_ref = f"host-{uuid.uuid4().hex[:12]}"
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        per_tenant_object_ids: dict[str, set[str]] = {}
        for tenant in (tenant_a, tenant_b):
            findings = await ingest_posture_document(
                runtime,
                _valid_posture(f"obs-{uuid.uuid4()}", ref=shared_ref),
                tenant_id=tenant,
                digest=f"sha256:{'0' * 64}",
                observed_at=datetime.now(UTC),
                actor=ActorRef(actor_type="user", actor_id=new_id("acc")),
            )
            assert findings
            per_tenant_object_ids[tenant] = {
                object_id for finding in findings for object_id in finding.affected_object_ids
            }
            assert per_tenant_object_ids[tenant]
            for finding in findings:
                assert finding.tenant_id == tenant
        # The breach-not-blemish property: identical natural keys never converge across tenants.
        assert per_tenant_object_ids[tenant_a].isdisjoint(per_tenant_object_ids[tenant_b])
        for tenant, object_ids in per_tenant_object_ids.items():
            for object_id in object_ids:
                stored = await runtime.object_store.get(object_id)
                assert stored is not None
                assert stored.tenant_id == tenant
    finally:
        # Close EVERY pool the factory opened (no-op on the memory backend).
        await runtime.close()
