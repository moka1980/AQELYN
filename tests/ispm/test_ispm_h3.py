"""C-031 H3 value-free identity binding acceptance tests."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

import pytest
from pydantic import ValidationError

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    EvidenceNotFound,
    EvidenceTampered,
    ISPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore, VerifyResult
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.ispm import (
    IdentityBindingDescriptor,
    IdentityDescriptor,
    InMemoryISPMStore,
    ISPMEngine,
    ISPMStore,
    PostgresISPMStore,
)
from aqelyn.ispm.normalize import IdentityObjectStore
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.secrets import (
    CryptographicKey,
    CryptographicKeyDescriptor,
    InMemoryCryptoStore,
    SecretsIntelligenceEngine,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry, SourceReliability, TrustEngine

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 22, 20, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000340301"
OTHER_TENANT = "018f0000-0000-7000-8000-000000340302"
ACTOR = ActorRef(actor_type="system", actor_id="is034-h3-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    ispm_store: ISPMStore
    object_store: InMemoryObjectStore
    inventory_store: InMemoryAssetStore
    evidence_store: InMemoryEvidenceStore
    reliability: InMemorySourceReliabilityRegistry
    inventory: InventoryIntelligenceEngine
    ispm: ISPMEngine
    secrets: SecretsIntelligenceEngine


@asynccontextmanager
async def _harness(kind: str = "inmemory") -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        ispm_store: ISPMStore = InMemoryISPMStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresISPMStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_ispm_identity_revision, aq_ispm_identity_key RESTART IDENTITY CASCADE"
            )
        ispm_store = postgres
        closer = cast(_Closable, postgres)

    object_store = InMemoryObjectStore(mode="enterprise")
    inventory_store = InMemoryAssetStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    reliability = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    inventory = InventoryIntelligenceEngine(inventory_store)
    trust = TrustEngine(registry=reliability)
    ispm = ISPMEngine(
        ispm_store,
        object_store=object_store,
        inventory=inventory,
        evidence_store=evidence_store,
        trust=trust,
    )
    secrets = SecretsIntelligenceEngine(
        InMemoryCryptoStore(mode="enterprise"),
        object_store=object_store,
        inventory=inventory,
        evidence_store=evidence_store,
        trust=trust,
    )
    try:
        yield _Harness(
            ispm_store,
            object_store,
            inventory_store,
            evidence_store,
            reliability,
            inventory,
            ispm,
            secrets,
        )
    finally:
        if closer is not None:
            await closer.close()


async def _evidence(
    harness: _Harness,
    *,
    tenant_id: str,
    source_id: str,
    evidence_type: str,
    content: dict[str, object],
    weight: float = 0.82,
) -> EvidenceRecord:
    await harness.reliability.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="C-031 H3 source fixture.",
            set_by=ACTOR,
            set_at=NOW,
        )
    )
    return await harness.evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type=evidence_type,
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=source_id,
            method="handed_in_nhi_binding/v1",
            content=content,
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


async def _crypto_key(
    harness: _Harness,
    *,
    tenant_id: str = TENANT,
    index: int = 1,
) -> CryptographicKey:
    source_id = new_id("src")
    fingerprint = f"hmac-sha256:{index:064x}"
    evidence = await _evidence(
        harness,
        tenant_id=tenant_id,
        source_id=source_id,
        evidence_type="crypto_descriptor",
        content={"fingerprint": fingerprint, "metadata_only": True},
    )
    assets = await harness.secrets.ingest_crypto_assets(
        [
            CryptographicKeyDescriptor(
                tenant_id=tenant_id,
                external_key_ref=f"urn:aqelyn:key:h3-{index}",
                fingerprint=fingerprint,
                algorithm="rsa",
                key_size=3072,
                usages=["signing"],
                last_rotated_at=NOW - timedelta(days=30),
                source_id=source_id,
                observed_at=NOW,
                evidence_id=evidence.id,
            )
        ],
        [],
        tenant_id=tenant_id,
    )
    key = assets[0]
    assert isinstance(key, CryptographicKey)
    return key


async def _identity_material(
    harness: _Harness,
    *,
    target_object_id: str,
    target_type: str = "cryptographic_key",
    relation_type: str = "uses",
) -> tuple[str, EvidenceRecord, EvidenceRecord, IdentityDescriptor]:
    source_id = new_id("src")
    identity_evidence = await _evidence(
        harness,
        tenant_id=TENANT,
        source_id=source_id,
        evidence_type="identity.descriptor",
        content={"external_id": "identity:signing-service", "metadata_only": True},
    )
    binding_evidence = await _evidence(
        harness,
        tenant_id=TENANT,
        source_id=source_id,
        evidence_type="identity.crypto_binding",
        content={
            "from_external_id": "identity:signing-service",
            "target_object_id": target_object_id,
            "relation_type": relation_type,
            "metadata_only": True,
        },
    )
    descriptor = IdentityDescriptor.model_validate(
        {
            "source_id": source_id,
            "provider": "workload-registry",
            "external_id": "identity:signing-service",
            "identity_kind": "service",
            "observed_at": NOW,
            "evidence_id": identity_evidence.id,
            "bindings": [
                {
                    "from_external_id": "identity:signing-service",
                    "target_object_id": target_object_id,
                    "target_type": target_type,
                    "relation_type": relation_type,
                    "observed_at": NOW,
                    "evidence_id": binding_evidence.id,
                }
            ],
        }
    )
    return source_id, identity_evidence, binding_evidence, descriptor


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_nhi_crypto_binding_real_owner_round_trip(kind: str) -> None:
    async with _harness(kind) as harness:
        key = await _crypto_key(harness)
        _, _, binding_evidence, descriptor = await _identity_material(
            harness,
            target_object_id=key.object_id,
        )

        first = (await harness.ispm.ingest_identities([descriptor], tenant_id=TENANT))[0]
        second = (await harness.ispm.ingest_identities([descriptor], tenant_id=TENANT))[0]
        relations = await harness.object_store.relationships(
            first.object_id,
            direction="out",
            relation_type="uses",
        )

        assert first.relationship_ids == second.relationship_ids
        assert len(relations) == 1
        relation = relations[0]
        assert relation.id in first.relationship_ids
        assert relation.to_id == key.object_id
        assert relation.attributes == {
            "module": "EA-0033",
            "binding_target_type": "cryptographic_key",
            "authenticity": "unknown",
        }
        assert relation.sources[0].evidence_id == binding_evidence.id
        expected_trust = await TrustEngine(registry=harness.reliability).assess(
            (f"identity-binding:identity:signing-service:uses:{key.object_id}"),
            [binding_evidence],
            now=NOW,
        )
        assert relation.confidence == expected_trust.score

        graph: KnowledgeGraph = InMemoryKnowledgeGraph(harness.object_store)
        paths = await graph.paths(
            first.object_id,
            key.object_id,
            direction="out",
            relation_types=["uses"],
            max_depth=2,
            max_paths=2,
            max_work=10,
        )
        assert len(paths) == 1
        assert paths[0].node_ids == [first.object_id, key.object_id]
        assert paths[0].length == 1


def test_nhi_binding_no_secret_value() -> None:
    target_id = new_id("obj")
    evidence_id = new_id("evd")
    valid = {
        "from_external_id": "identity:signing-service",
        "target_object_id": target_id,
        "target_type": "cryptographic_key",
        "relation_type": "signs",
        "observed_at": NOW,
        "evidence_id": evidence_id,
    }
    assert IdentityBindingDescriptor.model_validate(valid).target_type == "cryptographic_key"
    for forbidden in (
        "value",
        "raw_value",
        "private_key",
        "credential",
        "password",
        "token",
        "payload",
    ):
        with pytest.raises(ValidationError):
            IdentityBindingDescriptor.model_validate({**valid, forbidden: "must-not-persist"})

    script = """
from datetime import datetime, timezone
from pydantic import ValidationError
from aqelyn.conventions import new_id
from aqelyn.ispm import IdentityBindingDescriptor

base = {
    'from_external_id': 'identity:signing-service',
    'target_object_id': new_id('obj'),
    'target_type': 'cryptographic_key',
    'relation_type': 'uses',
    'observed_at': datetime.now(timezone.utc),
    'evidence_id': new_id('evd'),
}
IdentityBindingDescriptor.model_validate(base)
try:
    IdentityBindingDescriptor.model_validate({**base, 'private_key': 'must-not-persist'})
except ValidationError:
    pass
else:
    raise SystemExit('optimized Python accepted credential material')
"""
    environment = dict(os.environ)
    source = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source, environment.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


async def test_nhi_binding_integrity_not_authenticity() -> None:
    async with _harness() as harness:
        key = await _crypto_key(harness)
        _, _, _, descriptor = await _identity_material(
            harness,
            target_object_id=key.object_id,
        )
        normalized = (await harness.ispm.ingest_identities([descriptor], tenant_id=TENANT))[0]
        relations = await harness.object_store.relationships(
            normalized.object_id,
            direction="out",
            relation_type="uses",
        )
        assert relations[0].attributes["authenticity"] == "unknown"

        binding = descriptor.bindings[0].model_dump(mode="python")
        with pytest.raises(ValidationError):
            IdentityBindingDescriptor.model_validate({**binding, "authenticity": "valid"})


class _BindingEvidenceUnavailable:
    def __init__(self, owner: InMemoryEvidenceStore, binding_evidence_id: str) -> None:
        self._owner = owner
        self._binding_evidence_id = binding_evidence_id

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        if evidence_id == self._binding_evidence_id:
            raise StoreUnavailable("binding evidence owner unavailable")
        return await self._owner.get(evidence_id, actor=actor)

    async def verify(self, evidence_id: str) -> VerifyResult:
        if evidence_id == self._binding_evidence_id:
            raise StoreUnavailable("binding evidence owner unavailable")
        return await self._owner.verify(evidence_id)


@pytest.mark.parametrize("failure", ["missing", "tampered", "retriable"])
async def test_nhi_binding_evidence_failure_writes_nothing(failure: str) -> None:
    async with _harness() as harness:
        key = await _crypto_key(harness)
        _, _, binding_evidence, descriptor = await _identity_material(
            harness,
            target_object_id=key.object_id,
        )
        if failure == "missing":
            descriptor = descriptor.model_copy(
                update={
                    "bindings": [
                        descriptor.bindings[0].model_copy(update={"evidence_id": new_id("evd")})
                    ]
                },
                deep=True,
            )
        elif failure == "tampered":
            assert binding_evidence.content is not None
            binding_evidence.content["relation_type"] = "tampered"
        else:
            harness.ispm.evidence_store = cast(
                EvidenceStore,
                _BindingEvidenceUnavailable(harness.evidence_store, binding_evidence.id),
            )

        expected = {
            "missing": EvidenceNotFound,
            "tampered": EvidenceTampered,
            "retriable": StoreUnavailable,
        }[failure]
        with pytest.raises(expected):
            await harness.ispm.ingest_identities([descriptor], tenant_id=TENANT)

        identities, cursor = await harness.ispm_store.query_identities(
            tenant_id=TENANT,
            limit=100,
        )
        identity_objects, object_cursor = await harness.object_store.query(
            ObjectQuery(tenant_id=TENANT, object_type="identity", limit=100)
        )
        assert identities == []
        assert cursor is None
        assert identity_objects == []
        assert object_cursor is None
        assert await harness.object_store.relationships(key.object_id) == []


async def test_nhi_binding_cross_tenant_refused() -> None:
    async with _harness() as harness:
        key = await _crypto_key(harness, tenant_id=OTHER_TENANT, index=2)
        _, _, _, descriptor = await _identity_material(
            harness,
            target_object_id=key.object_id,
        )
        with pytest.raises(CrossTenantReference, match="binding target"):
            await harness.ispm.ingest_identities([descriptor], tenant_id=TENANT)

        identities, _ = await harness.ispm_store.query_identities(
            tenant_id=TENANT,
            limit=100,
        )
        identity_objects, _ = await harness.object_store.query(
            ObjectQuery(tenant_id=TENANT, object_type="identity", limit=100)
        )
        assert identities == []
        assert identity_objects == []


@pytest.mark.parametrize("failure", ["missing", "type_mismatch"])
async def test_nhi_binding_invalid_target_writes_nothing(failure: str) -> None:
    async with _harness() as harness:
        key = await _crypto_key(harness)
        target_id = new_id("obj") if failure == "missing" else key.object_id
        target_type = "cryptographic_key" if failure == "missing" else "secret_asset"
        _, _, _, descriptor = await _identity_material(
            harness,
            target_object_id=target_id,
            target_type=target_type,
        )
        with pytest.raises(ISPMConfigInvalid):
            await harness.ispm.ingest_identities([descriptor], tenant_id=TENANT)

        identities, _ = await harness.ispm_store.query_identities(
            tenant_id=TENANT,
            limit=100,
        )
        identity_objects, _ = await harness.object_store.query(
            ObjectQuery(tenant_id=TENANT, object_type="identity", limit=100)
        )
        assert identities == []
        assert identity_objects == []


def test_nhi_binding_contract_and_vocabulary() -> None:
    concrete_store = InMemoryObjectStore(mode="enterprise")
    object_store: IdentityObjectStore = concrete_store
    graph: KnowledgeGraph = InMemoryKnowledgeGraph(concrete_store)
    assert object_store is concrete_store
    assert graph is not None

    base = {
        "from_external_id": "identity:workload",
        "target_object_id": new_id("obj"),
        "target_type": "workload",
        "relation_type": "runs_on",
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    assert IdentityBindingDescriptor.model_validate(base).target_type == "workload"
    for update in (
        {"target_type": "credential"},
        {"relation_type": "owns"},
        {"target_type": "secret_asset", "relation_type": "runs_on"},
    ):
        with pytest.raises((ValidationError, ISPMConfigInvalid)):
            IdentityBindingDescriptor.model_validate({**base, **update})

    binding = IdentityBindingDescriptor.model_validate(base)
    with pytest.raises(ISPMConfigInvalid, match="duplicates"):
        IdentityDescriptor(
            source_id=new_id("src"),
            provider="workload-registry",
            external_id="identity:workload",
            identity_kind="service",
            bindings=[binding, binding.model_copy(deep=True)],
            observed_at=NOW,
            evidence_id=new_id("evd"),
        )
