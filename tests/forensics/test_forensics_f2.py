"""F2 acceptance tests for Digital Forensics artifact persistence."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import CrossTenantReference, SchemaValidationError
from aqelyn.forensics import (
    Artifact,
    ArtifactStore,
    InMemoryArtifactStore,
    PostgresArtifactStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"
CASE_A = new_id("inc")
CASE_B = new_id("inc")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


@dataclass
class ArtifactHarness:
    kind: str
    store: ArtifactStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def artifact_harness(
    request: pytest.FixtureRequest,
) -> AsyncIterator[ArtifactHarness]:
    if request.param == "inmemory":
        yield ArtifactHarness(kind="inmemory", store=InMemoryArtifactStore())
        return

    if PG_URL is None:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresArtifactStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_forensics_artifact")
    try:
        yield ArtifactHarness(kind="postgres", store=store)
    finally:
        await store.close()


async def test_dfe_artifact_contract(artifact_harness: ArtifactHarness) -> None:
    store = artifact_harness.store
    original = _artifact(artifact_id="", metadata={"profile": "Default"})
    stored = await store.put(original)

    assert stored.id.startswith("art_")
    assert stored is not original
    assert stored.model_dump(mode="json") == original.model_copy(
        update={"id": stored.id}, deep=True
    ).model_dump(mode="json")

    loaded = await store.get(stored.id)
    assert loaded is not None
    assert loaded.model_dump(mode="json") == stored.model_dump(mode="json")
    loaded.metadata["profile"] = "mutated locally"
    reloaded = await store.get(stored.id)
    assert reloaded is not None
    assert reloaded.metadata == {"profile": "Default"}

    updated = await store.put(
        _artifact(
            artifact_id=stored.id,
            artifact_type="browser_history",
            metadata={"profile": "Default", "entries": 4},
            first_seen_at=NOW + timedelta(minutes=5),
        )
    )
    assert updated.id == stored.id
    assert updated.artifact_type == "browser_history"
    assert updated.metadata["entries"] == 4

    second = await store.put(_artifact(case_id=CASE_B, first_seen_at=NOW + timedelta(minutes=10)))
    rows = await store.list(tenant_id=None)
    assert [artifact.id for artifact in rows] == [updated.id, second.id]

    case_rows = await store.list(tenant_id=None, case_id=updated.case_id)
    assert [artifact.id for artifact in case_rows] == [updated.id]

    with pytest.raises(SchemaValidationError):
        await store.get("not-an-artifact-id")
    with pytest.raises(SchemaValidationError):
        await store.list(tenant_id="not-a-uuid")
    with pytest.raises(CrossTenantReference):
        await store.put(_artifact(artifact_id=updated.id, tenant_id=TENANT_A))


async def test_dfe_tenant_isolation(artifact_harness: ArtifactHarness) -> None:
    store = artifact_harness.store
    local = await store.put(_artifact(case_id=CASE_A))
    tenant_a_1 = await store.put(_artifact(tenant_id=TENANT_A, case_id=CASE_A))
    tenant_a_2 = await store.put(
        _artifact(
            tenant_id=TENANT_A,
            case_id=CASE_B,
            first_seen_at=NOW + timedelta(minutes=1),
        )
    )
    tenant_b = await store.put(_artifact(tenant_id=TENANT_B, case_id=CASE_A))

    rows_a = await store.list(tenant_id=TENANT_A)
    assert [artifact.id for artifact in rows_a] == [tenant_a_1.id, tenant_a_2.id]
    assert tenant_b.id not in [artifact.id for artifact in rows_a]
    assert local.id not in [artifact.id for artifact in rows_a]

    rows_a_case = await store.list(tenant_id=TENANT_A, case_id=CASE_A)
    assert [artifact.id for artifact in rows_a_case] == [tenant_a_1.id]

    rows_b = await store.list(tenant_id=TENANT_B)
    assert [artifact.id for artifact in rows_b] == [tenant_b.id]

    rows_local = await store.list(tenant_id=None)
    assert [artifact.id for artifact in rows_local] == [local.id]


def _artifact(
    *,
    artifact_id: str | None = None,
    tenant_id: str | None = None,
    case_id: str | None = CASE_A,
    artifact_type: str = "browser",
    metadata: dict[str, object] | None = None,
    first_seen_at: datetime = NOW,
) -> Artifact:
    return Artifact(
        id=new_id("art") if artifact_id is None else artifact_id,
        tenant_id=tenant_id,
        artifact_type=artifact_type,
        acquisition_id=new_id("acq"),
        object_id=new_id("obj"),
        evidence_id=new_id("evd"),
        metadata=dict(metadata or {}),
        linked_asset_ids=[new_id("obj")],
        first_seen_at=first_seen_at,
        case_id=case_id,
    )
