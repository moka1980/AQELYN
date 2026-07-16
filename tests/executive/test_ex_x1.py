"""X1 acceptance tests for executive types and KPI definition versioning."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    ExecutiveConfigInvalid,
    FigureProvenanceMissing,
    KPIDefinitionNotFound,
)
from aqelyn.executive import (
    Dashboard,
    ExceptionItem,
    ExecutiveConfig,
    Figure,
    InMemoryKPIDefinitionStore,
    KPIDefinition,
    KPIRecord,
    ReportSection,
    SourceRef,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="exec-reviewer@example.com")
EVIDENCE_ID = new_id("evd")


def _source_ref() -> SourceRef:
    return SourceRef(
        kind="risk",
        ref_id="risk:mission-critical",
        as_of=NOW,
        evidence_id=EVIDENCE_ID,
    )


def _figure() -> Figure:
    return Figure(
        value=73.0,
        unit="score",
        source_refs=[_source_ref()],
        confidence=0.91,
        as_of=NOW,
    )


def _definition(*, title: str = "Executive posture") -> KPIDefinition:
    return KPIDefinition(
        key="executive_posture",
        title=title,
        inputs=[
            {
                "source_engine": "risk",
                "metric": "score",
                "selector": {"scope": "all"},
                "weight": 1.0,
            }
        ],
        combinator="identity",
        unit="score",
        thresholds={"amber": 60.0, "red": 40.0},
    )


async def test_exec_definition_promote() -> None:
    store = InMemoryKPIDefinitionStore()

    first = await store.propose(_definition(), by=ACTOR)

    assert first.version == 1
    assert first.active is False
    assert first.promoted_by is None
    with pytest.raises(KPIDefinitionNotFound):
        await store.active("executive_posture")

    promoted_first = await store.promote(
        "executive_posture",
        1,
        by=ACTOR,
        reason="Initial board metric.",
    )

    assert promoted_first.active is True
    assert promoted_first.promoted_by == ACTOR
    assert promoted_first.promoted_at is not None
    assert (await store.active("executive_posture")).version == 1

    second = await store.propose(_definition(title="Executive posture v2"), by=ACTOR)

    assert second.version == 2
    assert second.active is False
    assert (await store.active("executive_posture")).version == 1

    promoted_second = await store.promote(
        "executive_posture",
        2,
        by=ACTOR,
        reason="Threshold review.",
    )

    active = await store.active("executive_posture")
    original = await store.get("executive_posture", 1)

    assert promoted_second.version == 2
    assert active.version == 2
    assert original is not None
    assert original.version == 1
    assert original.active is True
    assert original.title == "Executive posture"

    active.title = "mutated caller copy"
    assert (await store.active("executive_posture")).title == "Executive posture v2"


def test_exec_config_invalid() -> None:
    with pytest.raises(ExecutiveConfigInvalid, match="max_kpis"):
        ExecutiveConfig(max_kpis=0)

    with pytest.raises(ExecutiveConfigInvalid, match="unknown source engine"):
        KPIDefinition(
            key="bad_source",
            title="Bad source",
            inputs=[{"source_engine": "ai_magic", "metric": "score"}],
            combinator="identity",
            unit="score",
            thresholds={"amber": 60.0, "red": 40.0},
        )

    with pytest.raises(ExecutiveConfigInvalid, match="unknown metric"):
        KPIDefinition(
            key="bad_metric",
            title="Bad metric",
            inputs=[{"source_engine": "risk", "metric": "posture_score"}],
            combinator="identity",
            unit="score",
            thresholds={"amber": 60.0, "red": 40.0},
        )

    with pytest.raises(ExecutiveConfigInvalid, match="ordered"):
        KPIDefinition(
            key="bad_thresholds",
            title="Bad thresholds",
            inputs=[{"source_engine": "risk", "metric": "score"}],
            combinator="identity",
            unit="score",
            thresholds={"red": 40.0, "amber": 60.0},
        )

    with pytest.raises(ExecutiveConfigInvalid, match="promotion metadata"):
        KPIDefinition(
            key="bad_active",
            title="Bad active",
            inputs=[{"source_engine": "risk", "metric": "score"}],
            combinator="identity",
            unit="score",
            thresholds={"amber": 60.0, "red": 40.0},
            active=True,
        )


def test_exec_figure_requires_provenance() -> None:
    with pytest.raises(FigureProvenanceMissing):
        Figure(value=73.0, unit="score", source_refs=[], as_of=NOW)

    with pytest.raises(FigureProvenanceMissing):
        Dashboard.model_validate(
            {
                "owner": ACTOR.model_dump(mode="json"),
                "widgets": [{"value": 73.0, "unit": "score", "source_refs": [], "as_of": NOW}],
                "refresh_interval": 300,
            }
        )

    with pytest.raises(FigureProvenanceMissing):
        ExceptionItem.model_validate(
            {
                "key": "material_exception",
                "title": "Material exception",
                "figure": {
                    "value": "critical exception",
                    "unit": "status",
                    "source_refs": [],
                    "as_of": NOW,
                },
            }
        )

    record = KPIRecord(
        kpi_key="executive_posture",
        definition_version=1,
        figure=_figure(),
        reporting_period="2026-Q3",
        band="amber",
    )
    section = ReportSection(key="kpis", title="KPIs", figures=[record.figure])

    assert record.figure.source_refs == [_source_ref()]
    assert section.figures[0].source_refs == [_source_ref()]
