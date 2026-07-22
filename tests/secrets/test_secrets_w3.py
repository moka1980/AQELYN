"""C-029 W3 acceptance tests for lifecycle and two-stage verification."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    CryptoConfigInvalid,
    EvidenceNotFound,
    EvidenceTampered,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore, VerifyResult
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.objects import InMemoryObjectStore
from aqelyn.secrets import (
    AuthenticityCheck,
    CertificateAsset,
    CertificateDescriptor,
    CryptoAssessment,
    CryptoConfig,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoStore,
    InMemoryCryptoStore,
    PostgresCryptoStore,
    SecretLocation,
    SecretScanDescriptor,
    SecretsIntelligenceEngine,
)
from aqelyn.secrets.lifecycle import CertificateAuthenticityVerifier
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime.now(UTC)
TENANT = "018f0000-0000-7000-8000-000000320301"
ACTOR = ActorRef(actor_type="system", actor_id="crypto-w3-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: CryptoStore
    evidence: InMemoryEvidenceStore
    engine: SecretsIntelligenceEngine


@asynccontextmanager
async def _harness(
    kind: str,
    *,
    verifier: CertificateAuthenticityVerifier | None = None,
    config: CryptoConfig | None = None,
) -> AsyncIterator[_Harness]:
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
    engine = SecretsIntelligenceEngine(
        store,
        object_store=InMemoryObjectStore(mode="enterprise"),
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise")),
        evidence_store=evidence,
        trust=TrustEngine(registry=InMemorySourceReliabilityRegistry(default_reliability=0.8)),
        authenticity_verifier=verifier,
        config=config,
        actor=ACTOR,
    )
    try:
        yield _Harness(store=store, evidence=evidence, engine=engine)
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
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="crypto_descriptor",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=NOW,
            recorded_at=NOW,
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


def _certificate(
    *,
    source_id: str,
    evidence_id: str,
    fingerprint: str,
    not_after: datetime | None,
) -> CertificateDescriptor:
    return CertificateDescriptor(
        tenant_id=TENANT,
        fingerprint=fingerprint,
        serial="01:23:45",
        subject="CN=service.internal",
        issuer="CN=AQELYN Test CA",
        not_after=not_after,
        source_id=source_id,
        observed_at=NOW,
        evidence_id=evidence_id,
    )


def _key(
    *,
    source_id: str,
    evidence_id: str,
    fingerprint: str,
    algorithm: str | None,
    key_size: int | None,
    last_rotated_at: datetime | None,
) -> CryptographicKeyDescriptor:
    return CryptographicKeyDescriptor(
        tenant_id=TENANT,
        external_key_ref=f"urn:aqelyn:key:{fingerprint[-8:]}",
        fingerprint=fingerprint,
        algorithm=algorithm,
        key_size=key_size,
        usages=["signing"],
        last_rotated_at=last_rotated_at,
        source_id=source_id,
        observed_at=NOW,
        evidence_id=evidence_id,
    )


def _secret(
    *,
    source_id: str,
    evidence_id: str,
    fingerprint: str,
) -> SecretScanDescriptor:
    return SecretScanDescriptor(
        tenant_id=TENANT,
        kind="api_key",
        fingerprint=fingerprint,
        location=SecretLocation(
            kind="runtime_reference",
            resource_ref="urn:aqelyn:runtime:billing-api",
        ),
        source_id=source_id,
        observed_at=NOW,
        evidence_id=evidence_id,
    )


@dataclass
class _Verifier:
    status: str = "valid"
    fingerprint: str | None = None
    evidence_id: str | None = None
    unavailable: bool = False
    calls: int = 0

    async def verify(self, certificate: CertificateDescriptor) -> AuthenticityCheck:
        self.calls += 1
        if self.unavailable:
            raise StoreUnavailable("certificate authenticity owner unavailable")
        return AuthenticityCheck(
            certificate_fingerprint=self.fingerprint or certificate.fingerprint,
            basis_evidence_id=self.evidence_id or certificate.evidence_id,
            status=self.status,
            reason=f"Typed verifier returned {self.status} for the bound certificate.",
        )


class _UnavailableEvidence:
    async def add(self, record: EvidenceRecord) -> EvidenceRecord:
        del record
        raise StoreUnavailable("evidence owner unavailable")

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        del evidence_id, actor
        raise StoreUnavailable("evidence owner unavailable")

    async def verify(self, evidence_id: str) -> VerifyResult:
        del evidence_id
        raise StoreUnavailable("evidence owner unavailable")


class _MissingEvidence(_UnavailableEvidence):
    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        del actor
        raise EvidenceNotFound(f"evidence not found: {evidence_id}")


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_crypto_conformance_lifecycle(kind: str) -> None:
    async with _harness(kind) as harness:
        source_id = new_id("src")
        evidences = [
            await _evidence(
                harness.evidence,
                source_id=source_id,
                fingerprint=_fingerprint(index),
            )
            for index in range(100, 103)
        ]
        [secret] = await harness.engine.ingest_secrets(
            [
                _secret(
                    source_id=source_id,
                    evidence_id=evidences[0].id,
                    fingerprint=_fingerprint(100),
                )
            ],
            tenant_id=TENANT,
        )
        assets = await harness.engine.ingest_crypto_assets(
            [
                _key(
                    source_id=source_id,
                    evidence_id=evidences[1].id,
                    fingerprint=_fingerprint(101),
                    algorithm="rsa",
                    key_size=3072,
                    last_rotated_at=NOW - timedelta(days=20),
                )
            ],
            [
                _certificate(
                    source_id=source_id,
                    evidence_id=evidences[2].id,
                    fingerprint=_fingerprint(102),
                    not_after=NOW + timedelta(days=90),
                )
            ],
            tenant_id=TENANT,
        )
        key = next(asset for asset in assets if isinstance(asset, CryptographicKey))
        certificate = next(asset for asset in assets if isinstance(asset, CertificateAsset))

        checked_key = await harness.engine.assess_key(key.id, tenant_id=TENANT)
        checked_certificate = await harness.engine.assess_certificate(
            certificate.id,
            tenant_id=TENANT,
        )

        assert secret.kind == "api_key"
        assert secret.rotation.status == "unknown"
        assert checked_key.strength.status == "valid"
        assert checked_key.rotation.status == "valid"
        assert checked_certificate.expiry.status == "valid"
        assert checked_certificate.integrity.status == "valid"
        assert checked_certificate.chain.status == "unknown"
        assert checked_certificate.revocation.status == "unknown"
        assert checked_certificate.authenticity.status == "unknown"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_crypto_unknown_not_safe(kind: str) -> None:
    async with _harness(kind) as harness:
        source_id = new_id("src")
        unknown_key_evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(1),
        )
        weak_key_evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(2),
        )
        certificate_evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(3),
        )
        assets = await harness.engine.ingest_crypto_assets(
            [
                _key(
                    source_id=source_id,
                    evidence_id=unknown_key_evidence.id,
                    fingerprint=_fingerprint(1),
                    algorithm="future-kem",
                    key_size=4096,
                    last_rotated_at=None,
                ),
                _key(
                    source_id=source_id,
                    evidence_id=weak_key_evidence.id,
                    fingerprint=_fingerprint(2),
                    algorithm="sha1",
                    key_size=4096,
                    last_rotated_at=NOW - timedelta(days=500),
                ),
            ],
            [
                _certificate(
                    source_id=source_id,
                    evidence_id=certificate_evidence.id,
                    fingerprint=_fingerprint(3),
                    not_after=None,
                )
            ],
            tenant_id=TENANT,
        )
        keys = [asset for asset in assets if isinstance(asset, CryptographicKey)]
        certificate = next(asset for asset in assets if isinstance(asset, CertificateAsset))
        unknown_key = await harness.engine.assess_key(keys[0].id, tenant_id=TENANT)
        weak_key = await harness.engine.assess_key(keys[1].id, tenant_id=TENANT)
        checked_certificate = await harness.engine.assess_certificate(
            certificate.id,
            tenant_id=TENANT,
        )

        assert unknown_key.strength.status == "unknown"
        assert unknown_key.rotation.status == "unknown"
        assert weak_key.strength.status == "invalid"
        assert weak_key.rotation.status == "invalid"
        assert checked_certificate.expiry.status == "unknown"
        assert checked_certificate.chain.status == "unknown"
        assert checked_certificate.revocation.status == "unknown"
        assert checked_certificate.integrity.status == "valid"
        assert checked_certificate.authenticity.status == "unknown"


async def test_crypto_integrity_not_authenticity() -> None:
    verifier = _Verifier()
    async with _harness("inmemory", verifier=verifier) as harness:
        source_id = new_id("src")
        evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(10),
        )
        [asset] = await harness.engine.ingest_crypto_assets(
            [],
            [
                _certificate(
                    source_id=source_id,
                    evidence_id=evidence.id,
                    fingerprint=_fingerprint(10),
                    not_after=NOW + timedelta(days=90),
                )
            ],
            tenant_id=TENANT,
        )
        assert isinstance(asset, CertificateAsset)
        checked = await harness.engine.assess_certificate(asset.id, tenant_id=TENANT)
        assert verifier.calls == 1
        assert checked.integrity.status == "valid"
        assert checked.integrity.evidence_id == evidence.id
        assert checked.authenticity.status == "valid"
        assert checked.authenticity.evidence_id != evidence.id
        result_evidence_id = checked.authenticity.evidence_id
        assert result_evidence_id is not None
        result = await harness.evidence.get(result_evidence_id, actor=ACTOR)
        assert result.content == {
            "certificate_id": asset.id,
            "certificate_fingerprint": asset.fingerprint,
            "basis_evidence_id": evidence.id,
            "status": "valid",
            "reason": "Typed verifier returned valid for the bound certificate.",
        }
        assert (await harness.evidence.verify(result.id)).ok


async def test_crypto_failed_authenticity_is_surfaced() -> None:
    verifier = _Verifier(status="invalid")
    async with _harness("inmemory", verifier=verifier) as harness:
        source_id = new_id("src")
        evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(12),
        )
        [asset] = await harness.engine.ingest_crypto_assets(
            [],
            [
                _certificate(
                    source_id=source_id,
                    evidence_id=evidence.id,
                    fingerprint=_fingerprint(12),
                    not_after=NOW + timedelta(days=90),
                )
            ],
            tenant_id=TENANT,
        )
        checked = await harness.engine.assess_certificate(asset.id, tenant_id=TENANT)
        assert checked.integrity.status == "valid"
        assert checked.authenticity.status == "invalid"
        result_evidence_id = checked.authenticity.evidence_id
        assert result_evidence_id is not None
        result = await harness.evidence.get(result_evidence_id, actor=ACTOR)
        assert result.content is not None
        assert result.content["status"] == "invalid"


@pytest.mark.parametrize(
    "mismatch",
    ["descriptor_evidence", "result_fingerprint", "result_evidence"],
)
async def test_crypto_unrelated_authenticity_input_is_refused(mismatch: str) -> None:
    verifier = _Verifier()
    if mismatch == "result_fingerprint":
        verifier.fingerprint = _fingerprint(99)
    if mismatch == "result_evidence":
        verifier.evidence_id = new_id("evd")
    async with _harness("inmemory", verifier=verifier) as harness:
        source_id = new_id("src")
        evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=(
                _fingerprint(98) if mismatch == "descriptor_evidence" else _fingerprint(11)
            ),
        )
        descriptor = _certificate(
            source_id=source_id,
            evidence_id=evidence.id,
            fingerprint=_fingerprint(11),
            not_after=NOW + timedelta(days=90),
        )
        if mismatch == "descriptor_evidence":
            with pytest.raises(CryptoConfigInvalid, match="fingerprint"):
                await harness.engine.ingest_crypto_assets([], [descriptor], tenant_id=TENANT)
            assert verifier.calls == 0
            return
        [asset] = await harness.engine.ingest_crypto_assets([], [descriptor], tenant_id=TENANT)
        with pytest.raises(CryptoConfigInvalid, match="authenticity result"):
            await harness.engine.assess_certificate(asset.id, tenant_id=TENANT)


@pytest.mark.parametrize(
    "failure",
    ["missing", "tampered", "evidence_unavailable", "verifier_unavailable"],
)
async def test_crypto_evidence_failure_not_safe(failure: str) -> None:
    verifier = _Verifier(unavailable=failure == "verifier_unavailable")
    async with _harness("inmemory", verifier=verifier) as harness:
        source_id = new_id("src")
        evidence = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=_fingerprint(20),
        )
        [asset] = await harness.engine.ingest_crypto_assets(
            [],
            [
                _certificate(
                    source_id=source_id,
                    evidence_id=evidence.id,
                    fingerprint=_fingerprint(20),
                    not_after=NOW + timedelta(days=90),
                )
            ],
            tenant_id=TENANT,
        )
        assert isinstance(asset, CertificateAsset)
        if failure == "tampered":
            assert evidence.content is not None
            evidence.content["fingerprint"] = _fingerprint(21)
            with pytest.raises(EvidenceTampered):
                await harness.engine.assess_certificate(asset.id, tenant_id=TENANT)
            assert verifier.calls == 0
            unchanged = await harness.store.get_asset(asset.id, tenant_id=TENANT)
            assert isinstance(unchanged, CertificateAsset)
            assert unchanged.integrity.status == "unknown"
            assert unchanged.authenticity.status == "unknown"
            return
        if failure == "missing":
            harness.engine.evidence_store = cast(EvidenceStore, _MissingEvidence())
            with pytest.raises(EvidenceNotFound):
                await harness.engine.assess_certificate(asset.id, tenant_id=TENANT)
            assert verifier.calls == 0
            unchanged = await harness.store.get_asset(asset.id, tenant_id=TENANT)
            assert isinstance(unchanged, CertificateAsset)
            assert unchanged.integrity.status == "unknown"
            assert unchanged.authenticity.status == "unknown"
            return
        if failure == "evidence_unavailable":
            harness.engine.evidence_store = cast(EvidenceStore, _UnavailableEvidence())
        checked = await harness.engine.assess_certificate(asset.id, tenant_id=TENANT)
        assert checked.authenticity.status == "unknown"
        if failure == "evidence_unavailable":
            assert checked.integrity.status == "unknown"
            assert checked.expiry.status == "unknown"
            assert verifier.calls == 0
        else:
            assert checked.integrity.status == "valid"
            assert checked.expiry.status == "valid"
            assert verifier.calls == 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_crypto_assessment_coverage(kind: str) -> None:
    verifier = _Verifier()
    async with _harness(kind, verifier=verifier) as harness:
        source_id = new_id("src")
        evidences = [
            await _evidence(
                harness.evidence,
                source_id=source_id,
                fingerprint=_fingerprint(index),
            )
            for index in range(30, 33)
        ]
        await harness.engine.ingest_secrets(
            [
                _secret(
                    source_id=source_id,
                    evidence_id=evidences[0].id,
                    fingerprint=_fingerprint(30),
                )
            ],
            tenant_id=TENANT,
        )
        await harness.engine.ingest_crypto_assets(
            [
                _key(
                    source_id=source_id,
                    evidence_id=evidences[1].id,
                    fingerprint=_fingerprint(31),
                    algorithm="rsa",
                    key_size=3072,
                    last_rotated_at=NOW - timedelta(days=20),
                )
            ],
            [
                _certificate(
                    source_id=source_id,
                    evidence_id=evidences[2].id,
                    fingerprint=_fingerprint(32),
                    not_after=NOW + timedelta(days=10),
                )
            ],
            tenant_id=TENANT,
        )
        complete = await harness.engine.assess(tenant_id=TENANT)
        assert complete.status == "complete"
        assert complete.assets_evaluated == 3
        assert (complete.secrets, complete.keys, complete.certificates) == (1, 1, 1)
        assert complete.expiring_soon == 1
        assert complete.unknown_lifecycle == 2
        assert complete.evidence_id is not None
        assert (await harness.evidence.verify(complete.evidence_id)).ok
        stored = await harness.store.get_assessment(complete.id, tenant_id=TENANT)
        assert stored == complete

        harness.engine.config = CryptoConfig(max_work=2, batch_size=2)
        truncated = await harness.engine.assess(tenant_id=TENANT)
        assert truncated.status == "truncated"
        assert truncated.assets_evaluated == 2
        assert truncated.incomplete_reason == "CryptoStore scan stopped at max_work=2."
        assert truncated.evidence_id is not None
        assert isinstance(
            await harness.store.get_assessment(truncated.id, tenant_id=TENANT),
            CryptoAssessment,
        )
