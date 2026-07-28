# C-041 A1 - Fold Identity Audit

**Baseline:** `main @404a86d`
**Contract:** [C-041_Task_Bundle.md](C-041_Task_Bundle.md)
**Scope:** A1 enumeration only. This document contains no repair and changes no
production or test code.

## Result

The four sites named by ECR-0076 are real, but they are not the full repair
surface.

The structural pass found:

- the four named mission-input erasures in EA-0013, EA-0015, EA-0023, and
  EA-0032;
- one central contract boundary in EA-0013: `score_risk` accepts an optional
  mission input only as a bare `float` whose default is `0.0`, so the function
  cannot distinguish missing mission context from a supplied zero.

The first repair commit must therefore not be scoped to the four filenames in
ECR-0076. A2 must decide whether the EA-0013 numeric boundary changes centrally
or remains guarded at every owner adapter.

## Method

### Pass 1 - exact byte identity

The reference was the complete pre-fix
`ispm.scoring._mission_factor` function at `f067b80`. Its normalized LF byte
sequence has SHA-256:

```text
fc557f9d2d4575fe3e2e35f03440e41013d8478a426108dc6c14c37b909430ba
```

Exactly one shipped function matches those bytes:

```text
src/aqelyn/secrets/scoring.py:646:_mission_factor
```

No other exact copy exists. This pass finds copies, not drifted instances.

### Pass 2 - structural and type-guided

Python's AST was used to inventory every production function containing
`max`, `min`, `sum`, `any`, or `all`, then the same pass was extended to
manual accumulators and `math.prod`. The raw inventory covers:

```text
86 files
192 functions
274 fold calls
all=13, any=57, max=81, min=56, sum=67
```

A site enters the candidate ledger below only when all three conditions hold:

1. one or more optional owner, estate, control, evidence, or score
   contributors are folded;
2. that set can be empty, or the code contains an explicit empty fallback; and
3. the folded value can escape as an analytical record, decision, ranking,
   correlation, coverage claim, confidence, or metric.

Each candidate was then traced through its model validators and production
callers. This removes syntactic lookalikes without relying on names:

| Eliminated shape | Why it is outside the class |
|---|---|
| pagination, limits, clamps, timestamps, latest-version selection | the fold is over mechanical values, not optional analytical contributors |
| model validation and collection predicates | the identity does not escape as an analytical result |
| pairwise reconciliation | the operands are fixed incoming/existing records, not a possibly-empty contributor set |
| ordering and replay extraction after an explicit empty refusal | the fold is unreachable on empty input |

The table is the reviewable output of that reduction. A later source change
must rerun discovery; this is not a permanent hand-maintained registry.

## Candidate Ledger

`Favorable?` is evaluated in the site's own orientation. `N/A` means the empty
case is explicitly represented as a declared no-applicable-input result, not
an unknown input.

| Site | Fold operator | Empty identity/fallback | Favorable here? | Absence class | Disposition and reason |
|---|---|---:|---|---|---|
| `assetconfig/drift.py:_assess_baseline` | counts then ratio | `1.0` when `evaluated == 0` | yes - perfect compliance | cannot occur | **Not affected - fragile.** `Baseline` rejects `checks=[]`; depends on that model validator. |
| `assetconfig/drift.py:AssetConfigGovernanceEngine.assess` | mean | `1.0` | yes | cannot occur independently | **Not affected - fragile.** `objects_assessed > 0` is required and every matching baseline emits one `AssetDrift`; depends on that invariant. The empty-check defect is the row above. |
| `cspm/engine.py:_routing_status` | sum accepted outcomes | `0`; `0 == len([])` | yes - `complete` | cannot occur | **Not affected - fragile.** Routing always selects one or six owners, and `CloudRoutingResult` rejects empty outcomes. |
| `detection/engine.py:_merge_detections` | max confidence/severity | numeric minimum | yes | cannot occur | **Not affected - fragile.** It is called only for correlation groups with at least two detections. |
| `detection/profiles.py:_baseline` | sum/mean | no numeric baseline | no | explicit unknown | **Not affected - structural.** Empty input emits `n=0` and `insufficient_data=true`; mean/stddev/p95 are absent. |
| `detection/scoring.py:_mission_factor` | max mission impact | configured default tier | policy-dependent | declared configured default | **Not affected - structural.** The fold runs only for non-empty impacts; empty uses `MissionConfig.default_tier`, not the operator identity. |
| `executive/kpi.py:_apply_combinator` | sum/min/max/average | none | no | empty refused | **Not affected - structural.** Every non-identity combinator rejects an empty input before folding. |
| `executive/kpi.py:_combined_confidence` | min | `None` | no | explicit unknown | **Not affected - structural.** No confidence remains `None`, not a favorable number. |
| `exposure/engine.py:_mission_factors` | max mission impact | `0.0` | **yes** - least exposure risk | not supplied | **Affected.** Empty and truncated-with-no-impact results become the same favorable numeric factor. |
| `exposure/engine.py:_score_from_replay` | max score | none | no | empty refused | **Not affected - structural.** Missing/empty score items raise before `max`. |
| `forecast/scoring.py:accuracy_records` | mean/sum | `mae=0.0`, `within=0.0` | mixed | explicit unknown | **Not affected - structural.** `n=0` remains in the same `AccuracyRecord`; absence is not erased into a bare metric. |
| `governance/engine.py:_ControlAccumulator.result` | counts then ratio | `1.0` | yes - perfect compliance | declared not applicable | **Not affected - declared N/A.** The result says `evaluated=0` and names "no in-scope targets"; the owner has represented the empty domain explicitly. |
| `governance/engine.py:ComplianceEngine.assess` | mean control score | `1.0` | yes | cannot occur | **Not affected - fragile.** `GovernanceConfig` rejects an empty control list; depends on that validator. |
| `governance/engine.py:_framework_scores` | mean | `0.0` | **no** - worst compliance | declared not applicable | **Not affected - context-dependent.** An unmapped framework is scored at the unfavorable end. |
| `ispm/scoring.py:_mission_factor` | max mission impact | typed `value=None` | no | explicit unknown | **Not affected - structural.** The ECR-0074 repair preserves unknown before a factor exists. |
| `ispm/scoring.py:_owner_risk` | max IAG severity | `0.0` | yes - no risk | declared complete empty | **Not affected - declared N/A.** A supplied empty EA-0011 risk list means no owner risks found; missing mission context separately makes the outer factor unknown. |
| `ispm/scoring.py:posture_score_result` | weighted sums | none | no | unknown excluded | **Not affected - structural.** It requires positive known weight and applies a coverage adjustment to excluded unknowns. |
| `lake/retention.py:RetentionEngine._is_referenced` | any reference owner | `False` | action-enabling | cannot occur | **Not affected - fragile.** The set is a fixed, non-optional triple of evidence/finding/case checkers; exceptions block retention. |
| `mission/engine.py:_mission_factor` | max mission impact | configured default tier | policy-dependent | declared configured default | **Not affected - structural.** Empty is explicitly marked by `used_default` in the priority reason. |
| `policy/engine.py:authorize` | any deny/approval | `False` | potentially | empty refused | **Not affected - structural.** `matches=[]` returns an explicit deny before either fold. |
| `policy/engine.py:evaluate_compliance` | violation accumulation | `compliant=True` | yes - compliant | declared complete empty | **Not affected - declared N/A.** EA-0009 defines compliance as no violations, and the same result carries `evaluated=0`; no-rule evaluation remains distinguishable. |
| `policy/engine.py:more_restrictive_effect` | max effect rank | none | no | empty refused | **Not affected - structural.** The helper rejects an empty effect set before `max`. |
| `policy/engine.py:_requires_approval` | any approval obligation | `False` | action-enabling | declared not applicable | **Not affected - declared N/A.** A permit rule with no approval effect or obligation has explicitly declared no approval requirement. |
| `policy/interpreter.py:_matches` | all/any conditions | Boolean identities | potentially | cannot occur | **Not affected - fragile.** `Condition` rejects empty `all` and `any` lists; depends on that validator. |
| `policy/service.py:_decision_requires_approval` | any approval obligation | `False` | action-enabling | declared not applicable | **Not affected - declared N/A.** The owner decision explicitly contains neither `require_approval` effect nor obligation. |
| `response/campaign.py:_next_phase` | all dependencies complete | `True` | action-enabling | declared not applicable | **Not affected - declared N/A.** A phase with no declared dependencies is ready by definition; it still passes its own action gates. |
| `response/campaign.py:_apply_dependency_blocks` | any failed dependency | `False` | action-enabling | declared not applicable | **Not affected - declared N/A.** No declared dependencies means no dependency block, not missing dependency evidence. |
| `response/metrics.py:_mean_or_none` | mean | `None` | no | explicit unknown | **Not affected - structural.** No usable duration stays unknown. |
| `response/metrics.py:_automated_pct` | sum/ratio | `0.0` | **no stable favorable orientation** | declared complete empty | **Not affected - context-dependent.** The same record carries `campaigns=0`; zero automation is descriptive, not a safety verdict. |
| `response/recovery.py:checks_verified` | all checks | `False` | no | explicit unknown/failure | **Not affected - structural.** `bool(checks)` prevents `all([])` from verifying recovery. |
| `risk/correlate.py:_risk_from_group` | max signal impact | `0.0` | yes - no risk | cannot occur | **Not affected - fragile.** Groups are created only by appending a real signal; each call receives at least one. |
| `risk/engine.py:RiskIntelligenceEngine._mission_context` | manual max accumulator | `0.0` | **yes** - least risk | not supplied | **Affected.** Unwired, empty, and truncated-with-no-impact states collapse into a favorable number. |
| `risk/engine.py:_snapshot_from_risks` | mean risk score | `0.0` | yes - no exposure | declared complete empty | **Not affected - declared N/A.** A completed correlation yielding no risks carries `total=0` and empty band counts in the same snapshot. |
| `risk/scoring.py:score_risk` | max base/mission impact | default mission `0.0` | **yes** - mission cannot raise risk | not supplied | **Affected contract boundary.** The public numeric input cannot represent unknown. All current production callers pass a value, but several pass the erased `0.0`; A2/A3 must keep this boundary from re-erasing typed owner state. |
| `secrets/scoring.py:_mission_factor` | max mission impact | `0.0` | **yes** - least credential risk | not supplied | **Affected.** This is the sole exact-byte copy of pre-fix ISPM. |
| `secrets/scoring.py:_owner_risk` | max adverse control | `0.0` | yes - no risk | cannot cast a vote | **Not affected - fragile.** If any direct control is unknown, the outer `owner_risk` factor is unknown; depends on `risk_known = all(five control factors known)`. The mission erasure remains the separate affected row above. |
| `secrets/scoring.py:governance_score_result` | weighted sums | none | no | unknown excluded | **Not affected - structural.** It requires positive known weight, applies coverage and uncertainty penalties, and caps active exposure. |
| `soc/correlate.py:_incident_for_group` | max risk/mission priority | `0.0` | yes - least priority | explicit in companion fields | **Not affected - structural, after upstream repair.** Missing risk remains `risk_score=None`; an explicit zero mission retains its mission id. The current mission erasure is isolated in the next row. |
| `soc/correlate.py:_mission_context` | manual max accumulator | `0.0` | **yes** - least incident priority | not supplied | **Affected.** This correlation path proves the class is wider than scorers. |
| `supplychain/engine.py:reachability` | min dependency path | none | no | empty handled | **Not affected - structural.** The fold runs only when `direct_paths` is non-empty; complete empty traversal becomes `unreachable`, truncation becomes `unknown`. |
| `threat/engine.py:_severity_score` | max mission impact | `1.0` | **no** - maximum severity | not supplied | **Not affected - context-dependent.** Empty/unwired mission context takes the conservative end, not the fold identity. |
| `trust/engine.py:TrustEngine.assess` | noisy-or product | `score=0.0` | **no** - lowest trust | explicit unknown | **Not affected - structural.** No evidence carries `no_evidence=true`, low level, and an explicit reason. |
| `vuln/engine.py:_mission_factor` | max mission impact | typed unknown factor | no | explicit unknown | **Not affected - structural.** Provider absent and provider empty have typed, distinct `unknown_cause` values. |
| `vuln/engine.py:_compose_score` | weighted sum | none | no | unknown excluded | **Not affected - structural.** Unknown factors have zero normalized weight and the function requires positive known weight. |
| `vuln/engine.py:_score_from_replay` | max score | none | no | empty refused | **Not affected - structural.** Missing/empty score items raise before `max`. |
| `workflow/engine.py:_step_succeeded` | any successful result | `False` | no | explicit not completed | **Not affected - context-dependent.** Absence cannot authorize progress. |
| `workflow/engine.py:_all_steps_succeeded` | all playbook steps | Boolean `True` | action-enabling | cannot occur | **Not affected - fragile.** `Playbook` rejects an empty step list; depends on that validator. |
| `workflow/gating.py:_has_confirm_token` | any matching confirmation | `False` | no | explicit not approved | **Not affected - context-dependent.** No confirmation token cannot authorize execution. |

## A1 Repair Inputs

### Affected sites

The repair phase starts with these rows, not with the prose list in ECR-0076:

1. `risk/engine.py:RiskIntelligenceEngine._mission_context`
2. `risk/scoring.py:score_risk` (contract boundary)
3. `exposure/engine.py:_mission_factors`
4. `secrets/scoring.py:_mission_factor`
5. `soc/correlate.py:_mission_context`

The `score_risk` row is a boundary finding, not permission to replace every
float with a new type. A3 must choose the narrowest representation that keeps
unknown visible through all production callers, then A4 must prove the central
guarantee reaches it.

The production call-site trace is:

| Caller | Missing mission reaches `score_risk` as | Does another type preserve unknown? |
|---|---:|---|
| `risk/engine.py:RiskIntelligenceEngine.score` | `0.0` | **no** - the returned `Risk` is the owner record |
| `exposure/engine.py:_risk_for_exposure` | `0.0` | **no** - the scored exposure consumes the numeric `Risk` |
| `secrets/scoring.py:_owner_risk` | `0.0` | **no for mission absence** - `risk_known` covers direct controls, not mission |
| `ispm/scoring.py:_owner_risk` | provisional `0.0` | **yes** - `_MissionContext.value=None` makes the outer posture factor unknown |

### Fragile invariants to preserve

These sites are safe only while another invariant holds and must be revisited
if that invariant changes:

- EA-0012 drift score and snapshot mean: every baseline has at least one check,
  and at least one assessed object emits an `AssetDrift`;
- CSPM routing: non-empty owner roster plus result-model validation;
- detection merge: groups contain at least two detections;
- governance overall mean: non-empty configured controls;
- policy Boolean folds: non-empty condition lists;
- EA-0013 correlation: every group contains a signal;
- credential owner-risk: the outer factor cannot become known while a direct
  control is unknown; and
- Workflow completion: every playbook contains at least one step.

These are not exemptions. They are dependencies whose removal reopens the
finding without changing the fold itself.

## Commit Boundary

A1 is complete only as this audit-only commit. No source, test, specification,
or ECR status is changed here. A2/A3 begins in a later commit after review of
this enumeration.
