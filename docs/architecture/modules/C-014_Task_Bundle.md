# C-014 Threat Detection & Analytics — Implementation Task Bundle

**Milestone:** C-014 (Threat Detection & Analytics, EA-0017)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0016 merged & green; EA-0017 spec **Accepted**; CONVENTIONS + EA-0006/0007/0009/0014/0015 + Finding model read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **reproducible detections, no `eval`, no ML black box, no network, no action**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0017 §2 first.** This is the first statistical module; the whole design
hinges on **versioned baselines + pinned detections** so a detection is
reproducible and explainable months later. Build D2/S2 before any anomaly code.

## Target source layout

```
src/aqelyn/detection/
├── __init__.py       # exports the engine, service, types, register_detection_events
├── models.py         # DetectionRule, BehaviorProfile, AnomalyMeasure, ThreatDetection, Projection, DetectionConfig (D1)
├── rules.py          # rule evaluation via the EA-0009 structured interpreter (D1/D2)
├── profiles.py       # build_profile: versioned baselines, never overwrite (D2)
├── anomaly.py        # explicit measures (z-score/percentile/rate) + pinned profile_version (D3)
├── scoring.py        # confidence via Trust + severity via Mission (compose, no 3rd scorer) (D3)
├── store.py          # RuleStore + ProfileStore protocols (D2)
├── memory.py         # in-memory stores (D2)
├── postgres.py       # Postgres stores + DDL (D2)
├── engine.py         # correlate_signals, map_techniques, reproduce, detections_to_findings, project (D4)
└── service.py        # ThreatDetectionService(AQService) + register_detection_events (D5)
tests/detection/      # acceptance suite (in-memory + Postgres)
```

---

## D1 — Types, config & declarative rules (no eval)

**Spec:** §5, §6, D2, FR-1/13; §10.
**Deliverables:** the models; rule evaluation **reusing the EA-0009 structured
condition interpreter** (no `eval`/`exec`/DSL); `DetectionConfig`/rule validation
(`DetectionConfigInvalid`); new error codes in `conventions.errors` +
CONVENTIONS §9.
**Depends on:** EA-0009 interpreter, conventions.
**Acceptance:** `test_det_rules_no_eval`, `test_det_config_invalid`.

## D2 — Versioned baselines + stores (the audit backbone)

**Spec:** §2 (S2), §7, FR-2/14, NFR-1.
**Deliverables:** `build_profile` (baseline over `window_days`, **new version
every time, never overwrite**); `insufficient_data` handling (skip, don't guess);
`RuleStore` + `ProfileStore` (in-memory + Postgres + DDL, version-addressable
`get(version=...)`).
**Depends on:** D1.
**Acceptance:** `test_det_profile_versioned`,
`test_det_rule_contract[inmemory]`, `test_det_rule_contract[postgres]`,
`test_det_profile_contract[inmemory]`, `test_det_profile_contract[postgres]`.

## D3 — Anomaly detection + scoring (explainable, pinned)

**Spec:** §2 (S1/S2), §7, FR-3/4/5/6, D3.
**Deliverables:** explicit anomaly measures (z-score/percentile/rate) with
observed + baseline + threshold; **pin `profile_version` + `rule_version` on every
detection**; `reproduce()` returning an identical result; confidence via Trust,
severity via Mission; plain-language `reason`.
**Depends on:** D2.
**Acceptance:** `test_det_anomaly_measure`, `test_det_pins_versions`,
`test_det_reproduce`, `test_det_explainable`, `test_det_scoring_composed`.

## D4 — Correlation, ATT&CK, findings & projections

**Spec:** §2 (S4/S5), §7, FR-7/8/9/10/11/12, D4.
**Deliverables:** `correlate_signals` (merge weak → stronger; **no incidents** —
SOC owns that); `map_techniques` (declarative, reusing EA-0014 TTPs);
`detections_to_findings` (evidence-cited, Mission-prioritized, **no action**);
`project` (advisory-only `Projection`, never a finding/evidence).
**Depends on:** D3.
**Acceptance:** `test_det_correlate_not_incidents`, `test_det_attack_mapping`,
`test_det_findings_no_action`, `test_det_projection_advisory`,
`test_det_no_network_no_side_effects`, `test_det_tenant_and_bounds`.

## D5 — Service + events

**Spec:** FR-15, §11.
**Deliverables:** `ThreatDetectionService` (`AQService`, name
`"detection_engine"`) + `register_detection_events`; wired into the kernel factory.
**Depends on:** D4.
**Acceptance:** `test_det_service_health`.

---

## Review protocol (Claude Code) — reproducibility gets the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **Reproducibility (the core property):** every detection pins its `rule_version`
   **and** `profile_version`; `reproduce()` returns an identical result. Profiles
   are append-version, never overwritten. Without this, statistical detection is
   unauditable.
2. **No `eval`/`exec`/DSL** — rules go through the EA-0009 structured
   interpreter. **No opaque ML model** anywhere (S3).
3. Every anomaly renders as observed vs baseline vs threshold in plain language
   (S1); insufficient data → skipped and flagged, never guessed.
4. **No third scorer** — confidence from Trust, severity weighting from Mission.
5. **Detection ≠ incident** — `correlate_signals` must not create alerts/
   incidents (SOC owns it, S5). **Projections are advisory** — never findings,
   never evidence (S4).
6. No network; no action; mutates only its own detection records + evidence.
7. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
