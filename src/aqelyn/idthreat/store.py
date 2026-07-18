"""Identity-detection persistence contract and replay gates (EA-0027 I3)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from aqelyn.conventions import canonical_json, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    AQError,
    IdentityCorroborationMissing,
    IdentityNotReplayable,
    IdThreatConfigInvalid,
)
from aqelyn.decision import ClaimRef, OperationRegistry, default_operation_registry, replay
from aqelyn.decision.operations import JsonMap, JsonMapping
from aqelyn.idthreat.dignity import dignity_gate
from aqelyn.idthreat.models import (
    VALID_DETECTION_TYPES,
    DetectionType,
    IdentityBasis,
    IdentityDetection,
    IdThreatConfig,
    SignalRef,
    independent_signal_count,
)

_IDENTITY_RESULT_OP = "identity_detection_result"
_ENGINE_VERSION = "identity-threat/v1"


class IdentityDetectionStore(Protocol):
    async def put(self, detection: IdentityDetection) -> IdentityDetection: ...

    async def get(
        self,
        detection_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityDetection | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        subject_ref: str | None = None,
        detection_type: DetectionType | None = None,
        limit: int = 100,
    ) -> list[IdentityDetection]: ...


def validate_detection(
    detection: IdentityDetection,
    *,
    config: IdThreatConfig,
) -> IdentityDetection:
    """Revalidate dignity and replay at the persistence boundary."""

    stored = IdentityDetection.model_validate(detection.model_dump(mode="json"))
    if independent_signal_count(stored.corroboration) < config.min_corroboration:
        raise IdentityCorroborationMissing(
            "identity detection does not meet the independent-signal floor"
        )
    if not dignity_gate(stored.corroboration, stored.confidence, config):
        raise IdThreatConfigInvalid("identity detection confidence does not meet the dignity floor")
    return validate_replayable_detection(stored)


def validate_replayable_detection(detection: IdentityDetection) -> IdentityDetection:
    """Require replay, result match, and source match before serving a detection."""

    stored = IdentityDetection.model_validate(detection.model_dump(mode="json"))
    expected_result = detection_result(
        subject_ref=stored.subject_ref,
        detection_type=stored.detection_type,
        statement=stored.statement,
        corroboration=stored.corroboration,
        confidence=stored.confidence,
        basis=stored.basis,
        profile_ref=stored.profile_ref,
        entitlement_refs=stored.entitlement_refs,
        detected_at=stored.detected_at.isoformat(),
    )
    try:
        result = replay(stored.derivation, registry=identity_operation_registry())
    except AQError as exc:
        raise IdentityNotReplayable("identity detection derivation does not replay") from exc
    if canonical_json(result) != canonical_json(expected_result):
        raise IdentityNotReplayable("identity detection result does not match derivation")

    expected_inputs = [claim.model_dump(mode="json") for claim in detection_claims(stored)]
    actual_inputs = [claim.model_dump(mode="json") for claim in stored.derivation.inputs]
    if canonical_json(actual_inputs) != canonical_json(expected_inputs):
        raise IdentityNotReplayable("identity detection sources do not match derivation")
    _validate_version_pins(stored)
    return stored


def detection_claims(detection: IdentityDetection) -> list[ClaimRef]:
    return claims_for_sources(detection.corroboration, detection.basis)


def claims_for_sources(
    corroboration: Sequence[SignalRef],
    basis: Sequence[IdentityBasis],
) -> list[ClaimRef]:
    claims: list[ClaimRef] = []
    for index, signal in enumerate(corroboration, start=1):
        claims.append(
            ClaimRef(
                kind="detection",
                ref_id=f"identity-signal:{index}:{signal.ref}",
                evidence_id=signal.evidence_id,
            )
        )
    for index, item in enumerate(basis, start=1):
        claims.append(
            ClaimRef(
                kind="detection",
                ref_id=f"identity-basis:{index}:{item.kind}:{item.ref}",
                evidence_id=item.evidence_id,
            )
        )
    return claims


def detection_result(
    *,
    subject_ref: str,
    detection_type: str,
    statement: str,
    corroboration: Sequence[SignalRef],
    confidence: float,
    basis: Sequence[IdentityBasis],
    profile_ref: str | None,
    entitlement_refs: Sequence[str],
    detected_at: str,
) -> dict[str, Any]:
    return {
        "subject_ref": subject_ref,
        "detection_type": detection_type,
        "statement": statement,
        "corroboration": [signal.model_dump(mode="json") for signal in corroboration],
        "confidence": confidence,
        "basis": [item.model_dump(mode="json") for item in basis],
        "profile_ref": profile_ref,
        "entitlement_refs": list(entitlement_refs),
        "detected_at": detected_at,
    }


def identity_operation_registry() -> OperationRegistry:
    registry = default_operation_registry()
    registry.register(_IDENTITY_RESULT_OP, identity_detection_result)
    return registry


def identity_detection_result(
    inputs: Sequence[JsonMapping],
    params: JsonMapping,
) -> JsonMap:
    expected_refs = params.get("source_refs")
    if not isinstance(expected_refs, list) or not all(
        isinstance(item, str) for item in expected_refs
    ):
        raise IdThreatConfigInvalid("identity derivation source_refs must be strings")
    actual_refs = [item.get("ref_id") for item in inputs]
    if actual_refs != expected_refs:
        raise IdThreatConfigInvalid("identity derivation inputs do not match source_refs")
    selected = params.get("result")
    if not isinstance(selected, Mapping) or not selected:
        raise IdThreatConfigInvalid("identity derivation result must be an object")
    return copy.deepcopy(dict(selected))


def validate_detection_id(value: str) -> str:
    return require_typed_id(value, "idt", field="detection_id")


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_subject_filter(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise IdThreatConfigInvalid("subject_ref filter must not be empty")
    return value


def validate_detection_type_filter(value: DetectionType | None) -> DetectionType | None:
    if value is None:
        return None
    if value not in VALID_DETECTION_TYPES:
        raise IdThreatConfigInvalid(f"unknown identity detection type: {value!r}")
    return value


def validate_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IdThreatConfigInvalid("limit must be >= 1")
    return value


def identity_engine_version() -> str:
    return _ENGINE_VERSION


def identity_result_operation() -> str:
    return _IDENTITY_RESULT_OP


def _validate_version_pins(detection: IdentityDetection) -> None:
    step = detection.derivation.steps[-1]
    profile_version = step.params.get("profile_version")
    rule_ref = step.params.get("rule_ref")
    rule_version = step.params.get("rule_version")
    if (
        isinstance(profile_version, bool)
        or not isinstance(profile_version, int)
        or profile_version < 1
        or not isinstance(rule_ref, str)
        or not rule_ref.strip()
        or isinstance(rule_version, bool)
        or not isinstance(rule_version, int)
        or rule_version < 1
    ):
        raise IdentityNotReplayable("identity derivation is missing profile/rule version pins")
    if detection.profile_ref is None:
        raise IdentityNotReplayable("identity detection requires a pinned profile")
    profile_basis = f"{detection.profile_ref}:v{profile_version}"
    rule_basis = f"rule:{rule_ref}:v{rule_version}"
    basis_refs = {item.ref for item in detection.basis}
    if profile_basis not in basis_refs or rule_basis not in basis_refs:
        raise IdentityNotReplayable("identity derivation pins do not match detection basis")
    if detection.derivation.model_version != rule_version:
        raise IdentityNotReplayable("identity derivation model_version does not match rule version")
    if detection.derivation.engine_version != _ENGINE_VERSION:
        raise IdentityNotReplayable("identity derivation engine_version is unsupported")
