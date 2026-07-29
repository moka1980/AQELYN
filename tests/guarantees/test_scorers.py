"""GC4 composition-scorer discovery and unknown semantics."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import aqelyn.soc.correlate as soc_correlate
from aqelyn.assetconfig import InMemoryDriftSnapshotStore
from aqelyn.conventions import new_id
from aqelyn.conventions.errors import VulnConfigInvalid
from aqelyn.exposure import AssetRef, InMemoryExposureStore
from aqelyn.exposure import engine as exposure_engine
from aqelyn.findings import InMemoryFindingStore
from aqelyn.ispm import PostureFactor
from aqelyn.ispm import scoring as ispm_scoring
from aqelyn.ispm.scoring import posture_score_result
from aqelyn.mission import MissionImpactResult
from aqelyn.risk import (
    InMemoryRiskSnapshotStore,
    InMemoryRiskStore,
    Risk,
    RiskConfig,
    RiskIntelligenceEngine,
    RiskMissionContext,
    SignalRef,
)
from aqelyn.risk import engine as risk_engine
from aqelyn.risk import scoring as risk_scoring
from aqelyn.risk.scoring import mission_context_from_results, score_risk
from aqelyn.secrets import GovernanceFactor
from aqelyn.secrets import scoring as secrets_scoring
from aqelyn.secrets.models import LEGACY_GOVERNANCE_FACTOR_NAMES
from aqelyn.secrets.scoring import governance_score_result
from aqelyn.threat.parse import KevCatalog, KevExploitationProvider
from aqelyn.vuln import (
    VALID_FACTOR_UNKNOWN_CAUSES,
    CarriedScore,
    DriftSnapshotBlockingProvider,
    ExposureStoreReachabilityProvider,
    InMemoryVulnerabilityStore,
    PriorityFactor,
    ThreatExploitProvider,
    ThreatSignalFactorProvider,
    VulnBasis,
    VulnConfig,
    VulnerabilityIntelligenceEngine,
    VulnerabilityRecord,
)
from aqelyn.vuln import engine as vuln_engine
from guarantees.controls import unsafe_status_score
from guarantees.discovery import (
    GuaranteeViolation,
    ScorerObservation,
    assert_mission_score_path_registry_complete,
    assert_scorer_registry_complete,
    assert_unknown_less_favourable,
    assert_vulnerability_factor_provider_registry_complete,
    discover_composition_scorer_packages,
    discover_mission_score_paths,
    discover_vulnerability_factor_providers,
)

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
SCORER_CASES: dict[str, Callable[[], ScorerObservation]] = {
    "ispm": lambda: _real_scorer_observations()[0],
    "secrets": lambda: _real_scorer_observations()[1],
    "vuln": lambda: _real_scorer_observations()[2],
}
SCORER_EXCLUSIONS = {
    "aqelyn.risk.scoring.score_risk": (
        "EA-0013 score_risk consumes a typed RiskMissionContext rather than a local "
        "Factor model; the mission score-path guarantee covers that boundary."
    )
}


@dataclass(frozen=True)
class _FactorProviderCase:
    factor_name: str
    observe: Callable[[VulnerabilityRecord], Awaitable[PriorityFactor]]
    expected_status: str
    expected_cause: str | None


def test_gc_scorer_discovery_complete() -> None:
    assert discover_composition_scorer_packages() == frozenset(SCORER_CASES)
    assert_scorer_registry_complete(SCORER_CASES)


def test_gc_scorer_discovery_detects_new_package(tmp_path: Path) -> None:
    root = tmp_path / "aqelyn"
    package = root / "future_scorer"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Future scorer control."""\n', encoding="utf-8")
    (package / "scoring.py").write_text(
        "\n".join(
            (
                "from typing import Literal",
                'FactorStatus = Literal["known", "unknown"]',
                "class FutureFactor:",
                "    status: FactorStatus",
                "def score_future() -> float:",
                "    return 100.0",
                "",
            )
        ),
        encoding="utf-8",
    )

    assert discover_composition_scorer_packages(root) == frozenset(("future_scorer",))
    with pytest.raises(GuaranteeViolation, match=r"missing=\['future_scorer'\]"):
        assert_scorer_registry_complete({}, aqelyn_root=root)


def test_gc_scorer_unknown_not_favourable() -> None:
    observations = _real_scorer_observations()

    assert_unknown_less_favourable(observations)
    assert observations[0].unknown == 80.0
    assert observations[1].unknown < _credential_score("bad")
    assert observations[2].known_good < observations[2].unknown < _vulnerability_score("bad")


def test_gc_scorer_exclusion_documented() -> None:
    assert callable(score_risk)
    assert "risk" not in discover_composition_scorer_packages()
    [reason] = SCORER_EXCLUSIONS.values()
    assert "typed RiskMissionContext" in reason
    assert "mission score-path guarantee" in reason


def test_gc_negative_control_unguarded_scorer() -> None:
    observation = ScorerObservation(
        name="unsafe-control",
        known_good=unsafe_status_score("known_good"),
        unknown=unsafe_status_score("unknown"),
        orientation="higher_is_favourable",
    )

    assert observation.unknown == observation.known_good
    with pytest.raises(GuaranteeViolation, match="favourable known result"):
        assert_unknown_less_favourable((observation,))


def test_gc_guards_survive_optimized_python() -> None:
    script = """
import asyncio
import inspect
from pathlib import Path
from aqelyn.conventions.errors import VulnConfigInvalid
from aqelyn.risk import SignalRef
from aqelyn.kernel import create_inmemory_runtime
from aqelyn.vuln import PriorityFactor
from guarantees.controls import PermissiveSignal, RogueEngine, unsafe_status_score
from guarantees.discovery import (
    GuaranteeViolation,
    ScorerObservation,
    assert_no_direct_handler_invocations_in,
    assert_runtime_action_authority,
    assert_runtime_rejects_kind,
    assert_unknown_less_favourable,
)
from guarantees.test_scorers import (
    MISSION_SCORE_PATH_CASES,
    VULNERABILITY_FACTOR_PROVIDER_CASES,
    _assert_mission_score_path_case,
    _assert_provider_case,
)

assert_runtime_rejects_kind(
    SignalRef,
    {'kind': 'future_unregistered_kind', 'ref_id': 'finding:optimized', 'weight': 0.5},
)
try:
    assert_runtime_rejects_kind(PermissiveSignal, {'kind': 'future_unregistered_kind'})
except GuaranteeViolation:
    pass
else:
    raise SystemExit('optimized Python bypassed the SignalKind negative control')

try:
    PriorityFactor(
        0.0,
        'optimized:unknown',
        'Unknown factor without a cause.',
        status='unknown',
    )
except VulnConfigInvalid:
    pass
else:
    raise SystemExit('optimized Python bypassed the factor unknown-cause invariant')

for provider_name in sorted(VULNERABILITY_FACTOR_PROVIDER_CASES):
    asyncio.run(_assert_provider_case(provider_name))

for path in sorted(MISSION_SCORE_PATH_CASES):
    asyncio.run(_assert_mission_score_path_case(path))

bad = ScorerObservation(
    name='optimized-control',
    known_good=unsafe_status_score('known_good'),
    unknown=unsafe_status_score('unknown'),
    orientation='higher_is_favourable',
)
try:
    assert_unknown_less_favourable((bad,))
except GuaranteeViolation:
    pass
else:
    raise SystemExit('optimized Python bypassed the scorer negative control')

rogue = RogueEngine()
asyncio.run(rogue.execute_outside_workflow())
if rogue.handler.executions != 1:
    raise SystemExit('rogue negative control did not perform its forbidden action')
try:
    assert_runtime_action_authority(
        create_inmemory_runtime(),
        additional_roots=(rogue,),
    )
except GuaranteeViolation:
    pass
else:
    raise SystemExit('optimized Python bypassed alternate registry detection')

source = Path(inspect.getsourcefile(RogueEngine) or '')
try:
    assert_no_direct_handler_invocations_in((source,))
except GuaranteeViolation:
    pass
else:
    raise SystemExit('optimized Python bypassed direct handler detection')
"""
    environment = dict(os.environ)
    root = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(root / "src"),
            str(root / "tests"),
            environment.get("PYTHONPATH", ""),
        )
        if part
    )
    completed = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def _real_scorer_observations() -> tuple[ScorerObservation, ...]:
    ispm_good = _ispm_score("good")
    ispm_bad = _ispm_score("bad")
    ispm_unknown = _ispm_score("unknown")
    if ispm_unknown != ispm_bad:
        raise GuaranteeViolation("ISPM per-scorer unknown relation changed")

    credential_good = _credential_score("good")
    credential_bad = _credential_score("bad")
    credential_unknown = _credential_score("unknown")
    if not credential_unknown < credential_bad < credential_good:
        raise GuaranteeViolation("credential per-scorer unknown relation changed")

    vulnerability_safe = _vulnerability_score("safe")
    vulnerability_bad = _vulnerability_score("bad")
    vulnerability_unknown = _vulnerability_score("unknown")
    if not vulnerability_safe < vulnerability_unknown < vulnerability_bad:
        raise GuaranteeViolation("vulnerability per-scorer unknown relation changed")

    return (
        ScorerObservation(
            name="EA-0033 ISPM posture",
            known_good=ispm_good,
            unknown=ispm_unknown,
            orientation="higher_is_favourable",
        ),
        ScorerObservation(
            name="EA-0032 credential governance",
            known_good=credential_good,
            unknown=credential_unknown,
            orientation="higher_is_favourable",
        ),
        ScorerObservation(
            name="EA-0024 vulnerability priority",
            known_good=vulnerability_safe,
            unknown=vulnerability_unknown,
            orientation="lower_is_favourable",
        ),
    )


def _ispm_score(state: str) -> float:
    selected = {
        "good": PostureFactor(
            name="mfa",
            value=1.0,
            weight=0.2,
            status="known",
            source_ref={"owner": "GC-001"},
            reason="MFA is present.",
        ),
        "bad": PostureFactor(
            name="mfa",
            value=0.0,
            weight=0.2,
            status="known",
            source_ref={"owner": "GC-001"},
            reason="MFA is absent.",
        ),
        "unknown": PostureFactor(
            name="mfa",
            value=None,
            weight=0.2,
            status="unknown",
            source_ref={"owner": "GC-001"},
            reason="MFA was not assessed.",
        ),
    }[state]
    factors = [
        PostureFactor(
            name="owner",
            value=1.0,
            weight=0.8,
            status="known",
            source_ref={"owner": "GC-001"},
            reason="The remaining control is known-good.",
        ),
        selected,
    ]
    result = posture_score_result(
        [],
        {"factors": [factor.model_dump(mode="json") for factor in factors]},
    )
    return float(result["score"])


def _credential_score(state: str) -> float:
    weight = 1.0 / len(LEGACY_GOVERNANCE_FACTOR_NAMES)
    factors: list[GovernanceFactor] = []
    for name in LEGACY_GOVERNANCE_FACTOR_NAMES:
        selected = name == "ownership"
        factors.append(
            GovernanceFactor(
                name=name,
                rating=(
                    None
                    if selected and state == "unknown"
                    else 0.0
                    if selected and state == "bad"
                    else 1.0
                ),
                weight=weight,
                status="unknown" if selected and state == "unknown" else "known",
                source_ref={"owner": "GC-001"},
                reason=f"{name} control for the central scorer check.",
            )
        )
    result = governance_score_result(
        [],
        {
            "factors": [factor.model_dump(mode="json") for factor in factors],
            "active_critical_exposure_ids": [],
        },
    )
    return float(result["score"])


def _vulnerability_score(state: str) -> float:
    factors = {
        name: PriorityFactor(
            0.8,
            f"gc:{name}",
            f"{name} is known for the central scorer check.",
        )
        for name in ("cvss", "epss", "threat", "exposure", "mission", "baseline", "trust")
    }
    factors["exposure"] = PriorityFactor(
        0.0 if state != "bad" else 1.0,
        "gc:exposure",
        "Reachability is varied by the central scorer check.",
        status="unknown" if state == "unknown" else "known",
        unknown_cause="input_missing" if state == "unknown" else None,
    )
    score, _ = vuln_engine._compose_score(
        _vulnerability(),
        factors=factors,
        config=VulnConfig(),
    )
    return score


def _vulnerability() -> VulnerabilityRecord:
    return VulnerabilityRecord(
        cve_id="CVE-2099-0057",
        scanner="gc-001",
        asset_ref=AssetRef(kind="asset", ref_id=new_id("obj"), evidence_id=new_id("evd")),
        severity="high",
        cvss=CarriedScore(
            source="gc-001",
            value=8.0,
            vector="CVSS:3.1/GC-001",
            as_of=NOW,
        ),
        epss=CarriedScore(source="gc-001", value=0.8, as_of=NOW),
        confidence=0.8,
        basis=[
            VulnBasis(
                kind="scanner",
                ref="gc-001",
                as_of=NOW,
                evidence_id=new_id("evd"),
            )
        ],
        discovered_at=NOW,
    )


def test_gc_scorer_absent_cvss_is_unknown_not_favourable() -> None:
    """ECR-0064 Gap 1: an absent CVSS must not score better than a known one.

    GC-001 AC-3 sweep. `VulnerabilityRecord.cvss` became optional because 46% of real
    scanner matches carry none. The hazard is that absence takes the most favourable
    reading -- a zero claiming the vulnerability scores nothing. The engine's factor
    must therefore be `status="unknown"`, which ECR-0040 excludes from the denominator
    rather than scoring as benign.
    """
    absent = vuln_engine._cvss_factor(_vulnerability_without_cvss())
    present = vuln_engine._cvss_factor(_vulnerability())

    assert absent.status == "unknown"
    assert present.status == "known"
    assert "not zero" in absent.reason

    observation = ScorerObservation(
        name="vuln-cvss-absent",
        known_good=_vulnerability_score_with_cvss(present=True),
        unknown=_vulnerability_score_with_cvss(present=False),
        orientation="lower_is_favourable",
    )
    assert_unknown_less_favourable((observation,))


def _vulnerability_without_cvss() -> VulnerabilityRecord:
    return _vulnerability().model_copy(update={"cvss": None}, deep=True)


def _vulnerability_score_with_cvss(*, present: bool) -> float:
    """Score varying only the CVSS factor, mirroring the shipped exposure check.

    `known_good` is a **known benign** CVSS, not a known severe one -- comparing
    absence against a high score would prove only that high scores are high. The
    guarantee is that not knowing is never better than knowing it is fine.
    """
    record = _vulnerability() if present else _vulnerability_without_cvss()
    factors = {
        name: PriorityFactor(0.8, f"gc:{name}", f"{name} is known for the CVSS check.")
        for name in ("epss", "threat", "exposure", "mission", "baseline", "trust")
    }
    factors["cvss"] = (
        PriorityFactor(0.0, "gc:cvss", "CVSS is known and benign for the check.")
        if present
        else vuln_engine._cvss_factor(record)
    )
    score, _ = vuln_engine._compose_score(record, factors=factors, config=VulnConfig())
    return score


def test_gc_every_factor_reports_unknown_when_unsupplied() -> None:
    """AC-3 widened: per-FACTOR, not per-scorer (ECR-0066).

    As originally specified, AC-3 asserted each composition scorer ships *a case*
    proving unknown is not favourable -- **per scorer, one case**. A seven-factor
    scorer with one correct factor passed, so the guarantee written to catch this
    family was capable of passing the exact defect it exists to prevent: `exposure`
    handled unknown correctly while `threat`, `baseline`, `mission` and `epss`
    defaulted to `known` three lines away.

    This drives an engine with **no providers wired at all** and asserts that every
    factor whose input was not supplied reports `status="unknown"`. A factor that
    defaults to `known` casts a confident vote nobody supplied, and ECR-0040 then
    counts it in the denominator as known-benign.
    """
    engine = VulnerabilityIntelligenceEngine(InMemoryVulnerabilityStore(mode="local"))
    record = _vulnerability().model_copy(update={"cvss": None, "epss": None}, deep=True)

    factors = asyncio.run(engine._factors_for(record))

    unsupplied = {"cvss", "epss", "threat", "exposure", "mission", "baseline"}
    confident = sorted(name for name in unsupplied if factors[name].status != "unknown")
    assert confident == [], (
        f"factors reporting 'known' with no input supplied: {confident} -- "
        "each casts a favourable vote nobody supplied (ECR-0040, ECR-0066)"
    )
    # `trust` is excluded deliberately: it always has a provider
    # (`_StoredScannerTrustProvider`), so its `known` is earned rather than defaulted.
    assert factors["trust"].status == "known"
    assert {name: factors[name].unknown_cause for name in sorted(unsupplied)} == {
        "baseline": "provider_unconfigured",
        "cvss": "input_missing",
        "epss": "input_missing",
        "exposure": "provider_unconfigured",
        "mission": "provider_unconfigured",
        "threat": "provider_unconfigured",
    }


def test_gc_negative_control_factor_defaulting_to_known() -> None:
    """Rule 24: the widened AC-3 must fail against the defect it was written for.

    A factor built without an explicit `status` defaults to `known`. That is exactly
    what `threat`, `baseline`, `mission` and `epss` did, and a per-scorer AC-3 passed
    it. Constructing one here proves the per-factor check can see it.
    """
    defaulted = PriorityFactor(0.0, "control:unavailable", "No provider supplied.")

    assert defaulted.status == "known", "the control no longer models the defect"

    explicit = PriorityFactor(
        0.0,
        "control:unavailable",
        "No provider supplied.",
        status="unknown",
        unknown_cause="provider_unconfigured",
    )
    assert explicit.status == "unknown"
    # mypy narrows both literals, so the inequality is asserted on the values rather
    # than the types -- the point is that the default differs from the explicit form.
    assert str(defaulted.status) != str(explicit.status)


def test_gc_priority_factor_unknown_cause_is_structural() -> None:
    assert {
        "provider_unconfigured",
        "input_missing",
        "assessment_incomplete",
        "source_cannot_assert",
    } == VALID_FACTOR_UNKNOWN_CAUSES

    with pytest.raises(VulnConfigInvalid, match="requires a registered unknown_cause"):
        PriorityFactor(
            0.0,
            "control:missing-cause",
            "The factor is unknown but its cause was omitted.",
            status="unknown",
        )
    with pytest.raises(VulnConfigInvalid, match="known priority factor"):
        PriorityFactor(
            0.0,
            "control:known",
            "The factor is known and must not carry an unknown cause.",
            unknown_cause="input_missing",
        )


class _EmptyMissionProvider:
    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        _ = object_id
        return MissionImpactResult()


@dataclass(frozen=True)
class _MissionScorePathCase:
    check: Callable[[], Awaitable[None]]


MISSION_SCORE_PATH_CASES: dict[str, _MissionScorePathCase] = {
    "aqelyn.exposure.engine._mission_factors": _MissionScorePathCase(
        lambda: _check_context_adapter(exposure_engine._mission_factors)
    ),
    "aqelyn.ispm.scoring._mission_factor": _MissionScorePathCase(
        lambda: _check_context_adapter(ispm_scoring._mission_factor)
    ),
    "aqelyn.risk.engine.RiskIntelligenceEngine._mission_context": _MissionScorePathCase(
        lambda: _check_risk_engine_mission_path()
    ),
    "aqelyn.risk.scoring.score_risk": _MissionScorePathCase(
        lambda: _check_risk_score_mission_boundary()
    ),
    "aqelyn.secrets.scoring._mission_factor": _MissionScorePathCase(
        lambda: _check_context_adapter(secrets_scoring._mission_factor)
    ),
    "aqelyn.soc.correlate._mission_context": _MissionScorePathCase(
        lambda: _check_soc_mission_path()
    ),
    "aqelyn.vuln.engine.VulnerabilityIntelligenceEngine._mission_factor": (
        _MissionScorePathCase(lambda: _check_vulnerability_mission_path())
    ),
}
MISSION_SCORE_PATH_EXCLUSIONS = {
    "aqelyn.detection.scoring._mission_factor": (
        "EA-0017 declares MissionConfig.default_tier for an empty owner result; it "
        "does not use the fold identity and records the configured policy."
    ),
    "aqelyn.detection.service.ThreatDetectionService._check_mission_engine": (
        "Service health probes owner availability and emits no score or priority."
    ),
    "aqelyn.exposure.engine.KnownDataExposureEngine.score_exposure": (
        "The owner path delegates its conversion to the separately discovered and "
        "behaviorally checked exposure.engine._mission_factors adapter."
    ),
    "aqelyn.exposure.service.ExposureManagementService._check_mission_provider": (
        "Service health probes owner availability and emits no score or priority."
    ),
    "aqelyn.ispm.engine.ISPMEngine.score_identity": (
        "The owner path delegates its conversion to the separately discovered and "
        "behaviorally checked ispm.scoring._mission_factor adapter."
    ),
    "aqelyn.mission.engine.MissionEngine.assess_finding_impact": (
        "EA-0007 is the mission owner: this path returns typed MissionImpactResult "
        "records and does not convert absence into a downstream score."
    ),
    "aqelyn.risk.service.RiskIntelligenceService._check_mission_engine": (
        "Service health probes owner availability and emits no score or priority."
    ),
    "aqelyn.secrets.engine.SecretsIntelligenceEngine._score_asset": (
        "The owner path delegates its conversion to the separately discovered and "
        "behaviorally checked secrets.scoring._mission_factor adapter."
    ),
    "aqelyn.soc.service.SecurityOperationsService._check_mission_engine": (
        "Service health probes owner availability and emits no score or priority."
    ),
    "aqelyn.threat.engine.ThreatFusionEngine._severity_score": (
        "EA-0014 uses 1.0, the conservative maximum severity multiplier, when no "
        "mission impact is supplied; absence is not favourable in this orientation."
    ),
    "aqelyn.threat.service.ThreatFusionService._check_mission_engine": (
        "Service health probes owner availability and emits no score or priority."
    ),
    "aqelyn.vuln.service.VulnerabilityIntelligenceService._check_mission_provider": (
        "Service health probes owner availability and emits no score or priority."
    ),
}


def test_gc_mission_score_path_discovery_complete() -> None:
    assert_mission_score_path_registry_complete(
        MISSION_SCORE_PATH_CASES,
        MISSION_SCORE_PATH_EXCLUSIONS,
    )


def test_gc_mission_score_path_discovery_detects_new_path(tmp_path: Path) -> None:
    root = tmp_path / "aqelyn"
    package = root / "future_score"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Future mission scorer control."""\n', encoding="utf-8")
    (package / "scoring.py").write_text(
        "\n".join(
            (
                "async def score_future(provider: object) -> float:",
                "    result = await provider.mission_impact('obj_future')",
                "    return max((item.impact_score for item in result.impacts), default=0.0)",
                "",
            )
        ),
        encoding="utf-8",
    )

    discovered = discover_mission_score_paths(root)

    assert discovered == frozenset(("aqelyn.future_score.scoring.score_future",))
    with pytest.raises(GuaranteeViolation, match="score_future"):
        assert_mission_score_path_registry_complete({}, {}, aqelyn_root=root)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(MISSION_SCORE_PATH_CASES))
async def test_gc_discovered_mission_score_path_state(path: str) -> None:
    await _assert_mission_score_path_case(path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "aqelyn.exposure.engine._mission_factors",
        "aqelyn.risk.engine.RiskIntelligenceEngine._mission_context",
        "aqelyn.risk.scoring.score_risk",
        "aqelyn.secrets.scoring._mission_factor",
        "aqelyn.soc.correlate._mission_context",
    ],
)
async def test_gc_a3_reversion_turns_central_guard_red(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_a3_reversion(path, monkeypatch)

    with pytest.raises(GuaranteeViolation, match="mission"):
        await _assert_mission_score_path_case(path)


async def _assert_mission_score_path_case(path: str) -> None:
    case = MISSION_SCORE_PATH_CASES.get(path)
    if case is None:
        raise GuaranteeViolation(f"no behavioral mission score-path case for {path}")
    await case.check()


async def _check_context_adapter(
    adapter: Callable[[MissionImpactResult], RiskMissionContext],
) -> None:
    _require_unknown_mission_context(
        adapter(MissionImpactResult()),
        path=f"{adapter.__module__}.{adapter.__name__}",
    )


async def _check_risk_engine_mission_path() -> None:
    engine = RiskIntelligenceEngine(
        InMemoryFindingStore(),
        InMemoryRiskStore(),
        InMemoryRiskSnapshotStore(),
        mission_engine=_EmptyMissionProvider(),
    )
    scored = await engine.score(_mission_guard_risk())
    _require_unknown_mission_context(
        scored.mission_context,
        path="aqelyn.risk.engine.RiskIntelligenceEngine._mission_context",
    )
    if "mission_factor" in scored.factors:
        raise GuaranteeViolation("risk mission absence cast a numeric mission vote")


async def _check_risk_score_mission_boundary() -> None:
    risk = _mission_guard_risk()
    unknown = risk_scoring.score_risk(
        risk,
        mission_context=mission_context_from_results([MissionImpactResult()]),
    )
    known_zero = risk_scoring.score_risk(
        risk,
        mission_context=_known_zero_mission_context(),
    )
    _require_unknown_mission_context(
        unknown.mission_context,
        path="aqelyn.risk.scoring.score_risk",
    )
    if "mission_factor" in unknown.factors:
        raise GuaranteeViolation("score_risk inserted an unknown mission factor")
    if unknown.score <= known_zero.score:
        raise GuaranteeViolation(
            "score_risk made missing mission no less favourable than explicit zero"
        )


async def _check_soc_mission_path() -> None:
    context = await soc_correlate._mission_context(
        [new_id("obj")],
        _EmptyMissionProvider(),
    )
    _require_unknown_mission_context(
        context,
        path="aqelyn.soc.correlate._mission_context",
    )


async def _check_vulnerability_mission_path() -> None:
    engine = VulnerabilityIntelligenceEngine(
        InMemoryVulnerabilityStore(mode="local"),
        mission_provider=_EmptyMissionProvider(),
    )
    factor = await engine._mission_factor(_vulnerability())
    if factor.status != "unknown" or factor.unknown_cause != "input_missing":
        raise GuaranteeViolation(
            "vulnerability mission path failed to retain input_missing as unknown"
        )
    factors = _known_factors()
    factors["mission"] = factor
    _, payload = vuln_engine._compose_score(
        _vulnerability(),
        factors=factors,
        config=VulnConfig(),
    )
    if payload["mission"]["weight"] != 0.0:
        raise GuaranteeViolation("vulnerability unknown mission received a score weight")


def _require_unknown_mission_context(
    context: RiskMissionContext,
    *,
    path: str,
) -> None:
    if (
        context.status != "unknown"
        or context.unknown_cause != "input_missing"
        or context.factor is not None
        or context.top_mission_id is not None
    ):
        raise GuaranteeViolation(
            f"{path} erased missing mission input: "
            f"status={context.status!r}, cause={context.unknown_cause!r}, "
            f"factor={context.factor!r}, top_mission_id={context.top_mission_id!r}"
        )


def _mission_guard_risk() -> Risk:
    return Risk(
        id="risk-gc-mission",
        correlation_key="gc:mission",
        title="Central mission-boundary control",
        category="guarantee",
        likelihood=0.0,
        impact=0.2,
        score=0.0,
        band="within_appetite",
        signals=[
            SignalRef(
                kind="finding",
                ref_id=new_id("fnd"),
                weight=0.6,
            )
        ],
        affected_object_ids=[new_id("obj")],
        reason="Unscored central mission-boundary control.",
        first_seen_at=NOW,
        last_scored_at=NOW,
    )


def _known_zero_mission_context() -> RiskMissionContext:
    return RiskMissionContext(
        status="known",
        factor=0.0,
        top_mission_id=new_id("obj"),
        reason="Central negative control explicitly assessed zero mission impact.",
    )


def _apply_a3_reversion(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if path == "aqelyn.risk.scoring.score_risk":
        original = risk_scoring.score_risk

        def unsafe_score_risk(
            risk: Risk,
            *,
            config: RiskConfig | None = None,
            mission_context: RiskMissionContext | None = None,
        ) -> Risk:
            _ = mission_context
            return original(
                risk,
                config=config,
                mission_context=_known_zero_mission_context(),
            )

        monkeypatch.setattr(risk_scoring, "score_risk", unsafe_score_risk)
        return
    targets = {
        "aqelyn.exposure.engine._mission_factors": exposure_engine,
        "aqelyn.risk.engine.RiskIntelligenceEngine._mission_context": risk_engine,
        "aqelyn.secrets.scoring._mission_factor": secrets_scoring,
        "aqelyn.soc.correlate._mission_context": soc_correlate,
    }
    module = targets.get(path)
    if module is None:
        raise GuaranteeViolation(f"no A3 reversion control registered for {path}")
    monkeypatch.setattr(module, "mission_context_from_results", _unsafe_mission_context)


def _unsafe_mission_context(
    results: object,
) -> RiskMissionContext:
    _ = results
    return _known_zero_mission_context()


class _MalformedThreatProvider:
    async def exploitation_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        _ = vulnerability
        return cast(PriorityFactor, None)


class _TimeoutThreatProvider:
    async def exploitation_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        _ = vulnerability
        raise TimeoutError("threat provider timed out")


async def _observe_kev_absence(record: VulnerabilityRecord) -> PriorityFactor:
    catalog = KevCatalog(
        catalog_version="gc-empty",
        date_released="2026-07-26",
        entries={},
    )
    return cast(
        PriorityFactor,
        await KevExploitationProvider(catalog).exploitation_factor(record),
    )


async def _observe_threat_signal_absence(record: VulnerabilityRecord) -> PriorityFactor:
    return await ThreatSignalFactorProvider(object()).exploitation_factor(record)


async def _observe_exposure_absence(record: VulnerabilityRecord) -> PriorityFactor:
    return await ExposureStoreReachabilityProvider(
        InMemoryExposureStore(mode="local")
    ).reachability_factor(record)


async def _observe_baseline_absence(record: VulnerabilityRecord) -> PriorityFactor:
    return await DriftSnapshotBlockingProvider(InMemoryDriftSnapshotStore()).blocking_factor(record)


async def _observe_stored_trust(record: VulnerabilityRecord) -> PriorityFactor:
    return await vuln_engine._StoredScannerTrustProvider().scanner_trust(record)


VULNERABILITY_FACTOR_PROVIDER_CASES = {
    "aqelyn.threat.parse.KevExploitationProvider.exploitation_factor": _FactorProviderCase(
        "threat",
        _observe_kev_absence,
        "unknown",
        "source_cannot_assert",
    ),
    "aqelyn.vuln.engine._StoredScannerTrustProvider.scanner_trust": _FactorProviderCase(
        "trust",
        _observe_stored_trust,
        "known",
        None,
    ),
    "aqelyn.vuln.service.DriftSnapshotBlockingProvider.blocking_factor": _FactorProviderCase(
        "baseline",
        _observe_baseline_absence,
        "unknown",
        "input_missing",
    ),
    "aqelyn.vuln.service.ExposureStoreReachabilityProvider.reachability_factor": (
        _FactorProviderCase(
            "exposure",
            _observe_exposure_absence,
            "unknown",
            "input_missing",
        )
    ),
    "aqelyn.vuln.service.ThreatSignalFactorProvider.exploitation_factor": _FactorProviderCase(
        "threat",
        _observe_threat_signal_absence,
        "unknown",
        "source_cannot_assert",
    ),
}
VULNERABILITY_FACTOR_PROVIDER_EXCLUSIONS = {
    "VulnerabilityMissionProvider": (
        "mission_impact is a shared owner API returning MissionImpactResult, not a "
        "PriorityFactor. EA-0024 adapts it internally, so its empty result is covered "
        "by test_gc_wired_mission_absence_is_unknown_and_excluded."
    )
}


def test_gc_vulnerability_factor_provider_discovery_complete() -> None:
    assert discover_vulnerability_factor_providers() == frozenset(
        VULNERABILITY_FACTOR_PROVIDER_CASES
    )
    assert_vulnerability_factor_provider_registry_complete(VULNERABILITY_FACTOR_PROVIDER_CASES)
    [mission_reason] = VULNERABILITY_FACTOR_PROVIDER_EXCLUSIONS.values()
    assert "shared owner API" in mission_reason
    assert "covered" in mission_reason


def test_gc_vulnerability_factor_provider_discovery_detects_new_provider(
    tmp_path: Path,
) -> None:
    root = tmp_path / "aqelyn"
    package = root / "future_threat"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Future provider control."""\n', encoding="utf-8")
    (package / "provider.py").write_text(
        "\n".join(
            (
                "from aqelyn.vuln import PriorityFactor",
                "class FutureThreatProvider:",
                "    async def exploitation_factor(self, vulnerability: object) -> PriorityFactor:",
                "        return PriorityFactor(0.0, 'future:none', 'No matching signal.')",
                "",
            )
        ),
        encoding="utf-8",
    )

    discovered = discover_vulnerability_factor_providers(root)

    assert discovered == frozenset(
        ("aqelyn.future_threat.provider.FutureThreatProvider.exploitation_factor",)
    )
    with pytest.raises(GuaranteeViolation, match="FutureThreatProvider"):
        assert_vulnerability_factor_provider_registry_complete({}, aqelyn_root=root)


def _known_factors() -> dict[str, PriorityFactor]:
    return {
        name: PriorityFactor(
            0.8,
            f"gc:{name}",
            f"{name} is known for the provider-state check.",
        )
        for name in ("cvss", "epss", "threat", "exposure", "mission", "baseline", "trust")
    }


async def _assert_provider_case(provider_name: str) -> PriorityFactor:
    case = VULNERABILITY_FACTOR_PROVIDER_CASES[provider_name]
    record = _vulnerability()
    factor = await case.observe(record)
    if factor.status != case.expected_status or factor.unknown_cause != case.expected_cause:
        raise GuaranteeViolation(
            f"{provider_name} produced status={factor.status!r}, "
            f"unknown_cause={factor.unknown_cause!r}; expected "
            f"status={case.expected_status!r}, unknown_cause={case.expected_cause!r}"
        )
    factors = _known_factors()
    factors[case.factor_name] = factor
    _, payload = vuln_engine._compose_score(record, factors=factors, config=VulnConfig())
    normalized_weight = cast(float, payload[case.factor_name]["weight"])
    if factor.status == "unknown" and normalized_weight != 0.0:
        raise GuaranteeViolation(
            f"{provider_name} unknown factor received normalized weight {normalized_weight}"
        )
    if factor.status == "known" and normalized_weight <= 0.0:
        raise GuaranteeViolation(
            f"{provider_name} earned known factor received no normalized weight"
        )
    return factor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_name",
    sorted(VULNERABILITY_FACTOR_PROVIDER_CASES),
)
async def test_gc_discovered_vulnerability_factor_provider_state(
    provider_name: str,
) -> None:
    await _assert_provider_case(provider_name)


@pytest.mark.asyncio
async def test_gc_wired_mission_absence_is_unknown_and_excluded() -> None:
    engine = VulnerabilityIntelligenceEngine(
        InMemoryVulnerabilityStore(mode="local"),
        mission_provider=_EmptyMissionProvider(),
    )
    factors = await engine._factors_for(_vulnerability())
    mission = factors["mission"]

    assert mission.status == "unknown"
    assert mission.unknown_cause == "input_missing"
    _, payload = vuln_engine._compose_score(
        _vulnerability(),
        factors=factors,
        config=VulnConfig(),
    )
    assert payload["mission"]["weight"] == 0.0


@pytest.mark.asyncio
async def test_gc_negative_control_discovered_provider_defaulting_to_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def favourable_kev_absence(
        self: KevExploitationProvider,
        vulnerability: object,
    ) -> PriorityFactor:
        _ = (self, vulnerability)
        return PriorityFactor(
            0.0,
            "control:kev:none",
            "Incorrectly claims KEV absence is known-safe.",
        )

    monkeypatch.setattr(KevExploitationProvider, "exploitation_factor", favourable_kev_absence)
    provider_name = "aqelyn.threat.parse.KevExploitationProvider.exploitation_factor"

    with pytest.raises(GuaranteeViolation, match="expected status='unknown'"):
        await _assert_provider_case(provider_name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "error"),
    [
        (_MalformedThreatProvider(), VulnConfigInvalid),
        (_TimeoutThreatProvider(), TimeoutError),
    ],
    ids=["malformed", "timeout"],
)
async def test_gc_wired_provider_failure_emits_no_factor(
    provider: object,
    error: type[Exception],
) -> None:
    engine = VulnerabilityIntelligenceEngine(
        InMemoryVulnerabilityStore(mode="local"),
        threat_provider=cast(ThreatExploitProvider, provider),
    )

    with pytest.raises(error):
        await engine._factors_for(_vulnerability())
