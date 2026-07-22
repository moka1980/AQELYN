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

### 18. A test double that stops conforming to its Protocol stops testing that contract
ECR-0052 additively made `IdentityGovernanceOwner.risks_to_findings` tenant-scoped, but the C-030 G3
spy retained the old signature. The implementation was correct and `mypy --strict src` was green;
`mypy --strict src tests` failed because the test double no longer represented the owner interface.
A stale spy can leave assertions green while silently testing a different call shape. Whenever a
Protocol changes, sweep every implementation and test double, statically check the full `src tests`
surface, and assert forwarding of the new argument or result. A spy proves delegation only while it
continues to satisfy the Protocol it doubles.

---


## Part 2 — Current handover: IS-035 / EA-0035 (Secrets, Keys & Certificate Lifecycle Governance)

**Repository state:** `main @6edfba8`, green (ruff, format, `mypy --strict src tests` 479 files,
1260 passed / 3 skipped live PG16+Redis7).
**Next free ECR:** **0054** (log ends at ECR-0053; re-read `ECR-LOG.md` before assigning).
**Archive verified:** `archive/EA-0035/EA-0035_Master.md` is IS-035, *Secrets, Keys & Certificate
Lifecycle Governance Engine*.
**Layout:** there is NO new package. Enhancements land in **`src/aqelyn/secrets/`** (EA-0032).

### ECR-0015 result — this is EA-0032, again. Do not build a second secrets engine.

Run by the reviewer against shipped `src/`:

```
secret_asset / cryptographic_key / x509_certificate object types : 5 each  (EA-0032 owns)
rotation 28 · revocation 19 · expiry 17 · propose_rotation 3              (EA-0032 lifecycle)
sct / cky / x509 prefixes : 8 each · cas                                  (EA-0032 PREFIXES)
secrets_engine 16 · aqelyn.crypto.* 4 events                              (EA-0032 service/events)
renewal 0 · kms 0 · certificate.*lifecycle 0                             <- net-new *vocabulary* only
```

**IS-035 is the third distributed-conformance case (after IS-026 and IS-034).** EA-0035 renames
EA-0032's shipped capability — secrets, keys, certificates, their lifecycle (expiry/strength/rotation/
chain/revocation/integrity/authenticity), rotation proposals, exposure, compliance, findings, and the
value-free no-plaintext guarantee — under a "governance" label plus a provider list (Vault, CyberArk,
Azure Key Vault, AWS Secrets Manager, KMS, PKI, HSM). Building the archive literally would create a
second secrets store, a second crypto object model, duplicate lifecycle logic, duplicate `sct`/`cky`/
`x509` prefixes, a second `secrets_engine`, and a renamed `aqelyn.crypto.*` namespace.

**Propose ECR-0054 as an IS-035 conformance decision.** There SHALL be no `src/aqelyn/secrets2/` (or
`credential_governance/`), no second secrets store, no second crypto asset/score model, no duplicate
prefix, no second `*_engine` service, and no new event namespace. If the drafted bundle calls for a new
package or service, the reconciliation has gone wrong. First verify conformance against shipped code,
then realize only the genuine gaps as additive, owner-scoped enhancements to **EA-0032**.

### What EA-0032 already owns — route/reuse, never re-derive

Verified present in shipped `src/aqelyn/secrets/`:
- `SecretsIntelligenceEngine.ingest_secrets`, `ingest_crypto_assets` (handed-in descriptors, value-free)
- `assess_key`, `assess_certificate`, `assess` — tri-state lifecycle (`valid|invalid|unknown`),
  two-stage cert verification (EA-0004 integrity ≠ authenticity, ECR-0039/0046)
- `analyze_exposure` (EA-0023 seam, `credential_sensitivity` ECR-0044), `propose_rotation` (EA-0008
  gated, `source_finding`-bound, never executes)
- object types `secret_asset`/`cryptographic_key`/`x509_certificate`; prefixes `sct`/`cky`/`x509`/`cas`
- **value-free by construction** — `_ValueFreeModel`, `extra="forbid"`, no raw-value/content field;
  the master's "no plaintext" boundary is ALREADY structural. Do not re-implement it.

### The genuine remainders (candidate enhancements to EA-0032, owner's call)

1. **A deterministic per-credential governance SCORE (0–100).** Verified EA-0032 has *no* per-asset
   score today — `CryptoAssessment` carries counts, not a score. This is the one genuinely-new
   capability, and it is **the EA-0033-ISPM posture-score pattern applied to crypto**: compose EA-0032
   lifecycle + EA-0025 ownership + EA-0023 exposure + EA-0006 trust + EA-0007 mission + EA-0010
   compliance into a replayable **EA-0020 `Derivation`**. It MUST follow the ISPM rules exactly:
   - **No second scorer** — compose EA-0013 risk / EA-0007 / EA-0006, do not stand up a new one.
   - **Unknown excluded from the denominator, never favourable** (rules 4/5; the ECR-0040/ISPM-G4
     shape — an unknown control must not let a credential outscore a proven-good one, and
     `known_only × coverage_adjustment` is the shape that avoids "unknown == present").
   - **Replayable or unrepresentable** (S1c) — a score whose derivation does not replay is rejected at
     `put`, driven against the real scorer per ECR-0007, not a spy.
2. **Storage-safety governance** — EA-0032's `SecretLocation` has kinds (`repository`/`configuration`/
   `vault_reference`/`runtime_reference`/`other`) but no approved-vs-unsafe classification. A
   metadata-only "is this stored in an approved vault/KMS/HSM vs an unsafe location" signal is a narrow,
   value-free addition. Never store or infer the secret itself.
3. **Ownership handoff for credentials → EA-0025** — the C-031 H2 pattern (identity ownership → real
   `Ownership`/`reconcile`, evidence-pinned, missing=unknown) applied to crypto assets, if wanted.

**Explicitly resist:** the archive's rich lifecycle STATE MACHINES
(`Requested→Approved→…→Archived`, `Requested→Validated→Issued→…→Archived`). EA-0032's shipped reality is
tri-state lifecycle *fields* (`valid|invalid|unknown`), which is sufficient. Do **not** build a
lifecycle state-machine engine or a transition-event store unless a specific governance need is proven
against shipped gaps — a 13-state credential machine is archive over-specification.

### Boundaries (unchanged from the family)

- **Handed-in descriptors, not connectors** (rule 13). The provider list (Vault/CyberArk/KMS/PKI/HSM)
  is the EA-0031/0034 trap — live provider ingestion is a later EA-0008-gated connector; EA-0032
  accepts handed-in descriptors and holds no credential.
- **Detect and propose, never act** — rotation/revocation is EA-0032's `propose_rotation` (gated,
  `source_finding`-bound, `requires_approval=True`); the master's "no unauthorized rotation" is already
  the shipped guarantee.
- **Value-free is structural** (rule 14) — reuse `_ValueFreeModel`; never a plaintext field.
- **No-action boundary** proven against the OWNING finding's actual automation contract (rule 16) — for
  EA-0032 that is eligibility-`none` (structural execute-block), verified behaviourally.

### Delegation seams, verified present in shipped code

| Need | Shipped seam |
|---|---|
| secret/key/cert assets + lifecycle | EA-0032 `ingest_secrets`/`ingest_crypto_assets`/`assess_key`/`assess_certificate` |
| rotation proposal | EA-0032 `propose_rotation` (EA-0008 gated) |
| exposure | EA-0023 `KnownSurfaceSource`; EA-0032 `analyze_exposure` + `credential_sensitivity` |
| ownership / storage lifecycle | EA-0025 `Ownership`/`ingest`/`reconcile`/`ownership` |
| score composition | EA-0013 risk · EA-0007 mission · EA-0006 trust; replay EA-0020 `Derivation` |
| compliance | EA-0010 `assess` |
| findings | EA-0013 finding path — no new `SignalKind` |
| relationships / traversal | EA-0002 `ObjectStore.relate`; EA-0005 bounded paths |

### False friends — names already taken

- Prefixes `sct`/`cky`/`x509`/`cas` are EA-0032's. A new governance-score record needs a *new* prefix
  (verify collision-free against `PREFIXES` at spec stage, e.g. name it in §9 like EA-0032 did).
- `aqelyn.crypto.*` events belong to EA-0032; a governance-score event must be net-new and not re-emit
  them. `secrets_engine` is EA-0032's service name.

### Open follow-up this must not weaken

**ECR-0034** (inventory `limit=10_000` reports complete) remains unimplemented. If credential governance
registers or reads crypto assets through EA-0025, it inherits the cap — keep coverage honest.
