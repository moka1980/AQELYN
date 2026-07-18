"""Gate-first identity threat detection (EA-0027 I3)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    IdentityNotFound,
    IdThreatConfigInvalid,
    ObjectNotFound,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.decision import DerivationStep, build_derivation
from aqelyn.detection import BehaviorProfile
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.findings import (
    AuditEntry,
    Automation,
    Finding,
    FindingStore,
    Remediation,
)
from aqelyn.iag import AccessPath, AccessRiskReport
from aqelyn.idthreat.dignity import dignity_gate
from aqelyn.idthreat.models import (
    IdentityBasis,
    IdentityDetection,
    IdentityObservation,
    IdentityReview,
    IdThreatConfig,
    SignalRef,
)
from aqelyn.idthreat.store import (
    IdentityDetectionStore,
    claims_for_sources,
    detection_result,
    identity_engine_version,
    identity_operation_registry,
    identity_result_operation,
    validate_replayable_detection,
)
from aqelyn.objects import ObjectQuery
from aqelyn.trust import TrustAssessment

_SYSTEM_ACTOR = ActorRef(actor_type="system", actor_id="idthreat-engine")

_STATEMENTS = {
    "impossible_travel": (
        "This credential authenticated from locations with an inconsistent travel interval."
    ),
    "credential_reuse": "This credential was observed in independently reported reuse events.",
    "session_hijack": "This session showed independently corroborated control changes.",
    "first_time_privilege_use": (
        "This account used a privilege not present in its cited behaviour profile."
    ),
    "dormant_account_use": (
        "This account was used after the cited profile recorded a dormant period."
    ),
    "mfa_anomaly": "This account produced independently corroborated MFA anomalies.",
}


class IdentityTrustAssessor(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


class IdentityEvidenceLookup(Protocol):
    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord: ...


class IdentityEvidenceRecorder(Protocol):
    async def add(self, record: EvidenceRecord) -> EvidenceRecord: ...


class IdentityProfileSource(Protocol):
    async def get(
        self,
        profile_id: str,
        *,
        version: int | None = None,
    ) -> BehaviorProfile | None: ...


class IdentityEntitlementAnalyzer(Protocol):
    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]: ...

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport: ...


class IdentityThreatEngine:
    def __init__(
        self,
        store: IdentityDetectionStore,
        *,
        evidence_store: IdentityEvidenceLookup,
        trust_engine: IdentityTrustAssessor,
        profile_store: IdentityProfileSource,
        entitlement_analyzer: IdentityEntitlementAnalyzer,
        config: IdThreatConfig,
        finding_store: FindingStore | None = None,
        evidence_recorder: IdentityEvidenceRecorder | None = None,
        source_id: str | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store
        self.evidence_store = evidence_store
        self.trust_engine = trust_engine
        self.profile_store = profile_store
        self.entitlement_analyzer = entitlement_analyzer
        self.config = config
        self.finding_store = finding_store
        self.evidence_recorder = evidence_recorder
        self.source_id = require_typed_id(
            source_id or new_id("src"),
            "src",
            field="source_id",
        )
        self._clock = clock

    async def detect(
        self,
        *,
        observation: IdentityObservation,
        tenant_id: str | None,
    ) -> IdentityDetection | None:
        selected = IdentityObservation.model_validate(observation.model_dump(mode="json"))
        selected_tenant = require_tenant_id(tenant_id)
        profile = await self._profile_for(selected, tenant_id=selected_tenant)
        if profile is None:
            return None
        context = await self._entitlement_context(selected, tenant_id=selected_tenant)
        if context is None:
            return None
        paths, risk_report = context
        evidence = await self._evidence_for(selected.signals, tenant_id=selected_tenant)
        assessment = await self.trust_engine.assess(
            selected.subject_ref,
            evidence,
            now=selected.detected_at,
        )
        if not dignity_gate(selected.signals, assessment.score, self.config):
            return None

        signals = sorted(
            (signal.model_copy(deep=True) for signal in selected.signals),
            key=lambda signal: (
                signal.as_of,
                signal.ref,
                signal.evidence_id or "",
                signal.kind,
            ),
        )
        basis, entitlement_refs = _basis_for(
            selected,
            signals,
            profile=profile,
            paths=paths,
            risk_report=risk_report,
        )
        statement = _STATEMENTS[selected.detection_type]
        result = detection_result(
            subject_ref=selected.subject_ref,
            detection_type=selected.detection_type,
            statement=statement,
            corroboration=signals,
            confidence=assessment.score,
            basis=basis,
            profile_ref=selected.profile_ref,
            entitlement_refs=entitlement_refs,
            detected_at=selected.detected_at.isoformat(),
        )
        claims = claims_for_sources(signals, basis)
        derivation = build_derivation(
            inputs=claims,
            steps=[
                DerivationStep(
                    seq=1,
                    op=identity_result_operation(),
                    input_refs=[claim.ref_id for claim in claims],
                    params={
                        "source_refs": [claim.ref_id for claim in claims],
                        "result": result,
                        "profile_version": selected.profile_version,
                        "rule_ref": selected.rule_ref,
                        "rule_version": selected.rule_version,
                    },
                    output=result,
                    note=(
                        "Reproduce the account-scoped observation from cited signals and "
                        "the pinned profile and rule versions."
                    ),
                )
            ],
            model_version=selected.rule_version,
            engine_version=identity_engine_version(),
            registry=identity_operation_registry(),
        )
        detection = IdentityDetection(
            tenant_id=selected_tenant,
            subject_ref=selected.subject_ref,
            detection_type=selected.detection_type,
            statement=statement,
            corroboration=signals,
            confidence=assessment.score,
            basis=basis,
            derivation=derivation,
            profile_ref=selected.profile_ref,
            entitlement_refs=entitlement_refs,
            detected_at=selected.detected_at,
        )
        return await self.store.put(validate_replayable_detection(detection))

    async def raise_detection(
        self,
        detection: IdentityDetection,
        *,
        by: ActorRef,
    ) -> Finding:
        selected = validate_replayable_detection(detection)
        if self.finding_store is None:
            raise StoreUnavailable("identity finding store is unavailable")
        evidence_ids = _evidence_ids(selected)
        if not evidence_ids:
            raise StoreUnavailable("identity detection finding requires evidence")
        return await self.finding_store.raise_finding(
            _finding_for_detection(selected, by=by, evidence_ids=evidence_ids)
        )

    async def review(
        self,
        detection_id: str,
        *,
        by: ActorRef,
        outcome: str,
        tenant_id: str | None,
    ) -> IdentityDetection:
        selected_tenant = require_tenant_id(tenant_id)
        detection = await self.store.get(detection_id, tenant_id=selected_tenant)
        if detection is None:
            raise IdentityNotFound(detection_id)
        if await self.store.review_for(detection_id, tenant_id=selected_tenant) is not None:
            raise OptimisticConcurrencyConflict("identity detection is already reviewed")
        if self.evidence_recorder is None:
            raise StoreUnavailable("identity review evidence recorder is unavailable")
        reviewed_at = self._clock()
        evidence = await self.evidence_recorder.add(
            EvidenceRecord(
                id="",
                tenant_id=detection.tenant_id,
                evidence_type="identity.detection_review",
                schema_version=1,
                subject=Subject(object_ids=_affected_object_ids(detection)),
                collected_at=reviewed_at,
                recorded_at=reviewed_at,
                collector=by,
                source_id=self.source_id,
                method="idthreat.review/v1",
                content={
                    "detection_id": detection.id,
                    "subject_ref": detection.subject_ref,
                    "outcome": _review_outcome(outcome),
                    "statement": detection.statement,
                    "source_evidence_ids": _evidence_ids(detection),
                    "derivation": detection.derivation.model_dump(mode="json"),
                },
                content_hash="",
                confidence=1.0,
                labels={"module": "EA-0027", "kind": "identity_review"},
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        await self.store.record_review(
            IdentityReview(
                detection_id=detection.id,
                tenant_id=detection.tenant_id,
                outcome=_review_outcome(outcome),
                reviewed_by=by,
                reviewed_at=reviewed_at,
                evidence_id=evidence.id,
            )
        )
        reviewed = await self.store.get(detection.id, tenant_id=selected_tenant)
        if reviewed is None:
            raise IdentityNotFound(detection.id)
        return reviewed

    async def _profile_for(
        self,
        observation: IdentityObservation,
        *,
        tenant_id: str | None,
    ) -> BehaviorProfile | None:
        try:
            profile = await self.profile_store.get(
                observation.profile_ref,
                version=observation.profile_version,
            )
        except StoreUnavailable:
            return None
        if (
            profile is None
            or profile.subject_ref != observation.subject_ref
            or profile.tenant_id != tenant_id
            or profile.version != observation.profile_version
        ):
            return None
        return profile

    async def _entitlement_context(
        self,
        observation: IdentityObservation,
        *,
        tenant_id: str | None,
    ) -> tuple[list[AccessPath], AccessRiskReport] | None:
        try:
            paths = await self.entitlement_analyzer.access_paths(
                observation.identity_id,
                tenant_id=tenant_id,
            )
            risks = await self.entitlement_analyzer.analyze_risk(
                tenant_id=tenant_id,
                scope=None,
            )
        except (ObjectNotFound, StoreUnavailable):
            return None
        return paths, risks

    async def _evidence_for(
        self,
        signals: Sequence[SignalRef],
        *,
        tenant_id: str | None,
    ) -> list[EvidenceRecord]:
        evidence_ids = sorted(
            {signal.evidence_id for signal in signals if signal.evidence_id is not None}
        )
        records = [
            await self.evidence_store.get(evidence_id, actor=_SYSTEM_ACTOR)
            for evidence_id in evidence_ids
        ]
        if any(record.tenant_id != tenant_id for record in records):
            raise CrossTenantReference("identity evidence tenant does not match detection tenant")
        records.sort(key=lambda record: record.id)
        return records


def _basis_for(
    observation: IdentityObservation,
    signals: Sequence[SignalRef],
    *,
    profile: BehaviorProfile,
    paths: Sequence[AccessPath],
    risk_report: AccessRiskReport,
) -> tuple[list[IdentityBasis], list[str]]:
    basis = [
        IdentityBasis(
            kind="event",
            ref=signal.ref,
            as_of=signal.as_of,
            evidence_id=signal.evidence_id,
        )
        for signal in signals
    ]
    basis.extend(
        (
            IdentityBasis(
                kind="profile",
                ref=f"{observation.profile_ref}:v{observation.profile_version}",
                as_of=profile.computed_at,
            ),
            IdentityBasis(
                kind="event",
                ref=f"rule:{observation.rule_ref}:v{observation.rule_version}",
                as_of=observation.detected_at,
            ),
        )
    )
    entitlement_refs = sorted(
        {entitlement_id for path in paths for entitlement_id in path.entitlement_ids}
    )
    basis.append(
        IdentityBasis(
            kind="entitlement",
            ref=f"iag-identity:{observation.identity_id}",
            as_of=observation.detected_at,
        )
    )
    basis.extend(
        IdentityBasis(
            kind="entitlement",
            ref=entitlement_id,
            as_of=observation.detected_at,
        )
        for entitlement_id in entitlement_refs
    )
    context_ids = {observation.identity_id, *entitlement_refs}
    basis.extend(
        IdentityBasis(
            kind="entitlement",
            ref=f"iag-risk:{risk.kind}:{risk.subject_id}",
            as_of=observation.detected_at,
        )
        for risk in risk_report.risks
        if risk.subject_id in context_ids
    )
    assert profile.id == observation.profile_ref
    return basis, entitlement_refs


def _evidence_ids(detection: IdentityDetection) -> list[str]:
    return sorted(
        {
            evidence_id
            for evidence_id in (
                *[signal.evidence_id for signal in detection.corroboration],
                *[item.evidence_id for item in detection.basis],
            )
            if evidence_id is not None
        }
    )


def _affected_object_ids(detection: IdentityDetection) -> list[str]:
    object_ids = set(detection.entitlement_refs)
    for item in detection.basis:
        prefix = "iag-identity:"
        if item.kind == "entitlement" and item.ref.startswith(prefix):
            object_ids.add(
                require_typed_id(
                    item.ref.removeprefix(prefix),
                    "obj",
                    field="identity basis ref",
                )
            )
    return sorted(object_ids)


def _finding_for_detection(
    detection: IdentityDetection,
    *,
    by: ActorRef,
    evidence_ids: Sequence[str],
) -> Finding:
    return Finding(
        id="",
        tenant_id=detection.tenant_id,
        finding_type=f"identity_threat.{detection.detection_type}",
        schema_version=1,
        dedup_key=f"identity-threat:{detection.id}",
        title=f"Account observation requires review: {detection.detection_type.replace('_', ' ')}",
        severity="medium",
        severity_score=50.0,
        status="open",
        what_happened=detection.statement,
        why_it_matters=(
            "Independent evidence indicates an account or credential event that may require "
            "human investigation; it is not a verdict about the account owner."
        ),
        how_determined=(
            "The Identity Threat Engine replayed the pinned profile and rule derivation, "
            "required independent corroboration, and cited EA-0011 entitlement context."
        ),
        risk_of_inaction=(
            "If the account event is not reviewed, credential misuse may remain uninvestigated."
        ),
        evidence_ids=list(evidence_ids),
        affected_object_ids=_affected_object_ids(detection),
        expert_details={
            "identity_detection": detection.model_dump(mode="json"),
            "account_scoped": True,
            "person_verdict": False,
        },
        remediation=Remediation(
            summary="Review the cited account evidence before considering any consequence.",
            steps=[
                "Show the account owner the observed evidence and replayable derivation.",
                "Record a human review outcome through the identity detection review gate.",
                "Use EA-0008 Workflow for any later response proposal.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The account event receives an evidenced human review.",
            references=["EA-0027 S7/S8", "EA-0008"],
        ),
        automation=Automation(
            eligibility="none",
            action_ref=None,
            requires_approval=True,
            risk_note="Identity detections are questions for human review and never act directly.",
        ),
        confidence=detection.confidence,
        source_engine="idthreat_engine",
        correlation_id=f"identity-threat:{detection.id}",
        first_detected_at=detection.detected_at,
        last_detected_at=detection.detected_at,
        audit=[AuditEntry(at=utc_now(), actor=by, action="raised")],
    )


def _review_outcome(value: str) -> str:
    selected = value.strip()
    if not selected:
        raise IdThreatConfigInvalid("review outcome must not be empty")
    return selected
