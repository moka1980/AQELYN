"""ISPM persistence contract and shared validation (EA-0033 G2)."""

from __future__ import annotations

from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ISPMConfigInvalid, TenantScopeRequired
from aqelyn.ispm.models import (
    VALID_IDENTITY_KINDS,
    IdentityBaseline,
    IdentityDriftSnapshot,
    IdentityPostureScore,
    NormalizedIdentity,
    NormalizedIdentityKind,
)
from aqelyn.ispm.scoring import validate_replayable_score


class ISPMStore(Protocol):
    async def upsert_identity(self, identity: NormalizedIdentity) -> NormalizedIdentity: ...

    async def get_identity(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity | None: ...

    async def get_identity_by_external(
        self,
        provider: str,
        external_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity | None: ...

    async def query_identities(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        identity_kind: NormalizedIdentityKind | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[NormalizedIdentity], str | None]: ...

    async def put_score(self, score: IdentityPostureScore) -> IdentityPostureScore: ...

    async def get_score(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityPostureScore | None: ...

    async def put_baseline(self, baseline: IdentityBaseline) -> IdentityBaseline: ...

    async def get_baseline(
        self,
        baseline_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityBaseline | None: ...

    async def put_drift(self, snapshot: IdentityDriftSnapshot) -> IdentityDriftSnapshot: ...

    async def get_drift(
        self,
        snapshot_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityDriftSnapshot | None: ...


def validate_identity(identity: NormalizedIdentity) -> NormalizedIdentity:
    return NormalizedIdentity.model_validate(identity.model_dump(mode="json"))


def validate_score(score: IdentityPostureScore) -> IdentityPostureScore:
    return validate_replayable_score(score)


def validate_baseline(baseline: IdentityBaseline) -> IdentityBaseline:
    return IdentityBaseline.model_validate(baseline.model_dump(mode="json"))


def validate_drift(snapshot: IdentityDriftSnapshot) -> IdentityDriftSnapshot:
    return IdentityDriftSnapshot.model_validate(snapshot.model_dump(mode="json"))


def validate_object_id(value: str, *, field: str = "object_id") -> str:
    return require_typed_id(value, "obj", field=field)


def validate_score_id(value: str) -> str:
    return require_typed_id(value, "ips", field="score_id")


def validate_baseline_id(value: str) -> str:
    return require_typed_id(value, "ibl", field="baseline_id")


def validate_drift_id(value: str) -> str:
    return require_typed_id(value, "idr", field="drift_id")


def validate_provider(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ISPMConfigInvalid("provider must not be empty")
    return value


def validate_external_id(value: str) -> str:
    if not value.strip():
        raise ISPMConfigInvalid("external_id must not be empty")
    return value


def validate_identity_kind(value: str | None) -> NormalizedIdentityKind | None:
    if value is None:
        return None
    if value != "unknown" and value not in VALID_IDENTITY_KINDS:
        raise ISPMConfigInvalid(f"unknown identity kind filter: {value!r}")
    return cast(NormalizedIdentityKind, value)


def validate_tenant_scope(value: str | None, *, mode: str) -> str | None:
    tenant_id = require_tenant_id(value)
    if mode == "enterprise" and tenant_id is None:
        raise TenantScopeRequired("ISPM read must be tenant-scoped")
    return tenant_id


def validate_write_tenant(value: str | None, *, mode: str) -> str | None:
    tenant_id = validate_tenant_scope(value, mode=mode)
    if mode == "local" and tenant_id is not None:
        raise ISPMConfigInvalid("local ISPM store writes require tenant_id=null")
    return tenant_id


def validate_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10_000:
        raise ISPMConfigInvalid("limit must be in [1,10000]")
    return value


def validate_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_object_id(value, field="cursor")
