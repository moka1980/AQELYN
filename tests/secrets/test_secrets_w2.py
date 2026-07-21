"""C-029 W2 acceptance tests for evidence-first crypto ingest and stores."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import (
    CryptoConfigInvalid,
    EvidenceNotFound,
    EvidenceTampered,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore, VerifyResult
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.secrets import (
    CertificateAsset,
    CertificateDescriptor,
    CryptoAssessment,
    CryptoConfig,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoQuery,
    CryptoScope,
    CryptoStore,
    InMemoryCryptoStore,
    PostgresCryptoStore,
    SecretAsset,
    SecretLocation,
    SecretScanDescriptor,
    SecretsIntelligenceEngine,
)
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    TrustEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000320201"
OTHER_TENANT = "018f0000-0000-7000-8000-000000320202"
ACTOR = ActorRef(actor_type="system", actor_id="crypto-w2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: CryptoStore
    evidence: InMemoryEvidenceStore
    registry: InMemorySourceReliabilityRegistry
    object_store: InMemoryObjectStore
    inventory_store: InMemoryAssetStore
    inventory: InventoryIntelligenceEngine
    engine: SecretsIntelligenceEngine


@asynccontextmanager
async def _harness(kind: str) -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: CryptoStore = InMemoryCryptoStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresCryptoStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_crypto_asset_revision, aq_crypto_asset_identity, "
                "aq_crypto_assessment RESTART IDENTITY CASCADE"
            )
        store = postgres
        closer = cast(_Closable, postgres)
    evidence = InMemoryEvidenceStore(mode="enterprise")
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    object_store = InMemoryObjectStore(mode="enterprise")
    inventory_store = InMemoryAssetStore(mode="enterprise")
    inventory = InventoryIntelligenceEngine(inventory_store)
    engine = SecretsIntelligenceEngine(
        store,
        object_store=object_store,
        inventory=inventory,
        evidence_store=evidence,
        trust=TrustEngine(registry=registry),
    )
    try:
        yield _Harness(
            store,
            evidence,
            registry,
            object_store,
            inventory_store,
            inventory,
            engine,
        )
    finally:
        if closer is not None:
            await closer.close()


def _fingerprint(index: int) -> str:
    return f"hmac-sha256:{index:064x}"


async def _evidence(
    store: InMemoryEvidenceStore,
    *,
    source_id: str,
    fingerprint: str,
    observed_at: datetime = NOW,
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="crypto_descriptor",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=observed_at,
            recorded_at=observed_at,
            collector=ACTOR,
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


async def _reliability(
    registry: InMemorySourceReliabilityRegistry,
    source_id: str,
    weight: float,
) -> None:
    await registry.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="W2 source-reliability fixture.",
            set_by=ACTOR,
            set_at=NOW,
        )
    )


def _secret_descriptor(
    *,
    fingerprint: str,
    source_id: str,
    evidence_id: str,
    kind: str = "api_key",
    observed_at: datetime = NOW,
) -> SecretScanDescriptor:
    return SecretScanDescriptor.model_validate(
        {
            "tenant_id": TENANT,
            "kind": kind,
            "fingerprint": fingerprint,
            "location": SecretLocation(
                kind="repository",
                resource_ref="repo://billing-api",
                path_hint="config/runtime.env",
                line=12,
            ),
            "source_id": source_id,
            "observed_at": observed_at,
            "evidence_id": evidence_id,
        }
    )


def _key_descriptor(
    *,
    fingerprint: str,
    source_id: str,
    evidence_id: str,
) -> CryptographicKeyDescriptor:
    return CryptographicKeyDescriptor(
        tenant_id=TENANT,
        external_key_ref="urn:aqelyn:key:billing-signing",
        fingerprint=fingerprint,
        algorithm="rsa",
        key_size=3072,
        usages=["signing"],
        last_rotated_at=NOW - timedelta(days=45),
        source_id=source_id,
        observed_at=NOW,
        evidence_id=evidence_id,
    )


def _certificate_descriptor(
    *,
    fingerprint: str,
    source_id: str,
    evidence_id: str,
) -> CertificateDescriptor:
    return CertificateDescriptor(
        tenant_id=TENANT,
        fingerprint=fingerprint,
        serial="01:23:45:67",
        subject="CN=api.example.test",
        issuer="CN=AQELYN Test CA",
        not_after=NOW + timedelta(days=90),
        source_id=source_id,
        observed_at=NOW,
        evidence_id=evidence_id,
    )


async def _owner_counts(harness: _Harness) -> tuple[int, int, int]:
    objects, _ = await harness.object_store.query(ObjectQuery(tenant_id=TENANT, limit=1000))
    inventory = await harness.inventory_store.query(tenant_id=TENANT, limit=1000)
    assets, _ = await harness.store.query_assets(CryptoQuery(tenant_id=TENANT, limit=1000))
    return len(objects), len(inventory), len(assets)


async def test_crypto_handed_in_only(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def blocked(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("network")
        raise AssertionError("crypto ingest must not open a network connection")

    async with _harness("inmemory") as harness:
        source_id = new_id("src")
        evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(1),
        )
        monkeypatch.setattr(socket, "socket", blocked)
        monkeypatch.setattr(socket, "create_connection", blocked)
        assets = await harness.engine.ingest_secrets(
            [
                _secret_descriptor(
                    fingerprint=_fingerprint(1),
                    source_id=source_id,
                    evidence_id=evidence.id,
                )
            ],
            tenant_id=TENANT,
        )
    assert len(assets) == 1
    assert attempts == []


class _UnavailableEvidence:
    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        del evidence_id, actor
        raise StoreUnavailable("evidence owner unavailable")

    async def verify(self, evidence_id: str) -> VerifyResult:
        del evidence_id
        raise StoreUnavailable("evidence owner unavailable")


@pytest.mark.parametrize("failure", ["missing", "tampered", "retriable"])
async def test_crypto_evidence_failure_not_safe(failure: str) -> None:
    async with _harness("inmemory") as harness:
        source_id = new_id("src")
        fingerprint = _fingerprint(2)
        evidence_id = new_id("evd")
        if failure == "tampered":
            evidence = await _evidence(
                harness.evidence,
                source_id=source_id,
                fingerprint=fingerprint,
            )
            evidence_id = evidence.id
            assert evidence.content is not None
            evidence.content["fingerprint"] = "tampered"
        if failure == "retriable":
            harness.engine.evidence_store = cast(EvidenceStore, _UnavailableEvidence())
        descriptor = _secret_descriptor(
            fingerprint=fingerprint,
            source_id=source_id,
            evidence_id=evidence_id,
        )
        expected = {
            "missing": EvidenceNotFound,
            "tampered": EvidenceTampered,
            "retriable": StoreUnavailable,
        }[failure]
        with pytest.raises(expected):
            await harness.engine.ingest_secrets([descriptor], tenant_id=TENANT)
        assert await _owner_counts(harness) == (0, 0, 0)


async def test_crypto_batch_validates_all_evidence_before_owner_writes() -> None:
    async with _harness("inmemory") as harness:
        source_id = new_id("src")
        evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(3),
        )
        descriptors = [
            _secret_descriptor(
                fingerprint=_fingerprint(3),
                source_id=source_id,
                evidence_id=evidence.id,
            ),
            _secret_descriptor(
                fingerprint=_fingerprint(4),
                source_id=source_id,
                evidence_id=new_id("evd"),
            ),
        ]
        with pytest.raises(EvidenceNotFound):
            await harness.engine.ingest_secrets(descriptors, tenant_id=TENANT)
        assert await _owner_counts(harness) == (0, 0, 0)


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_crypto_assets_to_inventory(backend: str) -> None:
    async with _harness(backend) as harness:
        key_source = new_id("src")
        cert_source = new_id("src")
        key_evidence = await _evidence(
            harness.evidence,
            source_id=key_source,
            fingerprint=_fingerprint(10),
        )
        cert_evidence = await _evidence(
            harness.evidence,
            source_id=cert_source,
            fingerprint=_fingerprint(11),
        )
        assets = await harness.engine.ingest_crypto_assets(
            [
                _key_descriptor(
                    fingerprint=_fingerprint(10),
                    source_id=key_source,
                    evidence_id=key_evidence.id,
                )
            ],
            [
                _certificate_descriptor(
                    fingerprint=_fingerprint(11),
                    source_id=cert_source,
                    evidence_id=cert_evidence.id,
                )
            ],
            tenant_id=TENANT,
        )
        assert len(assets) == 2
        for asset in assets:
            object_prefix, object_payload = parse_id(asset.object_id)
            inventory_prefix, inventory_payload = parse_id(asset.inventory_ref)
            assert object_prefix == "obj"
            assert inventory_prefix == "ast"
            assert object_payload == inventory_payload
            assert asset.object_id != asset.inventory_ref
            assert await harness.object_store.get(asset.object_id) is not None
            assert await harness.inventory_store.get(asset.inventory_ref, tenant_id=TENANT)
        key = cast(CryptographicKey, assets[0])
        certificate = cast(CertificateAsset, assets[1])
        assert key.last_rotated_at == NOW - timedelta(days=45)
        assert key.observed_at == NOW
        assert certificate.observed_at == NOW


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_crypto_reconcile_uses_trust_and_retains_conflict(backend: str) -> None:
    async with _harness(backend) as harness:
        high_source = new_id("src")
        low_source = new_id("src")
        fingerprint = _fingerprint(20)
        high_evidence = await _evidence(
            harness.evidence,
            source_id=high_source,
            fingerprint=fingerprint,
        )
        low_evidence = await _evidence(
            harness.evidence,
            source_id=low_source,
            fingerprint=fingerprint,
            observed_at=NOW + timedelta(minutes=5),
        )
        await _reliability(harness.registry, high_source, 0.9)
        await _reliability(harness.registry, low_source, 0.2)
        first = (
            await harness.engine.ingest_secrets(
                [
                    _secret_descriptor(
                        fingerprint=fingerprint,
                        source_id=high_source,
                        evidence_id=high_evidence.id,
                        kind="api_key",
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        second = (
            await harness.engine.ingest_secrets(
                [
                    _secret_descriptor(
                        fingerprint=fingerprint,
                        source_id=low_source,
                        evidence_id=low_evidence.id,
                        kind="token",
                        observed_at=NOW + timedelta(minutes=5),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]

        assert second.id == first.id
        assert second.object_id == first.object_id
        assert second.inventory_ref == first.inventory_ref
        assert second.kind == "api_key"
        assert second.source_id == high_source
        assert len(second.conflicts) == 1
        conflict = second.conflicts[0]
        assert conflict.fields == ["kind"]
        assert not conflict.unresolved
        assert conflict.resolved_by == high_source
        assert {candidate.source_id for candidate in conflict.candidates} == {
            high_source,
            low_source,
        }
        stored = await harness.store.get_asset_by_fingerprint(
            "secret", fingerprint, tenant_id=TENANT
        )
        assert stored == second
        obj = await harness.object_store.get(second.object_id)
        assert obj is not None
        assert obj.attributes["secret_kind"] == "api_key"
        inventory = await harness.inventory_store.get(second.inventory_ref, tenant_id=TENANT)
        assert inventory is not None
        assert inventory.discovery_source == high_source


def _direct_secret(*, asset_id: str, fingerprint: str, tenant_id: str = TENANT) -> SecretAsset:
    return SecretAsset(
        id=asset_id,
        tenant_id=tenant_id,
        object_id=new_id("obj"),
        inventory_ref=new_id("ast"),
        kind="api_key",
        fingerprint=fingerprint,
        location=SecretLocation(kind="configuration", resource_ref="app://billing"),
        rotation={"reason": "Not assessed."},
        claim_confidence=0.5,
        source_id=new_id("src"),
        detected_at=NOW,
        evidence_id=new_id("evd"),
    )


def _direct_key(*, asset_id: str, fingerprint: str, tenant_id: str = TENANT) -> CryptographicKey:
    return CryptographicKey(
        id=asset_id,
        tenant_id=tenant_id,
        object_id=new_id("obj"),
        inventory_ref=new_id("ast"),
        external_key_ref=f"urn:key:{fingerprint[-8:]}",
        fingerprint=fingerprint,
        algorithm="rsa",
        key_size=2048,
        usages=["signing"],
        strength={"reason": "Not assessed."},
        rotation={"reason": "Not assessed."},
        claim_confidence=0.5,
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_crypto_store_contract(backend: str) -> None:
    async with _harness(backend) as harness:
        key_ids = sorted(new_id("cky") for _ in range(100))
        secret_ids = sorted(new_id("sct") for _ in range(50))
        for index, asset_id in enumerate(key_ids):
            await harness.store.put_asset(
                _direct_key(asset_id=asset_id, fingerprint=_fingerprint(1000 + index))
            )
        for index, asset_id in enumerate(secret_ids):
            await harness.store.put_asset(
                _direct_secret(asset_id=asset_id, fingerprint=_fingerprint(2000 + index))
            )

        exact, exact_cursor = await harness.store.query_assets(
            CryptoQuery(tenant_id=TENANT, kind="secret", limit=50)
        )
        assert [asset.id for asset in exact] == secret_ids
        assert exact_cursor is None

        paged: list[str] = []
        cursor: str | None = None
        while True:
            rows, cursor = await harness.store.query_assets(
                CryptoQuery(tenant_id=TENANT, kind="secret", limit=25, cursor=cursor)
            )
            paged.extend(asset.id for asset in rows)
            if cursor is None:
                break
        assert paged == secret_ids

        first = cast(SecretAsset, exact[0])
        first.location.path_hint = "mutated-copy"
        reread = await harness.store.get_asset(first.id, tenant_id=TENANT)
        assert isinstance(reread, SecretAsset)
        assert reread.location.path_hint is None
        assert await harness.store.get_asset(first.id, tenant_id=OTHER_TENANT) is None

        updated = reread.model_copy(update={"claim_confidence": 0.75}, deep=True)
        await harness.store.put_asset(updated)
        latest = await harness.store.get_asset(first.id, tenant_id=TENANT)
        assert latest is not None
        assert latest.claim_confidence == 0.75
        with pytest.raises(CryptoConfigInvalid):
            await harness.store.put_asset(
                _direct_secret(asset_id=new_id("sct"), fingerprint=first.fingerprint)
            )

        assessment = CryptoAssessment(
            tenant_id=TENANT,
            run_at=NOW,
            scope=CryptoScope(),
        )
        await harness.store.put_assessment(assessment)
        with pytest.raises(OptimisticConcurrencyConflict):
            await harness.store.put_assessment(assessment)

        if isinstance(harness.store, PostgresCryptoStore):
            revisions = await harness.store._pool.fetchval(
                "SELECT count(*) FROM aq_crypto_asset_revision WHERE id=$1",
                first.id,
            )
            assert revisions == 2
            with pytest.raises(Exception, match="append-only"):
                await harness.store._pool.execute(
                    "UPDATE aq_crypto_asset_revision SET kind='key' WHERE id=$1",
                    first.id,
                )


async def test_crypto_work_budget() -> None:
    async with _harness("inmemory") as harness:
        ids = sorted(new_id("sct") for _ in range(5))
        for index, asset_id in enumerate(ids):
            await harness.store.put_asset(
                _direct_secret(asset_id=asset_id, fingerprint=_fingerprint(3000 + index))
            )
        bounded = SecretsIntelligenceEngine(
            harness.store,
            object_store=harness.object_store,
            inventory=harness.inventory,
            evidence_store=harness.evidence,
            trust=TrustEngine(registry=harness.registry),
            config=CryptoConfig(batch_size=2, max_work=3),
        )
        assets, truncated = await bounded._bounded_assets(tenant_id=TENANT)
        assert [asset.id for asset in assets] == ids[:3]
        assert truncated


class _RepeatingCursorStore(InMemoryCryptoStore):
    async def query_assets(
        self,
        query: CryptoQuery,
    ) -> tuple[list[SecretAsset], str | None]:
        rows, _ = await super().query_assets(query)
        next_cursor = query.cursor or rows[-1].id
        return [cast(SecretAsset, item) for item in rows], next_cursor


async def test_crypto_repeated_cursor_refused() -> None:
    store = _RepeatingCursorStore(mode="enterprise")
    await store.put_asset(_direct_secret(asset_id=new_id("sct"), fingerprint=_fingerprint(4000)))
    engine = SecretsIntelligenceEngine(
        store,
        object_store=InMemoryObjectStore(mode="enterprise"),
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise")),
        evidence_store=InMemoryEvidenceStore(mode="enterprise"),
        trust=TrustEngine(),
        config=CryptoConfig(batch_size=1, max_work=3),
    )
    with pytest.raises(StoreUnavailable, match="repeated pagination cursor"):
        await engine._bounded_assets(tenant_id=TENANT)
