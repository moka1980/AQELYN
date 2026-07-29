"""S-004 W4-W7 acceptance tests."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tools.first_run import FactorReading, RunReport, density_report
from tools.s003_baseline import BaselineClaim, BaselineDefinition
from tools.s003_declaration import (
    MissionDeclarationApplication,
    MissionDeclarationOutcome,
)
from tools.s003_estate import (
    SURFACE_NOT_DERIVED_REASONS,
    NginxVHost,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
    UnitRecord,
    canonical_asset_key,
)
from tools.s003_surface import (
    ASSET_NOT_REGISTERED,
    NO_SURFACE_EVIDENCE,
    OBSERVED_JOIN_UNAVAILABLE,
    SurfaceSummary,
)
from tools.s004_baseline import CertificatePathBinding, assess_s004_baseline
from tools.s004_handin import (
    HandedInCaptureSet,
    parse_firewall_ruleset_capture,
    parse_privileged_socket_capture,
    parse_proxy_configuration_capture,
    prepare_handed_in_capture_set,
)
from tools.s004_route import (
    UPSTREAM_OFF_ESTATE,
    build_privileged_surface_application,
    build_proxy_topology_application,
    derive_s004_surface,
    derive_s004_topology,
    topology_factor_readings,
)
from tools.s004_run import assemble_s004_report

from aqelyn.assetconfig import ASSET_OBJECT_TYPE
from aqelyn.conventions import ActorRef, new_id
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.exposure import ExposureBasis, InMemoryExposureStore
from aqelyn.inventory import (
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    PostgresAssetStore,
)
from aqelyn.objects import InMemoryObjectStore, ObjectStore, ObjectTypeRegistry
from aqelyn.secrets import (
    CertificateDescriptor,
    InMemoryCryptoStore,
    SecretsIntelligenceEngine,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine
from aqelyn.vuln import CoverageReport

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000004004"
NOW = datetime(2026, 7, 29, 12, 48, 30, tzinfo=UTC)
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
        object_store: ObjectStore,
        *,
        tenant_id: str | None,
    ) -> None:
        self.store = store
        self.inventory = inventory
        self.object_store = object_store
        self.tenant_id = tenant_id


@asynccontextmanager
async def _harness(backend: str, tenant_mode: str) -> AsyncIterator[_Harness]:
    tenant_id = None if tenant_mode == "local" else TENANT
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    if backend == "memory":
        store: AssetStore = InMemoryAssetStore(mode=tenant_mode)
        yield _Harness(
            store,
            InventoryIntelligenceEngine(store),
            InMemoryObjectStore(registry=registry, mode=tenant_mode),
            tenant_id=tenant_id,
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresAssetStore.connect(PG_URL, mode=tenant_mode)
    from aqelyn.objects.postgres import PostgresObjectStore

    objects = await PostgresObjectStore.connect(
        PG_URL,
        registry=registry,
        mode=tenant_mode,
    )
    async with postgres._pool.acquire() as connection:
        await connection.execute("TRUNCATE aq_inventory_asset RESTART IDENTITY")
    async with objects._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield _Harness(
            postgres,
            InventoryIntelligenceEngine(postgres),
            objects,
            tenant_id=tenant_id,
        )
    finally:
        await objects.close()
        await postgres.close()


def _unit(index: int, *, pid: int | None) -> UnitRecord:
    native_id = f"unit-{index}.service"
    return UnitRecord(
        asset_key=canonical_asset_key("systemd_unit", native_id),
        native_id=native_id,
        display_name=f"Unit {index}",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        main_pid=pid,
    )


def _listener(address: str, port: int, *, pid: int | None) -> str:
    process = "" if pid is None else f' users:(("process",pid={pid},fd=1))'
    return f"tcp LISTEN 0 128 {address}:{port} *:*{process}"


def _capture_set(
    inventory: UnitInventoryDocument,
    *,
    listeners: list[str],
    proxy: str | None = None,
) -> HandedInCaptureSet:
    prior_surface = ServiceSurfaceDocument(
        collected_at=NOW,
        listeners_raw=None,
        firewall_raw=None,
        nginx_config=None,
        unavailable_details=dict(SURFACE_NOT_DERIVED_REASONS),
    )
    return prepare_handed_in_capture_set(
        inventory,
        prior_surface,
        privileged_sockets=parse_privileged_socket_capture(
            "\n".join(listeners),
            captured_at=NOW + timedelta(seconds=5),
        ),
        proxy_configuration=parse_proxy_configuration_capture(
            proxy
            or """
                server {
                    listen 443;
                    server_name host-reference;
                    proxy_pass http://127.0.0.1:20002;
                    ssl_certificate certificate-reference;
                }
            """,
            captured_at=NOW + timedelta(seconds=6),
        ),
        firewall_ruleset=parse_firewall_ruleset_capture(
            '{"nftables":[{"metainfo":{}}]}',
            captured_at=NOW + timedelta(seconds=7),
        ),
        max_skew=timedelta(minutes=1),
    )


def _source() -> DiscoverySource:
    return DiscoverySource(
        source_id=new_id("src"),
        reliability=1.0,
        health="ok",
        as_of=NOW,
    )


def _definition() -> BaselineDefinition:
    return BaselineDefinition(
        claims=[
            BaselineClaim(claim_id=claim_id, comparator="eq", expected=True)
            for claim_id in ("C1", "C2", "C3", "C4", "C5")
        ]
    )


class _Catalog:
    def lookup(self, cve_id: str) -> None:
        del cve_id
        return None


def _base_report(tenant_mode: str) -> RunReport:
    return RunReport(
        target="private-estate",
        tenant_mode=tenant_mode,
        sbom_components=0,
        sbom_parsed=0,
        grype_matches=0,
        vuln_records=0,
        vuln_rejected=[],
        join_total=0,
        join_matched=0,
        stored=0,
        findings=[],
    )


def _mission_application() -> MissionDeclarationApplication:
    return MissionDeclarationApplication(
        outcomes=[
            MissionDeclarationOutcome(
                asset_key="declared-reference",
                asset_id=new_id("obj"),
                status="known",
                criticality_tier=2,
                mission_id=new_id("obj"),
                reason="owner criticality declared",
            )
        ],
        joined=1,
        declared=1,
        undeclared=0,
        unregistered=0,
    )


def _baseline_store() -> InMemoryObjectStore:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    return InMemoryObjectStore(registry=registry)


async def _certificate_owner(
    *,
    not_after: datetime,
) -> tuple[SecretsIntelligenceEngine, str]:
    actor = ActorRef(actor_type="system", actor_id="s004-certificate-owner")
    source_id = new_id("src")
    fingerprint = f"hmac-sha256:{1:064x}"
    evidence_store = InMemoryEvidenceStore()
    evidence = await evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=None,
            evidence_type="crypto_descriptor",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=actor,
            source_id=source_id,
            method="handed_in_descriptor",
            content={"fingerprint": fingerprint, "descriptor_kind": "metadata_only"},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    engine = SecretsIntelligenceEngine(
        InMemoryCryptoStore(),
        object_store=InMemoryObjectStore(),
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore()),
        evidence_store=evidence_store,
        trust=TrustEngine(registry=InMemorySourceReliabilityRegistry(default_reliability=0.8)),
        actor=actor,
    )
    [asset] = await engine.ingest_crypto_assets(
        [],
        [
            CertificateDescriptor(
                tenant_id=None,
                fingerprint=fingerprint,
                serial="01:23",
                subject="CN=service-reference",
                issuer="CN=issuer-reference",
                not_after=not_after,
                source_id=source_id,
                observed_at=NOW,
                evidence_id=evidence.id,
            )
        ],
        tenant_id=None,
    )
    return engine, asset.id


def _unregistered_vhost() -> NginxVHost:
    return NginxVHost(
        asset_key=canonical_asset_key("nginx_vhost", "unregistered-vhost"),
        native_id="unregistered-vhost",
        display_name="Unregistered virtual host",
    )


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_s004_attribution_resolves_where_evidence_exists(
    backend: str,
    tenant_mode: str,
) -> None:
    units = [_unit(1, pid=101), _unit(2, pid=102), _unit(3, pid=103)]
    inventory = UnitInventoryDocument(collected_at=NOW, units=units)
    captures = _capture_set(
        inventory,
        listeners=[
            _listener("0.0.0.0", 20001, pid=101),
            _listener("127.0.0.1", 20002, pid=102),
            _listener("0.0.0.0", 20999, pid=999),
        ],
    )
    selected_ids = {unit.asset_key: new_id("ast") for unit in units}

    async with _harness(backend, tenant_mode) as harness:
        result = await derive_s004_surface(
            captures,
            inventory_owner=harness.inventory,
            exposure_store=InMemoryExposureStore(mode=tenant_mode),
            source=_source(),
            tenant_id=harness.tenant_id,
            asset_ids_by_key=selected_ids,
            unregistered_assets=[_unregistered_vhost()],
        )

    assert result.application.aggregate() == SurfaceSummary(
        derived_external=1,
        derived_internal=1,
        no_surface_evidence=1,
        observed_unattributable=1,
        not_registered=1,
    )
    assert [row.asset_key for row in result.attributed_listeners] == [
        units[0].asset_key,
        units[1].asset_key,
        None,
    ]
    basis = {
        row.asset_ref.ref_id: row.basis
        for row in result.attack_surface
        if row.asset_ref.ref_id in selected_ids.values()
    }
    capture_id = captures.privileged_sockets.capture.capture_id
    for unit in units[:2]:
        assert {item.kind for item in basis[selected_ids[unit.asset_key]]} == {"host_state"}
        assert all(item.ref.startswith(capture_id) for item in basis[selected_ids[unit.asset_key]])


def test_s004_unattributable_state_still_reachable() -> None:
    inventory = UnitInventoryDocument(collected_at=NOW, units=[_unit(1, pid=101)])
    captures = _capture_set(
        inventory,
        listeners=[_listener("0.0.0.0", 20001, pid=999)],
    )
    selected_ids = {inventory.units[0].asset_key: new_id("ast")}

    _, application = build_privileged_surface_application(
        captures,
        registered_asset_ids=selected_ids,
    )
    states = {outcome.state: outcome.reason for outcome in application.outcomes}
    assert states["observed_unattributable"] == OBSERVED_JOIN_UNAVAILABLE
    assert states["no_surface_evidence"] == NO_SURFACE_EVIDENCE


def test_s004_three_states_still_distinguishable() -> None:
    inventory = UnitInventoryDocument(collected_at=NOW, units=[_unit(1, pid=101)])
    captures = _capture_set(
        inventory,
        listeners=[_listener("0.0.0.0", 20001, pid=999)],
    )
    selected_ids = {inventory.units[0].asset_key: new_id("ast")}

    _, application = build_privileged_surface_application(
        captures,
        registered_asset_ids=selected_ids,
        unregistered_assets=[_unregistered_vhost()],
    )
    states = {outcome.state: outcome.reason for outcome in application.outcomes}
    assert states["no_surface_evidence"] == NO_SURFACE_EVIDENCE
    assert states["observed_unattributable"] == OBSERVED_JOIN_UNAVAILABLE
    assert states["not_registered"] == ASSET_NOT_REGISTERED
    assert (
        len(
            {
                states["no_surface_evidence"],
                states["observed_unattributable"],
                states["not_registered"],
            }
        )
        == 3
    )


def test_s004_proxy_routes_preserve_server_block_context() -> None:
    captured = parse_proxy_configuration_capture(
        """
        server {
            listen 443 ssl;
            server_name first-reference;
            ssl_certificate first-certificate-reference;
            location / {
                proxy_pass http://127.0.0.1:20001;
            }
        }
        server {
            listen 8443 ssl;
            server_name second-reference;
            ssl_certificate second-certificate-reference;
            location / {
                proxy_pass http://127.0.0.1:20002;
            }
        }
        """,
        captured_at=NOW,
    )

    routes = {
        (route.frontend_ref, route.upstream_ref, route.server_names) for route in captured.routes
    }
    assert routes == {
        ("443", "http://127.0.0.1:20001", ("first-reference",)),
        ("8443", "http://127.0.0.1:20002", ("second-reference",)),
    }
    assert ("443", "http://127.0.0.1:20002", ("first-reference",)) not in routes


def test_s004_proxy_parser_does_not_treat_variable_as_block() -> None:
    captured = parse_proxy_configuration_capture(
        """
        server {
            listen 443;
            proxy_pass http://${backend_reference};
        }
        """,
        captured_at=NOW,
    )

    [route] = captured.routes
    assert route.upstream_ref == "http://${backend_reference}"


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_s004_declared_chain_derived(
    backend: str,
    tenant_mode: str,
) -> None:
    units = [_unit(1, pid=101), _unit(2, pid=102), _unit(3, pid=103)]
    inventory = UnitInventoryDocument(collected_at=NOW, units=units)
    captures = _capture_set(
        inventory,
        listeners=[
            _listener("0.0.0.0", 443, pid=101),
            _listener("0.0.0.0", 8443, pid=101),
            _listener("127.0.0.1", 20002, pid=102),
        ],
        proxy="""
            server {
                listen 443 ssl;
                server_name local-reference;
                ssl_certificate certificate-reference;
                location / {
                    proxy_pass http://127.0.0.1:20002;
                }
            }
            server {
                listen 8443 ssl;
                server_name remote-reference;
                proxy_pass http://203.0.113.10:9000;
            }
        """,
    )
    selected_ids = {unit.asset_key: new_id("ast") for unit in units}

    async with _harness(backend, tenant_mode) as harness:
        result = await derive_s004_topology(
            captures,
            inventory_owner=harness.inventory,
            exposure_store=InMemoryExposureStore(mode=tenant_mode),
            source=_source(),
            tenant_id=harness.tenant_id,
            asset_ids_by_key=selected_ids,
        )

    assert result.topology_application.aggregate().model_dump() == {
        "derived": 1,
        "off_estate": 1,
        "join_unavailable": 0,
    }
    derived = next(
        outcome for outcome in result.topology_application.outcomes if outcome.state == "derived"
    )
    assert derived.frontend_asset_id == selected_ids[units[0].asset_key]
    assert derived.upstream_asset_id == selected_ids[units[1].asset_key]
    assert derived.reachability == "external"
    assert derived.configuration_ref.startswith(captures.proxy_configuration.capture.capture_id)

    upstream = next(
        row
        for row in result.attack_surface
        if row.asset_ref.ref_id == selected_ids[units[1].asset_key]
    )
    assert upstream.classification == "configuration_declared_service"
    assert {basis.kind for basis in upstream.basis} == {"configuration", "host_state"}
    assert any(
        basis.ref.startswith(captures.proxy_configuration.capture.capture_id)
        for basis in upstream.basis
        if basis.kind == "configuration"
    )


def test_s004_basis_distinguishes_bind_from_config() -> None:
    assert (
        ExposureBasis(
            kind="inventory",
            ref="inventory-reference",
            as_of=NOW,
        ).kind
        == "inventory"
    )
    assert (
        ExposureBasis(
            kind="configuration",
            ref="configuration-reference",
            as_of=NOW,
        ).kind
        == "configuration"
    )
    units = [_unit(1, pid=101), _unit(2, pid=102)]
    inventory = UnitInventoryDocument(collected_at=NOW, units=units)
    captures = _capture_set(
        inventory,
        listeners=[
            _listener("0.0.0.0", 443, pid=101),
            _listener("127.0.0.1", 20002, pid=102),
        ],
    )
    selected_ids = {unit.asset_key: new_id("ast") for unit in units}
    attributed, _ = build_privileged_surface_application(
        captures,
        registered_asset_ids=selected_ids,
    )
    topology = build_proxy_topology_application(
        captures,
        attributed_listeners=attributed,
        registered_asset_ids=selected_ids,
    )
    [record] = topology.surface_records
    assert {basis.kind for basis in record.basis} == {"configuration", "host_state"}


def test_s004_offestate_upstream_is_unknown_with_reason() -> None:
    inventory = UnitInventoryDocument(collected_at=NOW, units=[_unit(1, pid=101)])
    captures = _capture_set(
        inventory,
        listeners=[_listener("0.0.0.0", 443, pid=101)],
        proxy="""
            server {
                listen 443;
                proxy_pass http://203.0.113.10:9000;
            }
        """,
    )
    selected_ids = {inventory.units[0].asset_key: new_id("ast")}
    attributed, _ = build_privileged_surface_application(
        captures,
        registered_asset_ids=selected_ids,
    )
    topology = build_proxy_topology_application(
        captures,
        attributed_listeners=attributed,
        registered_asset_ids=selected_ids,
    )

    [outcome] = topology.outcomes
    assert outcome.state == "off_estate"
    assert outcome.unknown_cause == "source_cannot_assert"
    assert outcome.reason == UPSTREAM_OFF_ESTATE
    assert topology.surface_records == []


def test_s004_derived_route_with_ambiguous_bind_stays_unknown() -> None:
    units = [_unit(1, pid=101), _unit(2, pid=102)]
    inventory = UnitInventoryDocument(collected_at=NOW, units=units)
    captures = _capture_set(
        inventory,
        listeners=[
            _listener("192.0.2.1", 443, pid=101),
            _listener("127.0.0.1", 20002, pid=102),
        ],
    )
    selected_ids = {unit.asset_key: new_id("ast") for unit in units}
    attributed, _ = build_privileged_surface_application(
        captures,
        registered_asset_ids=selected_ids,
    )
    topology = build_proxy_topology_application(
        captures,
        attributed_listeners=attributed,
        registered_asset_ids=selected_ids,
    )

    [outcome] = topology.outcomes
    assert outcome.state == "derived"
    assert outcome.reachability == "unknown"
    assert outcome.unknown_cause == "source_cannot_assert"
    [reading] = topology_factor_readings(topology)
    assert reading.status == "unknown"
    assert reading.unknown_cause == "source_cannot_assert"


def test_s004_density_honors_known_supplemental_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _base_report("local")
    report.coverage_factors = [
        # The full-chain test produces these through owner results; this small
        # control isolates the reporter branch for mutation testing.
        FactorReading(
            name="exposure",
            status="known",
            reason="known reference",
            source="s004:test",
            unknown_cause=None,
        ),
        FactorReading(
            name="exposure",
            status="unknown",
            reason="unknown reference",
            source="s004:test",
            unknown_cause="input_missing",
        ),
    ]

    density_report(report)
    rendered = capsys.readouterr().out
    assert "exposure     known=   1 unknown=   1" in rendered


async def test_s004_c1_checkable_via_gate() -> None:
    units = [_unit(1, pid=101), _unit(2, pid=102)]
    inventory = UnitInventoryDocument(collected_at=NOW, units=units)
    captures = _capture_set(
        inventory,
        listeners=[
            _listener("0.0.0.0", 443, pid=101),
            _listener("127.0.0.1", 20002, pid=102),
        ],
    )

    assessment = await assess_s004_baseline(
        _baseline_store(),
        captures,
        definition=_definition(),
        tenant_id=None,
        observed_at=NOW,
        source_id=new_id("src"),
    )

    by_claim = {outcome.claim_id: outcome for outcome in assessment.outcomes}
    assert by_claim["C1"].status == "pass"
    assert by_claim["C4"].status == "pass"
    assert by_claim["C5"].status == "unknown"
    assert by_claim["C5"].unknown_class == "certificate_lifecycle"
    assert assessment.aggregate() == {"passed": 2, "failed": 0, "unknown": 3}


async def test_s004_c5_unknown_when_cert_metadata_absent() -> None:
    inventory = UnitInventoryDocument(collected_at=NOW, units=[_unit(1, pid=101)])
    captures = _capture_set(
        inventory,
        listeners=[_listener("0.0.0.0", 443, pid=101)],
    )

    assessment = await assess_s004_baseline(
        _baseline_store(),
        captures,
        definition=_definition(),
        tenant_id=None,
        observed_at=NOW,
        source_id=new_id("src"),
    )

    c5 = next(outcome for outcome in assessment.outcomes if outcome.claim_id == "C5")
    assert c5.status == "unknown"
    assert c5.unknown_class == "certificate_lifecycle"


async def test_s004_c5_routes_to_ea0032() -> None:
    inventory = UnitInventoryDocument(collected_at=NOW, units=[_unit(1, pid=101)])
    captures = _capture_set(
        inventory,
        listeners=[_listener("0.0.0.0", 443, pid=101)],
    )
    owner, future_id = await _certificate_owner(not_after=NOW + timedelta(days=365))
    future = await assess_s004_baseline(
        _baseline_store(),
        captures,
        definition=_definition(),
        tenant_id=None,
        observed_at=NOW,
        source_id=new_id("src"),
        certificate_owner=owner,
        certificate_bindings=[
            CertificatePathBinding(
                certificate_ref="certificate-reference",
                certificate_id=future_id,
            )
        ],
    )
    future_c5 = next(outcome for outcome in future.outcomes if outcome.claim_id == "C5")
    assert future_c5.status == "unknown"
    assert future_c5.unknown_class == "certificate_lifecycle"

    expired_owner, expired_id = await _certificate_owner(not_after=NOW - timedelta(days=1))
    expired = await assess_s004_baseline(
        _baseline_store(),
        captures,
        definition=_definition(),
        tenant_id=None,
        observed_at=NOW,
        source_id=new_id("src"),
        certificate_owner=expired_owner,
        certificate_bindings=[
            CertificatePathBinding(
                certificate_ref="certificate-reference",
                certificate_id=expired_id,
            )
        ],
    )
    expired_c5 = next(outcome for outcome in expired.outcomes if outcome.claim_id == "C5")
    assert expired_c5.status == "fail"
    assert expired_c5.unknown_class is None


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_s004_chain_end_to_end(
    backend: str,
    tenant_mode: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    units = [_unit(1, pid=101), _unit(2, pid=102), _unit(3, pid=103)]
    inventory = UnitInventoryDocument(collected_at=NOW, units=units)
    captures = _capture_set(
        inventory,
        listeners=[
            _listener("0.0.0.0", 443, pid=101),
            _listener("0.0.0.0", 8443, pid=101),
            _listener("127.0.0.1", 20002, pid=102),
        ],
        proxy="""
            server {
                listen 443 ssl;
                server_name local-reference;
                ssl_certificate certificate-reference;
                proxy_pass http://127.0.0.1:20002;
            }
            server {
                listen 8443 ssl;
                server_name remote-reference;
                proxy_pass http://203.0.113.10:9000;
            }
        """,
    )
    selected_ids = {unit.asset_key: new_id("ast") for unit in units}

    async with _harness(backend, tenant_mode) as harness:
        report, baseline, derivation = await assemble_s004_report(
            _base_report(tenant_mode),
            catalog=_Catalog(),
            vulnerability_document={"matches": []},
            coverage=CoverageReport(
                scanned=[],
                unscanned=[],
                stale=[],
                unassessable=[],
                computed_at=NOW,
            ),
            captures=captures,
            mission_application=_mission_application(),
            baseline_definition=_definition(),
            object_store=harness.object_store,
            inventory_owner=harness.inventory,
            exposure_store=InMemoryExposureStore(mode=tenant_mode),
            discovery_source=_source(),
            tenant_id=harness.tenant_id,
            observed_at=NOW,
            source_id=new_id("src"),
            asset_ids_by_key=selected_ids,
        )

    assert baseline.aggregate() == {"passed": 2, "failed": 0, "unknown": 3}
    assert derivation.topology_application.aggregate().model_dump() == {
        "derived": 1,
        "off_estate": 1,
        "join_unavailable": 0,
    }
    assert report.roadmap_dependencies == []

    density_report(report)
    rendered = capsys.readouterr().out
    assert "exposure     known=   4 unknown=   2" in rendered
    assert "baseline     known=   2 unknown=   3" in rendered
    assert "mission      known=   1 unknown=   0" in rendered
    assert "certificate lifecycle owner could not establish validity" in rendered
    for private_value in (
        captures.privileged_sockets.capture.capture_id,
        captures.proxy_configuration.capture.capture_id,
        "unit-1.service",
        "local-reference",
        "certificate-reference",
    ):
        assert private_value not in rendered


def test_s004_w4_w7_guards_survive_python_o() -> None:
    script = """
import contextlib
import io
from datetime import UTC, datetime
from tools.first_run import FactorReading, RunReport, density_report
from tools.s004_handin import parse_proxy_configuration_capture
from aqelyn.exposure import ExposureBasis

now = datetime(2026, 7, 29, tzinfo=UTC)
captured = parse_proxy_configuration_capture(
    '''
    server { listen 443; proxy_pass http://127.0.0.1:20001; }
    server { listen 8443; proxy_pass http://127.0.0.1:20002; }
    ''',
    captured_at=now,
)
routes = {(row.frontend_ref, row.upstream_ref) for row in captured.routes}
if routes != {
    ("443", "http://127.0.0.1:20001"),
    ("8443", "http://127.0.0.1:20002"),
}:
    raise SystemExit("server-block route context changed under optimization")
if ExposureBasis(kind="configuration", ref="config-reference", as_of=now).kind != "configuration":
    raise SystemExit("configuration basis changed under optimization")
report = RunReport(
    target="private-estate",
    tenant_mode="local",
    sbom_components=0,
    sbom_parsed=0,
    grype_matches=0,
    vuln_records=0,
    vuln_rejected=[],
    join_total=0,
    join_matched=0,
    stored=0,
    findings=[],
    coverage_factors=[
        FactorReading(
            name="exposure",
            status="known",
            reason="known reference",
            source="s004:test",
            unknown_cause=None,
        ),
        FactorReading(
            name="exposure",
            status="unknown",
            reason="unknown reference",
            source="s004:test",
            unknown_cause="input_missing",
        ),
    ],
)
output = io.StringIO()
with contextlib.redirect_stdout(output):
    density_report(report)
if "exposure     known=   1 unknown=   1" not in output.getvalue():
    raise SystemExit("typed supplemental status changed under optimization")
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
