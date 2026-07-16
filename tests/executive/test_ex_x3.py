"""X3 acceptance tests for executive report assembly and issuance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ExceptionsUnavailable, FrozenReportMutation
from aqelyn.decision import ClaimRef, Derivation, DerivationStep
from aqelyn.executive import (
    ExecutiveKPIEngine,
    ExecutiveReportEngine,
    Figure,
    InMemoryKPIDefinitionStore,
    InMemoryReportStore,
    KPIDefinition,
    KPIInput,
    OwnerMetric,
    ReportConfig,
    SourceRef,
    forecast_summary_figure,
)
from aqelyn.forecast import AccuracyRecord, BasisRef, Forecast, Interval

NOW = datetime(2026, 7, 16, 16, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000220101"
ACTOR = ActorRef(actor_type="user", actor_id="executive-issuer@example.com")


class _Source:
    def __init__(self, source_engine: str, values: dict[str, OwnerMetric]) -> None:
        self.source_engine = source_engine
        self.values = values

    async def read(
        self,
        source_input: KPIInput,
        *,
        tenant_id: str | None,
        period: str,
    ) -> OwnerMetric | None:
        _ = tenant_id, period
        return self.values.get(source_input.metric)

    async def resolve(self, source_ref: SourceRef, *, tenant_id: str | None) -> OwnerMetric | None:
        _ = tenant_id
        for value in self.values.values():
            if value.ref_id == source_ref.ref_id:
                return value
        return None


class _Exceptions:
    def __init__(self, figures: list[Figure], *, unavailable: bool = False) -> None:
        self.figures = figures
        self.unavailable = unavailable
        self.calls = 0

    async def material_exceptions(self, *, period: str, tenant_id: str | None) -> list[Figure]:
        _ = period, tenant_id
        self.calls += 1
        if self.unavailable:
            raise RuntimeError("exceptions source down")
        return [figure.model_copy(deep=True) for figure in self.figures]


class _SectionSource:
    def __init__(self, figures: list[Figure]) -> None:
        self.figures = figures

    async def section_figures(
        self, *, section: str, period: str, tenant_id: str | None
    ) -> list[Figure]:
        _ = section, period, tenant_id
        return [figure.model_copy(deep=True) for figure in self.figures]


def _metric(
    *,
    source_engine: str = "risk",
    metric: str = "score",
    value: float = 73.0,
    as_of: datetime = NOW,
    evidence_id: str | None = None,
) -> OwnerMetric:
    selected_evidence_id = evidence_id or new_id("evd")
    return OwnerMetric(
        source_engine=source_engine,
        ref_id=f"{source_engine}:{metric}:record",
        value=value,
        unit="score",
        as_of=as_of,
        confidence=0.88,
        evidence_id=selected_evidence_id,
        owner_record={
            "source_engine": source_engine,
            "metric": metric,
            "value": value,
            "evidence_id": selected_evidence_id,
        },
    )


def _definition(*, key: str = "board_posture") -> KPIDefinition:
    return KPIDefinition(
        key=key,
        title="Board posture",
        inputs=[
            {
                "source_engine": "risk",
                "metric": "score",
                "selector": {"scope": "board"},
                "weight": 1.0,
            }
        ],
        combinator="identity",
        unit="score",
        thresholds={"amber": 60.0, "red": 40.0},
    )


def _figure(
    *,
    kind: str = "risk",
    ref_id: str = "risk:exception",
    value: float | str = 95.0,
    as_of: datetime = NOW,
    evidence_id: str | None = None,
) -> Figure:
    return Figure(
        value=value,
        unit="score",
        source_refs=[
            SourceRef(
                kind=kind,
                ref_id=ref_id,
                as_of=as_of,
                evidence_id=evidence_id or new_id("evd"),
            )
        ],
        confidence=0.9,
        as_of=as_of,
    )


async def _kpi_engine(source: _Source | None = None) -> ExecutiveKPIEngine:
    store = InMemoryKPIDefinitionStore()
    first = await store.propose(_definition(), by=ACTOR)
    await store.promote(first.key, first.version, by=ACTOR, reason="Initial board KPI")
    return ExecutiveKPIEngine(store, {"risk": source or _Source("risk", {"score": _metric()})})


async def _engine(
    *,
    exceptions: _Exceptions | None = None,
    source: _Source | None = None,
    section_sources: dict[str, _SectionSource] | None = None,
    clock_time: datetime = NOW,
) -> ExecutiveReportEngine:
    return ExecutiveReportEngine(
        report_store=InMemoryReportStore(mode="enterprise"),
        exception_source=exceptions or _Exceptions([_figure()]),
        kpi_engine=await _kpi_engine(source),
        kpi_keys=("board_posture",),
        section_sources=section_sources,
        clock=lambda: clock_time,
    )


async def test_exec_exceptions_unsuppressable() -> None:
    engine = await _engine(exceptions=_Exceptions([_figure(ref_id="risk:critical")]))
    config = ReportConfig(sections=["kpis"], period="2026-Q3", audience="board")

    report = await engine.assemble_report(config=config, tenant_id=TENANT)

    assert config.sections == ["kpis"]
    assert [section.key for section in report.sections] == ["kpis", "exceptions"]
    assert report.exceptions[0].source_refs[0].ref_id == "risk:critical"
    assert report.scope["assembled_sections"] == ["kpis", "exceptions"]


async def test_exec_exceptions_unavailable_refuses() -> None:
    exceptions = _Exceptions([_figure()], unavailable=True)
    engine = await _engine(exceptions=exceptions)
    clean_exceptions = _Exceptions([_figure()])
    draft_engine = await _engine(exceptions=clean_exceptions)
    draft = await draft_engine.assemble_report(
        config=ReportConfig(sections=["kpis"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )
    engine.report_store = draft_engine.report_store

    with pytest.raises(ExceptionsUnavailable):
        await engine.issue_report(draft.id, by=ACTOR, tenant_id=TENANT)

    stored = await engine.report_store.get(draft.id, tenant_id=TENANT)
    assert stored is not None
    assert stored.frozen is False


async def test_exec_issue_freezes() -> None:
    engine = await _engine(exceptions=_Exceptions([_figure(ref_id="risk:critical")]))
    draft = await engine.assemble_report(
        config=ReportConfig(sections=["kpis"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )

    issued = await engine.issue_report(draft.id, by=ACTOR, tenant_id=TENANT)

    assert issued.frozen is True
    assert issued.issued_by == ACTOR
    assert issued.issued_at == NOW
    assert issued.approval_status == "published"
    assert issued.content_hash is not None
    assert issued.scope["pinned_definitions"] == {"board_posture": 1}
    assert "risk:score:record" in issued.scope["input_snapshot_ids"]
    assert issued.scope["owner_as_of"]["risk:score:record"] == NOW.isoformat()


async def test_exec_report_immutable() -> None:
    engine = await _engine()
    draft = await engine.assemble_report(
        config=ReportConfig(sections=["kpis"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )
    issued = await engine.issue_report(draft.id, by=ACTOR, tenant_id=TENANT)

    with pytest.raises(FrozenReportMutation):
        await engine.report_store.put(issued.model_copy(update={"title": "Mutated"}, deep=True))


async def test_exec_pinned_definitions() -> None:
    definition_store = InMemoryKPIDefinitionStore()
    first = await definition_store.propose(_definition(), by=ACTOR)
    await definition_store.promote(first.key, first.version, by=ACTOR, reason="Initial")
    kpi_engine = ExecutiveKPIEngine(
        definition_store,
        {"risk": _Source("risk", {"score": _metric(value=73.0)})},
    )
    engine = ExecutiveReportEngine(
        report_store=InMemoryReportStore(mode="enterprise"),
        exception_source=_Exceptions([_figure()]),
        kpi_engine=kpi_engine,
        kpi_keys=("board_posture",),
        clock=lambda: NOW,
    )
    draft = await engine.assemble_report(
        config=ReportConfig(sections=["kpis"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )
    issued = await engine.issue_report(draft.id, by=ACTOR, tenant_id=TENANT)

    second = await definition_store.propose(
        _definition(key="board_posture").model_copy(update={"title": "Board posture v2"}),
        by=ACTOR,
    )
    await definition_store.promote(second.key, second.version, by=ACTOR, reason="Redefinition")
    fetched = await engine.report_store.get(issued.id, tenant_id=TENANT)

    assert fetched is not None
    assert fetched.scope["pinned_definitions"] == {"board_posture": 1}
    assert (await definition_store.active("board_posture")).version == 2


async def test_exec_issue_reproducible() -> None:
    kpi_evidence_id = new_id("evd")
    exception_evidence_id = new_id("evd")
    first_engine = await _engine(
        source=_Source("risk", {"score": _metric(value=73.0, evidence_id=kpi_evidence_id)}),
        exceptions=_Exceptions([_figure(evidence_id=exception_evidence_id)]),
        clock_time=NOW,
    )
    first_draft = await first_engine.assemble_report(
        config=ReportConfig(sections=["kpis"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )
    first = await first_engine.issue_report(first_draft.id, by=ACTOR, tenant_id=TENANT)

    second_engine = await _engine(
        source=_Source("risk", {"score": _metric(value=73.0, evidence_id=kpi_evidence_id)}),
        exceptions=_Exceptions([_figure(evidence_id=exception_evidence_id)]),
        clock_time=NOW + timedelta(hours=1),
    )
    second_draft = await second_engine.assemble_report(
        config=ReportConfig(sections=["kpis"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )
    second = await second_engine.issue_report(second_draft.id, by=ACTOR, tenant_id=TENANT)

    changed_engine = await _engine(
        source=_Source("risk", {"score": _metric(value=74.0, evidence_id=kpi_evidence_id)}),
        exceptions=_Exceptions([_figure(evidence_id=exception_evidence_id)]),
        clock_time=NOW + timedelta(hours=2),
    )
    changed_draft = await changed_engine.assemble_report(
        config=ReportConfig(sections=["kpis"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )
    changed = await changed_engine.issue_report(changed_draft.id, by=ACTOR, tenant_id=TENANT)

    assert first.id != second.id
    assert first.content_hash == second.content_hash
    assert changed.id not in {first.id, second.id}
    assert changed.content_hash != first.content_hash


def test_exec_forecast_interval_kept() -> None:
    evidence_id = new_id("evd")
    interval = Interval(low=28.0, high=52.0, level=0.8)
    forecast = Forecast(
        tenant_id=TENANT,
        metric="phishing_attempts",
        subject_ref="aggregate:phishing_attempts",
        method="moving_average",
        model_version=1,
        horizon_days=14,
        issued_at=NOW,
        resolves_at=NOW + timedelta(days=14),
        point=40.0,
        interval=interval,
        confidence=0.74,
        basis=[
            BasisRef(
                kind="metric",
                ref="metric:phishing_attempts",
                window={"days": 30},
                evidence_id=evidence_id,
            )
        ],
        derivation=_forecast_derivation(point=40.0, interval=interval, evidence_id=evidence_id),
        statement="Projected phishing attempts with interval.",
    )
    accuracy = AccuracyRecord(
        method="moving_average",
        metric="phishing_attempts",
        n=12,
        mae=4.5,
        within_interval_pct=0.83,
        updated_at=NOW,
    )

    figure = forecast_summary_figure(forecast, accuracy)

    assert isinstance(figure.value, str)
    assert "28.0" in figure.value
    assert "52.0" in figure.value
    assert "accuracy 0.830" in figure.value
    assert "accuracy_n=12" in figure.unit
    assert figure.source_refs[0].ref_id == forecast.id
    assert figure.source_refs[0].evidence_id == evidence_id


async def test_exec_scope_declared() -> None:
    forecast_figure = _figure(kind="forecast", ref_id="fct:summary", value="40 [28, 52]")
    engine = await _engine(
        exceptions=_Exceptions([_figure(ref_id="risk:critical")]),
        section_sources={"forecast": _SectionSource([forecast_figure])},
    )

    report = await engine.assemble_report(
        config=ReportConfig(sections=["kpis", "forecast"], period="2026-Q3", audience="board"),
        tenant_id=TENANT,
    )

    assert report.scope["audience"] == "board"
    assert report.scope["requested_sections"] == ["kpis", "forecast"]
    assert report.scope["assembled_sections"] == ["kpis", "forecast", "exceptions"]
    assert "fct:summary" in report.scope["input_snapshot_ids"]
    assert report.excludes == []


def _forecast_derivation(*, point: float, interval: Interval, evidence_id: str) -> Derivation:
    output = {"point": point, "interval": interval.model_dump(mode="json")}
    return Derivation(
        inputs=[ClaimRef(kind="risk", ref_id="metric:phishing_attempts", evidence_id=evidence_id)],
        steps=[
            DerivationStep(
                seq=1,
                op="forecast_result",
                input_refs=["metric:phishing_attempts"],
                params=output,
                output=output,
                note="Forecast result.",
            )
        ],
        result=output,
        model_version=1,
        engine_version="forecast-test/v1",
    )
