"""Vulnerability persistence protocol and validation helpers (EA-0024 V2)."""

from __future__ import annotations

from typing import Any, Protocol

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import VulnConfigInvalid
from aqelyn.vuln.models import (
    VALID_DISPOSITION_KINDS,
    DispositionKind,
    VulnerabilityRecord,
)


class VulnerabilityStore(Protocol):
    async def put(self, vulnerability: VulnerabilityRecord) -> VulnerabilityRecord: ...

    async def get(
        self, vulnerability_id: str, *, tenant_id: str | None = None
    ) -> VulnerabilityRecord | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        cve_id: str | None = None,
        asset_ref_id: str | None = None,
        disposition: DispositionKind | None = None,
        limit: int = 100,
    ) -> list[VulnerabilityRecord]: ...

    async def history(self, vulnerability_id: str) -> list[dict[str, Any]]: ...


def validate_vulnerability_id(value: str, *, field: str = "vulnerability_id") -> str:
    return require_typed_id(value, "vln", field=field)


def validate_vulnerability(vulnerability: VulnerabilityRecord) -> VulnerabilityRecord:
    return VulnerabilityRecord.model_validate(vulnerability.model_dump(mode="json"))


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_cve_filter(value: str | None) -> str | None:
    if value is None:
        return None
    selected = value.strip()
    if not selected:
        raise VulnConfigInvalid("cve_id filter must not be empty")
    return selected


def validate_asset_ref_filter(value: str | None) -> str | None:
    if value is None:
        return None
    selected = value.strip()
    if not selected:
        raise VulnConfigInvalid("asset_ref_id filter must not be empty")
    return selected


def validate_disposition_filter(value: str | None) -> DispositionKind | None:
    if value is None:
        return None
    if value not in VALID_DISPOSITION_KINDS:
        raise VulnConfigInvalid(f"unknown disposition kind: {value!r}")
    return value  # type: ignore[return-value]


def validate_query_limit(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise VulnConfigInvalid("limit must be >= 1")
    return value
