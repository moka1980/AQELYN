"""Digital Forensics linking, packaging, and findings helpers (EA-0016 F4)."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import ArtifactIntegrityError, ArtifactNotFound
from aqelyn.evidence import EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.forensics.models import Artifact
from aqelyn.forensics.store import ArtifactStore, validate_case_id
from aqelyn.forensics.timeline import verify_case
from aqelyn.graph import KnowledgeGraph

ASSET_OBJECT_TYPE = "asset"
FORENSICS_SOURCE_ENGINE = "forensics_engine"


async def link_to_assets(
    artifact_id: str,
    *,
    artifact_store: ArtifactStore,
    graph: KnowledgeGraph,
    relation_types: Sequence[str] | None = None,
    max_depth: int = 2,
    max_nodes: int = 1_000,
) -> list[str]:
    artifact = await _artifact_or_raise(artifact_store, artifact_id)
    subgraph = await graph.subgraph(
        artifact.object_id,
        direction="both",
        relation_types=relation_types,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )
    return sorted(
        node.id
        for node in subgraph.nodes
        if node.id != artifact.object_id and node.object_type == ASSET_OBJECT_TYPE
    )


async def package_case(
    case_id: str,
    *,
    tenant_id: str | None,
    artifact_store: ArtifactStore,
    evidence_store: EvidenceStore,
    by: ActorRef,
    reason: str,
) -> str:
    selected_case_id = _case_id(case_id)
    if not reason.strip():
        raise ArtifactIntegrityError("package reason must not be empty")

    artifacts = await artifact_store.list(tenant_id=tenant_id, case_id=selected_case_id)
    if not artifacts:
        raise ArtifactNotFound(selected_case_id)

    report = await verify_case(
        selected_case_id,
        tenant_id=tenant_id,
        artifact_store=artifact_store,
        evidence_store=evidence_store,
    )
    if not report.ok:
        raise ArtifactIntegrityError(
            f"case {selected_case_id} is not packageable: {report.detail or report.broken_at}"
        )

    evidence_ids = _unique_evidence_ids(artifacts)
    package = await evidence_store.package(evidence_ids, by=by, reason=reason)
    package_report = await evidence_store.verify_package(package.id)
    if not package_report.ok:
        raise ArtifactIntegrityError(
            f"case package {package.id} failed verification: "
            f"{package_report.detail or package_report.broken_at_seq}"
        )
    return package.id


async def findings_from_artifacts(
    artifact_ids: Sequence[str],
    *,
    artifact_store: ArtifactStore,
    finding_store: FindingStore,
    by: ActorRef,
    graph: KnowledgeGraph | None = None,
) -> list[str]:
    artifacts = await _artifacts_for_ids(artifact_store, artifact_ids)
    findings: list[Finding] = []
    for artifact in artifacts:
        linked_asset_ids = (
            await link_to_assets(artifact.id, artifact_store=artifact_store, graph=graph)
            if graph is not None
            else sorted(artifact.linked_asset_ids)
        )
        finding = await finding_store.raise_finding(
            _finding_for_artifact(artifact, linked_asset_ids=linked_asset_ids, by=by)
        )
        findings.append(finding)
    return [finding.id for finding in findings]


async def _artifact_or_raise(store: ArtifactStore, artifact_id: str) -> Artifact:
    artifact = await store.get(artifact_id)
    if artifact is None:
        raise ArtifactNotFound(artifact_id)
    return artifact


async def _artifacts_for_ids(store: ArtifactStore, artifact_ids: Sequence[str]) -> list[Artifact]:
    seen: set[str] = set()
    artifacts: list[Artifact] = []
    for artifact_id in artifact_ids:
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        artifacts.append(await _artifact_or_raise(store, artifact_id))
    artifacts.sort(key=lambda artifact: artifact.id)
    return artifacts


def _case_id(case_id: str) -> str:
    selected = validate_case_id(case_id)
    assert selected is not None
    return selected


def _unique_evidence_ids(artifacts: Sequence[Artifact]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for artifact in sorted(artifacts, key=lambda item: (item.first_seen_at, item.id)):
        if artifact.evidence_id in seen:
            continue
        seen.add(artifact.evidence_id)
        out.append(artifact.evidence_id)
    return out


def _finding_for_artifact(
    artifact: Artifact,
    *,
    linked_asset_ids: Sequence[str],
    by: ActorRef,
) -> Finding:
    now = utc_now()
    affected_object_ids = _affected_object_ids(artifact, linked_asset_ids)
    return Finding(
        id="",
        tenant_id=artifact.tenant_id,
        finding_type="forensics.artifact",
        schema_version=1,
        dedup_key=f"forensics.artifact:{artifact.id}",
        title=f"Forensic artifact requires review: {artifact.artifact_type}",
        severity="medium",
        severity_score=50.0,
        status="open",
        what_happened=(
            f"Forensic artifact {artifact.id} of type {artifact.artifact_type!r} was "
            "cataloged for analysis."
        ),
        why_it_matters=(
            "Forensic artifacts can prove incident scope and sequence only if their "
            "provenance, custody, and affected assets are reviewed."
        ),
        how_determined=(
            "The Digital Forensics Engine used the cataloged artifact metadata, its "
            "EA-0004 evidence record, and Knowledge Graph asset links where available."
        ),
        risk_of_inaction=(
            "If the artifact is not reviewed, incident conclusions may miss affected "
            "assets or rely on incomplete forensic evidence."
        ),
        evidence_ids=[artifact.evidence_id],
        affected_object_ids=affected_object_ids,
        expert_details={
            "artifact": artifact.model_dump(mode="json"),
            "linked_asset_ids": list(linked_asset_ids),
            "raised_by": by.model_dump(mode="json"),
            "boundary": "Forensics records findings only; any response remains delegated.",
        },
        remediation=Remediation(
            summary="Review the forensic artifact and decide whether response is needed.",
            steps=[
                "Verify the cited evidence record and custody chain.",
                "Review the linked assets and forensic timeline context.",
                "If response is needed, hand off through SOC and the gated Workflow Engine.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The artifact is reviewed and any response remains gated.",
            references=["EA-0016 §0", "EA-0004", "EA-0008"],
        ),
        automation=Automation(
            eligibility="none",
            action_ref=None,
            requires_approval=True,
            risk_note="Digital Forensics analyzes and attests; it never acts directly.",
        ),
        confidence=1.0,
        source_engine=FORENSICS_SOURCE_ENGINE,
        correlation_id=artifact.case_id or artifact.id,
        first_detected_at=now,
        last_detected_at=now,
    )


def _affected_object_ids(artifact: Artifact, linked_asset_ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys([artifact.object_id, *sorted(linked_asset_ids)]))
