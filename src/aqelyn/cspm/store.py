"""CSPM normalization persistence contract and shared validation (EA-0028 Y2)."""

from __future__ import annotations

from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import CloudConfigInvalid, TenantScopeRequired
from aqelyn.cspm.models import NormalizedCloudObject, Provider

_PROVIDERS = frozenset(("aws", "azure", "gcp", "oci", "other"))


class CloudNormalizationStore(Protocol):
    async def put(self, obj: NormalizedCloudObject) -> NormalizedCloudObject: ...

    async def get(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedCloudObject | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[NormalizedCloudObject], str | None]: ...


def validate_cloud_object(obj: NormalizedCloudObject) -> NormalizedCloudObject:
    return NormalizedCloudObject.model_validate(obj.model_dump(mode="json"))


def validate_cloud_object_id(value: str) -> str:
    return require_typed_id(value, "obj", field="object_id")


def validate_tenant_scope(value: str | None, *, mode: str) -> str | None:
    tenant_id = require_tenant_id(value)
    if mode == "enterprise" and tenant_id is None:
        raise TenantScopeRequired("cloud normalization read must be tenant-scoped")
    return tenant_id


def validate_provider_filter(value: str | None) -> Provider | None:
    if value is None:
        return None
    if value not in _PROVIDERS:
        raise CloudConfigInvalid(f"unknown cloud provider: {value!r}")
    return cast(Provider, value)


def validate_query_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10_000:
        raise CloudConfigInvalid("limit must be in [1,10000]")
    return value


def validate_query_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_cloud_object_id(value)
