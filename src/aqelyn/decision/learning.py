"""Learning helpers for AI Decision Intelligence (EA-0020 E4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import DecisionConfigInvalid
from aqelyn.decision.models import LearningRecord, ModelVersion, Recommendation


def build_learning_record(
    recommendation: Recommendation,
    *,
    feedback: str,
    by: ActorRef,
    at: datetime,
) -> LearningRecord:
    """Record feedback as a proposal source; it never applies itself."""

    feedback = validate_feedback(feedback)
    return LearningRecord(
        recommendation_id=recommendation.id,
        feedback=feedback,
        proposed_change={
            "kind": "model_parameter_review",
            "recommendation_id": recommendation.id,
            "pinned_model_version": recommendation.derivation.model_version,
            "actor": by.model_dump(mode="json"),
        },
        recorded_at=at,
    )


def proposed_model_params(
    active_model: ModelVersion,
    learning_records: Sequence[LearningRecord],
    *,
    by: ActorRef,
) -> dict[str, Any]:
    """Build transparent inactive proposal params from feedback records."""

    selected = validate_learning_records(learning_records)
    params = dict(active_model.params)
    params["learning_refs"] = [record.id for record in selected]
    params["feedback_count"] = len(selected)
    params["proposed_by"] = by.model_dump(mode="json")
    params["derived_from_model_version"] = active_model.version
    return params


def validate_feedback(value: str) -> str:
    if not value.strip():
        raise DecisionConfigInvalid("feedback must not be empty")
    return value


def validate_learning_records(records: Sequence[LearningRecord]) -> list[LearningRecord]:
    if not records:
        raise DecisionConfigInvalid("from_learning must not be empty")
    seen: set[str] = set()
    selected: list[LearningRecord] = []
    for record in records:
        stored = LearningRecord.model_validate(record.model_dump(mode="json"))
        if stored.applied:
            raise DecisionConfigInvalid("learning records must not be applied")
        if stored.id in seen:
            raise DecisionConfigInvalid("from_learning must not contain duplicates")
        seen.add(stored.id)
        selected.append(stored)
    return selected
