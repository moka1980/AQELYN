"""Inventory reference engine for handed-in ingest and reconciliation (EA-0025 N2)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aqelyn.conventions import new_id, require_tenant_id
from aqelyn.conventions.errors import AssetNotFound, InventoryConfigInvalid
from aqelyn.inventory.models import (
    AssetBasis,
    AssetRecord,
    ConflictCandidate,
    DiscoverySource,
    FieldConflict,
    InventoryConfig,
    Ownership,
)
from aqelyn.inventory.store import AssetStore, validate_asset_id

_RECONCILED_FIELDS = ("asset_type", "classification", "owner")


@dataclass(frozen=True)
class _Resolution:
    field: str
    conflict: FieldConflict | None
    value: Any
    resolved: bool


class InventoryIntelligenceEngine:
    def __init__(self, store: AssetStore, *, config: InventoryConfig | None = None) -> None:
        self.store = store
        self.config = config or InventoryConfig()

    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]:
        selected_tenant = require_tenant_id(tenant_id)
        stored: list[AssetRecord] = []
        for report in reports:
            candidate = await self._asset_from_report(
                report,
                source=source,
                tenant_id=selected_tenant,
            )
            existing = await self.store.get(candidate.id, tenant_id=selected_tenant)
            if existing is not None:
                candidate = candidate.model_copy(
                    update={"first_seen_at": existing.first_seen_at},
                    deep=True,
                )
            stored.append(await self.store.put(candidate))
        return stored

    async def reconcile(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = require_tenant_id(tenant_id)
        current = await self.store.get(selected_id, tenant_id=selected_tenant)
        if current is None:
            raise AssetNotFound(selected_id)
        records = _latest_records_by_source(await self.store.history(selected_id))
        if not records:
            records = [current]
        updates: dict[str, Any] = {}
        conflicts: list[FieldConflict] = []
        for field in _RECONCILED_FIELDS:
            resolution = _resolve_field(records, field)
            if resolution.conflict is not None:
                conflicts.append(resolution.conflict)
            if resolution.resolved:
                updates[field] = _model_value(field, resolution.value)
            elif field in {"classification", "owner"}:
                updates[field] = None
        updates["conflicts"] = conflicts
        return await self.store.put(current.model_copy(update=updates, deep=True))

    async def _asset_from_report(
        self,
        report: Mapping[str, Any],
        *,
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> AssetRecord:
        asset_id = _string(report.get("id", report.get("asset_id", new_id("ast"))), field="id")
        asset_type = _string(report.get("asset_type"), field="asset_type")
        classification = _optional_string(report.get("classification"), field="classification")
        lifecycle_state = _string(report.get("lifecycle_state", "active"), field="lifecycle_state")
        basis = _basis_from_report(report, source=source)
        owner = _owner_from_report(report)
        return AssetRecord(
            id=asset_id,
            tenant_id=tenant_id,
            asset_type=asset_type,
            discovery_source=source.source_id,
            classification=classification,
            owner=owner,
            lifecycle_state=lifecycle_state,
            confidence=source.reliability if source.reliability is not None else 0.5,
            basis=basis,
            first_seen_at=source.as_of,
            last_reported_at=source.as_of,
        )


def _basis_from_report(report: Mapping[str, Any], *, source: DiscoverySource) -> list[AssetBasis]:
    raw_basis = report.get("basis")
    if raw_basis is not None:
        if not isinstance(raw_basis, Sequence) or isinstance(raw_basis, str | bytes):
            raise InventoryConfigInvalid("basis must be a sequence")
        return [AssetBasis.model_validate(value) for value in raw_basis]
    ref = _optional_string(report.get("ref"), field="ref") or source.source_id
    evidence_id = _optional_string(report.get("evidence_id"), field="evidence_id")
    return [
        AssetBasis(
            kind="discovery",
            ref=f"{source.source_id}:{ref}",
            as_of=source.as_of,
            evidence_id=evidence_id,
        )
    ]


def _owner_from_report(report: Mapping[str, Any]) -> Ownership | None:
    owner = report.get("owner")
    if owner is None:
        return None
    return Ownership.model_validate(owner)


def _latest_records_by_source(history: Sequence[dict[str, Any]]) -> list[AssetRecord]:
    selected: dict[str, AssetRecord] = {}
    for row in sorted(history, key=lambda item: int(item.get("seq", 0))):
        snapshot = row.get("snapshot")
        record = AssetRecord.model_validate(snapshot)
        selected[record.discovery_source] = record
    return [selected[key] for key in sorted(selected)]


def _resolve_field(records: Sequence[AssetRecord], field: str) -> _Resolution:
    candidates = [
        ConflictCandidate(
            value=_field_value(record, field),
            source_id=record.discovery_source,
            reliability=record.confidence,
        )
        for record in records
    ]
    values = {_value_key(candidate.value) for candidate in candidates}
    if len(values) <= 1:
        return _Resolution(field=field, conflict=None, value=candidates[0].value, resolved=True)

    max_reliability = max(candidate.reliability or 0.0 for candidate in candidates)
    leaders = [
        candidate for candidate in candidates if (candidate.reliability or 0.0) == max_reliability
    ]
    leader_values = {_value_key(candidate.value) for candidate in leaders}
    if len(leader_values) == 1:
        winner = sorted(leaders, key=lambda candidate: candidate.source_id)[0]
        return _Resolution(
            field=field,
            conflict=FieldConflict(
                field=field,
                candidates=sorted(candidates, key=lambda candidate: candidate.source_id),
                resolved_by=winner.source_id,
                unresolved=False,
            ),
            value=winner.value,
            resolved=True,
        )
    return _Resolution(
        field=field,
        conflict=FieldConflict(
            field=field,
            candidates=sorted(candidates, key=lambda candidate: candidate.source_id),
            resolved_by=None,
            unresolved=True,
        ),
        value=None,
        resolved=False,
    )


def _field_value(record: AssetRecord, field: str) -> Any:
    value = getattr(record, field)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _model_value(field: str, value: Any) -> Any:
    if field == "owner" and value is not None:
        return Ownership.model_validate(value)
    return value


def _value_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryConfigInvalid(f"{field} must not be empty")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)
