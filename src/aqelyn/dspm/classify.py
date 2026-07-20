"""Metadata-only DSPM classification and reliability reconciliation (EA-0031 P2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import AQError, ClassificationUnavailable, CrossTenantReference
from aqelyn.dspm.models import (
    Classification,
    ClassificationCandidate,
    ClassificationConflict,
    ClassificationSignal,
    ClassifierRule,
    DataFieldDescriptor,
    DataStoreDescriptor,
    FieldClassification,
)
from aqelyn.evidence import EvidenceRecord, EvidenceStore, VerifyResult
from aqelyn.policy import condition_matches
from aqelyn.trust import TrustAssessment


class TrustAssessor(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


@dataclass(frozen=True)
class ClassificationResult:
    fields: list[FieldClassification]
    conflicts: list[ClassificationConflict]
    descriptor_confidence: float


@dataclass(frozen=True)
class _Candidate:
    value: ClassificationCandidate
    rule_ids: frozenset[str]


async def classify_descriptor(
    descriptor: DataStoreDescriptor,
    *,
    rules: Sequence[ClassifierRule],
    evidence_store: EvidenceStore,
    trust: TrustAssessor,
    actor: ActorRef,
    tenant_id: str | None,
) -> ClassificationResult:
    descriptor_evidence = await _load_evidence(
        descriptor.evidence_id,
        evidence_store=evidence_store,
        actor=actor,
        tenant_id=tenant_id,
        required=True,
    )
    if descriptor_evidence is None:
        raise ClassificationUnavailable("descriptor evidence is required")
    descriptor_assessment = await trust.assess(
        f"data-store:{descriptor.store_id}",
        [descriptor_evidence],
        now=descriptor.observed_at,
    )

    selected_fields: list[FieldClassification] = []
    conflicts: list[ClassificationConflict] = []
    cache: dict[str, tuple[EvidenceRecord, float] | None] = {
        descriptor_evidence.id: (descriptor_evidence, descriptor_assessment.score)
    }
    for field in descriptor.fields:
        classification, conflict = await _classify_field(
            descriptor,
            field,
            rules=rules,
            descriptor_evidence=descriptor_evidence,
            descriptor_score=descriptor_assessment.score,
            evidence_store=evidence_store,
            trust=trust,
            actor=actor,
            tenant_id=tenant_id,
            cache=cache,
        )
        selected_fields.append(classification)
        if conflict is not None:
            conflicts.append(conflict)
    return ClassificationResult(
        fields=selected_fields,
        conflicts=conflicts,
        descriptor_confidence=descriptor_assessment.score,
    )


async def _classify_field(
    descriptor: DataStoreDescriptor,
    field: DataFieldDescriptor,
    *,
    rules: Sequence[ClassifierRule],
    descriptor_evidence: EvidenceRecord,
    descriptor_score: float,
    evidence_store: EvidenceStore,
    trust: TrustAssessor,
    actor: ActorRef,
    tenant_id: str | None,
    cache: dict[str, tuple[EvidenceRecord, float] | None],
) -> tuple[FieldClassification, ClassificationConflict | None]:
    candidates: dict[tuple[str, str, str], _Candidate] = {}
    if field.existing_classification is not None:
        _add_candidate(
            candidates,
            classification=field.existing_classification,
            evidence=descriptor_evidence,
            reliability=descriptor_score,
            rule_id=None,
        )

    base_payload = _metadata_payload(descriptor, field, signal=None)
    for rule in sorted(rules, key=lambda item: item.id):
        if condition_matches(rule.condition, base_payload):
            _add_candidate(
                candidates,
                classification=rule.classification,
                evidence=descriptor_evidence,
                reliability=descriptor_score,
                rule_id=rule.id,
            )
            continue
        for signal in sorted(field.signals, key=lambda item: item.id):
            if not condition_matches(rule.condition, _metadata_payload(descriptor, field, signal)):
                continue
            evidence_and_score = await _optional_evidence_score(
                signal.evidence_id,
                descriptor=descriptor,
                field=field,
                evidence_store=evidence_store,
                trust=trust,
                actor=actor,
                tenant_id=tenant_id,
                cache=cache,
            )
            if evidence_and_score is None:
                continue
            evidence, score = evidence_and_score
            _add_candidate(
                candidates,
                classification=rule.classification,
                evidence=evidence,
                reliability=score,
                rule_id=rule.id,
            )

    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            item.value.classification,
            item.value.source_ref,
            item.value.evidence_id,
        ),
    )
    if not ordered:
        return (
            FieldClassification(
                field=field.name,
                classification="unknown",
                status="unknown",
                flagged=True,
                confidence=0.0,
                evidence_ids=[descriptor_evidence.id],
                reason="No evidence-backed classifier rule produced a winning classification.",
            ),
            None,
        )

    values = {item.value.classification for item in ordered}
    max_reliability = max(item.value.reliability for item in ordered)
    leaders = [item for item in ordered if item.value.reliability == max_reliability]
    leader_values = {item.value.classification for item in leaders}
    evidence_ids = sorted({item.value.evidence_id for item in ordered})
    rule_refs = sorted({rule_id for item in ordered for rule_id in item.rule_ids})

    if len(leader_values) > 1:
        conflict = ClassificationConflict(
            field=field.name,
            candidates=[item.value for item in ordered],
            unresolved=True,
        )
        return (
            FieldClassification(
                field=field.name,
                classification="unknown",
                status="conflict",
                flagged=True,
                rule_refs=rule_refs,
                confidence=max_reliability,
                evidence_ids=evidence_ids,
                reason="Equal-reliability evidence disagrees; no classification was selected.",
            ),
            conflict,
        )

    winner = min(
        leaders,
        key=lambda item: (item.value.source_ref, item.value.evidence_id),
    )
    resolved_conflict: ClassificationConflict | None = None
    if len(values) > 1:
        resolved_conflict = ClassificationConflict(
            field=field.name,
            candidates=[item.value for item in ordered],
            resolved_by=winner.value.source_ref,
            unresolved=False,
        )
    return (
        FieldClassification(
            field=field.name,
            classification=winner.value.classification,
            status="known",
            flagged=False,
            rule_refs=rule_refs,
            confidence=winner.value.reliability,
            evidence_ids=evidence_ids,
            reason=(
                f"Selected {winner.value.classification} from verified evidence using "
                f"the highest Trust score {winner.value.reliability:.3f}."
            ),
        ),
        resolved_conflict,
    )


async def _optional_evidence_score(
    evidence_id: str,
    *,
    descriptor: DataStoreDescriptor,
    field: DataFieldDescriptor,
    evidence_store: EvidenceStore,
    trust: TrustAssessor,
    actor: ActorRef,
    tenant_id: str | None,
    cache: dict[str, tuple[EvidenceRecord, float] | None],
) -> tuple[EvidenceRecord, float] | None:
    if evidence_id not in cache:
        evidence = await _load_evidence(
            evidence_id,
            evidence_store=evidence_store,
            actor=actor,
            tenant_id=tenant_id,
            required=False,
        )
        if evidence is None:
            cache[evidence_id] = None
        else:
            assessment = await trust.assess(
                f"data-field:{descriptor.store_id}:{field.name}",
                [evidence],
                now=descriptor.observed_at,
            )
            cache[evidence_id] = (evidence, assessment.score)
    return cache[evidence_id]


async def _load_evidence(
    evidence_id: str,
    *,
    evidence_store: EvidenceStore,
    actor: ActorRef,
    tenant_id: str | None,
    required: bool,
) -> EvidenceRecord | None:
    try:
        evidence = await evidence_store.get(evidence_id, actor=actor)
        verification: VerifyResult = await evidence_store.verify(evidence_id)
    except AQError as exc:
        if required or exc.retriable:
            raise ClassificationUnavailable(
                f"classification evidence unavailable: {exc.code}"
            ) from exc
        return None
    if evidence.tenant_id != tenant_id:
        raise CrossTenantReference("classification evidence tenant does not match descriptor")
    if not verification.ok:
        if required:
            raise ClassificationUnavailable("descriptor evidence failed integrity verification")
        return None
    return evidence


def _add_candidate(
    candidates: dict[tuple[str, str, str], _Candidate],
    *,
    classification: Classification,
    evidence: EvidenceRecord,
    reliability: float,
    rule_id: str | None,
) -> None:
    key = (classification, evidence.source_id, evidence.id)
    existing = candidates.get(key)
    rule_ids = frozenset() if rule_id is None else frozenset((rule_id,))
    if existing is not None:
        rule_ids = existing.rule_ids | rule_ids
    candidates[key] = _Candidate(
        value=ClassificationCandidate(
            classification=classification,
            source_ref=evidence.source_id,
            reliability=reliability,
            evidence_id=evidence.id,
        ),
        rule_ids=rule_ids,
    )


def _metadata_payload(
    descriptor: DataStoreDescriptor,
    field: DataFieldDescriptor,
    signal: ClassificationSignal | None,
) -> dict[str, object]:
    signal_payload: object = None
    if signal is not None:
        signal_payload = signal.model_dump(exclude={"evidence_id"}, mode="json")
    return {
        "store": {
            "store_id": descriptor.store_id,
            "store_type": descriptor.store_type,
            "provider": descriptor.location.provider,
            "account_ref": descriptor.location.account_ref,
            "region": descriptor.location.region,
            "resource_ref": descriptor.location.resource_ref,
        },
        "field": {
            "name": field.name,
            "data_type": field.data_type,
            "existing_classification": field.existing_classification,
        },
        "signal": signal_payload,
    }
