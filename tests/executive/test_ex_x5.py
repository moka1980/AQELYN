"""X5 acceptance tests for ExecutiveIntelligenceService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ExceptionsUnavailable
from aqelyn.events import EventTypeRegistry
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.executive import (
    EXECUTIVE_EVENTS,
    EmptyExecutiveValueSource,
    ExecutiveIntelligenceService,
    ExecutiveKPIEngine,
    ExecutiveReport,
    ExecutiveReportEngine,
    Figure,
    InMemoryKPIDefinitionStore,
    InMemoryReportStore,
    PostgresKPIDefinitionStore,
    PostgresReportStore,
    ReportSection,
    SourceRef,
    content_hash_for_report,
)
from aqelyn.executive.service import register_executive_events
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 16, 18, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000220501"
ACTOR = ActorRef(actor_type="user", actor_id="executive-service@example.com")
EXECUTIVE_EVENT_TYPES = (
    "aqelyn.executive.report_issued",
    "aqelyn.executive.kpi_calculated",
    "aqelyn.executive.briefing_completed",
    "aqelyn.executive.dashboard_updated",
    "aqelyn.executive.summary_generated",
)


class _MaterialExceptionSource:
    async def material_exceptions(self, *, period: str, tenant_id: str | None) -> list[Figure]:
        _ = period, tenant_id
        return []


def _figure() -> Figure:
    return Figure(
        value=73.0,
        unit="score",
        source_refs=[
            SourceRef(
                kind="risk",
                ref_id="risk:board-posture",
                as_of=NOW,
                evidence_id=new_id("evd"),
            )
        ],
        confidence=0.91,
        as_of=NOW,
    )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_exec_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.executive_definition_store, InMemoryKPIDefinitionStore)
        assert isinstance(runtime.executive_report_store, InMemoryReportStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.executive_definition_store, PostgresKPIDefinitionStore)
        assert isinstance(runtime.executive_report_store, PostgresReportStore)

    service = runtime.kernel.get_service("executive_engine")
    assert service.name == "executive_engine"
    assert tuple(service.dependencies) == (
        "mission_engine",
        "compliance_engine",
        "risk_engine",
        "forecast_engine",
        "trust_engine",
    )
    assert isinstance(runtime.executive_kpi_engine, ExecutiveKPIEngine)
    assert isinstance(runtime.executive_report_engine, ExecutiveReportEngine)
    assert isinstance(runtime.executive_engine_service, ExecutiveIntelligenceService)
    assert runtime.executive_engine_service is service
    assert runtime.executive_engine_service.kpi_engine is runtime.executive_kpi_engine
    assert runtime.executive_engine_service.report_engine is runtime.executive_report_engine
    assert runtime.executive_engine_service.definition_store is runtime.executive_definition_store
    assert runtime.executive_engine_service.report_store is runtime.executive_report_store
    assert runtime.executive_engine_service.evidence_store is runtime.evidence_store
    assert set(runtime.executive_engine_service.owner_sources) == {
        "compliance",
        "risk",
        "forecast",
        "mission",
    }
    for source in runtime.executive_engine_service.owner_sources.values():
        assert isinstance(source, EmptyExecutiveValueSource)
    for event_type in EXECUTIVE_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["report_store"] == "healthy"
    assert pre_start.dependencies["definition_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["exception_source"] == "inert"
    assert pre_start.dependencies["owner_sources"] == "healthy"
    assert pre_start.dependencies["section_sources"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        executive_health = state.services["executive_engine"]

        assert executive_health.status == "healthy"
        assert executive_health.ready is True
        assert executive_health.dependencies["report_store"] == "healthy"
        assert executive_health.dependencies["definition_store"] == "healthy"
        assert executive_health.dependencies["evidence_store"] == "healthy"
        assert executive_health.dependencies["exception_source"] == "inert"
        assert executive_health.dependencies["owner_sources"] == "healthy"
        assert executive_health.dependencies["section_sources"] == "healthy"
        assert state.services["mission_engine"].ready is True
        assert state.services["compliance_engine"].ready is True
        assert state.services["risk_engine"].ready is True
        assert state.services["forecast_engine"].ready is True
        assert state.services["trust_engine"].ready is True
        assert state.services["_kernel"].ready is True

        draft = await runtime.executive_report_store.put(
            ExecutiveReport(
                tenant_id=None,
                title="Executive report 2026-Q3",
                period="2026-Q3",
                sections=[ReportSection(key="kpis", title="KPIs", figures=[_figure()])],
                exceptions=[_figure()],
                scope={"audience": "board"},
            )
        )
        with pytest.raises(ExceptionsUnavailable):
            await runtime.executive_engine_service.issue_report(
                draft.id,
                by=ACTOR,
                tenant_id=None,
            )
    finally:
        await runtime.kernel.stop()


def test_exec_register_executive_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_executive_events(registry)

    assert set(EXECUTIVE_EVENTS) == set(EXECUTIVE_EVENT_TYPES)
    for event_type in EXECUTIVE_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_exec_import_isolation() -> None:
    executive = importlib.import_module("aqelyn.executive")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert executive.ExecutiveIntelligenceService is ExecutiveIntelligenceService
    assert hasattr(factory, "create_runtime")


async def test_exec_content_hash_excludes_issue_evidence_id() -> None:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    report_store = InMemoryReportStore(mode="enterprise")
    figure = _figure()
    draft = await report_store.put(
        ExecutiveReport(
            tenant_id=TENANT,
            title="Executive report 2026-Q3",
            period="2026-Q3",
            sections=[ReportSection(key="kpis", title="KPIs", figures=[figure])],
            exceptions=[figure],
            scope={"audience": "board"},
        )
    )
    engine = ExecutiveReportEngine(
        report_store=report_store,
        exception_source=_MaterialExceptionSource(),
        evidence_store=evidence_store,
        clock=lambda: NOW,
    )

    issued = await engine.issue_report(draft.id, by=ACTOR, tenant_id=TENANT)

    assert isinstance(issued.scope["issue_evidence_id"], str)
    assert issued.content_hash == content_hash_for_report(issued)
