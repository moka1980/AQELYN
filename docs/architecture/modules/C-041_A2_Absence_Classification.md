# C-041 A2 - Mission Absence Classification

**Baseline:** `main @467e060`
**Contract:** [C-041_Task_Bundle.md](C-041_Task_Bundle.md)
**Audit:** [C-041_A1_Fold_Identity_Audit.md](C-041_A1_Fold_Identity_Audit.md)
**Scope:** classification only. This document contains no production repair.

## Decision

None of the five affected paths receives a declared "not applicable" value.
`MissionImpactResult` carries only `impacts` and `truncated`; it has no semantic
token by which EA-0007 can assert that mission weighting does not apply.

The affected paths therefore classify owner states as follows:

| Owner state | Classification | Required representation |
|---|---|---|
| mission owner is not configured | not supplied | `unknown`, cause `provider_unconfigured` |
| owner returns `truncated=True` | not supplied completely | `unknown`, cause `assessment_incomplete` |
| owner returns a complete result with no impacts | input not established | `unknown`, cause `input_missing` |
| owner returns an impact, including an explicit `impact_score=0.0` | supplied value | `known`, preserving the value and mission id |

An empty result is not treated as declared not-applicable. Doing so would invent
an assertion that the EA-0007 result type cannot make. An explicit zero remains
known so absence and a real zero cannot collapse.

For a fold over several affected objects, every object is part of the input
domain. Any truncated or empty result keeps the combined mission context
unknown, because an omitted object's unobserved impact could exceed the observed
maximum.

## Per-site Classification

| Site | Provider absent | Complete empty | Truncated | Explicit impact |
|---|---|---|---|---|
| `risk/engine.py:RiskIntelligenceEngine._mission_context` | `provider_unconfigured` | `input_missing` | `assessment_incomplete` | known |
| `risk/scoring.py:score_risk` | fail-safe typed unknown when no context is supplied | preserves typed unknown | preserves typed unknown | known |
| `exposure/engine.py:_mission_factors` | refused earlier by `score_exposure` | `input_missing` | `assessment_incomplete` | known |
| `secrets/scoring.py:_mission_factor` | caller must supply an EA-0007 result | `input_missing` | refused earlier by `compose_credential_governance` | known |
| `soc/correlate.py:_mission_context` | `provider_unconfigured` | `input_missing` | `assessment_incomplete` | known |

## Boundary Policy

EA-0013 owns the shared numeric boundary. A semantic mission-context type must
cross that boundary and must remain on the returned `Risk`; a bare
`float | None` would distinguish only two states and would lose the cause that
determines remediation.

`score_risk` uses a maximum, not a weighted denominator, for mission impact.
When mission context is unknown it cannot literally renormalize a denominator.
The narrow safe policy is:

1. do not insert a fabricated numeric mission value into the maximum;
2. retain the typed unknown context on the owner record; and
3. use the conservative upper bound for the numeric risk score so uncertainty
   cannot look like the known-safe end.

Outer scorers that do have a denominator, notably EA-0032 credential governance,
exclude the unknown EA-0013 owner factor and apply their existing coverage
penalty. SOC priority follows the same max-bound rule as EA-0013.

This keeps scoring and roadmap semantics separate: every unknown is
non-favourable for scoring, while its typed cause remains available to say what
would close it.

## A3 Inputs

- Add one typed EA-0013 mission context with structural known/unknown
  consistency and a fail-safe unknown default.
- Persist the context on `Risk`; carry it onto scored exposure and SOC incident
  records.
- Make all four owner adapters construct the context rather than a bare tuple.
- Make EA-0032's `owner_risk` factor unknown when mission context is unknown, so
  the governance denominator and coverage penalty do the work they already do
  for other missing facts.
- Preserve the positive control: an explicit EA-0007 impact of `0.0` remains
  known and does not receive an uncertainty penalty.

