"""C-030 G1 acceptance tests for ISPM types and structural gates."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

import aqelyn.ispm as ispm
from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, ActorRef, is_valid, new_id
from aqelyn.conventions.errors import (
    IdentityBaselineNotFound,
    IdentityNotFound,
    ISPMConfigInvalid,
    PostureScoreNotReplayable,
)
from aqelyn.decision.models import ClaimRef, Derivation, DerivationStep
from aqelyn.iag.models import AccessRisk
from aqelyn.ispm import (
    ISPM_EVENTS,
    ControlFact,
    IdentityAccessEdgeDescriptor,
    IdentityAccountDescriptor,
    IdentityBaseline,
    IdentityBaselineEntry,
    IdentityControls,
    IdentityDescriptor,
    IdentityDriftItem,
    IdentityDriftSnapshot,
    IdentityPostureScore,
    ISPMAssessment,
    ISPMConfig,
    NormalizedIdentity,
    PostureFactor,
)

NOW = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000330001"
DUPLICATE_BASELINE_ID = new_id("ibl")


def _known_control(state: str = "present") -> ControlFact:
    return ControlFact(
        state=state,
        established_by="provider:entra:conditional-access",
        evidence_id=new_id("evd"),
        reason="The handed-in provider record established this control state.",
    )


def _account(**overrides: object) -> IdentityAccountDescriptor:
    data: dict[str, object] = {
        "external_id": "account:alex@example.test",
        "display_name": "alex@example.test",
        "attributes": {"last_used_at": NOW.isoformat()},
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return IdentityAccountDescriptor.model_validate(data)


def _edge(**overrides: object) -> IdentityAccessEdgeDescriptor:
    data: dict[str, object] = {
        "from_external_id": "account:alex@example.test",
        "to_object_id": new_id("obj"),
        "relation_type": "grants_entitlement",
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return IdentityAccessEdgeDescriptor.model_validate(data)


def _descriptor(**overrides: object) -> IdentityDescriptor:
    data: dict[str, object] = {
        "source_id": new_id("src"),
        "provider": "entra",
        "external_id": "identity:alex",
        "identity_kind": "human",
        "attributes": {"display_name": "Alex"},
        "controls": {"mfa": "present"},
        "accounts": [_account()],
        "access_edges": [_edge()],
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return IdentityDescriptor.model_validate(data)


def _normalized(**overrides: object) -> NormalizedIdentity:
    data: dict[str, object] = {
        "object_id": new_id("obj"),
        "tenant_id": TENANT,
        "external_id": "identity:alex",
        "provider": "entra",
        "identity_kind": "human",
        "account_object_ids": [new_id("obj")],
        "relationship_ids": [new_id("rel")],
        "controls": IdentityControls(mfa=_known_control()),
        "field_provenance": {"identity_kind": "/identity/type"},
        "conflicts": [],
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return NormalizedIdentity.model_validate(data)


def _factor(**overrides: object) -> PostureFactor:
    data: dict[str, object] = {
        "name": "mfa",
        "value": 1.0,
        "weight": 0.2,
        "status": "known",
        "source_ref": {"control": "mfa", "evidence_id": new_id("evd")},
        "reason": "MFA is present on this account.",
    }
    data.update(overrides)
    return PostureFactor.model_validate(data)


def _risk() -> AccessRisk:
    return AccessRisk(
        kind="dormant",
        subject_id=new_id("obj"),
        detail={"last_used_at": "2025-01-01T00:00:00+00:00"},
        severity="medium",
        reason="Account has not been used within the configured period.",
    )


def _derivation(score: float = 80.0) -> Derivation:
    evidence_id = new_id("evd")
    return Derivation(
        inputs=[ClaimRef(kind="risk", ref_id="iag:dormant:account", evidence_id=evidence_id)],
        steps=[
            DerivationStep(
                seq=1,
                op="weighted_sum",
                input_refs=["iag:dormant:account"],
                params={"weights": [1.0]},
                output={"score": score},
                note="The score composes the pinned IAG risk.",
            )
        ],
        result={"score": score},
        model_version=1,
        engine_version="ispm-score/v1",
    )


def _score(**overrides: object) -> IdentityPostureScore:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "subject_ref": new_id("obj"),
        "score": 80.0,
        "factors": [_factor(value=0.8, weight=1.0)],
        "iag_risks": [_risk()],
        "derivation": _derivation(),
        "confidence": 0.9,
        "statement": "MFA is present on this account; one dormant-risk record is cited.",
        "computed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return IdentityPostureScore.model_validate(data)


def _assessment(**overrides: object) -> ISPMAssessment:
    data: dict[str, object] = {"tenant_id": TENANT, "run_at": NOW}
    data.update(overrides)
    return ISPMAssessment.model_validate(data)


def _baseline() -> IdentityBaseline:
    return IdentityBaseline(
        tenant_id=TENANT,
        name="Human identity controls",
        identity_kind="human",
        entries=[
            IdentityBaselineEntry(
                key="controls.mfa.state",
                expected="present",
                comparator="eq",
                severity="high",
            )
        ],
        approved_by=ActorRef(actor_type="user", actor_id="security-owner"),
        approved_at=NOW,
    )


def test_ispm_controls_tristate() -> None:
    controls = IdentityControls()
    assert controls.mfa.state == "unknown"
    assert controls.lifecycle.state == "unknown"
    assert controls.last_activity.state == "unknown"
    assert _known_control("absent").state == "absent"

    with pytest.raises(ISPMConfigInvalid, match="requires source and evidence"):
        ControlFact(state="present", reason="Evidence is missing.")
    with pytest.raises(ISPMConfigInvalid, match="supplied together"):
        ControlFact(
            state="absent",
            established_by="provider:entra",
            reason="An orphaned source cannot establish the control.",
        )
    with pytest.raises(ISPMConfigInvalid, match="must not be empty"):
        ControlFact(reason=" ")


def test_ispm_descriptor_graph_contract() -> None:
    descriptor = _descriptor()
    assert descriptor.accounts[0].external_id == "account:alex@example.test"
    assert descriptor.access_edges[0].relation_type == "grants_entitlement"
    normalized = _normalized()
    assert len(normalized.account_object_ids) == 1
    assert len(normalized.relationship_ids) == 1

    with pytest.raises(ISPMConfigInvalid, match="from_external_id"):
        _descriptor(access_edges=[_edge(from_external_id="account:not-supplied")])
    with pytest.raises(ISPMConfigInvalid, match="has_account"):
        _normalized(relationship_ids=[])
    object_id = new_id("obj")
    with pytest.raises(ISPMConfigInvalid, match="cannot also be an account"):
        _normalized(object_id=object_id, account_object_ids=[object_id])


def test_ispm_unknown_factor_cannot_look_favourable() -> None:
    unknown = _factor(value=None, status="unknown")
    assert unknown.value is None

    with pytest.raises(ISPMConfigInvalid, match="unknown posture factor"):
        _factor(value=1.0, status="unknown")
    with pytest.raises(ISPMConfigInvalid, match="known posture factor"):
        _factor(value=None, status="known")


def test_ispm_no_person_rollup_type() -> None:
    score = _score()
    assert is_valid(score.id, "ips")
    assert score.subject_ref.startswith("obj_")
    assert score.iag_risks[0].kind == "dormant"

    forbidden = {"person", "person_id", "person_ref", "user_score", "trust_rating"}
    model_types = [
        value
        for _, value in inspect.getmembers(ispm)
        if inspect.isclass(value) and issubclass(value, BaseModel)
    ]
    assert all(not (set(model_type.model_fields) & forbidden) for model_type in model_types)
    with pytest.raises(ValidationError, match="person_id"):
        IdentityPostureScore.model_validate({**score.model_dump(), "person_id": new_id("obj")})
    assert not hasattr(ispm, "ExposureImpactContext")


def test_ispm_assessment_status() -> None:
    pending = _assessment()
    computed = _assessment(
        status="computed",
        identities_evaluated=2,
        scored=2,
        score_ids=[new_id("ips"), new_id("ips")],
        unknown_controls=1,
        inventory_complete=True,
        inventory_note="Inventory pagination reached exhaustion.",
        evidence_id=new_id("evd"),
    )
    truncated = _assessment(
        status="truncated",
        identities_evaluated=1,
        scored=1,
        score_ids=[new_id("ips")],
        inventory_note="The ISPM page budget was exhausted.",
        evidence_id=new_id("evd"),
    )
    assert {pending.status, computed.status, truncated.status} == {
        "pending",
        "computed",
        "truncated",
    }
    assert pending.inventory_complete is False

    with pytest.raises(ISPMConfigInvalid, match="pending assessment"):
        _assessment(identities_evaluated=1, scored=1)
    with pytest.raises(ISPMConfigInvalid, match="requires evidence_id"):
        _assessment(status="computed")
    with pytest.raises(ISPMConfigInvalid, match="scored cannot exceed"):
        _assessment(
            status="computed",
            identities_evaluated=1,
            scored=2,
            evidence_id=new_id("evd"),
        )
    with pytest.raises(ISPMConfigInvalid, match="three per identity"):
        _assessment(
            status="computed",
            identities_evaluated=1,
            unknown_controls=4,
            evidence_id=new_id("evd"),
        )
    with pytest.raises(ISPMConfigInvalid, match="number of score_ids"):
        _assessment(
            status="computed",
            identities_evaluated=1,
            scored=1,
            evidence_id=new_id("evd"),
        )


def test_ispm_baseline_and_drift_consistency() -> None:
    baseline = _baseline()
    item = IdentityDriftItem(
        identity_id=new_id("obj"),
        key="controls.mfa.state",
        expected="present",
        observed=None,
        status="unknown",
        reason="MFA evidence was unavailable.",
    )
    snapshot = IdentityDriftSnapshot(
        tenant_id=TENANT,
        run_at=NOW,
        baseline_id=baseline.id,
        evaluated=1,
        passed=0,
        failed=0,
        unknown=1,
        items=[item],
        evidence_id=new_id("evd"),
    )
    assert is_valid(baseline.id, "ibl")
    assert is_valid(snapshot.id, "idr")

    with pytest.raises(ISPMConfigInvalid, match="status counts"):
        IdentityDriftSnapshot.model_validate({**snapshot.model_dump(), "passed": 1})
    with pytest.raises(ISPMConfigInvalid, match="supplied together"):
        IdentityBaseline(
            name="Unattributed approval",
            identity_kind="human",
            entries=baseline.entries,
            approved_at=NOW,
        )


@pytest.mark.parametrize(
    "config",
    [
        {"factor_weights": {}},
        {"factor_weights": {"mfa": 0.5, "risk": 0.4}},
        {"factor_weights": {"mfa": float("nan"), "risk": 1.0}},
        {"baseline_ids": [new_id("obj")]},
        {"baseline_ids": [DUPLICATE_BASELINE_ID, DUPLICATE_BASELINE_ID]},
        {"stale_activity_days": 0},
        {"batch_size": 0},
        {"page_budget": 0},
    ],
)
def test_ispm_config_invalid(config: dict[str, object]) -> None:
    with pytest.raises(ISPMConfigInvalid):
        ISPMConfig.model_validate(config)


def test_ispm_prefixes_and_events() -> None:
    assert PREFIXES["ips"] == "ispm_posture_score"
    assert PREFIXES["ibl"] == "ispm_identity_baseline"
    assert PREFIXES["idr"] == "ispm_identity_drift"
    assert PREFIXES["ipa"] == "ispm_assessment"
    assert PREFIXES["cert"] == "iag_certification"
    assert is_valid(_assessment().id, "ipa")
    assert {
        "ISPMConfigInvalid",
        "PostureScoreNotReplayable",
        "IdentityBaselineNotFound",
        "IdentityNotFound",
    } <= ALL_ERROR_CODES
    assert ISPMConfigInvalid.code == "ISPMConfigInvalid"
    assert PostureScoreNotReplayable.code == "PostureScoreNotReplayable"
    assert IdentityBaselineNotFound.code == "IdentityBaselineNotFound"
    assert IdentityNotFound.code == "IdentityNotFound"
    assert set(ISPM_EVENTS) == {
        "aqelyn.ispm.identity_normalized",
        "aqelyn.ispm.posture_scored",
        "aqelyn.ispm.posture_drift_detected",
        "aqelyn.ispm.controls_unknown",
    }
    assert all(not event_type.startswith("aqelyn.iag.") for event_type in ISPM_EVENTS)


def test_ispm_gates_survive_optimized_python() -> None:
    script = """
from datetime import datetime, timezone
from aqelyn.conventions.errors import ISPMConfigInvalid
from aqelyn.ispm import ControlFact, ISPMAssessment, PostureFactor

checks = [
    lambda: ControlFact(state='present', reason='missing evidence'),
    lambda: PostureFactor(
        name='mfa', value=1.0, weight=1.0, status='unknown',
        source_ref={'control': 'mfa'}, reason='unknown cannot be favorable'
    ),
    lambda: ISPMAssessment(
        run_at=datetime.now(timezone.utc), identities_evaluated=1, scored=1
    ),
]
for check in checks:
    try:
        check()
    except ISPMConfigInvalid:
        continue
    raise SystemExit('optimized Python bypassed an ISPM structural gate')
"""
    environment = dict(os.environ)
    source = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source, environment.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
