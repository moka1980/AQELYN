"""Replayable derivation gate for AI Decision Intelligence (EA-0020 E2)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from aqelyn.conventions import canonical_json
from aqelyn.conventions.errors import DecisionConfigInvalid, DerivationNotReplayable
from aqelyn.decision.models import ClaimRef, Derivation, DerivationStep, Recommendation
from aqelyn.decision.operations import (
    JsonMap,
    JsonMapping,
    OperationRegistry,
    default_operation_registry,
)

_STEP_REF_PREFIX = "step:"


def build_derivation(
    *,
    inputs: Sequence[ClaimRef],
    steps: Sequence[DerivationStep],
    model_version: int,
    engine_version: str,
    registry: OperationRegistry | None = None,
    max_steps: int = 32,
) -> Derivation:
    """Build a derivation only if replay can reproduce the recorded outputs."""

    selected_steps = [step.model_copy(deep=True) for step in steps]
    if not selected_steps:
        raise DecisionConfigInvalid("derivation steps must not be empty")
    derivation = Derivation(
        inputs=[claim.model_copy(deep=True) for claim in inputs],
        steps=selected_steps,
        result=copy.deepcopy(selected_steps[-1].output),
        model_version=model_version,
        engine_version=engine_version,
    )
    replay(derivation, registry=registry, max_steps=max_steps)
    return derivation


def replay(
    derivation: Derivation,
    *,
    registry: OperationRegistry | None = None,
    max_steps: int = 32,
) -> JsonMap:
    """Re-execute a derivation and return its final result.

    Every step output is checked, and the final replayed output must equal
    ``derivation.result``. Any divergence withholds the recommendation.
    """

    _validate_max_steps(max_steps)
    if len(derivation.steps) > max_steps:
        raise DerivationNotReplayable("derivation exceeds max_steps")
    selected_registry = registry or default_operation_registry()
    context = _initial_context(derivation.inputs)
    last_output: JsonMap | None = None
    for step in derivation.steps:
        op = selected_registry.get(step.op)
        step_inputs = _resolve_inputs(context, step.input_refs)
        produced = op(step_inputs, step.params)
        if not _json_equal(produced, step.output):
            raise DerivationNotReplayable(f"derivation step {step.seq} output does not replay")
        last_output = copy.deepcopy(produced)
        context[f"{_STEP_REF_PREFIX}{step.seq}"] = copy.deepcopy(produced)
    if last_output is None or not _json_equal(last_output, derivation.result):
        raise DerivationNotReplayable("derivation result does not replay")
    return copy.deepcopy(last_output)


def validate_replayable_recommendation(
    recommendation: Recommendation,
    *,
    registry: OperationRegistry | None = None,
    max_steps: int = 32,
) -> Recommendation:
    """Return a deep-validated recommendation only when its derivation replays."""

    if not isinstance(recommendation.derivation, Derivation):
        raise DerivationNotReplayable("recommendation requires a derivation")
    stored = Recommendation.model_validate(recommendation.model_dump(mode="json"))
    result = replay(stored.derivation, registry=registry, max_steps=max_steps)
    if not _json_equal(result, stored.derivation.result):
        raise DerivationNotReplayable("recommendation derivation result mismatch")
    return stored


def explain(recommendation: Recommendation) -> dict[str, Any]:
    """Render an explanation directly from the replayable derivation."""

    stored = validate_replayable_recommendation(recommendation)
    return {
        "recommendation_id": stored.id,
        "statement": stored.statement,
        "model_version": stored.derivation.model_version,
        "engine_version": stored.derivation.engine_version,
        "inputs": [claim.model_dump(mode="json") for claim in stored.derivation.inputs],
        "steps": [_explain_step(step) for step in stored.derivation.steps],
        "result": copy.deepcopy(stored.derivation.result),
    }


def _initial_context(inputs: Sequence[ClaimRef]) -> dict[str, JsonMap]:
    context: dict[str, JsonMap] = {}
    for claim in inputs:
        payload = claim.model_dump(mode="json")
        context[claim.ref_id] = copy.deepcopy(payload)
    return context


def _resolve_inputs(context: Mapping[str, JsonMapping], refs: Sequence[str]) -> list[JsonMapping]:
    resolved: list[JsonMapping] = []
    for ref in refs:
        if ref not in context:
            raise DerivationNotReplayable(f"derivation input is unavailable: {ref}")
        value = context[ref]
        resolved.extend(_flatten_for_operation(value))
    return resolved


def _flatten_for_operation(value: JsonMapping) -> list[JsonMapping]:
    for key in ("items", "claims"):
        selected = value.get(key)
        if isinstance(selected, list):
            if not all(isinstance(item, Mapping) for item in selected):
                raise DerivationNotReplayable(f"{key} output contains non-object items")
            return [copy.deepcopy(dict(item)) for item in selected]
    return [copy.deepcopy(dict(value))]


def _explain_step(step: DerivationStep) -> dict[str, Any]:
    return {
        "seq": step.seq,
        "operation": step.op,
        "input_refs": list(step.input_refs),
        "params": copy.deepcopy(step.params),
        "note": step.note,
        "output": copy.deepcopy(step.output),
    }


def _json_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    try:
        return canonical_json(left) == canonical_json(right)
    except (TypeError, ValueError) as exc:
        raise DerivationNotReplayable("derivation output is not canonical JSON") from exc


def _validate_max_steps(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DecisionConfigInvalid("max_steps must be >= 1")
    return value
