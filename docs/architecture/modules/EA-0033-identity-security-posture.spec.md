# EA-0033 — Identity Security Posture Management (ISPM) — Implementation Specification

**Realizes:** EA-0033 / IS-033 (supersedes the placeholder `archive/EA-0033/EA-0033_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0011 (IAG — owns identity governance; routed to, never reimplemented)**, **EA-0013 / EA-0007 / EA-0006 (score composition)**, **EA-0020 (`Derivation` — replay)**, **EA-0012 (drift shape)**, EA-0002 (identity objects), EA-0025 (inventory registration), EA-0023 (exposure), EA-0010 (compliance), EA-0004 (evidence), EA-0008 (remediation gated)
**Consumed by:** EA-0011 (`analyze_risk` reads the identities this engine normalizes), EA-0023 (identity exposure), EA-0013 (findings path), the ISPM UI (a WCAG 2.2 AA surface)
**Status:** Accepted
**Build milestone:** C-030 (see `C-030_Task_Bundle.md`)
**Enhanced by:** C-031 H2 (evidence-backed ownership handoff to EA-0025)
**Change control:** ECR-0049, ECR-0050, ECR-0051, ECR-0052
**Definition of Ready:** see §12

---

## 0. Scope reconciliation — the identity-governance half already ships

The ECR-0015 check (run by the reviewer against shipped `src/`) is decisive:

```
ispm 0 · identity_posture 0 · federated 0 · service_account 0
machine_identity 0 · identity-drift 0            <- genuinely net-new
entitlement 107 · certification 154 · privilege 34 · dormant 19
orphaned 12 · access_path 23 · sod 1             <- ALL owned by EA-0011 (IAG)
```

This is the **fourth** posture instance (after CSPM, SSPM, DSPM). The master lists
five standalone-sounding components — Posture Assessment, Risk Scoring, Drift
Detection, Recommendation, Identity Classification — but **EA-0011 already owns
identity governance.** The central question is the DSPM question again: *is ISPM a
new capability, or a normalize + score + route layer over EA-0011?* **It is the
latter, plus three genuinely-new pieces.** The master's component list SHALL NOT
become five new engines.

| IS-033 component | Realization |
|---|---|
| Posture Assessment Engine | **Composition** over EA-0011 `analyze_risk` + control facts (§2.1). |
| **Risk Scoring Engine** | **NEW: deterministic 0–100 posture score** (§2.1) — composing EA-0013/EA-0007/EA-0006, **not** a second scorer. |
| **Drift Detection** | **NEW: identity posture drift** (§2.2) — reusing the **EA-0012** drift shape. |
| Recommendation Engine | **EA-0008 proposals** (`requires_approval=True`, `source_finding` bound) + EA-0020 advisory `Recommendation`. No new engine. |
| **Identity Classification** | **NEW: wider-scope identity normalization** (§2.3) — the DSPM parallel. |
| Certification / access review | **EA-0011** `open_certification` / `decide_item` / `complete_certification`. **ISPM certification *is* this.** |

### 0.1 What EA-0011 owns — route, never re-derive

Verified present in shipped `src/aqelyn/iag/`:

- `IdentityAccessGovernanceEngine.access_paths(identity_id, *, tenant_id) -> list[AccessPath]`
- `IdentityAccessGovernanceEngine.analyze_risk(*, tenant_id, scope) -> AccessRiskReport` — internally
  computes **orphaned, dormant, over-privileged, SoD (via Policy), and
  privileged-unreviewed** risks. **ISPM SHALL NOT re-derive any of these.**
- `open_certification` / `decide_item` / `complete_certification`
- `risks_to_findings(report, *, by, prioritize=True)` — evidence-backed
  findings into EA-0013.
  **No new `SignalKind`.**
- Models **reused, not redefined**: `AccessPath`, `AccessRisk`,
  `AccessRiskReport`, `ReviewItem`, `Certification`, `IAGConfig`.

### 0.2 Boundary — handed-in descriptors, not connectors

The master's ARC-033-001/002 ("Identity Discovery Manager", "Connector
Orchestration Layer", "provider-specific payloads") is the EA-0031/EA-0014 trap.
**ISPM opens no socket to Okta/AD/AAD/PAM, holds no credential, and polls
nothing.** It accepts already-produced, versioned `IdentityDescriptor`s; live
provider ingestion is a later **EA-0008-gated connector** (`identity.enumerate`).
Enforced by a no-network test (rule 13).

**Detect and propose, never act.** Master §2.2 puts "direct modification of
identity provider configuration" out of scope. Remediation is an EA-0008
`propose(playbook, by=, source_finding=finding)` with `requires_approval=True`
and the **`source_finding` binding mandatory** (rule 7) — never executed.

### 0.3 The rule the archive does not state: a score is not a verdict on a person

**This is the first module in the platform that attaches a number to an
identity.** REQ-FR-033-011 asks for a 0–100 identity posture score — and a number
next to a named human is exactly the artefact EA-0027 and EA-0021 S8 were written
to prevent. The distinction that makes it legitimate:

| Legitimate | Forbidden |
|---|---|
| *"This account scores 42/100: MFA absent, 3 unused privileged entitlements, last reviewed 14 months ago."* | *"This person scores 42/100."* |
| A measurement of **an account's control state**, decomposable into the facts that produced it. | A rating of **a human being**, aggregated across their accounts. |

- **The scored subject is the identity/account object** (`obj_`/identity id),
  never a person.
- **`statement` uses control language** — *"MFA is absent on this account"* —
  never characterisation of its holder.
- **No person-level rollup exists.** There SHALL be no type, field, or method
  aggregating an individual's accounts into a single person-level score or trust
  rating. The judgement is **structurally unrepresentable**, as in EA-0027
  (no person-score) and EA-0032 (no secret value).

## 1. Purpose

Identity is the control plane: most breaches now arrive through a valid account.
EA-0011 already answers *"does this identity have the right entitlements, and who
reviewed them?"* — but nobody has yet answered *"how healthy is our identity
estate overall, is it drifting from the shape we approved, and which accounts are
weakest right now?"* ISPM answers that by **normalizing identities EA-0011 doesn't
yet see, scoring each account's control state deterministically and replayably,
and detecting drift from approved baselines** — routing every governance question
back to the engine that owns it.

## 2. The three genuinely-new capabilities

### 2.1 Deterministic, replayable identity posture score (S1)

A 0–100 score per identity, **composed** from: EA-0011 `AccessRiskReport` risks,
control facts (MFA/lifecycle/last-activity), **EA-0007** mission weight of what
the identity reaches, and **EA-0006** confidence — carrying an **EA-0020
`Derivation`** so `replay` reproduces it. **No second scorer** (EA-0013 owns risk
scoring; this composes it).

- **S1a — Deterministic.** Same inputs + same weights → same score, always.
- **S1b — Unknown control facts are excluded from the denominator, never scored
  favourably** (rules 4/5, the ECR-0040 shape). An account whose MFA status is
  **unknown** SHALL NOT score as MFA-present; a missing last-activity SHALL NOT
  score as recently-active. Absence removes a factor's vote; it never casts a
  favourable one.
- **S1c — A score without a replayable derivation is unrepresentable** (the
  EA-0020/EA-0024 gate).

### 2.2 Identity posture drift (S2)

Drift of an identity's posture from an **approved baseline**, reusing the
**EA-0012 shape** (`src/aqelyn/assetconfig/`): declarative baseline entries
`(key, expected, comparator)` compared against observed control facts, with
**append-only drift snapshots**. **No parallel drift engine.**

### 2.3 Wider-scope identity normalization (S3)

Normalize identities from sources EA-0011 does not already govern —
`human | service | machine | application | federated | temporary` — into **EA-0002
identity/account objects and relationships using EA-0011's shipped graph
vocabulary**, so `analyze_risk` can actually read them. A lone identity object is
not a connected governance seam: account-backed descriptors also produce the
account object and evidence-backed `has_account` relationship; any additional
access edge is created only from an explicit evidence-backed descriptor claim.
The DSPM parallel exactly: **same governance vocabulary, wider discovery
scope.** A new identity shape or relationship vocabulary SHALL NOT be invented.

### 2.4 Cross-cutting

- **S4 — Compose, don't rebuild** (§0.1).
- **S5 — Evidence-backed and tenant-scoped**; every score, drift item, and
  normalized identity cites its source descriptor + evidence.

## 3. Design decisions

- **D1 — `IdentityDescriptor` in → EA-0002 identity/account objects plus shipped
  EA-0011 relationships out**, registered via **EA-0025**
  `InventoryIntelligenceEngine.ingest(reports=, source=DiscoverySource, tenant_id=)`;
  provenance preserved (§0.2/§2.3). Every supplied account gets an
  evidence-backed identity → account `has_account` relation. Optional
  `has_role`/`grants_entitlement`/`member_of` edges are emitted only when the
  handed-in descriptor explicitly claims them with verifiable evidence.
- **D2 — Control facts are tri-state** (`present | absent | unknown`), default
  `unknown`, each carrying the evidence that established it (S1b).
- **D3 — Score = EA-0020 `Derivation` over named factors**, each with a source
  ref; `unknown` factors recorded **and excluded from the denominator** (S1b).
- **D4 — Drift reuses the EA-0012 baseline/snapshot shape** (S2).
- **D5 — Governance routes to EA-0011**; findings via `risks_to_findings` /
  the EA-0013 finding path — **no new `SignalKind`** (§0.1).
- **D6 — Exposure via the shipped EA-0023 seam** — a `KnownSurfaceSource`
  yielding `KnownSurfaceRecord`s, reusing the existing **`AssetRef.kind="identity"`**,
  with an `ExposureImpactContext` carrying identity sensitivity. **This requires
  the ECR-0049 `identity_sensitivity` widening (§13) and SHALL be sequenced into
  the same ticket that first constructs it (rule 15).**
- **D7 — Registered as an `AQService`;** stores in-memory + Postgres; health
  probe **tenant-scoped and exercised in both `local` and `enterprise` modes**
  (rule 11).

## 4. Types

```
IdentityKind = "human" | "service" | "machine" | "application" | "federated" | "temporary"
ControlState = "present" | "absent" | "unknown"          # tri-state, default unknown (D2)

ControlFact = { state: ControlState, established_by: str | null,
                evidence_id: str | null, reason: str }   # unknown carries WHY (D2/S1b)

IdentityAccountDescriptor = { external_id: str, display_name: str,
                              attributes: dict, observed_at: datetime,
                              evidence_id: str }          # handed-in account claim (D1)
IdentityAccessEdgeDescriptor = { from_external_id: str, to_object_id: str,
                                 relation_type: "has_role" | "grants_entitlement" | "member_of",
                                 observed_at: datetime, evidence_id: str }
                                 # explicit claim; target is an existing EA-0002 role/entitlement
IdentityDescriptor = { source_id: str, provider: str, external_id: str,
                       identity_kind: IdentityKind | null,
                       attributes: dict, controls: dict,          # mfa/lifecycle/last_activity raw
                       accounts: list[IdentityAccountDescriptor],
                       access_edges: list[IdentityAccessEdgeDescriptor],
                       ownership: IdentityOwnershipClaim | null,
                       observed_at: datetime, evidence_id: str | null }   # handed in (§0.2)

IdentityOwnershipClaim = { business_owner: str | null,
                           technical_owner: str | null, custodian: str | null,
                           rationale: str, source_id: str,
                           observed_at: datetime, evidence_id: str }
IdentityOwnershipState = { inventory_ref: str, status: "known" | "unknown",
                           source_id: str | null, evidence_id: str | null,
                           observed_at: datetime | null, reason: str }

NormalizedIdentity = { object_id: str, tenant_id: str, external_id: str,
                       provider: str, identity_kind: IdentityKind | "unknown",
                       account_object_ids: list[str], relationship_ids: list[str],
                       controls: { mfa: ControlFact, lifecycle: ControlFact,
                                   last_activity: ControlFact },
                       ownership: IdentityOwnershipState | null,
                       field_provenance: dict, conflicts: list[dict],
                       flagged: bool,
                       evidence_id: str }                 # EA-0011 graph intake, not a second identity shape (S3)

PostureFactor = { name: str, value: float | None, weight: float,
                  status: "known" | "unknown",            # unknown -> excluded from denominator (S1b)
                  source_ref: dict, reason: str }
IdentityPostureScore = { id: str,                         # ips_ (§7 FR-18)
                         subject_ref: str,                # the ACCOUNT object id (§0.3)
                         score: float,                    # 0-100
                         factors: list[PostureFactor],
                         iag_risks: list["AccessRisk"],  # pinned owner records; AccessRisk has no id
                         derivation: "Derivation",        # EA-0020, MANDATORY (S1c)
                         confidence: float,               # EA-0006
                         statement: str,                  # control language (§0.3)
                         computed_at: datetime, evidence_id: str }

IdentityBaselineEntry = { key: str, expected: object, comparator: str, severity: str }
IdentityBaseline = { id,                                 # ibl_ (§7 FR-18)
                     tenant_id: str | null, name: str, version: int,
                     identity_kind: IdentityKind, entries: list[IdentityBaselineEntry],
                     approved_by: ActorRef | null, approved_at: datetime | null }   # EA-0012 shape (S2)
IdentityDriftItem = { identity_id, key: str, expected: object, observed: object,
                      status: "pass" | "fail" | "unknown", reason: str }
IdentityDriftSnapshot = { id,                            # idr_ (§7 FR-18)
                          tenant_id, run_at: datetime, baseline_id: str,
                          evaluated: int, passed: int, failed: int, unknown: int,
                          items: list[IdentityDriftItem], evidence_id: str }   # append-only (S2)

ISPMAssessment = { id,                                   # ipa_ (§7 FR-18)
                   tenant_id, run_at, scope: dict,
                   identities_evaluated: int, scored: int,
                   score_ids: list[str],                       # exact replayable ips_ records (ECR-0052)
                   unknown_controls: int,                 # surfaced, never hidden (S1b)
                   drift_snapshot_id: str | null,
                   status: "computed" | "truncated" | "pending",   # rule 4
                   inventory_complete: bool, inventory_note: str,  # ECR-0034 (§12a)
                   evidence_id: str }
ISPMConfig = { factor_weights: dict[str, float], baseline_ids: list[str],
               stale_activity_days: int, batch_size: int, page_budget: int }
```

Reuses EA-0011 `AccessPath`/`AccessRisk`/`AccessRiskReport`/`Certification`,
EA-0020 `Derivation`, EA-0023 `AssetRef(kind="identity")`, EA-0004 evidence.
**No person-level score type exists** (§0.3).

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class ISPMStore(Protocol):
    async def upsert_identity(self, i: NormalizedIdentity) -> NormalizedIdentity: ...
    async def get_identity(self, object_id: str) -> NormalizedIdentity | None: ...
    async def put_score(self, s: IdentityPostureScore) -> IdentityPostureScore: ...   # rejects unreplayable (S1c)
    async def put_drift(self, d: IdentityDriftSnapshot) -> IdentityDriftSnapshot: ... # append-only (S2)
    async def put_assessment(self, a: ISPMAssessment) -> ISPMAssessment: ...
    async def get_assessment(self, assessment_id: str, *,
                             tenant_id: str | None) -> ISPMAssessment | None: ...
    async def query_identities(self, *, tenant_id: str | None, cursor: str | None = None,
                               limit: int = 100) -> tuple[list[NormalizedIdentity], str | None]: ...
    # EA-0002 D8 pagination: stable id order, exclusive cursor, filters before LIMIT (rule 10)

class ISPMEngine(Protocol):
    async def ingest_identities(self, descriptors: Sequence[IdentityDescriptor], *,
                                tenant_id: str | None) -> list[NormalizedIdentity]: ...  # handed-in (§0.2)
    async def score_identity(self, account_object_id: str, *,
                             tenant_id: str | None) -> IdentityPostureScore: ...         # §2.1
    async def detect_drift(self, *, baseline_id: str, tenant_id: str | None,
                           scope: dict | None = None) -> IdentityDriftSnapshot: ...      # §2.2
    async def governance_context(self, object_id: str, *,
                                 tenant_id: str | None) -> "AccessRiskReport": ...
    # delegates to EA-0011 analyze_risk / access_paths — NEVER re-derives (§0.1)

    async def assess(self, *, tenant_id: str | None,
                     scope: dict | None = None) -> ISPMAssessment: ...
    async def posture_to_findings(self, assessment_id: str, *,
                                  tenant_id: str | None, by: ActorRef,
                                  propose_remediation: bool = True) -> list[str]: ...
    # findings via EA-0011 risks_to_findings / EA-0013 path; proposals bind source_finding (rule 7)

    def explain(self, s: IdentityPostureScore) -> dict: ...       # renders the Derivation
```

`ISPMService` wraps engine + store as an `AQService` (name `"ispm_engine"`,
depends on iag/object/inventory/exposure/risk/mission/trust/decision/assetconfig/
compliance/evidence/workflow; health **tenant-scoped**, exercised in both tenant
modes — rule 11).

**Deliberately absent:** any provider connector/poll/enumerate method (§0.2); any
re-derivation of orphaned/dormant/over-privileged/SoD/certification (§0.1); any
person-level score (§0.3); any second risk scorer or drift engine (§0).

## 6. Computation (the reference model)

**Normalize.** Handed-in `IdentityDescriptor`s → `NormalizedIdentity` using
**EA-0011's shipped EA-0002 graph intake**: an `object_type="identity"` object,
an `object_type="account"` object for every supplied account, and an
identity → account `has_account` relationship through `ObjectStore.relate`.
Additional EA-0011 access relationships are created only from explicit
evidence-backed `IdentityAccessEdgeDescriptor`s, with tenant/type validation;
absence of an edge claim never invents one. Classify `identity_kind` (unmatched
→ `"unknown"`, with `flagged=true` required structurally per ECR-0051); control facts to **tri-state** (`unknown` by default,
with reason); conflicts across sources resolved by **EA-0006** reliability and
**recorded** (EA-0025 pattern); register via **EA-0025** `ingest(...)`;
evidence-recorded.

**Score.** Gather: EA-0011 `analyze_risk` risks for the linked identity/account
(**pinned as the actual `AccessRisk` owner records, not re-derived or assigned
invented ids**), control facts, EA-0007 mission weight of what it reaches, EA-0006
confidence. Build `PostureFactor`s — a factor whose fact is `unknown` gets
`status="unknown"` and is **excluded from the denominator**, never scored
favourably (S1b). Combine under `factor_weights` into 0–100; build the **EA-0020
`Derivation`**; render `statement` in **control language** (§0.3). The store
**rejects** a score whose derivation does not replay (S1c).

**Drift.** Compare observed control facts to the approved `IdentityBaseline`
(EA-0012 comparator shape); an unestablishable fact is `status="unknown"`, **never
`pass`**; write an **append-only** `IdentityDriftSnapshot` + evidence.

**Assess.** Page identities under `page_budget` (rule 10); snapshot counts
including **`unknown_controls`**; set `status` to `computed | truncated |
pending` (rule 4); pin the exact replayable posture scores in `score_ids`
(ECR-0052); carry `inventory_complete` from EA-0025 honestly (§12a).

**Findings.** `posture_to_findings` loads the assessment's exact `score_ids` and
raises evidence-backed findings via tenant-scoped EA-0011
`risks_to_findings` / the EA-0013 path (**no new `SignalKind`**) and, when
requested, EA-0008 `propose(playbook, by=, source_finding=finding)` with
`requires_approval=True` (rule 7).

## 7. Requirements

### Functional (testable)

- **FR-1** `ingest_identities` SHALL accept handed-in descriptors only; the module SHALL open no socket, hold no credential, poll nothing, and expose no connector/enumerate method (§0.2, rule 13).
- **FR-2** Identities SHALL be normalized into **EA-0011's shipped EA-0002 graph intake** and registered via **EA-0025 `ingest(reports=, source=, tenant_id=)`**: identity and account `AQObject`s, an evidence-backed `has_account` relation for every supplied account, and only explicitly claimed/evidence-backed access edges. Optional ownership claims SHALL be verified before any owner write, routed through EA-0025 reconciliation, and persisted as an explicit known-or-unknown state pinning the exact inventory and winning evidence refs (C-031 H2). An omitted ownership claim is unknown and SHALL NOT erase an evidence-backed claim from another source. An unmatched `identity_kind="unknown"` SHALL require `flagged=true` on the normalized record itself (ECR-0051), not only on an owner-store label. The module SHALL NOT define a new identity shape, relationship vocabulary, graph engine, inventory, or ownership store (§2.3/D1).
- **FR-3** Orphaned, dormant, over-privileged, SoD, and privileged-unreviewed risks SHALL be read from **EA-0011 `analyze_risk`** and pinned as the actual `AccessRisk` records (the shipped type has no id); the module SHALL NOT re-derive any of them (§0.1). A real normalization → `IdentityAccessGovernanceEngine.analyze_risk` → posture-score round trip SHALL prove that a normalized identity/account graph produces the expected non-empty risk and that the score cites that exact owner record; a spy or call assertion alone is insufficient.
- **FR-4** Access paths SHALL come from **EA-0011 `access_paths`**; certification SHALL be **EA-0011 `open_certification`/`decide_item`/`complete_certification`**; the module SHALL NOT create a parallel certification model or `cert` prefix (§0.1, false friends).
- **FR-5** Control facts (`mfa`, `lifecycle`, `last_activity`) SHALL be tri-state `present|absent|unknown` defaulting to `unknown`, each carrying the evidence or the reason it is unknown (D2).
- **FR-6** A factor whose control fact is `unknown` SHALL be recorded `status="unknown"` and **excluded from the score denominator**; it SHALL NEVER contribute a favourable value (S1b, rules 4/5, ECR-0040 shape).
- **FR-7** `score_identity` SHALL be deterministic (same inputs + weights → same score) and SHALL carry an **EA-0020 `Derivation`**; a score whose `replay` does not reproduce it SHALL be rejected at `put_score` (S1a/S1c).
- **FR-8** Score composition SHALL use **EA-0013 risk scoring / EA-0007 mission / EA-0006 trust**; the module SHALL NOT introduce a second scorer (§2.1).
- **FR-9** `subject_ref` SHALL be an identity/account object id, and `statement` SHALL use control language; **no type, field, or method SHALL aggregate an individual's accounts into a person-level score or trust rating** (§0.3) — structurally unrepresentable.
- **FR-10** Drift SHALL reuse the **EA-0012** baseline/comparator shape with **append-only** snapshots; an unestablishable fact SHALL be `status="unknown"`, never `pass` (§2.2).
- **FR-11** Findings SHALL flow from the assessment's exact persisted `score_ids` via tenant-scoped **EA-0011 `risks_to_findings`** / the EA-0013 finding path; the module SHALL NOT recompute history or add a new `SignalKind` (§0.1/D5, ECR-0052).
- **FR-12** Remediation SHALL be an **EA-0008 `propose(playbook, by=, source_finding=finding)`** with `requires_approval=True`; the `source_finding` binding is **mandatory**, and the module SHALL modify no identity provider (§0.2, rule 7).
- **FR-13** Identity exposure SHALL use the shipped **EA-0023 `KnownSurfaceSource → KnownSurfaceRecord`** seam reusing **`AssetRef.kind="identity"`**; the module SHALL NOT implement reachability or exposure scoring (D6).
- **FR-14** Where identity sensitivity is supplied to EA-0023, it SHALL use the **`identity_sensitivity` `ExposureImpactKind`** (ECR-0049, additive, `data_sensitivity` default preserved, replay-pinned); this widening SHALL land in the same ticket that first constructs it (rule 15, §13).
- **FR-15** `ISPMAssessment.status` SHALL be `computed|truncated|pending` (semantic tokens, not truthy strings) and `unknown_controls` SHALL be surfaced (rule 4).
- **FR-16** `query_identities` SHALL implement EA-0002 D8 pagination (stable id order, exclusive cursor, `next_cursor` non-null exactly when another matching row exists, filters before `LIMIT`) under `page_budget`, reporting `truncated` rather than silently capping (rule 10).
- **FR-17** The assessment SHALL carry `inventory_complete` honestly from EA-0025 and SHALL NOT present a bounded inventory as exhaustive (§12a, ECR-0034).
- **FR-18** The collision-checked record prefixes **`ips`** (`ispm_posture_score`), **`ibl`** (`ispm_identity_baseline`), **`idr`** (`ispm_identity_drift`), and **`ipa`** (`ispm_assessment`) plus the error codes SHALL be registered in **both** `conventions/ids.py::PREFIXES` and CONVENTIONS §1 (errors in `errors.py` + CONVENTIONS §9). EA-0002 identities/accounts and relationships continue to use owner prefixes `obj`/`rel`, and inventory uses `ast`; the module SHALL NOT reuse the `cert` prefix (`iag_certification`) and SHALL NOT emit `aqelyn.iag.*` events (false friends).
- **FR-19** All operations SHALL be tenant-scoped; invalid config (weights not summing to 1 ± 1e-6, `stale_activity_days ≤ 0`, `batch_size ≤ 0`, `page_budget ≤ 0`, unknown baseline id) SHALL raise `ISPMConfigInvalid`.
- **FR-20** `ISPMStore` in-memory and Postgres implementations SHALL pass one contract suite; any new persisted field SHALL be checked against the target table's shape before being called additive (rule 9).
- **FR-21** `ISPMService` SHALL register as an `AQService` with a **tenant-scoped** health probe, exercised in **both `local` and `enterprise`** tenant modes (rule 11).

### Non-functional

- **NFR-1 (no person-rating — structural)** no schema, field, or method represents a person-level score or trust rating; verified structurally (absent) and behaviourally, per **ECR-0007**.
- **NFR-2 (unknown never favourable — structural)** `unknown` factors are excluded from the denominator; an identity with unknown MFA SHALL NOT outscore one with MFA proven absent-but-known... and SHALL NOT match one with MFA proven present. Verified by driving the **real scoring function**, not a spy (the ECR-0040 method).
- **NFR-3 (no reimplementation of EA-0011)** delegation spies prove `analyze_risk`, `access_paths`, certification, and `risks_to_findings` are called; no local re-derivation exists.
- **NFR-4 (no collection)** socket spy proves zero outbound; no connector method.
- **NFR-5 (replayable)** every stored score replays to its value.
- **NFR-6 (bounded & typed)** paged under budget; both backends pass one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Handed-in only; no connector/socket | `test_ispm_no_collection` |
| AC-2 | Identity/account objects + evidence-backed EA-0011 relationships; EA-0025 registration; unknown identity kind structurally flagged | `test_ispm_normalize_to_iag_shape` |
| AC-3 | Real normalized graph → real EA-0011 risk → score citing the same `AccessRisk` | `test_ispm_real_iag_round_trip` + `test_ispm_score_cites_real_iag_risk` |
| AC-4 | Orphaned/dormant/over-priv/SoD read from EA-0011, not re-derived | `test_ispm_iag_not_reimplemented` |
| AC-5 | Access paths + certification delegate to EA-0011 | `test_ispm_certification_delegates` |
| AC-6 | Control facts tri-state, default unknown, with reason | `test_ispm_controls_tristate` |
| AC-7 | Unknown factor excluded from denominator, never favourable | `test_ispm_unknown_not_favourable` |
| AC-8 | Score deterministic; derivation replays; unreplayable rejected | `test_ispm_score_replay` |
| AC-9 | Score composes EA-0013/0007/0006 (no second scorer) | `test_ispm_score_composed` |
| AC-10 | Subject is an account; control language; **no person rollup type** | `test_ispm_no_person_score` |
| AC-11 | Drift reuses EA-0012 shape; append-only; unknown ≠ pass | `test_ispm_drift_shape` |
| AC-12 | Findings via EA-0011/EA-0013; no new SignalKind | `test_ispm_findings_path` |
| AC-13 | Remediation proposed, `source_finding` bound, nothing modified | `test_ispm_propose_binds_finding` |
| AC-14 | Exposure via KnownSurfaceSource + AssetRef.kind="identity" | `test_ispm_exposure_seam` |
| AC-15 | identity_sensitivity widening additive; default preserved | `test_ispm_identity_sensitivity_kind` |
| AC-16 | Assessment status semantic tri-state; unknown_controls surfaced | `test_ispm_assessment_status` |
| AC-17 | D8 pagination under budget; truncated reported | `test_ispm_pagination` |
| AC-18 | inventory_complete honest (ECR-0034 not weakened) | `test_ispm_inventory_not_exhaustive` |
| AC-19 | Prefixes/errors registered both sites; no `cert`, no `aqelyn.iag.*` | `test_ispm_prefixes_and_events` |
| AC-20 | Invalid config rejected | `test_ispm_config_invalid` |
| AC-21 | Store passes one suite on both backends | `test_ispm_store_contract[inmemory]` / `[postgres]` |
| AC-22 | Health tenant-scoped, both tenant modes | `test_ispm_service_health[local]` / `[enterprise]` |
| AC-23 | Ownership claim verifies before writes; real EA-0025 reconciliation pins known/unknown provenance on both stores | `test_nhi_ownership_*` |

## 9. Error taxonomy (contributions)

Contributes `ISPMConfigInvalid`, `PostureScoreNotReplayable`, and
`IdentityBaselineNotFound` (added to `conventions.errors` **and** CONVENTIONS §9 —
a test asserts the code set). Reuses EA-0027's existing platform
`IdentityNotFound` rather than declaring a second owner (ECR-0050), plus EA-0020
`DerivationNotReplayable`, `StoreUnavailable`, and `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0033)

`aqelyn.ispm.identity_normalized`, `aqelyn.ispm.posture_scored`,
`aqelyn.ispm.posture_drift_detected`, `aqelyn.ispm.controls_unknown` (the honest
event) — via `register_ispm_events()` (EA-0003 §7). **The module SHALL NOT emit
`aqelyn.iag.*`** (`certification_opened/_completed`, `item_decided`,
`risk_detected` belong to EA-0011).

## 11. Failure handling

- Invalid config → `ISPMConfigInvalid` at construction.
- **EA-0011 unavailable → no score is produced** (`StoreUnavailable`, service
  `degraded`). A posture score assembled without the governance half is not a
  posture score; it SHALL NOT be emitted with the risk factors silently missing.
- A control fact not establishable → `unknown` + reason, factor excluded from the
  denominator. **This is the correct outcome, not a degraded one** (S1b).
- Score fails to replay → **withheld**, not served with a caveat (EA-0020/EA-0021
  precedent).
- EA-0025 inventory bounded → `inventory_complete=false` with a note; the
  assessment SHALL NOT read as exhaustive (§12a).
- EA-0023 unavailable → exposure `pending`, surfaced; **never "not exposed"**
  (ECR-0040).
- Proposal failure → the finding stands, the delegation failure is surfaced, and
  **no identity provider is touched** (§0.2).

## 12. Dependencies & consumers

- **Depends on / routes to:** **EA-0011** (governance, certification, findings —
  `analyze_risk`, `access_paths`, `open_certification`/`decide_item`/
  `complete_certification`, `risks_to_findings`); **EA-0013 / EA-0007 / EA-0006**
  (score composition); **EA-0020** (`Derivation`); **EA-0012** (drift shape);
  **EA-0002** (identity objects); **EA-0025** (`ingest`); **EA-0023**
  (`KnownSurfaceSource`/`KnownSurfaceRecord`, `AssetRef.kind="identity"`);
  **EA-0010** (`assess`); EA-0004 (evidence); **EA-0008** (`propose`, gated);
  EA-0001 `AQService`.
- **Consumed by:** **EA-0011** (`analyze_risk` reads identities this engine
  normalizes); **EA-0023** (identity exposure); **EA-0013** (findings); the ISPM
  UI (**WCAG 2.2 AA**).

## 12a. Inherited constraint — ECR-0034 (must not weaken)

**ECR-0034** (Accepted-as-Proposed, unimplemented): EA-0025
`InventoryIntelligenceEngine.inventory()` reads `store.query(limit=10_000)` and
hardcodes `degraded=False`, so an estate above 10 000 assets reports as complete.
ISPM registers identities into that same store and **inherits the cap**. This spec
SHALL NOT treat the inventory report as exhaustive: `ISPMAssessment` carries
`inventory_complete` + `inventory_note`, and coverage-like claims stay honest.
EA-0033 does not fix ECR-0034; **it must not deepen it.**

## 13. Resolved / deferred decisions

- **ISPM is a posture layer over EA-0011, not a second identity-governance
  engine** (§0) — the master's five component names SHALL NOT become five engines.
- **Three net-new capabilities only**: deterministic replayable posture score
  (§2.1), identity drift on the EA-0012 shape (§2.2), wider-scope normalization
  (§2.3).
- **A score is not a verdict on a person** (§0.3) — structurally unrepresentable
  person-level rating, joining EA-0021 S8, EA-0027, and EA-0032's value-safety.
- **Handed-in descriptors** (§0.2) — provider connectors are a later EA-0008-gated
  action; the descriptor is the seam that keeps this engine unchanged when they
  land.
- **C-031 H2 ownership handoff** — EA-0033 accepts a value-free, evidence-backed
  owner claim but delegates ownership precedence and history to EA-0025. Missing
  ownership is explicit unknown, never a favourable control fact.
- **ECR-0049 (Accepted) — `identity_sensitivity` `ExposureImpactKind` widening.**
  `ExposureImpactKind` is currently `data_sensitivity | credential_sensitivity`
  (ECR-0041/0044). Feeding identity sensitivity into EA-0023 needs the same
  **additive widening + replay-pin** treatment, with the `data_sensitivity`
  default preserved. Anticipated here rather than discovered mid-build; **per rule
  15 it lands in the same ticket that first constructs an identity
  `ExposureImpactContext` (G5), never earlier.** Recorded as Proposed in the
  canonical ECR log.
- **ECR-0032 — fourth posture instance.** CSPM, SSPM, DSPM, now ISPM all share
  `normalize → (classify/score) → route`. The revisit condition is well past met.
  Recommendation unchanged: **decide after C-030 is green**, as a
  behaviour-preserving refactor against four real implementations — **not** part
  of this milestone.
