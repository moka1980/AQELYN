"""Security Data Lake store protocols and validators (EA-0019 L2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import LakeConfigInvalid
from aqelyn.lake.models import (
    ArchiveRecord,
    Dataset,
    Quarantine,
    RetentionState,
    TelemetryRecord,
)
from aqelyn.policy import Condition


class DatasetCatalogStore(Protocol):
    async def register(self, dataset: Dataset) -> Dataset: ...
    async def get(self, name: str, *, tenant_id: str | None) -> Dataset | None: ...
    async def list(self, *, tenant_id: str | None) -> list[Dataset]: ...


class TelemetryRecordStore(Protocol):
    async def append(self, record: TelemetryRecord) -> TelemetryRecord: ...

    async def update(self, record: TelemetryRecord) -> TelemetryRecord: ...

    async def get(
        self,
        record_id: str,
        *,
        tenant_id: str | None = None,
    ) -> TelemetryRecord | None: ...

    async def query(
        self,
        *,
        dataset: str,
        tenant_id: str | None,
        limit: int = 100,
        retention_state: Sequence[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        filter: Condition | None = None,
    ) -> list[TelemetryRecord]: ...

    async def count(
        self,
        *,
        dataset: str,
        tenant_id: str | None,
        retention_state: Sequence[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        filter: Condition | None = None,
    ) -> int: ...

    async def quarantine(self, item: Quarantine, *, tenant_id: str | None) -> Quarantine: ...

    async def list_quarantine(
        self,
        *,
        tenant_id: str | None,
        limit: int = 100,
    ) -> list[Quarantine]: ...

    async def put_archive(self, archive: ArchiveRecord) -> ArchiveRecord: ...

    async def get_archive(
        self,
        archive_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ArchiveRecord | None: ...


def validate_dataset(dataset: Dataset) -> Dataset:
    return Dataset.model_validate(dataset.model_dump(mode="json", by_alias=True))


def validate_record(record: TelemetryRecord) -> TelemetryRecord:
    return TelemetryRecord.model_validate(record.model_dump(mode="json"))


def validate_quarantine(item: Quarantine) -> Quarantine:
    return Quarantine.model_validate(item.model_dump(mode="json"))


def validate_archive(archive: ArchiveRecord) -> ArchiveRecord:
    return ArchiveRecord.model_validate(archive.model_dump(mode="json"))


def validate_record_id(
    value: str,
    *,
    field: str = "record_id",
    allow_empty: bool = False,
) -> str:
    return require_typed_id(value, "tlm", field=field, allow_empty=allow_empty)


def validate_archive_id(
    value: str,
    *,
    field: str = "archive_id",
    allow_empty: bool = False,
) -> str:
    return require_typed_id(value, "arc", field=field, allow_empty=allow_empty)


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_dataset_name(value: str, *, field: str = "dataset") -> str:
    if not value.strip():
        raise LakeConfigInvalid(f"{field} must not be empty")
    return value


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise LakeConfigInvalid(f"{field} must be >= 1")
    return value


def normalize_retention_state_filter(
    states: Sequence[str] | None,
) -> tuple[RetentionState, ...] | None:
    if states is None:
        return None
    valid: set[str] = {"active", "archived", "expired"}
    out: list[RetentionState] = []
    for state in states:
        if state not in valid:
            raise LakeConfigInvalid(f"unknown retention_state: {state!r}")
        out.append(cast(RetentionState, state))
    return tuple(out)
