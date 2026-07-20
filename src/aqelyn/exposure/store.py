"""Exposure persistence protocol and validation helpers (EA-0023 E2)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ExposureConfigInvalid
from aqelyn.exposure.models import VALID_REACHABILITY, ExposureRecord, Reachability


class ExposureStore(Protocol):
    async def put(self, exposure: ExposureRecord) -> ExposureRecord: ...

    async def get(
        self, exposure_id: str, *, tenant_id: str | None = None
    ) -> ExposureRecord | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        reachability: Reachability | None = None,
        flagged: bool | None = None,
        limit: int = 100,
    ) -> list[ExposureRecord]: ...


def validate_exposure_id(value: str, *, field: str = "exposure_id") -> str:
    return require_typed_id(value, "exp", field=field)


def validate_exposure(exposure: ExposureRecord) -> ExposureRecord:
    stored = ExposureRecord.model_validate(exposure.model_dump(mode="json"))
    if stored.score is not None:
        # Keep persistence as a validity gate without introducing a module import cycle.
        from aqelyn.exposure.engine import validate_replayable_exposure

        return validate_replayable_exposure(stored)
    return stored


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_reachability_filter(value: Reachability | None) -> Reachability | None:
    if value is None:
        return None
    if value not in VALID_REACHABILITY:
        raise ExposureConfigInvalid(f"unknown reachability: {value!r}")
    return value


def validate_flagged_filter(value: bool | None) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise ExposureConfigInvalid("flagged filter must be a boolean")


def validate_query_limit(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise ExposureConfigInvalid("limit must be >= 1")
    return value
