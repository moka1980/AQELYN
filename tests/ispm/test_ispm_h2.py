"""C-031 H2 ownership handoff acceptance tests."""

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
    EvidenceNotFound,
    EvidenceTampered,
    ISPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore, VerifyResult
from aqelyn.inventory import (
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    Ownership,
    PostgresAssetStore,
)
from aqelyn.ispm import (
    IdentityDescriptor,
    IdentityOwnershipClaim,
    IdentityOwnershipState,
    InMemoryISPMStore,
    ISPMEngine,
    ISPMStore,
    PostgresISPMStore,
)
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.trust import InMemorySourceReliabilityRegistry, SourceReliability, TrustEngine

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 22, 18, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000340201"
ACTOR = ActorRef(actor_type="system", actor_id="is034-h2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    ispm_store: ISPMStore
    inventory_store: AssetStore
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    reliability: InMemorySourceReliabilityRegistry
    inventory: InventoryIntelligenceEngine
    engine: ISPMEngine


@asynccontextmanager
async def _harness(kind: str) -> AsyncIterator[_Harness]:
    closers: list[_Closable] = []
    if kind == "inmemory":
        ispm_store: ISPMStore = InMemoryISPMStore(mode="enterprise")
        inventory_store: AssetStore = InMemoryAssetStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres_ispm = await PostgresISPMStore.connect(PG_URL, mode="enterprise")
        postgres_inventory = await PostgresAssetStore.connect(PG_URL, mode="enterprise")
        async with postgres_ispm._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_ispm_identity_revision, aq_ispm_identity_key RESTART IDENTITY CASCADE"
            )
        async with postgres_inventory._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_inventory_asset_history, aq_inventory_asset")
        ispm_store = postgres_ispm
        inventory_store = postgres_inventory
        closers.extend((postgres_ispm, postgres_inventory))
    object_store = InMemoryObjectStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    reliability = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    inventory = InventoryIntelligenceEngine(inventory_store)
    engine = ISPMEngine(
        ispm_store,
        object_store=object_store,
        inventory=inventory,
        evidence_store=evidence_store,
        trust=TrustEngine(registry=reliability),
    )
    try:
        yield _Harness(
            ispm_store,
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
    harness: _Harness,
    *,
    source_id: str,
    external_id: str,
    weight: float,
    observed_at: datetime = NOW,
) -> EvidenceRecord:
    await harness.reliability.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="C-031 H2 source fixture.",
            set_by=ACTOR,
            set_at=observed_at,
        )
    )
    return await harness.evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="identity.ownership",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=observed_at,
            recorded_at=observed_at,
            collector=ACTOR,
            source_id=source_id,
            method="handed_in_identity_ownership/v1",
            content={"external_id": external_id, "metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


def _claim(
    *,
    team: str,
    source_id: str,
    evidence_id: str,
    observed_at: datetime = NOW,
) -> IdentityOwnershipClaim:
    return IdentityOwnershipClaim(
        business_owner=f"team:{team}",
        technical_owner=f"team:{team}:platform",
        custodian=f"team:{team}:operations",
        rationale=f"{team} is accountable for this identity.",
        source_id=source_id,
        observed_at=observed_at,
        evidence_id=evidence_id,
    )


def _descriptor(
    *,
    source_id: str,
    evidence_id: str,
    external_id: str,
    ownership: IdentityOwnershipClaim | None,
    observed_at: datetime = NOW,
) -> IdentityDescriptor:
    return IdentityDescriptor(
        source_id=source_id,
        provider="entra",
        external_id=external_id,
        identity_kind="service",
        observed_at=observed_at,
        evidence_id=evidence_id,
        ownership=ownership,
    )


def test_nhi_ownership_state_is_structural() -> None:
    with pytest.raises(ISPMConfigInvalid, match="at least one owner"):
        IdentityOwnershipClaim(
            rationale="Owner source supplied no owner reference.",
            source_id="src:cmdb",
            observed_at=NOW,
            evidence_id=new_id("evd"),
        )
    with pytest.raises(ISPMConfigInvalid, match="unknown ownership cannot carry"):
        IdentityOwnershipState(
            inventory_ref=new_id("ast"),
            status="unknown",
            source_id="src:cmdb",
            evidence_id=new_id("evd"),
            observed_at=NOW,
            reason="This state is contradictory.",
        )
    with pytest.raises(ISPMConfigInvalid, match="known ownership requires"):
        IdentityOwnershipState(
            inventory_ref=new_id("ast"),
            status="known",
            reason="This state lacks evidence provenance.",
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_nhi_ownership_real_inventory_round_trip(kind: str) -> None:
    async with _harness(kind) as harness:
        descriptor_source = new_id("src")
        owner_source = new_id("src")
        descriptor_evidence = await _evidence(
            harness,
            source_id=descriptor_source,
            external_id="identity:payments-bot",
            weight=0.7,
        )
        owner_evidence = await _evidence(
            harness,
            source_id=owner_source,
            external_id="identity:payments-bot:owner",
            weight=0.93,
        )
        normalized = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=descriptor_source,
                        evidence_id=descriptor_evidence.id,
                        external_id="identity:payments-bot",
                        ownership=_claim(
                            team="payments",
                            source_id=owner_source,
                            evidence_id=owner_evidence.id,
                        ),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]

        assert normalized.ownership is not None
        assert normalized.ownership.status == "known"
        assert normalized.ownership.source_id == owner_source
        assert normalized.ownership.evidence_id == owner_evidence.id
        selected = await harness.inventory.ownership(
            normalized.ownership.inventory_ref,
            tenant_id=TENANT,
        )
        assert selected is not None
        assert selected.business_owner == "team:payments"
        assert selected.evidence_id == owner_evidence.id
        assert selected.observed_at == NOW
        assert (
            await harness.ispm_store.get_identity(normalized.object_id, tenant_id=TENANT)
            == normalized
        )

        later_source = new_id("src")
        later_evidence = await _evidence(
            harness,
            source_id=later_source,
            external_id="identity:payments-bot:later-owner",
            weight=1.0,
            observed_at=NOW + timedelta(days=1),
        )
        await harness.inventory.ingest(
            reports=[
                {
                    "id": normalized.ownership.inventory_ref,
                    "asset_type": "identity",
                    "lifecycle_state": "active",
                    "evidence_id": later_evidence.id,
                    "owner": Ownership(
                        business_owner="team:central-security",
                        rationale="A later owner record must not rewrite issued ISPM history.",
                        source_id=later_source,
                        evidence_id=later_evidence.id,
                        observed_at=NOW + timedelta(days=1),
                    ).model_dump(mode="json"),
                }
            ],
            source=DiscoverySource(
                source_id=later_source,
                reliability=1.0,
                health="ok",
                as_of=NOW + timedelta(days=1),
            ),
            tenant_id=TENANT,
        )
        await harness.inventory.reconcile(
            normalized.ownership.inventory_ref,
            tenant_id=TENANT,
        )
        current_owner = await harness.inventory.ownership(
            normalized.ownership.inventory_ref,
            tenant_id=TENANT,
        )
        pinned_identity = await harness.ispm_store.get_identity(
            normalized.object_id,
            tenant_id=TENANT,
        )
        assert current_owner is not None
        assert current_owner.evidence_id == later_evidence.id
        assert pinned_identity is not None
        assert pinned_identity.ownership == normalized.ownership

        missing_source = new_id("src")
        missing_evidence = await _evidence(
            harness,
            source_id=missing_source,
            external_id="identity:unowned",
            weight=0.99,
        )
        unowned = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=missing_source,
                        evidence_id=missing_evidence.id,
                        external_id="identity:unowned",
                        ownership=None,
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        assert unowned.ownership is not None
        assert unowned.ownership.status == "unknown"
        assert unowned.ownership.evidence_id is None
        assert "No evidence-backed ownership" in unowned.ownership.reason


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_nhi_ownership_conflict_uses_trust(kind: str) -> None:
    async with _harness(kind) as harness:
        high_source = new_id("src")
        low_source = new_id("src")
        high_evidence = await _evidence(
            harness,
            source_id=high_source,
            external_id="identity:build-bot",
            weight=0.91,
        )
        low_evidence = await _evidence(
            harness,
            source_id=low_source,
            external_id="identity:build-bot",
            weight=0.2,
            observed_at=NOW + timedelta(minutes=1),
        )
        first = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=high_source,
                        evidence_id=high_evidence.id,
                        external_id="identity:build-bot",
                        ownership=_claim(
                            team="platform",
                            source_id=high_source,
                            evidence_id=high_evidence.id,
                        ),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        second = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=low_source,
                        evidence_id=low_evidence.id,
                        external_id="identity:build-bot",
                        ownership=_claim(
                            team="unknown",
                            source_id=low_source,
                            evidence_id=low_evidence.id,
                            observed_at=NOW + timedelta(minutes=1),
                        ),
                        observed_at=NOW + timedelta(minutes=1),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]

        assert second.object_id == first.object_id
        assert second.ownership is not None
        assert second.ownership.status == "known"
        assert second.ownership.source_id == high_source
        assert second.ownership.evidence_id == high_evidence.id
        asset = await harness.inventory_store.get(
            second.ownership.inventory_ref,
            tenant_id=TENANT,
        )
        assert asset is not None
        owner_conflict = next(conflict for conflict in asset.conflicts if conflict.field == "owner")
        assert owner_conflict.resolved_by == high_source
        assert owner_conflict.unresolved is False
        assert sorted(
            cast(float, candidate.reliability) for candidate in owner_conflict.candidates
        ) == pytest.approx([0.2, 0.91])

        silent_source = new_id("src")
        silent_evidence = await _evidence(
            harness,
            source_id=silent_source,
            external_id="identity:build-bot",
            weight=1.0,
            observed_at=NOW + timedelta(minutes=2),
        )
        after_silence = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=silent_source,
                        evidence_id=silent_evidence.id,
                        external_id="identity:build-bot",
                        ownership=None,
                        observed_at=NOW + timedelta(minutes=2),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        assert after_silence.ownership is not None
        assert after_silence.ownership.status == "known"
        assert after_silence.ownership.source_id == high_source

        tie_a = new_id("src")
        tie_b = new_id("src")
        tie_a_evidence = await _evidence(
            harness,
            source_id=tie_a,
            external_id="identity:tie",
            weight=0.5,
        )
        tie_b_evidence = await _evidence(
            harness,
            source_id=tie_b,
            external_id="identity:tie",
            weight=0.5,
            observed_at=NOW + timedelta(minutes=1),
        )
        await harness.engine.ingest_identities(
            [
                _descriptor(
                    source_id=tie_a,
                    evidence_id=tie_a_evidence.id,
                    external_id="identity:tie",
                    ownership=_claim(
                        team="alpha",
                        source_id=tie_a,
                        evidence_id=tie_a_evidence.id,
                    ),
                )
            ],
            tenant_id=TENANT,
        )
        tied = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=tie_b,
                        evidence_id=tie_b_evidence.id,
                        external_id="identity:tie",
                        ownership=_claim(
                            team="beta",
                            source_id=tie_b,
                            evidence_id=tie_b_evidence.id,
                            observed_at=NOW + timedelta(minutes=1),
                        ),
                        observed_at=NOW + timedelta(minutes=1),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        assert tied.ownership is not None
        assert tied.ownership.status == "unknown"
        assert "equal reliability" in tied.ownership.reason
        assert (
            await harness.inventory.ownership(
                tied.ownership.inventory_ref,
                tenant_id=TENANT,
            )
            is None
        )


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
            raise StoreUnavailable("ownership evidence owner unavailable")
        return await self.delegate.get(evidence_id, actor=actor)

    async def verify(self, evidence_id: str) -> VerifyResult:
        if evidence_id == self.unavailable_id:
            raise StoreUnavailable("ownership evidence owner unavailable")
        return await self.delegate.verify(evidence_id)


@pytest.mark.parametrize("failure", ["missing", "tampered", "retriable"])
async def test_nhi_ownership_evidence_failure_writes_nothing(failure: str) -> None:
    async with _harness("inmemory") as harness:
        descriptor_source = new_id("src")
        owner_source = new_id("src")
        descriptor_evidence = await _evidence(
            harness,
            source_id=descriptor_source,
            external_id="identity:evidence-failure",
            weight=0.7,
        )
        owner_evidence_id = new_id("evd")
        if failure in {"tampered", "retriable"}:
            owner_evidence = await _evidence(
                harness,
                source_id=owner_source,
                external_id="identity:evidence-failure:owner",
                weight=0.9,
            )
            owner_evidence_id = owner_evidence.id
            if failure == "tampered":
                harness.evidence_store._by_id[owner_evidence.id].content = {"tampered": True}
            else:
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
            "retriable": StoreUnavailable,
        }[failure]
        with pytest.raises(expected):
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=descriptor_source,
                        evidence_id=descriptor_evidence.id,
                        external_id="identity:evidence-failure",
                        ownership=_claim(
                            team="security",
                            source_id=owner_source,
                            evidence_id=owner_evidence_id,
                        ),
                    )
                ],
                tenant_id=TENANT,
            )

        objects, _ = await harness.object_store.query(ObjectQuery(tenant_id=TENANT, limit=100))
        inventory_rows = await harness.inventory_store.query(tenant_id=TENANT, limit=100)
        identities, _ = await harness.ispm_store.query_identities(
            tenant_id=TENANT,
            limit=100,
        )
        assert objects == []
        assert inventory_rows == []
        assert identities == []
