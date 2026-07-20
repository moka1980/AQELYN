# EA-0031 - Data Security Posture Management (DSPM) - Implementation Specification

**Realizes:** EA-0031 / IS-031 (supersedes the archive placeholder for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (AQService), **EA-0019
(Classification taxonomy), EA-0025 (inventory), EA-0023 (known-surface
reachability and scoring), EA-0011 (identity/access context), EA-0010
(compliance), EA-0013 (risk through findings)**, EA-0009 (structured
conditions), EA-0006 (Trust), EA-0004 (evidence), EA-0008 (gated remediation)
**Consumed by:** EA-0023 (sensitivity-aware exposure), EA-0013 (findings),
the future DSPM UI
**Status:** Accepted
**Build milestone:** C-028 (see C-028_Task_Bundle.md)
**Change control:** ECR-0041 (connect DSPM to shipped owner contracts and make
unknown/minimal-retention guarantees structural)
**Definition of Ready:** see section 9

---

## 0. Scope reconciliation - the posture pattern, third instance

IS-031 uses the familiar Discovery / Classification / Access / Exposure /
Compliance / Risk posture skeleton. Data is a scope over five capabilities that
already have owners. The new capability is classifying sensitive data in stores
outside EA-0019's governed datasets, then combining that sensitivity with
EA-0023 reachability.

| IS-031 component | Realization |
|---|---|
| Data Discovery | **EA-0025**. DSPM normalizes a handed-in store descriptor to an EA-0002 object and routes an inventory report. |
| Sensitive Data Classification | **New at scope**, using EA-0019 Classification unchanged. |
| Data Access Intelligence | Handed-in, evidenced access claims are enriched by the shipped EA-0011 access_paths and analyze_risk APIs. DSPM does not infer entitlements. |
| Data Exposure | **New composition**: DSPM sensitivity context plus EA-0023 KnownSurfaceSource reachability and scoring. |
| Data Compliance | **EA-0010** assessment over data-store objects. |
| Data Risk | **EA-0013** through the existing evidence-backed findings path. No new SignalKind. |

The package is a classifier and router, not a second inventory, access,
compliance, exposure, or risk engine.

### 0.1 Hard collection boundary - descriptors, not data contents

DSPM accepts already-produced DataStoreDescriptor records. It opens no database,
bucket, file share, warehouse, or network connection and exposes no scan, sample,
read_content, or query_data method.

The descriptor shape contains field names/types, detector outcomes, counts,
existing classification tags, and evidence references. It has no raw value,
sample value, content, row, document, or blob field. Pydantic extra="forbid"
and store validation reject those fields. Detector evidence records describe
the result; they do not copy the matched sensitive value.

Live discovery or sampling is a future connector action represented by an
EA-0008 ActionSpec with capability data.scan. Its gated result may be handed to
ingest_store. DSPM never invokes the connector or reads a source directly.

### 0.2 One sensitivity vocabulary

DSPM imports EA-0019 Classification:

    Literal["public", "internal", "pii", "secret"]

It does not redefine those values. DSPM adds the assessment state unknown
outside that taxonomy. Unknown means classification was not completed; it is
never coerced to public.

### 0.3 Shipped exposure seam

EA-0023 does not define a SurfaceFacet or public_storage type. Its shipped intake
is:

    KnownSurfaceSource -> KnownSurfaceRecord -> ExposureRecord

DSPM therefore contributes a DataStoreKnownSurfaceSource that composes with the
existing source. It replaces the same-object inventory placeholder only when an
evidenced descriptor has more specific reachability; it never drops upstream
rows and fails rather than serving a partial source.

EA-0023 currently scores reachability but has no way to carry sensitivity.
ECR-0041 adds an optional, evidence-backed ExposureImpactContext to the owner
API. DSPM supplies the domain factor; EA-0023 remains the only exposure scorer
and includes the context in its replayable derivation. An unknown impact context
cannot be scored as zero: DSPM records a flagged classification gap instead.

## 1. Purpose

DSPM answers two evidence-backed questions without becoming a repository of the
data it protects:

1. Which known stores contain public, internal, PII, secret, or still-unknown
   fields?
2. Which PII/secret stores are externally or internally reachable, and how does
   sensitivity change the owner-computed exposure?

A public bucket of non-sensitive media and a public bucket of medical records
are not equivalent. A reachable store whose sensitivity is unknown is also not
safe: it is a visible posture gap.

## 2. Safety and honesty properties

- **S1 - Unknown is not public.** Unknown is a semantic state. Unknown and
  conflict classifications require flagged=True. A public classification
  requires an explicit, evidence-backed winning rule or source tag.
- **S2 - Minimal retention is structural.** Inputs and persisted models cannot
  carry raw sensitive values. Generic provider dictionaries are not accepted.
- **S3 - Exposure composes owners.** Reachability is EA-0023. Sensitivity is
  DSPM. Final exposure scoring is EA-0023 with Trust, Mission, Risk, and a
  replayable derivation. DSPM has no local exposure scorer.
- **S4 - Non-computation stays visible.** Unknown reachability yields pending,
  not not-exposed. Unknown sensitivity plus known reachability yields a flagged,
  unscored classification_gap.
- **S5 - Access claims are claims.** A descriptor may name evidenced identity
  refs. DSPM calls EA-0011 for their access paths and tenant risk context. No
  claim means pending, never nobody_has_access.
- **S6 - Detect and propose.** Findings are advisory. Locking, revoking, moving,
  or deleting data is only a proposed, gated EA-0008 run. No method executes it.
- **S7 - Bounded work is reported.** Cursor pagination follows EA-0002 D8.
  Assessment coverage is complete, truncated, or pending; truncated/pending
  output cannot carry a clean complete claim.

All operations are tenant-scoped, deterministic for the same pinned inputs, and
evidence-bound.

## 3. Design decisions

- **D1 - Normalize once.** DataStoreDescriptor becomes one EA-0002 object plus
  one EA-0025 inventory record; DataAsset stores both object_id and inventory_ref.
- **D2 - Metadata-only classification.** Rules are typed EA-0009 Conditions over
  descriptor metadata. No eval, free-form SQL, regex execution, or raw samples.
- **D3 - Trust-backed claims.** Every classification cites evidence and receives
  confidence from EA-0006 at descriptor.observed_at. Conflicts retain all
  candidates and source reliabilities.
- **D4 - Real known-surface adapter.** DataStoreKnownSurfaceSource implements
  EA-0023 KnownSurfaceSource and preserves upstream completeness.
- **D5 - Additive owner scoring.** ExposureImpactContext is optional; all
  existing EA-0023 callers preserve existing behavior.
- **D6 - Risk through findings.** Data exposure and classification gaps raise
  Findings. EA-0013 consumes those through its existing finding correlation
  path.
- **D7 - Append-only history.** Data assets, exposures, and assessments preserve
  history; updates do not erase prior classification claims.

## 4. Types

The following are normative shapes. All models use extra="forbid".

~~~
Classification = EA-0019 Literal["public", "internal", "pii", "secret"]
Sensitivity = Classification | Literal["unknown"]
ClassificationStatus = Literal["known", "unknown", "conflict"]
AssetClassificationStatus = Literal["complete", "partial", "unknown", "conflict"]
Reachability = EA-0023 Literal["external", "internal", "unknown"]
ExposureState = Literal["confirmed", "classification_gap", "reachability_pending"]
CoverageStatus = Literal["complete", "truncated", "pending"]

DSPMScope = {
  store_types: list[str],
  flagged: bool | None,
  limit: int,
  cursor: str | None
}

DataStoreLocation = {
  provider: str,
  account_ref: str | None,
  region: str | None,
  resource_ref: str
}
# No credential/token/secret field exists. resource_ref is an opaque provider
# identifier; embedded URL userinfo or credential-bearing query parameters fail.

ClassificationSignal = {
  id: str,
  kind: Literal["field_name", "existing_tag", "detector_match"],
  detector_ref: str,
  match_count: int,
  evidence_id: str
}
# No raw value/content/sample field exists.

DataFieldDescriptor = {
  name: str,
  data_type: EA-0019 SchemaType,
  signals: list[ClassificationSignal],
  existing_classification: Classification | None
}

DataAccessClaim = {
  identity_id: str,
  claim_kind: Literal["observed", "granted"],
  evidence_id: str
}

ReachabilityClaim = {
  reachability: Reachability,
  evidence_id: str,
  reason: str
}

DataStoreDescriptor = {
  store_id: str,
  tenant_id: str | None,
  store_type: Literal["bucket", "database", "fileshare", "warehouse", "other"],
  location: DataStoreLocation,
  fields: list[DataFieldDescriptor],
  access_claims: list[DataAccessClaim],
  reachability_claim: ReachabilityClaim | None,
  source_id: str,
  observed_at: datetime,
  evidence_id: str
}

ClassificationCandidate = {
  classification: Classification,
  source_ref: str,
  reliability: float,
  evidence_id: str
}

ClassificationConflict = {
  field: str,
  candidates: list[ClassificationCandidate],
  resolved_by: str | None,
  unresolved: bool
}

FieldClassification = {
  field: str,
  classification: Sensitivity,
  status: ClassificationStatus,
  flagged: bool,
  rule_refs: list[str],
  confidence: float,
  evidence_ids: list[str],
  reason: str
}
# known <=> classification is an EA-0019 value.
# unknown/conflict => classification == "unknown" and flagged is true.

DataAsset = {
  id: str,                            # dsa typed id
  object_id: str,
  inventory_ref: str,
  tenant_id: str | None,
  store_id: str,
  store_type: str,
  location: DataStoreLocation,
  field_classifications: list[FieldClassification],
  max_known_sensitivity: Classification | None,
  classification_status: AssetClassificationStatus,
  flagged: bool,
  conflicts: list[ClassificationConflict],
  access_claims: list[DataAccessClaim],
  reachability_claim: ReachabilityClaim | None,
  observed_at: datetime,
  evidence_id: str,
  version: int
}
# complete => all fields known and max_known_sensitivity is present.
# partial => known and unknown fields coexist; max_known_sensitivity is present.
# unknown => no known field and max_known_sensitivity is None.
# conflict => at least one unresolved conflict; flagged is true.

ExposureImpactContext = {
  kind: Literal["data_sensitivity"],
  status: Literal["known", "unknown"],
  factor: float | None,
  source_ref: str,
  evidence_id: str,
  reason: str
}
# known => factor in [0,1]; unknown => factor is None.

DataExposure = {
  id: str,                            # dxe typed id
  tenant_id: str | None,
  data_asset_id: str,
  object_id: str,
  exposure_ref: str,
  sensitivity: Sensitivity,
  reachability: Reachability,
  state: ExposureState,
  flagged: bool,
  score: float | None,
  derivation: EA-0020 Derivation | None,
  access_evidence_ids: list[str],
  reason: str,
  evidence_ids: list[str],
  detected_at: datetime
}
# confirmed => sensitivity in {pii, secret}, reachability != unknown,
#              score and derivation are present.
# classification_gap => sensitivity unknown, flagged, score/derivation absent.
# reachability_pending => reachability unknown, flagged, score/derivation absent.

DataAccessContext = {
  data_asset_id: str,
  status: Literal["known", "pending"],
  claims: list[DataAccessClaim],
  paths: list[EA-0011 AccessPath],
  risks: list[EA-0011 AccessRisk],
  truncated: bool,
  reason: str
}

DataPostureAssessment = {
  id: str,                            # dpa typed id
  tenant_id: str | None,
  run_at: datetime,
  scope: DSPMScope,
  coverage_status: CoverageStatus,
  coverage_reason: str | None,
  next_cursor: str | None,
  stores_evaluated: int,
  classified_fields: int,
  unknown_fields: int,
  exposure_ids: list[str],
  gap_ids: list[str],
  evidence_id: str | None
}
# pending => all counts/lists empty and evidence_id is None.
# truncated => next_cursor and coverage_reason are required.

ClassifierRule = {
  id: str,
  condition: EA-0009 Condition,
  classification: Classification,
  reason: str
}

DSPMConfig = {
  classifier_rules: list[ClassifierRule],
  sensitivity_factors: dict[Classification, float],
  batch_size: int,
  max_work: int,
  max_fields_per_store: int,
  max_signals_per_field: int
}
~~~

## 5. Interfaces (Python 3.12)

~~~python
class DSPMStore(Protocol):
    async def put_asset(self, asset: DataAsset) -> DataAsset: ...
    async def get_asset(
        self, asset_id: str, *, tenant_id: str | None
    ) -> DataAsset | None: ...
    async def get_asset_by_store_id(
        self, store_id: str, *, tenant_id: str | None
    ) -> DataAsset | None: ...
    async def put_exposure(self, exposure: DataExposure) -> DataExposure: ...
    async def put_assessment(
        self, assessment: DataPostureAssessment
    ) -> DataPostureAssessment: ...
    async def query_assets(
        self,
        *,
        tenant_id: str | None,
        classification: Classification | None = None,
        status: AssetClassificationStatus | None = None,
        flagged: bool | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[DataAsset], str | None]: ...

class DSPMEngine(Protocol):
    async def ingest_store(
        self,
        descriptors: Sequence[DataStoreDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[DataAsset]: ...
    async def classify(
        self, asset_id: str, *, tenant_id: str | None
    ) -> list[FieldClassification]: ...
    async def analyze_exposure(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope | None = None,
    ) -> list[DataExposure]: ...
    async def access_context(
        self, asset_id: str, *, tenant_id: str | None
    ) -> DataAccessContext: ...
    async def data_compliance(
        self, *, tenant_id: str | None, scope: ObjectQuery
    ) -> ComplianceSnapshot: ...
    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope | None = None,
    ) -> DataPostureAssessment: ...
    async def exposures_to_findings(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        propose_remediation: bool = True,
    ) -> list[str]: ...
    def explain(self, exposure: DataExposure) -> dict[str, object]: ...
~~~

DSPMService is an AQService named dspm_engine. Its health reports object,
inventory, exposure, IAG, governance, Trust, evidence, finding, Workflow, and
store availability plus config validity. Factory imports follow the established
TYPE_CHECKING plus local runtime-import pattern.

Deliberately absent: scan, sample, read_content, query_data, execute, move,
delete, a local risk scorer, and a local exposure scorer.

## 6. Computation

### 6.1 Ingest and classify

1. Validate descriptor.tenant_id against the explicit tenant scope and enforce
   max_fields_per_store/max_signals_per_field before owner calls.
2. Record or verify descriptor evidence. No raw data is copied into the DSPM
   store.
3. Upsert one EA-0002 object of type data_store and route one EA-0025 discovery
   report. Persist both returned ids.
4. Evaluate ClassifierRule.condition with EA-0009 condition_matches over a
   metadata-only payload.
5. Load the cited EvidenceRecords and call EA-0006 Trust at observed_at.
6. Reconcile conflicting candidates by source reliability. Preserve every
   candidate. Equal-reliability disagreement is unresolved.
7. No winning evidence-backed classification produces unknown + flagged. Public
   is never a default.

### 6.2 Known surface and exposure

DataStoreKnownSurfaceSource reads the DSPM store with cursor pagination,
starting from the composed upstream KnownSurfaceSource. For each evidenced
reachability claim it replaces only the same object_id row with a
KnownSurfaceRecord containing:

- AssetRef(kind="asset", ref_id=DataAsset.object_id),
- reachability from the claim,
- an evidence-backed inventory/access basis,
- observed_at from the descriptor.

Repeated cursors raise StoreUnavailable. Any page failure aborts the source; a
partial surface is never served.

For each DataAsset:

- EA-0023 analyze_exposure supplies reachability.
- Unknown reachability creates reachability_pending, flagged, unscored.
- Unknown sensitivity plus known reachability creates classification_gap,
  flagged, unscored.
- Known pii/secret max_known_sensitivity plus known reachability creates
  ExposureImpactContext(status="known") from DSPMConfig.sensitivity_factors and
  calls EA-0023 score_exposure. EA-0023 includes the impact claim/factor in its
  risk seed and replayable derivation.
- Partial/conflict/unknown classification plus known reachability also creates
  a separate classification_gap. A known sensitive exposure and an unknown-field
  gap may coexist for the same store; neither erases the other.
- Public/internal classifications do not become material DataExposure records;
  their classification records remain queryable.

The same asset/evidence with a higher known sensitivity factor cannot receive a
lower EA-0023 exposure score. Unknown is not assigned a factor.

### 6.3 Access, compliance, risk, and remediation

Access claims come from the descriptor and require evidence. For each identity
ref, DSPM calls the real EA-0011 access_paths method; it calls analyze_risk for
tenant context and cites only matching identity/account/entitlement records.
No access claims or an unavailable IAG provider yields DataAccessContext
status=pending, not an empty known context.

data_compliance delegates to EA-0010 assess over object_type=data_store. DSPM
does not evaluate controls locally.

Material exposures and classification gaps become evidence-backed Findings with
automation eligibility none and requires_approval true. EA-0013 consumes those
through its existing finding path. No new SignalKind is added.

If remediation is requested, DSPM calls Workflow.propose with an ActionSpec such
as data.restrict_access or data.review_classification. It never calls execute
and never invokes a connector handler.

### 6.4 Assessment coverage

Assessment pages under max_work and batch_size. A caller-supplied limit may
truncate and must preserve next_cursor plus coverage_reason="truncated".
Dependency failure before work yields pending with no clean counts. Complete is
set only when the cursor is exhausted.

## 7. Requirements

### Functional

- **FR-1** DSPM SHALL accept typed, size-bounded handed-in descriptors only and
  expose no collection/content-read method.
- **FR-2** Descriptor and persisted models, including assessment scope, SHALL
  reject raw values, samples, rows, documents, content, blobs, and undeclared
  extra fields.
- **FR-3** Data stores SHALL become EA-0002 objects and EA-0025 inventory
  records; DSPM SHALL NOT own a second inventory.
- **FR-4** Classification SHALL import EA-0019 Classification unchanged and use
  typed EA-0009 Conditions over metadata only.
- **FR-5** Every classification SHALL cite evidence and EA-0006 confidence.
  Unknown/conflict SHALL be flagged and SHALL NOT become public.
- **FR-6** Classification conflicts SHALL retain candidates and reliability;
  unresolved ties SHALL remain unknown.
- **FR-7** DSPMStore SHALL implement EA-0002 D8 pagination: filters before limit,
  exclusive cursor, and next_cursor exactly when another matching row exists.
- **FR-8** DSPM SHALL use EA-0023's real KnownSurfaceSource seam and preserve
  upstream completeness.
- **FR-9** Sensitivity weighting SHALL use ECR-0041 ExposureImpactContext and
  EA-0023 score_exposure; DSPM SHALL implement no exposure scorer.
- **FR-10** Unknown reachability SHALL be pending. Unknown sensitivity with known
  reachability SHALL be a flagged, unscored classification gap.
- **FR-11** Access context SHALL cite handed-in claims plus the real EA-0011
  access_paths/analyze_risk outputs; absent/unavailable context SHALL be pending.
- **FR-12** Compliance SHALL delegate to EA-0010. Risk SHALL flow through
  evidence-backed Findings into EA-0013.
- **FR-13** Remediation SHALL be proposed through EA-0008 only; DSPM SHALL never
  move/delete data, revoke access, execute a run, or call an action handler.
- **FR-14** Assessment coverage SHALL be complete/truncated/pending and SHALL
  never report a partial or failed assessment as complete.
- **FR-15** All reads/writes/delegations SHALL use explicit tenant scope.
- **FR-16** In-memory and Postgres DSPM stores SHALL pass one contract suite.
- **FR-17** DSPMService SHALL register as dspm_engine with dependency/config
  health and the standard circular-import-safe factory pattern.

### Non-functional

- **NFR-1 (unknown is not safe)** Unknown sensitivity/reachability is structural
  and behaviorally tested per ECR-0007.
- **NFR-2 (privacy)** Stored shapes contain metadata, classifications, and
  evidence refs only. No raw sensitive content is retained.
- **NFR-3 (one-capability-one-owner)** Inventory, access, compliance, exposure,
  risk, Trust, evidence, and action delegation use their shipped owners.
- **NFR-4 (bounded and honest)** Work budgets and cursor status are visible.
- **NFR-5 (portable and typed)** Python 3.12, mypy --strict, ruff, one store
  contract over both backends.

## 8. Acceptance criteria and tests

| # | Criterion | Pytest id |
|---|---|---|
| AC-1 | Handed-in only; no collection/content-read surface; network/read spy sees zero attempts | test_dspm_no_collection_or_bulk_read |
| AC-2 | Raw value/content/sample/credential/extra fields are unconstructible and never persisted | test_dspm_no_raw_sensitive_shape |
| AC-3 | Classification is imported from EA-0019 and no parallel known taxonomy exists | test_dspm_taxonomy_reused |
| AC-4 | No winning rule/evidence yields unknown+flagged, never public | test_dspm_unknown_not_public |
| AC-5 | Field classification carries evidence and Trust confidence pinned to observed_at | test_dspm_classification_evidence |
| AC-6 | Conflicts retain candidates; reliability winner and unresolved tie are deterministic | test_dspm_conflict_recorded |
| AC-7 | Real EA-0002 object and EA-0025 inventory records are created | test_dspm_store_to_inventory |
| AC-8 | DSPM store has D8 cursor semantics on in-memory and Postgres | test_dspm_store_contract[inmemory] / [postgres] |
| AC-9 | DataStoreKnownSurfaceSource composes upstream, replaces same-ref only, and fails on partial/repeated cursor | test_dspm_known_surface_contract |
| AC-10 | pii/secret plus known reachability produces DataExposure through real EA-0023 | test_dspm_exposure_intersection |
| AC-11 | Sensitivity reaches real EA-0023 scoring/derivation; higher known factor is monotonic | test_dspm_sensitivity_weights_exposure |
| AC-12 | Reachable plus incomplete classification is flagged/unscored; a known-sensitive exposure and its unknown-field gap coexist; unknown reachability is pending/unscored | test_dspm_unknown_exposure_states |
| AC-13 | Access claims call real EA-0011 APIs; absent/unavailable context is pending | test_dspm_iag_access_context |
| AC-14 | Compliance uses real EA-0010; risk consumes real findings path with no new SignalKind | test_dspm_compliance_and_risk_handoff |
| AC-15 | Remediation proposes a gated run; mutation/execute/handler spies remain empty | test_dspm_remediation_gated |
| AC-16 | Assessment reports complete/truncated/pending honestly under work bounds | test_dspm_assessment_coverage |
| AC-17 | Tenant isolation holds across models, stores, source adapter, and owner calls | test_dspm_tenant_isolation |
| AC-18 | Invalid rules/factors/limits/config are rejected | test_dspm_config_invalid |
| AC-19 | Three owned events only; owner events are not re-emitted | test_dspm_event_registration |
| AC-20 | Factory-built in-memory and Postgres services have honest lifecycle/health and clean imports | test_dspm_service_health[inmemory] / [postgres] |

## 9. Errors, events, dependencies

New errors: DSPMConfigInvalid, DataAssetNotFound, DataExposureNotFound,
ClassificationUnavailable. Reuses StoreUnavailable, TenantScopeRequired,
CrossTenantReference, and owner errors.

Owned events:

- aqelyn.data.store_classified
- aqelyn.data.exposure_detected
- aqelyn.data.classification_conflict

Inventory, access, compliance, exposure-score, risk, and workflow events remain
with their owners.

Definition of Ready:

1. This spec and C-028 are on main.
2. ECR-0041 is recorded, and EA-0023's additive owner contract is amended before
   P3 implementation.
3. C-027 is merged and green.
4. ECR-0034 remains independent; DSPM must treat degraded inventory as
   unavailable and must not weaken that pending fix.

## 10. Resolved and deferred decisions

- EA-0031 is genuine but thin: classification at wider scope plus
  sensitivity-aware exposure, routing everything else.
- SurfaceFacet/public_storage wording is rejected because those types do not
  exist. KnownSurfaceSource is the canonical seam.
- Unknown is a status, not a boolean and not a default public classification.
- Minimal retention is enforced by typed shapes, not a prose promise.
- ECR-0032 is revisited because DSPM is the third normalize/route posture module.
  The recommendation remains a behavior-preserving extraction only after C-028
  is green; no shared-base refactor belongs in C-028.
- Live scanning and sampling remain connector actions gated by EA-0008.
