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
| ECR-0019 | EA-0027 / IS-027 | Accepted | Make I4's IAG identity input and append-only right-of-reply record explicit: `IdentityObservation.identity_id` delegates to EA-0011; one evidenced `IdentityReview` materializes reviewed status without mutating the detection row. |
| ECR-0020 | EA-0028 / IS-028 | Accepted | Realize CSPM as a verdict-free normalization + routing layer over existing owners, with explicit partial-route outcomes and provider deletion mapped to EA-0025 `unreported`, never decommissioned by silence. |
| ECR-0021 | EA-0028 / IS-028 | Accepted | Close the two soft spots in EA-0028's verdict boundary: `native_facts` keys MUST equal `field_provenance` keys (nothing enters normalized state without a declared raw source), and CSPM does **not** emit `aqelyn.cloud.misconfiguration_detected` — an EA-0012 cloud-baseline failure is EA-0012's event, filtered by cloud object_type. |
| ECR-0022 | EA-0028 / IS-028 | Accepted | Make the normalized cloud record tenant-owned and every store read explicitly tenant-scoped; the Accepted draft otherwise could not satisfy CONVENTIONS §5 or AC-10 on Postgres. |
| ECR-0023 | EA-0028 / IS-028 | Accepted | ECR-0021's provenance binding is top-level only, so an invented verdict one level down (`native_facts["tags"]["posture_grade"]`) still passes. `native_facts` values are constrained to scalars or lists of scalars: structured provider material belongs in raw EA-0004 evidence, and every normalized key is then provenance-bound. |
| ECR-0024 | EA-0028 / IS-028 | Accepted | Make selective flattening explicit: config maps each normalized fact key to an RFC 6901 JSON Pointer in the handed-in raw provider record; generic provider-block flattening is forbidden. |
| ECR-0025 | EA-0028 / IS-028 | Accepted | A configured fact path missing from a later snapshot silently deletes a previously-known fact. Absence is **unknown**, not a change: the fact is retained with its last-known value, marked `unreported`, and the object is flagged — never dropped without trace (the ECR-0014 rule at field level). |
| ECR-0026 | EA-0028 / IS-028 | Accepted | Y3 routes a typed, evidence-backed `CloudRouteEnvelope` containing the full normalized object to owner adapters. The six heterogeneous owner APIs are not rewritten, and no adapter may strip ECR-0025's `unreported_facts`; provider deletion is recovered from the pinned evidence and maps only to inventory `mark_unreported`. |
| ECR-0027 | EA-0028 + EA-0012 | Accepted | `apply_cloud_baselines` can never assess a cloud object: EA-0012's asset query hard-forces `object_type="asset"` while CSPM normalizes to `cloud_*`. It returns a clean-looking empty snapshot. EA-0012 gains a configured set of assessable object types, and an assessment that applied no baseline to in-scope objects must be surfaced, never reported clean. |
| ECR-0028 | EA-0012 + EA-0028 | Accepted | Complete ECR-0027: plumb ACG/CSPM config through both runtime factories; apply query budgets independently per object type; persist complete, per-type baseline coverage; distinguish empty scope from missing baselines; and amend EA-0012's owner contract. |
| ECR-0029 | EA-0012 + EA-0028 | Accepted | ECR-0028's `coverage_complete` is asserted over a truncated page budget. When a type's `ObjectQuery.limit` is exhausted while a `next_cursor` remains, `_asset_pages` breaks and the unseen objects are counted nowhere; the snapshot reports `coverage_complete=true` and an `objects_in_scope` that is the number of objects *looked at*, not the number in scope. `apply_cloud_baselines` with no scope materializes `ObjectQuery()` with its default `limit=100`, so any cloud estate above 100 objects reports a complete, clean assessment of its first 100. Truncation must make coverage incomplete, and an unscoped assessment must not silently impose a bound the caller never chose. |
| ECR-0030 | EA-0002 (+ EA-0010, EA-0011, EA-0014, EA-0015) | Accepted | PR #164 silently repaired two latent `ObjectStore.query` defects while fixing EA-0012: neither backend had ever returned a `next_cursor` (every paging loop in the platform stopped after one page believing it was complete), and Postgres filtered `labels`/`natural_key` in Python *after* the SQL `LIMIT` (a label-filtered query returned 0 rows where 50 matched). The repair is correct but undisclosed: EA-0002's spec is unchanged, and the consumers are unswept — EA-0010 and EA-0011 change coverage silently, while `soc` and `threat.correlate` discard the cursor and remain capped at one page. |

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
   same `evidence_id` are one signal seen twice, not two. A **null** `evidence_id` is
   not a match: two signals that both lack evidence are **not** merged on that basis,
   because "unknown" is not "same". `ref` remains the primary key, so such signals
   still count separately when their `ref`s differ. Merging is only ever a *reduction*
   applied on positive evidence of sameness — never inferred from absent data.
   Collapsing is transitive: signals joined through any chain of shared `ref` or
   shared `evidence_id` count as one.
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

---

## ECR-0019 — explicit IAG identity input and append-only right of reply

**Raised by:** Codex (C-024 I4 implementation).
**Severity:** blocking ambiguity — I4 requires two states its Accepted types and store
contract cannot represent.

**Problem.** (1) I4 must call EA-0011 `access_paths`/`analyze_risk`, whose subject is a
typed `obj_` identity id, but `IdentityObservation` carries only an account-scoped
display reference such as `acct:alice`. Inferring an object id would fabricate a
cross-engine reference. (2) `review` must durably record a human outcome and return a
reviewed detection, while I3 correctly made `aq_identity_detection` append-only and
the Accepted store protocol has no review record. Updating the detection row would
break D6; returning an unpersisted status would make right of reply cosmetic.

**Resolution.** Add a required, typed `identity_id` to the handed-in
`IdentityObservation`; it is used only to delegate to EA-0011 and is cited in the
detection basis, while `subject_ref` remains the account/credential/session and the
person is never the finding. Add one append-only `IdentityReview` per detection:
`{detection_id, tenant_id, outcome, reviewed_by, reviewed_at, evidence_id}`. The
review evidence is written through EA-0004 first, then the review row is appended;
`get`/`query` materialize `status="reviewed"` from that row without updating the
original detection. Re-review is refused as an optimistic conflict. I4 findings use
a fixed `medium` / `50.0` triage severity (not a new scorer), cite existing signal
evidence, and remain non-actionable (`eligibility="none"`).

**Impact.** Additive I4 contract and DDL only. It preserves I3's append-only gate,
makes EA-0011 delegation possible without inference, and makes S7/FR-11/AC-12/14
durable and testable. No Workflow execution or new scoring authority is introduced.

---

## ECR-0020 — CSPM is a verdict-free normalizer and router, not a parallel cloud stack

**Raised by:** planning (IS-028 spec pass using the ECR-0015 event/type check).
**Status:** Accepted.
**Severity:** architectural — a cloud-specific copy of existing owners would split
inventory, configuration, compliance, identity, exposure, and risk truth six ways.

**Finding.** IS-028 is not a wholesale restatement: its cloud normalization and
`cloud.misconfiguration.detected` integration are net-new. But each proposed
"Cloud <capability> Engine" already has a platform owner. A cloud resource is an
EA-0025 asset; cloud configuration is EA-0012 baseline data; CIS cloud frameworks
belong to EA-0010; cloud IAM belongs to EA-0011; reachability belongs to EA-0023;
and cloud findings aggregate through EA-0013. "Runs in AWS/Azure/GCP" is a scope
and provenance property, not a new capability.

**Resolution.** EA-0028 is a thin **normalization + routing layer**:
`CloudResourceDescriptor` in, verdict-free `NormalizedCloudObject` out, then one
explicit route outcome for every existing owner. It owns provider type mapping,
field provenance, conflict recording through EA-0006 reliability, and preservation
of handed-in raw evidence. It owns no assessment, score, compliance verdict,
finding, action, inventory, or risk computation. `NormalizedCloudObject` and all
other CSPM models use `extra="forbid"`; severity, score/risk-score,
compliance-status, finding, and action fields are unrepresentable in CSPM-owned
state, and those reserved keys are rejected recursively from nested normalized
facts/provenance/conflicts. Provider verdict material remains only in raw EA-0004
evidence. Routing reports `complete`, `partial`, or `failed` and names each
accepted or failed owner, so a five-of-six handoff cannot be smoothed into success.

**Lifecycle constraint.** The archive event `cloud.resource.deleted` is a
handed-in provider observation, not decommission authority. It maps to EA-0025
`mark_unreported` / `aqelyn.inventory.asset_unreported`. Decommission still
requires positive evidence or an attributed EA-0008-gated decision under
EA-0025 S3 / ECR-0014. CSPM registers no deletion assertion of its own.

**Collection boundary.** Descriptors are handed in. Live cloud enumeration remains
a connector-delivered, EA-0008-gated `cloud.enumerate` action; CSPM holds no cloud
credential and opens no provider/network connection.

**Impact.** Governs EA-0028 and C-025 only. The Accepted spec captures this in §0,
D2/D5, FR-6/13/14, NFR-1, and AC-14/15/16. Proof is structural and behavioural per
ECR-0007: forbidden verdict fields fail construction, delegation spies show the
six owners perform analysis, route failure remains visible, and a lifecycle spy
proves provider deletion calls only EA-0025's unreported path.

---

## ECR-0021 — provenance-bound normalized state, and no second name for an EA-0012 fact

**Raised by:** Claude Code (EA-0028 spec review, PR #151).
**Severity:** blocking for C-025 — both items set what the implementer builds first,
and the second one decides whether an event exists at all.

**Problem.** EA-0028 lands the verdict boundary correctly at the model level and then
softens in two places.

1. **The recursive key check is a denylist described as a guarantee.** FR-13 rejects
   six reserved names (`severity`, `score`, `risk_score`, `compliance_status`,
   `finding`, `action`) at any depth, and AC-14 calls the result "verdict fields/keys
   are **unrepresentable** at any normalized depth". For the model's own fields that is
   true and structural (`extra="forbid"` + no such field). For `native_facts` it is not:
   `verdict`, `posture_grade`, `risk_level`, `is_compliant`, `criticality`, `rating`
   and `passed` all pass today, as does `Severity` if matching is case-sensitive. The
   accurate claim is "six known names are rejected", and a future reviewer who trusts
   AC-14's wording will not re-check. A denylist is also the wrong shape here: it must
   anticipate every word a provider or a future contributor might choose.
2. **`aqelyn.cloud.misconfiguration_detected` is a second name for an EA-0012 fact.**
   §10 emits it "when a routed EA-0012 assessment on a cloud object fails a cloud
   baseline". EA-0012 already ships `aqelyn.config.drift_detected` and
   `aqelyn.config.assessment_completed` for that fact. Two events for one occurrence
   invites double-counting, and the name asserts a *detection* from the layer that
   owns no verdicts — rebuilding the silo at the event layer, where the archive's
   restatement pressure was strongest. It is also the event whose apparent net-newness
   was taken as evidence that IS-028 is not a restatement; under the same
   strip-the-prefix reading applied to the rest of the archive's events,
   `cloud.misconfiguration.detected` is `config.drift_detected` scoped to cloud
   objects.

**Resolution.**

1. **Normalized state is provenance-bound.** `set(native_facts) == set(field_provenance)`
   is enforced at construction: every key in normalized state declares the raw provider
   path it came from, and a key without a declared source is unconstructable. This makes
   the boundary an allowlist shaped by D3's own machinery rather than a list of
   forbidden words — an *invented* verdict (`posture_grade`) has no raw source and cannot
   exist, and a *copied* provider verdict is traceable to the field it came from and
   reviewable. The reserved-name check remains as a backstop and becomes
   case-insensitive. AC-14 is reworded to claim only what holds.
2. **CSPM emits no misconfiguration event.** `aqelyn.cloud.misconfiguration_detected` is
   withdrawn. A cloud baseline failure is EA-0012's `aqelyn.config.drift_detected` on an
   object whose `provider` is set; "cloud misconfiguration" is a **query over an existing
   event**, not a new fact — which is the module's own thesis (cloud is a scope filter)
   applied to its event surface. `aqelyn.cloud.resource_normalized` and
   `aqelyn.cloud.resource_unclassified` remain: both are facts this engine genuinely
   originates.

**Impact.** Amends EA-0028 §4/§10, FR-3/FR-13, AC-14, adds **AC-17**
(`test_cspm_native_facts_provenance_bound`), and removes one registered event. C-025
ticket notes updated. No shipped code changes — C-025 has not started.

**Implementation note (not a requirement).** Real provider payloads carry verdict-ish
keys: AWS Config returns `complianceType`, Azure Policy `complianceState`, Security Hub
`Severity`. A normalizer that copies the provider block wholesale will refuse genuine
input. Extraction must be selective — which the provenance-equality rule enforces by
construction, since each extracted key must name its source path.

---

## ECR-0022 — normalized cloud records are tenant-owned and reads require scope

**Raised by:** Codex (C-025 Y1 implementation).
**Status:** Accepted.
**Severity:** blocking contract omission — Y2 cannot implement tenant isolation on
either store while the persisted record and `get` contract carry no tenant scope.

**Problem.** EA-0028 FR-10 and AC-10 require tenant-scoped operations, and
CONVENTIONS §5 requires `tenant_id` on every tenant-owned record plus an explicit
scope on enterprise reads. The Accepted `NormalizedCloudObject` omitted
`tenant_id`, while `CloudNormalizationStore.get(object_id)` accepted no tenant.
`put(obj)` therefore had no tenant to persist, and `get` could only be unscoped or
infer tenancy from ambient state. Either choice would make the in-memory/Postgres
contract diverge or permit a cross-tenant read.

**Resolution.** Add `tenant_id: str | null` to `NormalizedCloudObject`, validated
with the canonical UUID-or-null guard. Change the store contract to
`get(object_id, *, tenant_id)`; `query` already carries the explicit scope. Local
mode continues to use `NULL`, while enterprise mode requires a tenant UUID under
the existing store-mode rules.

**Impact.** Amends EA-0028 §4/§5 and FR-10, adds AC-18
(`test_cspm_tenant_model_guard`), and updates C-025 Y1/Y2 notes. No new capability
or storage field beyond the platform-wide tenancy convention is introduced.

---

## ECR-0023 — normalized facts are flat, so provenance binding is total

**Raised by:** Claude Code (C-025 Y1 review, PR #153). **Correcting my own ECR-0021.**
**Severity:** blocking for C-025 Y2 — it constrains what the normalizer may emit, and
Y2 writes that normalizer.

**Problem.** ECR-0021 replaced a verdict denylist with a provenance binding and claimed
"an invented verdict key has no raw source and cannot exist". Y1 implemented that
faithfully — `set(native_facts) == set(field_provenance)` is enforced — but the binding
is **top-level only**, and I did not say what happens below it. Constructed against the
shipped Y1 model:

```
native_facts={"acl": "public"},                     provenance={}            -> refused
native_facts={"policy": {"severity": "HIGH"}},      provenance={"policy":…}  -> refused (denylist)
native_facts={"tags": {"posture_grade": "F"}},      provenance={"tags":…}    -> CONSTRUCTED
native_facts={"a": {"b": {"risk_level": "crit"}}},  provenance={"a":…}       -> CONSTRUCTED
native_facts={"rules": [{"verdict": "FAIL"}]},      provenance={"rules":…}   -> CONSTRUCTED
```

One level down, the only defence is the reserved-name denylist — the defence ECR-0021
was written to stop relying on. And nesting is the normal case, not an edge case:
provider attributes are structured, so most real `native_facts` will have depth.

**Resolution.** `native_facts` values SHALL be **scalars (`str`/`int`/`float`/`bool`/
`null`) or lists of scalars**. Nested mappings are rejected; structured provider material
belongs in the **raw EA-0004 evidence block**, which the spec already preserves. With
flat values, top-level key binding covers every key in normalized state and the guarantee
is total rather than depth-0.

This is also better normalization, not merely a stricter rule. A nested provider blob in
`native_facts` is un-normalized data carried through the normalizer: EA-0023 wants
`open_ports: [22, 3389]` and `ingress_cidrs: ["0.0.0.0/0"]`, not a copy of the
security-group JSON. Flattening is the translation this engine exists to perform, and the
raw block remains available to anyone who needs the original shape.

**Impact.** Amends EA-0028 §4 and FR-3, adds AC-19 (`test_cspm_native_facts_flat`),
updates C-025 Y1/Y2 notes, and adds the validator to the shipped Y1 model. The
reserved-name denylist remains as a backstop for the flat keys themselves.

**Method note.** This is the second ECR of mine that needed correcting against a shipped
implementation (ECR-0017's null-evidence gloss was the first, fixed in #145). Both were
found by constructing the forbidden state rather than by re-reading the ECR. A spec claim
about what is "impossible" is worth exactly as much as the probe that tried it.

---

## ECR-0024 — selective cloud flattening is an explicit provenance allowlist

**Raised by:** Codex (C-025 Y2 implementation).
**Status:** Accepted.
**Severity:** blocking contract omission — Y2 cannot choose provider facts without
either inventing an undocumented extraction convention or generically flattening raw
provider verdicts into normalized state.

**Problem.** ECR-0021/0023 make normalized state flat and provenance-bound, but the
Accepted `CloudNormalizationConfig` says only which provider type maps to which object
type. It does not say which raw provider paths become facts. A generic recursive
flatten would assign provenance to everything, including AWS Config
`complianceType`, Azure Policy `complianceState`, and Security Hub `Severity`; a hidden
verdict denylist would recreate the maintenance problem ECR-0021 rejected. The desired
selective extraction was therefore not representable in configuration.

**Resolution.** Add `fact_paths: dict[str, dict[str, str]]` to
`CloudNormalizationConfig`. The outer key uses the same provider/resource mapping key
as `type_map`; each inner entry maps a normalized flat fact key to an RFC 6901 JSON
Pointer into `CloudResourceDescriptor.raw`. The normalizer emits only those selected
paths, and records the pointer verbatim in `field_provenance`. Missing paths are omitted
rather than fabricated; selected mappings or lists containing structured values are
rejected because ECR-0023 permits only scalars or lists of scalars. Fact-map entries
without a corresponding `type_map` entry and malformed/non-absolute pointers are
invalid config.

**Impact.** Amends EA-0028 §4/§6, FR-3/FR-10, adds AC-20
(`test_cspm_selective_flatten`), and updates C-025 Y2. It introduces no provider logic,
verdict, or collection capability. Raw payloads remain intact in EA-0004 evidence; the
configuration merely declares which observations are normalized for existing owners.

---

## ECR-0025 — a fact that stops being reported is unknown, not deleted

**Raised by:** Claude Code (C-025 Y2 review, PR #155).
**Severity:** blocking for C-025 Y3 — routing hands these facts to EA-0023/0012/0010, and
a silently deleted fact reaches them as an absence of finding.

**Problem.** ECR-0024 states that a missing configured path is "omitted rather than
fabricated", which is right for a *first* observation. Y2 applies the same rule to a
*subsequent* one: `_resolve_conflicts` reconciles only the keys present in both the
stored and incoming fact sets, and returns the incoming set. A fact that was known and is
absent from the next snapshot is therefore deleted with no conflict record, no flag, and
no trace. Constructed against the shipped Y2 engine:

```
snapshot 1 facts : {'encryption_enabled': True, 'network_public': False, 'open_ports': [22, 443]}
snapshot 2 facts : {'network_public': False, 'open_ports': [22, 443]}
silently dropped : ['encryption_enabled']   conflicts recorded: 0   flagged: False
```

This is **ECR-0014's rule at field level**, and it fails the same way: absence read as
fact. A provider API that omits a key during an incident, a narrowed IAM permission, or a
transient partial response all present as "this resource no longer has that property."
The consequence lands downstream — if `network_public: true` stops being reported,
EA-0023 stops seeing the facet, and a disappearing exposure looks exactly like a
remediated one. Silence becomes good news, in the layer explicitly built so that owners
see cloud reality.

Retaining the old value unconditionally is equally wrong: providers routinely omit a key
when a feature is off, so a stale `True` would hide a genuine change. Absence is neither
the old value nor a new one — **it is unknown**, and it must be represented as such rather
than resolved in either direction. This follows EA-0023's own precedent (unmatched
reachability is `unknown` and flagged, never defaulted) and EA-0025's (`unreported`, still
counted, never decommissioned).

**Resolution.**

1. A configured fact path that produced a value previously and is **absent** from a later
   snapshot SHALL NOT be silently removed. The fact is retained with its last-known value
   and its original `field_provenance`, and marked **`unreported`** — carrying the
   evidence id and `observed_at` of the last snapshot that did report it.
2. The object SHALL be **flagged** when any fact is `unreported`, so the condition is
   visible without inspecting individual facts.
3. The transition SHALL be **recorded** in `conflicts` (the existing mechanism for
   "recorded, not smoothed"), naming the field, the last reporting evidence, and the
   snapshot that omitted it.
4. `explain()` SHALL surface unreported facts, since "why does this object still claim
   X?" is exactly the provenance question this engine exists to answer.
5. A fact that returns in a later snapshot clears `unreported` through the normal
   conflict path.
6. **Downstream owners SHALL receive `unreported` facts as unknown, never as absence.**
   Y3 routing must carry the marker; dropping it at the boundary reintroduces the defect
   one layer later.

**Impact.** Amends EA-0028 §4/§6 and FR-4, adds AC-21
(`test_cspm_unreported_fact_retained`), and updates C-025 Y2/Y3. Implementation is Codex's
(Y2 follow-on): it adds a representation for per-fact reporting state, which is a data-model
change rather than a review fix.

**Note on ECR-0024.** Its "omitted rather than fabricated" wording remains correct for a
first observation and is not withdrawn — this ECR only settles what the same absence means
on a *subsequent* one, which ECR-0024 did not address.

---

## ECR-0026 — owner routing uses a typed, evidence-backed envelope

**Raised by:** Codex (C-025 Y3 implementation).
**Status:** Accepted.
**Severity:** blocking contract omission — the Accepted Y3 interface names six owner
handoffs but does not define a common input, and `route(object_ids)` does not carry the
descriptor metadata needed to distinguish an observation from `reported_deleted`.

**Problem.** The shipped owners expose different contracts: inventory ingests discovery
reports, asset configuration and compliance assess shared objects, exposure consumes known
surface records, IAG reads identity objects, and risk consumes findings/signals. None has a
shared `accept_cloud_object` method, and rewriting all six owners would fork their APIs for
one scope filter. Passing only `native_facts` would also strip ECR-0025's
`unreported_facts`, making a stale retained value look current at the exact boundary the
ECR was meant to protect. Finally, the normalized projection pins the current evidence id
but does not duplicate `change_kind`, source, resource id, or observation time; those facts
remain in EA-0004 evidence by design.

**Resolution.** Y3 introduces a `CloudRouteEnvelope` built from the tenant-scoped
`NormalizedCloudObject` and its pinned EA-0004 evidence. It carries the **entire** normalized
object (including `field_provenance`, `unreported_facts`, conflicts, and flag), plus
`resource_id`, `source_id`, source reliability, `observed_at`, and `change_kind`.
`CloudOwnerRouter` is the adapter boundary: each configured owner receives that envelope
unchanged and returns owner refs. The engine attempts every owner independently and records
accepted/failed outcomes. Concrete adapters translate to the owner's existing API; they do
not add cloud-specific analysis.

For `reported_deleted`, Y3 invokes only the inventory adapter's `mark_unreported` path.
The route envelope is reconstructed from verified stored evidence rather than caller input,
so a caller cannot relabel an observation as deletion or vice versa. `apply_cloud_baselines`
uses a separate EA-0012 adapter receiving the configured baseline ids and cloud scope; CSPM
does not evaluate checks.

**Impact.** Amends EA-0028 §4/§5/§6 and FR-6/FR-14, updates C-025 Y3, and adds no verdict,
collector, finding, or action surface. Y3 tests use six behavioral spies and require every
received envelope to retain `unreported_facts`; Y4 wires concrete adapters without changing
this contract.

---

## ECR-0027 — cloud baselines never reach EA-0012, and the empty result looks clean

**Raised by:** Claude Code (C-025 Y4 review, PR #159).
**Severity:** blocking — EA-0028 **D4/FR-7** ("cloud config assessment is EA-0012 using cloud
`Baseline`s") is non-functional as shipped, and it fails **silently**.

**Problem.** `AssetConfigCloudBaselineRouter` delegates to `AssetConfigAnalyzer.assess`, which
enumerates candidates through `_asset_query`. That builder **overrides** whatever scope it is
given:

```python
data.update({"tenant_id": ..., "object_type": ASSET_OBJECT_TYPE, ...})   # ASSET_OBJECT_TYPE == "asset"
```

CSPM normalizes cloud resources to `cloud_storage` / `cloud_network` / `cloud_iam` / … — never
`"asset"`. No adapter creates an `"asset"`-typed object either: `SharedObjectCloudOwnerRouter`
verifies and returns the existing object, and EA-0025's engine does not write to the object
store at all. So **no normalized cloud object is visible to EA-0012's assessment by any path**.

Constructed end-to-end against the shipped adapter, with a matching baseline in the store and
one non-compliant cloud object present (`encryption_enabled: False`):

```
normalized        : obj_… {'encryption_enabled': False, 'network_public': True}
snapshot id       : drift-snapshot-…
baselines applied : []
assets assessed   : 0
evidence recorded : True
```

A direct `AssetConfigAnalyzer.assess(tenant_id, scope=None)` on the same store returns the same
zero. This is not a classification or configuration gap — the object type is forced in code, so
no deployment configuration can reach it.

**The failure mode is the dangerous half.** `apply_cloud_baselines` returns a snapshot id, records
evidence, and reports zero drift. To every caller and every dashboard above it, "cloud baselines
were assessed and nothing failed" is indistinguishable from "nothing was ever assessed". This is
the platform's recurring defect — absence presented as a clean result — in the one place a
misconfigured cloud estate would be caught. **Not assessed ≠ compliant** (ECR-0012's rule for
scan coverage, restated for assessment coverage).

**Why the milestone's tests passed.** AC-7 (`test_cspm_config_delegates`) exercises delegation
through a **`_BaselineSpy`**, so it proves `apply_cloud_baselines` calls its router with the right
arguments — it cannot prove the concrete adapter shipped in Y4 assesses anything. A delegation spy
demonstrates *intent*; only a run against the real owner demonstrates *connectivity*.

**Resolution.**

1. **EA-0012 owns the widening.** `AssetConfigAnalyzer` gains a configured set of assessable
   object types (default `{"asset"}`, preserving today's behaviour) and stops discarding a
   scope-supplied `object_type`. Cloud object types are assessed by adding them to that set. CSPM
   SHALL NOT relabel cloud resources as `"asset"` to sneak past the filter: the object type is
   information the owners need, and forging it would trade a visible gap for an invisible one.
2. **An assessment that assessed nothing is not a clean assessment.** When a scope matches
   in-scope objects but **no baseline applies to any of them**, or matches no assessable objects
   at all, `apply_cloud_baselines` SHALL surface that state rather than return a zero-drift
   snapshot — refusing, or returning a snapshot that explicitly declares zero coverage. A caller
   must never be able to read "assessed, all clean" from an assessment that ran against nothing.
3. **AC-7 is re-proved end-to-end.** The acceptance test SHALL drive a real `AssetConfigAnalyzer`
   with a real cloud `Baseline` and a non-compliant normalized cloud object, and assert the drift
   is detected. The spy test may remain for argument-passing.

**Impact.** Amends EA-0028 §6 and FR-7, amends EA-0012's assessment scope contract, adds AC-22
(`test_cspm_cloud_baseline_assessed_end_to_end`), and updates C-025 Y4. Implementation is Codex's
— it changes an owner's contract and a shipped query builder, which is beyond a review fix.

**Method note.** Every other owner handoff in Y3 was verified with spies too. Those spies proved
the envelope arrives intact, which was the right question for ECR-0025's marker. They did not ask
whether the receiving owner can act on what arrives. The five non-baseline owners should each get
one end-to-end proof before C-025 is called done.

---

## ECR-0028 — ECR-0027's widening is unreachable in the shipped runtime, and coverage is still not declared

**Raised by:** Claude Code (post-merge review of PR #162, main @affd9d5).
**Severity:** blocking — **EA-0028 FR-7** remains non-functional as deployed, and one shape of
ECR-0027's own defect (a clean snapshot over objects that were never assessed) survives the fix.

PR #162 does the hard part correctly. `assessable_object_types` is a real widening, the forced
`object_type="asset"` is gone, the zero-coverage cases fail closed instead of returning a
zero-drift snapshot, and AC-22 is a genuine end-to-end proof against a real `AssetConfigAnalyzer`
with a real baseline and a real non-compliant normalized cloud object. The five non-baseline owner
seams each got the end-to-end proof the ECR-0027 method note asked for. What follows is what the
merge did not reach.

**(a) No shipped runtime can assess a cloud object.** `kernel/factory.py:808` (memory) and
`:1340` (Postgres) construct `AssetConfigAnalyzer` without a `config`, so `ACGConfig()` applies
and `assessable_object_types == ["asset"]`. `AssetConfigCloudBaselineRouter` reuses
`self.engine.config`, so the CSPM path inherits it. `ACGConfig` is not derived from
`AQELYNConfig` anywhere, so this is not a deployment setting that happens to be unset — there is
no path to set it outside direct construction.

Against the shipped in-memory runtime:

```
assessable_object_types = ['asset']
apply_cloud_baselines(scope={"object_type": "cloud_storage"})
  -> BaselineConfigInvalid: scope object_type 'cloud_storage' is not configured for assessment
```

The refusal is correct and is the valuable half of ECR-0027 — no false clean. But FR-7 ("cloud
config assessment SHALL be performed by EA-0012 using cloud `Baseline`s") is still not performed
by any deployment. AC-22 passes because the test hand-builds `_acg_config()`. That is one level
above the `_BaselineSpy` it replaced and still short of the shipped path: a hand-built config
demonstrates the *mechanism*; only the factory demonstrates *deployment connectivity*.

**Resolution.** `ACGConfig` — at minimum `assessable_object_types` — becomes reachable from
`AQELYNConfig` and is passed at both factory sites, with the CSPM-relevant cloud object types
enabled wherever the CSPM engine is wired. An acceptance test drives the **factory-built** runtime,
not a locally constructed analyzer.

**(b) A shared page budget silently starves later object types.** `_asset_pages` initialises
`remaining = scope.limit` once and decrements it across every type in `object_types`, which the
`ACGConfig` validator sorts alphabetically. The earlier type can consume the entire budget; the
later type is never queried. Neither guard fires — objects *were* assessed and a baseline *did*
apply — so a snapshot is returned. `ObjectQuery.limit` defaults to `100`, so this needs only a
tenant with 100 assets, not an unusual call.

Constructed against a real analyzer with both types configured (`limit=1` for brevity; identical
at 100):

```
snapshot returned  : drift-snapshot-…
baselines applied  : ['cis-server-v1']
overall_score      : 1.0        # reads as "all clean"
cloud object       : obj_… encryption_enabled=False
cloud assessed?    : False
scope recorded     : {'object_type': None, 'limit': 1,
                      'assessable_object_types': ['asset', 'cloud_storage']}
```

The snapshot **records `cloud_storage` as in scope and asserts a clean result over it without ever
querying it**. This is ECR-0027's finding — absence presented as a clean result — reached by a
different route, and the snapshot's own scope field is what makes it credible to a reader.

**Resolution.** The budget is per object type, or the snapshot declares per-type coverage and a
configured type that was never queried is surfaced rather than implied clean.

**(c) Coverage is computed, then thrown away.** `assess` counts `assessed_objects` to drive the
all-or-nothing guard and does not persist it. An assessment that applied a baseline to 1 of 500
in-scope objects is indistinguishable from one that covered all 500: same shape, and
`overall_score` is the mean over the assessed few. "No baseline applied to *anything*" is the
floor of ECR-0027's rule, not its principle — not assessed ≠ compliant holds per object.

**Resolution.** `DriftSnapshot` carries objects-in-scope, objects-assessed, and the object ids
that matched scope but had no applicable baseline. Downstream readers can then tell coverage from
compliance.

**(d) EA-0012's spec was not amended.** ECR-0027 states it "amends EA-0012's assessment scope
contract". `EA-0028-cloud-security-posture.spec.md` was updated (FR-7 + AC-22 ✅);
`EA-0012-asset-config-governance.spec.md` was not: D1 and the glossary still scope assessment to
`object_type "asset"`, `assessable_object_types` appears nowhere, ECR-0027 is absent from its
change-control line, and **FR-5 ("`assess` SHALL persist a `DriftSnapshot`") now contradicts
shipped behaviour** — `assess` raises `BaselineNotFound` on the zero-coverage paths. An owner's
contract changed in code without changing in its spec.

**Also (non-blocking, fold in here):**

- `assess_asset(asset_id)` now raises `BaselineNotFound` where it previously returned `[]`. This
  is a defensible reading of the same principle, but it was not required by ECR-0027, is not in
  any spec, and has no AC. Either document it in EA-0012 with an AC, or revert it.
- "assessment matched no assessable objects" is raised as `BaselineNotFound`. The condition is
  "no objects", not "no baseline"; the two zero-coverage cases should be distinguishable by an
  operator without reading the message string.
- `_scope_dump` no longer round-trips as an `ObjectQuery` — it emits a raw dict carrying an extra
  `assessable_object_types` key and `object_type: None` for multi-type runs. `ObjectQuery` is
  `extra="forbid"`, so any future consumer that re-validates `snapshot.scope` breaks. No consumer
  does today; recording the choice so it stays deliberate.

**Impact.** Amends EA-0012 §D1/FR-5 and its change-control line, amends EA-0028 AC-22 to drive the
factory-built runtime, adds per-type budgeting and snapshot coverage fields. Implementation is
Codex's — it touches the kernel factory, an owner's persisted model, and an owner's spec.

**Accepted resolution.** `AQELYNConfig` now supplies the ACG assessment config and CSPM
normalization/baseline config to both runtime factories. An explicit `ObjectQuery.limit` is a
per-object-type assessment budget; newly issued snapshots persist aggregate and per-type coverage,
including every in-scope object without an applicable baseline. Historical rows remain readable
with `coverage_complete=false` rather than being misrepresented as fully covered. The recorded
scope remains valid `ObjectQuery` data; configured object types live in the coverage records.
Empty scope and missing baselines retain `BaselineNotFound` but carry distinct stable
`details.reason` values, and `assess_asset`'s no-baseline refusal is now part of EA-0012's contract.

---

## ECR-0029 — `coverage_complete` is asserted over a silently truncated page budget

**Raised by:** Claude Code (post-merge review of PR #163, main @0c8ada3).
**Severity:** blocking — the field that ECR-0028 added to make coverage honest reports complete
coverage of an estate it truncated, on the default CSPM call path.

PR #163 resolves ECR-0028 as raised. Both factory sites build a real `ACGConfig` from
`AQELYNConfig` (verified: the shipped runtime now reports
`['asset', 'cloud_compute', 'cloud_database', 'cloud_iam', 'cloud_network', 'cloud_storage',
'cloud_unknown']`), the page budget is per object type (verified: the starvation reproduction from
ECR-0028(b) now assesses the cloud object and scores it `0.5` instead of a clean `1.0`), coverage
is persisted per type, refusals carry stable `details.reason` codes, `_scope_dump` is
`ObjectQuery`-valid again, and EA-0012's spec carries the change-control line, D1/D7, the type
model, FR-14 and AC-18..21. The `DriftSnapshot` model validators make an internally inconsistent
coverage record unconstructible rather than merely tested — the right house pattern.

**The residual.** `_asset_pages` exhausts a type's budget with:

```python
if remaining is not None:
    remaining -= len(rows)
    if remaining <= 0:
        break          # next_cursor may still be non-None — nothing records that
```

The objects beyond the budget were never queried, so they appear in neither
`assessed_by_type` nor `unassessed_by_type`. `objects_in_scope` is therefore the count of objects
**looked at**, and `coverage_complete` is set to `True` unconditionally.

`AssetConfigCloudBaselineRouter.apply` builds `ObjectQuery.model_validate({})` when the caller
passes no scope, and `ObjectQuery.limit` defaults to `100`. So the bound is not a caller decision
— it is a default the caller never saw.

Constructed against a real analyzer and the shipped router: 150 normalized `cloud_storage`
objects, 149 encrypted, one not, calling `apply_cloud_baselines(tenant_id=…)` with **no scope**:

```
cloud estate size      : 150
coverage_complete      : True
objects_in_scope       : 100
objects_assessed       : 100
unassessed_object_ids  : 0
overall_score          : 1.0
non-compliant bucket   : obj_… (encryption_enabled=False)
  assessed?            : False
  listed as unassessed?: False
```

The misconfigured bucket is not assessed, not listed as uncovered, and not implied by any count.
The snapshot states that coverage is complete and the estate is clean. This also fails **FR-14**
as written — "objects in scope" is not the objects in scope.

This is the third form of the same defect (ECR-0027 → ECR-0028(b) → here), and the most
dangerous, because it is now wearing the field that was added to prevent it: a reader who checks
`coverage_complete` before trusting `overall_score` is still misled. Every real cloud estate is
larger than 100 objects.

**Resolution.**

1. **Truncation makes coverage incomplete.** When a type's budget is exhausted and `next_cursor`
   is not `None`, that type is truncated: `coverage_complete` SHALL be `false`, and the truncated
   object types SHALL be named on the snapshot (per-type `truncated: bool`). The signal exists at
   the `break` and is discarded — it costs one flag to keep.
2. **An unscoped assessment SHALL NOT inherit a default bound.** `apply_cloud_baselines` with no
   caller scope means the whole estate: pass no limit and page to exhaustion, or refuse rather
   than silently assess a prefix. A bound the caller never chose must not be reported as coverage.
3. `coverage_complete=false` must remain readable — it already denotes pre-ECR-0028 historical
   snapshots, so truncated-new and historical-unknown SHALL be distinguishable (a reason, not just
   a boolean).

**Impact.** Amends EA-0012 FR-14 and D7, adds a per-type `truncated` flag to
`ObjectTypeAssessmentCoverage` and its consistency validator, amends EA-0028's baseline-router
scope handling, adds an AC driving an estate larger than the default limit. Implementation is
Codex's.

**Accepted resolution.** `ObjectQuery.cursor` is now honored by both object-store backends so
unbounded assessments can page to exhaustion. A caller-supplied scope limit remains a bound, but if
that bound is exhausted while more rows remain, the resulting `DriftSnapshot` is persisted as
`coverage_complete=false`, `coverage_incomplete_reason="truncated"`, with the truncated object
type named by `ObjectTypeAssessmentCoverage.truncated=true`. Historical unknown coverage remains
readable as `coverage_complete=false` with no reason and empty coverage fields, while new writes
must be either complete or explicitly truncated. `AssetConfigCloudBaselineRouter.apply` treats a
missing caller `limit` as unbounded, even after it adds the EA-0028 label filter; a no-scope CSPM
baseline run over more than the old default 100 objects now assesses every page and omits `limit`
from the stored scope.

---

## ECR-0030 — EA-0002 never paginated, and Postgres filtered labels after the LIMIT

**Raised by:** Claude Code (post-merge review of PR #164, main @7eabbd8).
**Severity:** blocking for EA-0002's contract and traceability; the code fix has already landed —
what is missing is the owner's spec, the disclosure, and the consumer sweep.

PR #164 resolves ECR-0029 as raised, and I verified it end-to-end on both backends. The
reproduction from ECR-0029 — 150 `cloud_storage` objects, one unencrypted, `apply_cloud_baselines`
with no scope — now assesses all of them, catches the misconfigured bucket, and scores `0.993`
instead of a clean `1.0`. A caller-supplied limit that truncates now persists
`coverage_complete=false`, `coverage_incomplete_reason="truncated"`, and names the truncated type;
the model validator keeps truncated-new distinguishable from historical-unknown. Full suite: 666
passed in-memory, **916 passed / 3 skipped on live Postgres 16 + Redis 7**.

**What landed alongside it.** To make "page to exhaustion" possible, #164 changed
`ObjectStore.query` in both backends. Those edits fixed two pre-existing defects in the platform's
most-depended-on owner. Running the same script against `0c8ada3` (pre-PR) and `7eabbd8` (post-PR),
150 objects, `limit=100`, of which 50 carry the filtered label and all 50 sort after the first
page:

```
pre-PR  (0c8ada3)                             post-PR (7eabbd8)
[memory]   next_cursor=None                   [memory]   next_cursor=set
[memory]   paged to exhaustion: 100 of 150    [memory]   paged to exhaustion: 150 of 150
[postgres] next_cursor=None                   [postgres] next_cursor=set
[postgres] paged to exhaustion: 100 of 150    [postgres] paged to exhaustion: 150 of 150
[postgres] labelled query: rows=0  (50 match) [postgres] labelled query: rows=50
```

1. **`next_cursor` was never returned by either backend.** `InMemoryObjectStore.query` ended
   `return rows[: q.limit], None`; `PostgresObjectStore.query` ended `return out, None`. Every
   `while next_cursor` loop in the platform was dead: it ran once, saw `None`, and concluded the
   estate was exhausted. "Paged over the estate" was, everywhere, "the first page of the estate".
2. **Postgres applied `labels` and `natural_key` in Python after the SQL `LIMIT`.** The database
   returned the first `limit` rows matching only the *other* predicates, and the filter then ran
   over that window. Matching rows outside it were not merely missed — the query returned an empty
   result that reads as "nothing matches". Note where that lands: `AssetConfigCloudBaselineRouter`
   filters on `labels={"module": "EA-0028"}`. On the production backend, the EA-0028 baseline path
   was broken twice over, and only the in-memory backend ever showed the first failure.

Both are the platform's recurring defect — absence rendered as a clean, complete result — sitting
in EA-0002 the whole time. #164 fixed them correctly. What it did not do is treat them as an
owner-contract change.

**Resolution.**

1. **Disclose and spec it.** EA-0002's spec gains the pagination contract (`query` returns a
   `next_cursor` when more rows match; `cursor` is honored; `labels` and `natural_key` are
   applied *before* the limit, not after) plus acceptance tests for each, and the change-control
   line records this ECR. The ECR-0029 note currently describes the cursor work as an enabler for
   EA-0012 and does not mention that no consumer had working pagination, nor the Postgres filter
   bug at all.
2. **Sweep the consumers.** `governance/engine.py:_pages` (EA-0010) and `iag/engine.py`
   identity paging (EA-0011) contain `while next_cursor` loops that were dead and are now live:
   this merge silently widened what those two modules assess, with no test and no note in either
   spec. Their coverage semantics need an explicit check, exactly as EA-0012's did.
3. **Close the ones still capped.** `soc/engine.py:300` and `threat/correlate.py:169,206` call
   `objects, _ = await object_store.query(...)` — they discard the cursor and still see one page,
   now provably. Either they page, or they declare their bound the way `DriftSnapshot` now does.
   Three ECRs were spent removing this exact failure from EA-0012; it should not survive
   unremarked in two other modules.

**Also (non-blocking):**

- `assess(..., use_scope_limit: bool)` carries the caller's intent *beside* the query rather than
  in it, because `ObjectQuery.limit` cannot express "unbounded". `limit: int | None` on
  `ObjectQuery` would put it in the type and remove the sidecar from EA-0012's public signature.
- `_scope_dump` omits `limit` entirely for an unbounded run. Re-validated as an `ObjectQuery` that
  dict yields `limit=100`, so the stored scope of an unbounded assessment reads as bounded.
  Nothing re-validates it today; recording it so the choice stays deliberate.

**Impact.** Amends EA-0002's spec and ACs, adds pagination/label acceptance tests on both
backends, and requires coverage checks in EA-0010, EA-0011, plus a decision for `soc` and
`threat.correlate`. Implementation is Codex's — it touches a core owner's contract and four
consuming modules.

**Accepted resolution.** EA-0002 now owns the stable id-ordered pagination contract: filters are
applied before the page limit, `cursor` is an exclusive continuation token, and `next_cursor` is
returned exactly when another matching row exists. The shared in-memory/Postgres contract suite
proves label and natural-key filtering plus multi-page exhaustion. EA-0010 and EA-0011 exhaust
object pages in bounded batches and fail closed on a repeated cursor; real-store acceptance tests
prove assessments and certifications include later pages. EA-0015 threat hunts page past
post-query attribute non-matches until the requested result bound is filled or the estate ends.
EA-0014 retains its configured correlation cap, pages past expired indicators, and marks
`MatchReport.truncated=true` whenever unprocessed indicator or asset rows remain.
