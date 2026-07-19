"""Supply-chain SBOM ingestion and owner routing (EA-0030 Q2)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from aqelyn.conventions import new_id, parse_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import SBOMParseError, StoreUnavailable
from aqelyn.inventory import AssetRecord, DiscoverySource
from aqelyn.supplychain.models import (
    ComponentConflict,
    ComponentConflictCandidate,
    QuarantinedSBOM,
    SBOMDocument,
    SoftwareComponent,
    SupplyChainConfig,
)
from aqelyn.supplychain.parse import parse_sbom
from aqelyn.supplychain.store import SBOMStore
from aqelyn.trust import SourceReliabilityRegistry


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
        config: SupplyChainConfig | None = None,
    ) -> None:
        self.store = store
        self.inventory = inventory
        self.source_registry = source_registry
        self.config = config or SupplyChainConfig()

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
