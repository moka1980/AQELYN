"""S-003 U3 acceptance tests for observed-host exposure."""

from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tools.first_run import RunReport, density_report
from tools.s003_estate import (
    SURFACE_NOT_DERIVED_REASONS,
    NginxVHost,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
    UnitRecord,
    canonical_asset_key,
)
from tools.s003_surface import (
    AMBIGUOUS_BIND,
    ASSET_NOT_REGISTERED,
    NO_SURFACE_EVIDENCE,
    OBSERVED_JOIN_UNAVAILABLE,
    SurfaceApplication,
    SurfaceSummary,
    build_surface_application,
    classify_bind,
    derive_surface_from_documents,
    surface_factor_readings,
)

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import InventoryUnavailable
from aqelyn.exposure import ExposureBasis, InMemoryExposureStore
from aqelyn.inventory import (
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    InventoryKnownSurfaceSource,
    InventoryReport,
    ObservedHostSurface,
    PostgresAssetStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000003003"
NOW = datetime(2026, 7, 27, tzinfo=UTC)
MATRIX = [
    pytest.param("memory", "local", id="memory-local"),
    pytest.param("memory", "enterprise", id="memory-enterprise"),
    pytest.param("postgres", "local", id="postgres-local"),
    pytest.param("postgres", "enterprise", id="postgres-enterprise"),
]


class _Harness:
    def __init__(
        self,
        store: AssetStore,
        inventory: InventoryIntelligenceEngine,
        *,
        tenant_id: str | None,
    ) -> None:
        self.store = store
        self.inventory = inventory
        self.tenant_id = tenant_id


@asynccontextmanager
async def _harness(backend: str, tenant_mode: str) -> AsyncIterator[_Harness]:
    tenant_id = None if tenant_mode == "local" else TENANT
    if backend == "memory":
        store: AssetStore = InMemoryAssetStore(mode=tenant_mode)
        yield _Harness(
            store,
            InventoryIntelligenceEngine(store),
            tenant_id=tenant_id,
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresAssetStore.connect(PG_URL, mode=tenant_mode)
    async with postgres._pool.acquire() as connection:
        await connection.execute("TRUNCATE aq_inventory_asset RESTART IDENTITY")
    try:
        yield _Harness(
            postgres,
            InventoryIntelligenceEngine(postgres),
            tenant_id=tenant_id,
        )
    finally:
        await postgres.close()


def _unit(index: int, *, pid: int | None) -> UnitRecord:
    native_id = f"unit-{index}." + "".join(("ser", "vice"))
    return UnitRecord(
        asset_key=canonical_asset_key("systemd_unit", native_id),
        native_id=native_id,
        display_name=f"Unit {index}",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        main_pid=pid,
    )


def _inventory(*units: UnitRecord) -> UnitInventoryDocument:
    return UnitInventoryDocument(collected_at=NOW, units=list(units))


def _listener(address: str, index: int, *, pid: int | None) -> str:
    selected_port = 20_000 + index
    endpoint = f"[{address}]:{selected_port}" if ":" in address else f"{address}:{selected_port}"
    process = "" if pid is None else f' users:(("process",pid={pid},fd=1))'
    return f"tcp LISTEN 0 128 {endpoint} *:*{process}"


def _surface(*listeners: str) -> ServiceSurfaceDocument:
    return ServiceSurfaceDocument(
        collected_at=NOW,
        listeners_raw="\n".join(listeners) + ("\n" if listeners else ""),
        firewall_raw=None,
        nginx_config=None,
        unavailable_details=dict(SURFACE_NOT_DERIVED_REASONS),
    )


def _source() -> DiscoverySource:
    return DiscoverySource(
        source_id=new_id("src"),
        reliability=1.0,
        health="ok",
        as_of=NOW,
    )


def _ids(inventory: UnitInventoryDocument) -> dict[str, str]:
    return {unit.asset_key: new_id("ast") for unit in inventory.units}


def _unregistered_vhost() -> NginxVHost:
    native_id = "".join(("virtual", "-", "asset"))
    return NginxVHost(
        asset_key=canonical_asset_key("nginx_vhost", native_id),
        native_id=native_id,
        display_name="Virtual asset",
    )


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_s003_services_registered_as_assets(backend: str, tenant_mode: str) -> None:
    inventory_document = _inventory(_unit(1, pid=101), _unit(2, pid=102))
    selected_ids = _ids(inventory_document)

    async with _harness(backend, tenant_mode) as harness:
        application, derived = await derive_surface_from_documents(
            _surface(),
            inventory_document,
            inventory_owner=harness.inventory,
            exposure_store=InMemoryExposureStore(mode=tenant_mode),
            source=_source(),
            tenant_id=harness.tenant_id,
            asset_ids_by_key=selected_ids,
        )
        report = await harness.inventory.inventory(tenant_id=harness.tenant_id)

        assert set(report.assets) == set(selected_ids.values())
        assert report.total == len(selected_ids)
        assert {row.asset_ref.ref_id for row in derived} == set(selected_ids.values())
        assert application.aggregate().no_surface_evidence == len(selected_ids)
        for asset_id in selected_ids.values():
            stored = await harness.store.get(asset_id, tenant_id=harness.tenant_id)
            assert stored is not None
            assert stored.asset_type == "systemd_unit"


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_s003_reachability_measured_from_bind(
    backend: str,
    tenant_mode: str,
) -> None:
    units = [
        _unit(1, pid=101),
        _unit(2, pid=102),
        _unit(3, pid=103),
        _unit(4, pid=104),
    ]
    inventory_document = _inventory(*units)
    selected_ids = _ids(inventory_document)
    external = str(ipaddress.ip_address(0))
    internal = str(ipaddress.ip_address(0x7F000001))
    specific = str(ipaddress.ip_address(0x0A000001))
    surface = _surface(
        _listener(external, 1, pid=101),
        _listener(internal, 2, pid=102),
        _listener(specific, 3, pid=103),
        _listener(external, 4, pid=None),
    )

    async with _harness(backend, tenant_mode) as harness:
        application, derived = await derive_surface_from_documents(
            surface,
            inventory_document,
            inventory_owner=harness.inventory,
            exposure_store=InMemoryExposureStore(mode=tenant_mode),
            source=_source(),
            tenant_id=harness.tenant_id,
            asset_ids_by_key=selected_ids,
            unregistered_assets=[_unregistered_vhost()],
        )

    summary = application.aggregate()
    assert summary == SurfaceSummary(
        derived_external=1,
        derived_internal=1,
        derived_unknown=1,
        no_surface_evidence=1,
        observed_unattributable=1,
        not_registered=1,
    )
    levels = {row.asset_ref.ref_id: row.exposure_level for row in derived}
    assert levels[selected_ids[units[0].asset_key]] == "high"
    assert levels[selected_ids[units[1].asset_key]] == "low"
    assert levels[selected_ids[units[2].asset_key]] == "unknown"
    assert levels[selected_ids[units[3].asset_key]] == "unknown"
    basis = {row.asset_ref.ref_id: row.basis for row in derived}
    for unit in units[:3]:
        selected_basis = basis[selected_ids[unit.asset_key]]
        assert {item.kind for item in selected_basis} == {"host_state"}
        assert all(item.ref.startswith("s003:host-state:sha256:") for item in selected_basis)
    assert {item.kind for item in basis[selected_ids[units[3].asset_key]]} == {"inventory"}


def _three_state_application() -> SurfaceApplication:
    unit = _unit(1, pid=101)
    inventory_document = _inventory(unit)
    return build_surface_application(
        _surface(_listener(str(ipaddress.ip_address(0)), 1, pid=None)),
        inventory_document,
        registered_asset_ids=_ids(inventory_document),
        unregistered_assets=[_unregistered_vhost()],
    )


def test_s003_unregistered_asset_distinguishable() -> None:
    states = {outcome.state: outcome.reason for outcome in _three_state_application().outcomes}

    assert states["no_surface_evidence"] == NO_SURFACE_EVIDENCE
    assert states["observed_unattributable"] == OBSERVED_JOIN_UNAVAILABLE
    assert states["not_registered"] == ASSET_NOT_REGISTERED
    assert len(set(states.values())) == 3


def test_s003_bind_classification_is_nonbinary() -> None:
    assert classify_bind(str(ipaddress.ip_address(0))) == "external"
    assert classify_bind(str(ipaddress.IPv6Address(0))) == "external"
    assert classify_bind(str(ipaddress.ip_address(0x7F000001))) == "internal"
    assert classify_bind(str(ipaddress.IPv6Address(1))) == "internal"
    assert classify_bind(str(ipaddress.ip_address(0x0A000001))) is None
    assert classify_bind(str(ipaddress.IPv6Address(0xFE80 << 112))) is None


def test_s003_observed_unattributable_named() -> None:
    [outcome] = [
        value
        for value in _three_state_application().outcomes
        if value.state == "observed_unattributable"
    ]

    assert outcome.asset_key is None
    assert outcome.asset_id is None
    assert outcome.unknown_cause == "input_missing"
    assert outcome.reason == OBSERVED_JOIN_UNAVAILABLE


def test_s003_tier4_service_is_state_three() -> None:
    application = _three_state_application()
    [outcome] = [value for value in application.outcomes if value.state == "not_registered"]

    assert outcome.asset_key == _unregistered_vhost().asset_key
    assert outcome.asset_id is None
    assert outcome.reason == ASSET_NOT_REGISTERED


def test_exposure_basis_kind_accepts_observed_state() -> None:
    basis = ExposureBasis(
        kind="host_state",
        ref="s003:host-state:sha256:" + "0" * 64,
        as_of=NOW,
    )

    assert basis.kind == "host_state"


async def test_exposure_basis_bind_derived_not_inventory() -> None:
    asset_id = new_id("ast")

    class _Inventory:
        async def inventory(self, *, tenant_id: str | None) -> InventoryReport:
            return InventoryReport(
                assets=[asset_id],
                total=1,
                as_of=NOW,
                source_freshness={"s003": NOW},
            )

    [row] = await InventoryKnownSurfaceSource(
        _Inventory(),
        observed_surface=[
            ObservedHostSurface(
                asset_id=asset_id,
                reachability="external",
                basis_refs=["s003:host-state:sha256:" + "1" * 64],
                observed_at=NOW,
                rationale="Observed external bind.",
            )
        ],
    ).list_known_surface(tenant_id=None)

    assert {basis.kind for basis in row.basis} == {"host_state"}
    assert all(basis.kind != "inventory" for basis in row.basis)


async def test_exposure_basis_ref_records_specific_evidence() -> None:
    asset_id = new_id("ast")
    evidence_ref = "s003:host-state:sha256:" + "2" * 64

    class _Inventory:
        async def inventory(self, *, tenant_id: str | None) -> InventoryReport:
            return InventoryReport(
                assets=[asset_id],
                total=1,
                as_of=NOW,
                source_freshness={"s003": NOW},
            )

    [row] = await InventoryKnownSurfaceSource(
        _Inventory(),
        observed_surface=[
            ObservedHostSurface(
                asset_id=asset_id,
                reachability=None,
                basis_refs=[evidence_ref],
                observed_at=NOW,
                rationale=AMBIGUOUS_BIND,
            )
        ],
    ).list_known_surface(tenant_id=None)

    assert [basis.ref for basis in row.basis] == [evidence_ref]


async def test_s003_degraded_inventory_still_refuses() -> None:
    asset_id = new_id("ast")

    class _DegradedInventory:
        async def inventory(self, *, tenant_id: str | None) -> InventoryReport:
            return InventoryReport(
                assets=[asset_id],
                total=1,
                as_of=NOW,
                source_freshness={"s003": NOW},
                degraded=True,
            )

    source = InventoryKnownSurfaceSource(
        _DegradedInventory(),
        observed_surface=[
            ObservedHostSurface(
                asset_id=asset_id,
                reachability="external",
                basis_refs=["s003:host-state:sha256:" + "3" * 64],
                observed_at=NOW,
                rationale="Observed external bind.",
            )
        ],
    )

    with pytest.raises(InventoryUnavailable, match="inventory source is degraded"):
        await source.list_known_surface(tenant_id=None)


async def test_s003_observation_outside_inventory_refuses() -> None:
    asset_id = new_id("ast")

    class _EmptyInventory:
        async def inventory(self, *, tenant_id: str | None) -> InventoryReport:
            return InventoryReport(
                assets=[],
                total=0,
                as_of=NOW,
                source_freshness={},
            )

    source = InventoryKnownSurfaceSource(
        _EmptyInventory(),
        observed_surface=[
            ObservedHostSurface(
                asset_id=asset_id,
                reachability="external",
                basis_refs=["s003:host-state:sha256:" + "4" * 64],
                observed_at=NOW,
                rationale="Observed external bind.",
            )
        ],
    )

    with pytest.raises(InventoryUnavailable, match="not bound to current inventory"):
        await source.list_known_surface(tenant_id=None)


def test_s003_unattributable_appears_closable_in_density(
    capsys: pytest.CaptureFixture[str],
) -> None:
    readings = surface_factor_readings(SurfaceSummary(observed_unattributable=2))

    assert len(readings) == 2
    assert all(reading.closable for reading in readings)
    assert all(reading.reason == OBSERVED_JOIN_UNAVAILABLE for reading in readings)
    assert all("ast_" not in repr(reading) for reading in readings)

    density_report(
        RunReport(
            target="private-estate",
            tenant_mode="enterprise",
            sbom_components=0,
            sbom_parsed=0,
            grype_matches=0,
            vuln_records=0,
            vuln_rejected=[],
            join_total=0,
            join_matched=0,
            stored=0,
            findings=[],
            coverage_factors=readings,
        )
    )
    rendered = capsys.readouterr().out
    assert "exposure" in rendered
    assert OBSERVED_JOIN_UNAVAILABLE in rendered
    assert "ast_" not in rendered


def test_s003_surface_guards_survive_python_o() -> None:
    script = """
import ipaddress
from datetime import UTC, datetime
from pydantic import ValidationError
from tools.s003_surface import SurfaceOutcome, classify_bind
from aqelyn.exposure import ExposureBasis

now = datetime(2026, 7, 27, tzinfo=UTC)
if classify_bind(str(ipaddress.ip_address(0))) != "external":
    raise SystemExit("wildcard bind was not external")
if classify_bind(str(ipaddress.ip_address(0x7F000001))) != "internal":
    raise SystemExit("loopback bind was not internal")
if classify_bind(str(ipaddress.ip_address(0x0A000001))) is not None:
    raise SystemExit("specific bind was guessed")
if ExposureBasis(
    kind="host_state",
    ref="s003:host-state:sha256:" + "0" * 64,
    as_of=now,
).kind != "host_state":
    raise SystemExit("host-state basis was not retained")
try:
    SurfaceOutcome(
        state="observed_unattributable",
        asset_key="smuggled",
        unknown_cause="input_missing",
        reason="surface observed, join key unavailable",
    )
except ValidationError:
    pass
else:
    raise SystemExit("unattributable surface claimed an asset")
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
