# C-023 Configuration Drift Enhancement (IS-026 intent) — Implementation Task Bundle

**Milestone:** C-023 (IS-026 intent, realized as an **EA-0012 enhancement** — **not a
module**)
**For:** Codex (implementer) / Claude Code (reviewer)
**Prerequisites:** EA-0025 merged & green; **`IS-026_Conformance_Analysis.md` and
ECR-0015 read first**; CONVENTIONS + EA-0012 (`assetconfig`), EA-0020, EA-0021 read.
**Definition of Done:** acceptance tests pass on in-memory **and** Postgres where a
store is touched; `ruff` clean; `mypy --strict` clean; `make check` green; nothing
outside EA-0012's existing package; Claude Code sign-off per ticket.

> **This is not a new module. IS-026 is IS-012 restated (ECR-0015).** All work lands
> in **`src/aqelyn/assetconfig/`** (EA-0012). **If `src/aqelyn/configcompliance/` (or
> any new top-level config engine) appears, the milestone has gone wrong** — stop and
> re-read ECR-0015. No second baseline store, no second drift detector, no second
> `configuration.drift.detected` emitter.

## K1 — Verify conformance against shipped code

**Ref:** `IS-026_Conformance_Analysis.md`, ECR-0015, ECR-0007.
**Deliverables:** confirm **each ✅** in the conformance analysis against **shipped
EA-0012 code** (not the spec) — the baseline store, `DriftSnapshot`/`assess_asset`,
`classify`, `drift_to_findings`, and the `aqelyn.config.drift_detected` event all
exist and behave as mapped. **Any ✅ that fails to hold becomes a scoped C-023 EA-0012
ticket here — never a reason to build a second module.** No code change if every ✅
holds; the deliverable is the verified record.
**Acceptance:** the conformance analysis is accepted (or the specific failing rows are
enumerated as follow-up EA-0012 tickets).

## K2 — Drift trend delegation (+ optional advisory recommendation)

**Ref:** conformance gaps 1 & 2; EA-0021 `analyze_trend`; EA-0020 `Derivation`/
recommendation; the EA-0023/EA-0024 delegation precedent.
**Deliverables (in `src/aqelyn/assetconfig/`):**
- **Drift trend delegates to EA-0021.** Add a thin delegation so configuration
  **drift trend** is answered by **EA-0021 `analyze_trend`** — no trend model is
  implemented inside EA-0012 (the EA-0023/EA-0024 pattern). Behaviourally proven with
  a spy that `analyze_trend` is called and its record returned.
- **(Optional) EA-0020 advisory recommendation.** Emit an EA-0020 advisory
  recommendation **alongside — never replacing** — the existing proposed gated
  remediation run. The finding/proposed-run path (`drift_to_findings`) is unchanged;
  the recommendation is additive and advisory-only (no new execution path).
**Constraints:** no new baseline store, drift detector, or `configuration.drift.detected`
emitter; drift detection stays exactly as shipped; **scheduling ("continuous drift")
is out of scope** — deferred to the future scheduler EA (EA-0008 §13).
**Acceptance:** `test_acg_drift_trend_delegates_forecast`; if the advisory
recommendation is added, `test_acg_drift_recommendation_advisory_only` (recommendation
is additive, execution still 0, proposed run unchanged).

---

## Review protocol (Claude Code)

1. **No second module.** All changes are in `src/aqelyn/assetconfig/`. The presence of
   any new config-engine package fails the review outright (ECR-0015).
2. **Conformance verified against shipped code (K1).** Each ✅ traced to real EA-0012
   code, not the spec; failures become scoped EA-0012 tickets.
3. **Trend delegates, not rebuilt (K2).** A spy proves EA-0021 `analyze_trend` is
   called; no trend logic in EA-0012.
4. **Advisory only.** Any recommendation is additive to — never a replacement of — the
   proposed gated run; execution surface stays zero; the drift/finding path is
   unchanged.
5. **Scheduling stays deferred.** No "continuous"/scheduler code lands here.

Merge only on green review; then **report back to the owner** before the next module.
