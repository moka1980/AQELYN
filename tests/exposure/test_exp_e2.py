"""E2 acceptance tests for ExposureStore and known-data derivation."""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NoReturn, Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict
from aqelyn.exposure import (
    AssetRef,
    ExposureBasis,
    ExposureRecord,
    ExposureStore,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    KnownSurfaceRecord,
    PostgresExposureStore,
    StaticKnownSurfaceSource,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 16, 21, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000230101"
OTHER_TENANT = "018f0000-0000-7000-8000-000000230102"


class _Closable(Protocol):
    async def close(self) -> None: ...


async def _store(kind: str) -> AsyncIterator[ExposureStore]:
    if kind == "inmemory":
        yield InMemoryExposureStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresExposureStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_exposure_record")
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


def _asset_ref(ref_id: str = "asset:web-1") -> AssetRef:
    return AssetRef(kind="asset", ref_id=ref_id, evidence_id=new_id("evd"))


def _basis(ref: str = "inventory:web-1") -> ExposureBasis:
    return ExposureBasis(kind="inventory", ref=ref, as_of=NOW, evidence_id=new_id("evd"))


def _record(
    *,
    exposure_id: str | None = None,
    tenant_id: str | None = TENANT,
    reachability: str = "external",
    flagged: bool = False,
    ref_id: str = "asset:web-1",
) -> ExposureRecord:
    data: dict[str, object] = {
        "tenant_id": tenant_id,
        "asset_ref": _asset_ref(ref_id),
        "exposure_type": "reachable_service",
        "reachability": reachability,
        "basis": [_basis(f"inventory:{ref_id}")],
        "confidence": 0.76,
        "rationale": "Reachability is derived from known inventory, not probing.",
        "flagged": flagged,
        "discovered_at": NOW,
    }
    if exposure_id is not None:
        data["id"] = exposure_id
    return ExposureRecord.model_validate(data)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_exp_store_contract(kind: str) -> None:
    async for store in _store(kind):
        first = await store.put(_record())
        second = await store.put(
            _record(
                tenant_id=OTHER_TENANT,
                reachability="unknown",
                flagged=True,
                ref_id="asset:unknown",
            )
        )

        assert await store.get(first.id, tenant_id=TENANT) == first
        assert await store.get(first.id, tenant_id=OTHER_TENANT) is None

        external = await store.query(tenant_id=TENANT, reachability="external")
        flagged = await store.query(tenant_id=OTHER_TENANT, flagged=True)

        assert [row.id for row in external] == [first.id]
        assert [row.id for row in flagged] == [second.id]

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(first.model_copy(update={"rationale": "mutated"}, deep=True))

        stored = await store.get(first.id, tenant_id=TENANT)
        assert stored is not None
        assert stored.rationale == first.rationale


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_exp_tenant_isolation(kind: str) -> None:
    async for store in _store(kind):
        row = await store.put(_record(tenant_id=TENANT))
        await store.put(_record(tenant_id=OTHER_TENANT, ref_id="asset:other"))

        assert await store.get(row.id, tenant_id=OTHER_TENANT) is None
        assert {item.tenant_id for item in await store.query(tenant_id=TENANT)} == {TENANT}


async def test_exp_unknown_not_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("socket")
        raise AssertionError("socket use is not permitted in exposure E2")

    def blocked_create_connection(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("create_connection")
        raise AssertionError("network connection is not permitted in exposure E2")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    monkeypatch.setattr(socket, "create_connection", blocked_create_connection)

    asset_ref = _asset_ref("asset:unresolved")
    source = StaticKnownSurfaceSource(
        [
            KnownSurfaceRecord(
                asset_ref=asset_ref,
                classification="internet_service",
                reachability=None,
                basis=[_basis("inventory:unresolved")],
                observed_at=NOW,
            )
        ]
    )
    store = InMemoryExposureStore(mode="enterprise")
    engine = KnownDataExposureEngine(store, source)

    surface = await engine.derive_surface(tenant_id=TENANT)
    exposure = await engine.analyze_exposure(asset_ref=asset_ref, tenant_id=TENANT)

    assert surface[0].exposure_level == "unknown"
    assert exposure.reachability == "unknown"
    assert exposure.flagged is True
    assert exposure.reachability != "internal"
    assert attempts == []


async def test_exp_failure_not_faked() -> None:
    asset_ref = _asset_ref("asset:source-down")
    store = InMemoryExposureStore(mode="enterprise")
    engine = KnownDataExposureEngine(
        store,
        StaticKnownSurfaceSource([], unavailable=True),
    )

    exposure = await engine.analyze_exposure(asset_ref=asset_ref, tenant_id=TENANT)
    rows = await store.query(tenant_id=TENANT, reachability="unknown", flagged=True)

    assert exposure.reachability == "unknown"
    assert exposure.flagged is True
    assert "source unavailable" in exposure.rationale.lower()
    assert [row.id for row in rows] == [exposure.id]
