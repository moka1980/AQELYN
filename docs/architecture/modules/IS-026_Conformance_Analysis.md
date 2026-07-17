# IS-026 Conformance Analysis — IS-026 is IS-012 restated

**Determination:** IS-026 (Configuration Compliance & Drift Intelligence) is **not a
new module** — it restates **EA-0012 (Asset & Configuration Governance)**, which
shipped in **C-009** and is green on `main`. No `EA-0026` engine is to be built. See
**ECR-0015**.
**Verification standard:** every ✅ below is checked against **shipped code** (per
ECR-0007 and C-023 **K1**), not against the EA-0012 spec.

## The decisive tell

Both archive masters declare the **identical** event type
`configuration.drift.detected`:

- EA-0012 archive master — lines 787, 1557, 1959 (as an `event_type`).
- IS-026 archive master — line 294.

EA-0012 ships it as `aqelyn.config.drift_detected` (`assetconfig/service.py:16`, the
platform-namespaced form). Identical declared event names across two archives are a
reliable **restatement** signal — a single grep caught it.

## Component & type mapping (verified against shipped code)

| IS-026 component / type | Shipped EA-0012 | Evidence (file:line) | ✅ |
|---|---|---|---|
| Baseline Management / `BaselineDefinition` | `Baseline` + `BaselineStore` | `assetconfig/models.py:102`; `assetconfig/store.py` | ✅ |
| Drift Detection / `DriftAssessment` | `DriftSnapshot` + `assess_asset()` | `assetconfig/models.py:201`; `assetconfig/drift.py:94` | ✅ |
| Drift items / deviations | `DriftItem`, `AssetDrift` | `assetconfig/models.py:140,163` | ✅ |
| Configuration classification | `classify()` | `assetconfig/classify.py:14`; `assetconfig/drift.py:90` | ✅ |
| `ConfigurationRemediation` | drift → `Finding` (+ proposed EA-0008 run) | `assetconfig/drift.py:146` `drift_to_findings` → `raise_finding` (165) | ✅ |
| `configuration.drift.detected` event | `aqelyn.config.drift_detected` | `assetconfig/service.py:16` | ✅ |
| Compliance validation / mapping | **EA-0010** (Compliance & Governance) | `governance/engine.py` `coverage/control_result/trend` | ✅ (owned elsewhere) |
| Executive configuration reporting | **EA-0022** (views over owners) | `executive/` | ✅ (owned elsewhere) |
| Governance / policy validation | **EA-0009** Policy + **EA-0008** Workflow | shipped | ✅ (owned elsewhere) |

Major Engineering Decisions (IS-026 §36) map one-for-one onto EA-0012's shipped
decisions (evidence-backed drift, baseline as first-class object, event-driven
lifecycle, findings-path remediation). None is new.

## C-023 K1 shipped-code verification

**Status:** Accepted at `main` commit `44f2539`.
**Verifier:** Codex.
**Result:** every ✅ row above holds against shipped code; no new EA-0026 module or
follow-up repair ticket is required.

Verified evidence:

- `src/aqelyn/assetconfig/models.py` ships `Baseline`, `DriftItem`, `AssetDrift`,
  and `DriftSnapshot`.
- `src/aqelyn/assetconfig/store.py` ships `BaselineStore` and
  `DriftSnapshotStore`.
- `src/aqelyn/assetconfig/drift.py` ships `AssetConfigAnalyzer.assess_asset`,
  `AssetConfigAnalyzer.assess`, and `AssetConfigAnalyzer.drift_to_findings`;
  `drift_to_findings` raises findings and proposes remediation through the existing
  workflow path when configured.
- `src/aqelyn/assetconfig/classify.py` ships `classify`, backed by the EA-0009
  structured `Condition` interpreter.
- `src/aqelyn/assetconfig/service.py` ships `aqelyn.config.drift_detected` and
  `register_acg_events`.
- `src/aqelyn/configcompliance/` is absent, so no second config engine/package was
  introduced.

Verification command:

```bash
AQELYN_ENV=ci AQELYN_TENANT_MODE=local AQELYN_BACKEND=postgres \
AQELYN_DATABASE_URL=postgresql+asyncpg://aqelyn:aqelyn@localhost:5432/aqelyn \
AQELYN_REDIS_URL=redis://localhost:6379/0 pytest tests/assetconfig -q
```

Result: `22 passed`.

## The three honest gaps (not "already done")

1. **Drift trend is not delegated to EA-0021.** EA-0012 emits drift but does not
   produce a *trend*. EA-0021 owns forecasting/trends platform-wide
   (`forecast/engine.py:111 analyze_trend`). → **C-023 K2** (the EA-0023/EA-0024
   precedent: delegate, don't rebuild).
2. **No EA-0020 advisory recommendation alongside the proposed run.** Optional
   enhancement: emit an EA-0020 advisory recommendation **alongside — never
   replacing** — the existing proposed gated run. → **C-023 K2 (optional)**.
3. **"Continuous drift detection" (scheduling) — deliberately NOT closed here.**
   Scheduling is a platform-wide capability deferred by EA-0008 §13; it belongs to a
   future scheduler EA where it serves every assessment engine
   (EA-0010/0012/0023/0024/0025), not re-implemented inside the config engine.

## Consequence of building it anyway

Two baseline stores (two answers to "desired config state"), two drift detectors
(divergent results on the same asset), two `configuration.drift.detected` emitters
(duplicate findings, doubled remediation proposals, inflated drift counts in EA-0022
reporting), and a split brain in every consumer. Honouring the archive's words would
violate its intent — auditable, non-contradictory governance. This is the second
archive redundancy after IS-018 vs EA-0008 (ECR-0006), indicating the archive was
authored per-topic without cross-topic dedup.

**Deliverable this turn:** proof (this file) + decision (ECR-0015) + the small genuine
remainder (C-023) — not a module.
