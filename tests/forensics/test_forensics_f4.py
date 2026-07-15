"""F4 acceptance tests for Digital Forensics linking, packaging, and findings."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import ArtifactIntegrityError, EvidenceNotFound
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore
from aqelyn.findings import Finding, FindingStore, InMemoryFindingStore
from aqelyn.findings.postgres import PostgresFindingStore
from aqelyn.forensics import (
    ASSET_OBJECT_TYPE,
    FORENSIC_ARTIFACT_OBJECT_TYPE,
    Artifact,
    ArtifactStore,
    InMemoryArtifactStore,
    PostgresArtifactStore,
    findings_from_artifacts,
    link_to_assets,
    package_case,
    register_forensic_object_types,
)
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph, PostgresKnowledgeGraph
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    InMemoryObjectStore,
    ObjectQuery,
    ObjectStore,
    SourceRef,
)
from aqelyn.objects.postgres import PostgresObjectStore
from aqelyn.objects.registry import ObjectTypeRegistry

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="forensics-f4-test")
COLLECTOR = ActorRef(actor_type="user", actor_id="forensics-f4-collector")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"
CASE_ID = new_id("inc")
BAD_CASE_ID = new_id("inc")
NOW = datetime(2026, 7, 15, 14, 0, tzinfo=UTC)


@dataclass
class F4Harness:
    kind: str
    objects: ObjectStore
    graph: KnowledgeGraph
    evidence: EvidenceStore
    artifacts: ArtifactStore
    findings: FindingStore


class _MutationSpyStore:
    def __init__(self, inner: InMemoryObjectStore) -> None:
        self.inner = inner
        self.registry = inner.registry
        self.mutations: list[str] = []

    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        return await self.inner.get(object_id, resolve_merged=resolve_merged)

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        return await self.inner.query(q)

    async def relationships(
        self,
        object_id: str,
        *,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[AQRelationship]:
        return await self.inner.relationships(
            object_id,
            direction=direction,
            relation_type=relation_type,
        )

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        return await self.inner.history(object_id)

    async def upsert(self, obj: AQObject) -> AQObject:
        self.mutations.append("upsert")
        return await self.inner.upsert(obj)

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        self.mutations.append("update")
        return await self.inner.update(obj, expected_version=expected_version)

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        self.mutations.append("relate")
        return await self.inner.relate(rel)

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        self.mutations.append("merge")
        return await self.inner.merge(survivor_id, duplicate_id, by=by)

    async def set_state(
        self,
        object_id: str,
        state: str,
        *,
        by: ActorRef,
        expected_version: int,
    ) -> AQObject:
        self.mutations.append("set_state")
        return await self.inner.set_state(
            object_id,
            state,
            by=by,
            expected_version=expected_version,
        )


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def f4_harness(request: pytest.FixtureRequest) -> AsyncIterator[F4Harness]:
    if request.param == "inmemory":
        registry = _registry()
        evidence: EvidenceStore = InMemoryEvidenceStore(mode="enterprise")

        async def memory_evidence_exists(evidence_id: str) -> bool:
            return await _evidence_exists(evidence, evidence_id)

        memory_objects = InMemoryObjectStore(registry=registry, mode="enterprise")
        yield F4Harness(
            kind="inmemory",
            objects=memory_objects,
            graph=InMemoryKnowledgeGraph(memory_objects),
            evidence=evidence,
            artifacts=InMemoryArtifactStore(),
            findings=InMemoryFindingStore(
                mode="enterprise",
                evidence_exists=memory_evidence_exists,
            ),
        )
        return

    if PG_URL is None:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.evidence.postgres import PostgresEvidenceStore

    registry = _registry()
    postgres_objects = await PostgresObjectStore.connect(
        PG_URL,
        registry=registry,
        mode="enterprise",
    )
    evidence = await PostgresEvidenceStore.connect(PG_URL, mode="enterprise")

    async def postgres_evidence_exists(evidence_id: str) -> bool:
        return await _evidence_exists(evidence, evidence_id)

    findings = await PostgresFindingStore.connect(
        PG_URL,
        mode="enterprise",
        evidence_exists=postgres_evidence_exists,
    )
    artifacts = await PostgresArtifactStore.connect(PG_URL)
    async with postgres_objects._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_finding_audit, aq_finding_evidence, aq_finding_asset, aq_finding, "
            "aq_forensics_artifact, aq_evidence_custody, aq_evidence_package, aq_evidence, "
            "aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY CASCADE"
        )
    try:
        yield F4Harness(
            kind="postgres",
            objects=postgres_objects,
            graph=PostgresKnowledgeGraph(postgres_objects._pool),
            evidence=evidence,
            artifacts=artifacts,
            findings=findings,
        )
    finally:
        await artifacts.close()
        await findings.close()
        await evidence.close()
        await postgres_objects.close()


async def test_dfe_link_assets(f4_harness: F4Harness) -> None:
    artifact, asset = await _stored_artifact(f4_harness, tenant_id=TENANT_A)
    tenant_b_artifact, tenant_b_asset = await _stored_artifact(
        f4_harness,
        tenant_id=TENANT_B,
        case_id=new_id("inc"),
        name="tenant-b",
    )

    linked = await link_to_assets(
        artifact.id,
        artifact_store=f4_harness.artifacts,
        graph=f4_harness.graph,
        relation_types=("observed_on",),
    )

    assert linked == [asset.id]
    assert tenant_b_asset.id not in linked
    assert await link_to_assets(
        tenant_b_artifact.id,
        artifact_store=f4_harness.artifacts,
        graph=f4_harness.graph,
        relation_types=("observed_on",),
    ) == [tenant_b_asset.id]


async def test_dfe_package_case(f4_harness: F4Harness) -> None:
    first, _ = await _stored_artifact(f4_harness, name="first")
    second, _ = await _stored_artifact(f4_harness, name="second")

    package_id = await package_case(
        CASE_ID,
        tenant_id=TENANT_A,
        artifact_store=f4_harness.artifacts,
        evidence_store=f4_harness.evidence,
        by=SYS,
        reason="legal export",
    )

    assert package_id.startswith("pkg_")
    assert (await f4_harness.evidence.verify_package(package_id)).ok is True
    for evidence_id in (first.evidence_id, second.evidence_id):
        actions = [entry["action"] for entry in await f4_harness.evidence.custody_of(evidence_id)]
        assert actions == ["intake", "package"]

    tampered, _ = await _stored_artifact(
        f4_harness,
        case_id=BAD_CASE_ID,
        name="tampered",
        first_seen_at=NOW,
    )
    before = await _package_count(f4_harness)
    await _tamper_evidence(f4_harness, tampered.evidence_id)

    with pytest.raises(ArtifactIntegrityError):
        await package_case(
            BAD_CASE_ID,
            tenant_id=TENANT_A,
            artifact_store=f4_harness.artifacts,
            evidence_store=f4_harness.evidence,
            by=SYS,
            reason="must fail closed",
        )

    assert await _package_count(f4_harness) == before


async def test_dfe_findings(f4_harness: F4Harness) -> None:
    artifact, asset = await _stored_artifact(f4_harness, tenant_id=TENANT_A)

    [finding_id] = await findings_from_artifacts(
        [artifact.id],
        artifact_store=f4_harness.artifacts,
        finding_store=f4_harness.findings,
        by=SYS,
        graph=f4_harness.graph,
    )

    finding = await _finding(f4_harness.findings, finding_id)
    assert finding.finding_type == "forensics.artifact"
    assert finding.source_engine == "forensics_engine"
    assert finding.evidence_ids == [artifact.evidence_id]
    assert finding.affected_object_ids == [artifact.object_id, asset.id]
    assert finding.automation.eligibility == "none"
    assert finding.automation.action_ref is None
    assert finding.expert_details is not None
    assert finding.expert_details["linked_asset_ids"] == [asset.id]
    evidence = await f4_harness.evidence.get(finding.evidence_ids[0], actor=SYS)
    assert evidence.evidence_type == "forensics.artifact_cataloged"
    assert (await f4_harness.evidence.verify(evidence.id)).ok is True


async def test_dfe_no_mutation_no_action() -> None:
    registry = _registry()
    inner = InMemoryObjectStore(registry=registry, mode="enterprise")
    evidence: EvidenceStore = InMemoryEvidenceStore(mode="enterprise")

    async def evidence_exists(evidence_id: str) -> bool:
        return await _evidence_exists(evidence, evidence_id)

    harness = F4Harness(
        kind="inmemory",
        objects=inner,
        graph=InMemoryKnowledgeGraph(inner),
        evidence=evidence,
        artifacts=InMemoryArtifactStore(),
        findings=InMemoryFindingStore(mode="enterprise", evidence_exists=evidence_exists),
    )
    artifact, _asset = await _stored_artifact(harness, tenant_id=TENANT_A)
    spy = _MutationSpyStore(inner)
    graph = InMemoryKnowledgeGraph(cast(ObjectStore, spy))

    await link_to_assets(artifact.id, artifact_store=harness.artifacts, graph=graph)
    await findings_from_artifacts(
        [artifact.id],
        artifact_store=harness.artifacts,
        finding_store=harness.findings,
        by=SYS,
        graph=graph,
    )
    await package_case(
        CASE_ID,
        tenant_id=TENANT_A,
        artifact_store=harness.artifacts,
        evidence_store=evidence,
        by=SYS,
        reason="no mutation check",
    )

    assert spy.mutations == []
    source = (
        Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "forensics" / "engine.py"
    ).read_text(encoding="utf-8")
    assert "aqelyn.workflow" not in source
    assert ".propose(" not in source
    assert "execute(" not in source


async def _stored_artifact(
    harness: F4Harness,
    *,
    tenant_id: str | None = TENANT_A,
    case_id: str | None = CASE_ID,
    name: str = "browser",
    first_seen_at: datetime = NOW,
) -> tuple[Artifact, AQObject]:
    evidence = await harness.evidence.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="forensics.artifact_cataloged",
            schema_version=1,
            subject=Subject(),
            collected_at=first_seen_at,
            recorded_at=utc_now(),
            collector=COLLECTOR,
            source_id=new_id("src"),
            method="forensics.f4-test/v1",
            content={"name": name, "case_id": case_id},
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0016", "kind": "artifact_cataloged"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    artifact_object = await _object(
        harness.objects,
        object_type=FORENSIC_ARTIFACT_OBJECT_TYPE,
        tenant_id=tenant_id,
        display_name=f"artifact:{name}",
        evidence_id=evidence.id,
        attributes={"artifact_type": "browser", "case_id": case_id},
    )
    asset = await _object(
        harness.objects,
        object_type=ASSET_OBJECT_TYPE,
        tenant_id=tenant_id,
        display_name=f"asset:{name}",
        evidence_id=evidence.id,
        attributes={"hostname": f"{name}.example.test"},
    )
    await harness.objects.relate(
        AQRelationship(
            id="",
            tenant_id=tenant_id,
            from_id=artifact_object.id,
            to_id=asset.id,
            relation_type="observed_on",
            attributes={},
            sources=[_source(evidence.id, "forensics.link/v1")],
            created_at=first_seen_at,
            updated_at=first_seen_at,
            created_by=SYS,
            updated_by=SYS,
        )
    )
    artifact = await harness.artifacts.put(
        Artifact(
            id="",
            tenant_id=tenant_id,
            artifact_type="browser",
            acquisition_id=new_id("acq"),
            object_id=artifact_object.id,
            evidence_id=evidence.id,
            metadata={"name": name},
            linked_asset_ids=[],
            first_seen_at=first_seen_at,
            case_id=case_id,
        )
    )
    return artifact, asset


async def _object(
    store: ObjectStore,
    *,
    object_type: str,
    tenant_id: str | None,
    display_name: str,
    evidence_id: str,
    attributes: dict[str, object],
) -> AQObject:
    return await store.upsert(
        AQObject(
            id="",
            object_type=object_type,
            schema_version=1,
            tenant_id=tenant_id,
            display_name=display_name,
            attributes=dict(attributes),
            sources=[_source(evidence_id, f"{object_type}.source/v1")],
            first_seen_at=NOW,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            created_by=SYS,
            updated_by=SYS,
        )
    )


def _source(evidence_id: str, method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"), evidence_id=evidence_id, observed_at=NOW, method=method
    )


def _registry() -> ObjectTypeRegistry:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    register_forensic_object_types(registry)
    return registry


async def _evidence_exists(store: EvidenceStore, evidence_id: str) -> bool:
    try:
        await store.get(evidence_id, actor=SYS)
    except EvidenceNotFound:
        return False
    return True


async def _finding(store: FindingStore, finding_id: str) -> Finding:
    finding = await store.get(finding_id)
    assert finding is not None
    return finding


async def _tamper_evidence(harness: F4Harness, evidence_id: str) -> None:
    if harness.kind == "inmemory":
        store = cast(Any, harness.evidence)
        rec = store._by_id[evidence_id]
        assert rec.content is not None
        rec.content["tampered"] = True
        return

    store = cast(Any, harness.evidence)
    async with store._pool.acquire() as conn:
        await conn.execute(
            "UPDATE aq_evidence SET content = jsonb_set(content, '{tampered}', 'true'::jsonb) "
            "WHERE id=$1",
            evidence_id,
        )


async def _package_count(harness: F4Harness) -> int:
    if harness.kind == "inmemory":
        return len(cast(Any, harness.evidence)._packages)
    store = cast(Any, harness.evidence)
    async with store._pool.acquire() as conn:
        value = await conn.fetchval("SELECT count(*) FROM aq_evidence_package")
    return int(value)
