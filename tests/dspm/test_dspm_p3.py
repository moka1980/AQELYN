"""C-028 P3 acceptance tests for the real EA-0023 handoff."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.dspm import (
    DataAsset,
    DataExposure,
    DataStoreKnownSurfaceSource,
    DataStoreLocation,
    DSPMConfig,
    DSPMEngine,
    DSPMStore,
    FieldClassification,
    InMemoryDSPMStore,
    PostgresDSPMStore,
    ReachabilityClaim,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.exposure import (
    ExposureStore,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    PostgresExposureStore,
    StaticKnownSurfaceSource,
)
from aqelyn.inventory import (
    DiscoverySource,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    InventoryKnownSurfaceSource,
)
from aqelyn.mission import MissionImpactResult
from aqelyn.objects import InMemoryObjectStore
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 20, 19, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000310302"
ACTOR = ActorRef(actor_type="system", actor_id="dspm-p3-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _MissionProvider:
    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        _ = object_id
        return MissionImpactResult()


class _BrokenQueryStore:
    def __init__(self, asset: DataAsset | None = None, *, repeated: bool = False) -> None:
        self.asset = asset
        self.repeated = repeated

    async def query_assets(self, **kwargs: object) -> tuple[list[DataAsset], str | None]:
        _ = kwargs
        if self.repeated and self.asset is not None:
            return [self.asset.model_copy(deep=True)], self.asset.id
        raise StoreUnavailable("DSPM source unavailable")


@asynccontextmanager
async def _dspm_store(backend: str) -> AsyncIterator[DSPMStore]:
    if backend == "inmemory":
        yield InMemoryDSPMStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresDSPMStore.connect(PG_URL, mode="enterprise")
    await _truncate_dspm(postgres)
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


@asynccontextmanager
async def _owner_stores(
    backend: str,
) -> AsyncIterator[tuple[DSPMStore, ExposureStore]]:
    if backend == "inmemory":
        yield (
            InMemoryDSPMStore(mode="enterprise"),
            InMemoryExposureStore(mode="enterprise"),
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    dspm_store = await PostgresDSPMStore.connect(PG_URL, mode="enterprise")
    exposure_store = await PostgresExposureStore.connect(PG_URL, mode="enterprise")
    await _truncate_dspm(dspm_store)
    async with exposure_store._pool.acquire() as connection:
        await connection.execute("TRUNCATE aq_exposure_record")
    try:
        yield dspm_store, exposure_store
    finally:
        await cast(_Closable, exposure_store).close()
        await cast(_Closable, dspm_store).close()


async def _truncate_dspm(store: PostgresDSPMStore) -> None:
    async with store._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE aq_dspm_assessment, aq_dspm_exposure, aq_dspm_asset, aq_dspm_asset_key"
        )


def _config() -> DSPMConfig:
    return DSPMConfig(
        sensitivity_factors={
            "public": 0.0,
            "internal": 0.25,
            "pii": 0.8,
            "secret": 1.0,
        },
        batch_size=2,
        max_work=20,
    )


def _known_field(name: str, sensitivity: str, evidence_id: str) -> FieldClassification:
    return FieldClassification.model_validate(
        {
            "field": name,
            "classification": sensitivity,
            "status": "known",
            "flagged": False,
            "confidence": 0.9,
            "evidence_ids": [evidence_id],
            "reason": f"{name} is classified as {sensitivity}.",
        }
    )


def _unknown_field(name: str, evidence_id: str) -> FieldClassification:
    return FieldClassification(
        field=name,
        classification="unknown",
        status="unknown",
        flagged=True,
        confidence=0.0,
        evidence_ids=[evidence_id],
        reason=f"{name} could not be classified.",
    )


def _asset(
    *,
    inventory_ref: str,
    object_id: str,
    evidence_id: str,
    sensitivity: str,
    status: str = "complete",
    reachability: str | None = "external",
) -> DataAsset:
    fields = [_known_field("primary", sensitivity, evidence_id)]
    if status == "partial":
        fields.append(_unknown_field("unclassified", evidence_id))
    elif status == "unknown":
        fields = [_unknown_field("unclassified", evidence_id)]
    return DataAsset.model_validate(
        {
            "object_id": object_id,
            "inventory_ref": inventory_ref,
            "tenant_id": TENANT,
            "store_id": f"store:{inventory_ref}",
            "store_type": "bucket",
            "location": DataStoreLocation(
                provider="aws",
                region="eu-north-1",
                resource_ref=f"arn:aws:s3:::{inventory_ref}",
            ),
            "field_classifications": fields,
            "max_known_sensitivity": None if status == "unknown" else sensitivity,
            "classification_status": status,
            "flagged": status != "complete",
            "reachability_claim": (
                None
                if reachability is None
                else ReachabilityClaim(
                    reachability=reachability,
                    evidence_id=evidence_id,
                    reason=f"Known data reports {reachability} reachability.",
                )
            ),
            "observed_at": NOW,
            "evidence_id": evidence_id,
        }
    )


async def _inventory(
    rows: list[tuple[str, str]],
) -> InventoryIntelligenceEngine:
    engine = InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise"))
    await engine.ingest(
        reports=[
            {
                "id": inventory_ref,
                "asset_type": "data_store",
                "classification": classification,
                "lifecycle_state": "active",
                "ref": f"dspm:{inventory_ref}",
                "evidence_id": new_id("evd"),
            }
            for inventory_ref, classification in rows
        ],
        source=DiscoverySource(
            source_id=new_id("src"),
            reliability=0.9,
            health="ok",
            as_of=NOW,
        ),
        tenant_id=TENANT,
    )
    return engine


async def _evidence(store: InMemoryEvidenceStore, *, object_id: str) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="data.store_metadata",
            schema_version=1,
            subject=Subject(object_ids=[object_id]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=new_id("src"),
            method="dspm.metadata/v1",
            content={"metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_dspm_known_surface_contract(backend: str) -> None:
    inventory_ref = new_id("ast")
    unrelated_ref = new_id("ast")
    object_id = new_id("obj")
    evidence_id = new_id("evd")
    inventory = await _inventory([(inventory_ref, "pii"), (unrelated_ref, "internal")])
    async with _dspm_store(backend) as store:
        await store.put_asset(
            _asset(
                inventory_ref=inventory_ref,
                object_id=object_id,
                evidence_id=evidence_id,
                sensitivity="pii",
            )
        )
        source = DataStoreKnownSurfaceSource(
            InventoryKnownSurfaceSource(inventory),
            store,
        )

        rows = await source.list_known_surface(tenant_id=TENANT)
        by_ref = {row.asset_ref.ref_id: row for row in rows}

        assert set(by_ref) == {inventory_ref, unrelated_ref}
        assert len([row for row in rows if row.asset_ref.ref_id == inventory_ref]) == 1
        assert by_ref[inventory_ref].asset_ref.object_id == object_id
        assert by_ref[inventory_ref].reachability == "external"
        assert by_ref[unrelated_ref].reachability is None


async def test_dspm_surface_refuses_failure_or_repeated_cursor() -> None:
    asset = _asset(
        inventory_ref=new_id("ast"),
        object_id=new_id("obj"),
        evidence_id=new_id("evd"),
        sensitivity="pii",
    )
    upstream = StaticKnownSurfaceSource([])
    failing = DataStoreKnownSurfaceSource(
        upstream,
        cast(DSPMStore, _BrokenQueryStore()),
    )
    repeated = DataStoreKnownSurfaceSource(
        upstream,
        cast(DSPMStore, _BrokenQueryStore(asset, repeated=True)),
    )

    with pytest.raises(StoreUnavailable, match="source unavailable"):
        await failing.list_known_surface(tenant_id=TENANT)
    with pytest.raises(StoreUnavailable, match="repeated pagination cursor"):
        await repeated.list_known_surface(tenant_id=TENANT)


async def _analyze_definitions(
    backend: str,
    definitions: list[tuple[str, str, str | None]],
) -> list[DataExposure]:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    assets: list[DataAsset] = []
    for sensitivity, status, reachability in definitions:
        object_id = new_id("obj")
        evidence = await _evidence(evidence_store, object_id=object_id)
        assets.append(
            _asset(
                inventory_ref=new_id("ast"),
                object_id=object_id,
                evidence_id=evidence.id,
                sensitivity=sensitivity,
                status=status,
                reachability=reachability,
            )
        )
    inventory = await _inventory(
        [(asset.inventory_ref, asset.max_known_sensitivity or "unknown") for asset in assets]
    )

    async with _owner_stores(backend) as (dspm_store, exposure_store):
        for asset in assets:
            await dspm_store.put_asset(asset)
        source = DataStoreKnownSurfaceSource(
            InventoryKnownSurfaceSource(inventory),
            dspm_store,
        )
        trust = TrustEngine(registry=InMemorySourceReliabilityRegistry(default_reliability=0.8))
        exposure_owner = KnownDataExposureEngine(
            exposure_store,
            source,
            evidence_lookup=evidence_store,
            trust_provider=trust,
            mission_provider=_MissionProvider(),
        )
        engine = DSPMEngine(
            dspm_store,
            object_store=InMemoryObjectStore(mode="enterprise"),
            inventory=inventory,
            evidence_store=evidence_store,
            trust=trust,
            config=_config(),
            exposure_owner=exposure_owner,
        )

        results = await engine.analyze_exposure(tenant_id=TENANT)
        if isinstance(dspm_store, InMemoryDSPMStore):
            assert len(dspm_store._exposures) == len(results)
        else:
            postgres = cast(PostgresDSPMStore, dspm_store)
            async with postgres._pool.acquire() as connection:
                assert await connection.fetchval("SELECT count(*) FROM aq_dspm_exposure") == len(
                    results
                )
        return [result.model_copy(deep=True) for result in results]


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_dspm_exposure_intersection(backend: str) -> None:
    results = await _analyze_definitions(
        backend,
        [("pii", "complete", "external")],
    )

    assert len(results) == 1
    confirmed = results[0]
    assert confirmed.state == "confirmed"
    assert confirmed.sensitivity == "pii"
    assert confirmed.score is not None
    assert confirmed.derivation is not None


async def test_dspm_sensitivity_weights_exposure() -> None:
    results = await _analyze_definitions(
        "inmemory",
        [
            ("pii", "complete", "external"),
            ("secret", "complete", "external"),
        ],
    )
    confirmed = {result.sensitivity: result for result in results if result.state == "confirmed"}

    assert set(confirmed) == {"pii", "secret"}
    assert confirmed["pii"].score is not None
    assert confirmed["secret"].score is not None
    assert confirmed["secret"].score >= confirmed["pii"].score
    assert confirmed["pii"].derivation is not None
    assert confirmed["secret"].derivation is not None


async def test_dspm_unknown_exposure_states() -> None:
    results = await _analyze_definitions(
        "inmemory",
        [
            ("pii", "partial", "external"),
            ("public", "unknown", "external"),
            ("secret", "complete", None),
        ],
    )
    states = [result.state for result in results]

    assert states.count("confirmed") == 1
    assert states.count("classification_gap") == 2
    assert states.count("reachability_pending") == 1
    partial_id = results[0].data_asset_id
    assert {result.state for result in results if result.data_asset_id == partial_id} == {
        "confirmed",
        "classification_gap",
    }
    for result in results:
        if result.state == "confirmed":
            assert result.score is not None
            assert result.derivation is not None
        else:
            assert result.flagged is True
            assert result.score is None
            assert result.derivation is None
