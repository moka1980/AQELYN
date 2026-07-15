"""Digital Forensics timeline and verification helpers (EA-0016 F3)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from aqelyn.conventions.errors import ArtifactNotFound, ForensicsConfigInvalid
from aqelyn.evidence import EvidenceStore, VerifyResult
from aqelyn.forensics.models import Artifact, ForensicTimeline, TimelineEvent, VerifyReport
from aqelyn.forensics.store import (
    ArtifactStore,
    validate_artifact_id,
    validate_case_id,
    validate_tenant,
)


async def custody_chain(
    artifact_id: str,
    *,
    artifact_store: ArtifactStore,
    evidence_store: EvidenceStore,
) -> list[dict[str, Any]]:
    artifact = await _artifact_or_raise(artifact_store, artifact_id)
    return await evidence_store.custody_of(artifact.evidence_id)


async def build_timeline(
    *,
    artifact_store: ArtifactStore,
    tenant_id: str | None,
    case_id: str | None = None,
    artifact_ids: Sequence[str] = (),
    limit: int = 100,
) -> ForensicTimeline:
    tenant_id = validate_tenant(tenant_id)
    case_id = validate_case_id(case_id)
    _validate_limit(limit)
    artifacts = await _select_artifacts(
        artifact_store,
        tenant_id=tenant_id,
        case_id=case_id,
        artifact_ids=artifact_ids,
    )
    events = [event for artifact in artifacts for event in _artifact_events(artifact)]
    events.sort(key=lambda event: (event.at, event.artifact_id, event.kind, event.evidence_id))
    truncated = len(events) > limit
    return ForensicTimeline(case_id=case_id, events=events[:limit], truncated=truncated)


async def verify_artifact(
    artifact_id: str,
    *,
    artifact_store: ArtifactStore,
    evidence_store: EvidenceStore,
) -> VerifyReport:
    artifact = await _artifact_or_raise(artifact_store, artifact_id)
    result = await evidence_store.verify(artifact.evidence_id)
    return _verify_report(artifact.id, result)


async def verify_case(
    case_id: str,
    *,
    tenant_id: str | None,
    artifact_store: ArtifactStore,
    evidence_store: EvidenceStore,
) -> VerifyReport:
    tenant_id = validate_tenant(tenant_id)
    validated_case_id = validate_case_id(case_id)
    assert validated_case_id is not None
    chain = await evidence_store.verify_chain(tenant_id=tenant_id)
    if not chain.ok:
        return _verify_report(validated_case_id, chain)

    artifacts = await artifact_store.list(tenant_id=tenant_id, case_id=validated_case_id)
    for artifact in artifacts:
        result = await evidence_store.verify(artifact.evidence_id)
        if not result.ok:
            return _verify_report(validated_case_id, result)
    return VerifyReport(subject_id=validated_case_id, ok=True)


def explain(event: TimelineEvent) -> dict[str, Any]:
    return {
        "artifact_id": event.artifact_id,
        "evidence_id": event.evidence_id,
        "at": event.at.isoformat(),
        "kind": event.kind,
        "detail": event.detail,
        "reason": (
            "Timeline event derived from a cataloged forensic artifact and backed by "
            "the cited evidence record."
        ),
    }


async def _artifact_or_raise(store: ArtifactStore, artifact_id: str) -> Artifact:
    validate_artifact_id(artifact_id)
    artifact = await store.get(artifact_id)
    if artifact is None:
        raise ArtifactNotFound(artifact_id)
    return artifact


async def _select_artifacts(
    store: ArtifactStore,
    *,
    tenant_id: str | None,
    case_id: str | None,
    artifact_ids: Sequence[str],
) -> list[Artifact]:
    if artifact_ids:
        seen: set[str] = set()
        out: list[Artifact] = []
        for artifact_id in artifact_ids:
            normalized = validate_artifact_id(artifact_id)
            if normalized in seen:
                continue
            seen.add(normalized)
            artifact = await _artifact_or_raise(store, normalized)
            if artifact.tenant_id != tenant_id:
                continue
            if case_id is None or artifact.case_id == case_id:
                out.append(artifact)
        return out
    return await store.list(tenant_id=tenant_id, case_id=case_id)


def _artifact_events(artifact: Artifact) -> list[TimelineEvent]:
    raw_events = artifact.metadata.get("timeline_events")
    if raw_events is None:
        return [_catalog_event(artifact)]
    if not isinstance(raw_events, list):
        raise ForensicsConfigInvalid("metadata.timeline_events must be a list")
    out = [_timeline_event(artifact, raw) for raw in raw_events]
    return out or [_catalog_event(artifact)]


def _catalog_event(artifact: Artifact) -> TimelineEvent:
    return TimelineEvent(
        at=artifact.first_seen_at,
        artifact_id=artifact.id,
        kind="artifact_cataloged",
        detail={
            "artifact_type": artifact.artifact_type,
            "acquisition_id": artifact.acquisition_id,
            "object_id": artifact.object_id,
            "linked_asset_ids": list(artifact.linked_asset_ids),
            "metadata": {
                key: value for key, value in artifact.metadata.items() if key != "timeline_events"
            },
        },
        evidence_id=artifact.evidence_id,
    )


def _timeline_event(artifact: Artifact, raw: object) -> TimelineEvent:
    if not isinstance(raw, dict):
        raise ForensicsConfigInvalid("timeline_events entries must be objects")
    detail = raw.get("detail", {})
    if not isinstance(detail, dict):
        raise ForensicsConfigInvalid("timeline event detail must be an object")
    merged_detail = {
        "artifact_type": artifact.artifact_type,
        "acquisition_id": artifact.acquisition_id,
        "object_id": artifact.object_id,
        **detail,
    }
    return TimelineEvent.model_validate(
        {
            "at": raw.get("at", artifact.first_seen_at),
            "artifact_id": artifact.id,
            "kind": raw.get("kind", artifact.artifact_type),
            "detail": merged_detail,
            "evidence_id": raw.get("evidence_id", artifact.evidence_id),
        }
    )


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or limit < 1:
        raise ForensicsConfigInvalid("limit must be >= 1")


def _verify_report(subject_id: str, result: VerifyResult) -> VerifyReport:
    return VerifyReport(
        subject_id=subject_id,
        ok=result.ok,
        broken_at=_broken_at(result),
        detail=result.detail,
    )


def _broken_at(result: VerifyResult) -> str | None:
    if result.broken_at_seq is None:
        return None
    return f"seq:{result.broken_at_seq}"
