"""Security Data Lake intake helpers (EA-0019 L2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from aqelyn.conventions import canonical_json, utc_now
from aqelyn.conventions.errors import LakeConfigInvalid
from aqelyn.evidence import BlobRef, BlobStore
from aqelyn.lake.models import Dataset, Quarantine, SchemaType, TelemetryRecord
from aqelyn.lake.store import DatasetCatalogStore, TelemetryRecordStore, validate_tenant


class IngestResult:
    def __init__(self, *, accepted: list[TelemetryRecord], quarantined: list[Quarantine]) -> None:
        self.accepted = accepted
        self.quarantined = quarantined

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def quarantined_count(self) -> int:
        return len(self.quarantined)


async def ingest(
    records: Sequence[TelemetryRecord],
    *,
    catalog: DatasetCatalogStore,
    store: TelemetryRecordStore,
    blob_store: BlobStore,
    tenant_id: str | None,
) -> IngestResult:
    tenant_id = validate_tenant(tenant_id)
    accepted: list[TelemetryRecord] = []
    quarantined: list[Quarantine] = []
    for record in records:
        raw_ref = record.raw_ref or await _write_raw(record, blob_store)
        try:
            normalized = await _normalize_record(record, catalog=catalog, tenant_id=tenant_id)
        except LakeConfigInvalid as exc:
            quarantined.append(
                await store.quarantine(
                    Quarantine(
                        source_id=record.source_id,
                        reason=exc.message,
                        received_at=utc_now(),
                        raw_ref=raw_ref,
                    ),
                    tenant_id=tenant_id,
                )
            )
            continue
        stored = await store.append(normalized.model_copy(update={"raw_ref": raw_ref}, deep=True))
        accepted.append(stored)
    return IngestResult(accepted=accepted, quarantined=quarantined)


async def _write_raw(record: TelemetryRecord, blob_store: BlobStore) -> BlobRef:
    return await blob_store.put(
        canonical_json(record.model_dump(mode="json")),
        media_type="application/json",
    )


async def _normalize_record(
    record: TelemetryRecord,
    *,
    catalog: DatasetCatalogStore,
    tenant_id: str | None,
) -> TelemetryRecord:
    if tenant_id != record.tenant_id:
        raise LakeConfigInvalid("record tenant_id must match intake tenant_id")
    dataset = await catalog.get(record.dataset, tenant_id=tenant_id)
    if dataset is None:
        raise LakeConfigInvalid(f"unknown dataset: {record.dataset}")
    normalized = _normalize_fields(record.fields, dataset)
    return TelemetryRecord.model_validate(
        record.model_copy(update={"fields": normalized}, deep=True).model_dump(mode="json")
    )


def _normalize_fields(fields: Mapping[str, Any], dataset: Dataset) -> dict[str, Any]:
    expected = set(dataset.schema_)
    actual = set(fields)
    missing = sorted(expected - actual)
    if missing:
        raise LakeConfigInvalid(f"missing fields: {', '.join(missing)}")
    extra = sorted(actual - expected)
    if extra:
        raise LakeConfigInvalid(f"unknown fields: {', '.join(extra)}")
    return {
        field: _normalize_value(fields[field], schema_type, field=field)
        for field, schema_type in dataset.schema_.items()
    }


def _normalize_value(value: Any, schema_type: SchemaType, *, field: str) -> Any:
    if schema_type == "string":
        if isinstance(value, str):
            return value
        raise LakeConfigInvalid(f"{field} must be a string")
    if schema_type == "int":
        return _int_value(value, field=field)
    if schema_type == "float":
        return _float_value(value, field=field)
    if schema_type == "bool":
        return _bool_value(value, field=field)
    if schema_type == "datetime":
        return _datetime_value(value, field=field)
    return value


def _int_value(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise LakeConfigInvalid(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise LakeConfigInvalid(f"{field} must be an integer") from exc
    raise LakeConfigInvalid(f"{field} must be an integer")


def _float_value(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise LakeConfigInvalid(f"{field} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise LakeConfigInvalid(f"{field} must be a number") from exc
    raise LakeConfigInvalid(f"{field} must be a number")


def _bool_value(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise LakeConfigInvalid(f"{field} must be a boolean")


def _datetime_value(value: Any, *, field: str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise LakeConfigInvalid(f"{field} must be timezone-aware")
        return value.isoformat()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LakeConfigInvalid(f"{field} must be an ISO datetime") from exc
        if parsed.tzinfo is None:
            raise LakeConfigInvalid(f"{field} must be timezone-aware")
        return parsed.isoformat()
    raise LakeConfigInvalid(f"{field} must be an ISO datetime")
