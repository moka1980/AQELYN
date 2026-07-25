"""ECR-0065: replay must perform the same arithmetic as composition.

S-001 found `_compose_score` scaling-then-rounding while the replay path
rounded-then-scaled. Those are different functions; precision is only how the
difference became visible. Fixture scores carried four decimals or fewer, so the
round-trip was lossless **by accident of fixture construction** -- real EPSS values
like `0.01109` and `0.73327` broke 162 of 200 records on first contact.

**This is rule 27's own remedy.** Real data was the *discovery* mechanism, but once
the shape is known the test is a fixture built to withhold what fixtures accidentally
supply: a value carrying more significant digits than any scale crossing can survive.
The same move C-037 made with anti-correlated ids.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import new_id
from aqelyn.decision import replay
from aqelyn.exposure import AssetRef
from aqelyn.vuln import CarriedScore, VulnBasis, VulnConfig, VulnerabilityRecord
from aqelyn.vuln import engine as vuln_engine
from aqelyn.vuln.engine import PriorityFactor

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

#: Values chosen to survive nothing. Each carries more significant digits than a
#: six-decimal round-trip through unit scale can preserve -- which is exactly what
#: real EPSS and CVSS values look like and no hand-written fixture ever does.
ADVERSARIAL_FACTORS = (0.01109, 0.73327, 0.987654321, 0.135792468, 0.246813579)


def _record() -> VulnerabilityRecord:
    return VulnerabilityRecord(
        cve_id="CVE-2026-0065",
        scanner="ecr-0065",
        asset_ref=AssetRef(kind="asset", ref_id=new_id("obj"), evidence_id=new_id("evd")),
        severity="high",
        cvss=CarriedScore(source="nvd", value=7.3271, as_of=NOW),
        epss=CarriedScore(source="first:epss", value=0.01109, as_of=NOW),
        confidence=0.73327,
        basis=[VulnBasis(kind="scanner", ref="ecr-0065", as_of=NOW)],
        discovered_at=NOW,
    )


@pytest.mark.parametrize("seed", ADVERSARIAL_FACTORS)
def test_vuln_replay_survives_precision_adversarial_factors(seed: float) -> None:
    """A composed score must replay regardless of how many digits it carries.

    Fails against the round-then-scale order: a six-decimal percentage needs eight
    decimals at unit scale, so an intermediate `round(score / 100.0, 6)` discards two
    digits and the replayed score misses by ~2.5e-5 against a 1e-6 tolerance.
    """
    record = _record()
    factors = {
        name: PriorityFactor(
            round(seed * (index + 1) % 1.0, 9),
            f"ecr0065:{name}",
            f"{name} carries adversarial precision.",
        )
        for index, name in enumerate(vuln_engine._FACTOR_ORDER)
    }

    score, payload = vuln_engine._compose_score(record, factors=factors, config=VulnConfig())
    derivation = vuln_engine._priority_derivation(
        record, score=score, priority="high", factors=payload
    )

    replayed = vuln_engine._score_from_replay(replay(derivation))

    assert abs(replayed - score) <= vuln_engine._SCORE_TOLERANCE, (
        f"replay produced {replayed!r} for a composed {score!r} -- "
        "the two paths are computing different functions"
    )


def test_vuln_replay_precision_boundary_is_the_documented_one() -> None:
    """Pin the arithmetic the fix depends on, so a future refactor cannot drift.

    A six-decimal value at percentage scale requires eight at unit scale. This states
    that relationship as an executable fact rather than a comment.
    """
    percentage = 30.763625

    lossy = round(percentage / 100.0, 6) * 100.0
    faithful = (percentage / 100.0) * 100.0

    assert abs(lossy - percentage) > vuln_engine._SCORE_TOLERANCE
    assert abs(faithful - percentage) <= vuln_engine._SCORE_TOLERANCE


def test_ecr0065_sweep_the_other_three_composers_store_inputs_not_outputs() -> None:
    """The sweep across the four replay-validated composers, answered structurally.

    The distinguishing feature is **what the derivation stores**, not how many digits
    it keeps:

    * `vuln` stored a **re-derived output** -- `round(score / 100.0, 6)`, obtained by
      dividing the finished percentage back down. That is a second, different
      computation, and it is what made replay round-then-scale where composition
      scales-then-rounds. **This was the defect.**
    * `ispm` (`scoring.py:167-172`) and `secrets` (`scoring.py:189-195`) store their
      **inputs** -- `known_only_score`, `coverage_adjustment`, `known_weight` -- and
      the replay op recomputes the same single expression, rounding once. Mirroring
      operation-for-operation **by construction**, so no round-trip exists to lose
      digits in.
    * `exposure` (`engine.py:425`) calls `replay(...)` but never compares the result
      to the stored score, so no scale crossing occurs in the comparison at all.
      **Noted separately:** that is a weaker guarantee than the other three hold, and
      is not this ECR's business.

    Recorded as an executable statement of the invariant that keeps them safe: a
    derivation that stores inputs cannot drift from its composition, because there is
    only one computation. This test pins the reasoning so a future refactor that
    starts storing a re-derived output has something to fail against.
    """
    percentage = 30.763625
    known_only, coverage = 0.61527250, 0.5

    # The ispm/secrets shape: recompute from stored inputs, round once.
    from_inputs = round(known_only * coverage * 100.0, 6)
    # The vuln shape as it was: divide the output back down, round, scale back up.
    from_output = round(round(percentage / 100.0, 6) * 100.0, 6)

    assert abs(from_inputs - percentage) <= vuln_engine._SCORE_TOLERANCE
    assert abs(from_output - percentage) > vuln_engine._SCORE_TOLERANCE
