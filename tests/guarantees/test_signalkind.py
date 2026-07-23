"""GC3 SignalKind closure and runtime-rejection conformance."""

from __future__ import annotations

from typing import get_args

import pytest

from aqelyn.conventions import new_id
from aqelyn.dspm import ClassificationSignal, ClassificationSignalKind
from aqelyn.risk import SignalKind, SignalRef
from guarantees.controls import PermissiveSignal
from guarantees.discovery import GuaranteeViolation, assert_runtime_rejects_kind

RISK_SIGNAL_KINDS = frozenset(("finding", "compliance", "identity", "config", "threat_intel"))
CLASSIFICATION_SIGNAL_KINDS = frozenset(("field_name", "existing_tag", "detector_match"))


def test_gc_signalkind_frozen() -> None:
    assert frozenset(get_args(SignalKind)) == RISK_SIGNAL_KINDS
    assert frozenset(get_args(ClassificationSignalKind)) == CLASSIFICATION_SIGNAL_KINDS


def test_gc_signalkind_runtime_rejected() -> None:
    risk_payload: dict[str, object] = {
        "kind": "finding",
        "ref_id": "finding:gc-control",
        "weight": 0.5,
    }
    detector_payload: dict[str, object] = {
        "id": "classification-signal:gc-control",
        "kind": "field_name",
        "detector_ref": "detector:gc-control",
        "match_count": 1,
        "evidence_id": new_id("evd"),
    }
    assert SignalRef.model_validate(risk_payload).kind == "finding"
    assert ClassificationSignal.model_validate(detector_payload).kind == "field_name"

    assert_runtime_rejects_kind(
        SignalRef,
        {**risk_payload, "kind": "future_unregistered_kind"},
    )
    assert_runtime_rejects_kind(
        ClassificationSignal,
        {**detector_payload, "kind": "future_unregistered_kind"},
    )


def test_gc_negative_control_unregistered_kind() -> None:
    payload = {"kind": "future_unregistered_kind"}
    accepted = PermissiveSignal.model_validate(payload)

    assert accepted.kind == "future_unregistered_kind"
    with pytest.raises(GuaranteeViolation, match="accepted an unregistered signal kind"):
        assert_runtime_rejects_kind(PermissiveSignal, payload)
