"""S-003 U5 acceptance tests for the assembled count-only report."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tools.first_run import (
    RoadmapDependency,
    RunReport,
    density_report,
    roadmap_dependency_counts,
)
from tools.s003_baseline import (
    BaselineClaim,
    BaselineDefinition,
)
from tools.s003_declaration import (
    CRITICALITY_NOT_DECLARED,
    MissionDeclarationApplication,
    MissionDeclarationOutcome,
)
from tools.s003_estate import (
    SURFACE_NOT_DERIVED_REASONS,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
)
from tools.s003_run import assemble_s003_report
from tools.s003_surface import (
    OBSERVED_JOIN_UNAVAILABLE,
    SurfaceApplication,
    SurfaceOutcome,
)

from aqelyn.assetconfig import ASSET_OBJECT_TYPE
from aqelyn.conventions import new_id
from aqelyn.objects import InMemoryObjectStore, ObjectStore, ObjectTypeRegistry
from aqelyn.vuln import CoverageGap, CoverageReport

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000003005"
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
MATRIX = [
    pytest.param("memory", "local", id="memory-local"),
    pytest.param("memory", "enterprise", id="memory-enterprise"),
    pytest.param("postgres", "local", id="postgres-local"),
    pytest.param("postgres", "enterprise", id="postgres-enterprise"),
]


class _Catalog:
    def __init__(self, *cves: str) -> None:
        self.cves = frozenset(cves)

    def lookup(self, cve_id: str) -> object | None:
        return object() if cve_id in self.cves else None


@asynccontextmanager
async def _store(backend: str, tenant_mode: str) -> AsyncIterator[ObjectStore]:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    if backend == "memory":
        yield InMemoryObjectStore(registry=registry, mode=tenant_mode)
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.objects.postgres import PostgresObjectStore

    postgres = await PostgresObjectStore.connect(
        PG_URL,
        registry=registry,
        mode=tenant_mode,
    )
    async with postgres._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield postgres
    finally:
        await postgres.close()


def _base_report() -> RunReport:
    return RunReport(
        target="private-estate",
        tenant_mode="enterprise",
        sbom_components=2,
        sbom_parsed=2,
        grype_matches=2,
        vuln_records=2,
        vuln_rejected=[],
        join_total=2,
        join_matched=2,
        stored=2,
        findings=[],
    )


def _inventory() -> UnitInventoryDocument:
    return UnitInventoryDocument(collected_at=NOW, units=[])


def _surface(
    *,
    listeners_raw: str | None = "tcp LISTEN 0 128 0.0.0.0:443 0.0.0.0:*",
) -> ServiceSurfaceDocument:
    unavailable = {"nginx": "read unavailable"}
    if listeners_raw is None:
        unavailable["listeners"] = SURFACE_NOT_DERIVED_REASONS["listeners"]
    return ServiceSurfaceDocument(
        collected_at=NOW,
        listeners_raw=listeners_raw,
        firewall_raw=None,
        nginx_config=None,
        listeners=None if listeners_raw is None else [],
        vhosts=[],
        unavailable_details=unavailable,
    )


def _surface_application() -> SurfaceApplication:
    return SurfaceApplication(
        outcomes=[
            SurfaceOutcome(
                state="observed_unattributable",
                unknown_cause="input_missing",
                reason=OBSERVED_JOIN_UNAVAILABLE,
            )
        ],
        observed_surface=[],
    )


def _mission_application() -> MissionDeclarationApplication:
    return MissionDeclarationApplication(
        outcomes=[
            MissionDeclarationOutcome(
                asset_key="declared",
                asset_id=new_id("obj"),
                status="known",
                criticality_tier=2,
                mission_id=new_id("obj"),
                reason="owner criticality declared",
            ),
            MissionDeclarationOutcome(
                asset_key="undeclared",
                asset_id=new_id("obj"),
                status="unknown",
                unknown_cause="input_missing",
                reason=CRITICALITY_NOT_DECLARED,
            ),
        ],
        joined=2,
        declared=1,
        undeclared=1,
        unregistered=0,
    )


def _coverage() -> CoverageReport:
    return CoverageReport(
        scanned=[],
        unscanned=[],
        stale=[],
        unassessable=[
            CoverageGap(
                asset_ref=new_id("ast"),
                reason="no provider matches the handed-in component identity",
                unknown_cause="provider_unconfigured",
            )
        ],
        computed_at=NOW,
    )


def _definition() -> BaselineDefinition:
    return BaselineDefinition(
        claims=[
            BaselineClaim(claim_id=claim_id, comparator="eq", expected=True)
            for claim_id in ("C1", "C2", "C3", "C4", "C5")
        ]
    )


def _vulnerabilities() -> dict[str, Any]:
    return {
        "matches": [
            {
                "vulnerability": {"id": "CVE-2026-0001"},
                "artifact": {"type": "binary"},
                "matchDetails": [{"matcher": "binary-classifier"}],
            },
            {
                "vulnerability": {"id": "CVE-2026-0002"},
                "artifact": {"type": "deb"},
            },
        ]
    }


async def _assemble(
    store: ObjectStore,
    *,
    tenant_id: str | None,
    surface: ServiceSurfaceDocument | None = None,
) -> tuple[RunReport, Any]:
    return await assemble_s003_report(
        _base_report(),
        catalog=_Catalog("CVE-2026-0001"),
        vulnerability_document=_vulnerabilities(),
        coverage=_coverage(),
        inventory=_inventory(),
        surface=_surface() if surface is None else surface,
        surface_application=_surface_application(),
        mission_application=_mission_application(),
        baseline_definition=_definition(),
        object_store=store,
        tenant_id=tenant_id,
        observed_at=NOW,
        source_id=new_id("src"),
    )


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_s003_chain_end_to_end(backend: str, tenant_mode: str) -> None:
    tenant_id = None if tenant_mode == "local" else TENANT
    async with _store(backend, tenant_mode) as store:
        report, baseline = await _assemble(store, tenant_id=tenant_id)

    assert baseline.aggregate() == {"passed": 1, "failed": 0, "unknown": 4}
    assert {reading.name for reading in report.coverage_factors} == {
        "baseline",
        "exposure",
        "mission",
        "vulnerability_coverage",
    }
    assert roadmap_dependency_counts(report.roadmap_dependencies) == {"privileged_read": 4}
    assert report.kev_join is not None
    assert report.kev_join.matched_cves == 1


async def test_u5_baseline_observations_derived_from_documents() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    store = InMemoryObjectStore(registry=registry)
    _, passing = await _assemble(store, tenant_id=None)
    _, failing = await _assemble(store, tenant_id=None, surface=_surface(listeners_raw=""))

    assert passing.passed == 1
    assert failing.failed == 1
    assert failing.passed == 0


async def test_u5_unresolvable_claim_still_unknown_via_gate() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    report, baseline = await _assemble(
        InMemoryObjectStore(registry=registry),
        tenant_id=None,
        surface=_surface(listeners_raw=None),
    )

    assert baseline.aggregate() == {"passed": 0, "failed": 0, "unknown": 5}
    assert (
        sum(
            reading.name == "baseline" and reading.status == "unknown"
            for reading in report.coverage_factors
        )
        == 5
    )


async def test_s003_kev_join_verified_and_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    report, _ = await _assemble(InMemoryObjectStore(registry=registry), tenant_id=None)

    density_report(report)
    rendered = capsys.readouterr().out

    assert "matched=1 distinct_cves=2" in rendered
    assert "join's positive control" in rendered
    assert "pre-run hypothesis: falsified" in rendered
    assert "class=vendored_binary_component count=1" in rendered


def test_u5_dependents_derived_not_declared() -> None:
    dependencies = [
        RoadmapDependency(decision="privileged_read", dependent=f"dependent:{index}")
        for index in range(4)
    ]

    assert roadmap_dependency_counts(dependencies) == {"privileged_read": 4}


def test_u5_adding_a_dependent_changes_the_count() -> None:
    dependencies = [
        RoadmapDependency(decision="privileged_read", dependent=f"dependent:{index}")
        for index in range(4)
    ]
    changed = [
        *dependencies,
        RoadmapDependency(decision="privileged_read", dependent="dependent:new"),
    ]

    assert roadmap_dependency_counts(changed)["privileged_read"] == 5


def test_u5_density_refusal_cannot_emit_identifying_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    identifier = "obj_019f0000000070008000000000000005"
    priority = SimpleNamespace(
        vulnerability_id=identifier,
        factors={"exposure": {"status": "broken", "reason": identifier}},
    )
    report = _base_report()
    report.findings = [priority, RuntimeError(identifier)]

    with pytest.raises(SystemExit):
        density_report(report)
    rendered = capsys.readouterr().out

    assert identifier not in rendered
    assert "RuntimeError" in rendered


def test_s003_u5_guards_survive_python_o() -> None:
    script = """
from tools.first_run import RoadmapDependency, measure_kev_join, roadmap_dependency_counts

class Catalog:
    def lookup(self, cve_id):
        return object() if cve_id == "CVE-2026-0001" else None

document = {
    "matches": [
        {
            "vulnerability": {"id": "CVE-2026-0001"},
            "artifact": {"type": "binary"},
        }
    ]
}
measurement = measure_kev_join(Catalog(), document)
if measurement.matched_cves != 1 or measurement.hypothesis_status != "falsified":
    raise SystemExit("KEV positive control disappeared under optimization")
dependencies = [
    RoadmapDependency(decision="privileged_read", dependent=f"d:{index}")
    for index in range(4)
]
if roadmap_dependency_counts(dependencies) != {"privileged_read": 4}:
    raise SystemExit("dependency discovery changed under optimization")
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
