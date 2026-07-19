"""Typed SSPM owner-routing boundary (EA-0029 Z2)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, parse_id
from aqelyn.conventions.errors import SaaSConfigInvalid
from aqelyn.evidence import EvidenceStore
from aqelyn.inventory import AssetRecord, DiscoverySource
from aqelyn.objects import ObjectStore
from aqelyn.sspm.models import NormalizedSaaSObject, SaaSRouteOwner
from aqelyn.trust import SourceReliabilityRegistry


class SaaSOwnerRouter(Protocol):
    owner: SaaSRouteOwner

    async def route(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]: ...


class SaaSBaselineRouter(Protocol):
    async def apply(
        self,
        baseline_ids: Sequence[str],
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> str: ...


class InventoryRoutingOwner(Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...

    async def mark_unreported(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> AssetRecord: ...


class SaaSAbsenceRouter(Protocol):
    async def mark_unreported(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> str: ...


class InventorySaaSOwnerRouter:
    """Route normalized SaaS apps into EA-0025's ingest and lifecycle contracts."""

    owner: SaaSRouteOwner = "inventory"

    def __init__(
        self,
        inventory: InventoryRoutingOwner,
        *,
        evidence_store: EvidenceStore,
        source_registry: SourceReliabilityRegistry,
        actor: ActorRef,
    ) -> None:
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.source_registry = source_registry
        self.actor = actor

    async def route(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]:
        evidence = await self.evidence_store.get(obj.evidence_id, actor=self.actor)
        if evidence.tenant_id != tenant_id or obj.object_id not in evidence.subject.object_ids:
            raise SaaSConfigInvalid("SaaS inventory evidence does not match routed object")
        reliability = (
            await self.source_registry.get(
                source_id=evidence.source_id,
                method=evidence.method,
            )
        ).weight
        source = DiscoverySource(
            source_id=evidence.source_id,
            reliability=reliability,
            health="ok",
            as_of=evidence.collected_at,
        )
        assets = await self.inventory.ingest(
            reports=[_inventory_report(obj, asset_id=saas_asset_id(obj.object_id))],
            source=source,
            tenant_id=tenant_id,
        )
        if not assets:
            raise SaaSConfigInvalid("inventory route returned no asset reference")
        return [asset.id for asset in assets]

    async def mark_unreported(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> str:
        asset = await self.inventory.mark_unreported(
            saas_asset_id(obj.object_id),
            tenant_id=tenant_id,
        )
        return asset.id


class SharedObjectSaaSOwnerRouter:
    """Verify an existing owner can read the complete shared SaaS object."""

    def __init__(self, owner: SaaSRouteOwner, object_store: ObjectStore) -> None:
        if owner == "inventory":
            raise SaaSConfigInvalid("inventory requires InventorySaaSOwnerRouter")
        self.owner: SaaSRouteOwner = owner
        self.object_store = object_store

    async def route(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]:
        shared = await self.object_store.get(obj.object_id, resolve_merged=False)
        if shared is None:
            raise SaaSConfigInvalid(f"{self.owner} route object is unavailable")
        if shared.tenant_id != tenant_id:
            raise SaaSConfigInvalid(f"{self.owner} route object tenant does not match")
        expected = {
            "native_facts": obj.native_facts,
            "field_provenance": obj.field_provenance,
            "conflicts": obj.conflicts,
            "flagged": obj.flagged,
        }
        for field, value in expected.items():
            if shared.attributes.get(field) != value:
                raise SaaSConfigInvalid(f"{self.owner} route object does not preserve {field}")
        return [shared.id]


def saas_asset_id(object_id: str) -> str:
    prefix, payload = parse_id(object_id)
    if prefix != "obj":
        raise SaaSConfigInvalid("SaaS route object_id must use obj_ prefix")
    return f"ast_{payload}"


def _inventory_report(obj: NormalizedSaaSObject, *, asset_id: str) -> dict[str, Any]:
    return {
        "id": asset_id,
        "asset_type": obj.object_type,
        "classification": obj.object_type,
        "lifecycle_state": "active",
        "evidence_id": obj.evidence_id,
        "ref": f"sspm:{obj.object_id}",
        "saas_object_id": obj.object_id,
        "native_facts": copy.deepcopy(obj.native_facts),
        "field_provenance": dict(obj.field_provenance),
        "flagged": obj.flagged,
    }
