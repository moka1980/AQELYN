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

---

## Part 2 — Current handover: IS-032 / EA-0032

**Repository state:** `main @6d8ab03`, green (ruff, format, mypy --strict over 289 files,
1113 passed / 3 skipped on live PG16 + Redis 7).
**Next free ECR:** **0043** (log ends at ECR-0042 — re-read before use).
**Component:** Secrets Security & Cryptographic Asset Intelligence Engine.
**Layout:** propose `src/aqelyn/secrets/` + `tests/secrets/`; confirm against `README.md`'s mapping
table (EA-0030's master proposed a path that did not match the convention).

### ECR-0015 check — run against shipped `src/`, result: genuinely NET-NEW

```
certificate 0 · crypto 0 · cipher 0 · tls 0 · x509 0 · rotation 0
ssh_key 0 · keystore 0 · vault 0 · kms 0 · hsm 0 · expiry 0 · not_after 0
secret 15  <- two unrelated senses, see below
```

No shipped events for secrets, certificates or cryptographic material.

### False friends — names already taken in another sense

1. **`secret`** has two existing, unrelated meanings: `conventions/logging.py::_SECRET_KEYS`
   (log-redaction key names) and the EA-0019 `Classification` literal
   `public|internal|pii|secret` — a **data sensitivity level**, now load-bearing in EA-0031's
   `max_known_sensitivity` and `sensitivity_factors`. Neither is a cryptographic secret. Do not
   overload that literal.
2. **`cert` is a taken id prefix**: `PREFIXES["cert"] = "iag_certification"` (CONVENTIONS §1,
   EA-0011 access certification). The only shipped certification events are
   `aqelyn.iag.certification_opened` / `_completed` — *access review campaigns*, not X.509.
   EA-0032 needs different prefixes and different event names. Register new prefixes in both
   `conventions/ids.py::PREFIXES` and CONVENTIONS §1; new errors in `errors.py` and CONVENTIONS §9
   (a test asserts the code set).

### Boundaries to state in §0

- **Integrity ≠ authenticity (rule 8).** This module will be tempted to say "AQELYN verifies the
  certificate". Chain/signature validation is a typed verifier supplied by a trusted adapter;
  EA-0004 integrity is a separate, earlier stage; unverifiable material stays flagged, never assumed
  good.
- **No collection (rule 13).** No connection to Vault, KMS, HSM, cloud secret managers or
  repositories; no credential held; no repo scanning. Handed-in descriptors only.
- **Detect and propose.** Rotation, revocation and re-issuance are EA-0008 proposals with
  `requires_approval=True` and `source_finding` bound (rule 7) — never executed.
- **No PII/secret lake (rule 14).** Descriptors carry metadata, fingerprints and references — never
  key material, private keys, or secret values. Make it unconstructible in the types.

### Delegation seams, verified present in shipped code

| Need | Shipped seam |
|---|---|
| asset registration | EA-0025 `InventoryIntelligenceEngine.ingest(reports=, source=DiscoverySource, tenant_id=)` |
| exposure / reachability | EA-0023 `KnownSurfaceSource → KnownSurfaceRecord`; ECR-0041 `AssetRef.object_id` (surface identity `ast_`, scoring subject `obj_`) and `ExposureImpactContext` |
| policy conditions | EA-0009 `condition_matches` / `Condition` |
| compliance | EA-0010 `assess` |
| risk | EA-0013 via evidence-backed `Finding`s — **no new `SignalKind`** |
| remediation | EA-0008 `propose(playbook, by=, source_finding=)` |
| confidence | EA-0006 Trust |
| evidence | EA-0004 `add` / `get` / `verify` |
| authenticity | typed verifier, pattern at `supplychain/provenance.py::ProvenanceVerifier` |

### Domain-specific tri-state warning (rule 4 applied here)

Cryptographic lifecycle is unusually prone to the absence-means-safe bug:

- "no expiry date found" must not read as **not expiring**;
- "algorithm not recognised" must not read as **strong**;
- "no rotation record" must not read as **recently rotated**;
- an unreadable or unparsable certificate must not read as **valid**.

Each of these needs a named status with an explicit unknown, and the unknown must be excluded from
any score denominator rather than contributing a favourable zero (ECR-0040's shape).

### Open follow-up this module must not weaken

**ECR-0034** (Accepted-as-Proposed, not yet implemented): `InventoryIntelligenceEngine.inventory()`
reads `store.query(limit=10_000)` and hardcodes `degraded=False`, so an estate above 10 000 assets is
reported as complete. If EA-0032 registers cryptographic assets into EA-0025, it inherits that cap
and adds to the same store. State the dependency; do not assume a complete inventory.
