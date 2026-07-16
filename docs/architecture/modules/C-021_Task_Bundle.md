# C-021 Vulnerability Intelligence & Prioritization - Implementation Task Bundle

**Milestone:** C-021 (Vulnerability Intelligence & Prioritization, EA-0024)
**For:** Codex (implementer) / Claude Code (reviewer)
**Prerequisites:** EA-0023 merged & green; EA-0024 spec **Accepted**; **EA-0024 §0, §0.1 (inherited) and §1 read first**; CONVENTIONS + EA-0004/0006/0007/0008/0012/0014/0018/0020/0021/0023 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres where a backing store is required; `ruff` clean; `mypy --strict` clean; **CVSS/EPSS carried, never recomputed; every assessment carries a `CoverageReport` or is refused; every `VulnPriority` replays; no scan/patch/execute surface**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0024 §1 first.** A severity score is not a priority. This engine does not
invent the answer - it **composes** it from owners that already exist (EA-0014
exploited, EA-0023 reachable, EA-0007 cost, EA-0012 already-blocked, EA-0006 scanner
trust) plus carried CVSS/EPSS, and it is honest about coverage. If a needed behavior
is not in the spec, raise an ECR.

**Verification standard (ECR-0007):** invariants are structural and behavioural.
For this module: a `VulnPriority` without a replaying `Derivation` is
unrepresentable; an assessment without a computable `CoverageReport` is refused; a
spy proves no severity recomputation; no public `scan`/`patch`/`execute` method
exists. Do not substitute a grep for the proof.

## Target source layout

```
src/aqelyn/vuln/
|-- __init__.py       # exports engine, service, stores, types, register_vuln_events
|-- models.py         # CarriedScore, VulnBasis, VulnerabilityRecord, VulnPriority,
|                     #   CoverageReport, Disposition, VulnerabilityAssessment,
|                     #   RemediationPlan, VulnConfig (V1)
|-- engine.py         # ingest/disposition (V2), prioritize+derivation (V3),
|                     #   assess/coverage/recommend/raise/trend (V4)
|-- store.py          # VulnerabilityStore protocol + validators (V2)
|-- memory.py         # in-memory store (V2)
|-- postgres.py       # Postgres store + DDL (V2)
`-- service.py        # VulnerabilityIntelligenceService(AQService) + register_vuln_events (V5)
tests/vuln/           # acceptance suite (in-memory + Postgres)
```

Suggested id prefixes (register in CONVENTIONS §9): `vln` (vulnerability_record),
`vpr` (vuln_priority), `vas` (vuln_assessment), `rem` (remediation_plan).

---

## V1 - Types, config, taxonomy & no-recompute/no-scan surface

**Spec:** §0.1 (inherited), §1 (S2/S3), §5, §8 FR-1/2/3, §10.
**Deliverables:** the models; `CarriedScore` names its `source` (CVSS/EPSS carried
verbatim); `VulnerabilityRecord` requires a `scanner` + non-empty `basis` and
carries EA-0006 `confidence`; `Severity` is a carried enum (not computed);
`VulnConfig`; error codes (`VulnConfigInvalid`, `VulnBasisMissing`,
`CoverageUnavailable`, `VulnNotFound`, `VulnNotReplayable`) in `conventions.errors`
+ CONVENTIONS §9. **No public `scan`/`patch`/`execute` method or socket/network
dependency.**
**Depends on:** CONVENTIONS, EA-0020 `Derivation` types, EA-0004 evidence refs.
**Acceptance:** `test_vuln_scanner_basis_required`, `test_vuln_cvss_carried_not_recomputed`,
`test_vuln_no_scan_surface`, `test_vuln_config_invalid`.

## V2 - VulnerabilityStore + ingest + dispositions

**Spec:** §6, §7 ingest/disposition, FR-1/2/3/8/12, S3/S5.
**Deliverables:** `VulnerabilityStore` protocol, in-memory + Postgres stores + DDL;
contract suite; tenant scoping; append-only history; `ingest` carries handed-in
scanner/CVE records **verbatim** (CVSS/EPSS unchanged, `scanner` + `basis`
required); `disposition` records an attributed, durable `Disposition`
(`actor`+`reason`+`kind`), and on re-ingest of a suppressed vuln sets
`reasserted_by_scanner=True` and keeps it counted (never silently dropped).
**Depends on:** V1.
**Acceptance:** `test_vuln_store_contract[inmemory]`, `test_vuln_store_contract[postgres]`,
`test_vuln_confidence_from_trust`, `test_vuln_disposition_attributed`,
`test_vuln_disposition_reasserted`.

## V3 - Prioritization: owner composition + replayable derivation

**Spec:** §1 (S1/S2), §7 prioritize, FR-2/4/5, NFR-1/3.
**Deliverables:** `prioritize` reads each factor **from its owner** - EA-0014
(exploited), EA-0023 (reachable), EA-0007 (mission cost), EA-0012 (already blocked),
EA-0006 (scanner trust) - plus carried CVSS/EPSS; composes a score and builds an
EA-0020 `Derivation` naming **each factor, its source, and its weight**; rejects if
`replay(derivation) != result` (`VulnNotReplayable`). **No owner value is
recomputed**; CVSS/EPSS pass through unchanged.
**Depends on:** V2.
**Acceptance:** `test_vuln_priority_replayable`, `test_vuln_priority_replay_mismatch`,
`test_vuln_factors_from_owners`, `test_vuln_cvss_carried_not_recomputed` (composition path).

## V4 - Assess (coverage or refuse), findings, advisory remediation, trend

**Spec:** §1 (S4/S6/S7), §7 assess/recommend/raise, FR-6/7/9/10/11/15, NFR-2.
**Deliverables:** `assess` computes the `CoverageReport` (scanned/unscanned/stale)
**first**; **if coverage cannot be computed, refuse** (`CoverageUnavailable`) - an
assessment without coverage reports "not scanned" as "clean"; unscanned/stale assets
are reported, never counted clean/remediated; a failed correlation/prioritization is
recorded degraded/unavailable, **never a fabricated fallback or a silently retained
prior assessment**; `recommend` emits an advisory `RemediationPlan` proposing an
EA-0018 campaign shape (no execution); `raise_vulnerability` raises a material vuln
as an EA-0013-consumable `Finding` (non-actionable, no new `SignalRef`); `trend`
delegates to EA-0021.
**Depends on:** V3.
**Acceptance:** `test_vuln_coverage_mandatory`, `test_vuln_coverage_unavailable_refuses`,
`test_vuln_unknown_not_clean`, `test_vuln_failure_not_faked`,
`test_vuln_remediation_advisory_only`, `test_vuln_raise_finding_path`,
`test_vuln_trend_delegates_forecast`.

## V5 - Service + events

**Spec:** FR-13, §11.
**Deliverables:** `VulnerabilityIntelligenceService` (`AQService`, name
`"vuln_engine"`) + `register_vuln_events`; in-memory and Postgres kernel-factory
wiring using the established `TYPE_CHECKING` + in-function import pattern; health
reflects owner-read availability + config validity.
**Depends on:** V4.
**Acceptance:** `test_vuln_service_health`.

---

## Review protocol (Claude Code) - a number is not a priority

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **Replayable composition.** Every `VulnPriority` carries an EA-0020 `Derivation`
   naming each factor + source + weight; `replay == result`; tamper → rejected. This
   is behavioural proof, not a grep.
2. **CVSS/EPSS carried, never recomputed.** A spy / round-trip proves the published
   severity passes through unchanged - the engine originates no severity.
3. **Coverage or refuse.** Every assessment carries a `CoverageReport`; if coverage
   can't be computed, the assessment is **refused**, not issued clean. Unscanned/stale
   is never reported clean.
4. **A vulnerability is a scanner's claim.** Every record names its scanner and carries
   EA-0006 Trust confidence; no bare assertions.
5. **Dispositions are attributed + durable + counted.** Suppression records who/why,
   survives re-ingest (`reasserted_by_scanner`), and is counted - never invisible.
6. **Reuse, not rebuild.** Factors read from EA-0014/0023/0007/0012/0006; trend
   delegates to EA-0021; no second exploit/severity/trend model.
7. **Advisory only.** `RemediationPlan` proposes an EA-0018 campaign; there is no
   scan/patch/execute surface; material vulns flow through the existing `FindingStore`.
8. **Failure looks failed.** A failed assessment is degraded/unavailable, not a
   fabricated fallback or a silent stale assessment.
9. **Service import discipline.** The final ticket must avoid the R5/T5 circular
   import trap: `TYPE_CHECKING` imports plus in-function runtime imports.

Merge only on green review; then **report back to the owner** before the next module.
