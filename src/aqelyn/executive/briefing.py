"""Template-only briefings and EA-0004 package export (EA-0022 X4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import (
    ExecutiveConfigInvalid,
    FigureProvenanceMissing,
    ReportNotFound,
)
from aqelyn.evidence import EvidencePackage
from aqelyn.executive.models import ExecutiveBriefing, ExecutiveReport, ReportSection, SourceRef
from aqelyn.executive.store import ReportStore, validate_report_id, validate_tenant


class BriefingTemplate(BaseModel):
    """A versioned selector over report records.

    It intentionally contains no free-form narrative body. Narratives are rendered
    from the selected report records by this module.
    """

    model_config = ConfigDict(extra="forbid")

    version: int
    audience: str
    sections: list[str] = Field(default_factory=list)
    include_recommendations: bool = True

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ExecutiveConfigInvalid("briefing template version must be >= 1")
        return value

    @field_validator("audience")
    @classmethod
    def _audience(cls, value: str) -> str:
        if not value.strip():
            raise ExecutiveConfigInvalid("briefing template audience must not be empty")
        return value

    @field_validator("sections")
    @classmethod
    def _sections(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if not value.strip():
                raise ExecutiveConfigInvalid("briefing template sections must not be empty")
            out.append(value)
        if len(out) != len(set(out)):
            raise ExecutiveConfigInvalid("briefing template sections must not contain duplicates")
        return out


class EvidencePackager(Protocol):
    async def package(
        self, evidence_ids: list[str], *, by: ActorRef, reason: str
    ) -> EvidencePackage: ...


async def render_briefing(
    report: ExecutiveReport,
    *,
    template: BriefingTemplate,
    generated_at: datetime | None = None,
) -> ExecutiveBriefing:
    selected_sections = _selected_sections(report, template)
    rendered_sections = [
        ReportSection(
            key=section.key,
            title=section.title,
            figures=[figure.model_copy(deep=True) for figure in section.figures],
            narrative=_render_section_narrative(section, template=template),
            template_version=template.version,
        )
        for section in selected_sections
    ]
    return ExecutiveBriefing(
        tenant_id=report.tenant_id,
        audience=template.audience,
        template_version=template.version,
        sections=rendered_sections,
        recommendations=(
            _unique_source_refs(rendered_sections) if template.include_recommendations else []
        ),
        generated_at=generated_at or utc_now(),
    )


async def brief(
    *,
    report_store: ReportStore,
    report_id: str,
    template: BriefingTemplate,
    tenant_id: str | None,
    generated_at: datetime | None = None,
) -> ExecutiveBriefing:
    report = await _get_report(report_store, report_id, tenant_id=tenant_id)
    return await render_briefing(report, template=template, generated_at=generated_at)


async def export_report(
    *,
    report_store: ReportStore,
    evidence_store: EvidencePackager,
    report_id: str,
    by: ActorRef,
    tenant_id: str | None,
    reason: str | None = None,
) -> str:
    report = await _get_report(report_store, report_id, tenant_id=tenant_id)
    evidence_ids = _evidence_ids_for_export(report)
    package = await evidence_store.package(
        evidence_ids,
        by=by,
        reason=reason or f"executive report export: {report.id}",
    )
    return package.id


def _selected_sections(report: ExecutiveReport, template: BriefingTemplate) -> list[ReportSection]:
    by_key = {section.key: section for section in report.sections}
    keys = template.sections or [section.key for section in report.sections]
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise ExecutiveConfigInvalid(
            f"briefing template references sections absent from report: {missing!r}"
        )
    return [by_key[key] for key in keys]


def _render_section_narrative(section: ReportSection, *, template: BriefingTemplate) -> str:
    refs = sorted(
        {f"{ref.kind}:{ref.ref_id}" for figure in section.figures for ref in figure.source_refs}
    )
    ref_text = ", ".join(refs) if refs else "no cited figures"
    count = len(section.figures)
    label = "figure" if count == 1 else "figures"
    return (
        f"Template v{template.version}; section {section.key}; "
        f"{count} cited {label}; refs: {ref_text}."
    )


def _unique_source_refs(sections: Sequence[ReportSection]) -> list[SourceRef]:
    refs: dict[tuple[str, str, str], SourceRef] = {}
    for section in sections:
        for figure in section.figures:
            for ref in figure.source_refs:
                refs[(ref.kind, ref.ref_id, ref.as_of.isoformat())] = ref
    return [refs[key].model_copy(deep=True) for key in sorted(refs)]


def _evidence_ids_for_export(report: ExecutiveReport) -> list[str]:
    ids: set[str] = set()
    for ref in _source_refs(report):
        if ref.evidence_id is not None:
            ids.add(ref.evidence_id)
    issue_evidence_id = report.scope.get("issue_evidence_id")
    if isinstance(issue_evidence_id, str):
        ids.add(issue_evidence_id)
    if not ids:
        raise FigureProvenanceMissing("report export requires evidence-backed source_refs")
    return sorted(ids)


def _source_refs(report: ExecutiveReport) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for section in report.sections:
        for figure in section.figures:
            refs.extend(figure.source_refs)
    for figure in report.exceptions:
        refs.extend(figure.source_refs)
    return refs


async def _get_report(
    report_store: ReportStore, report_id: str, *, tenant_id: str | None
) -> ExecutiveReport:
    selected_id = validate_report_id(report_id)
    selected_tenant = validate_tenant(tenant_id)
    report = await report_store.get(selected_id, tenant_id=selected_tenant)
    if report is None:
        raise ReportNotFound(f"executive report not found: {selected_id}")
    return report
