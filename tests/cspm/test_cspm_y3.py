"""Y3 acceptance tests for typed CSPM routing and owner delegation."""

from __future__ import annotations

import copy
import inspect
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import CloudConfigInvalid, CloudObjectNotFound, StoreUnavailable
from aqelyn.cspm import (
    ROUTE_OWNERS,
    CloudNormalizationConfig,
    CloudNormalizationStore,
    CloudPostureEngine,
    CloudResourceDescriptor,
    CloudRouteEnvelope,
    InMemoryCloudNormalizationStore,
    InventoryCloudOwnerRouter,
    PostgresCloudNormalizationStore,
    RouteOwner,
    cloud_asset_id,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.inventory import AssetRecord, DiscoverySource, InMemoryAssetStore
from aqelyn.inventory.engine import InventoryIntelligenceEngine
from aqelyn.objects import InMemoryObjectStore
from aqelyn.trust import InMemorySourceReliabilityRegistry

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 18, 16, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000280301"
OTHER_TENANT = "018f0000-0000-7000-8000-000000280302"
ACTOR = ActorRef(actor_type="system", actor_id="cspm-y3-test")
BASELINE_ID = "cis-aws-s3-v1"


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _OwnerSpy:
    owner: RouteOwner
    fail: bool = False
    mutate_copy: bool = False
    calls: list[tuple[CloudRouteEnvelope, str | None]] = field(default_factory=list)

    async def route(
        self,
        envelope: CloudRouteEnvelope,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]:
        self.calls.append((envelope.model_copy(deep=True), tenant_id))
        if self.mutate_copy:
            envelope.normalized.unreported_facts.clear()
        if self.fail:
            raise StoreUnavailable(f"{self.owner} unavailable")
        return [f"{self.owner}:{envelope.normalized.object_id}"]


@dataclass
class _BaselineSpy:
    result: str = field(default_factory=lambda: new_id("snap"))
    calls: list[tuple[tuple[str, ...], str | None, Mapping[str, object] | None]] = field(
        default_factory=list
    )

    async def apply(
        self,
        baseline_ids: Sequence[str],
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> str:
        self.calls.append(
            (
                tuple(baseline_ids),
                tenant_id,
                None if scope is None else copy.deepcopy(dict(scope)),
            )
        )
        return self.result


@dataclass
class _InventoryOwnerSpy:
    engine: InventoryIntelligenceEngine
    ingested_reports: list[Mapping[str, Any]] = field(default_factory=list)
    marked: list[str] = field(default_factory=list)
    decommissioned: list[str] = field(default_factory=list)

    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]:
        self.ingested_reports.extend(copy.deepcopy(list(reports)))
        return await self.engine.ingest(reports=reports, source=source, tenant_id=tenant_id)

    async def mark_unreported(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> AssetRecord:
        self.marked.append(asset_id)
        return await self.engine.mark_unreported(asset_id, tenant_id=tenant_id)

    async def decommission(self, asset_id: str) -> None:
        self.decommissioned.append(asset_id)


@dataclass
class _Harness:
    store: CloudNormalizationStore
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    engine: CloudPostureEngine


def _config() -> CloudNormalizationConfig:
    return CloudNormalizationConfig.model_validate(
        {
            "type_map": {"aws:s3:bucket": "cloud_storage"},
            "fact_paths": {
                "aws:s3:bucket": {
                    "encryption_enabled": "/configuration/encryptionEnabled",
                    "network_public": "/configuration/network/public",
                }
            },
            "baseline_ids": [BASELINE_ID],
            "batch_size": 20,
        },
        context={
            "known_object_types": {"cloud_storage"},
            "known_baseline_ids": {BASELINE_ID},
        },
    )


@asynccontextmanager
async def _harness(
    kind: str,
    *,
    routers: Sequence[object],
    baseline_router: object | None = None,
) -> AsyncIterator[_Harness]:
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
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.7)
    engine = CloudPostureEngine(
        store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=registry,
        config=_config(),
        owner_routers=cast(Any, routers),
        baseline_router=cast(Any, baseline_router),
        actor=ACTOR,
    )
    try:
        yield _Harness(store, object_store, evidence_store, engine)
    finally:
        if closer is not None:
            await closer.close()


def _raw(*, include_encryption: bool = True) -> dict[str, object]:
    configuration: dict[str, object] = {"network": {"public": True}}
    if include_encryption:
        configuration["encryptionEnabled"] = True
    return {"configuration": configuration}


def _descriptor(
    *,
    source_id: str,
    raw: dict[str, object] | None = None,
    observed_at: datetime = NOW,
    change_kind: str = "observed",
    resource_id: str = "arn:aws:s3:::customer-exports",
) -> CloudResourceDescriptor:
    return CloudResourceDescriptor.model_validate(
        {
            "provider": "aws",
            "account": "123456789012",
            "region": "eu-north-1",
            "resource_type": "s3:bucket",
            "resource_id": resource_id,
            "raw": raw or _raw(),
            "observed_at": observed_at,
            "source_id": source_id,
            "change_kind": change_kind,
        }
    )


def _owner_spies(*, failed: RouteOwner | None = None) -> list[_OwnerSpy]:
    return [
        _OwnerSpy(
            owner=cast(RouteOwner, owner),
            fail=owner == failed,
            mutate_copy=owner == "assetconfig",
        )
        for owner in sorted(ROUTE_OWNERS)
    ]


async def _normalized_with_unreported_fact(harness: _Harness) -> str:
    source_id = new_id("src")
    first = (
        await harness.engine.normalize(
            [_descriptor(source_id=source_id)],
            tenant_id=TENANT,
        )
    )[0]
    second = (
        await harness.engine.normalize(
            [
                _descriptor(
                    source_id=source_id,
                    raw=_raw(include_encryption=False),
                    observed_at=NOW + timedelta(minutes=5),
                )
            ],
            tenant_id=TENANT,
        )
    )[0]
    assert second.object_id == first.object_id
    return second.object_id


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_cspm_routing(kind: str) -> None:
    spies = _owner_spies()
    async with _harness(kind, routers=spies) as harness:
        object_id = await _normalized_with_unreported_fact(harness)
        results = await harness.engine.route([object_id], tenant_id=TENANT)

        assert len(results) == 1
        result = results[0]
        assert result.status == "complete"
        assert [outcome.owner for outcome in result.outcomes] == sorted(ROUTE_OWNERS)
        assert all(outcome.status == "accepted" for outcome in result.outcomes)
        for spy in spies:
            assert len(spy.calls) == 1
            envelope, routed_tenant = spy.calls[0]
            assert routed_tenant == TENANT
            assert envelope.normalized.object_id == object_id
            assert "encryption_enabled" in envelope.normalized.unreported_facts
            assert envelope.change_kind == "observed"

        obj = await harness.object_store.get(object_id, resolve_merged=False)
        assert obj is not None
        assert "encryption_enabled" not in obj.attributes["observed_state"]
        assert "encryption_enabled" in obj.attributes["unreported_facts"]


async def test_cspm_all_delegations() -> None:
    spies = _owner_spies()
    async with _harness("inmemory", routers=spies) as harness:
        object_id = await _normalized_with_unreported_fact(harness)
        await harness.engine.route([object_id], tenant_id=TENANT)

        assert {spy.owner for spy in spies if spy.calls} == ROUTE_OWNERS
        marker_ids = {
            spy.calls[0][0].normalized.unreported_facts["encryption_enabled"].evidence_id
            for spy in spies
        }
        assert len(marker_ids) == 1


async def test_cspm_partial_routing_visible() -> None:
    spies = _owner_spies(failed="exposure")
    async with _harness("inmemory", routers=spies) as harness:
        object_id = await _normalized_with_unreported_fact(harness)
        result = (await harness.engine.route([object_id], tenant_id=TENANT))[0]

        assert result.status == "partial"
        outcomes = {outcome.owner: outcome for outcome in result.outcomes}
        assert outcomes["exposure"].status == "failed"
        assert outcomes["exposure"].detail == "exposure unavailable"
        assert all(
            outcome.status == "accepted"
            for owner, outcome in outcomes.items()
            if owner != "exposure"
        )


async def test_cspm_config_delegates() -> None:
    baseline = _BaselineSpy()
    async with _harness(
        "inmemory",
        routers=_owner_spies(),
        baseline_router=baseline,
    ) as harness:
        scope: Mapping[str, object] = {"labels": {"module": "EA-0028"}, "limit": 20}
        result = await harness.engine.apply_cloud_baselines(
            tenant_id=TENANT,
            scope=scope,
        )

        assert result == baseline.result
        assert baseline.calls == [((BASELINE_ID,), TENANT, scope)]


async def test_cspm_tenant_isolation() -> None:
    spies = _owner_spies()
    async with _harness("inmemory", routers=spies) as harness:
        object_id = await _normalized_with_unreported_fact(harness)

        with pytest.raises(CloudObjectNotFound):
            await harness.engine.route([object_id], tenant_id=OTHER_TENANT)
        assert all(spy.calls == [] for spy in spies)


async def test_cspm_routing_refuses_tampered_evidence() -> None:
    spies = _owner_spies()
    async with _harness("inmemory", routers=spies) as harness:
        object_id = await _normalized_with_unreported_fact(harness)
        normalized = await harness.store.get(object_id, tenant_id=TENANT)
        assert normalized is not None
        evidence = harness.evidence_store._by_id[normalized.evidence_id]
        harness.evidence_store._by_id[normalized.evidence_id] = evidence.model_copy(
            update={"content": {"tampered": True}}
        )

        with pytest.raises(CloudConfigInvalid, match="evidence failed verification"):
            await harness.engine.route([object_id], tenant_id=TENANT)
        assert all(spy.calls == [] for spy in spies)


async def test_cspm_routing_refuses_evidence_rebound_from_another_object() -> None:
    spies = _owner_spies()
    async with _harness("inmemory", routers=spies) as harness:
        source_id = new_id("src")
        first, second = await harness.engine.normalize(
            [
                _descriptor(source_id=source_id),
                _descriptor(
                    source_id=source_id,
                    resource_id="arn:aws:s3:::other-bucket",
                ),
            ],
            tenant_id=TENANT,
        )
        await harness.store.put(
            first.model_copy(update={"evidence_id": second.evidence_id}, deep=True)
        )

        with pytest.raises(CloudConfigInvalid, match="does not name the normalized object"):
            await harness.engine.route([first.object_id], tenant_id=TENANT)
        assert all(spy.calls == [] for spy in spies)


async def test_cspm_no_side_effects() -> None:
    spies = _owner_spies()
    async with _harness("inmemory", routers=spies) as harness:
        object_id = await _normalized_with_unreported_fact(harness)
        await harness.engine.route([object_id], tenant_id=TENANT)

        public = {
            name
            for name, value in inspect.getmembers(harness.engine)
            if not name.startswith("_") and callable(value)
        }
        assert not ({"execute", "propose", "raise_finding", "score", "detect"} & public)
        assert sum(len(spy.calls) for spy in spies) == len(ROUTE_OWNERS)


async def test_cspm_deleted_maps_unreported() -> None:
    inventory_store = InMemoryAssetStore(mode="enterprise")
    inventory_engine = InventoryIntelligenceEngine(inventory_store)
    inventory_owner = _InventoryOwnerSpy(inventory_engine)
    inventory_router = InventoryCloudOwnerRouter(inventory_owner)
    other_spies = [spy for spy in _owner_spies() if spy.owner != "inventory"]

    async with _harness(
        "inmemory",
        routers=[inventory_router, *other_spies],
    ) as harness:
        source_id = new_id("src")
        observed = (
            await harness.engine.normalize(
                [_descriptor(source_id=source_id)],
                tenant_id=TENANT,
            )
        )[0]
        await harness.engine.route([observed.object_id], tenant_id=TENANT)
        asset_id = cloud_asset_id(observed.object_id)
        active = await inventory_store.get(asset_id, tenant_id=TENANT)
        assert active is not None
        assert active.lifecycle_state == "active"
        assert inventory_owner.ingested_reports[0]["unreported_facts"] == {}

        deleted = (
            await harness.engine.normalize(
                [
                    _descriptor(
                        source_id=source_id,
                        observed_at=NOW + timedelta(minutes=5),
                        change_kind="reported_deleted",
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        result = (await harness.engine.route([deleted.object_id], tenant_id=TENANT))[0]

        assert result.status == "complete"
        assert [outcome.owner for outcome in result.outcomes] == ["inventory"]
        assert inventory_owner.marked == [asset_id]
        assert inventory_owner.decommissioned == []
        unreported = await inventory_store.get(asset_id, tenant_id=TENANT)
        assert unreported is not None
        assert unreported.lifecycle_state == "unreported"
        assert all(len(spy.calls) == 1 for spy in other_spies)
