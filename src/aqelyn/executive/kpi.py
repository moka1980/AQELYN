"""KPI computation and provenance drill-down (EA-0022 X2)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aqelyn.conventions.errors import ExecutiveConfigInvalid, FigureProvenanceMissing
from aqelyn.decision import ClaimRef, Derivation, DerivationStep, build_derivation
from aqelyn.decision.operations import JsonMap, JsonMapping, OperationRegistry
from aqelyn.executive.definitions import KPIDefinitionStore
from aqelyn.executive.models import (
    VALID_INPUT_METRICS,
    Figure,
    KPIDefinition,
    KPIInput,
    KPIRecord,
    SourceRef,
)

_ENGINE_VERSION = "executive-x2/v1"
_KPI_RESULT_OP = "kpi_result"


class OwnerMetric(BaseModel):
    """A value read from the owning engine, not recomputed here."""

    model_config = ConfigDict(extra="forbid")

    source_engine: str
    ref_id: str
    value: float | str
    unit: str
    as_of: datetime
    confidence: float | None = None
    evidence_id: str | None = None
    owner_record: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_engine")
    @classmethod
    def _source_engine(cls, value: str) -> str:
        if value not in VALID_INPUT_METRICS:
            raise ExecutiveConfigInvalid(f"unknown source engine: {value!r}")
        return value

    @field_validator("ref_id", "unit")
    @classmethod
    def _text(cls, value: str) -> str:
        if not value.strip():
            raise ExecutiveConfigInvalid("owner metric field must not be empty")
        return value

    @field_validator("value")
    @classmethod
    def _value(cls, value: float | str) -> float | str:
        if isinstance(value, str):
            if not value.strip():
                raise ExecutiveConfigInvalid("owner metric value must not be empty")
            return value
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ExecutiveConfigInvalid("owner metric value must be finite")
        return float(value)

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise ExecutiveConfigInvalid("owner metric confidence must be in [0,1]")
        return value


class DrillDownRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: SourceRef
    owner_record: dict[str, Any]
    evidence_id: str | None = None


class KPIValueSource(Protocol):
    async def read(
        self,
        source_input: KPIInput,
        *,
        tenant_id: str | None,
        period: str,
    ) -> OwnerMetric | None: ...

    async def resolve(
        self, source_ref: SourceRef, *, tenant_id: str | None
    ) -> OwnerMetric | None: ...


class ExecutiveKPIEngine:
    def __init__(
        self,
        definition_store: KPIDefinitionStore,
        sources: Mapping[str, KPIValueSource],
    ) -> None:
        self.definition_store = definition_store
        self.sources = dict(sources)

    async def compute_kpi(self, *, key: str, period: str, tenant_id: str | None) -> KPIRecord:
        if not key.strip():
            raise ExecutiveConfigInvalid("key must not be empty")
        if not period.strip():
            raise ExecutiveConfigInvalid("period must not be empty")
        definition = await self.definition_store.active(key)
        owner_values = await self._read_inputs(definition, tenant_id=tenant_id, period=period)
        value = _apply_combinator(
            definition.combinator,
            [item.value for item in owner_values],
            [source_input.weight for source_input in definition.inputs],
        )
        source_refs = [_source_ref(item) for item in owner_values]
        figure = Figure(
            value=value,
            unit=definition.unit,
            source_refs=source_refs,
            confidence=_combined_confidence(owner_values),
            as_of=max(item.as_of for item in owner_values),
        )
        return KPIRecord(
            tenant_id=tenant_id,
            kpi_key=definition.key,
            definition_version=definition.version,
            figure=figure,
            reporting_period=period,
            band=_band_for(value, definition),
            derivation=_derivation_for(definition, owner_values, result=value),
        )

    async def drill_down(self, figure: Figure, *, tenant_id: str | None) -> list[DrillDownRecord]:
        return await drill_down(figure, sources=self.sources, tenant_id=tenant_id)

    async def _read_inputs(
        self, definition: KPIDefinition, *, tenant_id: str | None, period: str
    ) -> list[OwnerMetric]:
        rows: list[OwnerMetric] = []
        for source_input in definition.inputs:
            source = self.sources.get(source_input.source_engine)
            if source is None:
                raise ExecutiveConfigInvalid(
                    f"source is unavailable: {source_input.source_engine!r}"
                )
            value = await source.read(source_input, tenant_id=tenant_id, period=period)
            if value is None:
                raise ExecutiveConfigInvalid(
                    f"kpi input is unavailable: {source_input.source_engine}.{source_input.metric}"
                )
            if value.source_engine != source_input.source_engine:
                raise FigureProvenanceMissing("owner metric source does not match KPI input")
            rows.append(OwnerMetric.model_validate(value.model_dump(mode="json")))
        if not rows:
            raise FigureProvenanceMissing("kpi requires at least one source")
        return rows


async def compute_kpi(
    *,
    definition_store: KPIDefinitionStore,
    sources: Mapping[str, KPIValueSource],
    key: str,
    period: str,
    tenant_id: str | None,
) -> KPIRecord:
    engine = ExecutiveKPIEngine(definition_store, sources)
    return await engine.compute_kpi(key=key, period=period, tenant_id=tenant_id)


async def drill_down(
    figure: Figure,
    *,
    sources: Mapping[str, KPIValueSource],
    tenant_id: str | None,
) -> list[DrillDownRecord]:
    if not figure.source_refs:
        raise FigureProvenanceMissing("figure requires source_refs")
    rows: list[DrillDownRecord] = []
    for ref in figure.source_refs:
        source = sources.get(_source_engine_for(ref.kind))
        if source is None:
            raise ExecutiveConfigInvalid(f"source is unavailable: {ref.kind!r}")
        value = await source.resolve(ref, tenant_id=tenant_id)
        if value is None:
            raise FigureProvenanceMissing(f"source reference cannot be resolved: {ref.ref_id}")
        rows.append(
            DrillDownRecord(
                source_ref=ref,
                owner_record=value.owner_record,
                evidence_id=ref.evidence_id,
            )
        )
    return rows


def kpi_operation_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(_KPI_RESULT_OP, kpi_result)
    return registry


def kpi_result(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    _ = inputs
    return {
        "value": _apply_combinator(
            _string_param(params, "combinator"),
            _sequence_param(params, "values"),
            _sequence_param(params, "weights"),
        )
    }


def _source_ref(value: OwnerMetric) -> SourceRef:
    return SourceRef(
        kind=_source_kind_for(value.source_engine),
        ref_id=value.ref_id,
        as_of=value.as_of,
        evidence_id=value.evidence_id,
    )


def _source_kind_for(source_engine: str) -> str:
    if source_engine == "compliance":
        return "compliance"
    if source_engine == "risk":
        return "risk"
    if source_engine == "forecast":
        return "forecast"
    if source_engine == "mission":
        return "mission"
    raise ExecutiveConfigInvalid(f"unknown source engine: {source_engine!r}")


def _source_engine_for(source_kind: str) -> str:
    if source_kind in {"compliance", "risk", "forecast", "mission"}:
        return source_kind
    raise ExecutiveConfigInvalid(f"source kind is not a KPI owner: {source_kind!r}")


def _apply_combinator(
    combinator: str, values: Sequence[object], weights: Sequence[object | None]
) -> float | str:
    if combinator == "identity":
        if len(values) != 1:
            raise ExecutiveConfigInvalid("identity KPI requires exactly one input")
        value = values[0]
        if isinstance(value, str):
            return value
        return _number(value, field="identity value")

    numbers = [_number(value, field="kpi input value") for value in values]
    if not numbers:
        raise ExecutiveConfigInvalid("composed KPI requires at least one input")
    if combinator == "sum":
        return sum(numbers)
    if combinator == "average":
        return sum(numbers) / len(numbers)
    if combinator == "weighted_average":
        selected_weights = [_weight(weight) for weight in weights]
        if len(selected_weights) != len(numbers):
            raise ExecutiveConfigInvalid("weighted_average requires one weight per input")
        total = sum(selected_weights)
        if total <= 0.0:
            raise ExecutiveConfigInvalid("weighted_average requires positive weights")
        return (
            sum(value * weight for value, weight in zip(numbers, selected_weights, strict=True))
            / total
        )
    if combinator == "min":
        return min(numbers)
    if combinator == "max":
        return max(numbers)
    if combinator == "delta":
        if len(numbers) != 2:
            raise ExecutiveConfigInvalid("delta KPI requires exactly two inputs")
        return numbers[0] - numbers[1]
    if combinator == "ratio":
        if len(numbers) != 2:
            raise ExecutiveConfigInvalid("ratio KPI requires exactly two inputs")
        if numbers[1] == 0.0:
            raise ExecutiveConfigInvalid("ratio denominator must not be zero")
        return numbers[0] / numbers[1]
    raise ExecutiveConfigInvalid(f"unknown combinator: {combinator!r}")


def _combined_confidence(values: Sequence[OwnerMetric]) -> float | None:
    confidences = [value.confidence for value in values if value.confidence is not None]
    if not confidences:
        return None
    return min(confidences)


def _band_for(value: float | str, definition: KPIDefinition) -> str:
    if isinstance(value, str):
        return "unknown"
    band = "green"
    for candidate, threshold in definition.thresholds.items():
        if value < threshold:
            band = candidate
    return band


def _derivation_for(
    definition: KPIDefinition, values: Sequence[OwnerMetric], *, result: float | str
) -> Derivation | None:
    if definition.combinator == "identity" and len(values) == 1:
        return None
    source_refs = [_source_ref(value) for value in values]
    inputs = [
        ClaimRef(
            kind=_claim_kind(ref),
            ref_id=f"kpi-input:{index}:{ref.kind}:{ref.ref_id}",
            evidence_id=ref.evidence_id,
        )
        for index, ref in enumerate(source_refs, start=1)
    ]
    output = {"value": result}
    steps = [
        DerivationStep(
            seq=1,
            op=_KPI_RESULT_OP,
            input_refs=[claim.ref_id for claim in inputs],
            params={
                "combinator": definition.combinator,
                "values": [value.value for value in values],
                "weights": [source_input.weight for source_input in definition.inputs],
                "definition_key": definition.key,
                "definition_version": definition.version,
            },
            output=output,
            note="Replay the presentation arithmetic over cited owner KPI inputs.",
        )
    ]
    return build_derivation(
        inputs=inputs,
        steps=steps,
        model_version=definition.version,
        engine_version=_ENGINE_VERSION,
        registry=kpi_operation_registry(),
    )


def _claim_kind(ref: SourceRef) -> str:
    if ref.kind == "mission":
        return "mission"
    if ref.kind == "finding":
        return "finding"
    if ref.kind in {"evidence", "forecast"}:
        return "trust"
    return "risk"


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExecutiveConfigInvalid(f"{field} must be numeric")
    selected = float(value)
    if not math.isfinite(selected):
        raise ExecutiveConfigInvalid(f"{field} must be finite")
    return selected


def _weight(value: object | None) -> float:
    if value is None:
        return 1.0
    selected = _number(value, field="weight")
    if selected < 0.0:
        raise ExecutiveConfigInvalid("weight must be >= 0")
    return selected


def _string_param(params: JsonMapping, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExecutiveConfigInvalid(f"{key} must be a non-empty string")
    return value


def _sequence_param(params: JsonMapping, key: str) -> Sequence[object | None]:
    value = params.get(key)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ExecutiveConfigInvalid(f"{key} must be a sequence")
    return list(value)
