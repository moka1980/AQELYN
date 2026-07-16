"""Sandboxed scenario simulation for Forecasting (EA-0021 P5)."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any

from aqelyn.conventions.errors import ForecastConfigInvalid
from aqelyn.decision import ClaimRef, DerivationStep, build_derivation
from aqelyn.decision.operations import JsonMap, JsonMapping, OperationRegistry
from aqelyn.forecast.models import Scenario
from aqelyn.forecast.store import forecast_operation_registry

_SCENARIO_OP = "scenario_result"
_ENGINE_VERSION = "forecast-p5/v1"


def scenario_operation_registry() -> OperationRegistry:
    registry = forecast_operation_registry()
    registry.register(_SCENARIO_OP, scenario_result)
    return registry


def scenario_result(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    _ = inputs
    base_value = _finite(params.get("base_value"), field="base_value")
    assumptions = _mapping(params.get("assumptions"), field="assumptions")
    absolute_delta = _optional_finite(assumptions.get("absolute_delta"), field="absolute_delta")
    percent_delta = _optional_finite(assumptions.get("percent_delta"), field="percent_delta")
    multiplier = _optional_finite(assumptions.get("multiplier"), field="multiplier")
    projected = base_value
    if multiplier is not None:
        projected *= multiplier
    if percent_delta is not None:
        projected *= 1.0 + percent_delta
    if absolute_delta is not None:
        projected += absolute_delta
    return {
        "base_value": base_value,
        "projected": projected,
        "assumptions": copy.deepcopy(dict(assumptions)),
        "hypothetical": True,
    }


def simulate_scenario(scenario: Scenario) -> Scenario:
    stored = Scenario.model_validate(scenario.model_dump(mode="json"))
    base_value = _base_value(stored)
    result = scenario_result(
        (),
        {
            "base_value": base_value,
            "assumptions": stored.assumptions,
        },
    )
    derivation = build_derivation(
        inputs=[
            ClaimRef(
                kind="trust",
                ref_id=f"scenario:{stored.id}:{stored.base_metric}",
                evidence_id=None,
            )
        ],
        steps=[
            DerivationStep(
                seq=1,
                op=_SCENARIO_OP,
                input_refs=[f"scenario:{stored.id}:{stored.base_metric}"],
                params={
                    "base_value": base_value,
                    "assumptions": copy.deepcopy(stored.assumptions),
                },
                output=result,
                note="Apply hypothetical assumptions over a read-only scenario copy.",
            )
        ],
        model_version=stored.derivation.model_version,
        engine_version=_ENGINE_VERSION,
        registry=scenario_operation_registry(),
    )
    return stored.model_copy(
        update={
            "result": result,
            "hypothetical": True,
            "derivation": derivation,
        },
        deep=True,
    )


def _base_value(scenario: Scenario) -> float:
    explicit = scenario.assumptions.get("base_value")
    if explicit is not None:
        return _finite(explicit, field="base_value")
    existing = scenario.result.get("base_value") or scenario.result.get("projected")
    return _finite(existing, field="base_value")


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ForecastConfigInvalid(f"{field} must be a non-empty mapping")
    return value


def _optional_finite(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    return _finite(value, field=field)


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    return selected
