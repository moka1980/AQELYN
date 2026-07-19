"""Supply-chain SBOM, dependency, and provenance engine (EA-0030 Q2-Q4)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef, new_id, parse_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import (
    AQError,
    ComponentNotFound,
    ObjectNotFound,
    SBOMParseError,
    StoreUnavailable,
    SupplyChainConfigInvalid,
)
from aqelyn.evidence import EvidenceStore
from aqelyn.graph import KnowledgeGraph, Path
from aqelyn.inventory import AssetRecord, DiscoverySource
from aqelyn.objects import AQObject, AQRelationship, NaturalKey, ObjectStore, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.supplychain.models import (
    ComponentConflict,
    ComponentConflictCandidate,
    DependencyPathResult,
    DependencyRelationship,
    ProvenanceAttestation,
    ProvenanceResult,
    ProvenanceStatus,
    QuarantinedSBOM,
    ReachabilitySignal,
    SBOMDocument,
    SoftwareComponent,
    SupplyChainConfig,
    path_ref,
)
from aqelyn.supplychain.parse import parse_sbom
from aqelyn.supplychain.provenance import ProvenanceVerifier, verify_attestation
from aqelyn.supplychain.store import SBOMStore
from aqelyn.trust import SourceReliabilityRegistry

SOFTWARE_COMPONENT_OBJECT_TYPE = "software_component"
_SUPPLYCHAIN_ACTOR = ActorRef(actor_type="system", actor_id="supplychain_engine")


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


def ensure_supplychain_object_type(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        registry.register(SOFTWARE_COMPONENT_OBJECT_TYPE, 1, None)
        return
    if registry is not None:
        cast(_ObjectStoreRegistry, object_store).registry.register(
            SOFTWARE_COMPONENT_OBJECT_TYPE,
            1,
            None,
        )


class ComponentInventoryOwner(Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...


class SupplyChainEngine:
    def __init__(
        self,
        store: SBOMStore,
        *,
        inventory: ComponentInventoryOwner,
        source_registry: SourceReliabilityRegistry,
        object_store: ObjectStore,
        graph: KnowledgeGraph,
        evidence_store: EvidenceStore,
        provenance_verifier: ProvenanceVerifier | None = None,
        config: SupplyChainConfig | None = None,
    ) -> None:
        self.store = store
        self.inventory = inventory
        self.source_registry = source_registry
        self.object_store = object_store
        self.graph = graph
        self.evidence_store = evidence_store
        self.provenance_verifier = provenance_verifier
        self.config = config or SupplyChainConfig()
        ensure_supplychain_object_type(object_store)

    async def ingest_sbom(
        self,
        doc: SBOMDocument,
        *,
        tenant_id: str | None,
    ) -> list[SoftwareComponent]:
        selected_tenant = require_tenant_id(tenant_id)
        try:
            parsed = parse_sbom(doc, tenant_id=selected_tenant)
            if len(parsed.components) > self.config.batch_size:
                raise SBOMParseError(
                    "SBOM component count exceeds the configured batch_size; "
                    "partial acceptance is forbidden"
                )
        except SBOMParseError as exc:
            await self.store.quarantine(
                QuarantinedSBOM(
                    doc_id=doc.doc_id,
                    tenant_id=selected_tenant,
                    source_id=doc.source_id,
                    observed_at=doc.observed_at,
                    evidence_id=doc.evidence_id,
                    raw=copy.deepcopy(doc.raw),
                    reason=str(exc),
                    quarantined_at=utc_now(),
                )
            )
            raise

        incoming_reliability = (await self.source_registry.get(source_id=doc.source_id)).weight
        stored: list[SoftwareComponent] = []
        for component in parsed.components:
            existing = await self.store.get_component(
                component.purl,
                tenant_id=selected_tenant,
            )
            if existing is None:
                selected = component.model_copy(update={"object_id": new_id("obj")}, deep=True)
            else:
                selected = await self._reconcile(
                    existing,
                    component,
                    incoming_reliability=incoming_reliability,
                )
            stored.append(await self.store.put_component(selected))

        await self._materialize_dependency_graph(
            stored,
            parsed.relationships,
            doc=doc,
            relationship_confidence=incoming_reliability,
        )

        for component in stored:
            reliability = (await self.source_registry.get(source_id=component.source_id)).weight
            assets = await self.inventory.ingest(
                reports=[_inventory_report(component)],
                source=DiscoverySource(
                    source_id=component.source_id,
                    reliability=reliability,
                    health="ok",
                    as_of=component.observed_at,
                ),
                tenant_id=selected_tenant,
            )
            if len(assets) != 1:
                raise StoreUnavailable(
                    "EA-0025 inventory did not accept a parsed software component"
                )
        return [component.model_copy(deep=True) for component in stored]

    async def dependency_paths(
        self,
        purl: str,
        *,
        direction: str,
        tenant_id: str | None,
    ) -> DependencyPathResult:
        selected_tenant = require_tenant_id(tenant_id)
        if direction not in {"up", "down"}:
            raise SupplyChainConfigInvalid("dependency direction must be 'up' or 'down'")
        component = await self.store.get_component(purl, tenant_id=selected_tenant)
        if component is None:
            raise ComponentNotFound(purl)
        result = await self.graph.impact(
            component.object_id,
            direction="in" if direction == "up" else "out",
            relation_types=("depends_on",),
            max_depth=self.config.max_depth,
            max_nodes=self.config.batch_size,
        )
        return DependencyPathResult(
            paths=[hit.via.model_copy(deep=True) for hit in result.hits],
            truncated=result.truncated,
        )

    async def reachability(
        self,
        component_purl: str,
        cve_id: str,
        *,
        tenant_id: str | None,
    ) -> ReachabilitySignal:
        selected_tenant = require_tenant_id(tenant_id)
        try:
            component = await self.store.get_component(component_purl, tenant_id=selected_tenant)
        except AQError as exc:
            if not exc.retriable:
                raise
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason=f"component catalog unavailable: {exc.code}",
            )
        if component is None:
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason="component is not cataloged; reachability was not computed",
            )
        if component.direct:
            return ReachabilitySignal(
                component_purl=component_purl,
                cve_id=cve_id,
                reachable="direct",
                depth=0,
                reason="the SBOM identifies the component as a direct dependency",
            )

        try:
            result = await self.dependency_paths(
                component_purl,
                direction="up",
                tenant_id=selected_tenant,
            )
            direct_paths: list[Path] = []
            for candidate in result.paths:
                if not candidate.node_ids:
                    continue
                ancestor = await self.object_store.get(
                    candidate.node_ids[-1],
                    resolve_merged=False,
                )
                if ancestor is not None and ancestor.attributes.get("direct") is True:
                    direct_paths.append(_forward_dependency_path(candidate))
        except (ObjectNotFound, StoreUnavailable) as exc:
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason=f"reachability owner unavailable: {exc.code}",
            )
        except AQError as exc:
            if not exc.retriable:
                raise
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason=f"reachability owner unavailable: {exc.code}",
            )

        if direct_paths:
            selected_path = min(
                direct_paths,
                key=lambda item: (item.length, item.node_ids, [edge.id for edge in item.edges]),
            )
            return ReachabilitySignal(
                component_purl=component_purl,
                cve_id=cve_id,
                reachable="transitive",
                depth=selected_path.length,
                path_ref=path_ref(selected_path),
                path=selected_path,
                reason=(
                    "an EA-0005 dependency path connects a direct component to the "
                    "vulnerable transitive component"
                ),
            )
        if result.truncated:
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason="EA-0005 traversal was truncated before reachability could be disproved",
            )
        return ReachabilitySignal(
            component_purl=component_purl,
            cve_id=cve_id,
            reachable="unreachable",
            reason="complete EA-0005 traversal found no path from a direct component",
        )

    async def verify_provenance(
        self,
        attestations: Sequence[ProvenanceAttestation],
        *,
        tenant_id: str | None,
    ) -> list[ProvenanceResult]:
        selected_tenant = require_tenant_id(tenant_id)
        if len(attestations) > self.config.batch_size:
            raise SupplyChainConfigInvalid(
                "provenance attestation count exceeds the configured batch_size"
            )

        results: list[ProvenanceResult] = []
        components: dict[str, SoftwareComponent] = {}
        statuses: dict[str, list[ProvenanceStatus]] = {}
        for attestation in attestations:
            component = components.get(attestation.component_purl)
            if component is None:
                component = await self.store.get_component(
                    attestation.component_purl,
                    tenant_id=selected_tenant,
                )
                if component is None:
                    raise ComponentNotFound(attestation.component_purl)
                components[attestation.component_purl] = component
            result = await verify_attestation(
                attestation,
                component=component,
                evidence_store=self.evidence_store,
                verifier=self.provenance_verifier,
                actor=_SUPPLYCHAIN_ACTOR,
            )
            results.append(result)
            statuses.setdefault(component.purl, []).append(result.status)

        for purl in sorted(statuses):
            component = components[purl]
            status = _aggregate_provenance_status(statuses[purl])
            updated = await self.store.put_component(
                component.model_copy(update={"provenance_status": status}, deep=True)
            )
            confidence = (await self.source_registry.get(source_id=updated.source_id)).weight
            stored_object = await self.object_store.upsert(
                _component_object(updated, confidence=confidence)
            )
            if stored_object.id != updated.object_id:
                raise StoreUnavailable(
                    "EA-0002 resolved the component purl to a different object id"
                )
            assets = await self.inventory.ingest(
                reports=[_inventory_report(updated)],
                source=DiscoverySource(
                    source_id=updated.source_id,
                    reliability=confidence,
                    health="ok",
                    as_of=updated.observed_at,
                ),
                tenant_id=selected_tenant,
            )
            if len(assets) != 1:
                raise StoreUnavailable(
                    "EA-0025 inventory did not accept a provenance status update"
                )
        return [result.model_copy(deep=True) for result in results]

    async def _materialize_dependency_graph(
        self,
        components: Sequence[SoftwareComponent],
        relationships: Sequence[DependencyRelationship],
        *,
        doc: SBOMDocument,
        relationship_confidence: float,
    ) -> None:
        by_purl = {component.purl: component for component in components}
        for component in components:
            component_confidence = (
                await self.source_registry.get(source_id=component.source_id)
            ).weight
            stored = await self.object_store.upsert(
                _component_object(component, confidence=component_confidence)
            )
            if stored.id != component.object_id:
                raise StoreUnavailable(
                    "EA-0002 resolved the component purl to a different object id"
                )

        source = SourceRef(
            source_id=doc.source_id,
            evidence_id=doc.evidence_id,
            observed_at=doc.observed_at,
            method="supplychain.sbom_dependency/v1",
        )
        for relationship in relationships:
            from_component = by_purl.get(relationship.from_purl)
            to_component = by_purl.get(relationship.to_purl)
            if from_component is None or to_component is None:
                raise StoreUnavailable("parsed dependency endpoint was not stored")
            existing = await self.object_store.relationships(
                from_component.object_id,
                direction="out",
                relation_type="depends_on",
            )
            if any(item.to_id == to_component.object_id for item in existing):
                continue
            await self.object_store.relate(
                AQRelationship(
                    id=relationship.edge_id,
                    tenant_id=from_component.tenant_id,
                    from_id=from_component.object_id,
                    to_id=to_component.object_id,
                    relation_type="depends_on",
                    attributes={
                        "version_constraint": relationship.version_constraint,
                        "scope": relationship.scope,
                    },
                    sources=[source],
                    confidence=relationship_confidence,
                    created_at=doc.observed_at,
                    updated_at=doc.observed_at,
                    created_by=_SUPPLYCHAIN_ACTOR,
                    updated_by=_SUPPLYCHAIN_ACTOR,
                )
            )

    async def _reconcile(
        self,
        existing: SoftwareComponent,
        incoming: SoftwareComponent,
        *,
        incoming_reliability: float,
    ) -> SoftwareComponent:
        existing_reliability = (await self.source_registry.get(source_id=existing.source_id)).weight
        existing_values = _component_values(existing)
        incoming_values = _component_values(incoming)
        if existing_values == incoming_values:
            winner = max(
                (
                    (existing_reliability, existing.observed_at, existing.source_id, existing),
                    (incoming_reliability, incoming.observed_at, incoming.source_id, incoming),
                ),
                key=lambda item: item[:3],
            )[3]
            return winner.model_copy(
                update={
                    "object_id": existing.object_id,
                    "tenant_id": existing.tenant_id,
                    "conflicts": copy.deepcopy(existing.conflicts),
                },
                deep=True,
            )

        old_candidate = _conflict_candidate(existing, reliability=existing_reliability)
        new_candidate = _conflict_candidate(incoming, reliability=incoming_reliability)
        if existing_reliability != incoming_reliability:
            winner = existing if existing_reliability > incoming_reliability else incoming
            winner_candidate = old_candidate if winner is existing else new_candidate
            conflict = ComponentConflict(
                fields=_changed_fields(existing_values, incoming_values),
                candidates=_sorted_candidates(old_candidate, new_candidate),
                resolved_by=winner_candidate.source_id,
                resolved_evidence_id=winner_candidate.evidence_id,
                unresolved=False,
                reason="higher EA-0006 source reliability",
            )
        else:
            winner = max(
                (existing, incoming),
                key=lambda item: (item.observed_at, item.source_id, item.evidence_id),
            )
            conflict = ComponentConflict(
                fields=_changed_fields(existing_values, incoming_values),
                candidates=_sorted_candidates(old_candidate, new_candidate),
                unresolved=True,
                reason=(
                    "equal EA-0006 source reliability; deterministic value retained "
                    "while the conflict remains unresolved"
                ),
            )
        conflicts = _append_conflict(existing.conflicts, conflict)
        return winner.model_copy(
            update={
                "object_id": existing.object_id,
                "tenant_id": existing.tenant_id,
                "conflicts": conflicts,
            },
            deep=True,
        )


def _component_object(component: SoftwareComponent, *, confidence: float) -> AQObject:
    source = SourceRef(
        source_id=component.source_id,
        evidence_id=component.evidence_id,
        observed_at=component.observed_at,
        method="supplychain.sbom_component/v1",
    )
    return AQObject(
        id=component.object_id,
        object_type=SOFTWARE_COMPONENT_OBJECT_TYPE,
        schema_version=1,
        tenant_id=component.tenant_id,
        display_name=f"{component.name}@{component.version}",
        attributes={
            "purl": component.purl,
            "name": component.name,
            "version": component.version,
            "component_type": component.component_type,
            "licenses": list(component.licenses),
            "supplier": component.supplier,
            "hashes": dict(component.hashes),
            "provenance_status": component.provenance_status,
            "direct": component.direct,
        },
        labels={"module": "EA-0030", "kind": SOFTWARE_COMPONENT_OBJECT_TYPE},
        natural_keys=[NaturalKey(namespace="purl", value=component.purl)],
        sources=[source],
        confidence=confidence,
        first_seen_at=component.observed_at,
        last_seen_at=component.observed_at,
        created_at=component.observed_at,
        updated_at=component.observed_at,
        created_by=_SUPPLYCHAIN_ACTOR,
        updated_by=_SUPPLYCHAIN_ACTOR,
    )


def _forward_dependency_path(path: Path) -> Path:
    return Path(
        node_ids=list(reversed(path.node_ids)),
        edges=list(reversed(path.edges)),
        length=path.length,
    )


def _unknown_reachability(
    component_purl: str,
    cve_id: str,
    *,
    reason: str,
) -> ReachabilitySignal:
    return ReachabilitySignal(
        component_purl=component_purl,
        cve_id=cve_id,
        reason=reason,
    )


def _aggregate_provenance_status(statuses: Sequence[ProvenanceStatus]) -> ProvenanceStatus:
    if "failed" in statuses:
        return "failed"
    if "unverified" in statuses:
        return "unverified"
    return "verified"


def _inventory_report(component: SoftwareComponent) -> dict[str, Any]:
    prefix, payload = parse_id(component.object_id)
    if prefix != "obj":
        raise StoreUnavailable("software component object_id must use obj_ prefix")
    return {
        "id": f"ast_{payload}",
        "asset_type": "software_component",
        "classification": component.component_type,
        "lifecycle_state": "active",
        "evidence_id": component.evidence_id,
        "ref": f"supplychain:{component.purl}",
        "purl": component.purl,
        "name": component.name,
        "version": component.version,
        "licenses": list(component.licenses),
        "supplier": component.supplier,
        "hashes": dict(component.hashes),
        "provenance_status": component.provenance_status,
        "flagged": component.provenance_status != "verified",
        "direct": component.direct,
        "conflicts": [conflict.model_dump(mode="json") for conflict in component.conflicts],
    }


def _component_values(component: SoftwareComponent) -> dict[str, Any]:
    return {
        "name": component.name,
        "version": component.version,
        "component_type": component.component_type,
        "licenses": list(component.licenses),
        "supplier": component.supplier,
        "hashes": dict(component.hashes),
        "direct": component.direct,
    }


def _conflict_candidate(
    component: SoftwareComponent,
    *,
    reliability: float,
) -> ComponentConflictCandidate:
    return ComponentConflictCandidate(
        source_id=component.source_id,
        evidence_id=component.evidence_id,
        observed_at=component.observed_at,
        reliability=reliability,
        values=_component_values(component),
    )


def _sorted_candidates(
    first: ComponentConflictCandidate,
    second: ComponentConflictCandidate,
) -> list[ComponentConflictCandidate]:
    return sorted(
        (first, second),
        key=lambda item: (item.source_id, item.evidence_id),
    )


def _changed_fields(first: Mapping[str, Any], second: Mapping[str, Any]) -> list[str]:
    return sorted(key for key in first if first[key] != second[key])


def _append_conflict(
    existing: Sequence[ComponentConflict],
    conflict: ComponentConflict,
) -> list[ComponentConflict]:
    serialized = conflict.model_dump(mode="json")
    if any(item.model_dump(mode="json") == serialized for item in existing):
        return [item.model_copy(deep=True) for item in existing]
    return [*[item.model_copy(deep=True) for item in existing], conflict]
