"""Inventory reference engine for handed-in ingest and reconciliation (EA-0025 N2)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id, utc_now
from aqelyn.conventions.errors import (
    AssetNotFound,
    DecommissionRequiresEvidence,
    InventoryConfigInvalid,
    InventoryUnavailable,
    SourceHealthUnknown,
)
from aqelyn.graph import Path
from aqelyn.inventory.models import (
    AssetBasis,
    AssetRecord,
    AssetRelationship,
    ConflictCandidate,
    DiscoverySource,
    FieldConflict,
    InventoryConfig,
    InventoryReport,
    Ownership,
)
from aqelyn.inventory.store import AssetStore, validate_asset_id
from aqelyn.objects import AQRelationship, SourceRef

_RECONCILED_FIELDS = ("asset_type", "classification", "owner")
_INVENTORY_STATES = frozenset(("provisioned", "active", "modified", "unreported"))
_INVENTORY_ACTOR = ActorRef(actor_type="system", actor_id="inventory_engine")


class AssetClassifier(Protocol):
    async def classify(self, asset_id: str, *, tenant_id: str | None = None) -> str: ...


class InventoryRelationshipStore(Protocol):
    async def relate(self, rel: AQRelationship) -> AQRelationship: ...


class InventoryRelationshipGraph(Protocol):
    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
        max_work: int = 50_000,
    ) -> list[Path]: ...


@dataclass(frozen=True)
class _Resolution:
    field: str
    conflict: FieldConflict | None
    value: Any
    resolved: bool


@dataclass(frozen=True)
class _RelationshipHint:
    source_object_id: str
    relation_type: str
    target_object_id: str
    ref: str
    evidence_id: str | None
    as_of: datetime


class InventoryIntelligenceEngine:
    def __init__(
        self,
        store: AssetStore,
        *,
        config: InventoryConfig | None = None,
        classifier: AssetClassifier | None = None,
        relationship_store: InventoryRelationshipStore | None = None,
        graph: InventoryRelationshipGraph | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self.store = store
        self.config = config or InventoryConfig()
        self.classifier = classifier
        self.relationship_store = relationship_store
        self.graph = graph
        self.actor = actor or _INVENTORY_ACTOR
        self.source_id = source_id or new_id("src")

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

    async def mark_unreported(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = require_tenant_id(tenant_id)
        current = await self.store.get(selected_id, tenant_id=selected_tenant)
        if current is None:
            raise AssetNotFound(selected_id)
        now = utc_now()
        return await self.store.put(
            current.model_copy(
                update={
                    "lifecycle_state": "unreported",
                    "unreported_since": current.unreported_since or now,
                },
                deep=True,
            )
        )

    async def sweep_unreported(
        self, *, source: DiscoverySource, tenant_id: str | None
    ) -> list[AssetRecord]:
        if source.health == "unknown":
            raise SourceHealthUnknown("cannot sweep unreported assets for unknown source health")
        selected_tenant = require_tenant_id(tenant_id)
        try:
            rows = await self.store.query(tenant_id=selected_tenant, limit=10_000)
        except Exception as exc:
            raise InventoryUnavailable("asset inventory store unavailable") from exc
        changed: list[AssetRecord] = []
        for row in rows:
            if (
                row.discovery_source == source.source_id
                and row.lifecycle_state not in {"decommissioned", "archived", "unreported"}
                and row.last_reported_at < source.as_of
            ):
                changed.append(
                    await self.store.put(
                        row.model_copy(
                            update={
                                "lifecycle_state": "unreported",
                                "unreported_since": source.as_of,
                            },
                            deep=True,
                        )
                    )
                )
        return changed

    async def decommission(
        self,
        asset_id: str,
        *,
        by: ActorRef,
        evidence_id: str | None,
        tenant_id: str | None,
        decision_ref: str | None = None,
    ) -> AssetRecord:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = require_tenant_id(tenant_id)
        if evidence_id is None and decision_ref is None:
            raise DecommissionRequiresEvidence(
                "decommission requires positive evidence or an attributed gated decision"
            )
        selected_evidence_id = (
            None
            if evidence_id is None
            else require_typed_id(evidence_id, "evd", field="evidence_id")
        )
        selected_decision_ref = (
            None
            if decision_ref is None
            else require_typed_id(decision_ref, "run", field="decision_ref")
        )
        current = await self.store.get(selected_id, tenant_id=selected_tenant)
        if current is None:
            raise AssetNotFound(selected_id)
        basis = list(current.basis)
        basis.append(
            AssetBasis(
                kind="discovery",
                ref=_decommission_ref(
                    by=by, evidence_id=selected_evidence_id, decision_ref=selected_decision_ref
                ),
                as_of=utc_now(),
                evidence_id=selected_evidence_id,
            )
        )
        return await self.store.put(
            current.model_copy(
                update={
                    "lifecycle_state": "decommissioned",
                    "unreported_since": current.unreported_since,
                    "basis": basis,
                },
                deep=True,
            )
        )

    async def inventory(self, *, tenant_id: str | None) -> InventoryReport:
        selected_tenant = require_tenant_id(tenant_id)
        try:
            rows = await self.store.query(tenant_id=selected_tenant, limit=10_000)
        except Exception as exc:
            raise InventoryUnavailable("asset inventory store unavailable") from exc
        included = [row for row in rows if row.lifecycle_state in _INVENTORY_STATES]
        freshness = _source_freshness(included)
        as_of = min(freshness.values()) if freshness else utc_now()
        return InventoryReport(
            assets=sorted(row.id for row in included),
            total=len(included),
            as_of=as_of,
            source_freshness=freshness,
            degraded=False,
        )

    async def classify(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord:
        if self.classifier is None:
            raise InventoryConfigInvalid("asset classification provider is unavailable")
        selected_id = validate_asset_id(asset_id)
        selected_tenant = require_tenant_id(tenant_id)
        current = await self.store.get(selected_id, tenant_id=selected_tenant)
        if current is None:
            raise AssetNotFound(selected_id)
        asset_class = await self.classifier.classify(selected_id, tenant_id=selected_tenant)
        if not asset_class.strip():
            raise InventoryConfigInvalid("classification provider returned an empty class")
        return await self.store.put(
            current.model_copy(
                update={
                    "classification": asset_class,
                    "basis": [
                        *current.basis,
                        AssetBasis(
                            kind="config",
                            ref=f"ea0012:classify:{selected_id}",
                            as_of=utc_now(),
                            evidence_id=None,
                        ),
                    ],
                },
                deep=True,
            )
        )

    async def ownership(self, asset_id: str, *, tenant_id: str | None) -> Ownership | None:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = require_tenant_id(tenant_id)
        current = await self.store.get(selected_id, tenant_id=selected_tenant)
        if current is None:
            raise AssetNotFound(selected_id)
        return None if current.owner is None else current.owner.model_copy(deep=True)

    async def infer_relationships(
        self, asset_id: str, *, tenant_id: str | None
    ) -> list[AssetRelationship]:
        if self.relationship_store is None:
            raise InventoryConfigInvalid("EA-0002 relationship store is unavailable")
        if self.graph is None:
            raise InventoryConfigInvalid("EA-0005 knowledge graph is unavailable")
        selected_id = validate_asset_id(asset_id)
        selected_tenant = require_tenant_id(tenant_id)
        current = await self.store.get(selected_id, tenant_id=selected_tenant)
        if current is None:
            raise AssetNotFound(selected_id)
        inferred: list[AssetRelationship] = []
        for hint in _relationship_hints(current):
            paths = await self.graph.paths(
                hint.source_object_id,
                hint.target_object_id,
                direction="out",
                relation_types=(hint.relation_type,),
                max_paths=1,
                max_work=self.config.max_relationship_work,
            )
            if not paths:
                continue
            related = await self.relationship_store.relate(
                AQRelationship(
                    id="",
                    tenant_id=selected_tenant,
                    from_id=hint.source_object_id,
                    to_id=hint.target_object_id,
                    relation_type=hint.relation_type,
                    attributes={"inferred_from": hint.ref, "inventory_asset_id": current.id},
                    sources=[
                        SourceRef(
                            source_id=self.source_id,
                            evidence_id=hint.evidence_id,
                            observed_at=hint.as_of,
                            method="inventory_relationship_inference",
                        )
                    ],
                    confidence=current.confidence,
                    lifecycle_state="active",
                    version=1,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                    created_by=self.actor,
                    updated_by=self.actor,
                )
            )
            inferred.append(
                AssetRelationship(
                    tenant_id=selected_tenant,
                    source_asset=related.from_id,
                    target_asset=related.to_id,
                    relationship_type=related.relation_type,
                    confidence=related.confidence,
                    inferred_from=hint.ref,
                    evidence_id=hint.evidence_id,
                )
            )
        inferred.sort(key=lambda item: (item.source_asset, item.target_asset, item.id))
        return inferred

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


def _source_freshness(records: Sequence[AssetRecord]) -> dict[str, datetime]:
    freshness: dict[str, datetime] = {}
    for record in records:
        current = freshness.get(record.discovery_source)
        if current is None or record.last_reported_at > current:
            freshness[record.discovery_source] = record.last_reported_at
    return dict(sorted(freshness.items()))


def _decommission_ref(*, by: ActorRef, evidence_id: str | None, decision_ref: str | None) -> str:
    if evidence_id is not None:
        return f"decommission:evidence:{evidence_id}:by:{by.actor_type}:{by.actor_id}"
    assert decision_ref is not None
    return f"decommission:decision:{decision_ref}:by:{by.actor_type}:{by.actor_id}"


def _relationship_hints(asset: AssetRecord) -> list[_RelationshipHint]:
    hints: list[_RelationshipHint] = []
    for basis in asset.basis:
        if basis.kind != "relationship":
            continue
        parts = basis.ref.split("|")
        if len(parts) != 3:
            raise InventoryConfigInvalid(
                "relationship basis ref must be source_obj|relation_type|target_obj"
            )
        source_object_id = require_typed_id(parts[0], "obj", field="relationship source")
        relation_type = _string(parts[1], field="relationship type")
        target_object_id = require_typed_id(parts[2], "obj", field="relationship target")
        hints.append(
            _RelationshipHint(
                source_object_id=source_object_id,
                relation_type=relation_type,
                target_object_id=target_object_id,
                ref=basis.ref,
                evidence_id=basis.evidence_id,
                as_of=basis.as_of,
            )
        )
    return hints
