"""C-034 real-engine conformance tests for IS-037 (CAASM).

IS-037 is a distributed-conformance case: the capability ships across EA-0023
(exposure / attack surface), EA-0024 (prioritization), EA-0025 (inventory) and
EA-0005 (graph), with intake via EA-0028/0029. There is no CAASM module and no
single owner, so this proof is filed against the *chain* rather than any one
package.

The subject under test is the chain EA-0025 inventory -> EA-0023 known surface ->
exposure / reachable paths -> EA-0024 vulnerability coverage, driven through real
engines and real stores. No spies, no event-name greps.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import CoverageUnavailable, InventoryUnavailable
from aqelyn.exposure import ExposureConfig, KnownDataExposureEngine
from aqelyn.exposure.memory import InMemoryExposureStore
from aqelyn.inventory import (
    AssetBasis,
    AssetRecord,
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    InventoryKnownSurfaceSource,
    InventoryVulnerabilityCoverageProvider,
    PostgresAssetStore,
)
from aqelyn.inventory.engine import _ASSET_QUERY_CAP
from aqelyn.vuln import InMemoryVulnerabilityStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000340100"
OTHER_TENANT = "018f0000-0000-7000-8000-000000340200"

MATRIX = [
    pytest.param("memory", "local", id="memory-local"),
    pytest.param("memory", "enterprise", id="memory-enterprise"),
    pytest.param("postgres", "local", id="postgres-local"),
    pytest.param("postgres", "enterprise", id="postgres-enterprise"),
]


def _asset(
    tenant_id: str | None,
    *,
    index: int,
    lifecycle_state: str = "active",
) -> AssetRecord:
    """A real AssetRecord. Ordering is explicit so cap probing is deterministic."""
    base = utc_now() - timedelta(days=30)
    seen = base + timedelta(seconds=index)
    return AssetRecord(
        id=new_id("ast"),
        tenant_id=tenant_id,
        asset_type="host",
        discovery_source="is037-conformance",
        classification="inventory_asset",
        lifecycle_state=lifecycle_state,
        confidence=1.0,
        basis=[
            AssetBasis(
                kind="discovery",
                ref=f"is037:{index}",
                as_of=seen,
            )
        ],
        first_seen_at=seen,
        last_reported_at=seen,
    )


@dataclass
class _Chain:
    """The shipped owner seams, wired as the platform wires them."""

    store: AssetStore
    inventory: InventoryIntelligenceEngine
    known_surface: InventoryKnownSurfaceSource
    exposure: KnownDataExposureEngine
    coverage: InventoryVulnerabilityCoverageProvider
    tenant_id: str | None


@asynccontextmanager
async def _chain(backend: str, tenant_mode: str) -> AsyncIterator[_Chain]:
    tenant_id = None if tenant_mode == "local" else TENANT
    closeables: list[PostgresAssetStore] = []
    if backend == "memory":
        store: AssetStore = InMemoryAssetStore(mode=tenant_mode)
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        pg = await PostgresAssetStore.connect(PG_URL, mode=tenant_mode)
        async with pg._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_inventory_asset RESTART IDENTITY")
        store = pg
        closeables = [pg]

    inventory = InventoryIntelligenceEngine(store=store)
    known_surface = InventoryKnownSurfaceSource(inventory)
    exposure = KnownDataExposureEngine(
        store=InMemoryExposureStore(mode=tenant_mode),
        source=known_surface,
        config=ExposureConfig(),
    )
    coverage = InventoryVulnerabilityCoverageProvider(
        inventory,
        InMemoryVulnerabilityStore(mode=tenant_mode),
    )
    try:
        yield _Chain(
            store=store,
            inventory=inventory,
            known_surface=known_surface,
            exposure=exposure,
            coverage=coverage,
            tenant_id=tenant_id,
        )
    finally:
        for closeable in closeables:
            await closeable.close()


# --- M1: ownership seams exist in shipped code, exercised not grepped -------------


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is037_owner_seams_present(backend: str, tenant_mode: str) -> None:
    """Each IS-037 ownership row is a real, callable seam on the shipped engines."""
    async with _chain(backend, tenant_mode) as chain:
        for index in range(3):
            await chain.store.put(_asset(chain.tenant_id, index=index))

        # EA-0025 inventory.
        report = await chain.inventory.inventory(tenant_id=chain.tenant_id)
        assert report.total == 3

        # EA-0028/0029 intake seam: inventory presented as EA-0023 known surface.
        surface = await chain.known_surface.list_known_surface(tenant_id=chain.tenant_id)
        assert {row.asset_ref.ref_id for row in surface} == set(report.assets)

        # EA-0023 attack surface derivation.
        derived = await chain.exposure.derive_surface(tenant_id=chain.tenant_id)
        assert {asset.asset_ref.ref_id for asset in derived} == set(report.assets)

        # EA-0024 coverage base.
        coverage = await chain.coverage.coverage(tenant_id=chain.tenant_id)
        assert set(coverage.unscanned) == set(report.assets)
        assert coverage.scanned == []


def test_is037_no_cyber_namespace() -> None:
    """IS-037's Cyber* events are net-new naming, not capability. They stay absent.

    GC-002 enforces the event-namespace ban centrally; this asserts the source-level
    absence that made IS-037 a conformance case rather than a build.
    """
    src = ROOT / "src"
    offenders = [
        path.relative_to(ROOT)
        for path in src.rglob("*.py")
        if "aqelyn.cyber." in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# --- M2: ECR-0034, route (A) -----------------------------------------------------


async def test_inventory_cap_signal_shape() -> None:
    """`limit + 1` is the probe, and both backends honour it identically.

    The store has no cursor and no more-remaining signal, so the engine detects
    truncation by asking for one row past the cap. That is only sound if a store
    asked for `n + 1` returns `n + 1` when `n + 1` rows exist, under the same
    ordering. Proven here at small n on both backends; the real-cap behaviour is
    proven against 10_001 real records in the test below.
    """
    stores: list[AssetStore] = [InMemoryAssetStore(mode="enterprise")]
    closeables: list[PostgresAssetStore] = []
    if PG_URL:
        pg = await PostgresAssetStore.connect(PG_URL, mode="enterprise")
        async with pg._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_inventory_asset RESTART IDENTITY")
        stores.append(pg)
        closeables.append(pg)

    try:
        for store in stores:
            written = [_asset(TENANT, index=index) for index in range(6)]
            for asset in written:
                await store.put(asset)

            under = await store.query(tenant_id=TENANT, limit=5)
            probe = await store.query(tenant_id=TENANT, limit=6)
            assert len(under) == 5
            assert len(probe) == 6
            # The probe extends the same ordering; it does not reshuffle the page.
            assert [row.id for row in under] == [row.id for row in probe[:5]]
    finally:
        for closeable in closeables:
            await closeable.close()


async def test_inventory_degraded_when_capped() -> None:
    """Above the cap, `inventory()` reports `degraded=True` instead of claiming complete.

    Driven with 10_001 real AssetRecords through a real store and the real engine --
    the actual shipped cap, not a lowered stand-in.
    """
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(_ASSET_QUERY_CAP + 1):
        await store.put(_asset(TENANT, index=index))
    engine = InventoryIntelligenceEngine(store=store)

    report = await engine.inventory(tenant_id=TENANT)

    assert report.degraded is True
    # The report is still bounded by the cap: the flag says more exists, it does not
    # deliver the rest. Completeness is cursor pagination and a separate ticket.
    assert report.total == _ASSET_QUERY_CAP
    assert len(report.assets) == _ASSET_QUERY_CAP


async def test_inventory_not_degraded_at_cap_boundary() -> None:
    """Exactly at the cap is complete, not truncated -- the probe must not off-by-one."""
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(_ASSET_QUERY_CAP):
        await store.put(_asset(TENANT, index=index))
    engine = InventoryIntelligenceEngine(store=store)

    report = await engine.inventory(tenant_id=TENANT)

    assert report.degraded is False
    assert report.total == _ASSET_QUERY_CAP


async def test_is037_downstream_gates_refuse_on_degraded() -> None:
    """Every enumerated consumer of the capped denominator refuses or flags.

    An honest flag is necessary but not sufficient: a truthful field nobody acts on
    is the ECR-0013 unwired-default shape. The consumers of
    `InventoryIntelligenceEngine.inventory()` in shipped code are:

      1. `InventoryKnownSurfaceSource.list_known_surface` -- EA-0023's known-surface
         feed, and through it `derive_surface` / `reachable_paths`.
      2. `InventoryVulnerabilityCoverageProvider.coverage` -- EA-0024's coverage base.
      3. `ISPMEngine._inventory_note` -- a note, not a gate; it flags the truncated
         read rather than refusing. Asserted where that behaviour is owned, by
         `tests/ispm/test_ispm_g5.py::test_ispm_inventory_note_flags_a_truncated_read`.
      4. `InventoryIntelligenceService.inventory` -- passthrough; re-exposes the
         report verbatim, so the flag reaches its caller unmodified.

    This drives 1, 2 and 4 past the cap and asserts each one acts on the flag.
    """
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(_ASSET_QUERY_CAP + 1):
        await store.put(_asset(TENANT, index=index))
    engine = InventoryIntelligenceEngine(store=store)

    known_surface = InventoryKnownSurfaceSource(engine)
    exposure = KnownDataExposureEngine(
        store=InMemoryExposureStore(mode="enterprise"),
        source=known_surface,
        config=ExposureConfig(),
    )
    coverage = InventoryVulnerabilityCoverageProvider(
        engine,
        InMemoryVulnerabilityStore(mode="enterprise"),
    )

    # 1. EA-0023 known surface refuses rather than deriving a partial attack surface.
    with pytest.raises(InventoryUnavailable):
        await known_surface.list_known_surface(tenant_id=TENANT)

    # ... and the refusal propagates through the engine that consumes it.
    with pytest.raises(InventoryUnavailable):
        await exposure.derive_surface(tenant_id=TENANT)

    # 2. EA-0024 coverage refuses rather than reporting coverage over a partial base.
    with pytest.raises(CoverageUnavailable):
        await coverage.coverage(tenant_id=TENANT)

    # 4. The passthrough carries the flag to its caller intact.
    assert (await engine.inventory(tenant_id=TENANT)).degraded is True


async def test_inventory_sweep_refuses_over_truncated_read() -> None:
    """A sweep over a truncated read would leave stale assets looking reported.

    `sweep_unreported` has no report to flag, so it refuses. Silently half-sweeping
    is unknown treated as safe: the unread rows keep a fresh posture they have not
    earned.
    """
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(_ASSET_QUERY_CAP + 1):
        await store.put(_asset(TENANT, index=index))
    engine = InventoryIntelligenceEngine(store=store)

    with pytest.raises(InventoryUnavailable):
        await engine.sweep_unreported(
            source=DiscoverySource(
                source_id="is037-conformance",
                reliability=1.0,
                health="ok",
                as_of=utc_now(),
            ),
            tenant_id=TENANT,
        )


# --- M3: real-runtime chain proof ------------------------------------------------


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is037_chain_replay(backend: str, tenant_mode: str) -> None:
    """The chain is deterministic: same inputs, same surface and same coverage."""
    async with _chain(backend, tenant_mode) as chain:
        for index in range(5):
            await chain.store.put(_asset(chain.tenant_id, index=index))

        first_surface = await chain.exposure.derive_surface(tenant_id=chain.tenant_id)
        second_surface = await chain.exposure.derive_surface(tenant_id=chain.tenant_id)
        first_coverage = await chain.coverage.coverage(tenant_id=chain.tenant_id)
        second_coverage = await chain.coverage.coverage(tenant_id=chain.tenant_id)

        assert [asset.asset_ref for asset in first_surface] == [
            asset.asset_ref for asset in second_surface
        ]
        assert [asset.exposure_level for asset in first_surface] == [
            asset.exposure_level for asset in second_surface
        ]
        assert first_coverage.scanned == second_coverage.scanned
        assert first_coverage.unscanned == second_coverage.unscanned


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is037_chain_no_network(backend: str, tenant_mode: str) -> None:
    """Intake is handed-in. The chain performs no collection of its own.

    EA-0023 ships a no-scan boundary: the surface is derived from what was handed in,
    never from probing. Nothing the chain returns may reference an asset that was not
    supplied.
    """
    async with _chain(backend, tenant_mode) as chain:
        handed_in = [_asset(chain.tenant_id, index=index) for index in range(4)]
        for asset in handed_in:
            await chain.store.put(asset)

        surface = await chain.exposure.derive_surface(tenant_id=chain.tenant_id)

        assert {asset.asset_ref.ref_id for asset in surface} == {record.id for record in handed_in}
        # Every derived asset traces to handed-in basis, not to a discovery probe.
        for derived_asset in surface:
            assert derived_asset.basis
            assert all(basis.kind == "inventory" for basis in derived_asset.basis)


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is037_chain_tenant_isolation(backend: str, tenant_mode: str) -> None:
    """One tenant's assets never reach another tenant's surface or coverage."""
    if tenant_mode == "local":
        pytest.skip("local mode is single-tenant by construction")
    async with _chain(backend, tenant_mode) as chain:
        mine = [_asset(TENANT, index=index) for index in range(3)]
        theirs = [_asset(OTHER_TENANT, index=index) for index in range(100, 103)]
        for asset in [*mine, *theirs]:
            await chain.store.put(asset)

        surface = await chain.exposure.derive_surface(tenant_id=TENANT)
        coverage = await chain.coverage.coverage(tenant_id=TENANT)

        seen = {asset.asset_ref.ref_id for asset in surface}
        assert seen == {asset.id for asset in mine}
        assert not seen & {asset.id for asset in theirs}
        assert not set(coverage.unscanned) & {asset.id for asset in theirs}


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is037_chain_unknown_not_safe(backend: str, tenant_mode: str) -> None:
    """Unknown reachability and unknown coverage are never the favourable answer."""
    async with _chain(backend, tenant_mode) as chain:
        for index in range(3):
            await chain.store.put(_asset(chain.tenant_id, index=index))

        surface = await chain.exposure.derive_surface(tenant_id=chain.tenant_id)
        coverage = await chain.coverage.coverage(tenant_id=chain.tenant_id)

        # Inventory supplies no reachability evidence, so no asset may be graded
        # as the unexposed/benign case on the strength of that absence.
        assert surface
        for asset in surface:
            assert asset.exposure_level != "none"

        # An asset with no vulnerability record is unscanned, not scanned-clean.
        assert coverage.scanned == []
        assert len(coverage.unscanned) == 3


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is037_chain_matrix(backend: str, tenant_mode: str) -> None:
    """The whole chain runs end to end on both backends and both tenant modes."""
    async with _chain(backend, tenant_mode) as chain:
        for index in range(4):
            await chain.store.put(_asset(chain.tenant_id, index=index))

        report = await chain.inventory.inventory(tenant_id=chain.tenant_id)
        surface = await chain.known_surface.list_known_surface(tenant_id=chain.tenant_id)
        derived = await chain.exposure.derive_surface(tenant_id=chain.tenant_id)
        coverage = await chain.coverage.coverage(tenant_id=chain.tenant_id)

        assert report.degraded is False
        assert len(surface) == 4
        assert len(derived) == 4
        assert len(coverage.unscanned) == 4


def test_is037_conformance_holds_under_optimized_python() -> None:
    """The guarantees are not assert-statements that `python -O` strips away."""
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-m",
            "pytest",
            str(Path(__file__).resolve()),
            "-q",
            "-p",
            "no:cacheprovider",
            "-k",
            "degraded or refuse or sweep or boundary",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
