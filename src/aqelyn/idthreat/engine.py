"""Gate-first identity threat detection (EA-0027 I3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef, require_tenant_id
from aqelyn.conventions.errors import CrossTenantReference
from aqelyn.decision import DerivationStep, build_derivation
from aqelyn.evidence import EvidenceRecord
from aqelyn.idthreat.dignity import dignity_gate
from aqelyn.idthreat.models import (
    IdentityBasis,
    IdentityDetection,
    IdentityObservation,
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


class IdentityThreatEngine:
    def __init__(
        self,
        store: IdentityDetectionStore,
        *,
        evidence_store: IdentityEvidenceLookup,
        trust_engine: IdentityTrustAssessor,
        config: IdThreatConfig,
    ) -> None:
        self.store = store
        self.evidence_store = evidence_store
        self.trust_engine = trust_engine
        self.config = config

    async def detect(
        self,
        *,
        observation: IdentityObservation,
        tenant_id: str | None,
    ) -> IdentityDetection | None:
        selected = IdentityObservation.model_validate(observation.model_dump(mode="json"))
        selected_tenant = require_tenant_id(tenant_id)
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
        basis = _basis_for(selected, signals)
        statement = _STATEMENTS[selected.detection_type]
        result = detection_result(
            subject_ref=selected.subject_ref,
            detection_type=selected.detection_type,
            statement=statement,
            corroboration=signals,
            confidence=assessment.score,
            basis=basis,
            profile_ref=selected.profile_ref,
            entitlement_refs=[],
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
            detected_at=selected.detected_at,
        )
        return await self.store.put(validate_replayable_detection(detection))

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
) -> list[IdentityBasis]:
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
                as_of=observation.detected_at,
            ),
            IdentityBasis(
                kind="event",
                ref=f"rule:{observation.rule_ref}:v{observation.rule_version}",
                as_of=observation.detected_at,
            ),
        )
    )
    return basis
