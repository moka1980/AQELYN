"""X2 acceptance tests for executive KPI computation and stores."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    ExecutiveConfigInvalid,
    FigureProvenanceMissing,
    FrozenReportMutation,
    KPIDefinitionNotFound,
)
from aqelyn.decision import replay
from aqelyn.executive import (
    ExecutiveKPIEngine,
    ExecutiveReport,
    Figure,
    InMemoryKPIDefinitionStore,
    InMemoryReportStore,
    KPIDefinition,
    KPIDefinitionStore,
    KPIInput,
    OwnerMetric,
    PostgresKPIDefinitionStore,
    PostgresReportStore,
    ReportSection,
    ReportStore,
    SourceRef,
    kpi_operation_registry,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000220001"
OTHER_TENANT = "018f0000-0000-7000-8000-000000220002"
ACTOR = ActorRef(actor_type="user", actor_id="executive-reviewer@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _Source:
    def __init__(self, source_engine: str, values: dict[str, OwnerMetric]) -> None:
        self.source_engine = source_engine
        self.values = values
        self.reads: list[tuple[str, str | None, str]] = []
        self.resolves: list[str] = []

    async def read(
        self,
        source_input: KPIInput,
        *,
        tenant_id: str | None,
        period: str,
    ) -> OwnerMetric | None:
        self.reads.append((source_input.metric, tenant_id, period))
        return self.values.get(source_input.metric)

    async def resolve(self, source_ref: SourceRef, *, tenant_id: str | None) -> OwnerMetric | None:
        _ = tenant_id
        self.resolves.append(source_ref.ref_id)
        for value in self.values.values():
            if value.ref_id == source_ref.ref_id:
                return value
        return None


async def _definition_store(kind: str) -> AsyncIterator[KPIDefinitionStore]:
    if kind == "inmemory":
        yield InMemoryKPIDefinitionStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresKPIDefinitionStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_kpi_definition")
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


async def _report_store(kind: str) -> AsyncIterator[ReportStore]:
    if kind == "inmemory":
        yield InMemoryReportStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresReportStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_executive_report")
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


def _metric(
    source_engine: str,
    metric: str,
    value: float,
    *,
    confidence: float = 0.91,
    evidence_id: str | None = None,
) -> OwnerMetric:
    return OwnerMetric(
        source_engine=source_engine,
        ref_id=f"{source_engine}:{metric}:record",
        value=value,
        unit="score",
        as_of=NOW,
        confidence=confidence,
        evidence_id=evidence_id or new_id("evd"),
        owner_record={
            "engine": source_engine,
            "metric": metric,
            "value": value,
            "evidence_id": evidence_id or new_id("evd"),
        },
    )


def _definition(
    *,
    key: str = "board_posture",
    inputs: list[dict[str, object]] | None = None,
    combinator: str = "identity",
) -> KPIDefinition:
    return KPIDefinition(
        key=key,
        title="Board posture",
        inputs=inputs
        or [
            {
                "source_engine": "risk",
                "metric": "score",
                "selector": {"scope": "board"},
                "weight": 1.0,
            }
        ],
        combinator=combinator,
        unit="score",
        thresholds={"amber": 60.0, "red": 40.0},
    )


def _figure(*, value: float = 73.0) -> Figure:
    return Figure(
        value=value,
        unit="score",
        source_refs=[
            SourceRef(kind="risk", ref_id="risk:board:record", as_of=NOW, evidence_id=new_id("evd"))
        ],
        confidence=0.8,
        as_of=NOW,
    )


def _report(*, report_id: str | None = None, tenant_id: str | None = TENANT) -> ExecutiveReport:
    data: dict[str, object] = {
        "tenant_id": tenant_id,
        "title": "Board report",
        "period": "2026-Q3",
        "sections": [ReportSection(key="kpis", title="KPIs", figures=[_figure()])],
        "exceptions": [_figure(value=95.0)],
    }
    if report_id is not None:
        data["id"] = report_id
    return ExecutiveReport.model_validate(data)


async def _promoted_store(definition: KPIDefinition) -> InMemoryKPIDefinitionStore:
    store = InMemoryKPIDefinitionStore()
    proposed = await store.propose(definition, by=ACTOR)
    await store.promote(proposed.key, proposed.version, by=ACTOR, reason="X2 acceptance")
    return store


async def test_exec_provenance_required() -> None:
    definition_store = await _promoted_store(_definition())
    source = _Source("risk", {"score": _metric("risk", "score", 73.0)})
    engine = ExecutiveKPIEngine(definition_store, {"risk": source})

    with pytest.raises(FigureProvenanceMissing):
        Figure(value=73.0, unit="score", source_refs=[], as_of=NOW)

    record = await engine.compute_kpi(key="board_posture", period="2026-Q3", tenant_id=TENANT)

    assert record.figure.source_refs
    assert record.figure.source_refs[0].evidence_id is not None

    empty_engine = ExecutiveKPIEngine(definition_store, {})
    with pytest.raises(ExecutiveConfigInvalid, match="source is unavailable"):
        await empty_engine.compute_kpi(key="board_posture", period="2026-Q3", tenant_id=TENANT)


async def test_exec_drill_down() -> None:
    evidence_id = new_id("evd")
    definition_store = await _promoted_store(_definition())
    source = _Source("risk", {"score": _metric("risk", "score", 73.0, evidence_id=evidence_id)})
    engine = ExecutiveKPIEngine(definition_store, {"risk": source})

    record = await engine.compute_kpi(key="board_posture", period="2026-Q3", tenant_id=TENANT)
    rows = await engine.drill_down(record.figure, tenant_id=TENANT)

    assert [row.source_ref.ref_id for row in rows] == ["risk:score:record"]
    assert rows[0].evidence_id == evidence_id
    assert rows[0].owner_record["value"] == 73.0
    assert source.resolves == ["risk:score:record"]


async def test_exec_no_recomputation() -> None:
    definition_store = await _promoted_store(_definition())
    source = _Source("risk", {"score": _metric("risk", "score", 88.0, confidence=0.72)})
    engine = ExecutiveKPIEngine(definition_store, {"risk": source})

    record = await engine.compute_kpi(key="board_posture", period="2026-Q3", tenant_id=TENANT)

    assert record.figure.value == 88.0
    assert record.figure.confidence == 0.72
    assert source.reads == [("score", TENANT, "2026-Q3")]
    assert record.derivation is None


async def test_exec_composed_not_reinvented() -> None:
    definition = _definition(
        key="composed_posture",
        inputs=[
            {
                "source_engine": "risk",
                "metric": "score",
                "selector": {"scope": "board"},
                "weight": 0.75,
            },
            {
                "source_engine": "compliance",
                "metric": "posture_score",
                "selector": {"framework": "board"},
                "weight": 0.25,
            },
        ],
        combinator="weighted_average",
    )
    definition_store = await _promoted_store(definition)
    risk_source = _Source("risk", {"score": _metric("risk", "score", 80.0, confidence=0.9)})
    compliance_source = _Source(
        "compliance",
        {"posture_score": _metric("compliance", "posture_score", 60.0, confidence=0.7)},
    )
    engine = ExecutiveKPIEngine(
        definition_store,
        {"risk": risk_source, "compliance": compliance_source},
    )

    record = await engine.compute_kpi(key="composed_posture", period="2026-Q3", tenant_id=TENANT)

    assert record.figure.value == pytest.approx(75.0)
    assert record.figure.confidence == 0.7
    assert [ref.kind for ref in record.figure.source_refs] == ["risk", "compliance"]
    assert record.derivation is not None
    assert replay(record.derivation, registry=kpi_operation_registry()) == {"value": 75.0}


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_exec_def_contract(kind: str) -> None:
    async for store in _definition_store(kind):
        first = await store.propose(_definition(key="contract_posture"), by=ACTOR)
        second = await store.propose(
            _definition(
                key="contract_posture",
                inputs=[{"source_engine": "risk", "metric": "score"}],
            ),
            by=ACTOR,
        )

        assert first.version == 1
        assert second.version == 2
        with pytest.raises(KPIDefinitionNotFound):
            await store.active("contract_posture")

        promoted_first = await store.promote(
            "contract_posture", 1, by=ACTOR, reason="First board definition"
        )
        promoted_second = await store.promote(
            "contract_posture", 2, by=ACTOR, reason="Second board definition"
        )

        assert promoted_first.active is True
        assert promoted_second.active is True
        assert (await store.active("contract_posture")).version == 2
        assert (await store.get("contract_posture", 1)) == promoted_first
        assert [row.version for row in await store.versions("contract_posture")] == [1, 2]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_exec_report_contract(kind: str) -> None:
    async for store in _report_store(kind):
        tenant_report = await store.put(_report())
        other_report = await store.put(_report(tenant_id=OTHER_TENANT))

        assert (await store.get(tenant_report.id, tenant_id=TENANT)) == tenant_report
        assert await store.get(tenant_report.id, tenant_id=OTHER_TENANT) is None
        assert [row.id for row in await store.query(tenant_id=TENANT, period="2026-Q3")] == [
            tenant_report.id
        ]
        assert [row.id for row in await store.query(tenant_id=OTHER_TENANT)] == [other_report.id]

        draft_update = tenant_report.model_copy(update={"title": "Updated draft"}, deep=True)
        assert (await store.put(draft_update)).title == "Updated draft"

        frozen = draft_update.model_copy(
            update={
                "frozen": True,
                "issued_at": NOW,
                "issued_by": ACTOR,
                "content_hash": "sha256:test",
                "approval_status": "published",
            },
            deep=True,
        )
        await store.put(frozen)
        with pytest.raises(FrozenReportMutation):
            await store.put(frozen.model_copy(update={"title": "mutated"}, deep=True))
