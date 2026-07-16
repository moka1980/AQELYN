"""X4 acceptance tests for executive briefings and export."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ExecutiveConfigInvalid
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.executive import (
    BriefingTemplate,
    ExecutiveReport,
    Figure,
    InMemoryReportStore,
    ReportSection,
    SourceRef,
    export_report,
    render_briefing,
)

NOW = datetime(2026, 7, 16, 17, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000220401"
ACTOR = ActorRef(actor_type="user", actor_id="executive-briefer@example.com")


class _TrackingReportStore:
    def __init__(self, report: ExecutiveReport) -> None:
        self.report = report.model_copy(deep=True)
        self.gets = 0
        self.puts = 0

    async def put(self, report: ExecutiveReport) -> ExecutiveReport:
        self.puts += 1
        self.report = report.model_copy(deep=True)
        return self.report.model_copy(deep=True)

    async def get(self, report_id: str, *, tenant_id: str | None = None) -> ExecutiveReport | None:
        self.gets += 1
        if self.report.id != report_id or self.report.tenant_id != tenant_id:
            return None
        return self.report.model_copy(deep=True)

    async def query(
        self, *, tenant_id: str | None, period: str | None = None, limit: int = 100
    ) -> list[ExecutiveReport]:
        _ = limit
        if self.report.tenant_id != tenant_id:
            return []
        if period is not None and self.report.period != period:
            return []
        return [self.report.model_copy(deep=True)]


async def _evidence(store: InMemoryEvidenceStore, label: str) -> EvidenceRecord:
    record = EvidenceRecord(
        id="",
        tenant_id=TENANT,
        evidence_type="executive.test_source",
        schema_version=1,
        subject=Subject(),
        collected_at=NOW,
        recorded_at=NOW,
        collector=ACTOR,
        source_id=new_id("src"),
        method="executive.test/v1",
        content={"label": label},
        content_hash="",
        confidence=1.0,
        labels={"module": "EA-0022", "label": label},
        seq=0,
        prev_hash=None,
        record_hash="",
    )
    return await store.add(record)


def _figure(*, kind: str, ref_id: str, evidence_id: str, value: float | str) -> Figure:
    return Figure(
        value=value,
        unit="score",
        source_refs=[SourceRef(kind=kind, ref_id=ref_id, as_of=NOW, evidence_id=evidence_id)],
        confidence=0.91,
        as_of=NOW,
    )


async def _report(store: InMemoryEvidenceStore) -> ExecutiveReport:
    kpi_evidence = await _evidence(store, "kpi")
    exception_evidence = await _evidence(store, "exception")
    issue_evidence = await _evidence(store, "issue")
    kpi = _figure(
        kind="risk",
        ref_id="risk:board-posture",
        evidence_id=kpi_evidence.id,
        value=73.0,
    )
    exception = _figure(
        kind="risk",
        ref_id="risk:material-exception",
        evidence_id=exception_evidence.id,
        value=95.0,
    )
    return ExecutiveReport(
        tenant_id=TENANT,
        title="Executive report 2026-Q3",
        period="2026-Q3",
        sections=[
            ReportSection(key="kpis", title="KPIs", figures=[kpi]),
            ReportSection(key="exceptions", title="Material exceptions", figures=[exception]),
        ],
        exceptions=[exception],
        frozen=True,
        issued_at=NOW,
        issued_by=ACTOR,
        content_hash="sha256:test",
        scope={
            "audience": "board",
            "issue_evidence_id": issue_evidence.id,
            "input_snapshot_ids": ["risk:board-posture", "risk:material-exception"],
        },
    )


async def test_exec_briefing_from_records() -> None:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    report = await _report(evidence_store)
    template = BriefingTemplate(version=2, audience="board", sections=["kpis", "exceptions"])

    briefing = await render_briefing(report, template=template, generated_at=NOW)

    assert briefing.tenant_id == report.tenant_id
    assert briefing.template_version == 2
    assert [section.key for section in briefing.sections] == ["kpis", "exceptions"]
    assert briefing.sections[0].figures == report.sections[0].figures
    assert briefing.sections[0].template_version == 2
    assert briefing.sections[0].narrative is not None
    assert "risk:board-posture" in briefing.sections[0].narrative
    assert {ref.ref_id for ref in briefing.recommendations} == {
        "risk:board-posture",
        "risk:material-exception",
    }

    with pytest.raises(ValidationError):
        BriefingTemplate.model_validate(
            {
                "version": 1,
                "audience": "board",
                "sections": ["kpis"],
                "free_prose": "Everything is fine.",
            }
        )

    with pytest.raises(ExecutiveConfigInvalid, match="absent from report"):
        await render_briefing(
            report,
            template=BriefingTemplate(version=1, audience="board", sections=["not_in_report"]),
            generated_at=NOW,
        )


async def test_exec_export_package() -> None:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    report = await _report(evidence_store)
    report_store = InMemoryReportStore(mode="enterprise")
    await report_store.put(report)

    package_id = await export_report(
        report_store=report_store,
        evidence_store=evidence_store,
        report_id=report.id,
        by=ACTOR,
        tenant_id=TENANT,
    )
    result = await evidence_store.verify_package(package_id)

    assert package_id.startswith("pkg_")
    assert result.ok is True
    package = evidence_store._packages[package_id]
    kpi_evidence_id = report.sections[0].figures[0].source_refs[0].evidence_id
    exception_evidence_id = report.exceptions[0].source_refs[0].evidence_id
    issue_evidence_id = report.scope["issue_evidence_id"]
    assert kpi_evidence_id is not None
    assert exception_evidence_id is not None
    assert isinstance(issue_evidence_id, str)
    assert sorted(package.evidence_ids) == sorted(
        {kpi_evidence_id, exception_evidence_id, issue_evidence_id}
    )


async def test_exec_read_only() -> None:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    report = await _report(evidence_store)
    before = copy.deepcopy(report.model_dump(mode="json"))
    report_store = _TrackingReportStore(report)

    briefing = await render_briefing(
        report,
        template=BriefingTemplate(version=1, audience="board"),
        generated_at=NOW,
    )
    package_id = await export_report(
        report_store=report_store,
        evidence_store=evidence_store,
        report_id=report.id,
        by=ACTOR,
        tenant_id=TENANT,
    )
    after = report.model_dump(mode="json")

    assert briefing.sections
    assert package_id.startswith("pkg_")
    assert before == after
    assert report_store.gets == 1
    assert report_store.puts == 0
