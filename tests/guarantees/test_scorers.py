"""GC4 composition-scorer discovery and unknown semantics."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aqelyn.conventions import new_id
from aqelyn.exposure import AssetRef
from aqelyn.ispm import PostureFactor
from aqelyn.ispm.scoring import posture_score_result
from aqelyn.risk.scoring import score_risk
from aqelyn.secrets import GovernanceFactor
from aqelyn.secrets.models import LEGACY_GOVERNANCE_FACTOR_NAMES
from aqelyn.secrets.scoring import governance_score_result
from aqelyn.vuln import CarriedScore, PriorityFactor, VulnBasis, VulnConfig, VulnerabilityRecord
from aqelyn.vuln import engine as vuln_engine
from guarantees.controls import unsafe_status_score
from guarantees.discovery import (
    GuaranteeViolation,
    ScorerObservation,
    assert_scorer_registry_complete,
    assert_unknown_less_favourable,
    discover_composition_scorer_packages,
)

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
SCORER_CASES: dict[str, Callable[[], ScorerObservation]] = {
    "ispm": lambda: _real_scorer_observations()[0],
    "secrets": lambda: _real_scorer_observations()[1],
    "vuln": lambda: _real_scorer_observations()[2],
}
SCORER_EXCLUSIONS = {
    "aqelyn.risk.scoring.score_risk": (
        "EA-0013 score_risk is a bounded max/impact combinator with no unknown lever; "
        "unknown belongs to its factor producers."
    )
}


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
    assert "no unknown lever" in reason
    assert "factor producers" in reason


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
from aqelyn.risk import SignalRef
from aqelyn.kernel import create_inmemory_runtime
from guarantees.controls import PermissiveSignal, RogueEngine, unsafe_status_score
from guarantees.discovery import (
    GuaranteeViolation,
    ScorerObservation,
    assert_no_direct_handler_invocations_in,
    assert_runtime_action_authority,
    assert_runtime_rejects_kind,
    assert_unknown_less_favourable,
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
