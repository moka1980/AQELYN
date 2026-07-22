"""C-029 W5 acceptance tests for service, events, and factory wiring."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import EventSchemaValidationError
from aqelyn.dspm import DataStoreKnownSurfaceSource
from aqelyn.events import EventTypeRegistry, Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.ispm import IdentityKnownSurfaceSource
from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime, create_runtime
from aqelyn.kernel.service import HealthStatus
from aqelyn.secrets import (
    CRYPTO_EVENTS,
    CryptographicKeyDescriptor,
    CryptoKnownSurfaceSource,
    InMemoryCryptoStore,
    PostgresCryptoStore,
    SecretsIntelligenceEngine,
    SecretsIntelligenceService,
    register_crypto_events,
)
from aqelyn.sspm import SaaSIntegrationKnownSurfaceSource

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 21, 15, 0, tzinfo=UTC)
SYSTEM = ActorRef(actor_type="system", actor_id="secrets-w5-test")
TENANT = "018f0000-0000-7000-8000-000000320501"
CRYPTO_EVENT_TYPES = {
    "aqelyn.crypto.secret_detected",
    "aqelyn.crypto.certificate_expiring",
    "aqelyn.crypto.weak_key_detected",
    "aqelyn.crypto.lifecycle_unknown",
}


async def _runtime(backend: str, *, tenant_mode: str) -> Runtime:
    config = AQELYNConfig(
        backend=backend,
        tenant_mode=tenant_mode,
        secrets_expiry_warning_days=17,
        secrets_max_work=1_234,
    )
    if backend == "memory":
        return create_inmemory_runtime(config)
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    return await create_runtime(config.model_copy(update={"database_url": PG_URL}))


async def _descriptor_evidence(
    runtime: Runtime,
    *,
    fingerprint: str,
    source_id: str,
    tenant_id: str | None,
) -> EvidenceRecord:
    return await runtime.evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="crypto_descriptor",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=SYSTEM,
            source_id=source_id,
            method="handed_in_descriptor",
            content={"fingerprint": fingerprint, "descriptor_kind": "metadata_only"},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


async def _clear_crypto_store(runtime: Runtime, *, backend: str) -> None:
    if backend != "postgres":
        return
    store = cast(Any, runtime.secrets_store)
    async with store._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE aq_crypto_assessment, aq_crypto_asset_revision, "
            "aq_crypto_asset_identity RESTART IDENTITY CASCADE"
        )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
@pytest.mark.parametrize("tenant_mode", ["local", "enterprise"])
async def test_crypto_service_health_and_owner_connectivity(
    backend: str,
    tenant_mode: str,
) -> None:
    runtime = await _runtime(backend, tenant_mode=tenant_mode)
    await _clear_crypto_store(runtime, backend=backend)
    service = runtime.kernel.get_service("secrets_engine")
    tenant_id = TENANT if tenant_mode == "enterprise" else None

    assert isinstance(runtime.secrets_engine, SecretsIntelligenceEngine)
    assert isinstance(runtime.secrets_engine_service, SecretsIntelligenceService)
    assert runtime.secrets_engine_service is service
    assert runtime.secrets_engine_service.engine is runtime.secrets_engine
    assert runtime.secrets_engine.store is runtime.secrets_store
    assert runtime.secrets_engine.object_store is runtime.object_store
    assert runtime.secrets_engine.inventory is runtime.inventory_engine
    assert runtime.secrets_engine.evidence_store is runtime.evidence_store
    assert runtime.secrets_engine.trust is runtime.trust_engine
    assert runtime.secrets_engine.exposure_owner is runtime.exposure_engine
    assert runtime.secrets_engine.compliance_owner is runtime.compliance_engine
    assert runtime.secrets_engine.finding_store is runtime.finding_store
    assert runtime.secrets_engine.workflow_engine is runtime.workflow_engine
    assert runtime.secrets_engine.config.expiry_warning_days == 17
    assert runtime.secrets_engine.config.max_work == 1_234
    if backend == "memory":
        assert isinstance(runtime.secrets_store, InMemoryCryptoStore)
    else:
        assert isinstance(runtime.secrets_store, PostgresCryptoStore)

    source = runtime.secrets_engine_service.known_surface_source
    assert isinstance(source, CryptoKnownSurfaceSource)
    identity_source = runtime.exposure_engine.source
    assert isinstance(identity_source, IdentityKnownSurfaceSource)
    assert identity_source.upstream is source
    assert source.store is runtime.secrets_store
    assert isinstance(source.upstream, SaaSIntegrationKnownSurfaceSource)
    assert isinstance(source.upstream.upstream, DataStoreKnownSurfaceSource)
    assert set(runtime.secrets_engine_service.owner_services) == {
        "inventory_engine",
        "exposure_engine",
        "compliance_engine",
        "trust_engine",
        "workflow_engine",
    }
    assert tuple(service.dependencies) == (
        "object_store",
        "inventory_engine",
        "exposure_engine",
        "compliance_engine",
        "trust_engine",
        "workflow_engine",
    )

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["crypto_store"] == "healthy"
    assert pre_start.dependencies["known_surface_source"] == "healthy"
    assert pre_start.dependencies["authenticity_verifier"] == "unconfigured"

    if tenant_mode == "local":
        await runtime.kernel.start()
    else:
        await service.start()
    try:
        health = await service.health()
        assert health.status == "degraded"
        assert health.ready is True
        assert health.dependencies["crypto_store"] == "healthy"
        assert health.dependencies["known_surface_source"] == "healthy"
        assert health.dependencies["authenticity_verifier"] == "unconfigured"

        source_id = new_id("src")
        fingerprint = f"hmac-sha256:{new_id('src').split('_', 1)[1]:0>64}"
        evidence = await _descriptor_evidence(
            runtime,
            fingerprint=fingerprint,
            source_id=source_id,
            tenant_id=tenant_id,
        )
        [asset] = await service.ingest_crypto_assets(
            [
                CryptographicKeyDescriptor(
                    tenant_id=tenant_id,
                    external_key_ref=f"urn:aqelyn:key:{source_id}",
                    fingerprint=fingerprint,
                    algorithm="rsa",
                    key_size=4096,
                    usages=["signing"],
                    last_rotated_at=NOW,
                    source_id=source_id,
                    observed_at=NOW,
                    evidence_id=evidence.id,
                )
            ],
            [],
            tenant_id=tenant_id,
        )

        rows = await runtime.exposure_engine.source.list_known_surface(tenant_id=tenant_id)
        matches = [row for row in rows if row.asset_ref.ref_id == asset.inventory_ref]
        assert len(matches) == 1
        assert matches[0].asset_ref.object_id == asset.object_id
        assert matches[0].classification == "crypto_key"
        assert matches[0].reachability is None
        assert any(item.evidence_id == evidence.id for item in matches[0].basis)
    finally:
        await _clear_crypto_store(runtime, backend=backend)
        if tenant_mode == "local":
            await runtime.kernel.stop()
        else:
            await service.stop()


def test_crypto_events_value_free() -> None:
    registry = EventTypeRegistry(with_core=False)
    register_crypto_events(registry)

    assert set(CRYPTO_EVENTS) == CRYPTO_EVENT_TYPES
    assert len(CRYPTO_EVENTS) == 4
    assert all(registry.is_registered(event_type) for event_type in CRYPTO_EVENT_TYPES)
    for event_type in CRYPTO_EVENT_TYPES:
        registry.validate(
            event_type,
            {
                "asset_id": new_id("cky"),
                "fingerprint": f"hmac-sha256:{'a' * 64}",
                "kind": "private_key",
                "lifecycle": {"status": "unknown", "reason": "not assessed"},
                "evidence_ids": [new_id("evd")],
            },
        )
        with pytest.raises(EventSchemaValidationError) as caught:
            registry.validate(
                event_type,
                {"asset_id": new_id("cky"), "nested": {"raw-value": "do-not-leak"}},
            )
        assert "do-not-leak" not in str(caught.value)


def test_crypto_import_isolation() -> None:
    source = str(Path(__file__).resolve().parents[2] / "src")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source, environment.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import aqelyn.secrets; import aqelyn.kernel.factory",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


class _UnavailableOwner:
    async def health(self) -> HealthStatus:
        return HealthStatus(status="unavailable", ready=False, detail="forced owner outage")


async def test_crypto_health_refuses_invalid_config_and_owner_outage() -> None:
    runtime = create_inmemory_runtime()
    runtime.secrets_engine.config = runtime.secrets_engine.config.model_copy(update={"max_work": 0})

    invalid = await runtime.secrets_engine_service.health()

    assert invalid.status == "unavailable"
    assert invalid.ready is False
    assert invalid.detail == "max_work must be >= 1"

    runtime = create_inmemory_runtime()
    runtime.secrets_engine_service.owner_services["exposure_engine"] = _UnavailableOwner()

    unavailable = await runtime.secrets_engine_service.health()

    assert unavailable.status == "unavailable"
    assert unavailable.ready is False
    assert "exposure_engine: forced owner outage" in (unavailable.detail or "")
