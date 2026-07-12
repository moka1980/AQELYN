# C-003 Trust Engine — Implementation Task Bundle

**Milestone:** C-003 (Trust Engine, EA-0006)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0005 merged & green; EA-0006 spec **Accepted**; CONVENTIONS + EA-0004 read.
**Definition of Done:** every ticket's acceptance tests pass; `ruff` clean; `mypy --strict` clean; the engine mutates nothing; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

---

## How to use this bundle

Build tickets **in order** (TR1 → TR4). Each names its spec section and the exact
`pytest` ids from EA-0006 §9. The engine is **pure**: it reads evidence + config
and returns assessments; it never writes to a store. If a needed behavior isn't
in the spec, raise an Engineering Change Request.

## Target source layout

```
src/aqelyn/trust/
├── __init__.py       # exports TrustEngine, service, types
├── models.py         # SourceReliability, EvidenceContribution, TrustAssessment, Decision, TrustConfig (TR1)
├── registry.py       # SourceReliabilityRegistry protocol + in-memory impl (TR1)
├── engine.py         # TrustEngine: weigh_evidence, assess (noisy-OR), decide, explain (TR2/TR3)
└── service.py        # TrustEngineService(AQService) (TR4)
tests/trust/          # acceptance suite (in-memory registry)
```

---

## TR1 — Types, config, and reliability registry

**Spec:** §5, §6 (registry), D2, FR-11/FR-12.
**Deliverables:** the models; `TrustConfig` with validation
(`TrustConfigInvalid` on out-of-range weights/thresholds, `low > high`,
`half_life_days ≤ 0`) added to `conventions.errors` + CONVENTIONS §9; the
in-memory `SourceReliabilityRegistry` (default entry, provenance preserved,
unknown → default).
**Depends on:** EA-0004 (EvidenceRecord/SourceRef), conventions.
**Acceptance:** `test_trust_config_invalid`, `test_trust_reliability_provenance`,
`test_trust_unknown_source_default`.

## TR2 — Evidence weighting

**Spec:** §7, FR-3, FR-10, D7.
**Deliverables:** `weigh_evidence` = `clamp(reliability × type_weight × recency ×
collector_confidence)`, with the documented exponential recency decay
(half-life + floor).
**Depends on:** TR1.
**Acceptance:** `test_trust_evidence_weight`, `test_trust_recency_decay`.

## TR3 — Assessment, decision & explanation

**Spec:** §7, FR-1/2/4/5/7/8/9, D1/D3/D4/D6.
**Deliverables:** `assess` (noisy-OR aggregation, bounded, monotonic,
deterministic, pure), score→level mapping, `no_evidence` handling, plain-language
`reason`, `decide`, and `explain`.
**Depends on:** TR2.
**Acceptance:** `test_trust_deterministic`, `test_trust_score_bounded`,
`test_trust_monotonic`, `test_trust_explainable`, `test_trust_level_mapping`,
`test_trust_no_side_effects`, `test_trust_decide`, `test_trust_no_evidence`.

## TR4 — TrustEngineService (AQService)

**Spec:** FR-13, §11.
**Deliverables:** `TrustEngineService` registering as an `AQService`
(name `"trust_engine"`), health reflecting config validity; wired into the
kernel factory.
**Depends on:** TR3.
**Acceptance:** `test_trust_service_health`.

---

## Review protocol (Claude Code)

Per ticket, confirm: (1) each named acceptance test exists and passes;
(2) `assess`/`weigh_evidence` are pure — no store writes, no I/O beyond the
injected registry; (3) determinism holds (byte-identical output for identical
inputs); (4) aggregation is bounded `[0,1]` and monotonic; (5) every assessment
carries contributions + method + plain-language reason; (6) `ruff` +
`mypy --strict` clean; interfaces match the spec exactly. Merge only on green
review; then **report back to the owner** before the next module.
