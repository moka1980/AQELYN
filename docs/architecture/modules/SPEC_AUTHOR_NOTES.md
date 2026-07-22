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
Denominator exclusion alone is not sufficient: C-030 G4 showed that dropping an unknown MFA factor
would otherwise make the unknown case score exactly like MFA-present. Test the same subject with the
factor known-good, known-bad, and unknown; the unknown result must not become the favourable result.

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

### 16. Prove the no-action boundary against the owning finding's automation contract
`source_finding` binding is mandatory (rule 7), but not every owner finding has
`eligibility="none"`. EA-0033 correctly preserves EA-0011's `assisted` access-remediation contract:
the module only proposes, `requires_approval=True`, and the real workflow refuses execution before
approval. Do not rewrite an owner's automation semantics merely to make a stronger-looking test.
Drive the real workflow and prove the exact applicable boundary: permanent refusal for `none`, or
approval-gated execution for `assisted`.

### 17. Historical handoffs pin exact owner records; they never recompute
C-030 G5 exposed this at the assessment-to-finding boundary. A method accepting only an assessment
id cannot later reproduce the records it used unless the assessment durably stores their exact ids.
Persist the owner refs at computation time, validate them on read, and route those records forward.
Re-running the owner engine against today's estate is silent historical drift, not reconstruction.

---

## Part 2 — Current handover: IS-034 / EA-0034 (Machine Identity & NHI Governance)

**Repository state:** `main @496f0e8`, green (ruff, format, mypy --strict,
1237 passed / 3 skipped on live PG16 + Redis 7).
**Next free ECR:** **0053** (the log ends at ECR-0052; re-read it before assigning).
**Archive verified:** `archive/EA-0034/EA-0034_Master.md` is IS-034, Machine Identity &
Non-Human Identity Governance. Its continuation to IS-035 was checked against the actual
`archive/EA-0035/EA-0035_Master.md`, whose title is Secrets, Keys & Certificate Lifecycle
Governance — a likely EA-0032 restatement to inspect at that later turn.

### ECR-0015 result — do not build a second identity module

The master's exact PascalCase event/type names have no literal shipped collision, but the
capabilities and semantic events do. This is the IS-026 result distributed across several existing
owners rather than concentrated in one package.

```
17 declared master events: 0 exact matches in src/aqelyn
machine_identity 0 · non_human 0 · workload_identity 0 · service_account 0

Master machine/NHI categories       -> EA-0033 IdentityKind already includes
                                       service|machine|application|federated|temporary
discovery + normalization + score   -> aqelyn.ispm.identity_normalized / posture_scored
governance drift                    -> aqelyn.ispm.posture_drift_detected
credential/certificate lifecycle    -> aqelyn.crypto.* + EA-0032 stores and assessment
orphan/dormant/privilege/certify    -> aqelyn.iag.* + EA-0011 analysis/certification
asset ownership + lifecycle         -> aqelyn.inventory.* + EA-0025 Ownership/lifecycle
recommendation/workflow             -> aqelyn.decision.* / aqelyn.workflow.*
```

**Decision for the spec pass:** machine identity is a scope over EA-0033's identity capability, not
a new capability owner. Do not create `src/aqelyn/machine_identity/`, a second identity repository,
a second posture score, or a `machine_identity_engine` service. Propose ECR-0053 as an IS-034
conformance decision and realize only the genuine gaps as small enhancements to their existing
owners. If a task bundle says a new package or service is required, the reconciliation has gone
wrong.

### Capability ownership — verified against shipped code

| Archive capability | Shipped owner / exact seam |
|---|---|
| handed-in discovery + normalization | EA-0033 `ISPMEngine.ingest_identities(descriptors, *, tenant_id)` |
| canonical identity/account objects | EA-0033 writes EA-0002 `AQObject`s and `has_account` relationships |
| service/machine/application identity kinds | EA-0033 `IdentityKind` — already in the persisted model |
| identity posture and coverage | EA-0033 `score_identity`, `assess`; exact scores pinned in `ISPMAssessment.score_ids` |
| governance drift | EA-0033 `detect_drift` using the EA-0012 comparator shape |
| access paths, orphan/dormant/privilege/SoD | EA-0011 `access_paths`, `analyze_risk` |
| access certification | EA-0011 `open_certification` / `decide_item` / `complete_certification` |
| ownership and asset lifecycle | EA-0025 `InventoryIntelligenceEngine.ingest`, `ownership`, `mark_unreported`, `decommission` |
| secrets, keys, certificates, rotation/expiry | EA-0032 `ingest_crypto_assets`, `assess_key`, `assess_certificate`, `propose_rotation` |
| relationship storage / traversal | EA-0002 `ObjectStore.relate`; EA-0005 graph paths/subgraphs |
| trust | EA-0006 `TrustEngine.assess` |
| policy | EA-0009 `PolicyEngine`; do not add a machine-identity rule language |
| findings | EA-0011 `risks_to_findings` / EA-0013 finding path; no new `SignalKind` |
| recommendation | EA-0020 replayable advisory `Recommendation`; no prose-only recommendation engine |
| remediation | EA-0008 `WorkflowEngine.propose(..., source_finding=finding)` |
| reporting | EA-0022 figures/briefings; no machine-identity report engine |

### The genuine remainder — enhancements, not a module

1. **Ownership handoff is not connected.** EA-0025 already owns `Ownership` and reconciles it by
   source reliability, but EA-0033's `IdentityDescriptor` has no owner claim and
   `ispm.normalize.inventory_report()` omits `owner`. Add an evidence-backed ownership input and
   prove a real ISPM ingest produces the same owner through `InventoryIntelligenceEngine.ownership`.
   Do not create an NHI ownership store.
2. **Identity-to-credential/workload bindings are not represented.** EA-0033 currently accepts only
   `has_role|grants_entitlement|member_of` access edges (plus its required `has_account` edge).
   EA-0032 stores secret/key/certificate objects, but no shipped seam binds them to the non-human
   identity that uses them. Add a narrow, typed, evidence-backed relationship input to EA-0033 and
   persist it with EA-0002 `relate`; use EA-0005 for traversal. Never copy credential metadata or
   secret values into ISPM.
3. **Provider lifecycle detail is collapsed.** EA-0033 normalizes lifecycle to
   `present|absent|unknown`; values such as requested, provisioned, rotating, suspended, and revoked
   are not retained as an append-only identity lifecycle history. First map states that genuinely
   belong to EA-0025's asset lifecycle. If identity-only states remain, add the narrow history to
   EA-0033 under change control — not a second lifecycle engine — and keep source silence distinct
   from suspension/revocation.
4. **Missing archive events belong to their owners.** A needed credential-rotation event is an
   additive `aqelyn.crypto.*` event; an identity lifecycle event is an additive `aqelyn.ispm.*`
   event only if EA-0025's `aqelyn.inventory.lifecycle_changed` cannot express it. Do not re-emit
   existing ISPM, IAG, inventory, crypto, decision, or workflow events under a new NHI namespace.

A small conformance bundle is the expected shape: shipped-code conformance first, then only the
owner-handoff/relationship/lifecycle gaps that survive that proof. No service/factory ticket should
exist unless an existing owner's service needs an additive method or event.

### Boundaries the spec must make structural

- **Handed-in descriptors only.** The master repeatedly asks for connector orchestration and
  continuous discovery. IS-034 opens no provider/Kubernetes/vault connection, holds no credential,
  and schedules nothing. Connectors remain future EA-0008-gated actions; scheduling remains a
  platform capability.
- **No credential values.** Reuse EA-0032's value-free descriptors/records. A machine-identity link
  carries ids, fingerprints where already permitted, evidence, and provenance — never a key, token,
  password, certificate private material, or provider payload.
- **Absence is not revocation or safety.** A source going quiet maps through EA-0025's `unreported`
  rule; it never suspends, revokes, archives, or deletes an identity. Missing ownership, lifecycle,
  or credential binding is `unknown`/flagged and cannot improve posture.
- **One score owner.** Any machine-identity posture result extends EA-0033's replayable score and
  pinned owner inputs. It must not introduce `MachineIdentityRiskScore`, `GovernanceScore`, or a
  second scorer merely because the subject is non-human.
- **No action.** Suspend, revoke, rotate, renew, or alter privileges only through an EA-0008
  proposal bound to its source finding. Preserve the owning finding's automation contract and prove
  the real workflow boundary per rule 16.
- **No synthetic trust.** Confidence comes from EA-0006; EA-0004 integrity does not prove provider,
  workload, certificate, or event authenticity.
- **No silent cap.** Every inventory-backed assessment inherits unresolved ECR-0034. It must expose
  incomplete coverage and must not claim the first 10,000 assets are the whole NHI estate.

### Acceptance proofs to require

- **Conformance, not grep alone:** construct each supported non-human `IdentityKind`, ingest it
  through the real EA-0033 engine, and show the real EA-0011 analysis can act on its account graph.
- **Ownership round trip:** handed-in owner evidence -> EA-0033 ingest -> real EA-0025
  `ownership(...)`, including conflicting-source reliability and unresolved ties.
- **Credential binding round trip:** real EA-0032 crypto object -> evidence-backed EA-0002 relation
  from the normalized machine identity -> EA-0005 traversal; missing/tampered evidence writes
  neither the edge nor a favourable assessment.
- **Lifecycle contrast:** explicit revoked/suspended evidence, healthy active evidence, and source
  silence produce three distinguishable results; silence must become unreported/unknown, never
  revoked or clean.
- **No duplicate computation/events:** owner spies prove delegation, then real-owner tests prove the
  handoffs are actionable. Event registration must contain only genuinely new owner events.
- **No values under normal Python and `python -O`; no network attempts; both backends and both tenant
  modes.**

### Existing follow-ups to preserve, not absorb

- **ECR-0032 (Proposed):** the shared posture-normalization-base revisit threshold was met before
  EA-0033. IS-034 must not become a fifth implementation while that decision remains open.
- **ECR-0034 (Proposed):** inventory's 10,000-row cap can report a partial denominator as complete.
- **EA-0018:** `response/metrics.py` has an unclamped negative-duration timestamp flake.
- **EA-0027 + EA-0018:** enterprise-mode health probes remain unscoped in `idthreat_engine` and
  `response_engine`.
- **EA-0013:** equal-timestamp finding ordering still needs a deterministic tie-breaker.

### Pasteable spec-author brief

> Treat IS-034 as conformance plus targeted enhancement, not EA-0034 as a new runtime module.
> Machine/non-human identity is already an EA-0033 `IdentityKind` scope; governance is EA-0011,
> ownership/lifecycle EA-0025, credentials/certificates EA-0032, trust EA-0006, policy EA-0009,
> recommendations EA-0020, and actions EA-0008. Propose ECR-0053 to forbid a second identity store,
> score, service, or event namespace. Verify conformance against shipped code first. The honest
> remainders are: carry evidence-backed ownership from EA-0033 into EA-0025; add narrow
> evidence-backed identity-to-crypto/workload relationships through EA-0002/0005; and preserve any
> genuinely identity-specific lifecycle states without conflating source silence with revocation.
> Every handoff needs a real-owner round trip, not only a spy. Handed-in descriptors only, no secret
> values, no direct action, no favourable unknown, no duplicate events, and no claim of exhaustive
> inventory while ECR-0034 remains open.

---

## Prior handover — IS-033 / EA-0033 (Identity Security Posture Management)

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
