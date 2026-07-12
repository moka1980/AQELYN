# EA-0006 — Trust Engine — Implementation Specification

**Realizes:** EA-0006 (supersedes the placeholder `archive/EA-0006/EA-0006_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0004 (EvidenceRecord, SourceRef), EA-0001 (registers as an `AQService`)
**Consumed by:** the Finding pipeline (compute `confidence` for findings and for object/relationship assertions), EA-0007 Mission (prioritization inputs), EA-0009 Policy (confidence-gated decisions), UI (show why a score is what it is)
**Status:** Accepted
**Build milestone:** C-003 (see `C-003_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 1. Purpose

The Trust Engine answers one question, and answers it the same way every time:
**how confident should AQELYN be in a claim, and why?** It turns evidence and
the reliability of where that evidence came from into a single, bounded,
**explainable** confidence score — the number that populates the `confidence`
fields already defined on evidence, objects, relationships, and findings.

This is the concrete machinery behind the Charter's "Evidence Before Opinion":
a score is never a bare number, it is a number with its inputs, its method, and
a plain-language reason attached.

## 2. Scope

**In scope:** a configurable source-reliability registry (with provenance),
per-evidence weighting, deterministic confidence aggregation, score→level
mapping, threshold-based decision support, explanation output, and the
`TrustEngine` interface + `TrustEngineService` (`AQService`).

**Out of scope:** collecting evidence (EA-0004 and connectors), deciding *what*
to do with a score (the Finding pipeline / EA-0009 Policy), and any learned/ML
scoring (a later engine may extend this; the model here is transparent by
design). The Trust Engine **never mutates** stored objects, evidence, or
findings — it computes and returns (D6).

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Source reliability** | A configured weight in `[0,1]` for how trustworthy a source/method is (e.g. a vendor API vs a heuristic guess). |
| **Evidence weight** | The contribution of one evidence record to a claim, derived from reliability × type × recency × the collector's own confidence. |
| **Confidence score** | The aggregate `[0,1]` result for a claim, combined from its evidence weights. |
| **Trust level** | A plain-language band (`low`/`medium`/`high`) mapped from the score for non-experts. |
| **Assessment** | The full explainable result: score, level, per-evidence contributions, method, reason. |
| **Decision** | A threshold-based recommendation derived from an assessment (e.g. "corroborate before acting"). |

## 4. Design decisions

- **D1 — Deterministic and pure.** `assess()` is a pure function of its inputs
  and the current config: identical inputs → byte-identical result. No
  randomness, no hidden state, no I/O in the computation. Required for audit and
  reproducibility.
- **D2 — Source reliability is explicit, configured, and provenanced.** Weights
  live in a registry, not as magic numbers in code. Each entry carries who set
  it, when, and why. Unknown sources fall back to a documented default, flagged.
- **D3 — Aggregation is a documented, bounded, monotonic function.** Confidence
  combines evidence weights via **noisy-OR**:
  `C = 1 − Π_i (1 − w_i)`, with each `w_i ∈ [0,1]`. Properties that matter and
  are guaranteed: result stays in `[0,1]`; adding corroborating evidence never
  *decreases* the score (monotonic); order-independent. The formula is part of
  the output, not a black box.
- **D4 — Every assessment is explainable.** It returns each evidence
  contribution (with its reliability, type weight, recency factor), the method
  name/version, the final score, the level, and a plain-language reason
  ("high confidence: three independent sources, all recent"). Charter "how
  AQELYN knows" for confidence.
- **D5 — Score→level via configurable, ordered thresholds.** Default:
  `< 0.34 → low`, `< 0.67 → medium`, else `high`. Deterministic and readable.
- **D6 — Pure analysis, no side effects.** The engine returns assessments;
  callers decide what to persist. Mirrors the Knowledge Graph's read-side stance.
- **D7 — Recency decay is documented and configurable.** Older evidence weighs
  less via exponential decay with a configurable half-life (default 90 days);
  `recency = 0.5 ** (age_days / half_life_days)`, clamped to `[floor, 1]`
  (default floor `0.1`, so old-but-real evidence never drops to zero).
- **D8 — Registered as an `AQService`** (EA-0001) with health.

## 5. Types

```
SourceReliability = { key: str,            # source_id, or "method:<name>", or "*" default
                      weight: float,       # [0,1]
                      rationale: str, set_by: ActorRef, set_at: datetime, version: int }

EvidenceContribution = { evidence_id: str, weight: float,
                         source_reliability: float, type_weight: float,
                         recency_factor: float, collector_confidence: float,
                         age_days: float }

TrustAssessment = { subject_ref: str,      # what the score is about (obj_/fnd_/free string)
                    score: float,          # [0,1]
                    level: str,            # low | medium | high (configurable)
                    method: str,           # e.g. "noisy_or/v1"
                    contributions: list[EvidenceContribution],
                    reason: str,           # plain language (D4)
                    no_evidence: bool,     # true when there was nothing to assess
                    computed_at: datetime }

Decision = { decision: str, score: float, threshold: float, rationale: str }

TrustConfig = { type_weights: dict[str, float],   # per evidence_type, default 1.0
                thresholds: { low: float, high: float },
                half_life_days: float, recency_floor: float,
                default_reliability: float }
```

Reuses `ActorRef` (CONVENTIONS §6) and reads `EvidenceRecord` fields from
EA-0004 (`evidence_type`, `source_id`, `method`, `collected_at`, `confidence`).

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class SourceReliabilityRegistry(Protocol):
    async def get(self, *, source_id: str | None = None,
                  method: str | None = None) -> SourceReliability: ...   # resolves to default if unset
    async def set(self, entry: SourceReliability) -> SourceReliability: ...
    async def list(self) -> list[SourceReliability]: ...

class TrustEngine(Protocol):
    async def weigh_evidence(self, evidence: "EvidenceRecord",
                             *, now: datetime | None = None) -> EvidenceContribution: ...
    async def assess(self, subject_ref: str, evidence: Sequence["EvidenceRecord"],
                     *, now: datetime | None = None) -> TrustAssessment: ...   # core (D3)
    async def decide(self, assessment: TrustAssessment, *,
                     threshold: float, action: str) -> Decision: ...
    def explain(self, assessment: TrustAssessment) -> list[dict]: ...          # per-contribution detail
```

`TrustEngineService` wraps a `TrustEngine` + registry as an `AQService`
(name `"trust_engine"`, health reflects config validity + registry
availability).

## 7. Computation (the reference model, `noisy_or/v1`)

For each evidence record `e`:

```
reliability   = registry.get(e.source_id, e.method).weight          # D2
type_weight   = config.type_weights.get(e.evidence_type, 1.0)
age_days      = (now - e.collected_at).days
recency       = clamp(0.5 ** (age_days / half_life_days), recency_floor, 1.0)   # D7
w_e           = clamp(reliability * type_weight * recency * e.confidence, 0, 1)
```

Aggregate: `score = 1 − Π_e (1 − w_e)` (noisy-OR, D3). `level` from thresholds
(D5). With no evidence: `score = 0.0`, `level = low`, `no_evidence = True`
(FR-9). The `method` string records the model + version so a stored score can
always be reproduced.

## 8. Requirements

### Functional (testable)

- **FR-1** `assess` SHALL be deterministic: identical `(subject_ref, evidence, config, now)` → byte-identical `TrustAssessment` (D1).
- **FR-2** `assess` SHALL aggregate via noisy-OR; `score ∈ [0,1]`; adding a corroborating evidence record SHALL NOT decrease the score (monotonic, D3).
- **FR-3** `weigh_evidence` SHALL compute `w = clamp(reliability × type_weight × recency × collector_confidence, 0, 1)` per §7.
- **FR-4** Every `TrustAssessment` SHALL include per-evidence `contributions`, `method`, and a plain-language `reason` (D4).
- **FR-5** `level` SHALL be derived from configurable ordered thresholds; identical score → identical level (D5).
- **FR-6** Source reliability SHALL come from the registry; an unknown source/method SHALL resolve to `default_reliability`, and the contribution SHALL reflect that default (D2).
- **FR-7** The engine SHALL NOT mutate any object, evidence, or finding (pure, D6).
- **FR-8** `decide` SHALL return `{decision, score, threshold, rationale}`; `decision` reflects `score ≥ threshold`.
- **FR-9** `assess` with empty evidence SHALL return `score = 0.0`, lowest level, `no_evidence = True`, and SHALL NOT raise (FR-9).
- **FR-10** `recency_factor` SHALL apply the documented exponential decay with configurable half-life and floor (D7); older evidence weighs no more than newer.
- **FR-11** Reliability entries SHALL carry provenance (`set_by`, `set_at`, `rationale`, `version`); the registry SHALL preserve it (D2).
- **FR-12** Invalid config (weight or threshold outside `[0,1]`, `thresholds.low > thresholds.high`, `half_life_days ≤ 0`) SHALL raise `TrustConfigInvalid`.
- **FR-13** `TrustEngineService` SHALL register as an `AQService` with health reflecting config validity (EA-0001).

### Non-functional

- **NFR-1 (determinism)** repeated identical assessments serialize byte-identically.
- **NFR-2 (purity)** no I/O or state mutation inside `assess`/`weigh_evidence` beyond reading the injected registry.
- **NFR-3 (complexity)** `assess` is `O(N)` in evidence count.
- **NFR-4 (portability & typing)** in-memory registry fully tested; `mypy --strict` + `ruff` clean. (A Postgres-backed registry is optional — §12.)

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Same inputs → identical assessment | `test_trust_deterministic` |
| AC-2 | Noisy-OR bounded in [0,1] | `test_trust_score_bounded` |
| AC-3 | More corroboration never lowers score | `test_trust_monotonic` |
| AC-4 | Evidence weight formula correct | `test_trust_evidence_weight` |
| AC-5 | Assessment carries contributions + reason | `test_trust_explainable` |
| AC-6 | Score→level via thresholds | `test_trust_level_mapping` |
| AC-7 | Unknown source uses default, flagged | `test_trust_unknown_source_default` |
| AC-8 | Engine mutates nothing | `test_trust_no_side_effects` |
| AC-9 | decide() returns decision + rationale | `test_trust_decide` |
| AC-10 | No-evidence → 0.0 / low / no_evidence | `test_trust_no_evidence` |
| AC-11 | Recency decay reduces old-evidence weight | `test_trust_recency_decay` |
| AC-12 | Reliability provenance preserved | `test_trust_reliability_provenance` |
| AC-13 | Invalid config rejected | `test_trust_config_invalid` |
| AC-14 | Registers as AQService with health | `test_trust_service_health` |

## 10. Error taxonomy (contributions)

`TrustConfigInvalid` (added to `conventions.errors` + CONVENTIONS §9). Reuses
`ObjectNotFound`/`EvidenceNotFound` only if the engine is asked to resolve refs
it doesn't hold (it normally receives evidence records directly).

## 11. Failure handling

- Invalid configuration → `TrustConfigInvalid` at construction/`set`, before any
  assessment runs; the service reports `unavailable` via health until fixed.
- Registry unavailable (Postgres-backed variant) → `StoreUnavailable`; the
  service reports `degraded`; in-memory registry cannot be unavailable.
- Malformed evidence (missing `collected_at`) → treated as age 0 with a flagged
  contribution note, never a crash; the assessment still returns.

## 12. Dependencies & consumers

- **Depends on:** EA-0004 `EvidenceRecord`/`SourceRef`; EA-0001 `AQService`;
  CONVENTIONS (`ActorRef`, canonical serialization for deterministic output).
- **Consumed by:** the Finding pipeline (populate `finding.confidence` and
  object/relationship `confidence` from an assessment + attach its `reason`);
  EA-0007 Mission (confidence as a prioritization input); EA-0009 Policy
  (confidence-gated enforcement decisions); UI (render the assessment reason).

## 13. Resolved / deferred decisions

- **Transparent noisy-OR over a learned model.** A documented, explainable
  formula is chosen for auditability; a learned/ML scorer, if ever justified,
  gets its own EA and must remain explainable — it does not replace this
  interface.
- **In-memory reliability registry is the reference; Postgres-backed registry is
  optional/deferred.** The `SourceReliabilityRegistry` interface allows a
  persisted enterprise-config implementation later without changing callers; it
  is not required for C-003.
- **Single scalar confidence** remains the platform model (CONVENTIONS §7);
  per-attribute confidence, if introduced, would feed additional `assess` calls,
  not change this contract.
