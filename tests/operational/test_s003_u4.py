"""S-003 U4 acceptance tests for the owner-confirmed baseline."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from tools.first_run import RunReport, density_report
from tools.s003_baseline import (
    COLLECTION_SCOPE_INCOMPLETE,
    NO_BASELINE_DECLARED,
    PRIVILEGED_READ_DEPENDENTS,
    PRIVILEGED_READ_REQUIRED,
    BaselineAssessment,
    BaselineClaim,
    BaselineDefinition,
    BaselineOutcome,
    ClaimObservation,
    ResolvedObservation,
    S003BaselineError,
    UnresolvedObservation,
    assess_s003_baseline,
    baseline_factor_readings,
    s003_acg_config,
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


def _real_shape(*, evaluated_value: bool = True) -> list[ClaimObservation]:
    return [
        UnresolvedObservation(claim_id="C1", unknown_class="privileged_read"),
        UnresolvedObservation(claim_id="C2", unknown_class="collection_scope"),
        UnresolvedObservation(claim_id="C3", unknown_class="collection_scope"),
        ResolvedObservation(claim_id="C4", value=evaluated_value),
        UnresolvedObservation(claim_id="C5", unknown_class="privileged_read"),
    ]


async def _assess(
    store: ObjectStore,
    *,
    observations: Sequence[ClaimObservation] | None = None,
    tenant_id: str | None = None,
) -> BaselineAssessment:
    return await assess_s003_baseline(
        store,
        definition=_definition(),
        observations=_real_shape() if observations is None else observations,
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
        observations=_real_shape(evaluated_value=False),
    )

    assert assessment.aggregate() == {
        "passed": 0,
        "failed": 1,
        "unknown": 4,
    }


async def test_u4_resolution_change_clears_stale_observed_value() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    store = InMemoryObjectStore(registry=registry)
    first = await _assess(store)
    second_observations = [
        UnresolvedObservation(claim_id=claim_id, unknown_class="collection_scope")
        for claim_id in ("C1", "C2", "C3", "C4", "C5")
    ]
    second = await _assess(store, observations=second_observations)

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

    assert len(assessment.roadmap_dependencies) == 1
    [dependency] = assessment.roadmap_dependencies
    assert dependency.decision == "privileged_read"
    assert dependency.dependents == PRIVILEGED_READ_DEPENDENTS

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
    assert f"dependents={PRIVILEGED_READ_DEPENDENTS}" in rendered
    assert all(claim_id not in rendered for claim_id in ("C1", "C2", "C3", "C4", "C5"))


async def test_s003_no_baseline_is_unknown_with_reason() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    assessment = await assess_s003_baseline(
        InMemoryObjectStore(registry=registry),
        definition=None,
        observations=[],
        tenant_id=None,
        observed_at=NOW,
        source_id=new_id("src"),
    )

    assert assessment.baseline_declared is False
    assert assessment.aggregate() == {"passed": 0, "failed": 0, "unknown": 0}
    [reading] = baseline_factor_readings(assessment)
    assert reading.status == "unknown"
    assert reading.reason == NO_BASELINE_DECLARED


async def test_u4_observations_must_cover_every_claim() -> None:
    registry = ObjectTypeRegistry()
    registry.register(ASSET_OBJECT_TYPE, 1, None)
    store = InMemoryObjectStore(registry=registry)

    with pytest.raises(S003BaselineError, match="cover exactly C1-C5"):
        await assess_s003_baseline(
            store,
            definition=_definition(),
            observations=[
                ResolvedObservation(claim_id="C4", value=True),
            ],
            tenant_id=None,
            observed_at=NOW,
            source_id=new_id("src"),
        )


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
    ResolvedObservation,
    UnresolvedObservation,
    assess_s003_baseline,
)
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
observations = [
    UnresolvedObservation(claim_id="C1", unknown_class="privileged_read"),
    UnresolvedObservation(claim_id="C2", unknown_class="collection_scope"),
    UnresolvedObservation(claim_id="C3", unknown_class="collection_scope"),
    ResolvedObservation(claim_id="C4", value=True),
    UnresolvedObservation(claim_id="C5", unknown_class="privileged_read"),
]
registry = ObjectTypeRegistry()
registry.register(ASSET_OBJECT_TYPE, 1, None)
assessment = asyncio.run(
    assess_s003_baseline(
        InMemoryObjectStore(registry=registry),
        definition=definition,
        observations=observations,
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
