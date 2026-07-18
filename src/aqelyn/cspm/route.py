"""Typed CSPM owner-routing boundaries and concrete inventory adapter (Y3)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from aqelyn.conventions import parse_id
from aqelyn.conventions.errors import CloudConfigInvalid
from aqelyn.cspm.models import CloudRouteEnvelope, RouteOwner
from aqelyn.inventory.models import AssetRecord, DiscoverySource


class CloudOwnerRouter(Protocol):
    """Translate one complete cloud envelope into an existing owner's contract."""

    owner: RouteOwner

    async def route(
        self,
        envelope: CloudRouteEnvelope,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]: ...


class CloudBaselineRouter(Protocol):
    """Delegate configured cloud baselines to EA-0012 without evaluating them here."""

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


class InventoryCloudOwnerRouter:
    """Route cloud resources into EA-0025's existing ingest/lifecycle API."""

    owner: RouteOwner = "inventory"

    def __init__(self, inventory: InventoryRoutingOwner) -> None:
        self.inventory = inventory

    async def route(
        self,
        envelope: CloudRouteEnvelope,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]:
        asset_id = cloud_asset_id(envelope.normalized.object_id)
        if envelope.change_kind == "reported_deleted":
            asset = await self.inventory.mark_unreported(asset_id, tenant_id=tenant_id)
            return [asset.id]

        reports = [_inventory_report(envelope, asset_id=asset_id)]
        source = DiscoverySource(
            source_id=envelope.source_id,
            reliability=envelope.source_reliability,
            health="ok",
            as_of=envelope.observed_at,
        )
        assets = await self.inventory.ingest(
            reports=reports,
            source=source,
            tenant_id=tenant_id,
        )
        if not assets:
            raise CloudConfigInvalid("inventory route returned no asset reference")
        return [asset.id for asset in assets]


def cloud_asset_id(object_id: str) -> str:
    prefix, payload = parse_id(object_id)
    if prefix != "obj":
        raise CloudConfigInvalid("cloud route object_id must use obj_ prefix")
    return f"ast_{payload}"


def _inventory_report(envelope: CloudRouteEnvelope, *, asset_id: str) -> dict[str, Any]:
    obj = envelope.normalized
    return {
        "id": asset_id,
        "asset_type": obj.object_type,
        "classification": obj.object_type,
        "lifecycle_state": "active",
        "evidence_id": obj.evidence_id,
        "ref": f"cspm:{obj.object_id}",
        "cloud_object_id": obj.object_id,
        "native_facts": copy.deepcopy(obj.native_facts),
        "field_provenance": dict(obj.field_provenance),
        "unreported_facts": {
            field: state.model_dump(mode="json")
            for field, state in sorted(obj.unreported_facts.items())
        },
        "flagged": obj.flagged,
    }
