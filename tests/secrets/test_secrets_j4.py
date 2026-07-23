"""C-032 J4 acceptance tests for the EA-0025 credential ownership handoff."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
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
    SecretValueRejected,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore, VerifyResult
from aqelyn.inventory import (
    AssetStore,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    Ownership,
    PostgresAssetStore,
)
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.secrets import (
    CredentialOwnershipClaim,
    CryptographicKeyDescriptor,
    CryptoQuery,
    CryptoStore,
    InMemoryCryptoStore,
    PostgresCryptoStore,
    SecretsIntelligenceEngine,
)
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    SourceReliabilityRegistry,
    TrustEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000350401"
ACTOR = ActorRef(actor_type="system", actor_id="is035-j4-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    crypto_store: CryptoStore
    inventory_store: AssetStore
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    reliability: InMemorySourceReliabilityRegistry
    inventory: InventoryIntelligenceEngine
    engine: SecretsIntelligenceEngine


@asynccontextmanager
async def _harness(kind: str) -> AsyncIterator[_Harness]:
    closers: list[_Closable] = []
    if kind == "inmemory":
        crypto_store: CryptoStore = InMemoryCryptoStore(mode="enterprise")
        inventory_store: AssetStore = InMemoryAssetStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres_crypto = await PostgresCryptoStore.connect(PG_URL, mode="enterprise")
        postgres_inventory = await PostgresAssetStore.connect(PG_URL, mode="enterprise")
        async with postgres_crypto._pool.acquire() as connection:
            await connection.execute(
                "TRUNCATE aq_crypto_governance_score, aq_crypto_assessment, "
                "aq_crypto_asset_revision, aq_crypto_asset_identity "
                "RESTART IDENTITY CASCADE"
            )
        async with postgres_inventory._pool.acquire() as connection:
            await connection.execute(
                "TRUNCATE aq_inventory_asset_history, aq_inventory_asset RESTART IDENTITY CASCADE"
            )
        crypto_store = postgres_crypto
        inventory_store = postgres_inventory
        closers.extend((postgres_crypto, postgres_inventory))
    object_store = InMemoryObjectStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    reliability = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    inventory = InventoryIntelligenceEngine(inventory_store)
    engine = SecretsIntelligenceEngine(
        crypto_store,
        object_store=object_store,
        inventory=inventory,
        evidence_store=evidence_store,
        trust=TrustEngine(registry=reliability),
    )
    try:
        yield _Harness(
            crypto_store,
            inventory_store,
            object_store,
            evidence_store,
            reliability,
            inventory,
            engine,
        )
    finally:
        for closer in reversed(closers):
            await closer.close()


async def _evidence(
    store: InMemoryEvidenceStore,
    *,
    source_id: str,
    fingerprint: str,
    tenant_id: str | None = TENANT,
    observed_at: datetime = NOW,
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="crypto.credential_ownership",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=observed_at,
            recorded_at=observed_at,
            collector=ACTOR,
            source_id=source_id,
            method="handed_in_credential_ownership/v1",
            content={"fingerprint": fingerprint, "metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


async def _set_reliability(
    registry: SourceReliabilityRegistry,
    source_id: str,
    weight: float,
    *,
    observed_at: datetime = NOW,
) -> None:
    await registry.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="C-032 J4 source-reliability fixture.",
            set_by=ACTOR,
            set_at=observed_at,
        )
    )


def _ownership(
    *,
    team: str,
    source_id: str,
    evidence_id: str,
    observed_at: datetime = NOW,
) -> CredentialOwnershipClaim:
    return CredentialOwnershipClaim(
        business_owner=f"team:{team}",
        technical_owner=f"team:{team}:platform",
        custodian=f"team:{team}:operations",
        rationale=f"{team} is accountable for this credential.",
        source_id=source_id,
        observed_at=observed_at,
        evidence_id=evidence_id,
    )


def _descriptor(
    *,
    fingerprint: str,
    source_id: str,
    evidence_id: str,
    ownership: CredentialOwnershipClaim | None,
    tenant_id: str | None = TENANT,
    observed_at: datetime = NOW,
) -> CryptographicKeyDescriptor:
    return CryptographicKeyDescriptor(
        tenant_id=tenant_id,
        external_key_ref=f"urn:aqelyn:key:{fingerprint[-12:]}",
        fingerprint=fingerprint,
        algorithm="rsa",
        key_size=4096,
        usages=["signing"],
        last_rotated_at=observed_at - timedelta(days=30),
        source_id=source_id,
        observed_at=observed_at,
        evidence_id=evidence_id,
        ownership=ownership,
    )


def test_credential_ownership_claim_is_value_free_and_attributed() -> None:
    with pytest.raises(CryptoConfigInvalid, match="at least one owner"):
        CredentialOwnershipClaim(
            rationale="No owner was supplied.",
            source_id=new_id("src"),
            observed_at=NOW,
            evidence_id=new_id("evd"),
        )
    with pytest.raises(SecretValueRejected):
        CredentialOwnershipClaim.model_validate(
            {
                "business_owner": "team:security",
                "rationale": "This claim attempts to carry credential material.",
                "source_id": new_id("src"),
                "observed_at": NOW,
                "evidence_id": new_id("evd"),
                "raw_value": "must-not-persist",
            }
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_crypto_owner_roundtrip_ea0025(kind: str) -> None:
    async with _harness(kind) as harness:
        fingerprint = f"hmac-sha256:{701:064x}"
        descriptor_source = new_id("src")
        owner_source = new_id("src")
        await _set_reliability(harness.reliability, descriptor_source, 0.7)
        await _set_reliability(harness.reliability, owner_source, 0.93)
        descriptor_evidence = await _evidence(
            harness.evidence_store,
            source_id=descriptor_source,
            fingerprint=fingerprint,
        )
        owner_evidence = await _evidence(
            harness.evidence_store,
            source_id=owner_source,
            fingerprint=fingerprint,
        )
        [asset] = await harness.engine.ingest_crypto_assets(
            [
                _descriptor(
                    fingerprint=fingerprint,
                    source_id=descriptor_source,
                    evidence_id=descriptor_evidence.id,
                    ownership=_ownership(
                        team="payments",
                        source_id=owner_source,
                        evidence_id=owner_evidence.id,
                    ),
                )
            ],
            [],
            tenant_id=TENANT,
        )

        selected = await harness.inventory.ownership(asset.inventory_ref, tenant_id=TENANT)
        assert selected == Ownership(
            business_owner="team:payments",
            technical_owner="team:payments:platform",
            custodian="team:payments:operations",
            rationale="payments is accountable for this credential.",
            source_id=owner_source,
            evidence_id=owner_evidence.id,
            observed_at=NOW,
        )
        reconciled = await harness.inventory.reconcile(
            asset.inventory_ref,
            tenant_id=TENANT,
        )
        assert reconciled.owner == selected

        silent_source = new_id("src")
        silent_evidence = await _evidence(
            harness.evidence_store,
            source_id=silent_source,
            fingerprint=fingerprint,
            observed_at=NOW + timedelta(minutes=1),
        )
        await _set_reliability(
            harness.reliability,
            silent_source,
            1.0,
            observed_at=NOW + timedelta(minutes=1),
        )
        await harness.engine.ingest_crypto_assets(
            [
                _descriptor(
                    fingerprint=fingerprint,
                    source_id=silent_source,
                    evidence_id=silent_evidence.id,
                    ownership=None,
                    observed_at=NOW + timedelta(minutes=1),
                )
            ],
            [],
            tenant_id=TENANT,
        )
        assert await harness.inventory.ownership(asset.inventory_ref, tenant_id=TENANT) == selected

        unowned_fingerprint = f"hmac-sha256:{702:064x}"
        unowned_source = new_id("src")
        unowned_evidence = await _evidence(
            harness.evidence_store,
            source_id=unowned_source,
            fingerprint=unowned_fingerprint,
        )
        [unowned] = await harness.engine.ingest_crypto_assets(
            [
                _descriptor(
                    fingerprint=unowned_fingerprint,
                    source_id=unowned_source,
                    evidence_id=unowned_evidence.id,
                    ownership=None,
                )
            ],
            [],
            tenant_id=TENANT,
        )
        assert await harness.inventory.ownership(unowned.inventory_ref, tenant_id=TENANT) is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_crypto_owner_conflict_reliability(kind: str) -> None:
    async with _harness(kind) as harness:
        fingerprint = f"hmac-sha256:{703:064x}"
        high_source = new_id("src")
        low_source = new_id("src")
        await _set_reliability(harness.reliability, high_source, 0.91)
        await _set_reliability(harness.reliability, low_source, 0.2)
        high_evidence = await _evidence(
            harness.evidence_store,
            source_id=high_source,
            fingerprint=fingerprint,
        )
        low_evidence = await _evidence(
            harness.evidence_store,
            source_id=low_source,
            fingerprint=fingerprint,
            observed_at=NOW + timedelta(minutes=1),
        )
        [first] = await harness.engine.ingest_crypto_assets(
            [
                _descriptor(
                    fingerprint=fingerprint,
                    source_id=high_source,
                    evidence_id=high_evidence.id,
                    ownership=_ownership(
                        team="platform",
                        source_id=high_source,
                        evidence_id=high_evidence.id,
                    ),
                )
            ],
            [],
            tenant_id=TENANT,
        )
        [second] = await harness.engine.ingest_crypto_assets(
            [
                _descriptor(
                    fingerprint=fingerprint,
                    source_id=low_source,
                    evidence_id=low_evidence.id,
                    ownership=_ownership(
                        team="unknown",
                        source_id=low_source,
                        evidence_id=low_evidence.id,
                        observed_at=NOW + timedelta(minutes=1),
                    ),
                    observed_at=NOW + timedelta(minutes=1),
                )
            ],
            [],
            tenant_id=TENANT,
        )

        assert second.id == first.id
        selected = await harness.inventory.ownership(second.inventory_ref, tenant_id=TENANT)
        assert selected is not None
        assert selected.business_owner == "team:platform"
        assert selected.evidence_id == high_evidence.id
        inventory_asset = await harness.inventory_store.get(
            second.inventory_ref,
            tenant_id=TENANT,
        )
        assert inventory_asset is not None
        owner_conflict = next(
            conflict for conflict in inventory_asset.conflicts if conflict.field == "owner"
        )
        assert owner_conflict.resolved_by == high_source
        assert owner_conflict.unresolved is False
        assert sorted(
            cast(float, candidate.reliability) for candidate in owner_conflict.candidates
        ) == pytest.approx([0.2, 0.91])

        tie_fingerprint = f"hmac-sha256:{704:064x}"
        tie_a = new_id("src")
        tie_b = new_id("src")
        await _set_reliability(harness.reliability, tie_a, 0.5)
        await _set_reliability(harness.reliability, tie_b, 0.5)
        tie_a_evidence = await _evidence(
            harness.evidence_store,
            source_id=tie_a,
            fingerprint=tie_fingerprint,
        )
        tie_b_evidence = await _evidence(
            harness.evidence_store,
            source_id=tie_b,
            fingerprint=tie_fingerprint,
            observed_at=NOW + timedelta(minutes=1),
        )
        await harness.engine.ingest_crypto_assets(
            [
                _descriptor(
                    fingerprint=tie_fingerprint,
                    source_id=tie_a,
                    evidence_id=tie_a_evidence.id,
                    ownership=_ownership(
                        team="alpha",
                        source_id=tie_a,
                        evidence_id=tie_a_evidence.id,
                    ),
                )
            ],
            [],
            tenant_id=TENANT,
        )
        [tied] = await harness.engine.ingest_crypto_assets(
            [
                _descriptor(
                    fingerprint=tie_fingerprint,
                    source_id=tie_b,
                    evidence_id=tie_b_evidence.id,
                    ownership=_ownership(
                        team="beta",
                        source_id=tie_b,
                        evidence_id=tie_b_evidence.id,
                        observed_at=NOW + timedelta(minutes=1),
                    ),
                    observed_at=NOW + timedelta(minutes=1),
                )
            ],
            [],
            tenant_id=TENANT,
        )
        assert await harness.inventory.ownership(tied.inventory_ref, tenant_id=TENANT) is None
        tied_inventory = await harness.inventory_store.get(
            tied.inventory_ref,
            tenant_id=TENANT,
        )
        assert tied_inventory is not None
        tied_conflict = next(
            conflict for conflict in tied_inventory.conflicts if conflict.field == "owner"
        )
        assert tied_conflict.unresolved is True
        assert tied_conflict.resolved_by is None


class _UnavailableOwnershipEvidence:
    def __init__(
        self,
        delegate: InMemoryEvidenceStore,
        unavailable_id: str,
    ) -> None:
        self.delegate = delegate
        self.unavailable_id = unavailable_id

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        if evidence_id == self.unavailable_id:
            raise StoreUnavailable("credential ownership evidence owner unavailable")
        return await self.delegate.get(evidence_id, actor=actor)

    async def verify(self, evidence_id: str) -> VerifyResult:
        if evidence_id == self.unavailable_id:
            raise StoreUnavailable("credential ownership evidence owner unavailable")
        return await self.delegate.verify(evidence_id)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
@pytest.mark.parametrize("failure", ["missing", "tampered", "mismatch", "retriable"])
async def test_crypto_owner_evidence_failure_writes_nothing(
    kind: str,
    failure: str,
) -> None:
    async with _harness(kind) as harness:
        fingerprint = f"hmac-sha256:{705:064x}"
        valid_fingerprint = f"hmac-sha256:{708:064x}"
        descriptor_source = new_id("src")
        valid_source = new_id("src")
        owner_source = new_id("src")
        valid_evidence = await _evidence(
            harness.evidence_store,
            source_id=valid_source,
            fingerprint=valid_fingerprint,
        )
        descriptor_evidence = await _evidence(
            harness.evidence_store,
            source_id=descriptor_source,
            fingerprint=fingerprint,
        )
        owner_evidence_id = new_id("evd")
        if failure in {"tampered", "mismatch", "retriable"}:
            owner_evidence = await _evidence(
                harness.evidence_store,
                source_id=owner_source,
                fingerprint=(f"hmac-sha256:{999:064x}" if failure == "mismatch" else fingerprint),
            )
            owner_evidence_id = owner_evidence.id
            if failure == "tampered":
                harness.evidence_store._by_id[owner_evidence.id].content = {
                    "fingerprint": f"hmac-sha256:{999:064x}"
                }
            elif failure == "retriable":
                harness.engine.evidence_store = cast(
                    EvidenceStore,
                    _UnavailableOwnershipEvidence(
                        harness.evidence_store,
                        owner_evidence.id,
                    ),
                )
        expected = {
            "missing": EvidenceNotFound,
            "tampered": EvidenceTampered,
            "mismatch": CryptoConfigInvalid,
            "retriable": StoreUnavailable,
        }[failure]
        with pytest.raises(expected):
            await harness.engine.ingest_crypto_assets(
                [
                    _descriptor(
                        fingerprint=valid_fingerprint,
                        source_id=valid_source,
                        evidence_id=valid_evidence.id,
                        ownership=None,
                    ),
                    _descriptor(
                        fingerprint=fingerprint,
                        source_id=descriptor_source,
                        evidence_id=descriptor_evidence.id,
                        ownership=_ownership(
                            team="security",
                            source_id=owner_source,
                            evidence_id=owner_evidence_id,
                        ),
                    ),
                ],
                [],
                tenant_id=TENANT,
            )

        objects, _ = await harness.object_store.query(ObjectQuery(tenant_id=TENANT, limit=100))
        inventory_rows = await harness.inventory_store.query(
            tenant_id=TENANT,
            limit=100,
        )
        assets, _ = await harness.crypto_store.query_assets(
            CryptoQuery(tenant_id=TENANT, limit=100)
        )
        assert objects == []
        assert inventory_rows == []
        assert assets == []


async def test_crypto_governance_score_pins_historical_owner() -> None:
    runtime = create_inmemory_runtime(
        AQELYNConfig(
            secrets_approved_storage_location_prefixes=["urn:aqelyn:key:"],
        )
    )
    fingerprint = f"hmac-sha256:{706:064x}"
    first_descriptor_source = new_id("src")
    first_owner_source = new_id("src")
    await _set_reliability(runtime.trust_engine.registry, first_descriptor_source, 0.7)
    await _set_reliability(runtime.trust_engine.registry, first_owner_source, 0.8)
    first_descriptor_evidence = await _evidence(
        runtime.evidence_store,
        source_id=first_descriptor_source,
        fingerprint=fingerprint,
        tenant_id=None,
    )
    first_owner_evidence = await _evidence(
        runtime.evidence_store,
        source_id=first_owner_source,
        fingerprint=fingerprint,
        tenant_id=None,
    )
    [asset] = await runtime.secrets_engine.ingest_crypto_assets(
        [
            _descriptor(
                fingerprint=fingerprint,
                source_id=first_descriptor_source,
                evidence_id=first_descriptor_evidence.id,
                ownership=_ownership(
                    team="payments",
                    source_id=first_owner_source,
                    evidence_id=first_owner_evidence.id,
                ),
                tenant_id=None,
            )
        ],
        [],
        tenant_id=None,
    )
    first_score = await runtime.secrets_engine.score_credential(asset.id, tenant_id=None)

    second_descriptor_source = new_id("src")
    second_owner_source = new_id("src")
    later = NOW + timedelta(days=1)
    await _set_reliability(
        runtime.trust_engine.registry,
        second_descriptor_source,
        0.9,
        observed_at=later,
    )
    await _set_reliability(
        runtime.trust_engine.registry,
        second_owner_source,
        1.0,
        observed_at=later,
    )
    second_descriptor_evidence = await _evidence(
        runtime.evidence_store,
        source_id=second_descriptor_source,
        fingerprint=fingerprint,
        tenant_id=None,
        observed_at=later,
    )
    second_owner_evidence = await _evidence(
        runtime.evidence_store,
        source_id=second_owner_source,
        fingerprint=fingerprint,
        tenant_id=None,
        observed_at=later,
    )
    await runtime.secrets_engine.ingest_crypto_assets(
        [
            _descriptor(
                fingerprint=fingerprint,
                source_id=second_descriptor_source,
                evidence_id=second_descriptor_evidence.id,
                ownership=_ownership(
                    team="central-security",
                    source_id=second_owner_source,
                    evidence_id=second_owner_evidence.id,
                    observed_at=later,
                ),
                tenant_id=None,
                observed_at=later,
            )
        ],
        [],
        tenant_id=None,
    )
    current_owner = await runtime.inventory_engine.ownership(
        asset.inventory_ref,
        tenant_id=None,
    )
    second_score = await runtime.secrets_engine.score_credential(asset.id, tenant_id=None)
    stored_first = await runtime.secrets_store.get_score(first_score.id, tenant_id=None)

    assert current_owner is not None
    assert current_owner.evidence_id == second_owner_evidence.id
    assert stored_first == first_score
    first_owner = cast(
        Mapping[str, object],
        first_score.derivation.steps[0].params["ownership"],
    )
    second_owner = cast(
        Mapping[str, object],
        second_score.derivation.steps[0].params["ownership"],
    )
    assert first_owner["evidence_id"] == first_owner_evidence.id
    assert second_owner["evidence_id"] == second_owner_evidence.id
    assert (
        first_score.derivation.steps[0].params["ownership_record_hash"]
        != (second_score.derivation.steps[0].params["ownership_record_hash"])
    )

    unowned_fingerprint = f"hmac-sha256:{707:064x}"
    unowned_source = new_id("src")
    unowned_evidence = await _evidence(
        runtime.evidence_store,
        source_id=unowned_source,
        fingerprint=unowned_fingerprint,
        tenant_id=None,
    )
    [unowned_asset] = await runtime.secrets_engine.ingest_crypto_assets(
        [
            _descriptor(
                fingerprint=unowned_fingerprint,
                source_id=unowned_source,
                evidence_id=unowned_evidence.id,
                ownership=None,
                tenant_id=None,
            )
        ],
        [],
        tenant_id=None,
    )
    unowned_score = await runtime.secrets_engine.score_credential(
        unowned_asset.id,
        tenant_id=None,
    )
    ownership_factor = next(
        factor for factor in unowned_score.factors if factor.name == "ownership"
    )
    assert ownership_factor.status == "unknown"
    assert ownership_factor.rating is None
    assert unowned_score.derivation.steps[0].params["ownership"] is None
