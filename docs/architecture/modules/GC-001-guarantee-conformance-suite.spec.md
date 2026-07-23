# GC-001 — Central §0 Guarantee-Conformance Suite — Implementation Specification

**Track:** GC (guarantee conformance) — **not** an archive module
**Depends on:** shipped `src/aqelyn/**`; EA-0008 (`WorkflowEngine`, `ActionSpec`/`ActionHandler` contract); EA-0013 `SignalKind`; EA-0031 `ClassificationSignalKind`; the shipped composition scorers (EA-0033, EA-0032, EA-0024, with EA-0030 supplying an EA-0024 factor)
**Consumed by:** CI — every future module passes through it
**Status:** Accepted
**Build milestone:** GC-001 (see `GC-001_Task_Bundle.md`)
**Change control:** **ECR-0057**

---

## 0. What this is, and what it is not

**GC-001 is one test module.** It adds **no runtime surface**: no engine, no
service, no package under `src/aqelyn/`, no event, no `SignalKind`, no capability,
no namespace. Detect-and-propose is unchanged. Any enumeration helper it needs
lives **in `tests/`**, not in `conventions` (§2.1).

It exists because of a precise finding, not a general worry.

## 1. The problem: decentralized, not absent

The reviewer's coverage audit (`GUARANTEE_COVERAGE_READ.md`, main @a5696bf,
157 test files) refutes the stronger hypothesis that §0 guarantees were "stated
everywhere, enforced nowhere":

| Guarantee | Shipped coverage | Verdict |
|---|---|---|
| detect-and-propose | ~16 engines (workflow w1/w3, idthreat i4, assetconfig a4, secrets w1/w4, vuln v1/v4, response r2/k1, cspm y3, exposure e4, threat t4, sspm z3, supplychain q5, risk r4) | broad, scattered |
| unknown never favourable | ISPM g4, secrets j2/w3, supplychain q1/q3 | covered where it applies |
| integrity ≠ authenticity | ISPM h3, secrets j3/w1/w3/w5, supplychain q4 | strong |
| no person-score / no secret value | structural in the types | stronger than a test |
| **SignalKind closure** | decision e3, threat t4 only | **thinnest** |

The refusal tests mostly **do** exist. **ECR-0056 (the workflow human-gate) was
the genuine "enforced-nowhere" case, and it is now the exception rather than the
rule.**

**So the gap is not absence — it is that enforcement is 100% decentralized.**
Nothing in the repository fails when a **new** module omits a boundary. Every
existing guarantee is enforced by a test that the *author of that module wrote*;
a future author who doesn't write one leaves no trace.

**GC-001's purpose is therefore future-proofing, not back-filling.** It is scoped
to the guarantees where a future module is genuinely unguarded, and deliberately
skips the ones already structural (§4).

## 2. Design principles

### 2.1 Enumeration by **discovery**, never by declaration (load-bearing)

A hand-maintained list of engines or scorers **reintroduces the exact gap GC-001
exists to close**: a new module added without being added to the list silently
skips the guarantee, and the omission is again invisible. That is the same
failure one level up.

Therefore:

- **Enumeration SHALL be derived from the filesystem/package structure** — walk
  `src/aqelyn/*/` and enumerate every package. A new module is **automatically in
  scope on the day it lands.**
- **Exemptions SHALL be an explicit, small, reasoned allow-list**, each entry
  carrying *why* it is exempt. An allow-list is safe where a registry is not,
  because adding to it is a **visible, reviewable act**, whereas omission from a
  registry is silent.
- Where discovery by structure is impractical (§4.3), the fallback is a declared
  list **plus a completeness scan that fails when a structurally-matching
  candidate is absent from it** — never a bare declared list.

### 2.2 Assert the **weakest form** that catches the defect

A central assertion stronger than what correct code guarantees produces **false
failures on correct modules** — and a suite that cries wolf gets weakened,
`xfail`-ed, or deleted. That would leave the platform worse off than no central
suite at all, because the appearance of coverage would remain.

So each AC asserts the weakest property that still fails on the real defect, and
anything stronger stays a **per-module** test where its cost is local.

### 2.3 Every AC ships its **negative control** (rule 19 / ECR-0007)

A guarantee test that only passes when the guarantee holds is untested. Each AC
SHALL include a **negative control that must FAIL** — a stub or mutation that
violates the guarantee — proving the assertion has teeth. Per **rule 19**, the
control must *perform* the forbidden thing, not merely assert about it.

## 3. The definition of "execution path" (the load-bearing definition)

AC-1 **SHALL NOT** match on method names or on `ActionSpec` construction. Five
shipped, benign sites expose `apply` and one deliberately safe site constructs
an `ActionSpec`; all six **MUST pass**:

| Site | Why it is not §0 execution |
|---|---|
| `cspm/baselines.py::apply` | delegates assessment to EA-0012 |
| `sspm/baselines.py::apply` | delegates assessment to EA-0012 |
| `cspm/route.py::apply` | routes into EA-0025 `ingest` |
| `sspm/route.py::apply` | routes into EA-0025 `ingest` |
| `lake/retention.py::apply` | EA-0019's own data-lake lifecycle — platform storage, not a customer asset |
| `exposure/models.py::active_reachability_action_spec` | describes a future gated connector action; it owns no handler, registry, or invocation path |

A name/reference-based test would flag these sites, generate noise, and be
disabled within a release. So the test keys on the **real §0 signature**, as a **two-part
conjunction** — both parts must hold:

> **An execution path is a code path by which a module can cause a
> capability-gated `ActionHandler` to run — i.e. mutate a customer asset or
> external system — without passing through
> `WorkflowEngine.propose → approve → execute`.**
>
> **(a) Direct handler invocation authority** — outside EA-0008, it can obtain an
> `ActionHandler` and call `execute`/`rollback`, or it creates/controls an
> alternate `ActionRegistry` used to dispatch handlers. Constructing or carrying
> an `ActionSpec`, proposing a run, holding a `WorkflowController`, or calling
> `WorkflowEngine.execute` does **not** satisfy this part: those are references to
> the one gated owner, not alternate invocation authority.
> **(b) Customer-asset effect** — the effect lands on a customer asset or external
> system, not on AQELYN's own storage or derived state.

The six sites above fail **(a)** — none owns or directly invokes a gated handler.
`lake/retention.py::apply` additionally fails **(b)**: it deletes AQELYN's own
telemetry under EA-0019 retention, which is the platform managing its own
storage, not remediating a customer system.

**They pass on principle, not by exemption** — which is what makes the test
durable: a sixth benign `apply` added next year passes automatically, while a
genuine alternate handler-invocation path outside EA-0008 fails on the day it
lands.

**Detection, in order of strength:**

1. **Runtime registry inspection (preferred).** Construct the kernel; assert every
   registered `ActionHandler` is owned by EA-0008's registry, and that no engine
   holds a reference permitting invocation outside `propose → approve → execute`.
   Runtime beats static: it observes what is *actually wired*.
2. **Structural scan (supplement).** Flag any module outside `workflow/` that
   directly invokes an `ActionHandler`, or constructs/controls an alternate
   action registry used for dispatch. A connector may implement an
   `ActionHandler`, the kernel may construct the one registry, and an analytical
   module may construct an `ActionSpec`; none is an execution path unless it also
   gains direct invocation authority outside `WorkflowEngine`.

*Proposing* a run is legitimate and universal — every engine does it. The
discriminator is **invocation capability**, never reference.

## 4. Scope — three ACs, in priority order

### 4.1 AC-1 — engine-no-execute registry *(load-bearing)*

Assert **EA-0008 `WorkflowEngine` is the platform's only production actor.**
Enumerate every package under `src/aqelyn/` **by discovery** (§2.1); fail if any
module other than EA-0008 exposes an execution path per §3.

**Negative control (must FAIL):** a stub engine that owns an alternate registry,
registers an `ActionHandler`, and invokes it outside EA-0008.

This is the highest-value item: it is the exact §0 risk that IS-036 surfaced — a
future module titled "autonomous" acquiring an execution route — and it is the one
guarantee whose breach causes **action** rather than disagreement.

### 4.2 AC-2 — `SignalKind` closure *(the thinnest real gap)*

Two closed literals are the source of truth:

- `risk/models.py::SignalKind = Literal["finding","compliance","identity","config","threat_intel"]`
- `dspm/models.py::ClassificationSignalKind = Literal["field_name","existing_tag","detector_match"]`

Only decision-e3 and threat-t4 touch closure today. AC-2 asserts **both**:

- **(i) the set is frozen** — a golden-set assertion listing the exact members, so
  silent widening fails and any change becomes a deliberate, reviewed edit;
- **(ii) an out-of-set kind is rejected at runtime** — constructing/ingesting a
  signal with an unregistered kind **raises**.

**(ii) matters independently of (i):** a `Literal` is a **static** guarantee that
`mypy` enforces at authoring time. Data arriving from Postgres, a JSON payload, or
a handed-in descriptor is **not** type-checked — it carries whatever string it
carries. So the rejection test SHALL drive the **real construction/ingestion
path**, not rely on the annotation.

**Negative control (must FAIL):** a kind reaching the runtime path without being
added to the literal.

### 4.3 AC-3 — scorer unknown-never-favourable registry

Enumerate the **composition scorers** — those with a known/unknown factor split:
EA-0033 ISPM posture, EA-0032 credential governance, and EA-0024 vulnerability
priority. EA-0030 supply chain is **not a fourth scorer**: it produces the
reachability `PriorityFactor` and delegates composition to EA-0024. **Exclude
`risk/scoring.py::score_risk`**, which is a bounded max/impact combinator with
**no unknown lever**; the property lives in its factor producers, which are
covered.

Assert each composition scorer ships a case proving **unknown is not the
favourable result**. Per §2.2, that is the weakest form that catches the defect
("unknown treated as safe").

> **Verified central form.** The brief's *"unknown scores strictly worse than
> known-bad"* is not universal. In shipped code, ISPM may place unknown equal to
> known-bad; credential governance places unknown below known-bad; vulnerability
> priority (whose score orientation is reversed) places unknown between proved
> unreachable and directly reachable. The central invariant is therefore
> **orientation-aware**: unknown must be strictly less favourable than the
> scorer's known-good/safe case. Its position relative to known-bad remains a
> per-scorer assertion. Do not require three distinct values centrally and never
> weight-tune a correct scorer to satisfy GC-001.

**Discovery preferred; fallback per §2.1** — discover scorers by structural
signature (a factor type carrying a known/unknown discriminant); if that proves
fragile, use a declared list **plus a completeness scan** that fails when a
structurally-matching scorer is missing from it.

**Negative control (must FAIL):** a stub composition scorer that maps unknown to
its favourable known case.

### 4.4 Explicitly out of scope — already covered

- **integrity ≠ authenticity** — ISPM h3, secrets j3/w1/w3/w5, supplychain q4;
  multiple independent refusals already. Low marginal value.
- **no person-level score / no secret value** — **structural** in the types
  (the field cannot be constructed), which is stronger than any test.

Re-centralizing these would add maintenance without adding safety.

## 5. Requirements

- **FR-1** GC-001 SHALL add no runtime surface: no package under `src/aqelyn/`, no service, event, capability, `SignalKind`, or namespace (§0).
- **FR-2** Any enumeration helper SHALL live in `tests/`; it SHALL NOT be added to `conventions` or any runtime module (§0/§2.1).
- **FR-3** Engine and scorer enumeration SHALL be derived by **discovery** from package structure, not from a hand-maintained list; exemptions SHALL be an explicit allow-list with a stated reason per entry (§2.1).
- **FR-4** AC-1 SHALL NOT match on method names or `ActionSpec` construction; it SHALL key on the §3 two-part signature, and the six listed benign sites SHALL pass **by that definition**, not by exemption (§3).
- **FR-5** AC-1 SHALL assert that every registered `ActionHandler` in a constructed kernel is owned by EA-0008 and that no module outside EA-0008 directly invokes a handler or dispatches one through an alternate registry. Connector implementations, kernel registration, proposal-only `ActionSpec` construction, and calls through the real `WorkflowEngine` are not alternate execution paths (§3/§4.1).
- **FR-6** AC-2 SHALL assert both the frozen membership of `SignalKind` and `ClassificationSignalKind` **and** runtime rejection of an out-of-set kind via the **real** construction/ingestion path (§4.2).
- **FR-7** AC-3 SHALL assert, for every discovered composition scorer, an orientation-aware case proving **unknown is strictly less favourable than known-good/safe**. Its relation to known-bad SHALL remain a per-scorer assertion. `risk/scoring.py::score_risk` SHALL be excluded, with the exclusion reason recorded (§4.3).
- **FR-8** Every AC SHALL ship a **negative control that fails** when the guarantee is violated; the control SHALL perform the forbidden action rather than assert about it (rule 19, §2.3).
- **FR-9** Out-of-set kinds and unknown factors SHALL resolve toward **rejection / non-favourable**, never toward a permissive default (rule 5).
- **FR-10** Any AC touching a real engine or scorer SHALL run on both backends, both tenant modes, and under `python -O`.
- **FR-11** GC-001 SHALL NOT weaken or duplicate an existing per-module refusal test; existing tests remain the owners of their local guarantees.

## 6. Acceptance Criteria ↔ Tests

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1a | Every registered `ActionHandler` is owned by EA-0008 | `test_gc_only_workflow_executes` |
| AC-1b | Discovery enumerates all `src/aqelyn/*` packages automatically | `test_gc_engine_discovery_complete` |
| AC-1c | The five benign `apply` sites and proposal-only exposure `ActionSpec` pass **by definition** | `test_gc_benign_apply_not_flagged`, `test_gc_actionspec_reference_not_flagged` |
| AC-1d | **Negative control:** stub engine owning an alternate registry and invoking its handler → FAILS | `test_gc_negative_control_rogue_handler` |
| AC-2a | `SignalKind` / `ClassificationSignalKind` membership frozen | `test_gc_signalkind_frozen` |
| AC-2b | Out-of-set kind rejected via the **real** ingestion path | `test_gc_signalkind_runtime_rejected` |
| AC-2c | **Negative control:** kind in runtime path but not in literal → FAILS | `test_gc_negative_control_unregistered_kind` |
| AC-3a | Every discovered composition scorer has an orientation-aware unknown case | `test_gc_scorer_unknown_not_favourable` |
| AC-3b | `score_risk` excluded, reason recorded | `test_gc_scorer_exclusion_documented` |
| AC-3c | **Negative control:** stub scorer without the case → FAILS | `test_gc_negative_control_unguarded_scorer` |
| AC-4 | No runtime surface added | `test_gc_no_runtime_surface` |
| AC-5 | Both backends, both tenant modes, `python -O` | `test_gc_matrix[...]` |

## 7. Failure handling

- A **new module** landing without a required guarantee → GC-001 fails in CI.
  **That is the feature**, and the failure message SHALL name the missing
  guarantee and point at the shipped precedent to follow.
- **Discovery finds a package GC-001 cannot classify** → **fail, do not skip.** An
  unclassifiable module is the case most likely to hide a new execution path;
  skipping it recreates the gap silently. Resolution is an explicit allow-list
  entry with a reason, which is reviewable.
- **A benign new `apply` or proposal-only `ActionSpec` is flagged** → the §3
  definition is wrong and SHALL be fixed; do **not** add a name-based exemption,
  which would erode the definition one entry at a time.
- **AC-3's orientation-aware form fails a correct scorer** → inspect the test
  harness and the scorer's documented meaning; do not weight-tune a correct
  scorer to satisfy the suite. The relation between unknown and known-bad stays
  local to each scorer.

## 8. Resolved decisions

- **Future-proofing, not back-filling** (§1) — the audit shows refusal tests
  mostly exist; ECR-0056 was the exception.
- **Discovery, never declaration** (§2.1) — a hand-maintained registry would
  reintroduce the omission gap GC-001 closes.
- **Weakest form that catches the defect** (§2.2) — an over-strong central suite
  produces false failures and gets disabled, leaving the *appearance* of coverage.
- **Invocation authority, not names or references** (§3) — the five benign
  `apply` sites and proposal-only exposure `ActionSpec` pass on principle, so the
  test survives new benign uses without mistaking a proposal for execution.
- **`Literal` is static; data is not** (§4.2) — runtime rejection is a separate,
  necessary assertion.
- **Integrity ≠ authenticity and no-person/no-secret stay out** (§4.4) — already
  structural or multiply covered.
