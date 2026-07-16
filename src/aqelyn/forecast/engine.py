"""Forecasting engine for trend and advisory forecasts (EA-0021 P3)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import ForecastConfigInvalid, InsufficientHistory
from aqelyn.decision import ClaimRef, Derivation, DerivationStep, build_derivation, replay
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.forecast.methods import MethodRegistry, default_method_registry
from aqelyn.forecast.models import (
    VALID_FORECAST_SUBJECT_PREFIXES,
    AccuracyRecord,
    BasisRef,
    Forecast,
    ForecastConfig,
    ForecastPublication,
    Interval,
    Method,
    Outcome,
    PredictionModel,
    Scenario,
    TrendRecord,
)
from aqelyn.forecast.scenario import simulate_scenario
from aqelyn.forecast.scoring import (
    ActualValueSource,
    EvidenceRecorder,
    accuracy_records,
    publish_forecasts,
    scored_outcome,
    unscoreable_outcome,
)
from aqelyn.forecast.store import (
    ForecastStore,
    PredictionModelStore,
    forecast_operation_registry,
    validate_method,
    validate_replayable_forecast,
    validate_tenant,
)
from aqelyn.forecast.trend import (
    MetricObservation,
    build_trend_record,
    ordered_observations,
    unique_basis,
)
from aqelyn.trust import TrustAssessment, TrustEngine

_ENGINE_VERSION = "forecast-p3/v1"
_SYSTEM_ACTOR = ActorRef(actor_type="system", actor_id="forecast-engine")


class MetricHistorySource(Protocol):
    async def history(
        self,
        *,
        metric: str,
        window_days: int,
        tenant_id: str | None,
    ) -> Sequence[MetricObservation]: ...


class EvidenceLookup(Protocol):
    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord: ...


class TrustAssessor(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


class ForecastingEngine:
    def __init__(
        self,
        forecast_store: ForecastStore,
        model_store: PredictionModelStore,
        *,
        history_source: MetricHistorySource,
        evidence_store: EvidenceLookup,
        actual_source: ActualValueSource | None = None,
        evidence_recorder: EvidenceRecorder | None = None,
        trust_engine: TrustAssessor | None = None,
        method_registry: MethodRegistry | None = None,
        config: ForecastConfig | None = None,
        source_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.forecast_store = forecast_store
        self.model_store = model_store
        self.history_source = history_source
        self.evidence_store = evidence_store
        self.actual_source = actual_source
        self.evidence_recorder = evidence_recorder
        self.trust_engine = trust_engine or TrustEngine()
        self.method_registry = method_registry or default_method_registry()
        self.config = config or ForecastConfig()
        self.source_id = source_id or new_id("src")
        self._clock = clock or utc_now

    async def analyze_trend(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> TrendRecord:
        _validate_metric(metric)
        _validate_window_days(window_days)
        tenant_id = validate_tenant(tenant_id)
        observations = await self._history(
            metric=metric,
            window_days=window_days,
            tenant_id=tenant_id,
        )
        return build_trend_record(
            metric=metric,
            window_days=window_days,
            tenant_id=tenant_id,
            observations=observations,
            min_history_points=self.config.min_history_points,
        )

    async def forecast(
        self,
        *,
        metric: str,
        horizon_days: int,
        method: Method,
        tenant_id: str | None,
        subject_ref: str | None = None,
    ) -> Forecast:
        _validate_metric(metric)
        _validate_horizon(horizon_days, max_horizon_days=self.config.max_horizon_days)
        method = self._validate_method_allowed(method)
        tenant_id = validate_tenant(tenant_id)
        selected_subject = validate_forecast_subject_ref(subject_ref or f"aggregate:{metric}")
        active_model = await self.model_store.active(method, tenant_id=tenant_id)
        window_days = _history_window(active_model, default=self.config.min_history_points)
        observations = await self._history(
            metric=metric,
            window_days=window_days,
            tenant_id=tenant_id,
        )
        ordered = ordered_observations(observations)
        if len(ordered) < self.config.min_history_points:
            raise InsufficientHistory(
                f"{metric} needs at least {self.config.min_history_points} history points; "
                f"got {len(ordered)}"
            )
        values = [row.value for row in ordered]
        method_result = self.method_registry.get(method)(
            values,
            horizon_days=horizon_days,
            level=self.config.default_level,
            params=active_model.params,
        )
        basis = unique_basis(ordered)
        issued_at = self._clock()
        evidence = await self._evidence_for_basis(basis)
        assessment = await self.trust_engine.assess(selected_subject, evidence, now=issued_at)
        derivation = _forecast_derivation(
            method=method,
            model=active_model,
            horizon_days=horizon_days,
            point=method_result.point,
            interval=method_result.interval,
            basis=basis,
        )
        forecast = Forecast(
            tenant_id=tenant_id,
            metric=metric,
            subject_ref=selected_subject,
            method=method,
            model_version=active_model.version,
            horizon_days=horizon_days,
            issued_at=issued_at,
            resolves_at=issued_at + timedelta(days=horizon_days),
            point=method_result.point,
            interval=method_result.interval,
            confidence=assessment.score,
            basis=basis,
            derivation=derivation,
            advisory=True,
            statement=statement_from_derivation(derivation),
        )
        return await self.forecast_store.put(forecast)

    def explain(self, forecast: Forecast) -> dict[str, object]:
        stored = validate_replayable_forecast(forecast)
        return {
            "forecast_id": stored.id,
            "statement": statement_from_derivation(stored.derivation),
            "advisory": stored.advisory,
            "method": stored.method,
            "model_version": stored.model_version,
            "confidence": stored.confidence,
            "basis": [basis.model_dump(mode="json") for basis in stored.basis],
            "inputs": [claim.model_dump(mode="json") for claim in stored.derivation.inputs],
            "steps": [step.model_dump(mode="json") for step in stored.derivation.steps],
            "result": stored.derivation.result,
        }

    async def score_due(self, *, tenant_id: str | None) -> list[Outcome]:
        if self.actual_source is None:
            raise ForecastConfigInvalid("actual_source is required to score forecasts")
        if self.evidence_recorder is None:
            raise ForecastConfigInvalid("evidence_recorder is required to score forecasts")
        tenant_id = validate_tenant(tenant_id)
        now = self._clock()
        due = await self.forecast_store.due_for_scoring(tenant_id=tenant_id, now=now)
        outcomes: list[Outcome] = []
        for forecast in due:
            actual = await self.actual_source.actual(
                metric=forecast.metric,
                at=forecast.resolves_at,
                tenant_id=forecast.tenant_id,
            )
            if actual is None:
                reason = "actual value unavailable for forecast resolution"
                evidence = await self._record_scoring_evidence(
                    forecast,
                    actual=None,
                    scored_at=now,
                    reason=reason,
                )
                outcome = unscoreable_outcome(
                    reason=reason,
                    evidence_id=evidence.id,
                    scored_at=now,
                )
            else:
                evidence = await self._record_scoring_evidence(
                    forecast,
                    actual=actual,
                    scored_at=now,
                    reason=None,
                )
                outcome = scored_outcome(
                    forecast,
                    actual=actual,
                    evidence_id=evidence.id,
                    scored_at=now,
                )
            updated = await self.forecast_store.record_outcome(
                forecast.id,
                outcome,
                tenant_id=forecast.tenant_id,
            )
            assert updated.outcome is not None
            outcomes.append(updated.outcome)
        return outcomes

    async def accuracy(
        self,
        *,
        tenant_id: str | None,
        method: Method | None = None,
        metric: str | None = None,
    ) -> list[AccuracyRecord]:
        tenant_id = validate_tenant(tenant_id)
        selected_method = None if method is None else self._validate_method_allowed(method)
        forecasts = await self.forecast_store.query(
            tenant_id=tenant_id,
            metric=metric,
            limit=self.config.batch_size,
        )
        return accuracy_records(
            forecasts,
            method=selected_method,
            metric=metric,
            now=self._clock(),
        )

    async def published_forecasts(
        self,
        *,
        tenant_id: str | None,
        metric: str | None = None,
        limit: int | None = None,
    ) -> list[ForecastPublication]:
        tenant_id = validate_tenant(tenant_id)
        forecasts = await self.forecast_store.query(
            tenant_id=tenant_id,
            metric=metric,
            limit=limit or self.config.batch_size,
        )
        return publish_forecasts(forecasts, now=self._clock())

    async def simulate(self, *, scenario: Scenario) -> Scenario:
        return simulate_scenario(scenario)

    async def _history(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> list[MetricObservation]:
        raw = await self.history_source.history(
            metric=metric,
            window_days=window_days,
            tenant_id=tenant_id,
        )
        return ordered_observations(raw)

    async def _evidence_for_basis(self, basis: Sequence[BasisRef]) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        seen: set[str] = set()
        for ref in basis:
            if ref.evidence_id is None or ref.evidence_id in seen:
                continue
            seen.add(ref.evidence_id)
            records.append(await self.evidence_store.get(ref.evidence_id, actor=_SYSTEM_ACTOR))
        records.sort(key=lambda record: record.id)
        return records

    async def _record_scoring_evidence(
        self,
        forecast: Forecast,
        *,
        actual: MetricObservation | None,
        scored_at: datetime,
        reason: str | None,
    ) -> EvidenceRecord:
        assert self.evidence_recorder is not None
        content: dict[str, object] = {
            "forecast_id": forecast.id,
            "metric": forecast.metric,
            "method": forecast.method,
            "model_version": forecast.model_version,
            "point": forecast.point,
            "interval": forecast.interval.model_dump(mode="json"),
            "resolves_at": forecast.resolves_at.isoformat(),
        }
        if actual is None:
            content["unscoreable"] = True
            content["reason"] = reason or "actual value unavailable"
        else:
            content["actual"] = actual.value
            content["actual_basis"] = actual.basis.model_dump(mode="json")
            content["error"] = abs(actual.value - forecast.point)
            content["within_interval"] = (
                forecast.interval.low <= actual.value <= forecast.interval.high
            )
        record = EvidenceRecord(
            id="",
            tenant_id=forecast.tenant_id,
            evidence_type="forecast.outcome",
            schema_version=1,
            subject=Subject(),
            collected_at=scored_at,
            recorded_at=scored_at,
            collector=_SYSTEM_ACTOR,
            source_id=self.source_id,
            method="forecast.score/v1",
            content=content,
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0021", "kind": "forecast_outcome"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self.evidence_recorder.add(record)

    def _validate_method_allowed(self, method: str) -> Method:
        selected = validate_method(method)
        if selected not in self.config.methods_allowed:
            raise ForecastConfigInvalid(f"forecast method not allowed: {selected}")
        return selected


def validate_forecast_subject_ref(value: str) -> str:
    selected = value.strip()
    if not selected:
        raise ForecastConfigInvalid("subject_ref must not be empty")
    if not selected.startswith(VALID_FORECAST_SUBJECT_PREFIXES):
        raise ForecastConfigInvalid("forecast subject_ref must be aggregate/system scope")
    return selected


def statement_from_derivation(derivation: Derivation) -> str:
    result = replay(derivation, registry=forecast_operation_registry())
    interval = _interval_from_result(result.get("interval"))
    point = _finite(result.get("point"), field="point")
    step = derivation.steps[-1]
    method = _string_param(step.params, "method", default="forecast_method")
    horizon_days = _int_param(step.params, "horizon_days", default=1)
    return (
        f"Given the cited basis, {method} projects {point:.3f} over {horizon_days} days "
        f"with {interval.level:.0%} interval [{interval.low:.3f}, {interval.high:.3f}]."
    )


def _forecast_derivation(
    *,
    method: Method,
    model: PredictionModel,
    horizon_days: int,
    point: float,
    interval: object,
    basis: Sequence[BasisRef],
) -> Derivation:
    inputs = _claim_refs_for_basis(basis)
    output = {"point": point, "interval": _interval_from_result(interval).model_dump(mode="json")}
    steps = [
        DerivationStep(
            seq=1,
            op="forecast_result",
            input_refs=[claim.ref_id for claim in inputs],
            params={
                **output,
                "method": method,
                "horizon_days": horizon_days,
                "model_version": model.version,
                "basis_count": len(basis),
            },
            output=output,
            note="Replay the explicit forecast point and interval from cited basis.",
        )
    ]
    return build_derivation(
        inputs=inputs,
        steps=steps,
        model_version=model.version,
        engine_version=_ENGINE_VERSION,
        registry=forecast_operation_registry(),
    )


def _claim_refs_for_basis(basis: Sequence[BasisRef]) -> list[ClaimRef]:
    if not basis:
        raise InsufficientHistory("forecast basis must not be empty")
    refs: list[ClaimRef] = []
    for index, ref in enumerate(basis, start=1):
        refs.append(
            ClaimRef(
                kind=_claim_kind(ref),
                ref_id=f"forecast-basis:{index}:{ref.kind}:{ref.ref}",
                evidence_id=ref.evidence_id,
            )
        )
    return refs


def _claim_kind(ref: BasisRef) -> str:
    if ref.kind == "finding":
        return "finding"
    if ref.kind == "telemetry":
        return "trust"
    return "risk"


def _history_window(model: PredictionModel, *, default: int) -> int:
    for key in ("window_days", "window"):
        raw = model.params.get(key)
        if raw is not None:
            return max(default, _positive_int(raw, field=key))
    return default


def _validate_metric(value: str) -> str:
    if not value.strip():
        raise ForecastConfigInvalid("metric must not be empty")
    return value


def _validate_window_days(value: int) -> int:
    return _positive_int(value, field="window_days")


def _validate_horizon(value: int, *, max_horizon_days: int) -> int:
    selected = _positive_int(value, field="horizon_days")
    if selected > max_horizon_days:
        raise ForecastConfigInvalid("horizon_days exceeds max_horizon_days")
    return selected


def _interval_from_result(value: object) -> Interval:
    return Interval.model_validate(value)


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ForecastConfigInvalid(f"{field} must be >= 1")
    return value


def _int_param(params: Mapping[str, object], name: str, *, default: int) -> int:
    raw = params.get(name, default)
    return _positive_int(raw, field=name)


def _string_param(params: Mapping[str, object], name: str, *, default: str) -> str:
    raw = params.get(name, default)
    if not isinstance(raw, str) or not raw.strip():
        raise ForecastConfigInvalid(f"{name} must be a non-empty string")
    return raw


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    return selected
