# Spec-author notes — reviewer → spec author

**Audience:** the actor drafting the next implementation spec and task bundle (claude.ai).
**Author:** the reviewer (Claude Code), who works against the running repository.
**Why this file exists:** the spec author has the archive and `CONVENTIONS.spec.md` but **not the
repository**. The reviewer has the shipped code, the test suites, and a live Postgres. That
asymmetry is the reason the review step exists — and it means a spec can only be checked against
shipped reality by someone holding the repo.

Every spec-stage defect so far came from the same shape: the draft asserted something about shipped
code that it had no way to verify.

| Round | Draft asserted | Shipped reality |
|---|---|---|
| EA-0029 | FR-7 delegated to a `SurfaceFacet` + `api_endpoint`/`federated_identity` | none of those types exist; the real seam is `KnownSurfaceSource → KnownSurfaceRecord` |
| EA-0030 | §0 asserted the module was net-new | true, but only confirmed by re-running the check against `src/` |
| EA-0031 | the DSPM surface row "replaces the same-object inventory placeholder" | it keyed on `obj_` while the placeholder keys on `ast_`; the replacement could never fire |

These are cheapest to kill before implementation. This file is where the reviewer hands over what
only the repo can answer. **It is cumulative** — each round appends; nothing is dropped.

---

## Part 1 — Standing rules for every spec

Each rule names the round that earned it, so the cost is visible.

### 1. Read the next free ECR number from `ECR-LOG.md`, never from context
A stale counter silently overwrites an accepted decision. Hit 2026-07-19: a proposed ECR was
numbered "0017", which was already an accepted corroboration-independence decision. Also check any
"what's built so far" claim against `git log` — the same stale message listed two merged milestones
as still to build.

### 2. Run the ECR-0015 event/type restatement check against shipped `src/`, not against the master
Do not accept the archive master's own §0 claim that a module is new. The reviewer runs the grep and
publishes the counts in Part 2. A module that restates an existing capability must route to the
owner instead of re-implementing.

### 3. Grep every named type and API of a delegation target before writing FR text
If an FR says "delegate to X", `X` must exist in shipped code with that exact name and signature.
This is the ECR-0027 class and it is the single most expensive thing to catch late (EA-0029).

### 4. Tri-state status audit: `bool` + absence is always the bug
Every status field must distinguish *computed and negative* from *never computed*. Absence must never
resolve toward "safe".
- `reachable_object_ids=[] , truncated=False` conflated "reaches nothing" with "never ran" → ECR-0035
  `reach_status: computed|truncated|pending`.
- `SupplyChainAssessment.truncated: bool` could not say "didn't assess" → `AssessmentStatus`.
- `PriorityFactor` had no `unknown`, so an unassessable vulnerability scored exactly as safe as a
  proved-unreachable one → ECR-0040.
- Use semantic tokens, **not** `"true"/"false"/"unknown"` strings — those are all truthy, so
  `if x.over_scoped:` misfires (ECR-0033).

### 5. Absence of a modifier must not reduce a score
Related to rule 4 but distinct: when an optional factor is missing, the result must not improve.
EA-0023's `ExposureImpactContext` gets this right — no context behaves as factor `1.0` (maximum
impact), so not knowing a store's sensitivity never buys it a lower score.

### 6. Losing or corrupting evidence must never improve an answer
EA-0031 P2 discarded a detector signal whose evidence was missing *or failed integrity
verification*, then classified the field from the weaker surviving candidate: `public / known /
flagged=False`, while the same input with readable evidence produced `unknown / conflict / flagged`.
Specify that unusable evidence is refused (`EvidenceNotFound` vs `EvidenceTampered`), never silently
skipped, and keep *absent* distinguishable from *tampered*.

### 7. `Workflow.propose(..., source_finding=finding)` is mandatory for finding-driven proposals
A finding carrying `Automation(eligibility="none")` only blocks execution if the run is bound to it —
`gating.py` checks `if source_finding is not None`. EA-0031 P4 omitted the argument; the proposed run
executed against the real engine after one ordinary approval. EA-0011/0012/0013/0014/0018 all pass it.

### 8. Evidence integrity is not authenticity
EA-0004 `verify()` proves AQELYN's own hash chain was not altered. It does **not** prove a publisher
signature is authentic — EA-0004 D4 reserves signing for a later ADR. Wiring `verify().ok` into a
trust claim would be the platform forging a claim from its own hash chain (ECR-0039). Two stages:
EA-0004 integrity first, then a typed kind-specific verifier supplied by a trusted adapter
(`supplychain/provenance.py::ProvenanceVerifier` is the shipped pattern).

### 9. Persistence shape decides whether an "additive" field is free
Check the target table before calling a new field additive. `asset_ref` is `jsonb`, so
`AssetRef.object_id` round-tripped for free; `aq_exposure_record` is **columnar**, so
`impact_context` needed a DDL column, `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for existing
deployments, and all write/read mapping sites — otherwise it passes in-memory and silently returns
`None` on Postgres.

### 10. Pagination: EA-0002 D8 semantics from the first persistence ticket, under a work budget
Stable id order, exclusive cursor, `next_cursor` non-null exactly when another matching row exists,
filters applied **before** `LIMIT`. Do not trade a silent cap for unbounded per-request scanning
(ECR-0031) — page under a budget and report `truncated`.

### 11. Health probes must be tenant-scoped, and both tenant modes must be exercised
`create_inmemory_runtime()` defaults to `tenant_mode="local"`, so driving "the factory-built runtime"
proves nothing about enterprise. Acceptance criteria must parametrize `(backend, tenant_mode)`.
Only a minority of services define a `_health_tenant()` helper; the ones whose probes issue
tenant-scoped queries need it. Known open instances: EA-0027 `idthreat_engine`, EA-0018
`response_engine` — both currently fail enterprise startup.

### 12. Confirm module ownership from `README.md` before naming an EA in a finding or dependency
`README.md` maps EA number → `src/` path. A wrong EA number sends the reader to the wrong spec and
the wrong task bundle. (Reviewer mislabelled `src/aqelyn/response/` as EA-0016 three times; it is
EA-0018. EA-0016 is Digital Forensics, `src/aqelyn/forensics/`.)

### 13. Handed-in descriptors, not collection
Analytical engines accept already-produced records. They open no socket, hold no credential, poll
nothing. Live collection is a later connector delivered as an EA-0008 gated action, and the
descriptor is the seam that keeps the engine unchanged when connectors land. Enforce it with a
grep/no-network test in the suite (`test_tif_ingest_no_fetch`,
`test_dspm_no_collection_or_bulk_read`).

### 14. Minimal retention is structural, not a prose promise
If a module handles sensitive material, the typed shapes must make raw content unconstructible
(`extra="forbid"`, no `value`/`sample`/`content`/`blob` field), and the acceptance test must attempt
construction rather than grep for the words.

### 15. Sequence a type with the ticket its dependency lands in
A type pulled into an earlier ticket than the change it depends on can have an interim where its only
constructible form violates a rule that arrives later — it will pass its own ticket's tests and fail
the system. (C-029 W1 shipped `CryptographicExposure` while the `credential_sensitivity` widening it
needs was scheduled for W4, so on-branch it could *only* be built with the ECR-0044-forbidden
`data_sensitivity` kind.) At spec/bundle stage, if ticket N defines a type whose valid construction
depends on a change in ticket N+k, either move the additive dependency forward to N or defer the type
to N+k. Review a type against the ticket its dependency lands in, never in isolation.

---

## Part 2 — Current handover: IS-033 / EA-0033 (Identity Security Posture Management)

**Repository state:** `main @97efba5`, green (ruff, format, mypy --strict over 300 files,
1193 passed / 3 skipped on live PG16 + Redis 7).
**Next free ECR:** **0049** (log ends at ECR-0048 — re-read `ECR-LOG.md` before use).
**Component:** Identity Security Posture Management (ISPM) Intelligence Engine.
**Layout:** propose `src/aqelyn/ispm/` + `tests/ispm/`; confirm against `README.md`'s mapping table.
The archive master's "Next" pointer (ISPM) was verified against `archive/EA-0033/EA-0033_Master.md`.

### ECR-0015 check — run against shipped `src/`: this is MOSTLY already owned

```
ispm 0 · identity_posture 0 · posture_score 1(unrelated, executive KPI) · federated 0
service_account 0 · machine_identity 0 · identity-drift 0     <- genuinely net-new
entitlement 107 · certification 154 · privilege 34 · dormant 19 · orphaned 12
access_path 23 · sod 1        <- ALL already owned by EA-0011 (IAG)
```

**This is the DSPM/SSPM/CSPM posture pattern, FOURTH instance — and the identity-governance half
already ships.** The master lists standalone-sounding components (Posture Assessment Engine, Risk
Scoring Engine, Drift Detection, Recommendation Engine, Identity Classification), but EA-0011 already
owns identity governance. The central spec question, exactly as for DSPM: **is ISPM a new capability,
or a normalize + score + route posture layer over EA-0011?** It is the latter, plus three genuinely-new
pieces (scoring, drift, wider-scope normalization). Do not let the master's component list become five
new engines.

### What EA-0011 (IAG) already owns — ROUTE to it, do not reimplement

Verified in `src/aqelyn/iag/`:
- `IAGEngine.access_paths(identity_id, *, tenant_id)` → `list[AccessPath]`
- `IAGEngine.analyze_risk(*, tenant_id, scope)` → `AccessRiskReport` — internally computes **orphaned,
  dormant, over-privileged, SoD (via Policy), privileged-unreviewed** risks. ISPM must not re-derive any
  of these.
- `open_certification` / `decide_item` / `complete_certification` — access-review campaigns. ISPM
  certification **is** this; do not create a parallel certification path.
- `risks_to_findings(*, by)` — evidence-backed findings into EA-0013. No new `SignalKind`.
- Models to reuse, not redefine: `AccessPath`, `AccessRisk`, `AccessRiskReport`, `ReviewItem`,
  `Certification`, `IAGConfig`.

### The three genuinely-new capabilities (where ISPM earns its existence)

1. **Deterministic 0–100 Identity Security Posture Score** (master REQ-FR-033-011). Compose EA-0013
   risk scoring / EA-0007 mission / EA-0006 trust — do not stand up a second scorer. Mission-weighted,
   deterministic, replayable (EA-0020 `Derivation`).
2. **Identity posture drift** against approved baselines — reuse the EA-0012 drift shape
   (`src/aqelyn/assetconfig/`, declarative baseline `(key, expected, comparator)` vs observed,
   append-only drift snapshots), do not invent a parallel drift engine.
3. **Wider-scope identity normalization** — classify/normalize identities from sources EA-0011 does
   not already govern (human/service/machine/application/federated/temporary) into EA-0002 objects that
   EA-0011's `analyze_risk` can then read. This is the DSPM parallel: same governance vocabulary, wider
   discovery scope. Reuse EA-0011's identity object shape rather than a new one.

### Boundaries to state in §0

- **Handed-in descriptors, not connectors (rule 13).** The master's ARC-033-001/002 ("Identity
  Discovery Manager", "Connector Orchestration Layer", "Provider-specific payloads") is the EA-0031 /
  EA-0014 trap — a real §0 hazard. ISPM opens no socket to Okta/AD/AAD/PAM, holds no credential, polls
  nothing. It accepts already-produced, versioned identity descriptors; live provider ingestion is a
  later EA-0008-gated connector. Enforce with a no-network/grep test.
- **Detect and propose, never act.** Master §2.2 (out of scope): "Direct modification of identity
  provider configuration." Remediation is an EA-0008 `requires_approval=True` proposal with
  `source_finding` bound (rule 7) — never executed.
- **Tri-state floor (rule 4/5), sharp for identity posture.** An identity whose MFA status, lifecycle
  state, or last-activity is *unknown* must not score as MFA-present / active / recently-reviewed.
  Missing control facts are `unknown`, excluded from the favourable side of the score denominator
  (the ECR-0040 shape) — never a favourable default.

### Delegation seams, verified present in shipped code

| Need | Shipped seam |
|---|---|
| identity governance risk | EA-0011 `analyze_risk`, `access_paths` (orphaned/dormant/over-priv/SoD) |
| access-review certification | EA-0011 `open_certification` / `decide_item` / `complete_certification` |
| identity objects | EA-0002 `ObjectStore.upsert` (identity/account object types EA-0011 already reads) |
| inventory registration | EA-0025 `InventoryIntelligenceEngine.ingest(reports=, source=DiscoverySource, tenant_id=)` |
| exposure | EA-0023 `KnownSurfaceSource → KnownSurfaceRecord`; `AssetRef.kind="identity"` already exists |
| risk score composition | EA-0013 risk scoring · EA-0007 mission · EA-0006 trust; replay via EA-0020 `Derivation` |
| drift pattern | EA-0012 `src/aqelyn/assetconfig/` declarative baselines + append-only snapshots |
| compliance | EA-0010 `assess` |
| findings | EA-0011 `risks_to_findings` / EA-0013 finding path — no new `SignalKind` |
| remediation | EA-0008 `propose(playbook, by=, source_finding=)` |

### False friends — names already taken

- **`cert` prefix** = `iag_certification` (EA-0011). ISPM certification IS EA-0011's; do not mint a
  parallel prefix or a second certification model.
- **`aqelyn.iag.*` events already exist** (`certification_opened/completed`, `item_decided`,
  `risk_detected`). ISPM's own events (posture-scored / drift-detected / identity-normalized) must be
  net-new `aqelyn.ispm.*` (or similar), and must not re-emit EA-0011's.
- **`AssetRef.kind="identity"`** already exists for EA-0023 exposure — reuse it.

### ECR-0044 shape to anticipate at the exposure step

If ISPM feeds identity sensitivity into EA-0023 scoring, `ExposureImpactKind` is currently
`data_sensitivity | credential_sensitivity` (ECR-0041/0044). An identity-sensitivity factor needs the
same additive-widening + replay-pin treatment (a new `identity_sensitivity` kind, `data_sensitivity`
default preserved) — anticipate it in the spec rather than discovering it mid-build.

### ECR-0032 — the FOURTH posture instance

CSPM, SSPM, DSPM, now ISPM. The shared posture-normalization-base revisit condition is well past met.
Keep it Proposed and after C-030 green (behaviour-preserving refactor, not this milestone), but note in
the spec that ISPM is the fourth `normalize → score → route` instance.

### Open follow-up this module must not weaken

**ECR-0034** (inventory `limit=10_000` reports itself complete) remains unimplemented. If ISPM
registers identities into EA-0025, it inherits the cap and adds to the same store — state the
dependency; do not treat the inventory report as exhaustive.
