# IS-034 Conformance Analysis - distributed ownership, no EA-0034 runtime module

**Determination:** IS-034 (Machine Identity & Non-Human Identity Governance) is
**not a new capability owner**. Its behavior is already distributed across
EA-0033 (identity normalization/posture), EA-0011 (identity governance), EA-0025
(inventory ownership/lifecycle), EA-0032 (secrets/keys/certificates), EA-0002/
EA-0005 (relationships/traversal), and the existing trust, policy, decision,
workflow, and reporting owners. See **ECR-0053**.

**Delivery consequence:** do not create `src/aqelyn/machine_identity/`, an
`nhi_engine`, another identity repository, another posture score, or an
`aqelyn.nhi.*` event namespace. IS-034 is realized by conformance proof plus the
small owner-scoped remainder in **C-031**.

**Verification standard:** this analysis compares archive capabilities and
semantic events with shipped code. Literal event/type grep is a useful first
signal, never the decision by itself (ECR-0007, ECR-0015, ECR-0053).

## Why the zero-collision result is not evidence of a new module

The archive declares 17 PascalCase events. None appears literally in
`src/aqelyn`, and the strings `machine_identity`, `non_human`,
`workload_identity`, and `service_account` likewise have no exact shipped hit.
That result would be decisive only if names and capabilities were equivalent.
They are not.

IS-026 was a concentrated restatement: one archive capability duplicated one
owner. IS-034 is a **distributed restatement**: a renamed subject scope groups
capabilities already owned by six modules. Each component can look new in
isolation while the proposed engine as a whole would fork every owner at once.

## Component and requirement mapping (verified against shipped code)

| IS-034 capability / requirement | Shipped owner and exact seam | Result |
|---|---|---|
| FR-001 discovery and canonical normalization | EA-0033 `ISPMEngine.ingest_identities(descriptors, *, tenant_id)` writes EA-0002 identity/account objects and EA-0025 inventory rows | Conforms; handed-in only |
| FR-002 identity classification | EA-0033 `IdentityKind` already includes `service`, `machine`, `application`, `federated`, and `temporary`; unknown remains flagged | Conforms |
| FR-003 accountable ownership | EA-0025 `Ownership`, reliability reconciliation, and `ownership(asset_id, *, tenant_id)` | Owner exists; EA-0033 handoff missing (C-031 H2) |
| FR-004 lifecycle tracking | EA-0025 lifecycle/unreported/decommission rules, EA-0033 lifecycle control/drift, EA-0032 crypto lifecycle | Base owners exist; provider-state mapping/history incomplete (H4) |
| FR-005 authentication assessment | EA-0011 `analyze_risk` / `access_paths`; EA-0033 controls and replayable posture | Conforms |
| FR-006 secret/credential/certificate governance | EA-0032 `ingest_crypto_assets`, `assess_key`, `assess_certificate`, `propose_rotation` | Conforms; identity-to-crypto binding missing (H3) |
| FR-007 privilege assessment | EA-0011 orphan/dormant/privilege/SoD analysis and certification | Conforms |
| FR-008 trust evaluation | EA-0006 `TrustEngine.assess`; EA-0033 and EA-0032 consume it | Conforms |
| FR-009 policy enforcement | EA-0009 policy plus owner findings and EA-0008 workflow | Conforms; no NHI rule language |
| FR-010 governance event publication | `aqelyn.ispm.*`, `aqelyn.inventory.*`, `aqelyn.crypto.*`, owner finding/decision/workflow events | Semantic conformance; any new lifecycle event stays with its owner |
| Governance score and drift | EA-0033 `IdentityPostureScore`, `score_identity`, `detect_drift`, `ISPMAssessment` | Conforms; no second score |
| Recommendation and remediation | EA-0020 replayable advisory recommendation and EA-0008 finding-bound proposal | Conforms; no direct action |
| Reporting and analytics | EA-0022 figures/briefings over owner records | Conforms; no NHI report engine |

The archive's machine identity categories are therefore subject scopes over
EA-0033's persisted identity model, not a reason to add another identity model.
Its "Machine Identity Repository" would be a second answer to the same object,
posture, governance, credential, and lifecycle questions.

## C-031 H1 shipped-code verification

**Verified against:** merged `main @1a62a72` (ECR-0053 and C-031 canonical).
**Result:** every conforming row above holds. The three partial rows remain the
explicit H2-H4 enhancement tickets; none requires a new runtime module.

- **Non-human identity scopes and real governance:** the parameterized
  `test_ispm_real_iag_round_trip` constructs each shipped non-human
  `IdentityKind` (`service`, `machine`, `application`, `federated`,
  `temporary`), ingests it through the real EA-0033 engine, and proves the real
  EA-0011 analyzer sees its dormant account without falsely calling it
  orphaned. Removing the `has_account` relationship in the negative control
  changes the owner verdict to orphaned. The resulting EA-0033 score pins the
  exact `AccessRisk` records.
- **Inventory ownership and lifecycle:** `test_inv_n2.py` proves EA-0025 owner
  reconciliation by reliability, conflict retention, and unresolved ties on
  both stores. `test_inv_n3.py` proves silence becomes `unreported`, unknown
  source health refuses the sweep, decommission requires evidence/decision,
  freshness is declared, and lifecycle history is append-only.
- **Credential and certificate lifecycle:** `test_secrets_w2.py` proves real
  EA-0002/EA-0025 object handoff; `test_secrets_w3.py` proves tri-state key and
  certificate lifecycle plus integrity/authenticity separation; W4/W5 prove
  finding-bound proposals, owner composition, and service/event ownership.
- **Relationships and traversal:** EA-0033 writes evidence-backed EA-0002
  `has_account` and access relationships; the real EA-0011/EA-0005 round trip
  consumes them. The graph acceptance suite separately proves bounded
  traversal and path behavior; no local NHI graph implementation exists.
- **Events:** EA-0033 registers four `aqelyn.ispm.*` events, EA-0025 five
  `aqelyn.inventory.*` events, and EA-0032 four `aqelyn.crypto.*` events. Their
  owner tests prove those registries; no `aqelyn.nhi.*` event is registered.
- **Structural boundary:** `src/aqelyn/machine_identity/`, `nhi_engine`, a
  second identity/lifecycle store, and a second posture score are absent. H1
  adds no `src/` package or runtime behavior.

Verification commands:

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src tests
pytest tests/ispm tests/iag tests/inventory tests/secrets tests/graph -q
pytest -q
```

Observed on live Postgres 16 + Redis 7: all five owner suites passed; the full
suite collected 1,244 tests and completed with **1,243 passed / 1 skipped**.
Ruff, format, and `mypy --strict src tests` were green across 477 files.

## The genuine remainder

### H2 - connect identity ownership to EA-0025

EA-0033's `IdentityDescriptor` has no typed owner claim, and
`ispm.normalize.inventory_report()` omits `owner` even though EA-0025 accepts
and reconciles it. Add a strict, evidence-backed ownership input to EA-0033 and
route it into the existing inventory row. Persist the inventory/evidence refs
used by the handoff so later posture and reporting can cite the exact owner
record instead of recomputing against current state (rule 17).

The proof is a real-owner round trip: conflicting owner claims enter through
EA-0033, EA-0025 resolves by EA-0006 reliability, equal reliability remains an
unresolved conflict, and `InventoryIntelligenceEngine.ownership(...)` returns
the selected value or explicit unknown. No NHI ownership store is permitted.

### H3 - bind identities to credentials and workloads through EA-0002

EA-0033 currently permits only the access-edge vocabulary needed by EA-0011,
while EA-0032 writes value-free `secret_asset`, `cryptographic_key`, and
`x509_certificate` objects. No shipped relation answers "which workload uses
this key?" Add a narrow, strict, value-free binding descriptor to EA-0033,
validate the target object and tenant, verify the cited EA-0004 record before
writing, derive confidence only from EA-0006, and persist the relation through
EA-0002 `ObjectStore.relate`. Traversal remains EA-0005's.

An integrity-checked record proves only that AQELYN's stored claim was not
altered. It does **not** prove that the workload authentically holds the
credential (ECR-0039). Any authenticity claim needs an owner-specific typed
verifier; C-031 does not synthesize one from `verify().ok`. Missing or tampered
evidence writes neither the edge nor a favourable posture result.

### H4 - map lifecycle ownership before adding history

The archive lists `requested`, `approved`, `provisioned`, `active`,
`credential_rotation`, `maintenance`, `suspended`, `revoked`, and `archived`.
EA-0033 currently collapses lifecycle into a control fact and EA-0025 owns the
asset lifecycle. C-031 first records and tests this ownership table:

| Archive state | Owner handling |
|---|---|
| requested / approved | identity-specific observation in EA-0033 only when explicitly reported |
| provisioned / active | EA-0025 `provisioned` / `active` |
| credential_rotation | EA-0032 crypto lifecycle, never an ISPM reimplementation |
| maintenance | EA-0025 `modified`; retain identity detail only if it cannot be reconstructed |
| suspended | identity-specific observation; asset remains inventoried |
| revoked | identity-specific observation; EA-0025 decommission only with positive evidence or an attributed gated decision |
| archived | EA-0025 `archived`, only from explicit evidence |
| source silence | EA-0025 `unreported`; never suspended, revoked, archived, deleted, or clean |

Only the identity-specific remainder may become a narrow append-only history in
EA-0033. It is not a second lifecycle engine. The decisive acceptance contrast
is explicit active evidence versus explicit revoked/suspended evidence versus
source silence; all three must remain distinguishable after persistence.

## Structural boundaries

- **No new runtime module.** All changes stay in existing owner packages and
  services. No second store, score, engine, or event namespace.
- **Handed-in records only.** No connector, provider credential, socket, poll,
  scheduler, or continuous-discovery loop is added.
- **No credential values.** Bindings carry typed ids, allowed fingerprints,
  provenance, and evidence only. EA-0032's recursive value-rejection boundary
  remains intact under normal Python and `python -O`.
- **No synthetic trust.** EA-0004 establishes integrity, not authenticity;
  confidence comes from EA-0006.
- **Absence is not revocation or safety.** Missing owner, lifecycle, or binding
  is unknown/flagged and cannot improve posture. Source silence is unreported.
- **No direct action.** Suspend, revoke, rotate, renew, or alter privileges only
  through the owning finding and EA-0008 proposal, with `source_finding` bound.
- **No silent denominator.** Inventory-backed proofs inherit unresolved
  ECR-0034 and may not present a capped first 10,000 rows as exhaustive.
- **Protocol-conforming doubles.** Any additive owner method or parameter is
  checked across implementations and test doubles with
  `mypy --strict src tests` (rule 18).

## Consequence of building IS-034 as written

A separate engine would create two identity repositories, two posture scores,
two ownership/lifecycle authorities, duplicated credential and certificate
governance, a second graph vocabulary, and renamed duplicate events. Consumers
could then receive contradictory answers for the same service account while
every individual package still appeared internally consistent.

**Deliverable:** this conformance proof, ECR-0053, and C-031 H1-H4. If the work
produces `src/aqelyn/machine_identity/`, an `nhi_engine`, an NHI store/score, or
an `aqelyn.nhi.*` event, the reconciliation has failed.
