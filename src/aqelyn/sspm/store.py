"""SSPM normalization persistence contract and shared validation (EA-0029 Z2)."""

from __future__ import annotations

from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SaaSConfigInvalid, TenantScopeRequired
from aqelyn.sspm.models import NormalizedSaaSObject, OverScopedStatus, SaaSIntegration

_OVER_SCOPED_STATUSES = frozenset(("over_scoped", "within_scope", "unknown"))


class SaaSNormalizationStore(Protocol):
    async def put(self, obj: NormalizedSaaSObject) -> NormalizedSaaSObject: ...

    async def put_integration(self, integration: SaaSIntegration) -> SaaSIntegration: ...

    async def get(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedSaaSObject | None: ...

    async def get_integration(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> SaaSIntegration | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[NormalizedSaaSObject], str | None]: ...

    async def query_integrations(
        self,
        *,
        tenant_id: str | None,
        over_scoped: OverScopedStatus | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[SaaSIntegration], str | None]: ...


def validate_saas_object(obj: NormalizedSaaSObject) -> NormalizedSaaSObject:
    return NormalizedSaaSObject.model_validate(obj.model_dump(mode="json"))


def validate_saas_integration(integration: SaaSIntegration) -> SaaSIntegration:
    return SaaSIntegration.model_validate(integration.model_dump(mode="json"))


def validate_object_id(value: str) -> str:
    return require_typed_id(value, "obj", field="object_id")


def validate_tenant_scope(value: str | None, *, mode: str) -> str | None:
    tenant_id = require_tenant_id(value)
    if mode == "enterprise" and tenant_id is None:
        raise TenantScopeRequired("SaaS normalization read must be tenant-scoped")
    return tenant_id


def validate_provider_filter(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise SaaSConfigInvalid("provider filter must not be empty")
    return value


def validate_over_scoped_filter(value: str | None) -> OverScopedStatus | None:
    if value is None:
        return None
    if value not in _OVER_SCOPED_STATUSES:
        raise SaaSConfigInvalid(f"unknown over_scoped filter: {value!r}")
    return cast(OverScopedStatus, value)


def validate_query_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10_000:
        raise SaaSConfigInvalid("limit must be in [1,10000]")
    return value


def validate_query_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_object_id(value)
