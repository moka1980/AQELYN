"""DSPM metadata classification, owner routing, and bounded assessment (EA-0031 P2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef, new_id, parse_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import (
    AQError,
    CrossTenantReference,
    DataAssetNotFound,
    DSPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.dspm.classify import ClassificationResult, TrustAssessor, classify_descriptor
from aqelyn.dspm.models import (
    AssetClassificationStatus,
    Classification,
    DataAsset,
    DataPostureAssessment,
    DataStoreDescriptor,
    DSPMConfig,
    DSPMScope,
    FieldClassification,
    classification_order,
)
from aqelyn.dspm.store import DSPMStore
from aqelyn.evidence import EvidenceStore
from aqelyn.inventory import AssetRecord, DiscoverySource
from aqelyn.objects import AQObject, NaturalKey, ObjectStore, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry

DATA_STORE_OBJECT_TYPE = "data_store"
_DSPM_ACTOR = ActorRef(actor_type="system", actor_id="dspm_engine")


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


class DataStoreInventoryOwner(Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...


def ensure_data_store_object_type(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        registry.register(DATA_STORE_OBJECT_TYPE, 1, None)
        return
    if registry is not None:
        cast(_ObjectStoreRegistry, object_store).registry.register(
            DATA_STORE_OBJECT_TYPE,
            1,
            None,
        )


class DSPMEngine:
    def __init__(
        self,
        store: DSPMStore,
        *,
        object_store: ObjectStore,
        inventory: DataStoreInventoryOwner,
        evidence_store: EvidenceStore,
        trust: TrustAssessor,
        config: DSPMConfig,
        actor: ActorRef | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.trust = trust
        self.config = config
        self.actor = actor or _DSPM_ACTOR
        ensure_data_store_object_type(object_store)

    async def ingest_store(
        self,
        descriptors: Sequence[DataStoreDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[DataAsset]:
        selected_tenant = require_tenant_id(tenant_id)
        stored: list[DataAsset] = []
        for descriptor in descriptors:
            self._validate_descriptor(descriptor, tenant_id=selected_tenant)
            result = await classify_descriptor(
                descriptor,
                rules=self.config.classifier_rules,
                evidence_store=self.evidence_store,
                trust=self.trust,
                actor=self.actor,
                tenant_id=selected_tenant,
            )
            existing = await self.store.get_asset_by_store_id(
                descriptor.store_id,
                tenant_id=selected_tenant,
            )
            saved_object = await self.object_store.upsert(
                _data_store_object(
                    descriptor,
                    result=result,
                    actor=self.actor,
                    object_id="" if existing is None else existing.object_id,
                )
            )
            if existing is not None and saved_object.id != existing.object_id:
                raise StoreUnavailable("EA-0002 data store identity changed across ingest")
            inventory_ref = _inventory_ref(saved_object.id)
            inventory_rows = await self.inventory.ingest(
                reports=[
                    _inventory_report(
                        descriptor,
                        result=result,
                        inventory_ref=inventory_ref,
                    )
                ],
                source=DiscoverySource(
                    source_id=descriptor.source_id,
                    reliability=result.descriptor_confidence,
                    health="ok",
                    as_of=descriptor.observed_at,
                ),
                tenant_id=selected_tenant,
            )
            if len(inventory_rows) != 1 or inventory_rows[0].id != inventory_ref:
                raise StoreUnavailable("EA-0025 inventory did not accept the data store")

            status, flagged = _asset_status(result)
            asset = DataAsset(
                id=new_id("dsa") if existing is None else existing.id,
                object_id=saved_object.id,
                inventory_ref=inventory_ref,
                tenant_id=selected_tenant,
                store_id=descriptor.store_id,
                store_type=descriptor.store_type,
                location=descriptor.location.model_copy(deep=True),
                field_classifications=[item.model_copy(deep=True) for item in result.fields],
                max_known_sensitivity=_max_sensitivity(result.fields),
                classification_status=status,
                flagged=flagged,
                conflicts=[item.model_copy(deep=True) for item in result.conflicts],
                access_claims=[item.model_copy(deep=True) for item in descriptor.access_claims],
                reachability_claim=(
                    None
                    if descriptor.reachability_claim is None
                    else descriptor.reachability_claim.model_copy(deep=True)
                ),
                observed_at=descriptor.observed_at,
                evidence_id=descriptor.evidence_id,
                version=1 if existing is None else existing.version + 1,
            )
            stored.append(await self.store.put_asset(asset))
        return [item.model_copy(deep=True) for item in stored]

    async def classify(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> list[FieldClassification]:
        selected_tenant = require_tenant_id(tenant_id)
        asset = await self.store.get_asset(asset_id, tenant_id=selected_tenant)
        if asset is None:
            raise DataAssetNotFound(asset_id)
        return [item.model_copy(deep=True) for item in asset.field_classifications]

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope | None = None,
    ) -> DataPostureAssessment:
        selected_tenant = require_tenant_id(tenant_id)
        selected_scope = (scope or DSPMScope()).model_copy(deep=True)
        budget = min(selected_scope.limit, self.config.max_work)
        cursor = selected_scope.cursor
        seen_cursors: set[str] = set()
        stores_evaluated = 0
        classified_fields = 0
        unknown_fields = 0
        work = 0

        while work < budget:
            page_limit = min(self.config.batch_size, budget - work)
            try:
                rows, next_cursor = await self.store.query_assets(
                    tenant_id=selected_tenant,
                    flagged=selected_scope.flagged,
                    limit=page_limit,
                    cursor=cursor,
                )
            except AQError as exc:
                if not exc.retriable:
                    raise
                if work == 0:
                    return DataPostureAssessment(
                        tenant_id=selected_tenant,
                        run_at=utc_now(),
                        scope=selected_scope,
                        coverage_status="pending",
                        coverage_reason=f"DSPM store unavailable: {exc.code}",
                    )
                if cursor is None:
                    raise StoreUnavailable("DSPM pagination lost its continuation cursor") from exc
                assessment = DataPostureAssessment(
                    tenant_id=selected_tenant,
                    run_at=utc_now(),
                    scope=selected_scope,
                    coverage_status="truncated",
                    coverage_reason=f"DSPM store unavailable: {exc.code}",
                    next_cursor=cursor,
                    stores_evaluated=stores_evaluated,
                    classified_fields=classified_fields,
                    unknown_fields=unknown_fields,
                )
                return await self.store.put_assessment(assessment)

            work += len(rows)
            for asset in rows:
                if (
                    selected_scope.store_types
                    and asset.store_type not in selected_scope.store_types
                ):
                    continue
                stores_evaluated += 1
                classified_fields += sum(
                    item.status == "known" for item in asset.field_classifications
                )
                unknown_fields += sum(
                    item.status != "known" for item in asset.field_classifications
                )

            if next_cursor is None:
                assessment = DataPostureAssessment(
                    tenant_id=selected_tenant,
                    run_at=utc_now(),
                    scope=selected_scope,
                    coverage_status="complete",
                    stores_evaluated=stores_evaluated,
                    classified_fields=classified_fields,
                    unknown_fields=unknown_fields,
                )
                return await self.store.put_assessment(assessment)
            if not rows:
                raise StoreUnavailable("DSPMStore returned an empty page with a cursor")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise StoreUnavailable("DSPMStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        if cursor is None:
            raise StoreUnavailable("DSPM assessment exhausted work without a continuation cursor")
        assessment = DataPostureAssessment(
            tenant_id=selected_tenant,
            run_at=utc_now(),
            scope=selected_scope,
            coverage_status="truncated",
            coverage_reason="truncated",
            next_cursor=cursor,
            stores_evaluated=stores_evaluated,
            classified_fields=classified_fields,
            unknown_fields=unknown_fields,
        )
        return await self.store.put_assessment(assessment)

    def _validate_descriptor(
        self,
        descriptor: DataStoreDescriptor,
        *,
        tenant_id: str | None,
    ) -> None:
        if descriptor.tenant_id != tenant_id:
            raise CrossTenantReference("descriptor tenant does not match explicit tenant scope")
        if len(descriptor.fields) > self.config.max_fields_per_store:
            raise DSPMConfigInvalid("descriptor exceeds max_fields_per_store")
        if any(
            len(field.signals) > self.config.max_signals_per_field for field in descriptor.fields
        ):
            raise DSPMConfigInvalid("descriptor field exceeds max_signals_per_field")


def _data_store_object(
    descriptor: DataStoreDescriptor,
    *,
    result: ClassificationResult,
    actor: ActorRef,
    object_id: str,
) -> AQObject:
    status, flagged = _asset_status(result)
    maximum = _max_sensitivity(result.fields)
    source = SourceRef(
        source_id=descriptor.source_id,
        evidence_id=descriptor.evidence_id,
        observed_at=descriptor.observed_at,
        method="dspm.metadata_descriptor/v1",
    )
    now = descriptor.observed_at
    return AQObject(
        id=object_id,
        object_type=DATA_STORE_OBJECT_TYPE,
        schema_version=1,
        tenant_id=descriptor.tenant_id,
        display_name=descriptor.store_id,
        attributes={
            "store_id": descriptor.store_id,
            "store_type": descriptor.store_type,
            "location": descriptor.location.model_dump(mode="json"),
            "field_classifications": [
                {
                    "field": item.field,
                    "classification": item.classification,
                    "status": item.status,
                    "flagged": item.flagged,
                }
                for item in result.fields
            ],
            "max_known_sensitivity": maximum,
            "classification_status": status,
            "flagged": flagged,
        },
        labels={"module": "EA-0031", "kind": DATA_STORE_OBJECT_TYPE},
        natural_keys=[NaturalKey(namespace="dspm:store", value=descriptor.store_id)],
        sources=[source],
        confidence=result.descriptor_confidence,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
    )


def _inventory_report(
    descriptor: DataStoreDescriptor,
    *,
    result: ClassificationResult,
    inventory_ref: str,
) -> dict[str, object]:
    return {
        "id": inventory_ref,
        "asset_type": DATA_STORE_OBJECT_TYPE,
        "classification": _max_sensitivity(result.fields) or "unknown",
        "lifecycle_state": "active",
        "evidence_id": descriptor.evidence_id,
        "ref": f"dspm:{descriptor.store_id}",
    }


def _inventory_ref(object_id: str) -> str:
    prefix, payload = parse_id(object_id)
    if prefix != "obj":
        raise StoreUnavailable("EA-0002 data store id must use obj_ prefix")
    # Preserve one stable payload while keeping each owner's typed identity distinct.
    return f"ast_{payload}"


def _max_sensitivity(fields: Sequence[FieldClassification]) -> Classification | None:
    known = {item.classification for item in fields if item.status == "known"}
    maximum: Classification | None = None
    for classification in classification_order():
        if classification in known:
            maximum = classification
    return maximum


def _asset_status(result: ClassificationResult) -> tuple[AssetClassificationStatus, bool]:
    known = [item for item in result.fields if item.status == "known"]
    non_known = [item for item in result.fields if item.status != "known"]
    if any(item.status == "conflict" for item in result.fields):
        return "conflict", True
    if known and not non_known:
        return "complete", False
    if known:
        return "partial", True
    return "unknown", True
