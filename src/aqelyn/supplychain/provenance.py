"""Evidence-backed software provenance verification (EA-0030 Q4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import (
    AQError,
    ChainBroken,
    CrossTenantReference,
    EvidenceNotFound,
    EvidenceTampered,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.supplychain.models import (
    ProvenanceAttestation,
    ProvenanceCheck,
    ProvenanceResult,
    ProvenanceStatus,
    SoftwareComponent,
)


class ProvenanceVerifier(Protocol):
    """Kind-specific authenticity verifier supplied by a trusted adapter."""

    async def verify(
        self,
        attestation: ProvenanceAttestation,
        *,
        component: SoftwareComponent,
    ) -> ProvenanceCheck: ...


@dataclass(frozen=True)
class _Outcome:
    status: ProvenanceStatus
    detail: str


async def verify_attestation(
    attestation: ProvenanceAttestation,
    *,
    component: SoftwareComponent,
    evidence_store: EvidenceStore,
    verifier: ProvenanceVerifier | None,
    actor: ActorRef,
) -> ProvenanceResult:
    """Verify evidence integrity first, then authenticity, and record the result."""

    outcome = await _evaluate(
        attestation,
        component=component,
        evidence_store=evidence_store,
        verifier=verifier,
        actor=actor,
    )
    try:
        recorded = await evidence_store.add(
            _result_evidence(
                attestation,
                component=component,
                outcome=outcome,
                actor=actor,
            )
        )
        integrity = await evidence_store.verify(recorded.id)
    except AQError as exc:
        if not exc.retriable:
            raise
        if outcome.status == "verified":
            return _result(
                attestation,
                status="unverified",
                detail=(
                    f"authenticity passed but EA-0004 result recording was unavailable: {exc.code}"
                ),
            )
        return _result(
            attestation,
            status=outcome.status,
            detail=f"{outcome.detail}; EA-0004 result recording unavailable: {exc.code}",
        )

    if not integrity.ok:
        return _result(
            attestation,
            status="failed",
            detail=(
                "EA-0004 could not verify the persisted provenance result: "
                f"{integrity.detail or 'integrity check failed'}"
            ),
            evidence_id=recorded.id,
        )
    return _result(
        attestation,
        status=outcome.status,
        detail=outcome.detail,
        evidence_id=recorded.id,
    )


async def _evaluate(
    attestation: ProvenanceAttestation,
    *,
    component: SoftwareComponent,
    evidence_store: EvidenceStore,
    verifier: ProvenanceVerifier | None,
    actor: ActorRef,
) -> _Outcome:
    if attestation.evidence_id is not None:
        basis = await _basis_integrity(
            attestation,
            component=component,
            evidence_store=evidence_store,
            actor=actor,
        )
        if basis is not None:
            return basis
    if verifier is None:
        return _Outcome(
            status="unverified",
            detail="no attestation authenticity verifier is configured",
        )
    try:
        checked = await verifier.verify(attestation, component=component)
    except AQError as exc:
        if not exc.retriable:
            raise
        return _Outcome(
            status="unverified",
            detail=f"attestation authenticity verifier unavailable: {exc.code}",
        )
    if checked.valid:
        return _Outcome(status="verified", detail=checked.detail)
    return _Outcome(status="failed", detail=checked.detail)


async def _basis_integrity(
    attestation: ProvenanceAttestation,
    *,
    component: SoftwareComponent,
    evidence_store: EvidenceStore,
    actor: ActorRef,
) -> _Outcome | None:
    evidence_id = attestation.evidence_id
    if evidence_id is None:
        return _Outcome(status="unverified", detail="provenance evidence id is absent")
    try:
        basis = await evidence_store.get(evidence_id, actor=actor)
        if basis.tenant_id != component.tenant_id:
            raise CrossTenantReference("provenance evidence belongs to another tenant")
        integrity = await evidence_store.verify(evidence_id)
    except EvidenceNotFound:
        return _Outcome(status="unverified", detail="cited provenance evidence was not found")
    except (EvidenceTampered, ChainBroken) as exc:
        return _Outcome(status="failed", detail=f"provenance evidence failed integrity: {exc.code}")
    except AQError as exc:
        if not exc.retriable:
            raise
        return _Outcome(
            status="unverified",
            detail=f"EA-0004 provenance evidence verification unavailable: {exc.code}",
        )
    if not integrity.ok:
        return _Outcome(
            status="failed",
            detail=(
                "provenance evidence failed integrity: "
                f"{integrity.detail or 'integrity check failed'}"
            ),
        )
    if component.object_id not in basis.subject.object_ids:
        return _Outcome(
            status="unverified",
            detail="cited evidence is not bound to the software component",
        )
    if basis.content != attestation.raw:
        return _Outcome(
            status="unverified",
            detail="cited evidence content does not match the handed-in attestation",
        )
    return None


def _result_evidence(
    attestation: ProvenanceAttestation,
    *,
    component: SoftwareComponent,
    outcome: _Outcome,
    actor: ActorRef,
) -> EvidenceRecord:
    now = utc_now()
    return EvidenceRecord(
        id="",
        tenant_id=component.tenant_id,
        evidence_type="supplychain.provenance_verification",
        schema_version=1,
        subject=Subject(object_ids=[component.object_id]),
        collected_at=now,
        recorded_at=now,
        collector=actor,
        source_id=component.source_id,
        method=f"supplychain.verify_provenance/{attestation.kind}/v1",
        content={
            "component_purl": component.purl,
            "attestation_kind": attestation.kind,
            "attestation": attestation.raw,
            "basis_evidence_id": attestation.evidence_id,
            "status": outcome.status,
            "detail": outcome.detail,
        },
        content_hash="",
        confidence=1.0 if outcome.status in {"verified", "failed"} else 0.0,
        labels={
            "module": "EA-0030",
            "kind": "provenance_verification",
            "status": outcome.status,
        },
        seq=0,
        prev_hash=None,
        record_hash="",
    )


def _result(
    attestation: ProvenanceAttestation,
    *,
    status: Literal["verified", "unverified", "failed"],
    detail: str,
    evidence_id: str | None = None,
) -> ProvenanceResult:
    return ProvenanceResult(
        component_purl=attestation.component_purl,
        status=status,
        detail=detail,
        evidence_id=evidence_id,
        basis_evidence_id=attestation.evidence_id,
        flagged=status != "verified",
    )
