"""Y2 acceptance tests for selective cloud normalization and persistence."""

from __future__ import annotations

import inspect
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol, cast

import pytest

import aqelyn.cspm as cspm
from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    CloudConfigInvalid,
    CrossTenantReference,
    TenantScopeRequired,
)
from aqelyn.cspm import (
    CLOUD_UNKNOWN_OBJECT_TYPE,
    CloudNormalizationConfig,
    CloudNormalizationStore,
    CloudPostureEngine,
    CloudResourceDescriptor,
    InMemoryCloudNormalizationStore,
    NormalizedCloudObject,
    PostgresCloudNormalizationStore,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.objects import InMemoryObjectStore
from aqelyn.trust import InMemorySourceReliabilityRegistry, SourceReliability

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 18, 14, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000280201"
OTHER_TENANT = "018f0000-0000-7000-8000-000000280202"
ACTOR = ActorRef(actor_type="system", actor_id="cspm-y2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: CloudNormalizationStore
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    registry: InMemorySourceReliabilityRegistry
    engine: CloudPostureEngine


def _config() -> CloudNormalizationConfig:
    return CloudNormalizationConfig.model_validate(
        {
            "type_map": {
                "aws:s3:bucket": "cloud_storage",
                "azure:network:security_group": "network_security_group",
            },
            "fact_paths": {
                "aws:s3:bucket": {
                    "encryption_enabled": "/configuration/encryptionEnabled",
                    "network_public": "/configuration/network/public",
                    "open_ports": "/configuration/network/openPorts",
                },
                "azure:network:security_group": {
                    "network_public": "/properties/public",
                    "open_ports": "/properties/openPorts",
                },
            },
            "baseline_ids": [],
            "batch_size": 20,
        },
        context={
            "known_object_types": {"cloud_storage", "network_security_group"},
            "known_baseline_ids": set(),
        },
    )


@asynccontextmanager
async def _harness(kind: str) -> AsyncIterator[_Harness]:
    if kind == "inmemory":
        store: CloudNormalizationStore = InMemoryCloudNormalizationStore(mode="enterprise")
        closer: _Closable | None = None
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresCloudNormalizationStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_cloud_normalization")
        store = postgres
        closer = cast(_Closable, postgres)
    object_store = InMemoryObjectStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    engine = CloudPostureEngine(
        store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=registry,
        config=_config(),
        actor=ACTOR,
    )
    try:
        yield _Harness(store, object_store, evidence_store, registry, engine)
    finally:
        if closer is not None:
            await closer.close()


def _raw(*, encryption_enabled: bool = True) -> dict[str, object]:
    return {
        "configuration": {
            "encryptionEnabled": encryption_enabled,
            "network": {"public": False, "openPorts": [22, 443]},
        },
        "complianceType": "NON_COMPLIANT",
        "complianceState": "failed",
        "Severity": "HIGH",
        "policy": {"posture_grade": "F"},
    }


def _descriptor(
    *,
    source_id: str | None = None,
    resource_type: str = "s3:bucket",
    resource_id: str = "arn:aws:s3:::customer-exports",
    raw: dict[str, object] | None = None,
    observed_at: datetime = NOW,
) -> CloudResourceDescriptor:
    return CloudResourceDescriptor(
        provider="aws",
        account="123456789012",
        region="eu-north-1",
        resource_type=resource_type,
        resource_id=resource_id,
        raw=raw or _raw(),
        observed_at=observed_at,
        source_id=source_id or new_id("src"),
    )


def _normalized(
    *,
    object_id: str | None = None,
    tenant_id: str | None = TENANT,
    provider: str = "aws",
) -> NormalizedCloudObject:
    return NormalizedCloudObject.model_validate(
        {
            "object_id": object_id or new_id("obj"),
            "object_type": "cloud_storage",
            "tenant_id": tenant_id,
            "provider": provider,
            "account": "123456789012",
            "region": "eu-north-1",
            "native_facts": {"encryption_enabled": True, "open_ports": [443]},
            "field_provenance": {
                "encryption_enabled": "/configuration/encryptionEnabled",
                "open_ports": "/configuration/network/openPorts",
            },
            "conflicts": [],
            "evidence_id": new_id("evd"),
            "flagged": False,
        }
    )


async def _set_reliability(
    registry: InMemorySourceReliabilityRegistry,
    source_id: str,
    weight: float,
) -> None:
    await registry.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="Y2 conflict precedence fixture.",
            set_by=ACTOR,
            set_at=NOW,
            version=1,
        )
    )


async def test_cspm_no_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _harness("inmemory") as harness:
        forbidden = {"enumerate", "scan", "probe", "connect"}
        public_callables = {
            name
            for name, value in inspect.getmembers(cspm)
            if not name.startswith("_") and callable(value)
        }
        assert not (public_callables & forbidden)

        attempts: list[str] = []

        def blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
            attempts.append("socket")
            raise AssertionError("CSPM normalization must not open sockets")

        def blocked_connection(*_args: object, **_kwargs: object) -> NoReturn:
            attempts.append("create_connection")
            raise AssertionError("CSPM normalization must not create network connections")

        monkeypatch.setattr(socket, "socket", blocked_socket)
        monkeypatch.setattr(socket, "create_connection", blocked_connection)

        result = await harness.engine.normalize([_descriptor()], tenant_id=TENANT)

        assert len(result) == 1
        assert attempts == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_cspm_normalize_object(kind: str) -> None:
    async with _harness(kind) as harness:
        descriptor = _descriptor()
        normalized = (await harness.engine.normalize([descriptor], tenant_id=TENANT))[0]

        assert normalized.object_type == "cloud_storage"
        assert normalized.provider == "aws"
        assert normalized.account == descriptor.account
        assert normalized.region == descriptor.region
        assert normalized.flagged is False
        assert normalized.native_facts == {
            "encryption_enabled": True,
            "network_public": False,
            "open_ports": [22, 443],
        }
        assert await harness.store.get(normalized.object_id, tenant_id=TENANT) == normalized

        obj = await harness.object_store.get(normalized.object_id, resolve_merged=False)
        assert obj is not None
        assert obj.object_type == "cloud_storage"
        assert obj.tenant_id == TENANT
        assert obj.attributes["resource_id"] == descriptor.resource_id
        assert obj.attributes["native_facts"] == normalized.native_facts
        assert "raw" not in obj.attributes

        evidence = await harness.evidence_store.get(normalized.evidence_id, actor=ACTOR)
        assert evidence.content is not None
        assert evidence.content["raw"] == descriptor.raw
        assert evidence.subject.object_ids == [normalized.object_id]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_cspm_field_provenance(kind: str) -> None:
    async with _harness(kind) as harness:
        normalized = (await harness.engine.normalize([_descriptor()], tenant_id=TENANT))[0]

        assert normalized.field_provenance == {
            "encryption_enabled": "/configuration/encryptionEnabled",
            "network_public": "/configuration/network/public",
            "open_ports": "/configuration/network/openPorts",
        }
        assert set(normalized.native_facts) == set(normalized.field_provenance)
        assert harness.engine.explain(normalized)["field_provenance"] == (
            normalized.field_provenance
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_cspm_selective_flatten(kind: str) -> None:
    async with _harness(kind) as harness:
        descriptor = _descriptor()
        normalized = (await harness.engine.normalize([descriptor], tenant_id=TENANT))[0]

        assert "complianceType" not in normalized.native_facts
        assert "complianceState" not in normalized.native_facts
        assert "Severity" not in normalized.native_facts
        assert "policy" not in normalized.native_facts
        assert all(not isinstance(value, dict) for value in normalized.native_facts.values())

        evidence = await harness.evidence_store.get(normalized.evidence_id, actor=ACTOR)
        assert evidence.content is not None
        raw = evidence.content["raw"]
        assert isinstance(raw, dict)
        assert raw["Severity"] == "HIGH"
        assert raw["complianceType"] == "NON_COMPLIANT"

        structured_config = _config().model_copy(
            update={"fact_paths": {"aws:s3:bucket": {"configuration": "/configuration"}}},
            deep=True,
        )
        structured_engine = CloudPostureEngine(
            harness.store,
            object_store=harness.object_store,
            evidence_store=harness.evidence_store,
            source_registry=harness.registry,
            config=structured_config,
            actor=ACTOR,
        )
        with pytest.raises(CloudConfigInvalid, match="select scalar leaves"):
            await structured_engine.normalize(
                [_descriptor(resource_id="arn:aws:s3:::structured")],
                tenant_id=TENANT,
            )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_cspm_conflict_recorded(kind: str) -> None:
    async with _harness(kind) as harness:
        trusted_source = new_id("src")
        weak_source = new_id("src")
        await _set_reliability(harness.registry, trusted_source, 0.9)
        await _set_reliability(harness.registry, weak_source, 0.2)

        first = (
            await harness.engine.normalize(
                [_descriptor(source_id=trusted_source, raw=_raw(encryption_enabled=True))],
                tenant_id=TENANT,
            )
        )[0]
        second = (
            await harness.engine.normalize(
                [
                    _descriptor(
                        source_id=weak_source,
                        raw=_raw(encryption_enabled=False),
                        observed_at=NOW + timedelta(minutes=5),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]

        assert second.object_id == first.object_id
        assert second.native_facts["encryption_enabled"] is True
        assert len(second.conflicts) == 1
        conflict = second.conflicts[0]
        assert conflict["field"] == "encryption_enabled"
        assert conflict["resolved_by"] == trusted_source
        assert conflict["reason"] == "higher source reliability"
        candidates = {item["source_id"]: item for item in conflict["candidates"]}
        assert candidates[trusted_source]["value"] is True
        assert candidates[trusted_source]["reliability"] == 0.9
        assert candidates[weak_source]["value"] is False
        assert candidates[weak_source]["reliability"] == 0.2
        assert await harness.store.get(second.object_id, tenant_id=TENANT) == second

        await _set_reliability(harness.registry, trusted_source, 0.1)
        await _set_reliability(harness.registry, weak_source, 0.8)
        third = (
            await harness.engine.normalize(
                [
                    _descriptor(
                        source_id=weak_source,
                        raw=_raw(encryption_enabled=False),
                        observed_at=NOW + timedelta(minutes=10),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        assert third.native_facts["encryption_enabled"] is False
        assert len(third.conflicts) == 2
        assert third.conflicts[-1]["resolved_by"] == weak_source
        refreshed = {item["source_id"]: item for item in third.conflicts[-1]["candidates"]}
        assert refreshed[trusted_source]["reliability"] == 0.1
        assert refreshed[weak_source]["reliability"] == 0.8


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_cspm_unknown_flagged(kind: str) -> None:
    async with _harness(kind) as harness:
        descriptor = _descriptor(
            resource_type="lambda:function",
            resource_id="arn:aws:lambda:eu-north-1:123456789012:function:billing",
        )
        normalized = (await harness.engine.normalize([descriptor], tenant_id=TENANT))[0]

        assert normalized.object_type == CLOUD_UNKNOWN_OBJECT_TYPE
        assert normalized.flagged is True
        assert normalized.native_facts == {}
        assert normalized.field_provenance == {}
        assert await harness.store.get(normalized.object_id, tenant_id=TENANT) == normalized

        evidence = await harness.evidence_store.get(normalized.evidence_id, actor=ACTOR)
        assert evidence.content is not None
        assert evidence.content["raw"] == descriptor.raw


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_cspm_store_contract(kind: str) -> None:
    async with _harness(kind) as harness:
        first = await harness.store.put(_normalized())
        other = await harness.store.put(_normalized(tenant_id=OTHER_TENANT, provider="azure"))

        assert await harness.store.get(first.object_id, tenant_id=TENANT) == first
        assert await harness.store.get(first.object_id, tenant_id=OTHER_TENANT) is None
        assert [row.object_id for row in await harness.store.query(tenant_id=TENANT)] == [
            first.object_id
        ]
        assert [
            row.object_id
            for row in await harness.store.query(tenant_id=OTHER_TENANT, provider="azure")
        ] == [other.object_id]
        assert await harness.store.query(tenant_id=TENANT, provider="gcp") == []

        changed = first.model_copy(
            update={
                "native_facts": {"encryption_enabled": False, "open_ports": [22, 443]},
                "conflicts": [{"field": "encryption_enabled", "reason": "test update"}],
            },
            deep=True,
        )
        updated = await harness.store.put(changed)
        assert await harness.store.get(first.object_id, tenant_id=TENANT) == updated

        updated.native_facts["open_ports"].append(8443)
        reread = await harness.store.get(first.object_id, tenant_id=TENANT)
        assert reread is not None
        assert reread.native_facts["open_ports"] == [22, 443]

        with pytest.raises(CrossTenantReference, match="tenant_id cannot change"):
            await harness.store.put(first.model_copy(update={"tenant_id": OTHER_TENANT}, deep=True))

        with pytest.raises(TenantScopeRequired, match="tenant-scoped"):
            await harness.store.get(first.object_id, tenant_id=None)
        with pytest.raises(TenantScopeRequired, match="tenant-scoped"):
            await harness.store.query(tenant_id=None)

        if kind == "inmemory":
            local: CloudNormalizationStore = InMemoryCloudNormalizationStore(mode="local")
        else:
            postgres = cast(PostgresCloudNormalizationStore, harness.store)
            local = PostgresCloudNormalizationStore(postgres._pool, mode="local")
        local_row = await local.put(_normalized(tenant_id=None))
        assert await local.get(local_row.object_id, tenant_id=None) == local_row
        assert await local.get(local_row.object_id, tenant_id=TENANT) is None
