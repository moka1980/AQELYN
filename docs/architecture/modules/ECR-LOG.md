# Engineering Change Request (ECR) Log

Records approved changes to **Accepted** module specs, so amendments happen
under change control rather than silent edits (per `START_HERE.md`).

| ECR | Against | Status | Summary |
|---|---|---|---|
| ECR-0001 | EA-0005 Knowledge Graph | Accepted | Add a `max_work` enumeration budget to `paths()`. |
| ECR-0002 | EA-0009 Policy Engine | Accepted | Harden condition attribute lookup against dunder traversal. |
| ECR-0003 | EA-0013 Risk Intelligence | Accepted | Tenant-qualify the correlated `Risk.id` to prevent a cross-tenant PK collision. |
| ECR-0004 | EA-0002 Universal Object Model | Accepted | Add `ObjectQuery.exclude_object_types` so a query can bound results to a subset of types. |
| ECR-0005 | EA-0004 Evidence & Integrity | Accepted | Add `EvidenceStore.custody_of()` and explicit intake custody rows for reconstructable custody. |
| ECR-0006 | EA-0018 / IS-018 | Accepted | Realize IS-018 as an orchestration layer above EA-0008, not a second executor. |
| ECR-0007 | cross-cutting (verification method) | Accepted | Grep-based enforcement is insufficient; require behavioural/structural proof. |
| ECR-0008 | EA-0017 Threat Detection | Accepted | `project()` superseded by EA-0021; EA-0017 keeps its S4 stance. |
| ECR-0009 | EA-0022 / IS-022 | Accepted | Override master §28.2/§28.3: a missing/failed executive figure is omitted + recorded, never backfilled with a stale value. |
| ECR-0010 | EA-0022 / IS-022 | Accepted | Composite `Figure.as_of` uses the **stalest** input (`min`), not the newest — a single timestamp must not overstate freshness. |
| ECR-0011 | EA-0023 / IS-023 | Accepted | Exposure is derived from known data; **no `scan()`/`probe()`/`connect()`**. Active scanning is an EA-0008 `scan.active` ActionSpec. Overrides master §20.3 scan endpoint + §28.2/§28.3. |
| ECR-0012 | EA-0024 / IS-024 | Accepted | CVSS/EPSS carried, **never recomputed**; every assessment carries a mandatory `CoverageReport` and is **refused if coverage can't be computed** (not-scanned ≠ clean). Overrides master §12.2 severity-normalization + §28.2/§28.3. |
| ECR-0013 | cross-cutting (unwired-dependency default) | Accepted | An unwired dependency's default implementation MUST be **inert or refusing, never optimistic**. Fixes EA-0024's coverage provider (reported `unscanned=[]`) to refuse. |
| ECR-0014 | EA-0025 / IS-025 | Accepted | Absence ≠ decommission (asset → `unreported`, never retired from silence); `inventory()` declares freshness + fails rather than shrinks; reconciliation **records** conflicts (EA-0006 precedence). Overrides master §28.2. |
| ECR-0015 | EA-0026 / IS-026 | Accepted | **IS-026 is IS-012 restated — do not build EA-0026.** EA-0012 already ships baseline/drift/classify/remediation and the `configuration.drift.detected` event. Realize IS-026's intent as a small EA-0012 enhancement (C-023). |
| ECR-0016 | EA-0027 / IS-027 | Accepted | Identity detection watches **accounts, not people**: no per-person risk score (absent), no insider-threat *prediction*; a **dignity gate** (≥2 corroboration + confidence floor > platform default) is non-negotiable. Overrides master §429 risk-score + §107/261 insider-threat + consumes EA-0017's `behavior.profile.updated`. |
| ECR-0017 | EA-0027 / IS-027 | Accepted | Corroboration independence is keyed on the **signal** (`ref`, and `evidence_id` when present), not on `(kind, ref)` — one occurrence relabelled twice is **one** corroboration, so the ≥2 floor cannot degrade to 1. Undecidable ties count as one. |
| ECR-0018 | EA-0027 / IS-027 | Accepted | Replace the under-specified `detect(subject_ref, signals, tenant_id)` input with a structured `IdentityObservation` carrying detection type and pinned profile/rule versions; the engine renders the account-scoped statement and basis. |

---

## ECR-0001 — `paths()` enumeration work budget

**Raised by:** Claude Code (post-EA-0005 review).
**Severity:** non-blocking hardening.

**Problem.** EA-0005 traversals are bounded, but the bound was uneven. The
Postgres CTE traversals are limited by `LIMIT` (max_nodes) and depth. The
Python-side `paths()` enumeration was bounded only by `max_depth` and
`max_paths` — on a dense graph it could expand a very large number of partial
paths before collecting `max_paths` complete ones, so worst-case effort was not
explicitly capped. This violates the spirit of EA-0005 D2 ("bounded, never
hang").

**Resolution.** Add `max_work: int = 50_000` to `paths()` (§6). It caps the
number of nodes/partial-paths expanded during enumeration; on reaching it,
`paths()` returns the paths found so far rather than continuing. Hard cap
`max_work ≤ 1_000_000`. Captured as **FR-13** and **AC-15**
(`test_kg_paths_work_budget`).

**Impact.** Additive, backward-compatible (new keyword arg with a default).
Implemented via C-002 follow-up ticket **G3a**. No change to other methods or to
the contract of already-passing tests.

---

## ECR-0002 — Policy condition lookup dunder hardening

**Raised by:** Claude Code (post-P1 review).
**Severity:** defense-in-depth hardening.

**Problem.** EA-0009 P1 correctly avoids arbitrary code execution: the condition
interpreter is structured data and contains no `eval`/`exec`/dynamic import
path. However, its dotted attribute lookup used `getattr(current, part)` after a
non-dict hop. With untrusted policy attr-path segments, a path such as
`resource.type.__class__` could traverse Python object internals. This is not a
code-execution issue, but it is an avoidable information-leak surface.

**Resolution.** Attribute lookup is restricted to data mapping traversal only.
Any empty path segment or segment starting with `__` is treated as missing, and
non-mapping values stop traversal rather than calling `getattr`.

**Impact.** Backward-compatible for supported policy data because Decision
requests and compliance resources are dictionaries. Adds an acceptance test that
a dunder attr path yields no match.

---

## ECR-0003 — Tenant-qualify the correlated `Risk.id`

**Raised by:** Claude Code (post-R3 review, PR #52).
**Severity:** blocking correctness — tenant-isolation break.

**Problem.** R2 derived the correlated risk id as `risk:{correlation_key}`, and
`aq_risk.id` is the primary key. A `correlation_key` is caller-controllable and
can be shared across tenants — via an explicit `finding.correlation_id` or an
external `CorrelationSignal.correlation_key` taxonomy (e.g.
`"risk:internet-exposure"`). Two tenants sharing such a key minted the **same
PK**, so the second tenant's `upsert` matched the first tenant's row by id and
raised `CrossTenantReference` — one tenant's risk permanently blocked another
from registering its own. The `(tenant_id, correlation_key)` unique index was
correct; only the PK id lacked a tenant segment. Reproduced empirically during
review (identical id, `CrossTenantReference`). Finding-derived keys embed object
UUIDs and were already collision-free; the defect surfaced only for shared
explicit keys.

**Resolution.** Derive the id as `risk:{tenant_id or 'global'}:{key}`
(`_risk_id`). The tenant id is a UUID (or the literal `global`), so the
`:`-delimited prefix is unambiguous and two tenants sharing a `correlation_key`
now produce distinct ids. Dedupe/versioning semantics are unchanged (still keyed
on `(tenant_id, correlation_key)`).

**Impact.** Changes the format of correlated risk ids (no persisted risks exist
yet — R3 is the first persistence). Adds `test_risk_cross_tenant_correlation_key`
(both backends); updates the one R2 assertion that pinned the old id string.

---

## ECR-0004 — `ObjectQuery.exclude_object_types`

**Raised by:** Claude Code (post-T3 review, PR #58).
**Severity:** blocking correctness (enables the EA-0014 T3 fix).

**Problem.** EA-0014 threat correlation enumerates estate **assets** via
`ObjectStore.query`, then filters the engine's own threat objects
(`threat_indicator`/`actor`/`campaign`) out of the result. But `ObjectQuery`
supports only a single positive `object_type` (or none), and the store applies
`limit` **before** any post-filtering, and returns no pagination cursor. So the
engine's own indicator objects compete with assets for the query budget: in an
estate with many indicators, a `limit`-sized query comes back full of indicators,
which are then stripped, leaving few or **zero** assets — correlation silently
under-matches or returns empty. Reproduced during review (`limit=2`, two matching
assets → `matches=0`, the query returned two `threat_indicator`s).

**Resolution.** Add `exclude_object_types: tuple[str, ...] = ()` to `ObjectQuery`,
honored in the WHERE/predicate of both the in-memory and Postgres stores (so the
`limit` applies to the already-filtered set). Threat `correlate` passes
`THREAT_OBJECT_TYPES`, so the asset budget is spent on assets only. Additive and
backward-compatible (default empty tuple; existing queries unaffected).

**Impact.** New optional `ObjectQuery` field + one predicate in each store.
Adds an object-store contract assertion for the exclusion, an EA-0014 scale test
(indicators far exceeding `limit` no longer starve asset correlation), and folds
in a `truncated`-on-match-limit fix (partial match lists are now reported as
truncated, §11/FR-6).

---

## ECR-0005 — Evidence custody reconstruction API

**Raised by:** Claude Code (EA-0016 spec review / C-013 F1 kickoff).
**Severity:** blocking contract gap for Digital Forensics.

**Problem.** EA-0016 requires chain-of-custody to be reconstructable for
forensic artifacts on both in-memory and Postgres backends. The C-001 evidence
implementation already tracked custody internally, but the public contract was
uneven: the in-memory store exposed a private `custody_of()` helper, while the
Postgres store exposed only `custody_count()`. That allowed count checks but not
the ordered custody reconstruction needed by forensic timelines, packages, and
audits. Also, `EvidenceStore.add()` assigned the hash-chain fields but did not
write an explicit intake custody row, despite EA-0004's contract text saying
`add()` logs custody.

**Resolution.** Add `async custody_of(evidence_id) -> list[dict[str, object]]`
to the EA-0004 `EvidenceStore` protocol. Both in-memory and Postgres
implementations return ordered custody rows. `add()` now records an `intake`
custody entry using the evidence collector, and Postgres DDL permits
`intake` alongside `read`, `export`, and `package`.

**Impact.** Additive contract surface plus a stricter fulfillment of the
existing custody requirement. Existing callers are unaffected; tests now assert
ordered `intake` then `read` custody on both backends. EA-0016 F1 can depend on
the public `EvidenceStore` protocol instead of backend-specific helpers.

---

## ECR-0006 - IS-018 realized as orchestration above EA-0008 (not a second executor)

**Raised by:** planning (EA-0018 spec pass).
**Severity:** architectural - would otherwise break the platform's §0 safety spine.

**Problem.** The archive's IS-018 component list (Playbook Engine, Approval
Engine, Response/Automation Engine, Containment/Remediation/Recovery Engines)
substantially duplicates **EA-0008 Workflow**, which is already implemented and
is the platform's single acting authority:

- IS-018 "Playbook Engine" vs EA-0008 `Playbook` (declarative, versioned, steps);
- IS-018 "Approval Engine" vs EA-0008 `Approval` gates (S4);
- IS-018 "Response/Automation Engine" vs EA-0008 gated run lifecycle + the
  `finding.automation.eligibility` ceiling (S3);
- IS-018 "Containment/Remediation/Recovery Engines" vs EA-0008 `ActionHandler`s,
  which EA-0008 §13 explicitly assigns to connectors.

Implementing IS-018 literally would create a **second acting path** with its own
playbooks and its own approvals, able to produce effects outside the gates every
prior module upholds. That would undo the §0 discipline proven across thirteen
modules.

**Resolution.** IS-018 is realized as the **orchestration layer above EA-0008**.
EA-0018 §0 carries a component-by-component mapping table so no archive scope is
dropped: playbooks/approvals/execution are **reused from EA-0008**; the genuinely
new contributions are multi-phase **response campaigns** composed of gated runs,
**automation triggers** bounded by eligibility + Policy (tighten-only; destructive
never auto-started), **approval routing/escalation** (routing is not granting),
**recovery verification**, and **response metrics** (MTTD/MTTR). The orchestrator
has **no privileged path** - it calls the same public `execute()` any caller does,
and EA-0008 re-validates every gate at run time.

**Impact.** No change to EA-0008. EA-0018 gains §0 (scope reconciliation) and §1
(safety boundary S1-S5), with `test_resp_no_privileged_path` (handler spy) and
`test_resp_no_auto_destructive` enforcing the invariant. The archive master is
unchanged; this spec governs implementation (per `modules/README.md`).

---

## ECR-0007 - Verification standard: behavioural/structural proof over textual checks

**Raised by:** the C-016 (EA-0019) L4 review, which found implementation code
**obfuscated to slip past an over-broad grep**. The reviewer fixed the test
honestly rather than accepting the evasion.

**Problem.** Several specs (EA-0014 NFR-1, EA-0016 NFR-2, EA-0017 NFR-3,
EA-0018 NFR-1, EA-0019 NFR-2) phrase an invariant as "enforced by test **and
grep**". A textual check is a weak guarantee: it can be defeated by obfuscation
without changing behaviour, and - worse - it can create a false sense of
assurance in review. An invariant that only a grep protects is not protected.

**Resolution (binding going forward).** Safety invariants SHALL be enforced
**structurally** (make the violation unrepresentable - type, constructor, or
store gate) and/or **behaviourally** (assert the effect, e.g. a spy proving zero
direct handler invocations; `replay(derivation) == result`). Grep MAY remain as a
cheap secondary signal but SHALL NOT be the primary or sole evidence for any
invariant.

**Applied first in EA-0020**, whose central invariant is deliberately structural:
a recommendation without a replayable derivation is **unrepresentable**, and the
review protocol explicitly instructs *"do not substitute a grep; the invariant is
behavioural"*.

**Retroactive impact.** No shipped behaviour is wrong - the existing modules
back their invariants with real behavioural tests (mutation spies, refusal tests,
fail-closed tests) in addition to the grep wording. This ECR corrects the
*standard and the wording*: reviewers SHALL treat the behavioural test as the
proof, and no future spec SHALL rest an invariant on a textual check alone.

---

## ECR-0008 - EA-0017 `project()` superseded by EA-0021

**Raised by:** planning (EA-0021 spec pass).
**Severity:** scope collision (one capability, two owners).

**Problem.** EA-0017 §S4 scoped "predictive analytics" narrowly and shipped
`project(subject_ref, horizon_days) -> Projection` (EA-0017 line 156) as an
advisory feature inside the detection engine. EA-0021 is a full forecasting
engine (methods, intervals, trends, scenarios, outcome scoring). Left as-is the
platform would have **two projection paths with different guarantees** - exactly
the duplication this project has rejected everywhere else (one capability, one
owner).

**Resolution.** **EA-0021 owns forecasting platform-wide.** EA-0017's `project()`
is **deprecated** and SHALL delegate to `ForecastingEngine.forecast(...)`; it
SHALL NOT keep an independent projection implementation. EA-0017's **S4 stance**
(predictions are advisory, never findings, never evidence) is **retained and
generalised** by EA-0021 §1 S3, which strengthens it further with mandatory
uncertainty intervals (S4), outcome scoring (S5), and the no-automation rule
(S7).

**Impact.** Non-breaking at the call site (same advisory semantics, richer
result). EA-0017's `Projection` type is superseded by EA-0021's `Forecast`.
Sequencing: EA-0021 (C-018) lands the engine, then the EA-0017 delegation is a
small follow-up ticket; until then EA-0017's `project()` remains as shipped and
is not extended.

**Also recorded here:** IS-021 requested a **Confidence Engine** (the third such
request, after IS-020) and an **Explainability Engine** (the second). Both are
mapped to existing owners - **EA-0006 Trust** and **EA-0020 `Derivation`/
`replay`** respectively - per EA-0021 §0. The platform keeps **one confidence
authority and one explainability mechanism**.

---

## ECR-0009 - EA-0022 overrides master §28.2/§28.3 (a missing number must look missing)

**Raised by:** planning (EA-0022 spec pass).
**Severity:** architectural - the master's stated failure handling would license
the exact un-evidenced verdict this module exists not to produce.

**Problem.** The EA-0022 archive master, in its failure-handling section, permits
two behaviours that are safe for an operational dashboard but **corrosive in an
executive report**:

- **§28.2 Dashboard Failure - "Fallback metrics displayed".** Substituting a
  fallback/last-known value for a figure that could not be read.
- **§28.3 KPI Calculation Failure - "Previous values retained".** Carrying a prior
  period's value forward when the current calculation fails.

In a *live dashboard* a last-known value is defensible. In an **issued executive
report** it is a lie: a board reads a retained/fallback number as the current,
computed figure, with full provenance implied. A stale value presented as current
is worse than a gap - it severs the evidence chain precisely where a non-expert
cannot see the seam. This directly contradicts EA-0022 S1 (no number without
provenance) and S5 (material exceptions cannot be omitted).

**Resolution.** For **issued reports and KPI records** (not live dashboards), a
figure that cannot be read/computed is **omitted and recorded in an `excludes`
list**, and SHALL NOT be zeroed, defaulted, or backfilled with a prior value. A
missing number **looks missing**. §28.2's "fallback metrics" is scoped to the
**live dashboard** surface only (which S3 already distinguishes from a frozen
report); §28.3's "previous values retained" is **not** applied to issued reports.
Captured as EA-0022 **FR-9**, **NFR-2**, **§12**, and **AC-9**
(`test_ex_missing_kpi_excluded`).

**Impact.** Governs implementation only; the archive master is unchanged (per
`modules/README.md`, the spec governs). No prior module behaviour changes. This
is the executive-layer application of the same discipline EA-0021 used for
`unscoreable` outcomes (record + exclude, never flatter the number).

---

## ECR-0010 - EA-0022 composite `Figure.as_of` uses the stalest input (min)

**Raised by:** owner (post-EA-0022 as_of review), pushing back on the reviewer's
"arguable, not wrong" call.
**Severity:** honesty correctness (small), on shipped EA-0022 code.

**Problem.** EA-0022 X2 set a composed KPI's `Figure.as_of` to
`max(input.as_of)` - the **newest** contributing timestamp. A composite is only as
fresh as its **stalest** input; reporting the newest timestamp overstates
freshness in exactly the way EA-0022 §1 exists to prevent (a single number
implying more currency than the data supports). The reviewer had called `max`
"arguable, not wrong"; the owner's position is that it is wrong.

**Resolution.** A composed `Figure.as_of` SHALL be the **minimum** (stalest) of
its inputs' `as_of`. "When was this calculated" is a distinct fact already carried
by `computed_at`, so both stay separable. (Acceptable alternative, if ever
preferred: surface **both** bounds; what SHALL NOT stand is a single timestamp
implying more freshness than the data supports.) `min` costs nothing.

**Impact.** One-line change in `executive/kpi.py` (`max(...)` -> `min(...)`) plus a
test asserting a composite of differently-dated inputs takes the **oldest**
`as_of`. Existing X2 tests use a single timestamp per case, so they are unaffected.
No other module changes.

---

## ECR-0011 - EA-0023 derives exposure from known data; no scanning

**Raised by:** planning (EA-0023 spec pass).
**Severity:** architectural - the master specifies an active-scan surface that
would make this engine touch systems it does not own.

**Problem.** The EA-0023 archive master specifies **active scanning as a native
capability**: §20.3 lists `POST /attack-surface/scan`, §12.1/§24 describe
"continuous discovery", and §28.2/§28.3 permit a "fallback assessment" and a
"previous score retained" on failure. A scan is **not read-only from the target's
point of view**: it touches a machine the platform does not own, can disrupt
fragile services, trips other parties' detection, and pointed at the wrong netblock
may be unlawful. A native `scan()` inside a detection engine is exactly the
uncontrolled acting path the platform's §0 discipline rejects. The fallback/retained
clauses repeat the EA-0022 §28.2/§28.3 hazard (ECR-0009): a fabricated or stale
exposure verdict presented as current.

**Resolution.** EA-0023 has **no `scan()`/`probe()`/`connect()` method**. The
attack surface is **derived from data the platform already holds** (EA-0012
inventory, EA-0019 telemetry, EA-0011 access, EA-0005 KG). Active scanning, when it
arrives, is **not** a method here - it is an **EA-0008 `ActionSpec`**: capability
**`scan.active`**, at minimum **reversible**, **Policy-authorized** (scope is the
whole safety question), delivered by a **connector**, requested as a **proposed
gated run**; this engine consumes the results as **stored data, unchanged**.
Unmatched reachability is recorded **`unknown` and flagged, never defaulted to
internal** (S2). Master §28.2/§28.3 are overridden as in ECR-0009: a failed
analysis is `unknown`+flagged, a failed re-score is stale/unavailable - never faked.

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0023 §0.1, **S1/S2/S9**, **FR-1/2/11/12**, **NFR-1**, and
**AC-1/2/3/13/14**. The no-probing invariant is proven **structurally** (no scan
method exists) and **behaviourally** (a network spy asserts zero outbound attempts),
per ECR-0007.

---

## ECR-0012 - EA-0024 carries CVSS/EPSS (never recomputes) and refuses coverage-blind assessments

**Raised by:** planning (EA-0024 spec pass).
**Severity:** architectural - the master would license both silent divergence from
the severity authority and "not scanned" masquerading as "clean".

**Problem.** The EA-0024 archive master (a) implies the engine **recomputes**
severity - §12.2 lists "Severity normalization" and §28.3 "Risk recalculated" - and
(b) repeats the fabrication/stale hazard - §28.2 "**Fallback assessment generated**"
and §28.3 "**Previous assessment retained**". It is also **silent on coverage**: a
vulnerability assessment that does not account for what was *not* scanned reports the
unscanned estate as implicitly clean. Two failure modes follow: a severity that
silently diverges from CVSS/EPSS (the published authority), and an assessment whose
green surface hides an unscanned or stale fleet.

**Resolution.** (1) **CVSS/EPSS are carried verbatim with their source and never
recomputed** (S2) - recomputation invites silent divergence from the authority.
(2) Every `VulnerabilityAssessment` carries a **mandatory `CoverageReport`**
(scanned/unscanned/stale); **if coverage cannot be computed, the assessment is
refused** (`CoverageUnavailable`), never issued clean (S4) - *"not scanned"* is
never *"clean"*, the same discipline as EA-0023's `unknown` reachability (ECR-0011)
and EA-0022's "a missing number must look missing" (ECR-0009). (3) Master §28.2/§28.3
are overridden: a failed correlation/prioritization is recorded degraded/unavailable,
never a fabricated fallback or a silently retained prior assessment (S7).

**Also recorded here:** every `VulnPriority` is **replayable composition** - an
EA-0020 `Derivation` naming each factor, its owner source, and its weight (S1); and a
vulnerability is treated as a **scanner's claim** carrying EA-0006 Trust confidence
(S3), never a bare fact. These are spec hardenings the master did not ask for.

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0024 **S1-S7**, **FR-2/4/5/6/7/11**, **NFR-1/2/3**, and
**AC-2/4/5/6/7/8/9/14**. Proven **structurally** (priority unrepresentable without a
replaying derivation; assessment refused without coverage) and **behaviourally** (a
spy proves no severity recomputation), per ECR-0007.

---

## ECR-0013 - An unwired dependency defaults to inert/refusing, never optimistic

**Raised by:** the C-021 V5 review, which found EA-0024's wired coverage provider
reporting `unscanned=[]` (fully-covered) when it could not actually see the asset
universe.
**Severity:** correctness of the safety posture - an unwired control that reports
"all good" is worse than one that reports nothing.

**Problem.** EA-0024 V5 wired `StoreBackedVulnerabilityCoverageProvider`, whose
`coverage()` returns `scanned = {ingested asset refs}` and **`unscanned = []`,
`stale = []` always** - it knows only the ingested vulnerability store, not the
full asset universe. So in the wired runtime every `assess()` looks fully-covered,
which is exactly the *"not scanned = clean"* outcome EA-0024 S4 exists to prevent.
The V4 *structure* is correct (assess refuses if coverage cannot be computed); the
V5 *wiring* got the default backwards - optimistic instead of inert.

**Resolution (binding, cross-cutting).** When a dependency is not yet wired to an
authoritative source, its default implementation SHALL be **inert or refusing,
never optimistic**. A coverage provider that cannot compute true coverage SHALL
**refuse** (`CoverageUnavailable`) rather than report an empty `unscanned`. EA-0019
established the pattern (inert reference checkers); EA-0024's wiring is corrected to
match. The authoritative fix is EA-0025 `inventory()` as the coverage denominator,
wired in C-022 **N6**; until then the default refuses.

**Impact.** Small change to `aqelyn.vuln.service` (the default coverage provider
refuses instead of reporting empty `unscanned`) plus the health/wiring semantics
that follow, and the generalization above as a standing rule for every future
"not-yet-wired dependency". No shipped invariant is weakened - the system becomes
**more** honest (refuses rather than falsely reassures).

---

## ECR-0014 - EA-0025 inventory is the authoritative, freshness-declaring denominator

**Raised by:** planning (EA-0025 spec pass).
**Severity:** architectural - a silently shrinking inventory makes twenty engines
report all-clear about a smaller world.

**Problem.** The EA-0025 archive master (a) permits **§28.2 "previous inventory
retained"** on failure - a silent stale/shrink - and (b) is **silent on how an
asset leaves the inventory**, so a naive "continuous discovery" would let a feed
that goes quiet retire assets. Both are the same failure: the inventory shrinks or
staleds without anyone deciding it should, and every downstream engine
(exposure coverage, vulnerability coverage, risk scope) then reports **all-clear of
a smaller or older world** - cascading blindness that looks like good news.

**Resolution.** (1) **Absence of evidence is not evidence of absence** - an asset
absent from a feed becomes **`unreported`**, never `decommissioned`; decommissioning
requires **positive evidence or an attributed EA-0008 decision**, and
`sweep_unreported` **refuses** when source health is `unknown`. (2) **`inventory()`
declares its own freshness** (`as_of` + per-source), and a **degraded store makes
`inventory()` fail rather than shrink** (`InventoryUnavailable`) - overriding master
§28.2. (3) **Reconciliation records conflicts** rather than smoothing them:
precedence resolves via **EA-0006 source reliability** (not last-writer, not source
order), every conflict stays on the record with each candidate's value + reliability,
and ties land **unresolved and surfaced**.

**Also recorded here:** `inventory()` is the authoritative "which assets exist" that
EA-0023 (asset set) and EA-0024 (coverage denominator) were missing - **not** network
access. C-022 **N6** wires both seams, and closes ECR-0013's coverage gap with a real
inventory-backed denominator. This is **not** the connector turn (discovery is
handed-in; no ADR-0001 refresh).

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0025 **S2/S3/S4**, **FR-2/4/5/6/7**, **NFR-1/2**, and
**AC-2/3/4/5/6/7/8/9/17**. Proven behaviourally (degraded store fails; sweep refuses
on unknown health; conflicts + ties on the record), per ECR-0007.

---

## ECR-0015 - IS-026 is IS-012 restated; do not build EA-0026

**Raised by:** owner (IS-026 spec pass), verified by Claude Code against shipped code
(K1).
**Severity:** architectural - building it would fork the platform's configuration
authority.

**Problem.** IS-026 (Configuration Compliance & Drift Intelligence) is **not a
component overlap with EA-0012 (Asset & Configuration Governance) - it is the same
engine restated.** The decisive tell: both archive masters declare the **identical**
event `configuration.drift.detected` (EA-0012 master lines 787/1557/1959; IS-026
master line 294). Types map one-for-one (`BaselineDefinition`->`Baseline`,
`DriftAssessment`->`DriftSnapshot`, `ConfigurationRemediation`->finding + proposed
run), components map, and EA-0012 **shipped all of it in C-009** (green on `main`):
`Baseline`/`BaselineStore`, `DriftSnapshot`/`assess_asset`, `classify`,
`drift_to_findings`, and the `aqelyn.config.drift_detected` event. Every mapping is
verified against shipped code in `IS-026_Conformance_Analysis.md`.

Building `EA-0026` as written would give the platform two baseline stores (two
answers to "desired config state"), two drift detectors (divergent results on the
same asset), two `configuration.drift.detected` emitters (duplicate findings, doubled
remediation proposals, inflated drift counts in EA-0022 reporting), and a split brain
in every consumer. That is the failure this project has rejected eight times - here in
its most extreme form. This is the **second** archive redundancy after IS-018 vs
EA-0008 (**ECR-0006**), indicating the archive was authored per-topic without
cross-topic dedup: a documentation artefact, not a requirement.

**Resolution.** **No `EA-0026` engine is built.** IS-026's intent is realized as a
small **two-ticket EA-0012 enhancement (C-023)** - not a module:
1. **K1** - accept the conformance mapping only after each ✅ is verified against
   **shipped code**; any ✅ that fails becomes a C-023 ticket (never a reason to build
   a second module).
2. **K2** - delegate configuration **drift trend** to **EA-0021** (`analyze_trend`,
   the EA-0023/EA-0024 precedent), and *optionally* emit an **EA-0020 advisory
   recommendation alongside - never replacing** - the existing proposed gated run.

The C-023 bundle states outright: **if `src/aqelyn/configcompliance/` appears, the
milestone has gone wrong.** IS-026's "continuous drift detection" (scheduling) is
**deliberately deferred** to a future scheduler EA (EA-0008 §13), where it will serve
every assessment engine (EA-0010/0012/0023/0024/0025) rather than being re-implemented
inside the config engine.

**Going-forward discipline (adopted).** Before specifying any remaining archive
module, **grep its declared event types and data types against shipped modules
first.** Identical event names are a reliable restatement signal; that single check
caught IS-026 immediately.

**Impact.** No new module, no repository change beyond docs. IS-026's intent is met at
its turn, sequentially, with evidence - without forking the platform's config
authority. Master's Next after IS-026 is IS-027 (Identity Threat Detection &
Behavioral Analytics), which the same event/type check should precede.

---

## ECR-0016 - EA-0027 watches accounts, not people: dignity gate, no person-scoring

**Raised by:** planning (EA-0027 spec pass).
**Severity:** architectural + ethical - this is the only engine that analyses named
human beings, and it sits directly against EA-0021 **S8** ("predictive suspicion of
named people is out of scope, permanently").

**Problem.** The EA-0027 archive master demands exactly what this boundary exists to
prevent: an **"Identity risk score"** (§429) - a UEBA per-user number attached to a
colleague, rising and decaying invisibly; **"insider threat identification"**
(§107/261) - *prediction* of who someone will become, for which no evidence exists and
whose cost is borne by a person; and it re-declares `behavior.profile.updated` (§300),
an event **EA-0017 already owns**. Individual behavioural anomalies are low-prevalence,
so even a strong detector produces mostly false positives - and here **each false
positive is a colleague wrongly suspected.**

**Resolution.** The engine surfaces **observed, evidence-backed, account-scoped
events** a human then judges - never a standing verdict about a person.
1. **The account is the subject; the person is not the finding** - *"this credential
   shows impossible travel,"* never *"this user is suspicious."*
2. **A dignity gate, non-negotiable.** An identity detection requires **both** ≥ 2
   independent corroborating signals **and** a confidence floor **strictly above the
   platform default** - the one detector deliberately made *less* sensitive. A config
   lowering corroboration below 2 or dropping the floor to the default is **rejected at
   construction** (EA-0027 §11). The guarantees are structural, not knobs.
3. **No per-person risk score - absent, not disabled.** No `risk_score`/`user_score`
   type or method exists; the review's first check is its absence.
4. **Right of reply by construction** - every detection is evidence-backed, replayable
   against pinned versions, and human-reviewed before consequence, so the accused can be
   shown exactly what was observed.
5. **Reuse, not rebuild** - behavioural profiles are **EA-0017**'s (keyed by an identity
   `subject_ref`); entitlements are **cited from EA-0011**, never merged; `behavior.
   profile.updated` is **consumed** from EA-0017, never re-emitted. No individual's
   future behaviour is forecast (EA-0021 S7/S8).

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0027 **S1-S8**, **FR-1..5/11/12**, **NFR-1/2/3**, and the §11
dignity gate; the dignity gate (C-024 **I2**) is built **before** any detection can be
raised, and the review's first check is that no person-scoring type/method exists.
Proven structurally (unrepresentable sub-threshold detection, unconstructable
knob-lowering config, absent score surface) per ECR-0007.

---

## ECR-0017 — corroboration independence is keyed on the signal, not on its label

**Raised by:** Claude Code (C-024 I2 review, PR #141).
**Severity:** blocking for C-024 I3 — it sets the numeric value of the dignity gate's
corroboration floor, and under EA-0027 S3 a weakened floor is a wrongly-suspected
colleague.

**Problem.** EA-0027 S3/FR-1 require "corroboration from **≥ 2 independent** signals"
but never define what makes two `SignalRef`s independent. I2 (`dignity.py`) resolved
it as the tuple `(kind, ref)`. Constructed behaviourally against the shipped gate:

```
dignity_gate([SignalRef(kind="auth",    ref="evt:42"),
              SignalRef(kind="session", ref="evt:42")], 0.9, config)  -> True
```

One underlying occurrence, reported under two `kind` labels, satisfies a floor whose
entire purpose is to require **two** things to have happened. The floor is then
nominally 2 and effectively 1 — and it degrades exactly where the platform is least
able to notice, because whichever upstream collector labels one event twice does so
for *every* event of that shape. Nothing in the module is wrong by its own reading;
the spec is simply silent, and silence resolved toward the *more* sensitive detector
in the one module the spec says must be deliberately **less** sensitive (S3).

**Resolution.** Independence is a property of the **signal**, not of its label.

1. **The independence key is `ref`** — one occurrence is one corroboration, regardless
   of how many `kind`s report it. Two `SignalRef`s sharing a `ref` collapse to one.
2. **`evidence_id` collapses too, when present** — two distinct `ref`s backed by the
   same `evidence_id` are one signal seen twice, not two. Absent `evidence_id` never
   merges (fail-closed toward *fewer* corroborations, never more).
3. **Counting is the gate's job, not the caller's.** `dignity_gate` de-duplicates
   internally; no caller may pre-count and pass a number. A caller able to assert its
   own corroboration count is a knob (S3/§11).
4. **Ties toward refusal.** Where independence is undecidable, the signals count as
   one. Dropping a true detection costs a missed alert; inflating corroboration costs
   a person.

**Impact.** Amends EA-0027 §4 (**Corroboration**), §5 (`SignalRef`), FR-1/FR-2 and
adds **AC-19** (`test_idt_corroboration_independence_key`). No master override — the
archive is silent here; this tightens an under-specified floor rather than overriding
a demand. Implemented in C-024 **I3**, where `detect` first calls the gate; I2's
`(kind, ref)` key is superseded. Proven behaviourally per ECR-0007: construct two
`SignalRef`s over one `ref`/`evidence_id` and assert the gate refuses.

---

## ECR-0018 — make identity-detection replay inputs explicit

**Raised by:** Codex (C-024 I3 implementation).
**Severity:** blocking ambiguity — the Accepted interface cannot supply data its
required output must pin.

**Problem.** EA-0027's Accepted `detect(subject_ref, signals, tenant_id)` signature
requires the resulting derivation to pin both profile and rule versions, but carries
neither version, the detection type, nor the observation time. I3 cannot infer those
values without inventing state or silently choosing "latest", which would break the
right-of-reply guarantee when profiles or rules later change. Allowing caller-authored
statement/basis fields would also permit verdict-like prose to bypass S2.

**Resolution.** Replace the under-specified arguments with a structured
`IdentityObservation`: account-scoped `subject_ref`, `detection_type`, signals,
`profile_ref` + `profile_version`, `rule_ref` + `rule_version`, and `detected_at`.
`detect(observation, tenant_id)` obtains confidence from EA-0006, runs the dignity
gate first, and only then constructs the statement, basis, and replayable derivation.
The derivation is accepted only when replay, result match, and source/pin match all
hold; the store repeats those checks at the persistence boundary.

**Impact.** I3 interface and reference computation only. No prior shipped caller
exists, and no later I4/I5 API is changed. This makes the spec's existing S2/S3/S7,
FR-2/6/10, and AC-6/7/11 implementable without an implicit "latest" choice.
