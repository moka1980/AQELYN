"""ECR-0098 ordered-prefix witnesses for executive reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import new_id
from aqelyn.executive import (
    ExecutiveReport,
    Figure,
    InMemoryKPIDefinitionStore,
    InMemoryReportStore,
    KPIDefinition,
    KPIDefinitionStore,
    PostgresKPIDefinitionStore,
    PostgresReportStore,
    ReportSection,
    ReportStore,
    SourceRef,
)
from aqelyn.executive.postgres import _definition_args

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 8, 4, 16, 0, tzinfo=UTC)
ROW_COUNT = 6
KEY = "ecr0098_posture"


def _definition(version: int) -> KPIDefinition:
    return KPIDefinition(
        id=new_id("kdf"),
        key=KEY,
        version=version,
        title=f"ECR-0098 posture v{version}",
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


def _report(report_id: str, *, period: str = "2026-Q3") -> ExecutiveReport:
    figure = Figure(
        value=75.0,
        unit="score",
        source_refs=[SourceRef(kind="risk", ref_id=f"risk:{report_id}", as_of=NOW)],
        as_of=NOW,
    )
    return ExecutiveReport(
        id=report_id,
        title="ECR-0098 board report",
        period=period,
        sections=[ReportSection(key="kpis", title="KPIs", figures=[figure])],
        exceptions=[],
    )


async def _definition_stores(
    kind: str, definitions: list[KPIDefinition]
) -> AsyncIterator[KPIDefinitionStore]:
    if kind == "inmemory":
        memory_store = InMemoryKPIDefinitionStore()
        for definition in reversed(definitions):
            memory_store._definitions[(definition.key, definition.version)] = definition
        yield memory_store
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    pg_store = await PostgresKPIDefinitionStore.connect(PG_URL)
    async with pg_store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_kpi_definition")
        for definition in reversed(definitions):
            await conn.execute(
                "INSERT INTO aq_kpi_definition "
                "(id, kpi_key, version, title, inputs, combinator, unit, thresholds, "
                "promoted_by, promoted_at, active) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                *_definition_args(definition),
            )
    try:
        yield pg_store
    finally:
        await pg_store.close()


async def _report_stores(kind: str) -> AsyncIterator[ReportStore]:
    if kind == "inmemory":
        yield InMemoryReportStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresReportStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_executive_report")
    try:
        yield store
    finally:
        await store.close()


async def _assert_definition_prefixes(store: KPIDefinitionStore, expected: list[int]) -> None:
    held = await store.versions(KEY, limit=len(expected))
    assert len(held) == len(expected), "KPI definition fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.versions(KEY, limit=limit)
        assert [row.version for row in rows] == expected[:limit]


async def _assert_report_prefixes(store: ReportStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "executive report fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_kpi_versions_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    definitions = [_definition(version) for version in range(1, ROW_COUNT + 1)]
    expected = list(range(1, ROW_COUNT + 1))
    async for store in _definition_stores(kind, definitions):
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_definition_prefixes(store, expected)
        else:
            await _assert_definition_prefixes(store, expected)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_executive_report_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("rpt") for _ in range(ROW_COUNT))
    periods = ["2026-Q3", "2026-Q3", "2026-Q2", "2026-Q2", "2026-Q1", "2026-Q1"]
    reports = [_report(report_id, period=periods[index]) for index, report_id in enumerate(ids)]
    ordered = sorted(reports, key=lambda row: (row.period, row.id))
    expected = [row.id for row in ordered]
    async for store in _report_stores(kind):
        for report in reversed(ordered):
            await store.put(report)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_report_prefixes(store, expected)
        else:
            await _assert_report_prefixes(store, expected)
