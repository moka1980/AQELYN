"""C-028 P2 acceptance tests for classification, owner routing, and stores."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

import asyncpg
import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    EvidenceNotFound,
    EvidenceTampered,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.dspm import (
    AssetClassificationStatus,
    Classification,
    DataAsset,
    DataExposure,
    DataFieldDescriptor,
    DataPostureAssessment,
    DataStoreDescriptor,
    DataStoreLocation,
    DSPMConfig,
    DSPMEngine,
    DSPMScope,
    DSPMStore,
    FieldClassification,
    InMemoryDSPMStore,
    PostgresDSPMStore,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.objects import InMemoryObjectStore, NaturalKey, ObjectQuery
from aqelyn.policy import Condition
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    TrustEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000310201"
OTHER_TENANT = "018f0000-0000-7000-8000-000000310202"
ACTOR = ActorRef(actor_type="system", actor_id="dspm-p2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: DSPMStore
    object_store: InMemoryObjectStore
    inventory_store: InMemoryAssetStore
    evidence_store: InMemoryEvidenceStore
    registry: InMemorySourceReliabilityRegistry
    engine: DSPMEngine


@asynccontextmanager
async def _harness(
    kind: str,
    *,
    config: DSPMConfig | None = None,
) -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: DSPMStore = InMemoryDSPMStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresDSPMStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_dspm_assessment, aq_dspm_exposure, aq_dspm_asset, aq_dspm_asset_key"
            )
        store = postgres
        closer = cast(_Closable, postgres)
    object_store = InMemoryObjectStore(mode="enterprise")
    inventory_store = InMemoryAssetStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    engine = DSPMEngine(
        store,
        object_store=object_store,
        inventory=InventoryIntelligenceEngine(inventory_store),
        evidence_store=evidence_store,
        trust=TrustEngine(registry=registry),
        config=config or _config(),
    )
    try:
        yield _Harness(
            store,
            object_store,
            inventory_store,
            evidence_store,
            registry,
            engine,
        )
    finally:
        if closer is not None:
            await closer.close()


def _config(**overrides: object) -> DSPMConfig:
    data: dict[str, object] = {
        "classifier_rules": [
            {
                "id": "rule:email-pii:v1",
                "condition": Condition(
                    op="eq",
                    attr="signal.detector_ref",
                    value="detector:email",
                ),
                "classification": "pii",
                "reason": "Email metadata indicates personal data.",
            },
            {
                "id": "rule:credential-secret:v1",
                "condition": Condition(
                    op="eq",
                    attr="signal.detector_ref",
                    value="detector:credential",
                ),
                "classification": "secret",
                "reason": "Credential metadata indicates secret data.",
            },
        ],
        "sensitivity_factors": {
            "public": 0.0,
            "internal": 0.25,
            "pii": 0.8,
            "secret": 1.0,
        },
        "batch_size": 2,
        "max_work": 10,
    }
    data.update(overrides)
    return DSPMConfig.model_validate(data)


async def _evidence(
    harness: _Harness,
    *,
    source_id: str,
    reliability: float,
    tenant_id: str = TENANT,
    method: str = "dspm.metadata/v1",
) -> EvidenceRecord:
    await harness.registry.set(
        SourceReliability(
            key=source_id,
            weight=reliability,
            rationale="DSPM P2 source fixture.",
            set_by=ACTOR,
            set_at=NOW,
        )
    )
    return await harness.evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="data.store_metadata",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=source_id,
            method=method,
            content={"metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


def _descriptor(
    *,
    evidence_id: str,
    source_id: str,
    store_id: str = "aws:s3:billing-records",
    fields: list[DataFieldDescriptor] | None = None,
    tenant_id: str = TENANT,
) -> DataStoreDescriptor:
    return DataStoreDescriptor(
        store_id=store_id,
        tenant_id=tenant_id,
        store_type="bucket",
        location=DataStoreLocation(
            provider="aws",
            account_ref="account-123",
            region="eu-north-1",
            resource_ref=f"arn:aws:s3:::{store_id.rsplit(':', 1)[-1]}",
        ),
        fields=fields or [],
        source_id=source_id,
        observed_at=NOW,
        evidence_id=evidence_id,
    )


def _field(
    name: str,
    *,
    detector_ref: str,
    evidence_id: str,
) -> DataFieldDescriptor:
    return DataFieldDescriptor.model_validate(
        {
            "name": name,
            "data_type": "string",
            "signals": [
                {
                    "id": f"signal:{name}:{detector_ref}",
                    "kind": "detector_match",
                    "detector_ref": detector_ref,
                    "match_count": 1,
                    "evidence_id": evidence_id,
                }
            ],
        }
    )


def _stored_asset(
    asset_id: str,
    *,
    tenant_id: str = TENANT,
    classification: Classification = "pii",
    flagged: bool = False,
    version: int = 1,
) -> DataAsset:
    field = FieldClassification(
        field="customer_email",
        classification=classification,
        status="known",
        flagged=False,
        confidence=0.8,
        evidence_ids=[new_id("evd")],
        reason="P2 store contract fixture.",
    )
    return DataAsset(
        id=asset_id,
        object_id=new_id("obj"),
        inventory_ref=new_id("ast"),
        tenant_id=tenant_id,
        store_id=f"store:{asset_id}",
        store_type="bucket",
        location=DataStoreLocation(
            provider="aws",
            resource_ref=f"arn:aws:s3:::{asset_id}",
        ),
        field_classifications=[field],
        max_known_sensitivity=classification,
        classification_status="complete",
        flagged=flagged,
        observed_at=NOW,
        evidence_id=new_id("evd"),
        version=version,
    )


async def test_dspm_classification_evidence_runtime() -> None:
    async with _harness("inmemory") as harness:
        descriptor_source = new_id("src")
        detector_source = new_id("src")
        descriptor_evidence = await _evidence(
            harness,
            source_id=descriptor_source,
            reliability=0.4,
        )
        detector_evidence = await _evidence(
            harness,
            source_id=detector_source,
            reliability=0.9,
        )
        descriptor = _descriptor(
            evidence_id=descriptor_evidence.id,
            source_id=descriptor_source,
            fields=[
                _field(
                    "customer_email",
                    detector_ref="detector:email",
                    evidence_id=detector_evidence.id,
                )
            ],
        )

        asset = (await harness.engine.ingest_store([descriptor], tenant_id=TENANT))[0]

    selected = asset.field_classifications[0]
    assert selected.classification == "pii"
    assert selected.confidence == pytest.approx(0.9)
    assert selected.evidence_ids == [detector_evidence.id]


async def test_dspm_no_winning_rule_is_unknown() -> None:
    async with _harness("inmemory") as harness:
        source_id = new_id("src")
        descriptor_evidence = await _evidence(
            harness,
            source_id=source_id,
            reliability=0.9,
        )
        signal_evidence = await _evidence(
            harness,
            source_id=new_id("src"),
            reliability=0.95,
        )
        descriptor = _descriptor(
            evidence_id=descriptor_evidence.id,
            source_id=source_id,
            fields=[
                _field(
                    "opaque_identifier",
                    detector_ref="detector:unmapped",
                    evidence_id=signal_evidence.id,
                )
            ],
        )

        asset = (await harness.engine.ingest_store([descriptor], tenant_id=TENANT))[0]

    selected = asset.field_classifications[0]
    assert selected.classification == "unknown"
    assert selected.status == "unknown"
    assert selected.flagged is True
    assert selected.confidence == 0.0
    assert selected.evidence_ids == [descriptor_evidence.id]
    assert asset.classification_status == "unknown"
    assert asset.max_known_sensitivity is None


async def test_dspm_conflict_recorded() -> None:
    async with _harness("inmemory") as harness:
        descriptor_source = new_id("src")
        descriptor_evidence = await _evidence(
            harness,
            source_id=descriptor_source,
            reliability=0.5,
        )
        pii_source = new_id("src")
        secret_source = new_id("src")
        pii_evidence = await _evidence(harness, source_id=pii_source, reliability=0.8)
        secret_evidence = await _evidence(harness, source_id=secret_source, reliability=0.8)
        descriptor = _descriptor(
            evidence_id=descriptor_evidence.id,
            source_id=descriptor_source,
            fields=[
                DataFieldDescriptor(
                    name="credential_or_email",
                    data_type="string",
                    signals=[
                        _field(
                            "unused",
                            detector_ref="detector:email",
                            evidence_id=pii_evidence.id,
                        ).signals[0],
                        _field(
                            "unused",
                            detector_ref="detector:credential",
                            evidence_id=secret_evidence.id,
                        ).signals[0],
                    ],
                )
            ],
        )
        tied = (await harness.engine.ingest_store([descriptor], tenant_id=TENANT))[0]

        stronger_evidence = await _evidence(
            harness,
            source_id=secret_source,
            reliability=0.95,
        )
        resolved_descriptor = descriptor.model_copy(
            update={
                "fields": [
                    descriptor.fields[0].model_copy(
                        update={
                            "signals": [
                                descriptor.fields[0].signals[0],
                                descriptor.fields[0]
                                .signals[1]
                                .model_copy(update={"evidence_id": stronger_evidence.id}),
                            ]
                        },
                        deep=True,
                    )
                ]
            },
            deep=True,
        )
        resolved = (await harness.engine.ingest_store([resolved_descriptor], tenant_id=TENANT))[0]

    assert tied.classification_status == "conflict"
    assert tied.field_classifications[0].classification == "unknown"
    assert tied.conflicts[0].unresolved is True
    assert {item.classification for item in tied.conflicts[0].candidates} == {"pii", "secret"}
    assert resolved.classification_status == "complete"
    assert resolved.field_classifications[0].classification == "secret"
    assert resolved.conflicts[0].resolved_by == secret_source
    assert len(resolved.conflicts[0].candidates) == 2


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_dspm_unusable_signal_evidence_never_improves_classification(kind: str) -> None:
    async with _harness(kind) as harness:
        descriptor_source = new_id("src")
        descriptor_evidence = await _evidence(
            harness,
            source_id=descriptor_source,
            reliability=0.9,
        )

        def descriptor_for(signal_evidence_id: str, *, store_id: str) -> DataStoreDescriptor:
            signal = _field(
                "credential",
                detector_ref="detector:credential",
                evidence_id=signal_evidence_id,
            ).signals[0]
            return _descriptor(
                evidence_id=descriptor_evidence.id,
                source_id=descriptor_source,
                store_id=store_id,
                fields=[
                    DataFieldDescriptor(
                        name="credential",
                        data_type="string",
                        signals=[signal],
                        existing_classification="public",
                    )
                ],
            )

        with pytest.raises(EvidenceNotFound):
            await harness.engine.ingest_store(
                [descriptor_for(new_id("evd"), store_id="missing-signal-evidence")],
                tenant_id=TENANT,
            )

        tampered = await _evidence(
            harness,
            source_id=new_id("src"),
            reliability=0.9,
        )
        harness.evidence_store._by_id[tampered.id].content = {"tampered": True}
        with pytest.raises(EvidenceTampered):
            await harness.engine.ingest_store(
                [descriptor_for(tampered.id, store_id="tampered-signal-evidence")],
                tenant_id=TENANT,
            )

        assets_before_valid, cursor = await harness.store.query_assets(
            tenant_id=TENANT,
            limit=10,
        )
        objects_before_valid, object_cursor = await harness.object_store.query(
            ObjectQuery(tenant_id=TENANT, limit=10)
        )
        assert assets_before_valid == []
        assert cursor is None
        assert objects_before_valid == []
        assert object_cursor is None

        valid = await _evidence(
            harness,
            source_id=new_id("src"),
            reliability=0.9,
        )
        asset = (
            await harness.engine.ingest_store(
                [descriptor_for(valid.id, store_id="valid-signal-evidence")],
                tenant_id=TENANT,
            )
        )[0]

    selected = asset.field_classifications[0]
    assert selected.classification == "unknown"
    assert selected.status == "conflict"
    assert selected.flagged is True
    assert len(asset.conflicts) == 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_dspm_store_to_inventory(kind: str) -> None:
    async with _harness(kind) as harness:
        source_id = new_id("src")
        evidence = await _evidence(harness, source_id=source_id, reliability=0.75)
        descriptor = _descriptor(evidence_id=evidence.id, source_id=source_id)

        first = (await harness.engine.ingest_store([descriptor], tenant_id=TENANT))[0]
        second = (await harness.engine.ingest_store([descriptor], tenant_id=TENANT))[0]
        object_row = await harness.object_store.get(first.object_id)
        inventory_row = await harness.inventory_store.get(
            first.inventory_ref,
            tenant_id=TENANT,
        )
        objects, cursor = await harness.object_store.query(
            ObjectQuery(
                tenant_id=TENANT,
                natural_key=NaturalKey(namespace="dspm:store", value=descriptor.store_id),
            )
        )

    assert object_row is not None
    assert object_row.object_type == "data_store"
    assert object_row.attributes["classification_status"] == "unknown"
    assert inventory_row is not None
    assert inventory_row.asset_type == "data_store"
    assert inventory_row.classification == "unknown"
    assert first.object_id == second.object_id
    assert first.inventory_ref == second.inventory_ref
    assert second.version == 2
    assert [item.id for item in objects] == [first.object_id]
    assert cursor is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_dspm_store_contract(kind: str) -> None:
    async with _harness(kind) as harness:
        ids = sorted(new_id("dsa") for _ in range(7))
        for asset_id in ids[:5]:
            await harness.store.put_asset(_stored_asset(asset_id, classification="internal"))
        for asset_id in ids[5:]:
            await harness.store.put_asset(_stored_asset(asset_id, classification="pii"))
        other = _stored_asset(new_id("dsa"), tenant_id=OTHER_TENANT)
        await harness.store.put_asset(other)

        filtered, filtered_cursor = await harness.store.query_assets(
            tenant_id=TENANT,
            classification="pii",
            limit=2,
        )
        paged: list[DataAsset] = []
        cursor: str | None = None
        while True:
            rows, cursor = await harness.store.query_assets(
                tenant_id=TENANT,
                limit=2,
                cursor=cursor,
            )
            paged.extend(rows)
            if cursor is None:
                break

        current = await harness.store.get_asset(ids[0], tenant_id=TENANT)
        assert current is not None
        updated = current.model_copy(update={"version": 2}, deep=True)
        await harness.store.put_asset(updated)
        latest = await harness.store.get_asset(ids[0], tenant_id=TENANT)
        other_visible = await harness.store.get_asset(other.id, tenant_id=TENANT)

        exposure = DataExposure(
            tenant_id=TENANT,
            data_asset_id=ids[0],
            object_id=new_id("obj"),
            exposure_ref=new_id("exp"),
            sensitivity="unknown",
            reachability="external",
            state="classification_gap",
            flagged=True,
            reason="Store contract classification gap.",
            evidence_ids=[new_id("evd")],
            detected_at=NOW,
        )
        assessment = DataPostureAssessment(
            tenant_id=TENANT,
            run_at=NOW,
            scope=DSPMScope(),
            coverage_status="complete",
        )
        await harness.store.put_exposure(exposure)
        await harness.store.put_assessment(assessment)

        assert [item.id for item in filtered] == ids[5:]
        assert filtered_cursor is None
        assert [item.id for item in paged] == ids
        assert latest is not None
        assert latest.version == 2
        assert other_visible is None
        with pytest.raises(OptimisticConcurrencyConflict):
            await harness.store.put_asset(updated)
        with pytest.raises(OptimisticConcurrencyConflict, match="identity cannot change"):
            await harness.store.put_asset(
                latest.model_copy(
                    update={"store_id": "changed-store", "version": 3},
                    deep=True,
                )
            )
        with pytest.raises(OptimisticConcurrencyConflict, match="another data asset"):
            await harness.store.put_asset(
                _stored_asset(new_id("dsa")).model_copy(
                    update={"store_id": current.store_id},
                    deep=True,
                )
            )
        with pytest.raises(OptimisticConcurrencyConflict):
            await harness.store.put_exposure(exposure)
        with pytest.raises(OptimisticConcurrencyConflict):
            await harness.store.put_assessment(assessment)
        with pytest.raises(TenantScopeRequired):
            await harness.store.query_assets(tenant_id=None)
        if kind == "postgres":
            postgres = cast(PostgresDSPMStore, harness.store)
            async with postgres._pool.acquire() as conn:
                with pytest.raises(asyncpg.PostgresError, match="append-only"):
                    await conn.execute(
                        "UPDATE aq_dspm_asset SET flagged=true WHERE id=$1",
                        ids[0],
                    )


async def test_dspm_assessment_coverage() -> None:
    config = _config(batch_size=2, max_work=10)
    async with _harness("inmemory", config=config) as harness:
        for asset_id in sorted(new_id("dsa") for _ in range(3)):
            await harness.store.put_asset(_stored_asset(asset_id))

        truncated = await harness.engine.assess(
            tenant_id=TENANT,
            scope=DSPMScope(limit=2),
        )
        complete = await harness.engine.assess(
            tenant_id=TENANT,
            scope=DSPMScope(limit=10),
        )

    assert truncated.coverage_status == "truncated"
    assert truncated.coverage_reason == "truncated"
    assert truncated.next_cursor is not None
    assert truncated.stores_evaluated == 2
    assert complete.coverage_status == "complete"
    assert complete.next_cursor is None
    assert complete.stores_evaluated == 3


async def test_dspm_tenant_isolation() -> None:
    async with _harness("inmemory") as harness:
        source_id = new_id("src")
        evidence = await _evidence(
            harness,
            source_id=source_id,
            reliability=0.8,
            tenant_id=OTHER_TENANT,
        )
        descriptor = _descriptor(
            evidence_id=evidence.id,
            source_id=source_id,
            tenant_id=OTHER_TENANT,
        )

        with pytest.raises(CrossTenantReference, match="tenant"):
            await harness.engine.ingest_store([descriptor], tenant_id=TENANT)

        assert (
            await harness.store.get_asset_by_store_id(
                descriptor.store_id,
                tenant_id=TENANT,
            )
            is None
        )


async def test_dspm_assessment_repeated_cursor_refuses() -> None:
    class _RepeatedCursorStore(InMemoryDSPMStore):
        async def query_assets(
            self,
            *,
            tenant_id: str | None,
            classification: Classification | None = None,
            status: AssetClassificationStatus | None = None,
            flagged: bool | None = None,
            limit: int = 100,
            cursor: str | None = None,
        ) -> tuple[list[DataAsset], str | None]:
            del tenant_id, classification, status, flagged, limit
            selected = cursor or new_id("dsa")
            return [_stored_asset(selected)], selected

    object_store = InMemoryObjectStore(mode="enterprise")
    inventory_store = InMemoryAssetStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    engine = DSPMEngine(
        _RepeatedCursorStore(mode="enterprise"),
        object_store=object_store,
        inventory=InventoryIntelligenceEngine(inventory_store),
        evidence_store=evidence_store,
        trust=TrustEngine(),
        config=_config(),
    )
    with pytest.raises(StoreUnavailable, match="repeated pagination cursor"):
        await engine.assess(tenant_id=TENANT, scope=DSPMScope(limit=3))
