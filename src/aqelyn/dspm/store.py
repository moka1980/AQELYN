"""DSPM persistence protocol and shared validation (EA-0031 P2)."""

from __future__ import annotations

from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import DSPMConfigInvalid, TenantScopeRequired
from aqelyn.dspm.models import (
    VALID_ASSET_CLASSIFICATION_STATUSES,
    VALID_CLASSIFICATIONS,
    AssetClassificationStatus,
    Classification,
    DataAsset,
    DataExposure,
    DataPostureAssessment,
)


class DSPMStore(Protocol):
    async def put_asset(self, asset: DataAsset) -> DataAsset: ...

    async def get_asset(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAsset | None: ...

    async def get_asset_by_store_id(
        self,
        store_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAsset | None: ...

    async def put_exposure(self, exposure: DataExposure) -> DataExposure: ...

    async def put_assessment(
        self,
        assessment: DataPostureAssessment,
    ) -> DataPostureAssessment: ...

    async def query_assets(
        self,
        *,
        tenant_id: str | None,
        classification: Classification | None = None,
        status: AssetClassificationStatus | None = None,
        flagged: bool | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[DataAsset], str | None]: ...


def validate_asset(asset: DataAsset) -> DataAsset:
    return DataAsset.model_validate(asset.model_dump(mode="json"))


def validate_exposure(exposure: DataExposure) -> DataExposure:
    return DataExposure.model_validate(exposure.model_dump(mode="json"))


def validate_assessment(assessment: DataPostureAssessment) -> DataPostureAssessment:
    return DataPostureAssessment.model_validate(assessment.model_dump(mode="json"))


def validate_asset_id(value: str, *, field: str = "asset_id") -> str:
    return require_typed_id(value, "dsa", field=field)


def validate_store_id(value: str) -> str:
    if not value.strip():
        raise DSPMConfigInvalid("store_id must not be empty")
    return value


def validate_tenant_scope(value: str | None, *, mode: str) -> str | None:
    tenant_id = require_tenant_id(value)
    if mode == "enterprise" and tenant_id is None:
        raise TenantScopeRequired("DSPM read must be tenant-scoped")
    return tenant_id


def validate_classification_filter(value: str | None) -> Classification | None:
    if value is None:
        return None
    if value not in VALID_CLASSIFICATIONS:
        raise DSPMConfigInvalid(f"unknown classification filter: {value!r}")
    return cast(Classification, value)


def validate_status_filter(value: str | None) -> AssetClassificationStatus | None:
    if value is None:
        return None
    if value not in VALID_ASSET_CLASSIFICATION_STATUSES:
        raise DSPMConfigInvalid(f"unknown classification status: {value!r}")
    return cast(AssetClassificationStatus, value)


def validate_query_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10_000:
        raise DSPMConfigInvalid("limit must be in [1,10000]")
    return value


def validate_query_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_asset_id(value, field="cursor")
