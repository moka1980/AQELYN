"""Executive Intelligence AQService wrapper and events (EA-0022 X5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    EvidenceNotFound,
    ExceptionsUnavailable,
    ExecutiveConfigInvalid,
    StoreUnavailable,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import EvidenceStore
from aqelyn.executive.briefing import BriefingTemplate, brief, export_report
from aqelyn.executive.definitions import KPIDefinitionStore
from aqelyn.executive.exceptions import collect_material_exceptions
from aqelyn.executive.kpi import ExecutiveKPIEngine, KPIValueSource, OwnerMetric
from aqelyn.executive.models import (
    VALID_INPUT_METRICS,
    ExecutiveBriefing,
    ExecutiveConfig,
    ExecutiveReport,
    Figure,
    KPIInput,
    KPIRecord,
    ReportConfig,
    SourceRef,
)
from aqelyn.executive.report import ExecutiveReportEngine, SectionFigureSource
from aqelyn.executive.store import ReportStore
from aqelyn.kernel.service import HealthStatus

EXECUTIVE_EVENTS: dict[str, int] = {
    "aqelyn.executive.report_issued": 1,
    "aqelyn.executive.kpi_calculated": 1,
    "aqelyn.executive.briefing_completed": 1,
    "aqelyn.executive.dashboard_updated": 1,
    "aqelyn.executive.summary_generated": 1,
}


def register_executive_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in EXECUTIVE_EVENTS.items():
        registry.register(event_type, schema_version, None)


class EmptyExecutiveValueSource:
    """Availability-only owner source for a freshly wired runtime.

    It proves the owner-read seam is callable without inventing report values.
    """

    def __init__(self, source_engine: str) -> None:
        if source_engine not in VALID_INPUT_METRICS:
            raise ExecutiveConfigInvalid(f"unknown source engine: {source_engine!r}")
        self.source_engine = source_engine

    async def read(
        self,
        source_input: KPIInput,
        *,
        tenant_id: str | None,
        period: str,
    ) -> OwnerMetric | None:
        _ = tenant_id, period
        if source_input.source_engine != self.source_engine:
            raise ExecutiveConfigInvalid("owner source engine mismatch")
        return None

    async def resolve(self, source_ref: SourceRef, *, tenant_id: str | None) -> OwnerMetric | None:
        _ = source_ref, tenant_id
        return None


class EmptyMaterialExceptionSource:
    """Refusing default until material-exception owners are wired.

    Per ECR-0013, returning an empty collection here would claim that no material
    exceptions exist. The default cannot know that, so report assembly and issuance
    fail closed instead.
    """

    async def material_exceptions(self, *, period: str, tenant_id: str | None) -> Sequence[Figure]:
        _ = period, tenant_id
        raise ExceptionsUnavailable(
            "executive material exceptions are not wired to authoritative owner sources "
            "(ECR-0013): refusing rather than reporting no exceptions"
        )


class ExecutiveIntelligenceService:
    def __init__(
        self,
        report_engine: ExecutiveReportEngine,
        *,
        kpi_engine: ExecutiveKPIEngine,
        definition_store: KPIDefinitionStore,
        report_store: ReportStore,
        evidence_store: EvidenceStore,
        owner_sources: Mapping[str, KPIValueSource],
        section_sources: Mapping[str, SectionFigureSource] | None = None,
        config: ExecutiveConfig | None = None,
        close_definition_store: Callable[[], Awaitable[None]] | None = None,
        close_report_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "mission_engine",
            "compliance_engine",
            "risk_engine",
            "forecast_engine",
            "trust_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.report_engine = report_engine
        self.kpi_engine = kpi_engine
        self.definition_store = definition_store
        self.report_store = report_store
        self.evidence_store = evidence_store
        self.owner_sources = dict(owner_sources)
        self.section_sources = dict(section_sources or {})
        self.config = config or ExecutiveConfig()
        self._close_definition_store = close_definition_store
        self._close_report_store = close_report_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "executive_engine"

    @property
    def dependencies(self) -> Sequence[str]:
        return self._dependencies

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_available()
        self._started = True

    async def stop(self) -> None:
        try:
            if self._close_report_store is not None:
                await self._close_report_store()
            if self._close_definition_store is not None:
                await self._close_definition_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_report_store()
            dependencies["report_store"] = "healthy"
            await self._check_definition_store()
            dependencies["definition_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            dependencies["exception_source"] = await self._check_exception_source()
            await self._check_owner_sources()
            dependencies["owner_sources"] = "healthy"
            await self._check_section_sources()
            dependencies["section_sources"] = "healthy"
        except ExecutiveConfigInvalid as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
        except Exception as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=str(exc),
                dependencies=dependencies,
            )

        if not self._started:
            return HealthStatus(
                status="degraded",
                ready=False,
                detail="service not started",
                dependencies=dependencies,
            )
        return HealthStatus(status="healthy", ready=True, dependencies=dependencies)

    async def compute_kpi(self, *, key: str, period: str, tenant_id: str | None) -> KPIRecord:
        return await self.kpi_engine.compute_kpi(key=key, period=period, tenant_id=tenant_id)

    async def assemble_report(
        self, *, config: ReportConfig, tenant_id: str | None
    ) -> ExecutiveReport:
        return await self.report_engine.assemble_report(config=config, tenant_id=tenant_id)

    async def issue_report(
        self, report_id: str, *, by: ActorRef, tenant_id: str | None
    ) -> ExecutiveReport:
        return await self.report_engine.issue_report(report_id, by=by, tenant_id=tenant_id)

    async def brief(
        self,
        *,
        report_id: str,
        template: BriefingTemplate,
        tenant_id: str | None,
        generated_at: datetime | None = None,
    ) -> ExecutiveBriefing:
        return await brief(
            report_store=self.report_store,
            report_id=report_id,
            template=template,
            tenant_id=tenant_id,
            generated_at=generated_at,
        )

    async def export_report(
        self,
        report_id: str,
        *,
        by: ActorRef,
        tenant_id: str | None,
        reason: str | None = None,
    ) -> str:
        return await export_report(
            report_store=self.report_store,
            evidence_store=self.evidence_store,
            report_id=report_id,
            by=by,
            tenant_id=tenant_id,
            reason=reason,
        )

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_report_store()
        await self._check_definition_store()
        await self._check_evidence_store()
        await self._check_exception_source()
        await self._check_owner_sources()
        await self._check_section_sources()

    def _check_config(self) -> None:
        ExecutiveConfig.model_validate(self.config.model_dump(mode="json"))

    async def _check_report_store(self) -> None:
        try:
            await self.report_store.get(new_id("rpt"), tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"executive report store unavailable: {exc}") from exc

    async def _check_definition_store(self) -> None:
        try:
            await self.definition_store.versions("healthcheck", limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"executive definition store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"executive evidence store unavailable: {exc}") from exc

    async def _check_exception_source(self) -> str:
        # The refusing default is an acceptable known state: the service can still
        # compute KPIs, while report assembly/issuance refuses rather than presenting
        # an unverified empty exceptions section (ECR-0013).
        if isinstance(self.report_engine.exception_source, EmptyMaterialExceptionSource):
            return "inert"
        try:
            await collect_material_exceptions(
                self.report_engine.exception_source,
                period="healthcheck",
                tenant_id=None,
            )
        except Exception as exc:
            raise StoreUnavailable(f"executive exception source unavailable: {exc}") from exc
        return "healthy"

    async def _check_owner_sources(self) -> None:
        if not self.owner_sources:
            raise StoreUnavailable("executive owner sources unavailable")
        for source_engine, source in sorted(self.owner_sources.items()):
            if source_engine not in VALID_INPUT_METRICS:
                raise StoreUnavailable(f"executive owner source unknown: {source_engine!r}")
            metric = sorted(VALID_INPUT_METRICS[source_engine])[0]
            try:
                await source.read(
                    KPIInput(source_engine=source_engine, metric=metric),
                    tenant_id=None,
                    period="healthcheck",
                )
            except Exception as exc:
                raise StoreUnavailable(
                    f"executive owner source unavailable: {source_engine}: {exc}"
                ) from exc

    async def _check_section_sources(self) -> None:
        for section, source in sorted(self.section_sources.items()):
            try:
                await source.section_figures(
                    section=section,
                    period="healthcheck",
                    tenant_id=None,
                )
            except Exception as exc:
                raise StoreUnavailable(
                    f"executive section source unavailable: {section}: {exc}"
                ) from exc
