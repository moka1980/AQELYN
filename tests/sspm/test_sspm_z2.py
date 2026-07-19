"""Z2 acceptance tests for SSPM normalization, routing, and persistence."""

from __future__ import annotations

import inspect
import os
import socket
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol, cast

import pytest

import aqelyn.sspm as sspm
from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    BusUnavailable,
    CrossTenantReference,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.objects import InMemoryObjectStore
from aqelyn.sspm import (
    SAAS_UNKNOWN_OBJECT_TYPE,
    InMemorySaaSNormalizationStore,
    NormalizedSaaSObject,
    PostgresSaaSNormalizationStore,
    SaaSAppDescriptor,
    SaaSConfig,
    SaaSIntegration,
    SaaSNormalizationStore,
    SaaSPostureEngine,
    SaaSRouteOwner,
    saas_asset_id,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry, SourceReliability

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 19, 15, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000290201"
OTHER_TENANT = "018f0000-0000-7000-8000-000000290202"
ACTOR = ActorRef(actor_type="system", actor_id="sspm-z2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: SaaSNormalizationStore
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    registry: InMemorySourceReliabilityRegistry
    engine: SaaSPostureEngine


@dataclass
class _Router:
    owner: SaaSRouteOwner
    calls: list[str] = field(default_factory=list)
    error: Exception | None = None

    async def route(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]:
        self.calls.append(obj.object_id)
        if self.error is not None:
            raise self.error
        assert obj.tenant_id == tenant_id
        if self.owner == "inventory":
            return [saas_asset_id(obj.object_id)]
        return [obj.object_id]


def _config() -> SaaSConfig:
    return SaaSConfig.model_validate(
        {
            "type_map": {
                "google_workspace:application": "saas_app",
                "microsoft_365:application": "saas_app",
            },
            "baseline_ids": [],
            "sensitive_scopes": ["read_all_files"],
            "batch_size": 20,
            "integration_max_nodes": 1000,
        },
        context={"known_object_types": {"saas_app"}, "known_baseline_ids": set()},
    )


@asynccontextmanager
async def _harness(
    kind: str,
    *,
    routers: Sequence[_Router] = (),
) -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: SaaSNormalizationStore = InMemorySaaSNormalizationStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresSaaSNormalizationStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_saas_normalization, aq_saas_integration")
        store = postgres
        closer = cast(_Closable, postgres)
    object_store = InMemoryObjectStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    engine = SaaSPostureEngine(
        store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=registry,
        config=_config(),
        owner_routers=routers,
        actor=ACTOR,
    )
    try:
        yield _Harness(store, object_store, evidence_store, registry, engine)
    finally:
        if closer is not None:
            await closer.close()


def _descriptor(
    *,
    source_id: str | None = None,
    resource_type: str = "application",
    app_id: str = "calendar-helper",
    raw: dict[str, object] | None = None,
    observed_at: datetime = NOW,
) -> SaaSAppDescriptor:
    return SaaSAppDescriptor(
        provider="google_workspace",
        tenant="example.com",
        app_id=app_id,
        app_name="Calendar Helper",
        resource_type=resource_type,
        raw=raw
        or {
            "mfa_enabled": True,
            "external_sharing": False,
            "allowed_domains": ["example.com"],
            "Severity": "HIGH",
            "provider_assessment": {"status": "NON_COMPLIANT"},
        },
        observed_at=observed_at,
        source_id=source_id or new_id("src"),
    )


def _normalized(
    *,
    object_id: str | None = None,
    tenant_id: str | None = TENANT,
    provider: str = "google_workspace",
) -> NormalizedSaaSObject:
    return NormalizedSaaSObject(
        object_id=object_id or new_id("obj"),
        tenant_id=tenant_id,
        object_type="saas_app",
        provider=provider,
        tenant="example.com",
        native_facts={"mfa_enabled": True},
        field_provenance={"mfa_enabled": "/mfa_enabled"},
        conflicts=[],
        evidence_id=new_id("evd"),
        flagged=False,
    )


def _integration(
    *,
    object_id: str | None = None,
    tenant_id: str | None = TENANT,
    over_scoped: str = "within_scope",
) -> SaaSIntegration:
    selected_id = object_id or new_id("obj")
    return SaaSIntegration.model_validate(
        {
            "object_id": selected_id,
            "tenant_id": tenant_id,
            "integration_id": f"integration:{selected_id}",
            "grantor_ref": new_id("obj"),
            "grantor_kind": "api",
            "third_party_app": new_id("obj"),
            "third_party_external": over_scoped == "over_scoped",
            "scopes": ["calendar.read"],
            "over_scoped": over_scoped,
            "reachable_object_ids": [],
            "reach_status": "computed",
            "known_surface_ref": selected_id if over_scoped == "over_scoped" else None,
            "claim_confidence": 0.8,
            "evidence_id": new_id("evd"),
            "observed_at": NOW,
            "reason": "Store contract fixture.",
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
            rationale="Z2 conflict precedence fixture.",
            set_by=ACTOR,
            set_at=NOW,
            version=1,
        )
    )


async def test_sspm_no_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"enumerate", "scan", "probe"}
    public_callables = {
        name
        for name, value in inspect.getmembers(sspm)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & forbidden)

    attempts: list[str] = []

    def blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("socket")
        raise AssertionError("SSPM normalization must not open sockets")

    def blocked_connection(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("create_connection")
        raise AssertionError("SSPM normalization must not create network connections")

    async with _harness("inmemory") as harness:
        monkeypatch.setattr(socket, "socket", blocked_socket)
        monkeypatch.setattr(socket, "create_connection", blocked_connection)
        result = await harness.engine.normalize([_descriptor()], tenant_id=TENANT)

    assert len(result) == 1
    assert attempts == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_normalize_object(kind: str) -> None:
    async with _harness(kind) as harness:
        descriptor = _descriptor()
        normalized = (await harness.engine.normalize([descriptor], tenant_id=TENANT))[0]

        assert normalized.object_type == "saas_app"
        assert normalized.native_facts == {
            "allowed_domains": ["example.com"],
            "external_sharing": False,
            "mfa_enabled": True,
        }
        assert normalized.field_provenance == {
            "allowed_domains": "/allowed_domains",
            "external_sharing": "/external_sharing",
            "mfa_enabled": "/mfa_enabled",
        }
        assert "Severity" not in normalized.native_facts
        assert "provider_assessment" not in normalized.native_facts
        assert await harness.store.get(normalized.object_id, tenant_id=TENANT) == normalized

        obj = await harness.object_store.get(normalized.object_id, resolve_merged=False)
        assert obj is not None
        assert obj.object_type == "saas_app"
        assert obj.attributes["native_facts"] == normalized.native_facts
        assert "raw" not in obj.attributes

        evidence = await harness.evidence_store.get(normalized.evidence_id, actor=ACTOR)
        assert evidence.content is not None
        assert evidence.content["raw"] == descriptor.raw
        assert evidence.subject.object_ids == [normalized.object_id]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_conflict_recorded(kind: str) -> None:
    async with _harness(kind) as harness:
        trusted_source = new_id("src")
        weak_source = new_id("src")
        await _set_reliability(harness.registry, trusted_source, 0.9)
        await _set_reliability(harness.registry, weak_source, 0.2)

        first = (
            await harness.engine.normalize(
                [_descriptor(source_id=trusted_source, raw={"mfa_enabled": True})],
                tenant_id=TENANT,
            )
        )[0]
        second = (
            await harness.engine.normalize(
                [
                    _descriptor(
                        source_id=weak_source,
                        raw={"mfa_enabled": False},
                        observed_at=NOW + timedelta(minutes=5),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]

        assert second.object_id == first.object_id
        assert second.native_facts["mfa_enabled"] is True
        assert second.conflicts[-1]["resolved_by"] == trusted_source
        assert second.conflicts[-1]["reason"] == "higher source reliability"
        candidates = {item["source_id"]: item for item in second.conflicts[-1]["candidates"]}
        assert candidates[trusted_source]["value"] is True
        assert candidates[weak_source]["value"] is False


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_unknown_flagged(kind: str) -> None:
    async with _harness(kind) as harness:
        unknown = (
            await harness.engine.normalize(
                [_descriptor(resource_type="unknown_app", app_id="unknown")],
                tenant_id=TENANT,
            )
        )[0]
        assert unknown.object_type == SAAS_UNKNOWN_OBJECT_TYPE
        assert unknown.flagged is True
        assert await harness.store.get(unknown.object_id, tenant_id=TENANT) == unknown


async def test_sspm_routing_pending() -> None:
    routers = [_Router(owner=owner) for owner in ("inventory", "assetconfig", "compliance", "iag")]
    async with _harness("inmemory", routers=routers) as harness:
        routed_obj = (await harness.engine.normalize([_descriptor()], tenant_id=TENANT))[0]
        routed = (await harness.engine.route([routed_obj.object_id], tenant_id=TENANT))[0]
        assert routed.routed_to == ["inventory", "assetconfig", "compliance", "iag"]
        assert routed.routing_pending == []
        assert routed.inventory_ref == saas_asset_id(routed_obj.object_id)
        assert routed.iam_refs == [routed_obj.object_id]

        empty_obj = (
            await harness.engine.normalize(
                [
                    _descriptor(
                        app_id="structured-only",
                        raw={"provider_assessment": {"status": "unknown"}},
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        pending = (await harness.engine.route([empty_obj.object_id], tenant_id=TENANT))[0]
        assert pending.routed_to == []
        assert pending.routing_pending == ["inventory", "assetconfig", "compliance", "iag"]
        assert all(router.calls == [routed_obj.object_id] for router in routers)


async def test_sspm_routing_propagates_programming_errors() -> None:
    unavailable = _Router(owner="inventory", error=StoreUnavailable("inventory unavailable"))
    async with _harness("inmemory", routers=[unavailable]) as harness:
        obj = (await harness.engine.normalize([_descriptor()], tenant_id=TENANT))[0]
        result = (await harness.engine.route([obj.object_id], tenant_id=TENANT))[0]
        assert result.routing_pending == ["inventory", "assetconfig", "compliance", "iag"]

    bus_unavailable = _Router(owner="inventory", error=BusUnavailable("bus unavailable"))
    async with _harness("inmemory", routers=[bus_unavailable]) as harness:
        obj = (await harness.engine.normalize([_descriptor()], tenant_id=TENANT))[0]
        result = (await harness.engine.route([obj.object_id], tenant_id=TENANT))[0]
        assert result.routing_pending == ["inventory", "assetconfig", "compliance", "iag"]

    broken = _Router(owner="inventory", error=RuntimeError("adapter defect"))
    async with _harness("inmemory", routers=[broken]) as harness:
        obj = (await harness.engine.normalize([_descriptor()], tenant_id=TENANT))[0]
        with pytest.raises(RuntimeError, match="adapter defect"):
            await harness.engine.route([obj.object_id], tenant_id=TENANT)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_store_contract(kind: str) -> None:
    async with _harness(kind) as harness:
        first = await harness.store.put(_normalized())
        other = await harness.store.put(
            _normalized(tenant_id=OTHER_TENANT, provider="microsoft_365")
        )
        integration = await harness.store.put_integration(_integration())

        assert await harness.store.get(first.object_id, tenant_id=TENANT) == first
        assert await harness.store.get(first.object_id, tenant_id=OTHER_TENANT) is None
        assert (
            await harness.store.get_integration(integration.object_id, tenant_id=TENANT)
            == integration
        )
        rows, cursor = await harness.store.query(tenant_id=TENANT)
        assert [row.object_id for row in rows] == [first.object_id]
        assert cursor is None
        other_rows, cursor = await harness.store.query(
            tenant_id=OTHER_TENANT,
            provider="microsoft_365",
        )
        assert [row.object_id for row in other_rows] == [other.object_id]
        assert cursor is None

        changed = first.model_copy(
            update={"native_facts": {"mfa_enabled": False}},
            deep=True,
        )
        updated = await harness.store.put(changed)
        updated.native_facts["mfa_enabled"] = "mutated"
        reread = await harness.store.get(first.object_id, tenant_id=TENANT)
        assert reread is not None
        assert reread.native_facts["mfa_enabled"] is False

        with pytest.raises(CrossTenantReference, match="tenant_id cannot change"):
            await harness.store.put(first.model_copy(update={"tenant_id": OTHER_TENANT}, deep=True))
        with pytest.raises(CrossTenantReference, match="tenant_id cannot change"):
            await harness.store.put_integration(
                integration.model_copy(update={"tenant_id": OTHER_TENANT}, deep=True)
            )
        with pytest.raises(TenantScopeRequired, match="tenant-scoped"):
            await harness.store.query(tenant_id=None)
        with pytest.raises(TenantScopeRequired, match="tenant-scoped"):
            await harness.store.query_integrations(tenant_id=None)

        if kind == "inmemory":
            local: SaaSNormalizationStore = InMemorySaaSNormalizationStore(mode="local")
        else:
            postgres = cast(PostgresSaaSNormalizationStore, harness.store)
            local = PostgresSaaSNormalizationStore(postgres._pool, mode="local")
        local_row = await local.put(_normalized(tenant_id=None))
        local_integration = await local.put_integration(_integration(tenant_id=None))
        assert await local.get(local_row.object_id, tenant_id=None) == local_row
        assert (
            await local.get_integration(local_integration.object_id, tenant_id=None)
            == local_integration
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_store_pagination(kind: str) -> None:
    async with _harness(kind) as harness:
        object_ids = sorted(new_id("obj") for _ in range(6))
        providers = (
            "google_workspace",
            "microsoft_365",
            "google_workspace",
            "microsoft_365",
            "google_workspace",
            "microsoft_365",
        )
        statuses = (
            "within_scope",
            "over_scoped",
            "within_scope",
            "over_scoped",
            "within_scope",
            "over_scoped",
        )
        for object_id, provider, status in zip(
            object_ids,
            providers,
            statuses,
            strict=True,
        ):
            await harness.store.put(_normalized(object_id=object_id, provider=provider))
            await harness.store.put_integration(
                _integration(object_id=object_id, over_scoped=status)
            )

        first, cursor = await harness.store.query(
            tenant_id=TENANT,
            provider="microsoft_365",
            limit=2,
        )
        assert [row.object_id for row in first] == [object_ids[1], object_ids[3]]
        assert cursor == object_ids[3]
        second, cursor = await harness.store.query(
            tenant_id=TENANT,
            provider="microsoft_365",
            limit=2,
            cursor=cursor,
        )
        assert [row.object_id for row in second] == [object_ids[5]]
        assert cursor is None

        integrations, cursor = await harness.store.query_integrations(
            tenant_id=TENANT,
            over_scoped="over_scoped",
            limit=2,
        )
        assert [row.object_id for row in integrations] == [object_ids[1], object_ids[3]]
        assert cursor == object_ids[3]
        integrations, cursor = await harness.store.query_integrations(
            tenant_id=TENANT,
            over_scoped="over_scoped",
            limit=2,
            cursor=cursor,
        )
        assert [row.object_id for row in integrations] == [object_ids[5]]
        assert cursor is None
