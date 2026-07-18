"""Cloud posture normalization engine (EA-0028 Y2)."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import CloudConfigInvalid
from aqelyn.cspm.models import (
    CloudNormalizationConfig,
    CloudResourceDescriptor,
    NormalizedCloudObject,
)
from aqelyn.cspm.normalize import (
    cloud_natural_key,
    ensure_cloud_object_types,
    extract_native_facts,
    normalized_to_object,
    object_type_for,
)
from aqelyn.cspm.store import CloudNormalizationStore
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.objects import AQObject, NaturalKey, ObjectQuery, ObjectStore, SourceRef
from aqelyn.trust import SourceReliabilityRegistry

_ACTOR = ActorRef(actor_type="system", actor_id="cspm_engine")


@dataclass(frozen=True)
class _Candidate:
    value: Any
    source_id: str
    evidence_id: str
    observed_at: datetime
    reliability: float
    path: str


class CloudPostureEngine:
    def __init__(
        self,
        store: CloudNormalizationStore,
        *,
        object_store: ObjectStore,
        evidence_store: EvidenceStore,
        source_registry: SourceReliabilityRegistry,
        config: CloudNormalizationConfig,
        actor: ActorRef | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.evidence_store = evidence_store
        self.source_registry = source_registry
        self.config = config
        self.actor = actor or _ACTOR
        ensure_cloud_object_types(object_store, config)

    async def normalize(
        self,
        descriptors: Sequence[CloudResourceDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[NormalizedCloudObject]:
        selected_tenant = require_tenant_id(tenant_id)
        if len(descriptors) > self.config.batch_size:
            raise CloudConfigInvalid(
                f"descriptor batch exceeds configured limit {self.config.batch_size}"
            )
        normalized: list[NormalizedCloudObject] = []
        for descriptor in descriptors:
            normalized.append(await self._normalize_one(descriptor, tenant_id=selected_tenant))
        return normalized

    def explain(self, obj: NormalizedCloudObject) -> dict[str, object]:
        return {
            "object_id": obj.object_id,
            "object_type": obj.object_type,
            "provider": obj.provider,
            "field_provenance": dict(obj.field_provenance),
            "conflicts": copy.deepcopy(obj.conflicts),
            "evidence_id": obj.evidence_id,
            "flagged": obj.flagged,
            "reason": (
                "Cloud facts were selectively extracted from handed-in provider data; "
                "each fact names its raw JSON Pointer and conflicts retain all candidates."
            ),
        }

    async def _normalize_one(
        self,
        descriptor: CloudResourceDescriptor,
        *,
        tenant_id: str | None,
    ) -> NormalizedCloudObject:
        object_type, selected_key = object_type_for(descriptor, self.config)
        paths = {} if selected_key is None else self.config.fact_paths.get(selected_key, {})
        incoming_facts, incoming_provenance = extract_native_facts(descriptor.raw, paths)
        natural_key = cloud_natural_key(descriptor)
        existing_object = await self._existing_object(natural_key, tenant_id=tenant_id)
        if existing_object is not None and existing_object.object_type != object_type:
            raise CloudConfigInvalid(
                "cloud resource type mapping cannot change for an existing natural key"
            )
        object_id = existing_object.id if existing_object is not None else new_id("obj")
        evidence = await self._record_raw_evidence(
            descriptor,
            object_id=object_id,
            tenant_id=tenant_id,
        )
        existing = await self.store.get(object_id, tenant_id=tenant_id)
        incoming_reliability = (
            await self.source_registry.get(source_id=descriptor.source_id)
        ).weight
        facts, provenance, conflicts = await self._resolve_conflicts(
            existing,
            existing_object=existing_object,
            incoming_facts=incoming_facts,
            incoming_provenance=incoming_provenance,
            descriptor=descriptor,
            evidence_id=evidence.id,
            incoming_reliability=incoming_reliability,
        )
        projected = NormalizedCloudObject(
            object_id=object_id,
            object_type=object_type,
            tenant_id=tenant_id,
            provider=descriptor.provider,
            account=descriptor.account,
            region=descriptor.region,
            native_facts=facts,
            field_provenance=provenance,
            conflicts=conflicts,
            evidence_id=evidence.id,
            flagged=selected_key is None,
        )
        object_confidence = max(
            incoming_reliability,
            0.0 if existing_object is None else existing_object.confidence,
        )
        saved_object = await self.object_store.upsert(
            normalized_to_object(
                projected,
                descriptor=descriptor,
                actor=self.actor,
                confidence=object_confidence,
            )
        )
        if saved_object.id != projected.object_id:
            projected = projected.model_copy(update={"object_id": saved_object.id}, deep=True)
        return await self.store.put(projected)

    async def _existing_object(
        self,
        natural_key: NaturalKey,
        *,
        tenant_id: str | None,
    ) -> AQObject | None:
        rows, _cursor = await self.object_store.query(
            ObjectQuery(
                tenant_id=tenant_id,
                natural_key=natural_key,
                include_states=("active", "archived"),
                limit=10_000,
            )
        )
        if len(rows) > 1:
            raise CloudConfigInvalid("cloud natural key resolved to multiple objects")
        return None if not rows else rows[0]

    async def _record_raw_evidence(
        self,
        descriptor: CloudResourceDescriptor,
        *,
        object_id: str,
        tenant_id: str | None,
    ) -> EvidenceRecord:
        now = utc_now()
        return await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=tenant_id,
                evidence_type="cloud.resource_descriptor",
                schema_version=1,
                subject=Subject(object_ids=[object_id], evidence_id=descriptor.evidence_id),
                collected_at=descriptor.observed_at,
                recorded_at=now,
                collector=self.actor,
                source_id=descriptor.source_id,
                method="cspm.normalize/v1",
                content={
                    "provider": descriptor.provider,
                    "account": descriptor.account,
                    "region": descriptor.region,
                    "resource_type": descriptor.resource_type,
                    "resource_id": descriptor.resource_id,
                    "change_kind": descriptor.change_kind,
                    "upstream_evidence_id": descriptor.evidence_id,
                    "raw": copy.deepcopy(descriptor.raw),
                },
                content_hash="",
                confidence=1.0,
                labels={"module": "EA-0028", "kind": "cloud_resource_descriptor"},
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )

    async def _resolve_conflicts(
        self,
        existing: NormalizedCloudObject | None,
        *,
        existing_object: AQObject | None,
        incoming_facts: dict[str, Any],
        incoming_provenance: dict[str, str],
        descriptor: CloudResourceDescriptor,
        evidence_id: str,
        incoming_reliability: float,
    ) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
        if existing is None:
            return incoming_facts, incoming_provenance, []
        facts = copy.deepcopy(incoming_facts)
        provenance = dict(incoming_provenance)
        conflicts = copy.deepcopy(existing.conflicts)
        for field in sorted(set(existing.native_facts) & set(incoming_facts)):
            if existing.native_facts[field] == incoming_facts[field]:
                continue
            old = await self._existing_candidate(
                existing,
                field=field,
                existing_object=existing_object,
            )
            incoming = _Candidate(
                value=copy.deepcopy(incoming_facts[field]),
                source_id=descriptor.source_id,
                evidence_id=evidence_id,
                observed_at=descriptor.observed_at,
                reliability=incoming_reliability,
                path=incoming_provenance[field],
            )
            winner, reason = _select_candidate(old, incoming)
            facts[field] = copy.deepcopy(winner.value)
            provenance[field] = winner.path
            conflicts.append(_conflict_record(field, old, incoming, winner=winner, reason=reason))
        return facts, provenance, conflicts

    async def _existing_candidate(
        self,
        existing: NormalizedCloudObject,
        *,
        field: str,
        existing_object: AQObject | None,
    ) -> _Candidate:
        conflict_candidate = _candidate_from_conflicts(existing, field)
        if conflict_candidate is not None:
            current_reliability = (
                await self.source_registry.get(source_id=conflict_candidate.source_id)
            ).weight
            return _Candidate(
                value=conflict_candidate.value,
                source_id=conflict_candidate.source_id,
                evidence_id=conflict_candidate.evidence_id,
                observed_at=conflict_candidate.observed_at,
                reliability=current_reliability,
                path=conflict_candidate.path,
            )
        source = _source_for_evidence(existing_object, existing.evidence_id)
        if source is None:
            raise CloudConfigInvalid(
                f"existing normalized field {field!r} has no source for evidence "
                f"{existing.evidence_id}"
            )
        reliability = (await self.source_registry.get(source_id=source.source_id)).weight
        return _Candidate(
            value=copy.deepcopy(existing.native_facts[field]),
            source_id=source.source_id,
            evidence_id=existing.evidence_id,
            observed_at=source.observed_at,
            reliability=reliability,
            path=existing.field_provenance[field],
        )


def _source_for_evidence(obj: AQObject | None, evidence_id: str) -> SourceRef | None:
    if obj is None:
        return None
    for source in reversed(obj.sources):
        if source.evidence_id == evidence_id:
            return source
    return None


def _candidate_from_conflicts(
    existing: NormalizedCloudObject,
    field: str,
) -> _Candidate | None:
    for conflict in reversed(existing.conflicts):
        if conflict.get("field") != field:
            continue
        evidence_id = conflict.get("resolved_evidence_id")
        candidates = conflict.get("candidates")
        if not isinstance(evidence_id, str) or not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict) or candidate.get("evidence_id") != evidence_id:
                continue
            source_id = candidate.get("source_id")
            observed_at = candidate.get("observed_at")
            reliability = candidate.get("reliability")
            path = candidate.get("path")
            if (
                not isinstance(source_id, str)
                or not isinstance(observed_at, str)
                or isinstance(reliability, bool)
                or not isinstance(reliability, int | float)
                or not isinstance(path, str)
            ):
                continue
            return _Candidate(
                value=copy.deepcopy(existing.native_facts[field]),
                source_id=source_id,
                evidence_id=evidence_id,
                observed_at=datetime.fromisoformat(observed_at),
                reliability=float(reliability),
                path=path,
            )
    return None


def _select_candidate(old: _Candidate, incoming: _Candidate) -> tuple[_Candidate, str]:
    if old.reliability != incoming.reliability:
        return (
            (old, "higher source reliability")
            if old.reliability > incoming.reliability
            else (incoming, "higher source reliability")
        )
    if old.observed_at != incoming.observed_at:
        return (
            (old, "newer observation")
            if old.observed_at > incoming.observed_at
            else (incoming, "newer observation")
        )
    winner = max(
        (old, incoming), key=lambda candidate: (candidate.source_id, candidate.evidence_id)
    )
    return winner, "deterministic source/evidence tie-break"


def _conflict_record(
    field: str,
    old: _Candidate,
    incoming: _Candidate,
    *,
    winner: _Candidate,
    reason: str,
) -> dict[str, Any]:
    candidates = sorted((old, incoming), key=lambda item: (item.source_id, item.evidence_id))
    return {
        "field": field,
        "candidates": [_candidate_dict(candidate) for candidate in candidates],
        "resolved_by": winner.source_id,
        "resolved_evidence_id": winner.evidence_id,
        "resolved_value": copy.deepcopy(winner.value),
        "reason": reason,
    }


def _candidate_dict(candidate: _Candidate) -> dict[str, Any]:
    return {
        "source_id": candidate.source_id,
        "evidence_id": candidate.evidence_id,
        "observed_at": candidate.observed_at.isoformat(),
        "reliability": candidate.reliability,
        "path": candidate.path,
        "value": copy.deepcopy(candidate.value),
    }
