"""Inventory AQService wrapper and events (EA-0025 N5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    AssetNotFound,
    EvidenceNotFound,
    InventoryConfigInvalid,
    ObjectNotFound,
    StoreUnavailable,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.inventory.engine import InventoryIntelligenceEngine
from aqelyn.inventory.models import (
    AssetRecord,
    AssetRelationship,
    DiscoverySource,
    InventoryConfig,
    InventoryReport,
    Ownership,
)
from aqelyn.inventory.store import AssetStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects.store import ObjectStore
from aqelyn.trust.models import TrustConfig

INVENTORY_EVENTS: dict[str, int] = {
    "aqelyn.inventory.asset_discovered": 1,
    "aqelyn.inventory.asset_reconciled": 1,
    "aqelyn.inventory.asset_unreported": 1,
    "aqelyn.inventory.lifecycle_changed": 1,
    "aqelyn.inventory.relationship_updated": 1,
}


def register_inventory_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in INVENTORY_EVENTS.items():
        registry.register(event_type, schema_version, None)


class InventoryIntelligenceService:
    def __init__(
        self,
        engine: InventoryIntelligenceEngine,
        *,
        store: AssetStore,
        object_store: ObjectStore | None = None,
        trust_engine: object | None = None,
        mission_engine: object | None = None,
        evidence_store: object | None = None,
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "acg_engine",
            "object_store",
            "knowledge_graph",
            "trust_engine",
            "mission_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.store = store
        self.object_store = object_store
        self.trust_engine = trust_engine
        self.mission_engine = mission_engine
        self.evidence_store = evidence_store
        self._close_store = close_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "inventory_engine"

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
            if self._close_store is not None:
                await self._close_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_store()
            dependencies["asset_store"] = "healthy"
            await self._check_classifier()
            dependencies["acg_engine"] = "healthy"
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_graph()
            dependencies["knowledge_graph"] = "healthy"
            await self._check_trust_engine()
            dependencies["trust_engine"] = "healthy"
            await self._check_mission_engine()
            dependencies["mission_engine"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
        except InventoryConfigInvalid as exc:
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

    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, object]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]:
        return await self.engine.ingest(reports=reports, source=source, tenant_id=tenant_id)

    async def reconcile(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord:
        return await self.engine.reconcile(asset_id, tenant_id=tenant_id)

    async def inventory(self, *, tenant_id: str | None) -> InventoryReport:
        return await self.engine.inventory(tenant_id=tenant_id)

    async def classify(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord:
        return await self.engine.classify(asset_id, tenant_id=tenant_id)

    async def ownership(self, asset_id: str, *, tenant_id: str | None) -> Ownership | None:
        return await self.engine.ownership(asset_id, tenant_id=tenant_id)

    async def infer_relationships(
        self, asset_id: str, *, tenant_id: str | None
    ) -> list[AssetRelationship]:
        return await self.engine.infer_relationships(asset_id, tenant_id=tenant_id)

    async def mark_unreported(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord:
        return await self.engine.mark_unreported(asset_id, tenant_id=tenant_id)

    async def sweep_unreported(
        self, *, source: DiscoverySource, tenant_id: str | None
    ) -> list[AssetRecord]:
        return await self.engine.sweep_unreported(source=source, tenant_id=tenant_id)

    async def decommission(
        self,
        asset_id: str,
        *,
        by: ActorRef,
        evidence_id: str | None,
        tenant_id: str | None,
        decision_ref: str | None = None,
    ) -> AssetRecord:
        return await self.engine.decommission(
            asset_id,
            by=by,
            evidence_id=evidence_id,
            tenant_id=tenant_id,
            decision_ref=decision_ref,
        )

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_store()
        await self._check_classifier()
        await self._check_object_store()
        await self._check_graph()
        await self._check_trust_engine()
        await self._check_mission_engine()
        await self._check_evidence_store()

    def _check_config(self) -> None:
        InventoryConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self.store.get(new_id("ast"), tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"inventory asset store unavailable: {exc}") from exc

    async def _check_classifier(self) -> None:
        classifier = self.engine.classifier
        if classifier is None:
            raise StoreUnavailable("inventory classifier unavailable")
        try:
            await classifier.classify(new_id("obj"), tenant_id=None)
        except ObjectNotFound:
            return
        except AssetNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"inventory classifier unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        if self.object_store is None:
            raise StoreUnavailable("inventory object store unavailable")
        try:
            await self.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"inventory object store unavailable: {exc}") from exc

    async def _check_graph(self) -> None:
        if self.engine.graph is None:
            raise StoreUnavailable("inventory knowledge graph unavailable")
        try:
            await self.engine.graph.paths(
                new_id("obj"),
                new_id("obj"),
                direction="out",
                max_paths=1,
                max_work=1,
            )
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"inventory knowledge graph unavailable: {exc}") from exc

    async def _check_trust_engine(self) -> None:
        if self.trust_engine is None:
            raise StoreUnavailable("inventory trust engine unavailable")
        config = getattr(self.trust_engine, "config", None)
        registry = getattr(self.trust_engine, "registry", None)
        try:
            if config is not None:
                TrustConfig.model_validate(config.model_dump(mode="json"))
            if registry is not None:
                await registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"inventory trust engine unavailable: {exc}") from exc

    async def _check_mission_engine(self) -> None:
        if self.mission_engine is None:
            raise StoreUnavailable("inventory mission engine unavailable")
        mission_impact = getattr(self.mission_engine, "mission_impact", None)
        if not callable(mission_impact):
            raise StoreUnavailable("inventory mission engine unavailable")
        try:
            await mission_impact(new_id("obj"))
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"inventory mission engine unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        if self.evidence_store is None:
            raise StoreUnavailable("inventory evidence store unavailable")
        verify = getattr(self.evidence_store, "verify", None)
        if not callable(verify):
            raise StoreUnavailable("inventory evidence store unavailable")
        try:
            await verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except KeyError:
            return
        except Exception as exc:
            raise StoreUnavailable(f"inventory evidence store unavailable: {exc}") from exc
