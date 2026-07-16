"""Report assembly and immutable issuance (EA-0022 X3)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, sha256_hex, utc_now
from aqelyn.conventions.errors import (
    ExecutiveConfigInvalid,
    FigureProvenanceMissing,
    ReportNotFound,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.executive.exceptions import MaterialExceptionSource, collect_material_exceptions
from aqelyn.executive.kpi import ExecutiveKPIEngine
from aqelyn.executive.models import (
    ExecutiveReport,
    Figure,
    ReportConfig,
    ReportExclude,
    ReportSection,
    SourceRef,
)
from aqelyn.executive.store import ReportStore, validate_report_id, validate_tenant
from aqelyn.forecast.models import AccuracyRecord, Forecast

_EXECUTIVE_ACTOR = ActorRef(actor_type="system", actor_id="executive-engine")
_EXCEPTIONS_SECTION_KEY = "exceptions"


class SectionFigureSource(Protocol):
    async def section_figures(
        self, *, section: str, period: str, tenant_id: str | None
    ) -> Sequence[Figure]: ...


class EvidenceRecorder(Protocol):
    async def add(self, record: EvidenceRecord) -> EvidenceRecord: ...


class ExecutiveReportEngine:
    def __init__(
        self,
        *,
        report_store: ReportStore,
        exception_source: MaterialExceptionSource,
        kpi_engine: ExecutiveKPIEngine | None = None,
        kpi_keys: Sequence[str] = (),
        section_sources: Mapping[str, SectionFigureSource] | None = None,
        evidence_store: EvidenceRecorder | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
        clock: Any | None = None,
    ) -> None:
        self.report_store = report_store
        self.exception_source = exception_source
        self.kpi_engine = kpi_engine
        self.kpi_keys = tuple(kpi_keys)
        self.section_sources = dict(section_sources or {})
        self.evidence_store = evidence_store
        self.actor = actor or _EXECUTIVE_ACTOR
        self.source_id = source_id or new_id("src")
        self._clock = clock or utc_now

    async def assemble_report(
        self, *, config: ReportConfig, tenant_id: str | None
    ) -> ExecutiveReport:
        tenant_id = validate_tenant(tenant_id)
        sections: list[ReportSection] = []
        excludes: list[ReportExclude] = []
        pinned_definitions: dict[str, int] = {}
        for section_key in config.sections:
            if section_key == "kpis":
                section, section_excludes, pins = await self._kpi_section(
                    period=config.period,
                    tenant_id=tenant_id,
                )
                sections.append(section)
                excludes.extend(section_excludes)
                pinned_definitions.update(pins)
                continue
            sections.append(
                await self._owner_section(
                    section_key,
                    period=config.period,
                    tenant_id=tenant_id,
                )
            )

        exceptions = await collect_material_exceptions(
            self.exception_source,
            period=config.period,
            tenant_id=tenant_id,
        )
        sections.append(
            ReportSection(
                key=_EXCEPTIONS_SECTION_KEY,
                title="Material exceptions",
                figures=exceptions,
            )
        )
        report = ExecutiveReport(
            tenant_id=tenant_id,
            title=f"Executive report {config.period}",
            period=config.period,
            sections=sections,
            exceptions=exceptions,
            scope=_scope(
                config=config,
                sections=sections,
                pinned_definitions=pinned_definitions,
            ),
            excludes=excludes,
        )
        return await self.report_store.put(report)

    async def issue_report(
        self, report_id: str, *, by: ActorRef, tenant_id: str | None
    ) -> ExecutiveReport:
        selected_id = validate_report_id(report_id)
        tenant_id = validate_tenant(tenant_id)
        report = await self.report_store.get(selected_id, tenant_id=tenant_id)
        if report is None:
            raise ReportNotFound(f"executive report not found: {selected_id}")

        # Re-read exceptions at issuance time. A clean-looking report is worse
        # than no report when material-exception sources are unavailable.
        await collect_material_exceptions(
            self.exception_source,
            period=report.period,
            tenant_id=tenant_id,
        )

        issued_at = self._clock()
        frozen_scope = _scope_with_freeze_metadata(report)
        content_hash = _report_content_hash(report.model_copy(update={"scope": frozen_scope}))
        evidence_id = await self._record_issue_evidence(
            report,
            by=by,
            issued_at=issued_at,
            content_hash=content_hash,
        )
        if evidence_id is not None:
            frozen_scope = {**frozen_scope, "issue_evidence_id": evidence_id}
        frozen = report.model_copy(
            update={
                "approval_status": "published",
                "issued_at": issued_at,
                "issued_by": by,
                "content_hash": content_hash,
                "frozen": True,
                "scope": frozen_scope,
            },
            deep=True,
        )
        return await self.report_store.put(frozen)

    async def _kpi_section(
        self, *, period: str, tenant_id: str | None
    ) -> tuple[ReportSection, list[ReportExclude], dict[str, int]]:
        if self.kpi_engine is None:
            raise ExecutiveConfigInvalid("kpi section requires a KPI engine")
        figures: list[Figure] = []
        excludes: list[ReportExclude] = []
        pins: dict[str, int] = {}
        for key in self.kpi_keys:
            try:
                record = await self.kpi_engine.compute_kpi(
                    key=key,
                    period=period,
                    tenant_id=tenant_id,
                )
            except (ExecutiveConfigInvalid, FigureProvenanceMissing, StoreUnavailable) as exc:
                excludes.append(ReportExclude(key=key, reason=exc.message))
                continue
            figures.append(record.figure)
            pins[record.kpi_key] = record.definition_version
        return ReportSection(key="kpis", title="KPIs", figures=figures), excludes, pins

    async def _owner_section(
        self, section_key: str, *, period: str, tenant_id: str | None
    ) -> ReportSection:
        source = self.section_sources.get(section_key)
        if source is None:
            return ReportSection(key=section_key, title=_section_title(section_key), figures=[])
        try:
            figures = await source.section_figures(
                section=section_key,
                period=period,
                tenant_id=tenant_id,
            )
        except StoreUnavailable as exc:
            raise ExecutiveConfigInvalid(f"{section_key} section source unavailable") from exc
        return ReportSection(
            key=section_key,
            title=_section_title(section_key),
            figures=[Figure.model_validate(figure.model_dump(mode="json")) for figure in figures],
        )

    async def _record_issue_evidence(
        self,
        report: ExecutiveReport,
        *,
        by: ActorRef,
        issued_at: datetime,
        content_hash: str,
    ) -> str | None:
        if self.evidence_store is None:
            return None
        record = EvidenceRecord(
            id="",
            tenant_id=report.tenant_id,
            evidence_type="executive.report_issued",
            schema_version=1,
            subject=Subject(),
            collected_at=issued_at,
            recorded_at=issued_at,
            collector=by,
            source_id=self.source_id,
            method="executive.issue_report/v1",
            content={
                "report_id": report.id,
                "period": report.period,
                "content_hash": content_hash,
                "source_refs": [ref.model_dump(mode="json") for ref in _all_source_refs(report)],
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0022", "kind": "report_issue"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        evidence = await self.evidence_store.add(record)
        return evidence.id


async def assemble_report(
    *,
    report_store: ReportStore,
    exception_source: MaterialExceptionSource,
    config: ReportConfig,
    tenant_id: str | None,
    kpi_engine: ExecutiveKPIEngine | None = None,
    kpi_keys: Sequence[str] = (),
    section_sources: Mapping[str, SectionFigureSource] | None = None,
) -> ExecutiveReport:
    engine = ExecutiveReportEngine(
        report_store=report_store,
        exception_source=exception_source,
        kpi_engine=kpi_engine,
        kpi_keys=kpi_keys,
        section_sources=section_sources,
    )
    return await engine.assemble_report(config=config, tenant_id=tenant_id)


async def issue_report(
    *,
    report_store: ReportStore,
    exception_source: MaterialExceptionSource,
    report_id: str,
    by: ActorRef,
    tenant_id: str | None,
) -> ExecutiveReport:
    engine = ExecutiveReportEngine(report_store=report_store, exception_source=exception_source)
    return await engine.issue_report(report_id, by=by, tenant_id=tenant_id)


def forecast_summary_figure(forecast: Forecast, accuracy: AccuracyRecord) -> Figure:
    evidence_id = next(
        (basis.evidence_id for basis in forecast.basis if basis.evidence_id is not None),
        None,
    )
    return Figure(
        value=(
            f"{forecast.point} [{forecast.interval.low}, {forecast.interval.high}] "
            f"accuracy {accuracy.within_interval_pct:.3f}"
        ),
        unit=(
            f"{forecast.metric}; interval_level={forecast.interval.level}; "
            f"accuracy_n={accuracy.n}; accuracy_mae={accuracy.mae}"
        ),
        source_refs=[
            SourceRef(
                kind="forecast",
                ref_id=forecast.id,
                as_of=forecast.issued_at,
                evidence_id=evidence_id,
            )
        ],
        confidence=forecast.confidence,
        as_of=forecast.issued_at,
    )


def content_hash_for_report(report: ExecutiveReport) -> str:
    return _report_content_hash(report)


def _scope(
    *,
    config: ReportConfig,
    sections: Sequence[ReportSection],
    pinned_definitions: Mapping[str, int],
) -> dict[str, Any]:
    return {
        "audience": config.audience,
        "period": config.period,
        "requested_sections": list(config.sections),
        "assembled_sections": [section.key for section in sections],
        "pinned_definitions": dict(sorted(pinned_definitions.items())),
        "input_snapshot_ids": _input_snapshot_ids_from_sections(sections),
        "owner_as_of": _owner_as_of_from_sections(sections),
    }


def _scope_with_freeze_metadata(report: ExecutiveReport) -> dict[str, Any]:
    scope = dict(report.scope)
    scope["input_snapshot_ids"] = sorted(set(_input_snapshot_ids(report)))
    scope["owner_as_of"] = _owner_as_of(report)
    scope.setdefault("pinned_definitions", {})
    return scope


def _report_content_hash(report: ExecutiveReport) -> str:
    return sha256_hex(
        {
            "tenant_id": report.tenant_id,
            "title": report.title,
            "version": report.version,
            "period": report.period,
            "sections": [section.model_dump(mode="json") for section in report.sections],
            "exceptions": [figure.model_dump(mode="json") for figure in report.exceptions],
            "scope": _scope_for_content_hash(report.scope),
            "excludes": [exclude.model_dump(mode="json") for exclude in report.excludes],
        }
    )


def _scope_for_content_hash(scope: Mapping[str, Any]) -> dict[str, Any]:
    selected = dict(scope)
    selected.pop("issue_evidence_id", None)
    return selected


def _input_snapshot_ids(report: ExecutiveReport) -> list[str]:
    return [ref.ref_id for ref in _all_source_refs(report)]


def _input_snapshot_ids_from_sections(sections: Sequence[ReportSection]) -> list[str]:
    return sorted(
        {
            ref.ref_id
            for section in sections
            for figure in section.figures
            for ref in figure.source_refs
        }
    )


def _owner_as_of(report: ExecutiveReport) -> dict[str, str]:
    rows: dict[str, str] = {}
    for ref in _all_source_refs(report):
        rows[ref.ref_id] = ref.as_of.isoformat()
    return dict(sorted(rows.items()))


def _owner_as_of_from_sections(sections: Sequence[ReportSection]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for section in sections:
        for figure in section.figures:
            for ref in figure.source_refs:
                rows[ref.ref_id] = ref.as_of.isoformat()
    return dict(sorted(rows.items()))


def _all_source_refs(report: ExecutiveReport) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for section in report.sections:
        for figure in section.figures:
            refs.extend(figure.source_refs)
    for figure in report.exceptions:
        refs.extend(figure.source_refs)
    refs.sort(key=lambda ref: (ref.kind, ref.ref_id, ref.as_of.isoformat()))
    return refs


def _section_title(section_key: str) -> str:
    return section_key.replace("_", " ").title()
