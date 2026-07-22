"""C-028 P5 acceptance tests for DSPM service, events, and factory wiring."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.dspm import (
    DSPM_EVENTS,
    DataStoreDescriptor,
    DataStoreKnownSurfaceSource,
    DataStoreLocation,
    DSPMEngine,
    DSPMService,
    InMemoryDSPMStore,
    PostgresDSPMStore,
    ReachabilityClaim,
    register_dspm_events,
)
from aqelyn.events import EventTypeRegistry, Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.inventory import InventoryKnownSurfaceSource
from aqelyn.ispm import IdentityKnownSurfaceSource
from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime, create_runtime
from aqelyn.kernel.service import HealthStatus
from aqelyn.secrets import CryptoKnownSurfaceSource
from aqelyn.sspm import SaaSIntegrationKnownSurfaceSource

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)
SYSTEM = ActorRef(actor_type="system", actor_id="dspm-p5-test")
TENANT = "018f0000-0000-7000-8000-000000310501"
DSPM_EVENT_TYPES = {
    "aqelyn.data.store_classified",
    "aqelyn.data.exposure_detected",
    "aqelyn.data.classification_conflict",
}


async def _runtime(backend: str, *, tenant_mode: str = "local") -> Runtime:
    config = AQELYNConfig(backend=backend, tenant_mode=tenant_mode)
    if backend == "memory":
        return create_inmemory_runtime(config)
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    return await create_runtime(config.model_copy(update={"database_url": PG_URL}))


async def _descriptor_evidence(
    runtime: Runtime,
    *,
    store_id: str,
    tenant_id: str | None = None,
) -> EvidenceRecord:
    return await runtime.evidence_store.add(
        EvidenceRecord(
            id="",
            evidence_type="data.store_descriptor",
            schema_version=1,
            subject=Subject(),
            collected_at=NOW,
            recorded_at=NOW,
            collector=SYSTEM,
            source_id=new_id("src"),
            method="dspm.metadata_descriptor/v1",
            content={"metadata_only": True, "store_id": store_id},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
            tenant_id=tenant_id,
        )
    )


@pytest.mark.parametrize(
    ("backend", "tenant_mode"),
    [("memory", "local"), ("postgres", "local"), ("memory", "enterprise")],
)
async def test_dspm_service_health(backend: str, tenant_mode: str) -> None:
    runtime = await _runtime(backend, tenant_mode=tenant_mode)
    service = runtime.kernel.get_service("dspm_engine")

    if backend == "memory":
        assert isinstance(runtime.dspm_store, InMemoryDSPMStore)
    else:
        assert isinstance(runtime.dspm_store, PostgresDSPMStore)
    assert isinstance(runtime.dspm_engine, DSPMEngine)
    assert isinstance(runtime.dspm_engine_service, DSPMService)
    assert runtime.dspm_engine_service is service
    assert runtime.dspm_engine_service.engine is runtime.dspm_engine
    assert runtime.dspm_engine.store is runtime.dspm_store
    assert runtime.dspm_engine.object_store is runtime.object_store
    assert runtime.dspm_engine.inventory is runtime.inventory_engine
    assert runtime.dspm_engine.evidence_store is runtime.evidence_store
    assert runtime.dspm_engine.trust is runtime.trust_engine
    assert runtime.dspm_engine.exposure_owner is runtime.exposure_engine
    assert runtime.dspm_engine.iag_owner is runtime.iag_engine
    assert runtime.dspm_engine.compliance_owner is runtime.compliance_engine
    assert runtime.dspm_engine.finding_store is runtime.finding_store
    assert runtime.dspm_engine.workflow_engine is runtime.workflow_engine
    assert tuple(service.dependencies) == (
        "object_store",
        "inventory_engine",
        "exposure_engine",
        "iag_engine",
        "compliance_engine",
        "trust_engine",
        "workflow_engine",
    )
    assert set(service.owner_services) == {
        "inventory_engine",
        "exposure_engine",
        "iag_engine",
        "compliance_engine",
        "trust_engine",
        "workflow_engine",
    }
    assert all(runtime.event_bus.registry.is_registered(name) for name in DSPM_EVENT_TYPES)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["dspm_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["known_surface_source"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"

    if tenant_mode == "local":
        await runtime.kernel.start()
        try:
            state = await runtime.kernel.health()
            health = state.services["dspm_engine"]
            assert health.status == "healthy"
            assert health.ready is True
            for dependency in service.dependencies:
                assert state.services[dependency].ready is True
            assert state.services["_kernel"].ready is True
        finally:
            await runtime.kernel.stop()
    else:
        await service.start()
        health = await service.health()
        assert health.status == "degraded"
        assert health.ready is True
        assert "exposure_engine" in (health.detail or "")
        await service.stop()


@pytest.mark.parametrize(
    ("backend", "tenant_mode"),
    [("memory", "local"), ("postgres", "local"), ("memory", "enterprise")],
)
async def test_dspm_factory_owner_connectivity(backend: str, tenant_mode: str) -> None:
    runtime = await _runtime(backend, tenant_mode=tenant_mode)
    tenant_id = TENANT if tenant_mode == "enterprise" else None
    service = runtime.dspm_engine_service
    source = service.known_surface_source
    assert isinstance(source, DataStoreKnownSurfaceSource)
    assert isinstance(source.upstream, InventoryKnownSurfaceSource)
    assert source.store is runtime.dspm_store
    assert source.upstream.inventory is runtime.inventory_engine
    identity_source = runtime.exposure_engine.source
    assert isinstance(identity_source, IdentityKnownSurfaceSource)
    crypto_source = identity_source.upstream
    assert isinstance(crypto_source, CryptoKnownSurfaceSource)
    assert isinstance(crypto_source.upstream, SaaSIntegrationKnownSurfaceSource)
    assert crypto_source.upstream.upstream is source

    if tenant_mode == "local":
        await runtime.kernel.start()
    try:
        store_id = f"p5-store-{new_id('src')}"
        evidence = await _descriptor_evidence(
            runtime,
            store_id=store_id,
            tenant_id=tenant_id,
        )
        [asset] = await service.ingest_store(
            [
                DataStoreDescriptor(
                    store_id=store_id,
                    tenant_id=tenant_id,
                    store_type="bucket",
                    location=DataStoreLocation(
                        provider="aws",
                        region="eu-north-1",
                        resource_ref=f"arn:aws:s3:::{store_id}",
                    ),
                    reachability_claim=ReachabilityClaim(
                        reachability="external",
                        evidence_id=evidence.id,
                        reason=("The handed-in control-plane record reports public reachability."),
                    ),
                    source_id=evidence.source_id,
                    observed_at=NOW,
                    evidence_id=evidence.id,
                )
            ],
            tenant_id=tenant_id,
        )

        inventory = await runtime.inventory_engine.inventory(tenant_id=tenant_id)
        assert asset.inventory_ref in inventory.assets
        known = await source.list_known_surface(tenant_id=tenant_id)
        known_row = next(row for row in known if row.asset_ref.ref_id == asset.inventory_ref)
        assert known_row.asset_ref.object_id == asset.object_id
        assert known_row.reachability == "external"

        derived = await runtime.exposure_engine.derive_surface(tenant_id=tenant_id)
        exposure = next(row for row in derived if row.asset_ref.ref_id == asset.inventory_ref)
        assert exposure.asset_ref.object_id == asset.object_id
        assert exposure.exposure_level == "high"
    finally:
        if tenant_mode == "local":
            await runtime.kernel.stop()


def test_dspm_event_registration_and_import_isolation() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_dspm_events(registry)

    assert set(DSPM_EVENTS) == DSPM_EVENT_TYPES
    assert len(DSPM_EVENTS) == 3
    assert all(registry.is_registered(event_type) for event_type in DSPM_EVENT_TYPES)
    assert importlib.import_module("aqelyn.dspm").DSPMService is DSPMService
    assert hasattr(importlib.import_module("aqelyn.kernel.factory"), "create_runtime")


async def test_dspm_health_reports_invalid_config() -> None:
    runtime = create_inmemory_runtime()
    runtime.dspm_engine.config = runtime.dspm_engine.config.model_copy(update={"batch_size": 0})

    health = await runtime.dspm_engine_service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail == "DSPM config limit must be >= 1"


class _UnavailableOwner:
    async def health(self) -> HealthStatus:
        return HealthStatus(status="unavailable", ready=False, detail="forced owner outage")


@pytest.mark.parametrize(
    ("dependency", "detail"),
    [
        ("store", "DSPM store unavailable"),
        ("classifier_evidence", "DSPM classifier evidence unavailable"),
        ("known_surface", "DSPM known surface unavailable"),
        ("iag", "iag_engine"),
        ("governance", "compliance_engine"),
        ("findings", "DSPM finding store unavailable"),
        ("workflow", "DSPM Workflow owner unavailable"),
    ],
)
async def test_dspm_health_reports_required_dependency(
    dependency: str,
    detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_inmemory_runtime()

    async def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise StoreUnavailable("forced dependency outage")

    if dependency == "store":
        monkeypatch.setattr(runtime.dspm_store, "query_assets", unavailable)
    elif dependency == "classifier_evidence":
        monkeypatch.setattr(runtime.evidence_store, "verify", unavailable)
    elif dependency == "known_surface":
        monkeypatch.setattr(
            runtime.dspm_engine_service.known_surface_source,
            "list_known_surface",
            unavailable,
        )
    elif dependency == "iag":
        runtime.dspm_engine_service.owner_services["iag_engine"] = _UnavailableOwner()
    elif dependency == "governance":
        runtime.dspm_engine_service.owner_services["compliance_engine"] = _UnavailableOwner()
    elif dependency == "findings":
        runtime.dspm_engine.finding_store = None
    else:
        runtime.dspm_engine.workflow_engine = None

    health = await runtime.dspm_engine_service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert detail in (health.detail or "")
