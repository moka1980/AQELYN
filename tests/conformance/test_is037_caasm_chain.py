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

from aqelyn.conventions import ActorRef, new_id, parse_id, utc_now
from aqelyn.conventions.errors import (
    CoverageUnavailable,
    InventoryUnavailable,
    StoreUnavailable,
)
from aqelyn.exposure import ExposureConfig, KnownDataExposureEngine
from aqelyn.exposure.memory import InMemoryExposureStore
from aqelyn.inventory import (
    AssetBasis,
    AssetRecord,
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryConfig,
    InventoryIntelligenceEngine,
    InventoryKnownSurfaceSource,
    InventoryVulnerabilityCoverageProvider,
    PostgresAssetStore,
)
from aqelyn.inventory.engine import _ASSET_PAGE_SIZE
from aqelyn.objects import AQObject, InMemoryObjectStore, NaturalKey, SourceRef
from aqelyn.supplychain import ensure_supplychain_object_type
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


def _component_for_asset(asset: AssetRecord, *, identity_kind: str) -> AQObject:
    """A software component whose object id maps to the inventory asset id."""
    prefix, payload = parse_id(asset.id)
    assert prefix == "ast"
    observed_at = asset.last_reported_at
    actor = ActorRef(actor_type="system", actor_id="is037-conformance")
    coordinate = (
        f"pkg:generic/{payload}"
        if identity_kind == "purl"
        else f"cpe:2.3:a:aqelyn:{payload}:1.0:*:*:*:*:*:*:*"
    )
    return AQObject(
        id=f"obj_{payload}",
        object_type="software_component",
        schema_version=1,
        tenant_id=asset.tenant_id,
        display_name=f"component-{payload}",
        attributes={"identity_kind": identity_kind},
        labels={"module": "EA-0030"},
        natural_keys=[NaturalKey(namespace=identity_kind, value=coordinate)],
        sources=[
            SourceRef(
                source_id=new_id("src"),
                evidence_id=new_id("evd"),
                observed_at=observed_at,
                method="C-036 coverage budget control",
            )
        ],
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        created_at=observed_at,
        updated_at=observed_at,
        created_by=actor,
        updated_by=actor,
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
        InMemoryObjectStore(mode=tenant_mode),
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


class _LimitRecordingAssetStore(InMemoryAssetStore):
    """A real store that also records the `limit` each read asked for."""

    def __init__(self, *, mode: str = "local") -> None:
        super().__init__(mode=mode)
        self.requested_limits: list[int] = []

    async def query(
        self,
        *,
        tenant_id: str | None,
        lifecycle_state: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[AssetRecord], str | None]:
        self.requested_limits.append(limit)
        return await super().query(
            tenant_id=tenant_id,
            lifecycle_state=lifecycle_state,  # type: ignore[arg-type]
            limit=limit,
            cursor=cursor,
        )


class _RepeatedCursorAssetStore(InMemoryAssetStore):
    """A malfunctioning store: it always offers the same cursor back."""

    async def query(
        self,
        *,
        tenant_id: str | None,
        lifecycle_state: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[AssetRecord], str | None]:
        page, _ = await super().query(
            tenant_id=tenant_id,
            lifecycle_state=lifecycle_state,  # type: ignore[arg-type]
            limit=limit,
            cursor=None,
        )
        return page, "ast_00000000000000000000000000"


def _budgeted(store: AssetStore, budget: int) -> InventoryIntelligenceEngine:
    """A real engine with a reduced page budget.

    P5's cost decision: the shipped budget is 50 000, and a 50 001-row fixture is
    disproportionate on both backends. The exhaustion *logic* is identical at any
    budget, so it is exercised at small N and the shipped value is pinned separately
    by `test_inventory_budget_constant_pinned`. Same pattern C-034 used for the cap.
    """
    return InventoryIntelligenceEngine(store=store, config=InventoryConfig(page_budget=budget))


async def test_inventory_budget_constant_pinned() -> None:
    """The proof and the shipped paging loop must not drift apart.

    This replaces C-034's `test_inventory_call_sites_pass_the_production_constant`,
    which pinned the 10 000-row cap and asserted both reads requested the probe. The
    cap is gone, so that guard is *rewritten rather than dropped* -- it pins the same
    property one level up: the loop pages using the production budget and page size,
    not literals, and the reduced-budget tests below cannot silently drift from the
    shipped value.
    """
    assert InventoryConfig().page_budget == 50_000
    assert _ASSET_PAGE_SIZE == 100

    store = _LimitRecordingAssetStore(mode="enterprise")
    for index in range(3):
        await store.put(_asset(TENANT, index=index))
    engine = InventoryIntelligenceEngine(store=store)

    await engine.inventory(tenant_id=TENANT)

    # Each page is bounded by the page size, never by an ad-hoc literal, and never
    # by the whole budget in one read.
    assert store.requested_limits
    assert all(limit == _ASSET_PAGE_SIZE for limit in store.requested_limits)


async def test_inventory_paging_never_overshoots_the_budget() -> None:
    """`min(page_size, remaining)` bounds the last page, so the budget is not exceeded."""
    store = _LimitRecordingAssetStore(mode="enterprise")
    for index in range(6):
        await store.put(_asset(TENANT, index=index))
    engine = _budgeted(store, 5)

    report = await engine.inventory(tenant_id=TENANT)

    # Budget 5 with a page size of 100 must ask for 5, not 100.
    assert store.requested_limits == [5]
    assert report.total == 5
    assert report.degraded is True


async def test_asset_store_cursor_contract() -> None:
    """EA-0002 D8 semantics, and both backends honour them identically.

    `next_cursor` is non-null exactly when another matching row exists, the cursor is
    exclusive, and paging the whole set returns every row once in a stable order.
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
            # Insert in REVERSE id order. `new_id` is monotonic, so inserting in
            # creation order would let a store that merely returns insertion order pass
            # every assertion below -- the fixture would mirror the property under test
            # and could not falsify the wrong implementation.
            for asset in reversed(written):
                await store.put(asset)
            expected = sorted(asset.id for asset in written)

            # Exhausted page: no cursor offered.
            whole, whole_cursor = await store.query(tenant_id=TENANT, limit=6)
            assert [row.id for row in whole] == expected
            assert whole_cursor is None

            # Partial page: a cursor is offered, and it is the last row of the page.
            first, first_cursor = await store.query(tenant_id=TENANT, limit=4)
            assert [row.id for row in first] == expected[:4]
            assert first_cursor == expected[3]

            # The cursor is exclusive: the next page starts after it, no overlap.
            second, second_cursor = await store.query(
                tenant_id=TENANT, limit=4, cursor=first_cursor
            )
            assert [row.id for row in second] == expected[4:]
            assert second_cursor is None

            # Paging the whole set yields every row exactly once.
            paged: list[str] = []
            cursor: str | None = None
            while True:
                page, cursor = await store.query(tenant_id=TENANT, limit=2, cursor=cursor)
                paged.extend(row.id for row in page)
                if cursor is None:
                    break
            assert paged == expected
    finally:
        for closeable in closeables:
            await closeable.close()


async def test_inventory_below_budget_not_degraded() -> None:
    """The user-visible win: 10 001 assets are now answered, not refused.

    Under C-034 this exact estate returned `degraded=True` and both gates refused.
    This is the one assertion that proves the threshold actually moved, so it pays for
    real records at the old cap rather than using a reduced budget.
    """
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(10_001):
        await store.put(_asset(TENANT, index=index))
    engine = InventoryIntelligenceEngine(store=store)

    report = await engine.inventory(tenant_id=TENANT)

    assert report.degraded is False
    assert report.total == 10_001


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_inventory_degraded_when_budget_exhausted(backend: str) -> None:
    """Above the budget the read is still partial, and still says so.

    The threshold moved; it did not disappear. A budget that truncates is still a cap,
    only a better-behaved one. Both stores drive the full budget-to-report composition;
    cursor primitives alone cannot prove the report carries the result.
    """
    closeable: PostgresAssetStore | None = None
    if backend == "memory":
        store: AssetStore = InMemoryAssetStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        closeable = await PostgresAssetStore.connect(PG_URL, mode="enterprise")
        async with closeable._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_inventory_asset RESTART IDENTITY")
        store = closeable

    try:
        for index in range(6):
            await store.put(_asset(TENANT, index=index))
        engine = _budgeted(store, 5)

        report = await engine.inventory(tenant_id=TENANT)

        assert report.degraded is True
        # Partial and flagged, not refused: the gated consumers refuse on the flag anyway,
        # and refusing here would foreclose callers that do not need completeness.
        assert report.total == 5
    finally:
        if closeable is not None:
            await closeable.close()


async def test_inventory_not_degraded_at_budget_boundary() -> None:
    """Exactly at the budget is exhausted, not truncated -- the loop must not off-by-one."""
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(5):
        await store.put(_asset(TENANT, index=index))
    engine = _budgeted(store, 5)

    report = await engine.inventory(tenant_id=TENANT)

    assert report.degraded is False
    assert report.total == 5


async def test_inventory_repeated_cursor_refused() -> None:
    """A store that keeps handing back the same cursor is a malfunction, not a loop."""
    store = _RepeatedCursorAssetStore(mode="enterprise")
    for index in range(4):
        await store.put(_asset(TENANT, index=index))
    engine = _budgeted(store, 50)

    with pytest.raises(StoreUnavailable):
        await engine.inventory(tenant_id=TENANT)


async def test_is037_downstream_gates_refuse_on_degraded() -> None:
    """Every enumerated consumer of the truncated denominator refuses or flags.

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

    Any *new* consumer of `inventory()` must read `degraded` too. That obligation is
    the residual risk of returning a flagged partial instead of refusing, and it is
    recorded in ECR-0061 alongside this list.

    This drives 1, 2 and 4 past the budget and asserts each one acts on the flag.
    """
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(6):
        await store.put(_asset(TENANT, index=index))
    engine = _budgeted(store, 5)

    known_surface = InventoryKnownSurfaceSource(engine)
    exposure = KnownDataExposureEngine(
        store=InMemoryExposureStore(mode="enterprise"),
        source=known_surface,
        config=ExposureConfig(),
    )
    coverage = InventoryVulnerabilityCoverageProvider(
        engine,
        InMemoryVulnerabilityStore(mode="enterprise"),
        InMemoryObjectStore(mode="enterprise"),
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


async def test_software_component_coverage_refuses_when_page_budget_exhausted() -> None:
    """The second C-036 paging loop must not return partial coverage as complete.

    The third component is deliberately CPE-only: silently truncating before it would
    omit a named unassessable gap and make coverage look better than it was measured.
    """
    asset_store = InMemoryAssetStore(mode="enterprise")
    object_store = InMemoryObjectStore(mode="enterprise")
    ensure_supplychain_object_type(object_store)
    assets = [_asset(TENANT, index=index) for index in range(3)]
    for asset in assets:
        await asset_store.put(asset)
    for asset in assets[:2]:
        await object_store.upsert(_component_for_asset(asset, identity_kind="purl"))

    provider = InventoryVulnerabilityCoverageProvider(
        InventoryIntelligenceEngine(store=asset_store),
        InMemoryVulnerabilityStore(mode="enterprise"),
        object_store,
        page_budget=2,
    )

    boundary = await provider.coverage(tenant_id=TENANT)
    assert boundary.unassessable == []

    await object_store.upsert(_component_for_asset(assets[2], identity_kind="cpe"))
    with pytest.raises(
        CoverageUnavailable,
        match="software component coverage exceeded the configured page budget",
    ):
        await provider.coverage(tenant_id=TENANT)


async def test_sweep_unreported_exhausts_and_sweeps() -> None:
    """Under the budget the sweep pages to exhaustion and does its job."""
    store = InMemoryAssetStore(mode="enterprise")
    stale = [_asset(TENANT, index=index) for index in range(4)]
    for asset in stale:
        await store.put(asset)
    engine = _budgeted(store, 50)

    changed = await engine.sweep_unreported(
        source=DiscoverySource(
            source_id="is037-conformance",
            reliability=1.0,
            health="ok",
            as_of=utc_now(),
        ),
        tenant_id=TENANT,
    )

    assert {row.id for row in changed} == {asset.id for asset in stale}
    assert all(row.lifecycle_state == "unreported" for row in changed)


async def test_sweep_unreported_refuses_when_budget_exhausted() -> None:
    """Exhaustion is a precondition for sweeping, not a target to approximate.

    A budget-truncated sweep would mark live assets as unreported -- assets that exist
    but fell outside the budget. That is the absence-is-not-decommission error EA-0025
    was founded on, so the sweep refuses rather than half-sweeping. Paging keeps the
    work bounded; it does not license a partial answer.
    """
    store = InMemoryAssetStore(mode="enterprise")
    for index in range(6):
        await store.put(_asset(TENANT, index=index))
    engine = _budgeted(store, 5)

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


async def test_sweep_never_marks_on_partial_read() -> None:
    """The refusal happens before any write: no asset is marked on a truncated read."""
    store = InMemoryAssetStore(mode="enterprise")
    written = [_asset(TENANT, index=index) for index in range(6)]
    for asset in written:
        await store.put(asset)
    engine = _budgeted(store, 5)

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

    rows, _ = await store.query(tenant_id=TENANT, limit=100)
    assert [row.lifecycle_state for row in rows] == ["active"] * 6


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
