"""C-030 G2 acceptance tests for ISPM normalization and persistence."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import ISPMConfigInvalid, TenantScopeRequired
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.graph import InMemoryKnowledgeGraph
from aqelyn.iag import IdentityAccessGovernanceEngine, InMemoryCertificationStore
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.ispm import (
    IdentityAccessEdgeDescriptor,
    IdentityAccountDescriptor,
    IdentityDescriptor,
    InMemoryISPMStore,
    ISPMEngine,
    ISPMStore,
    NormalizedIdentity,
    PostgresISPMStore,
)
from aqelyn.objects import AQObject, InMemoryObjectStore, NaturalKey, ObjectQuery, SourceRef
from aqelyn.policy import PolicyEngine
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    TrustEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000330201"
OTHER_TENANT = "018f0000-0000-7000-8000-000000330202"
ACTOR = ActorRef(actor_type="system", actor_id="ispm-g2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: ISPMStore
    object_store: InMemoryObjectStore
    inventory_store: InMemoryAssetStore
    evidence_store: InMemoryEvidenceStore
    reliability: InMemorySourceReliabilityRegistry
    engine: ISPMEngine


@asynccontextmanager
async def _harness(kind: str = "inmemory") -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: ISPMStore = InMemoryISPMStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresISPMStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_ispm_identity_revision, aq_ispm_identity_key RESTART IDENTITY CASCADE"
            )
        store = postgres
        closer = cast(_Closable, postgres)
    object_store = InMemoryObjectStore(mode="enterprise")
    inventory_store = InMemoryAssetStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    reliability = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    engine = ISPMEngine(
        store,
        object_store=object_store,
        inventory=InventoryIntelligenceEngine(inventory_store),
        evidence_store=evidence_store,
        trust=TrustEngine(registry=reliability),
    )
    try:
        yield _Harness(
            store,
            object_store,
            inventory_store,
            evidence_store,
            reliability,
            engine,
        )
    finally:
        if closer is not None:
            await closer.close()


async def _evidence(
    harness: _Harness,
    *,
    source_id: str,
    external_id: str,
    weight: float = 0.8,
    observed_at: datetime = NOW,
) -> EvidenceRecord:
    await harness.reliability.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="ISPM G2 source fixture.",
            set_by=ACTOR,
            set_at=observed_at,
        )
    )
    return await harness.evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="identity.descriptor",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=observed_at,
            recorded_at=observed_at,
            collector=ACTOR,
            source_id=source_id,
            method="handed_in_identity_descriptor",
            content={"external_id": external_id, "metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


def _descriptor(
    *,
    source_id: str,
    identity_evidence_id: str,
    account_evidence_id: str,
    external_id: str = "identity:alex",
    account_external_id: str = "account:alex@example.test",
    identity_kind: str | None = "human",
    account_attributes: dict[str, object] | None = None,
    access_edges: list[IdentityAccessEdgeDescriptor] | None = None,
) -> IdentityDescriptor:
    return IdentityDescriptor.model_validate(
        {
            "source_id": source_id,
            "provider": "entra",
            "external_id": external_id,
            "identity_kind": identity_kind,
            "attributes": {"display_name": "Alex"},
            "controls": {"mfa": "present", "lifecycle": "active"},
            "accounts": [
                IdentityAccountDescriptor(
                    external_id=account_external_id,
                    display_name="alex@example.test",
                    attributes=account_attributes or {"last_used_at": NOW.isoformat()},
                    observed_at=NOW,
                    evidence_id=account_evidence_id,
                )
            ],
            "access_edges": access_edges or [],
            "observed_at": NOW,
            "evidence_id": identity_evidence_id,
        }
    )


def _normalized(
    *,
    object_id: str | None = None,
    tenant_id: str = TENANT,
    provider: str = "entra",
    external_id: str = "identity:fixture",
    identity_kind: str = "human",
    flagged: bool = False,
    evidence_id: str | None = None,
) -> NormalizedIdentity:
    return NormalizedIdentity.model_validate(
        {
            "object_id": object_id or new_id("obj"),
            "tenant_id": tenant_id,
            "external_id": external_id,
            "provider": provider,
            "identity_kind": identity_kind,
            "field_provenance": {"identity_kind": evidence_id or "provider:/kind"},
            "conflicts": [],
            "flagged": flagged,
            "evidence_id": evidence_id or new_id("evd"),
        }
    )


async def _add_role(harness: _Harness, *, source_id: str, evidence_id: str) -> AQObject:
    harness.object_store.registry.register("role", 1, None)
    return await harness.object_store.upsert(
        AQObject(
            id="",
            object_type="role",
            schema_version=1,
            tenant_id=TENANT,
            display_name="Billing administrator",
            attributes={"privileged": True},
            natural_keys=[NaturalKey(namespace="iag:role", value="billing-admin")],
            sources=[
                SourceRef(
                    source_id=source_id,
                    evidence_id=evidence_id,
                    observed_at=NOW,
                    method="test_fixture",
                )
            ],
            first_seen_at=NOW,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            created_by=ACTOR,
            updated_by=ACTOR,
        )
    )


async def test_ispm_no_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def blocked(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("network")
        raise AssertionError("ISPM ingest must not open a network connection")

    async with _harness() as harness:
        source_id = new_id("src")
        identity_evidence = await _evidence(
            harness,
            source_id=source_id,
            external_id="identity:alex",
        )
        account_evidence = await _evidence(
            harness,
            source_id=source_id,
            external_id="account:alex@example.test",
        )
        monkeypatch.setattr(socket, "socket", blocked)
        monkeypatch.setattr(socket, "create_connection", blocked)
        rows = await harness.engine.ingest_identities(
            [
                _descriptor(
                    source_id=source_id,
                    identity_evidence_id=identity_evidence.id,
                    account_evidence_id=account_evidence.id,
                )
            ],
            tenant_id=TENANT,
        )
    assert len(rows) == 1
    assert attempts == []
    assert not any(hasattr(ISPMEngine, name) for name in ("scan", "probe", "poll", "enumerate"))


async def test_ispm_normalize_to_iag_shape() -> None:
    async with _harness() as harness:
        source_id = new_id("src")
        identity_evidence = await _evidence(
            harness,
            source_id=source_id,
            external_id="identity:alex",
        )
        account_evidence = await _evidence(
            harness,
            source_id=source_id,
            external_id="account:alex@example.test",
        )
        role_evidence = await _evidence(
            harness,
            source_id=source_id,
            external_id="role:billing-admin",
        )
        role = await _add_role(harness, source_id=source_id, evidence_id=role_evidence.id)
        descriptor = _descriptor(
            source_id=source_id,
            identity_evidence_id=identity_evidence.id,
            account_evidence_id=account_evidence.id,
            access_edges=[
                IdentityAccessEdgeDescriptor(
                    from_external_id="account:alex@example.test",
                    to_object_id=role.id,
                    relation_type="has_role",
                    observed_at=NOW,
                    evidence_id=role_evidence.id,
                )
            ],
        )
        normalized = (await harness.engine.ingest_identities([descriptor], tenant_id=TENANT))[0]

        identity = await harness.object_store.get(normalized.object_id)
        account = await harness.object_store.get(normalized.account_object_ids[0])
        relationships = await harness.object_store.relationships(
            normalized.object_id,
            direction="out",
        )
        account_relationships = await harness.object_store.relationships(
            normalized.account_object_ids[0],
            direction="out",
        )
        inventory_rows = await harness.inventory_store.query(tenant_id=TENANT, limit=100)

        assert identity is not None
        assert identity.object_type == "identity"
        assert account is not None
        assert account.object_type == "account"
        assert [(rel.relation_type, rel.to_id) for rel in relationships] == [
            ("has_account", account.id)
        ]
        assert [(rel.relation_type, rel.to_id) for rel in account_relationships] == [
            ("has_role", role.id)
        ]
        assert all(rel.sources[0].evidence_id is not None for rel in relationships)
        assert all(rel.sources[0].evidence_id is not None for rel in account_relationships)
        assert {row.asset_type for row in inventory_rows} == {"identity", "account"}
        assert len(inventory_rows) == 2
        assert set(normalized.relationship_ids) == {
            relationships[0].id,
            account_relationships[0].id,
        }

        unknown_source = new_id("src")
        unknown_identity_evidence = await _evidence(
            harness,
            source_id=unknown_source,
            external_id="identity:unknown",
        )
        unknown_account_evidence = await _evidence(
            harness,
            source_id=unknown_source,
            external_id="account:unknown",
        )
        unknown = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=unknown_source,
                        identity_evidence_id=unknown_identity_evidence.id,
                        account_evidence_id=unknown_account_evidence.id,
                        external_id="identity:unknown",
                        account_external_id="account:unknown",
                        identity_kind=None,
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        unknown_object = await harness.object_store.get(unknown.object_id)
        assert unknown.identity_kind == "unknown"
        assert unknown.flagged is True
        assert unknown_object is not None
        assert unknown_object.labels["flagged"] == "true"
        with pytest.raises(ISPMConfigInvalid, match="unknown identity_kind must be flagged"):
            _normalized(identity_kind="unknown", flagged=False)


async def test_ispm_trust_reconciliation_records_conflicts() -> None:
    async with _harness() as harness:
        low_source = new_id("src")
        high_source = new_id("src")
        low_identity = await _evidence(
            harness,
            source_id=low_source,
            external_id="identity:alex",
            weight=0.2,
        )
        low_account = await _evidence(
            harness,
            source_id=low_source,
            external_id="account:alex@example.test",
            weight=0.2,
        )
        first = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=low_source,
                        identity_evidence_id=low_identity.id,
                        account_evidence_id=low_account.id,
                        identity_kind="human",
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        high_identity = await _evidence(
            harness,
            source_id=high_source,
            external_id="identity:alex",
            weight=0.95,
            observed_at=NOW + timedelta(minutes=1),
        )
        high_account = await _evidence(
            harness,
            source_id=high_source,
            external_id="account:alex@example.test",
            weight=0.95,
            observed_at=NOW + timedelta(minutes=1),
        )
        second = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=high_source,
                        identity_evidence_id=high_identity.id,
                        account_evidence_id=high_account.id,
                        identity_kind="service",
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]

        assert second.object_id == first.object_id
        assert second.identity_kind == "service"
        assert len(second.conflicts) == 1
        conflict = second.conflicts[0]
        assert conflict["resolved_by"] == high_source
        assert conflict["unresolved"] is False
        candidates = cast(list[dict[str, object]], conflict["candidates"])
        assert {candidate["source_id"] for candidate in candidates} == {
            low_source,
            high_source,
        }
        reliabilities = sorted(cast(float, candidate["reliability"]) for candidate in candidates)
        assert reliabilities == pytest.approx([0.2, 0.95])
        identity = await harness.object_store.get(second.object_id)
        assert identity is not None
        assert identity.attributes["identity_kind"] == "service"

        third = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=low_source,
                        identity_evidence_id=low_identity.id,
                        account_evidence_id=low_account.id,
                        identity_kind="human",
                        account_attributes={"last_used_at": "2099-01-01T00:00:00+00:00"},
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        account = await harness.object_store.get(third.account_object_ids[0])
        assert account is not None
        assert account.attributes["last_used_at"] == NOW.isoformat()
        account_conflicts = [
            conflict
            for conflict in third.conflicts
            if conflict["fields"] == ["accounts.account:alex@example.test"]
        ]
        assert len(account_conflicts) == 1
        assert account_conflicts[0]["resolved_by"] == high_source


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_ispm_store_contract(kind: str) -> None:
    async with _harness(kind) as harness:
        original = _normalized(external_id="identity:one")
        stored = await harness.store.upsert_identity(original)
        assert await harness.store.get_identity(stored.object_id, tenant_id=TENANT) == stored
        assert (
            await harness.store.get_identity_by_external(
                "entra",
                "identity:one",
                tenant_id=TENANT,
            )
            == stored
        )
        assert await harness.store.get_identity(stored.object_id, tenant_id=OTHER_TENANT) is None

        changed = stored.model_copy(
            update={"controls": stored.controls.model_copy(deep=True)},
            deep=True,
        )
        assert await harness.store.upsert_identity(changed) == stored
        with pytest.raises(TenantScopeRequired, match="tenant-scoped"):
            await harness.store.query_identities(tenant_id=None)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_ispm_pagination(kind: str) -> None:
    async with _harness(kind) as harness:
        inserted: list[NormalizedIdentity] = []
        for index in range(7):
            provider = "entra" if index >= 3 else "okta"
            identity = _normalized(
                provider=provider,
                external_id=f"identity:{index}",
            )
            inserted.append(await harness.store.upsert_identity(identity))
        expected = sorted(
            identity.object_id for identity in inserted if identity.provider == "entra"
        )
        seen: list[str] = []
        cursor: str | None = None
        while True:
            rows, cursor = await harness.store.query_identities(
                tenant_id=TENANT,
                provider="entra",
                cursor=cursor,
                limit=2,
            )
            seen.extend(row.object_id for row in rows)
            if cursor is None:
                break
        assert seen == expected
        exact, next_cursor = await harness.store.query_identities(
            tenant_id=TENANT,
            provider="entra",
            limit=len(expected),
        )
        assert [row.object_id for row in exact] == expected
        assert next_cursor is None


async def test_ispm_real_iag_round_trip() -> None:
    async with _harness() as harness:
        source_id = new_id("src")
        identity_evidence = await _evidence(
            harness,
            source_id=source_id,
            external_id="identity:dormant",
        )
        account_evidence = await _evidence(
            harness,
            source_id=source_id,
            external_id="account:dormant",
        )
        normalized = (
            await harness.engine.ingest_identities(
                [
                    _descriptor(
                        source_id=source_id,
                        identity_evidence_id=identity_evidence.id,
                        account_evidence_id=account_evidence.id,
                        external_id="identity:dormant",
                        account_external_id="account:dormant",
                        account_attributes={
                            "last_used_at": (utc_now() - timedelta(days=365)).isoformat()
                        },
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        iag = IdentityAccessGovernanceEngine(
            harness.object_store,
            InMemoryKnowledgeGraph(harness.object_store),
            PolicyEngine([]),
            InMemoryCertificationStore(mode="enterprise"),
            harness.evidence_store,
        )
        report = await iag.analyze_risk(
            tenant_id=TENANT,
            scope=ObjectQuery(tenant_id=TENANT),
        )
        account_id = normalized.account_object_ids[0]
        account_risks = [risk for risk in report.risks if risk.subject_id == account_id]
        assert any(risk.kind == "dormant" for risk in account_risks)
        assert all(risk.kind != "orphaned" for risk in account_risks)
