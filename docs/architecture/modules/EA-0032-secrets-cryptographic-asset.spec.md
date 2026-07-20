# EA-0032 - Secrets Security & Cryptographic Asset Intelligence - Implementation Specification

**Realizes:** EA-0032 / IS-032 (supersedes the archive placeholder for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001, EA-0002, EA-0004, EA-0006, EA-0008, EA-0010, EA-0013, EA-0019, EA-0023, EA-0025
**Consumed by:** EA-0023, EA-0013, and a future secrets/crypto UI
**Status:** Accepted
**Build milestone:** C-029 (see `C-029_Task_Bundle.md`)
**Change control:** ECR-0043

---

## 0. Scope reconciliation

The ECR-0015 event/type check was run against shipped `src/`, not against the
archive's own novelty claim. No shipped module owns secrets, X.509 certificates,
cryptographic keys, their lifecycle, or their events. The `secret` matches that
do exist are unrelated classification and log-redaction concepts described in
section 0.2.

IS-032 is genuine new domain capability, but it is not seven new engines:

| IS-032 component | Realization |
|---|---|
| Secret Discovery | **New:** accept handed-in, value-free secret descriptors. No scanner or collector. |
| Cryptographic Asset Inventory | **EA-0025:** normalize crypto records into its inventory. No second inventory. |
| Certificate Lifecycle | **New:** expiry, chain, revocation, integrity, and authenticity state. |
| Key Management Intelligence | **New:** strength, rotation age, and usage assessment. |
| Secret/Crypto Exposure | **EA-0023:** `KnownSurfaceSource -> KnownSurfaceRecord` plus `ExposureImpactContext`. No `SurfaceFacet` exists. |
| Cryptographic Compliance | **EA-0010:** assess crypto objects through the existing compliance owner. |
| Cryptographic Risk | **EA-0013:** evidence-backed `Finding`s through the existing finding path. No new `SignalKind`. |

### 0.1 No collection and no secret-value retention

This engine opens no socket, connects to no vault/KMS/HSM/repository, holds no
credential, and scans no source. A future connector may perform a gated
`secret.scan` EA-0008 action and hand this engine descriptors. The descriptors
already contain one-way fingerprints and metadata; they never contain the
credential or private-key material.

The following is structural, not a logging convention:

> No accepted input model, persisted model, event, finding, explanation, or
> evidence record owned by this module can carry a secret value.

All models use `extra="forbid"`. `SecretLocation` and assessment scope are typed,
not free-form mappings. Fingerprints use a validated, upstream-generated
`hmac-sha256:<64 lowercase hex>` form so arbitrary credential text cannot be
relabelled as a fingerprint. Resource references reject URL userinfo and known
credential-bearing query keys. Raw mappings presenting `value`, `sample`,
`content`, `payload`, `blob`, `credential`, `token`, `password`, `private_key`,
or normalized variants are rejected with `SecretValueRejected` before model
construction, without logging the rejected value.

### 0.2 Two false friends

- `PREFIXES["cert"]` already means EA-0011 access certification, not X.509.
  EA-0032 owns new `sct`, `cky`, `x509`, and `cas` prefixes and registers them in
  `conventions/ids.py::PREFIXES` and CONVENTIONS section 1. It has no EA-0011
  certification dependency.
- EA-0019 `Classification = public|internal|pii|secret` describes data
  sensitivity, while `conventions/logging.py::_SECRET_KEYS` names log-redaction
  keys. A `SecretAsset` is a credential record. It reuses the EA-0019 `secret`
  classification literal without redefining either existing meaning.

### 0.3 Detect and propose

This engine assesses and proposes. Rotation, revocation, and re-issuance are
finding-driven EA-0008 Workflow proposals with `requires_approval=True` and the
actual `source_finding` bound. The module exposes no execute or handler path and
changes no live credential or certificate.

## 1. Load-bearing invariants

- **S1 - Unknown is not safe.** Expiry, strength, rotation, chain, revocation,
  integrity, and authenticity use `valid|invalid|unknown`; `unknown` is the
  default and never becomes the favourable value.
- **S2 - Integrity is not authenticity.** EA-0004 verifies AQELYN's evidence
  chain. A typed `CertificateAuthenticityVerifier` supplied by a trusted adapter
  separately validates certificate/chain authenticity. One result never implies
  the other (ECR-0039).
- **S3 - Exposure composes.** EA-0032 implements a `KnownSurfaceSource`, keys
  surface identity on the EA-0025 `ast_` id, carries the EA-0002 `obj_` scoring
  subject in `AssetRef.object_id`, and supplies an evidence-backed
  `ExposureImpactContext`. It performs no reachability traversal or scoring.
- **S4 - No value retention.** Section 0.1 applies recursively to every typed
  boundary and under `python -O`.
- **S5 - One owner per capability.** Inventory, exposure, compliance, risk,
  confidence, evidence, and action remain with EA-0025, EA-0023, EA-0010,
  EA-0013, EA-0006, EA-0004, and EA-0008 respectively.
- **S6 - Evidence failure cannot improve posture.** Missing evidence raises
  `EvidenceNotFound`; failed integrity raises `EvidenceTampered`; a retriable
  evidence outage yields an explicit unknown/pending result. No candidate is
  silently discarded.
- **S7 - Coverage is semantic.** `pending` means assessment did not run,
  `complete` means the bounded source was exhausted, and `truncated` means a
  work bound stopped partial work. A boolean cannot represent these states.

## 2. Purpose

AQELYN already knows how to inventory assets, assess compliance, model exposure,
and aggregate risk. EA-0032 adds the crypto-specific facts those owners need:
where a fingerprinted credential was reported, whether a certificate is near
expiry, whether a key is weak or stale, and what could not be established. It
answers those questions without creating a credential lake or claiming that a
missing lifecycle fact is good news.

## 3. Design decisions

- **D1:** Secret, key, and certificate records are typed EA-0002 objects and are
  registered with EA-0025. Domain records retain both `object_id` (`obj_`) and
  `inventory_ref` (`ast_`); the identities are never conflated.
- **D2:** Handed-in descriptors are typed and value-free. Fingerprinting happens
  upstream; this engine never receives the underlying value.
- **D3:** Lifecycle state is a validated value object. `valid`/`invalid` require
  evidence; `unknown` requires a reason and may cite evidence for an unreadable
  or incomplete observation.
- **D4:** Certificate verification is two-stage: EA-0004 evidence integrity,
  then a typed kind-specific authenticity verifier. The verifier returns a
  claim; EA-0004 records the result.
- **D5:** Exposure uses the shipped EA-0023 source/context seam; compliance uses
  EA-0010 `assess`; risk uses evidence-backed findings only.
- **D6:** Persistence adopts EA-0002 D8 semantics in its first ticket: stable id
  order, exclusive cursor, filters before limit, and `next_cursor` only when
  another matching row exists. Engine scans additionally enforce `max_work` and
  surface truncation.
- **D7:** The service is `SecretsIntelligenceService`, named `secrets_engine`,
  with mode-aware tenant-scoped health probes.

## 4. Type model

All models are strict (`extra="forbid"`) and tenant-scoped.

```text
LifecycleStatus = "valid" | "invalid" | "unknown"
AssessmentStatus = "pending" | "complete" | "truncated"

Lifecycle = {
  status: LifecycleStatus = "unknown",
  source_ref: str | null,
  evidence_id: evd_ | null,
  reason: str
}
# valid/invalid require source_ref + evidence_id; unknown requires a reason.

SecretKind = "api_key" | "token" | "private_key" | "password" |
             "connection_string" | "ssh_key" | "other"
SecretLocation = {
  kind: "repository" | "configuration" | "vault_reference" |
        "runtime_reference" | "other",
  resource_ref: str,
  path_hint: str | null,
  line: int | null
}
SecretScanDescriptor = {
  tenant_id, kind: SecretKind,
  fingerprint: "hmac-sha256:<64 lowercase hex>",
  location: SecretLocation,
  source_id: src_, observed_at: datetime, evidence_id: evd_
}

KeyUsage = "signing" | "encryption" | "authentication" | "key_agreement" | "other"
CryptographicKeyDescriptor = {
  tenant_id, external_key_ref: str,
  fingerprint: "hmac-sha256:<64 lowercase hex>",
  algorithm: str | null, key_size: int | null,
  usages: list[KeyUsage], last_rotated_at: datetime | null,
  source_id: src_, observed_at: datetime, evidence_id: evd_
}
CertificateDescriptor = {
  tenant_id, fingerprint: "hmac-sha256:<64 lowercase hex>",
  serial: str, subject: str, issuer: str, not_after: datetime | null,
  source_id: src_, observed_at: datetime, evidence_id: evd_
}
AuthenticityCheck = {
  status: LifecycleStatus,
  reason: str
}

SecretAsset = {
  id: sct_, tenant_id, object_id: obj_, inventory_ref: ast_,
  kind, fingerprint, location, classification: EA-0019 "secret",
  rotation: Lifecycle, claim_confidence: float,
  source_id: src_, detected_at: datetime, evidence_id: evd_
}
CryptographicKey = {
  id: cky_, tenant_id, object_id: obj_, inventory_ref: ast_,
  external_key_ref, fingerprint, algorithm, key_size, usages,
  strength: Lifecycle, rotation: Lifecycle, claim_confidence: float,
  source_id: src_, evidence_id: evd_
}
CertificateAsset = {
  id: x509_, tenant_id, object_id: obj_, inventory_ref: ast_,
  fingerprint, serial, subject, issuer, not_after,
  expiry: Lifecycle, chain: Lifecycle, revocation: Lifecycle,
  integrity: Lifecycle, authenticity: Lifecycle,
  claim_confidence: float, source_id: src_, evidence_id: evd_
}

CryptoAsset = SecretAsset | CryptographicKey | CertificateAsset
CryptoScope = { kinds: list["secret"|"key"|"certificate"], asset_ids: list[str] }
CryptoQuery = { tenant_id, kind, cursor: str|null, limit: int }

CryptographicExposure = {
  id, tenant_id, asset_id, surface_ref: ast_, object_id: obj_,
  exposure_record_id: exp_ | null,
  status: "confirmed" | "reachability_pending",
  impact_context: ExposureImpactContext,
  reason, evidence_id: evd_
}
CryptoAssessment = {
  id: cas_, tenant_id, run_at, scope: CryptoScope,
  status: AssessmentStatus = "pending",
  assets_evaluated, secrets, keys, certificates,
  expiring_soon, unknown_lifecycle,
  exposure_ids: list[str], incomplete_reason: str | null,
  evidence_id: evd_ | null
}
# pending requires all counts/lists zero and no evidence result;
# complete forbids incomplete_reason; truncated requires it.

CryptoConfig = {
  expiry_warning_days: int > 0,
  weak_algorithms: list[str], min_key_sizes: map[str, int],
  max_key_age_days: int > 0,
  batch_size: 1..1000, max_work: 1..100000
}
```

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class CryptoStore(Protocol):
    async def put_asset(self, asset: CryptoAsset) -> CryptoAsset: ...
    async def get_asset(self, asset_id: str, *, tenant_id: str | None) -> CryptoAsset | None: ...
    async def query_assets(self, query: CryptoQuery) -> tuple[list[CryptoAsset], str | None]: ...
    async def put_assessment(self, assessment: CryptoAssessment) -> CryptoAssessment: ...
    async def get_assessment(self, assessment_id: str, *, tenant_id: str | None) -> CryptoAssessment | None: ...

class CertificateAuthenticityVerifier(Protocol):
    async def verify(self, certificate: CertificateDescriptor) -> AuthenticityCheck: ...

class SecretsIntelligenceEngine(Protocol):
    async def ingest_secrets(self, descriptors: Sequence[SecretScanDescriptor], *, tenant_id: str | None) -> list[SecretAsset]: ...
    async def ingest_crypto_assets(self, keys: Sequence[CryptographicKeyDescriptor], certificates: Sequence[CertificateDescriptor], *, tenant_id: str | None) -> list[CryptoAsset]: ...
    async def assess_certificate(self, certificate_id: str, *, tenant_id: str | None) -> CertificateAsset: ...
    async def assess_key(self, key_id: str, *, tenant_id: str | None) -> CryptographicKey: ...
    async def analyze_exposure(self, *, tenant_id: str | None, scope: CryptoScope | None = None) -> list[CryptographicExposure]: ...
    async def crypto_compliance(self, *, tenant_id: str | None, scope: ObjectQuery) -> ComplianceSnapshot: ...
    async def assess(self, *, tenant_id: str | None, scope: CryptoScope | None = None) -> CryptoAssessment: ...
    async def propose_rotation(self, finding_id: str, *, tenant_id: str | None, by: ActorRef, reason: str) -> Run: ...
    def explain(self, asset: CryptoAsset) -> dict[str, object]: ...
```

`SecretsIntelligenceService` wraps the engine/store as an `AQService` named
`secrets_engine`. Deliberately absent: a scan/read/collect/connect method, a raw
value/content/blob parameter, an action handler, and a second inventory,
exposure, compliance, or risk engine.

## 6. Reference computation

1. **Ingest:** validate the descriptor and its evidence before any owner write.
   Missing or tampered evidence refuses the descriptor. Reconcile source claims
   through EA-0006; do not use last-writer-wins. Create the EA-0002 object,
   register it through EA-0025 `ingest(reports=, source=DiscoverySource,
   tenant_id=)`, and persist both resulting ids.
2. **Certificate lifecycle:** determine expiry from `not_after`; missing/unusable
   data is `unknown`. Verify evidence integrity first. Invoke the typed
   authenticity verifier only after integrity succeeds. Record the verifier
   result as EA-0004 evidence. Chain, revocation, integrity, and authenticity
   remain independent fields.
3. **Key lifecycle:** known weak algorithms or policy-inadequate sizes are
   invalid; recognized adequate facts are valid; unrecognized/missing facts are
   unknown. Missing rotation history is unknown, never recent.
4. **Exposure:** produce evidence-backed `KnownSurfaceRecord`s keyed by
   `inventory_ref`, carrying `object_id`; EA-0023 derives and scores the exposure.
   Credential sensitivity is an `ExposureImpactContext`. Unknown reachability
   remains `reachability_pending`, with no favourable numeric substitute.
5. **Compliance/risk/action:** compliance delegates to EA-0010. Material domain
   results raise evidence-backed, non-automatic findings for EA-0013. Rotation
   proposes EA-0008 Workflow with that exact finding bound and never executes.
6. **Assessment:** page the crypto store under `max_work`. Cursor exhaustion is
   complete; budget exhaustion is truncated; an unstarted/refused run remains
   pending. Persist counts and evidence only in a state-consistent record.

## 7. Functional requirements

- **FR-1:** Accepted and persisted models contain no secret/private-key value;
  forbidden raw keys are rejected as `SecretValueRejected` before construction.
- **FR-2:** Discovery is handed-in only. No scan, network, credential, bulk read,
  or collector surface exists.
- **FR-3:** Every lifecycle attribute is tri-state, defaults unknown, and known
  state requires evidence. Unknown requires an explicit reason.
- **FR-4:** No expiry, unknown algorithm, missing rotation, unverifiable chain,
  and unavailable revocation each remain unknown, never valid.
- **FR-5:** Evidence integrity and certificate authenticity are independent;
  authenticity uses a typed verifier, never `EvidenceStore.verify().ok` alone.
- **FR-6:** Missing/tampered evidence refuses; retriable unavailability is
  explicitly pending/unknown and cannot improve posture.
- **FR-7:** Assets route to EA-0025 and retain distinct `obj_` and `ast_` ids.
- **FR-8:** Exposure delegates through EA-0023's real source/context seam; the
  module performs no reachability or exposure scoring.
- **FR-9:** Compliance delegates to EA-0010; risk uses evidence-backed findings
  through EA-0013; no new `SignalKind` exists.
- **FR-10:** Rotation/revocation only proposes a `requires_approval=True` EA-0008
  run with `source_finding` bound. No effect executes in this module.
- **FR-11:** Assessments use semantic pending/complete/truncated coverage and
  surface `unknown_lifecycle`.
- **FR-12:** EA-0019's `secret` classification is reused; EA-0011 access
  certification and the `cert` prefix are not.
- **FR-13:** All reads/writes are tenant-scoped; health probes use a mode-aware
  tenant and are tested in both tenant modes on both backends.
- **FR-14:** In-memory and Postgres stores share one D8 pagination/tenant/
  immutability contract suite.
- **FR-15:** Work is bounded by `max_work`; partial results are marked truncated.
- **FR-16:** `SecretsIntelligenceService` registers as `secrets_engine` and its
  health reflects config and required owner-read availability.

## 8. Acceptance criteria

| # | Criterion | Test id |
|---|---|---|
| AC-1 | Nested/raw attempts to carry value/sample/content/blob/credential material are refused under normal Python and `-O` | `test_crypto_no_secret_values` |
| AC-2 | No scan/network/bulk-read surface; socket spy records zero attempts | `test_crypto_handed_in_only` |
| AC-3 | Lifecycle defaults unknown; known-without-evidence and pending-with-counts are unconstructible | `test_crypto_state_invariants` |
| AC-4 | Missing expiry/algorithm/rotation/chain/revocation never becomes valid | `test_crypto_unknown_not_safe` |
| AC-5 | EA-0004 integrity cannot establish authenticity; typed verifier outcome is separately evidenced | `test_crypto_integrity_not_authenticity` |
| AC-6 | Missing vs tampered vs retriable evidence remain distinct and never improve posture | `test_crypto_evidence_failure_not_safe` |
| AC-7 | Real EA-0025 receives crypto assets with distinct `obj_`/`ast_` identities | `test_crypto_assets_to_inventory` |
| AC-8 | Real composed EA-0023 source yields one row per asset and preserves unknown reachability | `test_crypto_exposure_owner_connectivity` |
| AC-9 | Exposure impact context is evidence-bound and cannot lower impact when absent/unknown | `test_crypto_exposure_context` |
| AC-10 | Compliance and finding/risk handoffs use their shipped owners | `test_crypto_owner_delegations` |
| AC-11 | Real Workflow refuses execution of the finding-bound eligibility-none rotation run after approval | `test_crypto_rotation_gated` |
| AC-12 | Assessment coverage is pending/complete/truncated and unknown lifecycle is counted | `test_crypto_assessment_coverage` |
| AC-13 | D8 cursor semantics hold adversarially on memory/Postgres; filters precede limit | `test_crypto_store_contract[inmemory]` / `[postgres]` |
| AC-14 | Work budget stops scans and sets truncated without losing accumulated results | `test_crypto_work_budget` |
| AC-15 | Prefix/error registries are complete; `cert` ownership is unchanged | `test_crypto_taxonomy_and_false_friends` |
| AC-16 | Invalid config and cross-tenant references are refused | `test_crypto_config_and_tenant_scope` |
| AC-17 | Exactly four owned events carry fingerprints/references only | `test_crypto_events_value_free` |
| AC-18 | Both factory runtimes exercise local and enterprise health; import isolation holds | `test_crypto_service_health` |

## 9. Error taxonomy and ids

New errors, registered in `errors.py` and CONVENTIONS section 9:
`CryptoConfigInvalid`, `SecretValueRejected`, `CryptoAssetNotFound`, and
`CertificateNotFound`. Reuse `EvidenceNotFound`, `EvidenceTampered`,
`StoreUnavailable`, `TenantScopeRequired`, and `CrossTenantReference`.

New prefixes, registered in `ids.py::PREFIXES` and CONVENTIONS section 1:
`sct` (secret asset), `cky` (cryptographic key), `x509` (X.509 certificate), and
`cas` (crypto assessment). `cert` remains `iag_certification`.

## 10. Events

EA-0032 owns exactly:

- `aqelyn.crypto.secret_detected`
- `aqelyn.crypto.certificate_expiring`
- `aqelyn.crypto.weak_key_detected`
- `aqelyn.crypto.lifecycle_unknown`

Events contain ids, fingerprints, locations, lifecycle state, and evidence refs
only. They never contain credential/private-key values. Compliance, risk,
exposure, and remediation events remain with their existing owners.

## 11. Failure handling

- Invalid config/value-bearing input/cross-tenant reference: refuse before write.
- Missing or tampered evidence: refuse; do not route to owners.
- Retriable owner outage: store valid domain records, mark dependent assessment
  pending/unknown with reason, and do not fabricate a favourable owner result.
- Authenticity verifier absent/unavailable: authenticity unknown and flagged;
  evidence integrity may still be reported separately.
- Rotation proposal failure: finding remains, no action occurs.
- Repeated store cursor: raise `StoreUnavailable`, never loop.

## 12. Inherited constraint: ECR-0034

ECR-0034 remains **Proposed and unimplemented**. EA-0025 `inventory()` currently
reads 10,000 rows and reports `degraded=False`, so its downstream global
denominator can silently truncate. EA-0032 adds assets to that same inventory.

EA-0032 does not claim EA-0025's capped report is exhaustive. Its own assessments
page `CryptoStore` under an explicit work budget and report semantic coverage.
Any operation that consumes EA-0025 `inventory()` must treat it as incomplete
until ECR-0034 is implemented. C-029 neither fixes nor deepens ECR-0034.

## 13. Resolved and deferred decisions

- ECR-0043 records the archive reconciliation: metadata-only handed-in
  discovery, owner delegation, tri-state lifecycle, separate authenticity, and
  proposal-only remediation.
- Live Vault/KMS/HSM/repository collection is deferred to gated connectors.
- PKI issuance, CA operation, and key custody remain out of scope.
- UI is deferred; a future surface must be WCAG 2.2 AA and must never reveal a
  secret value.
- The ECR-0032 shared posture-normalization proposal does not apply: this module
  owns lifecycle/value-safety domain logic rather than another normalization
  layer.
