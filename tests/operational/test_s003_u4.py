"""S-003 U4 acceptance tests for the owner-confirmed baseline."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from tools.first_run import RunReport, density_report
from tools.s003_baseline import (
    COLLECTION_SCOPE_INCOMPLETE,
    NO_BASELINE_DECLARED,
    PRIVILEGED_READ_REQUIRED,
    BaselineAssessment,
    BaselineClaim,
    BaselineDefinition,
    BaselineOutcome,
    assess_s003_baseline,
    baseline_factor_readings,
    derive_baseline_observations,
    s003_acg_config,
)
from tools.s003_estate import (
    SURFACE_NOT_DERIVED_REASONS,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
)

from aqelyn.assetconfig import ASSET_OBJECT_TYPE
from aqelyn.assetconfig import compare as owner_compare
from aqelyn.conventions import new_id
from aqelyn.objects import InMemoryObjectStore, ObjectStore, ObjectTypeRegistry

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000003004"
NOW = datetime(2026, 7, 28, tzinfo=UTC)
MATRIX = [
    pytest.param("memory", "local", id="memory-local"),
    pytest.param("memory", "enterprise", id="memory-enterprise"),
    pytest.param("postgres", "local", id="postgres-local"),
    pytest.param("postgres", "enterprise", id="postgres-enterprise"),
]


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


def _definition() -> BaselineDefinition:
    return BaselineDefinition(
        claims=[
            BaselineClaim(claim_id=claim_id, comparator="eq", expected=True)
            for claim_id in ("C1", "C2", "C3", "C4", "C5")
        ]
    )


def _documents(
    *,
    listeners_raw: str | None = "tcp LISTEN 0 128 0.0.0.0:443 0.0.0.0:*",
) -> tuple[UnitInventoryDocument, ServiceSurfaceDocument]:
    unavailable = (
        {"listeners": SURFACE_NOT_DERIVED_REASONS["listeners"]} if listeners_raw is None else {}
    )
    return (
        UnitInventoryDocument(collected_at=NOW, units=[]),
        ServiceSurfaceDocument(
            collected_at=NOW,
            listeners_raw=listeners_raw,
            firewall_raw=None,
            nginx_config=None,
            listeners=None if listeners_raw is None else [],
            vhosts=[],
            unavailable_details=unavailable,
        ),
    )


async def _assess(
    store: ObjectStore,
    *,
    listeners_raw: str | None = "tcp LISTEN 0 128 0.0.0.0:443 0.0.0.0:*",
    tenant_id: str | None = None,
) -> BaselineAssessment:
    inventory, surface = _documents(listeners_raw=listeners_raw)
    return await assess_s003_baseline(
        store,
        definition=_definition(),
        inventory=inventory,
        surface=surface,
        tenant_id=tenant_id,
        observed_at=NOW,
        source_id=new_id("src"),
    )


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_u4_unknown_bucket_visible(
    backend: str,
    tenant_mode: str,
) -> None:
    tenant_id = None if tenant_mode == "local" else TENANT
    async with _store(backend, tenant_mode) as store:
        assessment = await _assess(store, tenant_id=tenant_id)

    assert assessment.aggregate() == {
        "passed": 1,
        "failed": 0,
        "unknown": 4,
    }
    assert assessment.passed + assessment.failed + assessment.unknown == 5
    assert {outcome.status for outcome in assessment.outcomes} == {"pass", "unknown"}


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_u4_unknown_not_counted_as_failed(
    backend: str,
    tenant_mode: str,
) -> None:
    tenant_id = None if tenant_mode == "local" else TENANT
    async with _store(backend, tenant_mode) as store:
        assessment = await _assess(store, tenant_id=tenant_id)

    assert s003_acg_config().unknown_is_fail is False
    assert assessment.failed == 0
    assert assessment.unknown == 4
    assert all(
        outcome.status not in ("pass", "fail")
        for outcome in assessment.outcomes
        if outcome.unknown_class is not None
    )


async def test_u4_unresolved_never_reaches_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compared: list[object] = []

    def recording_compare(comparator: str, observed: object, expected: object) -> bool:
        compared.append(observed)
        return owner_compare(comparator, observed, expected)

    monkeypatch.setattr("aqelyn.assetconfig.drift.compare", recording_compare)
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    assessment = await _assess(InMemoryObjectStore(registry=registry))

    assert compared == [True]
    assert assessment.unknown == 4


async def test_u4_missing_observed_is_unknown_not_false() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    assessment = await _assess(InMemoryObjectStore(registry=registry))

    unknowns = [outcome for outcome in assessment.outcomes if outcome.status == "unknown"]
    assert len(unknowns) == 4
    assert all(outcome.status != "fail" for outcome in unknowns)


async def test_u4_resolved_failure_stays_failed() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    assessment = await _assess(
        InMemoryObjectStore(registry=registry),
        listeners_raw="",
    )

    assert assessment.aggregate() == {
        "passed": 1,
        "failed": 1,
        "unknown": 3,
    }


async def test_u4_resolution_change_clears_stale_observed_value() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    store = InMemoryObjectStore(registry=registry)
    first = await _assess(store)
    second = await _assess(store, listeners_raw=None)

    assert first.passed == 1
    assert second.aggregate() == {
        "passed": 0,
        "failed": 0,
        "unknown": 5,
    }


def test_u4_three_bucket_totals_reconcile() -> None:
    with pytest.raises(ValidationError, match="bucket counts do not match"):
        BaselineAssessment(
            baseline_declared=True,
            passed=0,
            failed=0,
            unknown=0,
            outcomes=[
                BaselineOutcome(
                    claim_id="C1",
                    status="unknown",
                    unknown_class="privileged_read",
                    reason=PRIVILEGED_READ_REQUIRED,
                )
            ],
        )


async def test_u4_unknown_reasons_distinct_by_class() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    assessment = await _assess(InMemoryObjectStore(registry=registry))
    reasons = {
        outcome.unknown_class: outcome.reason
        for outcome in assessment.outcomes
        if outcome.status == "unknown"
    }

    assert reasons == {
        "collection_scope": COLLECTION_SCOPE_INCOMPLETE,
        "privileged_read": PRIVILEGED_READ_REQUIRED,
    }
    assert len(set(reasons.values())) == 2


async def test_u4_privileged_read_is_one_roadmap_item(
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    assessment = await _assess(InMemoryObjectStore(registry=registry))

    assert len(assessment.roadmap_dependencies) == 2
    assert {dependency.decision for dependency in assessment.roadmap_dependencies} == {
        "privileged_read"
    }
    assert {dependency.dependent for dependency in assessment.roadmap_dependencies} == {
        "baseline:C1",
        "baseline:C5",
    }

    density_report(
        RunReport(
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
            coverage_factors=baseline_factor_readings(assessment),
            roadmap_dependencies=assessment.roadmap_dependencies,
        )
    )
    rendered = capsys.readouterr().out
    assert rendered.count("privileged_read") == 1
    assert "dependents=2" in rendered
    assert all(claim_id not in rendered for claim_id in ("C1", "C2", "C3", "C4", "C5"))


async def test_s003_no_baseline_is_unknown_with_reason() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    assessment = await assess_s003_baseline(
        InMemoryObjectStore(registry=registry),
        definition=None,
        inventory=None,
        surface=None,
        tenant_id=None,
        observed_at=NOW,
        source_id=new_id("src"),
    )

    assert assessment.baseline_declared is False
    assert assessment.aggregate() == {"passed": 0, "failed": 0, "unknown": 0}
    [reading] = baseline_factor_readings(assessment)
    assert reading.status == "unknown"
    assert reading.reason == NO_BASELINE_DECLARED


def test_u4_observations_derive_from_documents() -> None:
    inventory, with_listener = _documents()
    _, without_listener = _documents(listeners_raw="")

    with_value = derive_baseline_observations(inventory, with_listener)
    without_value = derive_baseline_observations(inventory, without_listener)

    assert with_value[3].model_dump() == {
        "state": "resolved",
        "claim_id": "C4",
        "value": True,
    }
    assert without_value[3].model_dump() == {
        "state": "resolved",
        "claim_id": "C4",
        "value": False,
    }


def test_u4_guards_survive_python_o() -> None:
    script = """
import asyncio
from datetime import UTC, datetime
from pydantic import ValidationError
from tools.s003_baseline import (
    PRIVILEGED_READ_REQUIRED,
    BaselineAssessment,
    BaselineClaim,
    BaselineDefinition,
    BaselineOutcome,
    assess_s003_baseline,
)
from tools.s003_estate import ServiceSurfaceDocument, UnitInventoryDocument
from aqelyn.assetconfig import ASSET_OBJECT_TYPE
from aqelyn.conventions import new_id
from aqelyn.objects import InMemoryObjectStore, ObjectTypeRegistry

now = datetime(2026, 7, 28, tzinfo=UTC)
definition = BaselineDefinition(
    claims=[
        BaselineClaim(claim_id=claim_id, comparator="eq", expected=True)
        for claim_id in ("C1", "C2", "C3", "C4", "C5")
    ]
)
inventory = UnitInventoryDocument(collected_at=now, units=[])
surface = ServiceSurfaceDocument(
    collected_at=now,
    listeners_raw="tcp LISTEN 0 128 0.0.0.0:443 0.0.0.0:*",
    firewall_raw=None,
    nginx_config=None,
    listeners=[],
    vhosts=[],
)
registry = ObjectTypeRegistry()
registry.register(ASSET_OBJECT_TYPE, 1, None)
assessment = asyncio.run(
    assess_s003_baseline(
        InMemoryObjectStore(registry=registry),
        definition=definition,
        inventory=inventory,
        surface=surface,
        tenant_id=None,
        observed_at=now,
        source_id=new_id("src"),
    )
)
if assessment.aggregate() != {"passed": 1, "failed": 0, "unknown": 4}:
    raise SystemExit("three-bucket result changed under optimization")
try:
    BaselineAssessment(
        baseline_declared=True,
        outcomes=[
            BaselineOutcome(
                claim_id="C1",
                status="unknown",
                unknown_class="privileged_read",
                reason=PRIVILEGED_READ_REQUIRED,
            )
        ],
    )
except ValidationError:
    pass
else:
    raise SystemExit("unknown bucket became invisible under optimization")
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
