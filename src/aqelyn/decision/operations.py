"""Pure operation registry for AI Decision Intelligence derivations (EA-0020 E1)."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol

from aqelyn.conventions.errors import DecisionConfigInvalid, UnknownOperation

JsonMap = dict[str, Any]
JsonMapping = Mapping[str, Any]


class PureOp(Protocol):
    def __call__(
        self,
        inputs: Sequence[JsonMapping],
        params: JsonMapping,
    ) -> JsonMap: ...


DEFAULT_OPERATION_NAMES: Final[tuple[str, ...]] = (
    "select_claims",
    "filter",
    "weigh",
    "mission_weight",
    "rank",
    "threshold",
    "similarity",
)


class OperationRegistry:
    def __init__(self) -> None:
        self._ops: dict[str, PureOp] = {}

    def register(self, name: str, fn: PureOp) -> None:
        _validate_operation_name(name)
        if name in self._ops:
            raise DecisionConfigInvalid(f"operation already registered: {name!r}")
        self._ops[name] = fn

    def get(self, name: str) -> PureOp:
        _validate_operation_name(name)
        try:
            return self._ops[name]
        except KeyError as exc:
            raise UnknownOperation(f"unknown operation: {name!r}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._ops))


def default_operation_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register("select_claims", select_claims)
    registry.register("filter", filter_items)
    registry.register("weigh", weigh)
    registry.register("mission_weight", mission_weight)
    registry.register("rank", rank)
    registry.register("threshold", threshold)
    registry.register("similarity", similarity)
    return registry


def select_claims(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    kinds = _optional_string_set(params.get("kinds"))
    claims = [_deepcopy_json(item) for item in inputs]
    if kinds is not None:
        claims = [claim for claim in claims if claim.get("kind") in kinds]
    return {"claims": claims, "count": len(claims)}


def filter_items(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    field = params.get("field")
    if field is None:
        return {"items": [_deepcopy_json(item) for item in inputs], "count": len(inputs)}
    if not isinstance(field, str) or not field.strip():
        raise DecisionConfigInvalid("filter field must be a non-empty string")
    equals = params.get("equals")
    items = [_deepcopy_json(item) for item in inputs if _lookup(item, field) == equals]
    return {"items": items, "count": len(items)}


def weigh(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    field = params.get("weight_field", "confidence")
    if not isinstance(field, str) or not field.strip():
        raise DecisionConfigInvalid("weight_field must be a non-empty string")
    default_weight = _unit(params.get("default", 0.0), field="default")
    items: list[JsonMap] = []
    for item in inputs:
        copied = _deepcopy_json(item)
        selected = _lookup(copied, field)
        copied["weight"] = _unit(selected, field=field) if selected is not None else default_weight
        items.append(copied)
    return {"items": items}


def mission_weight(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    factor = _unit(params.get("factor", 1.0), field="factor")
    source_field = _field_param(params, "source_field", default="weight")
    target_field = _field_param(params, "target_field", default="score")
    items: list[JsonMap] = []
    for item in inputs:
        copied = _deepcopy_json(item)
        base = _unit(_lookup(copied, source_field) or 0.0, field=source_field)
        copied[target_field] = _clamp_unit(base * factor)
        items.append(copied)
    return {"items": items, "factor": factor}


def rank(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    score_field = _field_param(params, "score_field", default="score")
    limit = _positive_int(params.get("limit", len(inputs) or 1), field="limit")
    items = [_deepcopy_json(item) for item in inputs]
    items.sort(
        key=lambda item: (
            -_numeric(_lookup(item, score_field), field=score_field),
            str(item.get("id", "")),
        )
    )
    return {"items": items[:limit], "count": min(limit, len(items))}


def threshold(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    score_field = _field_param(params, "score_field", default="score")
    min_score = _unit(params.get("min_score", 0.0), field="min_score")
    items = [
        _deepcopy_json(item)
        for item in inputs
        if _unit(_lookup(item, score_field) or 0.0, field=score_field) >= min_score
    ]
    return {"items": items, "count": len(items), "min_score": min_score}


def similarity(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    left = _feature_set(params.get("left"))
    right = _feature_set(params.get("right"))
    if left is None or right is None:
        if len(inputs) < 2:
            raise DecisionConfigInvalid("similarity requires two feature sets")
        left = _feature_set(inputs[0].get("features"))
        right = _feature_set(inputs[1].get("features"))
    assert left is not None
    assert right is not None
    shared = sorted(left & right)
    union = sorted(left | right)
    score = 1.0 if not union else len(shared) / len(union)
    return {
        "score": score,
        "shared": {"features": shared},
        "reason": f"shares {len(shared)} of {len(union)} features",
    }


def _validate_operation_name(value: str) -> str:
    if not value.strip():
        raise DecisionConfigInvalid("operation name must not be empty")
    return value


def _deepcopy_json(value: JsonMapping) -> JsonMap:
    return copy.deepcopy(dict(value))


def _field_param(params: JsonMapping, name: str, *, default: str) -> str:
    value = params.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise DecisionConfigInvalid(f"{name} must be a non-empty string")
    return value


def _optional_string_set(value: object) -> set[str] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise DecisionConfigInvalid("kinds must be a list of strings")
    out: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise DecisionConfigInvalid("kinds must contain non-empty strings")
        out.add(item)
    return out


def _feature_set(value: object) -> set[str] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise DecisionConfigInvalid("features must be a list of strings")
    out: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise DecisionConfigInvalid("features must contain non-empty strings")
        out.add(item)
    return out


def _lookup(data: JsonMapping, path: str) -> object:
    current: object = data
    for part in path.split("."):
        if not part or part.startswith("__"):
            return None
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _unit(value: object, *, field: str) -> float:
    selected = _numeric(value, field=field)
    if selected < 0.0 or selected > 1.0:
        raise DecisionConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _numeric(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DecisionConfigInvalid(f"{field} must be numeric")
    selected = float(value)
    if not math.isfinite(selected):
        raise DecisionConfigInvalid(f"{field} must be finite")
    return selected


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DecisionConfigInvalid(f"{field} must be >= 1")
    return value


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))
