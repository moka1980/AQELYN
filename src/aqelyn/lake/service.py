"""Security Data Lake AQService wrapper and events (EA-0019 L5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import BlobStore, EvidenceStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.lake.models import LakeConfig
from aqelyn.lake.retention import RetentionEngine, WorkflowProposer
from aqelyn.lake.store import DatasetCatalogStore, TelemetryRecordStore
from aqelyn.policy.service import PolicyEngineService

LAKE_EVENTS: dict[str, int] = {
    "aqelyn.telemetry.ingested": 1,
    "aqelyn.telemetry.quarantined": 1,
    "aqelyn.lake.retention_applied": 1,
    "aqelyn.lake.archived": 1,
}


def register_lake_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in LAKE_EVENTS.items():
        registry.register(event_type, schema_version, None)


class DataLakeService:
    def __init__(
        self,
        *,
        catalog: DatasetCatalogStore,
        record_store: TelemetryRecordStore,
        retention_engine: RetentionEngine,
        blob_store: BlobStore,
        audit_store: EvidenceStore,
        policy_authorizer: PolicyEngineService,
        workflow_engine: WorkflowProposer,
        config: LakeConfig | None = None,
        close_catalog: Callable[[], Awaitable[None]] | None = None,
        close_record_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = ("event_bus", "policy_engine", "workflow_engine"),
        critical: bool = True,
    ) -> None:
        self.catalog = catalog
        self.record_store = record_store
        self.retention_engine = retention_engine
        self.blob_store = blob_store
        self.audit_store = audit_store
        self.policy_authorizer = policy_authorizer
        self.workflow_engine = workflow_engine
        self.config = config or LakeConfig()
        self._close_catalog = close_catalog
        self._close_record_store = close_record_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "datalake_engine"

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
            if self._close_record_store is not None:
                await self._close_record_store()
            if self._close_catalog is not None:
                await self._close_catalog()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_catalog()
            dependencies["catalog"] = "healthy"
            await self._check_record_store()
            dependencies["record_store"] = "healthy"
            self._check_blob_store()
            dependencies["blob_store"] = "healthy"
            await self._check_audit_store()
            dependencies["audit_store"] = "healthy"
            self._check_retention_engine()
            dependencies["retention_engine"] = "healthy"
            self._check_policy_engine()
            dependencies["policy_engine"] = "healthy"
            self._check_workflow_engine()
            dependencies["workflow_engine"] = "healthy"
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

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_catalog()
        await self._check_record_store()
        self._check_blob_store()
        await self._check_audit_store()
        self._check_retention_engine()
        self._check_policy_engine()
        self._check_workflow_engine()

    def _check_config(self) -> None:
        LakeConfig.model_validate(self.config.model_dump(mode="json"))

    async def _check_catalog(self) -> None:
        try:
            await self.catalog.list(tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"lake catalog unavailable: {exc}") from exc

    async def _check_record_store(self) -> None:
        try:
            await self.record_store.get(new_id("tlm"), tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"lake record store unavailable: {exc}") from exc

    def _check_blob_store(self) -> None:
        if self.blob_store is None:
            raise StoreUnavailable("lake blob store unavailable")

    async def _check_audit_store(self) -> None:
        verifier = getattr(self.audit_store, "verify", None)
        if not callable(verifier):
            raise StoreUnavailable("lake audit store unavailable")
        try:
            await verifier(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"lake audit store unavailable: {exc}") from exc

    def _check_retention_engine(self) -> None:
        if self.retention_engine is None:
            raise StoreUnavailable("lake retention engine unavailable")

    def _check_policy_engine(self) -> None:
        if self.policy_authorizer is None:
            raise StoreUnavailable("lake policy engine unavailable")

    def _check_workflow_engine(self) -> None:
        if self.workflow_engine is None:
            raise StoreUnavailable("lake workflow engine unavailable")
