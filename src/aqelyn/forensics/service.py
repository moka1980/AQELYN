"""Digital Forensics AQService wrapper and events (EA-0016 F5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import EvidenceNotFound, ObjectNotFound, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import BlobStore, EvidenceStore
from aqelyn.findings import FindingStore
from aqelyn.forensics.acquire import catalog_artifact as _catalog_artifact
from aqelyn.forensics.acquire import register_acquisition as _register_acquisition
from aqelyn.forensics.engine import findings_from_artifacts as _findings_from_artifacts
from aqelyn.forensics.engine import link_to_assets as _link_to_assets
from aqelyn.forensics.engine import package_case as _package_case
from aqelyn.forensics.models import (
    Acquisition,
    Artifact,
    ForensicsConfig,
    ForensicTimeline,
    TimelineEvent,
    VerifyReport,
)
from aqelyn.forensics.store import ArtifactStore
from aqelyn.forensics.timeline import build_timeline as _build_timeline
from aqelyn.forensics.timeline import explain as _explain
from aqelyn.forensics.timeline import verify_artifact as _verify_artifact
from aqelyn.forensics.timeline import verify_case as _verify_case
from aqelyn.graph import KnowledgeGraph
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects import ObjectStore

FORENSICS_EVENTS: dict[str, int] = {
    "aqelyn.forensics.artifact_cataloged": 1,
    "aqelyn.forensics.evidence_verified": 1,
    "aqelyn.forensics.case_packaged": 1,
}


def register_forensics_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in FORENSICS_EVENTS.items():
        registry.register(event_type, schema_version, None)


class DigitalForensicsService:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        evidence_store: EvidenceStore,
        blob_store: BlobStore,
        object_store: ObjectStore,
        graph: KnowledgeGraph,
        finding_store: FindingStore,
        config: ForensicsConfig | None = None,
        close_artifact_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = ("object_store", "knowledge_graph", "soc_engine"),
        critical: bool = True,
    ) -> None:
        self.artifact_store = artifact_store
        self.evidence_store = evidence_store
        self.blob_store = blob_store
        self.object_store = object_store
        self.graph = graph
        self.finding_store = finding_store
        self.config = config or ForensicsConfig()
        self._close_artifact_store = close_artifact_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "forensics_engine"

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
            if self._close_artifact_store is not None:
                await self._close_artifact_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_artifact_store()
            dependencies["artifact_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_knowledge_graph()
            dependencies["knowledge_graph"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
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

    async def register_acquisition(
        self,
        acquisition: Acquisition,
        *,
        content: bytes,
        by: ActorRef,
        media_type: str = "application/octet-stream",
    ) -> Acquisition:
        return await _register_acquisition(
            acquisition,
            content=content,
            blob_store=self.blob_store,
            evidence_store=self.evidence_store,
            by=by,
            media_type=media_type,
        )

    async def catalog_artifact(
        self,
        acquisition: Acquisition,
        *,
        artifact_type: str,
        metadata: dict[str, object],
        by: ActorRef,
    ) -> Artifact:
        artifact = await _catalog_artifact(
            acquisition,
            artifact_type=artifact_type,
            metadata=metadata,
            object_store=self.object_store,
            evidence_store=self.evidence_store,
            by=by,
        )
        return await self.artifact_store.put(artifact)

    async def build_timeline(
        self,
        *,
        tenant_id: str | None,
        case_id: str | None = None,
        artifact_ids: Sequence[str] = (),
        limit: int = 100,
    ) -> ForensicTimeline:
        return await _build_timeline(
            artifact_store=self.artifact_store,
            tenant_id=tenant_id,
            case_id=case_id,
            artifact_ids=artifact_ids,
            limit=limit,
        )

    async def verify_artifact(self, artifact_id: str) -> VerifyReport:
        return await _verify_artifact(
            artifact_id,
            artifact_store=self.artifact_store,
            evidence_store=self.evidence_store,
        )

    async def verify_case(self, case_id: str, *, tenant_id: str | None) -> VerifyReport:
        return await _verify_case(
            case_id,
            tenant_id=tenant_id,
            artifact_store=self.artifact_store,
            evidence_store=self.evidence_store,
        )

    async def link_to_assets(
        self,
        artifact_id: str,
        *,
        relation_types: Sequence[str] | None = None,
        max_depth: int = 2,
        max_nodes: int = 1_000,
    ) -> list[str]:
        return await _link_to_assets(
            artifact_id,
            artifact_store=self.artifact_store,
            graph=self.graph,
            relation_types=relation_types,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )

    async def package_case(
        self,
        case_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        reason: str,
    ) -> str:
        return await _package_case(
            case_id,
            tenant_id=tenant_id,
            artifact_store=self.artifact_store,
            evidence_store=self.evidence_store,
            by=by,
            reason=reason,
        )

    async def findings_from_artifacts(
        self,
        artifact_ids: Sequence[str],
        *,
        by: ActorRef,
    ) -> list[str]:
        return await _findings_from_artifacts(
            artifact_ids,
            artifact_store=self.artifact_store,
            finding_store=self.finding_store,
            by=by,
            graph=self.graph,
        )

    def explain(self, event: TimelineEvent) -> dict[str, Any]:
        return _explain(event)

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_artifact_store()
        await self._check_evidence_store()
        await self._check_object_store()
        await self._check_knowledge_graph()
        await self._check_finding_store()

    def _check_config(self) -> None:
        ForensicsConfig.model_validate(self.config.model_dump(mode="json"))

    async def _check_artifact_store(self) -> None:
        try:
            await self.artifact_store.get(new_id("art"))
        except Exception as exc:
            raise StoreUnavailable(f"forensics artifact store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"forensics evidence store unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        try:
            await self.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"forensics object store unavailable: {exc}") from exc

    async def _check_knowledge_graph(self) -> None:
        try:
            await self.graph.correlate([new_id("obj")], within_hops=1, max_nodes=1)
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"forensics knowledge graph unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        try:
            await self.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"forensics finding store unavailable: {exc}") from exc
