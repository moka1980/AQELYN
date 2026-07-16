"""E1 acceptance tests for decision types, config, and operation registry."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, ActorRef, new_id
from aqelyn.conventions.errors import DecisionConfigInvalid, UnknownOperation
from aqelyn.decision import (
    DEFAULT_OPERATION_NAMES,
    ClaimRef,
    DecisionConfig,
    DecisionRecord,
    Derivation,
    DerivationStep,
    LearningRecord,
    ModelVersion,
    Recommendation,
    SimilarityHit,
    default_operation_registry,
)

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000000020"
ACTOR = ActorRef(actor_type="user", actor_id="analyst@example.com")


def _claim(kind: str = "finding") -> ClaimRef:
    return ClaimRef(kind=kind, ref_id=f"{kind}:alpha", evidence_id=new_id("evd"))


def _derivation() -> Derivation:
    return Derivation(
        inputs=[_claim()],
        steps=[
            DerivationStep(
                seq=1,
                op="select_claims",
                input_refs=["finding:alpha"],
                params={"kinds": ["finding"]},
                output={"claims": [{"kind": "finding", "ref_id": "finding:alpha"}]},
                note="Select cited findings.",
            )
        ],
        result={"recommendation": "review finding:alpha"},
        model_version=1,
        engine_version="0.1.0",
    )


def test_dec_operation_registry() -> None:
    registry = default_operation_registry()

    assert set(registry.names()) == set(DEFAULT_OPERATION_NAMES)
    for name in DEFAULT_OPERATION_NAMES:
        assert callable(registry.get(name))

    with pytest.raises(UnknownOperation):
        registry.get("opaque_model")
    with pytest.raises(DecisionConfigInvalid):
        registry.register("rank", lambda inputs, params: {"items": list(inputs)})

    original = [
        {"id": "a", "kind": "finding", "confidence": 0.7, "features": ["x", "y"]},
        {"id": "b", "kind": "risk", "confidence": 0.4, "features": ["y", "z"]},
    ]
    before = [dict(item) for item in original]
    selected = registry.get("select_claims")(original, {"kinds": ["finding"]})
    selected_again = registry.get("select_claims")(original, {"kinds": ["finding"]})

    assert selected == selected_again
    assert selected["count"] == 1
    assert original == before

    weighted = registry.get("weigh")(original, {"weight_field": "confidence"})
    ranked = registry.get("rank")(weighted["items"], {"score_field": "weight"})
    assert [item["id"] for item in ranked["items"]] == ["a", "b"]

    similar = registry.get("similarity")([], {"left": ["x", "y"], "right": ["y", "z"]})
    assert similar["score"] == pytest.approx(1 / 3)
    assert similar["shared"] == {"features": ["y"]}
    assert "shares 1 of 3" in similar["reason"]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: DecisionConfig(operations_allowed=["select_claims", "select_claims"]),
        lambda: DecisionConfig(operations_allowed=["select_claims", "neural_magic"]),
        lambda: DecisionConfig(max_steps=0),
        lambda: DecisionConfig(batch_size=0),
        lambda: DecisionConfig(min_confidence=1.1),
        lambda: ClaimRef(kind="prediction", ref_id="x"),
        lambda: Derivation(inputs=[], steps=[], result={}, model_version=1, engine_version="0.1.0"),
        lambda: Derivation(
            inputs=[_claim()],
            steps=[
                DerivationStep(
                    seq=2,
                    op="select_claims",
                    input_refs=["finding:alpha"],
                    output={"claims": []},
                    note="Bad seq.",
                )
            ],
            result={"ok": True},
            model_version=1,
            engine_version="0.1.0",
        ),
        lambda: Recommendation(
            tenant_id=TENANT,
            subject_ref="case:alpha",
            statement="Review this case.",
            confidence=0.8,
            derivation=_derivation(),
            advisory=False,
            created_at=NOW,
        ),
        lambda: LearningRecord(
            recommendation_id=new_id("rec"),
            feedback="Useful.",
            proposed_change={"threshold": 0.6},
            applied=True,
            recorded_at=NOW,
        ),
        lambda: ModelVersion(version=1, params={"threshold": 0.5}, active=True),
        lambda: SimilarityHit(case_id="case-alpha", score=0.4, shared={}, reason="none"),
    ],
)
def test_dec_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(DecisionConfigInvalid):
        factory()


def test_dec_e1_model_shapes_and_taxonomy() -> None:
    derivation = _derivation()
    recommendation = Recommendation(
        tenant_id=TENANT,
        subject_ref="case:alpha",
        statement="Review finding alpha.",
        action_hint={"playbook": "manual-review"},
        confidence=0.8,
        derivation=derivation,
        created_at=NOW,
    )
    decision = DecisionRecord(
        recommendation_id=recommendation.id,
        decision="accepted",
        decided_by=ACTOR,
        reason="Analyst agreed with the cited derivation.",
        at=NOW,
        workflow_run_id=new_id("run"),
        evidence_id=new_id("evd"),
    )
    learning = LearningRecord(
        recommendation_id=recommendation.id,
        feedback="Threshold should be slightly higher.",
        proposed_change={"threshold": 0.7},
        recorded_at=NOW,
    )
    inactive = ModelVersion(version=1, params={"threshold": 0.5})
    active = ModelVersion(
        version=2,
        params={"threshold": 0.7},
        promoted_by=ACTOR,
        promoted_at=NOW,
        active=True,
        evidence_id=new_id("evd"),
    )

    assert recommendation.id.startswith("rec_")
    assert recommendation.advisory is True
    assert decision.id.startswith("dec_")
    assert learning.id.startswith("lrn_")
    assert learning.applied is False
    assert inactive.active is False
    assert active.active is True
    assert DecisionConfig().operations_allowed == list(DEFAULT_OPERATION_NAMES)

    assert PREFIXES["rec"] == "decision_recommendation"
    assert PREFIXES["dec"] == "decision_record"
    assert PREFIXES["lrn"] == "decision_learning_record"
    assert "DecisionConfigInvalid" in ALL_ERROR_CODES
    assert "DerivationNotReplayable" in ALL_ERROR_CODES
    assert "UnknownOperation" in ALL_ERROR_CODES
    assert "RecommendationNotFound" in ALL_ERROR_CODES
    assert "ModelVersionNotFound" in ALL_ERROR_CODES
