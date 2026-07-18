"""I1 acceptance tests for identity-threat types and dignity boundaries."""

from __future__ import annotations

import inspect
import socket
from datetime import UTC, datetime
from typing import NoReturn

import pytest
from pydantic import ValidationError

import aqelyn.idthreat as idthreat
from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, is_valid, new_id
from aqelyn.conventions.errors import IdThreatConfigInvalid
from aqelyn.decision.models import ClaimRef, Derivation, DerivationStep
from aqelyn.idthreat import IdentityBasis, IdentityDetection, SignalRef

NOW = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000270001"


def _derivation() -> Derivation:
    return Derivation(
        inputs=[ClaimRef(kind="detection", ref_id="profile:acct:alice")],
        steps=[
            DerivationStep(
                seq=1,
                op="select_claims",
                input_refs=["profile:acct:alice"],
                output={"observation": "impossible_travel"},
                note="Select the pinned account observations.",
            )
        ],
        result={"detection_type": "impossible_travel"},
        model_version=1,
        engine_version="idthreat/v1",
    )


def _detection(**overrides: object) -> IdentityDetection:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "subject_ref": "acct:alice",
        "detection_type": "impossible_travel",
        "statement": ("This credential authenticated from Oslo and Sao Paulo 40 minutes apart."),
        "corroboration": [
            SignalRef(
                kind="authentication",
                ref="auth:oslo",
                as_of=NOW,
                evidence_id=new_id("evd"),
            ),
            SignalRef(
                kind="session",
                ref="session:sao-paulo",
                as_of=NOW,
                evidence_id=new_id("evd"),
            ),
        ],
        "confidence": 0.91,
        "basis": [
            IdentityBasis(
                kind="profile",
                ref="profile:acct:alice:v3",
                as_of=NOW,
                evidence_id=new_id("evd"),
            )
        ],
        "derivation": _derivation(),
        "profile_ref": new_id("prf"),
        "entitlement_refs": [new_id("obj")],
        "detected_at": NOW,
    }
    data.update(overrides)
    return IdentityDetection(**data)


def test_idt_no_person_score_surface() -> None:
    forbidden = {"risk_score", "score_user", "user_score", "predict"}

    public_names = {name for name, _value in inspect.getmembers(idthreat)}
    public_callables = {
        name
        for name, value in inspect.getmembers(idthreat)
        if not name.startswith("_") and callable(value)
    }

    assert not (public_names & forbidden)
    assert not (public_callables & forbidden)

    for model in (SignalRef, IdentityBasis, IdentityDetection):
        assert not (set(model.model_fields) & {"risk_score", "user_score", "person"})
        model_callables = {
            name
            for name, value in inspect.getmembers(model)
            if not name.startswith("_") and callable(value)
        }
        assert not (model_callables & forbidden)


@pytest.mark.parametrize("field", ["risk_score", "user_score", "person"])
def test_idt_no_user_score_field(field: str) -> None:
    data = _detection().model_dump()
    data[field] = 0.9 if field != "person" else "alice"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        IdentityDetection(**data)


def test_idt_account_not_person() -> None:
    detection = _detection()

    assert detection.subject_ref == "acct:alice"
    assert detection.statement.startswith("This credential authenticated")
    assert "person" not in IdentityDetection.model_fields
    assert is_valid(detection.id, "idt")

    with pytest.raises(IdThreatConfigInvalid, match="account, credential, or session"):
        _detection(subject_ref="person:alice")


def test_idt_no_scan_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"scan", "probe", "connect"}
    public_callables = {
        name
        for name, value in inspect.getmembers(idthreat)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & forbidden)

    attempts: list[str] = []

    def blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("socket")
        raise AssertionError("socket use is not permitted in identity-threat I1")

    def blocked_create_connection(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("create_connection")
        raise AssertionError("network use is not permitted in identity-threat I1")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    monkeypatch.setattr(socket, "create_connection", blocked_create_connection)

    detection = _detection()

    assert detection.detection_type == "impossible_travel"
    assert attempts == []


def test_idt_i1_taxonomy_registered() -> None:
    assert PREFIXES["idt"] == "identity_detection"
    assert {
        "IdThreatConfigInvalid",
        "IdentityCorroborationMissing",
        "IdentityBasisMissing",
        "IdentityNotFound",
        "IdentityNotReplayable",
    } <= ALL_ERROR_CODES
