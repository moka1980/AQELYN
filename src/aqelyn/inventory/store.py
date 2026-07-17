"""Inventory persistence protocol and validation helpers (EA-0025 N2)."""

from __future__ import annotations

from typing import Any, Protocol

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import InventoryConfigInvalid
from aqelyn.inventory.models import VALID_LIFECYCLE_STATES, AssetRecord, LifecycleState


class AssetStore(Protocol):
    async def put(self, asset: AssetRecord) -> AssetRecord: ...

    async def get(self, asset_id: str, *, tenant_id: str | None = None) -> AssetRecord | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        lifecycle_state: LifecycleState | None = None,
        limit: int = 100,
    ) -> list[AssetRecord]: ...

    async def history(self, asset_id: str) -> list[dict[str, Any]]: ...


def validate_asset_id(value: str, *, field: str = "asset_id") -> str:
    return require_typed_id(value, "ast", field=field)


def validate_asset(asset: AssetRecord) -> AssetRecord:
    return AssetRecord.model_validate(asset.model_dump(mode="json"))


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_lifecycle_filter(value: LifecycleState | None) -> LifecycleState | None:
    if value is None:
        return None
    if value not in VALID_LIFECYCLE_STATES:
        raise InventoryConfigInvalid(f"unknown lifecycle state: {value!r}")
    return value


def validate_query_limit(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise InventoryConfigInvalid("limit must be >= 1")
    return value
