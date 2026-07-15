# EA-0017 — Threat Detection & Analytics Engine — Implementation Specification

**Realizes:** EA-0017 / IS-017 (supersedes the placeholder `archive/EA-0017/EA-0017_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0002 (detections/profiles as objects), EA-0006 (Trust — detection confidence), EA-0007 (mission weighting), EA-0014 (indicators + TTP catalog), EA-0004 (detection evidence), the Finding model
**Consumed by:** **EA-0015 SOC** (detections enter as alerts — SOC owns incident correlation), the Finding pipeline, EA-0013 (detections as risk signal), the detection dashboard UI (a WCAG 2.2 AA surface)
**Status:** Accepted
**Build milestone:** C-014 (see `C-014_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 0. Scope & safety boundary (read first)

- **Detect and propose — never act.** This engine produces `ThreatDetection`
  records, findings, and a risk/SOC signal. Any response is a **proposed, gated
  EA-0008 Workflow run** driven by SOC (§EA-0015 §0). Nothing is executed here.
- **No network surface.** Detection runs over data already in the platform
  (objects, findings, threat indicators, evidence). It opens no sockets and holds
  no credentials — live telemetry collection is a later connector EA. The
  observation seam is data already stored.
- **Detections are claims, and claims need proof.** Every detection cites the
  signals and the rule/baseline that produced it (§2 below). A detection with no
  citable basis is not raised.
- Tenant-scoped and bounded throughout. No new authorization surface.

## 1. Purpose

Eleven engines produce structured knowledge; this one **asks the security
question directly: is something bad happening?** It runs detection rules over
estate signals, learns **behavioral baselines** and flags **anomalies** against
them, correlates weak signals into stronger detections, maps activity to
**MITRE ATT&CK** techniques, and scores each detection's confidence and severity —
handing high-quality, explainable detections to the SOC rather than raw noise.

## 2. Determinism & explainability under statistics (the central design problem)

Every engine so far chose transparent, deterministic scoring. Behavioral and
anomaly detection are inherently **statistical** — which is not the same as
non-deterministic or unexplainable, and this spec holds the line precisely:

- **S1 — Statistical, never opaque.** Baselines are computed from **stored
  observations over an explicit window**; an anomaly is an **explicit measure**
  (z-score, percentile, rate-of-change) against a stated threshold. The
  detection output carries the baseline value, the observed value, the measure,
  and the threshold — a non-expert can read "logins from this account averaged 3/
  day over 30 days; today there were 47." That is the Charter's plain-language
  bar met by construction.
- **S2 — Baselines are versioned and snapshotted; every detection pins the
  baseline version it fired against.** Baselines drift as data arrives, so
  without this a detection from last month could never be reproduced or defended.
  With it, `reproduce(detection)` re-computes the same result against the pinned
  `BehaviorProfile` version — deterministic *given its inputs*, forever. This is
  the property that makes statistical detection auditable.
- **S3 — No opaque ML in this EA.** No learned black-box classifier. If a learned
  model is ever justified it gets its **own ADR** and must remain explainable and
  reproducible — it does not replace this interface (consistent with EA-0006 §13).
- **S4 — Predictions are advisory projections, not findings-of-fact.** The
  archive's "predictive analytics" is scoped to clearly-labeled `Projection`
  records carrying their basis and horizon. A projection SHALL NOT be raised as a
  finding asserting something happened, and SHALL NOT be used as evidence. It
  informs; it does not accuse.
- **S5 — Detection ≠ incident.** This engine correlates *signals into detections*;
  **EA-0015 SOC correlates detections/alerts into incidents.** No duplicate
  incident logic here (same clean seam as fusion→risk).

## 3. Design decisions

- **D1 — Detections/profiles/anomalies are EA-0002 objects** (`object_type ∈
  {threat_detection, behavior_profile}`), evidence-bound (EA-0004). No bespoke
  store beyond the rule/profile catalogs.
- **D2 — Detection rules are declarative, structured predicates** — reuse the
  EA-0009 safe condition model (attr/op/value + `all`/`any`/`not`). **No `eval`/
  `exec`**, no embedded DSL.
- **D3 — Confidence reuses Trust (EA-0006);** severity weighting reuses Mission
  (EA-0007). No third scorer.
- **D4 — ATT&CK mapping is declarative data**, reusing EA-0014's TTP tags; a
  detection carries `technique_ids`. Coverage is derived from the mapping.
- **D5 — Detect-and-propose, no network** (§0). Registered as an `AQService`
  (D6). Tenant-scoped, bounded batches (D7).

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Detection rule** | A declarative predicate over signals that, when true, raises a detection. |
| **Behavior profile** | A **versioned** baseline of normal behavior for a subject, over a window. |
| **Anomaly** | An explicit deviation measure (z-score/percentile/rate) beyond a stated threshold. |
| **Detection** | A raised claim: subject, basis (signals/rule/baseline version), confidence, severity, ATT&CK techniques. |
| **Projection** | A labeled advisory forecast — never a finding, never evidence (S4). |
| **Technique** | A MITRE ATT&CK technique id mapped to a detection (D4). |

## 5. Types

```
DetectionRule = { id, name, description, kind: "rule"|"behavioral"|"correlation",
                  condition: "Condition",             # EA-0009 structured predicate (D2)
                  subject_type: str, technique_ids: list[str],
                  severity: str, enabled: bool, version: int }

BehaviorProfile = { id, tenant_id, subject_ref: str, metric: str,
                    window_days: int, baseline: dict,          # e.g. {mean, stddev, p95, n}
                    computed_at: datetime, version: int }      # versioned + pinned (S2)

AnomalyMeasure = { metric: str, observed: float, baseline_value: float,
                   measure: "z_score"|"percentile"|"rate_change", value: float,
                   threshold: float, profile_version: int }    # explainable (S1/S2)

ThreatDetection = { id, tenant_id, rule_id: str, rule_version: int,
                    subject_ref: str, kind: str,
                    signal_refs: list[dict],                    # findings/indicators/observations cited
                    anomaly: AnomalyMeasure | null,
                    confidence: float, severity: str, severity_score: float,
                    technique_ids: list[str], evidence_id: str,
                    profile_version: int | null,                # pinned baseline (S2)
                    reason: str, detected_at: datetime }

Projection = { id, tenant_id, subject_ref: str, statement: str, basis: dict,
               horizon_days: int, confidence: float,
               advisory: bool = True }                          # never a finding/evidence (S4)

DetectionConfig = { thresholds: dict[str, float], window_days: int,
                    batch_size: int, min_confidence: float }
```

Reuses EA-0009 `Condition`, EA-0006 confidence, EA-0014 TTPs, the Finding model.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class RuleStore(Protocol):
    async def put(self, rule: DetectionRule) -> DetectionRule: ...     # validates condition (D2)
    async def get(self, rule_id: str) -> DetectionRule | None: ...
    async def list(self, *, tenant_id: str | None, enabled_only: bool = True) -> list[DetectionRule]: ...

class ProfileStore(Protocol):
    async def put(self, profile: BehaviorProfile) -> BehaviorProfile: ...   # new version, never overwrite (S2)
    async def get(self, profile_id: str, *, version: int | None = None) -> BehaviorProfile | None: ...
    async def latest(self, *, subject_ref: str, metric: str) -> BehaviorProfile | None: ...

class ThreatDetectionEngine(Protocol):
    async def build_profile(self, *, subject_ref: str, metric: str,
                            tenant_id: str | None) -> BehaviorProfile: ...      # versioned baseline (S2)
    async def evaluate_rules(self, *, tenant_id: str | None,
                             scope: dict | None = None) -> list[ThreatDetection]: ...  # D2
    async def detect_anomalies(self, *, tenant_id: str | None,
                               scope: dict | None = None) -> list[ThreatDetection]: ...  # S1/S2
    async def correlate_signals(self, detections: Sequence[ThreatDetection]
                                ) -> list[ThreatDetection]: ...   # weak -> stronger; NOT incidents (S5)
    async def map_techniques(self, detection: ThreatDetection) -> list[str]: ...  # D4
    async def reproduce(self, detection_id: str) -> ThreatDetection: ...       # re-run vs pinned inputs (S2)
    async def detections_to_findings(self, detections: Sequence[ThreatDetection], *,
                                     by: ActorRef, prioritize: bool = True) -> list[str]: ...
    async def project(self, *, subject_ref: str, horizon_days: int) -> Projection: ...  # advisory (S4)
    def explain(self, detection: ThreatDetection) -> dict: ...
```

`ThreatDetectionService` wraps the engine + stores as an `AQService`
(name `"detection_engine"`, depends on object/finding/trust/mission/threat/
evidence; health reflects availability + config validity).

## 7. Computation (the reference model)

**Profiles.** `build_profile` aggregates stored observations for
`(subject_ref, metric)` over `window_days` into a baseline (`mean`, `stddev`,
`p95`, `n`) and **writes a new version** (never overwrites, S2).

**Rules.** `evaluate_rules` runs each enabled rule's structured condition over
in-scope signals (EA-0009 interpreter, D2); a match raises a `ThreatDetection`
citing the rule id+version and the matched signals.

**Anomalies.** For each profiled subject/metric, compute the measure (e.g.
`z = (observed − mean)/stddev`); if `|value| ≥ threshold`, raise a detection
carrying the full `AnomalyMeasure` **and the `profile_version` it fired against**
(S1/S2).

**Scoring.** `confidence` via Trust (rule reliability + corroboration across
signals + recency); `severity_score` = severity × Mission factor of the subject's
assets (EA-0007). No new scorer (D3).

**Correlate.** `correlate_signals` merges weak co-occurring detections on the same
subject/technique into one stronger detection (higher confidence, union of
signals) — **it does not create incidents** (S5).

**Output.** `detections_to_findings` raises evidence-cited, mission-prioritized
findings; SOC intake picks them up as alerts. `reproduce` re-runs a detection
against its pinned rule version + profile version and MUST return the same result.

## 8. Requirements

### Functional (testable)

- **FR-1** `evaluate_rules` SHALL evaluate declarative structured conditions (EA-0009 model) and SHALL NOT `eval`/`exec` any string or load rule code (D2).
- **FR-2** `build_profile` SHALL write a **new version** of a `BehaviorProfile` and SHALL NOT overwrite prior versions (S2).
- **FR-3** Every anomaly detection SHALL carry an `AnomalyMeasure` (observed, baseline value, measure, threshold) **and** the `profile_version` it fired against (S1/S2).
- **FR-4** `reproduce(detection_id)` SHALL re-run the detection against its pinned rule version + profile version and SHALL return an identical result (S2).
- **FR-5** Every detection SHALL cite its `signal_refs` + rule and carry a plain-language `reason`; a detection without a citable basis SHALL NOT be raised (§0).
- **FR-6** `confidence` SHALL come from the Trust Engine and severity weighting from the Mission Engine; the module SHALL NOT introduce a third scorer (D3).
- **FR-7** `map_techniques` SHALL attach ATT&CK technique ids from the declarative mapping (reusing EA-0014 TTPs) (D4).
- **FR-8** `correlate_signals` SHALL merge weak detections into stronger ones and SHALL NOT create incidents/alerts (SOC owns that) (S5).
- **FR-9** `project` SHALL return an `advisory=True` `Projection` carrying its basis and horizon; a projection SHALL NOT be raised as a finding nor used as evidence (S4).
- **FR-10** `detections_to_findings` SHALL raise evidence-cited findings (optionally Mission-prioritized); no action SHALL be executed (§0).
- **FR-11** The engine SHALL NOT mutate non-detection objects, and SHALL open no network connection (§0).
- **FR-12** All operations SHALL be tenant-scoped and bounded (`batch_size`); no cross-tenant subject appears.
- **FR-13** Invalid config/rule (unknown op, `window_days ≤ 0`, threshold out of range, `batch_size ≤ 0`) SHALL raise `DetectionConfigInvalid` at `put`/construction.
- **FR-14** `RuleStore` and `ProfileStore` in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-15** `ThreatDetectionService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (reproducibility)** any detection re-runs identically against its pinned rule + profile versions (S2) — the audit property.
- **NFR-2 (explainability)** every detection renders as a plain-language statement of observed vs baseline vs threshold (S1).
- **NFR-3 (no eval / no ML black box / no network)** enforced by test+grep (D2/S3/§0).
- **NFR-4 (bounded & typed)** batched processing; in-memory + Postgres stores pass their suites; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Rules evaluate via structured conditions; no eval | `test_det_rules_no_eval` |
| AC-2 | Profiles versioned, never overwritten | `test_det_profile_versioned` |
| AC-3 | Anomaly carries measure + baseline + threshold | `test_det_anomaly_measure` |
| AC-4 | Detection pins profile/rule version | `test_det_pins_versions` |
| AC-5 | reproduce() returns identical result | `test_det_reproduce` |
| AC-6 | Detection cites signals + plain reason | `test_det_explainable` |
| AC-7 | Confidence via Trust; severity via Mission | `test_det_scoring_composed` |
| AC-8 | ATT&CK techniques mapped | `test_det_attack_mapping` |
| AC-9 | correlate_signals merges, creates no incidents | `test_det_correlate_not_incidents` |
| AC-10 | Projection advisory; not a finding/evidence | `test_det_projection_advisory` |
| AC-11 | Detections → evidence-cited findings, no action | `test_det_findings_no_action` |
| AC-12 | No network; mutates no non-detection object | `test_det_no_network_no_side_effects` |
| AC-13 | Tenant isolation + bounded batches | `test_det_tenant_and_bounds` |
| AC-14 | Invalid config/rule rejected | `test_det_config_invalid` |
| AC-15 | Rule & profile stores pass one suite each | `test_det_rule_contract[...]` / `test_det_profile_contract[...]` |
| AC-16 | Registers as AQService with health | `test_det_service_health` |

## 10. Error taxonomy (contributions)

`DetectionConfigInvalid`, `DetectionRuleNotFound`, `ProfileNotFound` (added to
`conventions.errors` + CONVENTIONS §9). Reuses `StoreUnavailable`,
`TenantScopeRequired`.

## 11. Registered event types (owned by EA-0017)

`aqelyn.detection.threat_detected`, `aqelyn.detection.anomaly_detected`,
`aqelyn.detection.profile_updated` — via `register_detection_events()`
(EA-0003 §7). (Archive uses `threat.detected`; mapped into the platform namespace
as `aqelyn.detection.threat_detected`.)

## 12. Failure handling

- Invalid config/rule → `DetectionConfigInvalid`; service `unavailable` /
  rule rejected before any evaluation uses it.
- Dependency unavailable → `StoreUnavailable`; service `degraded`; a partial
  detection run is marked incomplete, never presented as "nothing detected".
- Insufficient data for a baseline (`n` below a configured minimum) → the profile
  is marked `insufficient_data` and anomaly detection for it is **skipped, not
  guessed** (flagged) — statistics on 3 samples are not a claim.
- A single rule error is recorded on that rule's result (flagged) and does not
  abort the run.

## 13. Dependencies & consumers

- **Depends on:** EA-0009 condition interpreter (rules); EA-0006 Trust
  (confidence); EA-0007 Mission (severity weighting); EA-0014 (indicators/TTPs);
  EA-0002 objects; EA-0004 evidence; the Finding model; EA-0001 `AQService`.
- **Consumed by:** **EA-0015 SOC** (detections → alerts → incidents; SOC owns
  incident correlation, S5); the Finding pipeline; EA-0013 (risk signal); the
  detection dashboard UI (**WCAG 2.2 AA** applies).

## 14. Resolved / deferred decisions

- **Statistical but reproducible** (S1/S2) — versioned baselines + pinned
  detections are the binding mechanism that keeps behavioral detection auditable.
- **No opaque ML here** (S3); a learned model requires its own ADR and must stay
  explainable.
- **Predictions are advisory only** (S4) — never findings, never evidence.
- **Detection ≠ incident** (S5) — SOC owns incident correlation; this engine hands
  it high-quality detections.
- **Live telemetry collection is a later connector EA** (§0); this engine detects
  over data already in the platform.
