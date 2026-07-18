# EA-0028 — Cloud Security Posture Management (CSPM) — Implementation Specification

**Realizes:** EA-0028 / IS-028 (supersedes the placeholder `archive/EA-0028/EA-0028_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0002 (cloud resources are objects)**, **EA-0025 (inventory), EA-0012 (config/baseline), EA-0010 (compliance), EA-0023 (exposure), EA-0011 (cloud identity), EA-0013 (risk)** — the owners it feeds; EA-0006 (source reliability), EA-0004 (evidence)
**Consumed by:** the six owner engines above (as normalized cloud objects/signals); the cloud posture UI (a WCAG 2.2 AA surface)
**Status:** Accepted
**Change control:** ECR-0020, ECR-0021
**Build milestone:** C-025 (see `C-025_Task_Bundle.md`)
**Definition of Ready:** see §8

---

## 0. Scope reconciliation — "cloud" is a scope + a normalizer, not six new engines

The ECR-0015 discipline (grep declared events/types before specifying) shows
IS-028 is **not** a wholesale restatement — its event `cloud.misconfiguration.
detected` is net-new. But its six components are each **"Cloud <capability that
already exists for every asset type>"**. The platform's rule is *one capability,
one owner* — and "runs in AWS" is a **property of an asset**, not a new
capability. So:

| IS-028 component | Owned by | This engine's part |
|---|---|---|
| 12.1 Cloud Inventory | **EA-0025** (a cloud resource is an asset) | **Normalize** provider resources → asset records; EA-0025 reconciles. |
| 12.2 Cloud Config Assessment | **EA-0012** (baseline + drift) | Supply cloud **baselines** (CIS-AWS/Azure/GCP as `Baseline` data); EA-0012 assesses. |
| 12.3 Cloud Compliance | **EA-0010** (frameworks) | CIS-Benchmark is a framework like any other; EA-0010 scores it. |
| 12.4 Cloud Identity Analysis | **EA-0011** (identity/entitlement) | Normalize IAM roles/policies → identities/entitlements; EA-0011 governs. |
| 12.5 Cloud Exposure | **EA-0023** (reachability/facets) | A public bucket / open SG is a `SurfaceFacet`; EA-0023 scores exposure. |
| 12.6 Cloud Risk | **EA-0013** (aggregation) | Cloud findings flow in as signals; EA-0013 scores risk. |

**What is genuinely new and unowned** (the archive's own **Decision 2 —
"Multi-Cloud Normalization Is Required"**):

- **Provider normalization** — turning an AWS/Azure/GCP resource description into
  AQELYN's object vocabulary, with provider/account/region provenance, so every
  downstream engine sees one consistent shape regardless of cloud.
- **Cloud-native facts** the generic model doesn't capture — a resource's
  provider, account/subscription, region, and the cloud-specific attributes
  (bucket ACL, security-group rule, IAM policy document) that the owners then
  interpret.

**This engine is therefore a normalization + routing layer**, deliberately thin:
it makes cloud resources *legible* to the platform and hands them to their owners.
It builds no second inventory, baseline, compliance, exposure, identity, or risk
engine.

### 0.1 Boundary (established precedent)

Cloud resource data is **handed in** (a `CloudResourceDescriptor` posted to the
platform). This engine makes **no cloud API calls**, holds no cloud credentials,
and enumerates no account — **live cloud collection is a connector concern**,
delivered as an EA-0008-gated `ActionHandler` (`capability "cloud.enumerate"`).
The archive's "Cloud Inventory API" (§20.1) is a **receiving** API, consistent
with EA-0025 §0.1.

The archive event `cloud.resource.deleted` is also a **handed-in provider
observation**, not authority to retire an asset. It maps to EA-0025
`mark_unreported` and the owned `aqelyn.inventory.asset_unreported` event. It
MUST NOT decommission an asset: decommissioning still requires positive evidence
or an attributed, EA-0008-gated decision (EA-0025 S3 / ECR-0014).

This layer carries **observations, never verdicts**. A normalized cloud object
cannot contain a severity, score, compliance status, finding, or action field;
those outputs remain structurally owned by the downstream engines (§0 / ECR-0020).

## 1. Purpose

Cloud is where misconfiguration is the breach: a public S3 bucket, an over-broad
IAM policy, an open security group. AQELYN can already detect drift, score
exposure, govern identity, and check compliance — **it just needs to see cloud
resources in its own terms.** This engine is the translator: it normalizes
multi-cloud resources into AQELYN objects with full provenance, attaches the
cloud-native facts the owners need, and routes each to the engine that already
knows what to do with it — so "cloud posture" is the existing platform, correctly
fed, not a bolted-on silo.

## 2. Design decisions

- **D1 — `CloudResourceDescriptor` in, `AQObject` out.** Normalize handed-in
  provider descriptions to `object_type` in a normalized set (`cloud_compute`,
  `cloud_storage`, `cloud_network`, `cloud_iam`, `cloud_database`, …), preserving
  `provider/account/region` + the raw provider block as evidence.
- **D2 — Routing, not re-implementation.** After normalization, hand off:
  resources → EA-0025; IAM → EA-0011; misconfig baselines → EA-0012; frameworks →
  EA-0010; facets → EA-0023; signals → EA-0013. This engine owns **normalization
  correctness**, not the analyses. Routing records one explicit outcome per owner
  and an overall `complete` / `partial` / `failed` status; five successful routes
  never conceal the sixth failure.
- **D3 — Provenance is mandatory** (multi-source, like EA-0025): every normalized
  field cites the provider field it came from; conflicts across provider snapshots
  resolve by EA-0006 reliability + recency, recorded not smoothed.
- **D4 — Cloud baselines are `Baseline` data** (EA-0012 model) shipped as
  configuration — CIS-AWS/Azure/GCP as declarative checks; **no cloud-specific
  drift engine**.
- **D5 — Observations, not verdicts.** `NormalizedCloudObject` uses
  `extra="forbid"` and has no severity/score/compliance-status/finding/action
  field; reserved verdict keys are also rejected recursively from nested
  normalized state. Those concepts are unrepresentable in this package
  (ECR-0020).
- **D6 — No collection** (§0.1); no second analysis engine (§0).
- **D7 — Registered as an `AQService`;** store in-memory + Postgres.

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Cloud resource descriptor** | A handed-in provider description of one resource (§0.1). |
| **Normalized cloud object** | The `AQObject` this engine emits, with provider/account/region provenance. |
| **Cloud-native facts** | Provider-specific attributes (ACL, SG rule, IAM policy) the owners interpret. |
| **Cloud baseline** | A CIS-style `Baseline` (EA-0012 model) for a provider/service. |
| **Routing** | Handing a normalized object/signal to its owning engine. |

## 4. Types

```
Provider = "aws" | "azure" | "gcp" | "oci" | "other"

CloudResourceDescriptor = { provider: Provider, account: str, region: str | null,
                            resource_type: str, resource_id: str,
                            raw: dict, observed_at: datetime,
                            source_id: str, evidence_id: str | null,
                            change_kind: "observed" | "reported_deleted" = "observed" }
                                                                    # handed in (§0.1)

NormalizedCloudObject = { object_id: str, object_type: str,             # EA-0002 object emitted
                          provider: Provider, account: str, region: str | null,
                          native_facts: dict,                           # observational only; verdict keys rejected
                          field_provenance: dict,                       # normalized field -> raw path (D3)
                          conflicts: list[dict],                        # EA-0006-resolved, recorded (D3)
                          evidence_id: str,
                          flagged: bool }                               # no verdict fields (D5)

OwnerRouteOutcome = { owner: "inventory" | "assetconfig" | "compliance" |
                             "exposure" | "iag" | "risk",
                      status: "accepted" | "failed",
                      refs: list[str], detail: str | null }

CloudRoutingResult = { object_id: str,
                       status: "complete" | "partial" | "failed",
                       outcomes: list[OwnerRouteOutcome] }              # one per owner (D2)

CloudNormalizationConfig = { type_map: dict,                            # provider resource_type -> object_type
                             baseline_ids: list[str],                   # EA-0012 cloud baselines to apply
                             batch_size: int }
```

Reuses EA-0002 objects, EA-0006 reliability, EA-0012 `Baseline`, EA-0004 evidence.
All EA-0028 models use Pydantic `extra="forbid"`. In particular,
`NormalizedCloudObject` rejects `severity`, `score`, `risk_score`,
`compliance_status`, `finding`, and `action` as extra fields **and as reserved
keys at any depth in `native_facts`, `field_provenance`, or `conflicts`**.
Provider verdicts may remain in the raw evidence block but are never normalized
into CSPM-owned state (D5).

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class CloudNormalizationStore(Protocol):
    async def put(self, obj: NormalizedCloudObject) -> NormalizedCloudObject: ...
    async def get(self, object_id: str) -> NormalizedCloudObject | None: ...
    async def query(self, *, tenant_id: str | None, provider: str | None = None,
                    limit: int = 1000) -> list[NormalizedCloudObject]: ...

class CloudPostureEngine(Protocol):
    async def normalize(self, descriptors: Sequence[CloudResourceDescriptor], *,
                        tenant_id: str | None) -> list[NormalizedCloudObject]: ...   # D1/D3
    async def route(self, object_ids: Sequence[str], *,
                    tenant_id: str | None) -> list[CloudRoutingResult]: ...          # D2
    async def apply_cloud_baselines(self, *, tenant_id: str | None,
                                    scope: dict | None = None) -> str: ...           # -> EA-0012 assess (D4)
    def explain(self, obj: NormalizedCloudObject) -> dict: ...                       # provenance (D3)
```

`CloudPostureService` wraps engine + store as an `AQService`
(name `"cspm_engine"`, depends on object/inventory/assetconfig/compliance/
exposure/iag/risk/trust/evidence; health reflects availability + config
validity).

**Deliberately absent:** any `enumerate()`/`scan()`/cloud-API method (§0.1); any
second drift/compliance/exposure/risk analysis (§0).

## 6. Computation (the reference model)

**Normalize.** For each handed-in `CloudResourceDescriptor`: map
`(provider, resource_type)` → normalized `object_type` via `type_map`; extract
`native_facts`; record `field_provenance` (normalized field → raw path); resolve
cross-snapshot conflicts by **EA-0006** reliability + recency, **recording** them
(D3); write the `NormalizedCloudObject` + an `EvidenceRecord` carrying the raw
block. An unmapped `resource_type` → `object_type "cloud_unknown"`, **flagged**
(never dropped — an unclassified cloud resource is an exposure risk, not noise).

**Route.** Hand each normalized object to its owners (D2): to **EA-0025** as an
asset (which reconciles it into the denominator); IAM objects to **EA-0011**;
facets (public storage, open network) to **EA-0023**; and register it for
**EA-0012** cloud-baseline assessment. Cloud findings raised by those owners flow
to **EA-0013** as usual. Every configured owner is attempted independently and
produces one `OwnerRouteOutcome`; `CloudRoutingResult.status` is `partial` when
accepted and failed outcomes coexist, so a five-of-six handoff is visible rather
than reported as success.

For a handed-in descriptor with `change_kind="reported_deleted"`, route the
existing asset to **EA-0025 `mark_unreported`**. Do not delete or decommission it,
and do not emit a CSPM-owned deletion assertion. EA-0025 emits
`aqelyn.inventory.asset_unreported`; only positive evidence or an attributed,
EA-0008-gated decision may decommission the asset (ECR-0014/ECR-0020).

**Baselines.** `apply_cloud_baselines` triggers **EA-0012 `assess`** with the
cloud `Baseline`s over cloud-scoped assets — no drift logic here (D4).

## 7. Requirements

### Functional (testable)

- **FR-1** `normalize` SHALL accept handed-in descriptors only; the module SHALL make no cloud API call, hold no cloud credential, and expose no enumerate/scan method (§0.1).
- **FR-2** Each descriptor SHALL be normalized to an `AQObject` with `provider`/`account`/`region` and `native_facts`; the raw block SHALL be preserved as evidence (D1).
- **FR-3** Every normalized field SHALL carry `field_provenance` back to the raw provider field (D3). `set(native_facts)` SHALL equal `set(field_provenance)`, enforced at construction: a key with no declared raw source is unconstructable (**ECR-0021**).
- **FR-4** Cross-snapshot field conflicts SHALL resolve by EA-0006 reliability then recency and SHALL be **recorded**, not smoothed (D3).
- **FR-5** An unmapped `resource_type` SHALL become `cloud_unknown`, flagged; it SHALL NOT be dropped (§6).
- **FR-6** `route` SHALL attempt every configured owner independently and record one `OwnerRouteOutcome` per owner plus an overall `complete` / `partial` / `failed` status; accepted and failed owners SHALL both remain visible. It SHALL NOT itself assess, score, or detect (D2/§0).
- **FR-7** Cloud config assessment SHALL be performed by **EA-0012** using cloud `Baseline`s; the module SHALL NOT implement drift detection (D4).
- **FR-8** Cloud compliance SHALL be **EA-0010**, cloud exposure **EA-0023**, cloud identity **EA-0011**, cloud risk **EA-0013**; the module SHALL implement none of them (§0).
- **FR-9** The module SHALL raise no findings directly and execute nothing; findings arise from the owners it routes to.
- **FR-10** All operations SHALL be tenant-scoped and bounded; invalid config (unknown `type_map` target, unknown `baseline_id`, `batch_size ≤ 0`) SHALL raise `CloudConfigInvalid`.
- **FR-11** `CloudNormalizationStore` in-memory and Postgres implementations SHALL pass one contract suite.
- **FR-12** `CloudPostureService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).
- **FR-13** `NormalizedCloudObject` SHALL use `extra="forbid"` and SHALL define no severity, score, risk score, compliance status, finding, or action field. Its constructor SHALL recursively reject those reserved verdict keys, **case-insensitively**, anywhere in normalized state, including `native_facts`, `field_provenance`, and `conflicts`; such provider material may exist only in raw EA-0004 evidence (D5/ECR-0020). This name check is a **backstop**: the primary guarantee is FR-3's provenance binding, under which an invented verdict key has no raw source and cannot be constructed (**ECR-0021**).
- **FR-14** A handed-in `reported_deleted` descriptor SHALL route to EA-0025 `mark_unreported` / `aqelyn.inventory.asset_unreported`; it SHALL NOT delete or decommission an asset without positive evidence or an attributed EA-0008-gated decision (EA-0025 S3/ECR-0014/ECR-0020).

### Non-functional

- **NFR-1 (normalizer, not silo — structural)** the module exposes normalization + routing only; no assessment/scoring/detection method or verdict field exists. `extra="forbid"` plus FR-3's provenance binding makes verdict-bearing normalized objects unconstructable, and delegation spies prove EA-0025/0012/0010/0023/0011/0013 do the analyses, per **ECR-0007**.
- **NFR-2 (no collection)** no cloud API/socket; socket spy proves zero outbound.
- **NFR-3 (provenance)** every normalized field traces to a raw provider field; conflicts recorded.
- **NFR-4 (bounded & typed)** batched; store passes one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Handed-in only; no cloud API/enumerate | `test_cspm_no_collection` |
| AC-2 | Descriptor → AQObject w/ provider/account/region + raw evidence | `test_cspm_normalize_object` |
| AC-3 | Field provenance recorded | `test_cspm_field_provenance` |
| AC-4 | Conflicts resolved by Trust, recorded | `test_cspm_conflict_recorded` |
| AC-5 | Unmapped type → cloud_unknown, flagged | `test_cspm_unknown_flagged` |
| AC-6 | Route hands off with one outcome per owner; no self-analysis | `test_cspm_routing` |
| AC-7 | Config assessment delegated to EA-0012 | `test_cspm_config_delegates` |
| AC-8 | Compliance/exposure/identity/risk all delegated | `test_cspm_all_delegations` |
| AC-9 | No direct findings/actions | `test_cspm_no_side_effects` |
| AC-10 | Tenant isolation | `test_cspm_tenant_isolation` |
| AC-11 | Invalid config rejected | `test_cspm_config_invalid` |
| AC-12 | Store in-memory & Postgres pass one suite | `test_cspm_store_contract[inmemory]` / `[postgres]` |
| AC-13 | Registers as AQService with health | `test_cspm_service_health` |
| AC-14 | No verdict field on the model (structural); reserved verdict names rejected case-insensitively at any depth (backstop) | `test_cspm_verdict_fields_rejected` |
| AC-15 | Partial routing names accepted + failed owners | `test_cspm_partial_routing_visible` |
| AC-16 | Provider-deleted input maps to unreported, never decommissioned | `test_cspm_deleted_maps_unreported` |
| AC-17 | `native_facts` keys ≡ `field_provenance` keys; an undeclared key is unconstructable (ECR-0021) | `test_cspm_native_facts_provenance_bound` |

## 9. Error taxonomy (contributions)

`CloudConfigInvalid`, `CloudObjectNotFound` (added to `conventions.errors` +
CONVENTIONS §9). Reuses `StoreUnavailable`,
`TenantScopeRequired`.

## 10. Registered event types (owned by EA-0028)

`aqelyn.cloud.resource_normalized`, `aqelyn.cloud.resource_unclassified` — via
`register_cloud_events()` (EA-0003 §7). Both are facts this engine originates.

The archive's `cloud.misconfiguration.detected` is **not** registered (**ECR-0021**).
A cloud baseline failure is EA-0012's `aqelyn.config.drift_detected` on an object whose
`provider` is set; "cloud misconfiguration" is a **query over that event**, not a second
fact. Emitting it here would give one occurrence two names — inviting double-counting —
and would assert a detection from the layer that owns no verdicts.

The archive's `cloud.resource.deleted` is **not** registered as a CSPM-owned fact.
A handed-in provider deletion observation maps to EA-0025 `mark_unreported`, whose
owner event is `aqelyn.inventory.asset_unreported` (ECR-0014/ECR-0020).

## 11. Failure handling

- Invalid config → `CloudConfigInvalid` at construction.
- An owner engine unavailable → the object is normalized and stored; that owner
  receives a `failed` outcome with a reason, successful owners remain `accepted`,
  and the result is `partial` (or `failed` if none accepted). Normalization SHALL
  NOT silently drop a resource or report complete routing because a downstream
  owner is down.
- Unmapped `resource_type` → `cloud_unknown`, flagged (never dropped) — an
  unclassified cloud resource is a **posture gap**, not noise.
- Store unavailable → `StoreUnavailable`; service `degraded`.

## 12. Dependencies & consumers

- **Depends on / routes to:** **EA-0025** (inventory), **EA-0012** (config/
  baseline), **EA-0010** (compliance), **EA-0023** (exposure), **EA-0011**
  (identity), **EA-0013** (risk); EA-0006 (reliability); EA-0002 (objects);
  EA-0004 (evidence); EA-0001 `AQService`.
- **Consumed by:** the six owners above (as normalized objects/signals); the cloud
  posture UI (**WCAG 2.2 AA**).

## 13. Resolved / deferred decisions

- **"Cloud" is a scope + a normalization layer, not six new engines** (§0) — the
  archive's Decision 2 ("multi-cloud normalization is required") is the genuine
  remainder; everything else is an existing owner, correctly fed.
- **No cloud collection** (§0.1) — descriptors are handed in; live enumeration is
  an EA-0008-gated connector action (`cloud.enumerate`).
- **Provider deletion is not decommission authority** — `reported_deleted` maps
  to EA-0025 `mark_unreported`; decommission still requires positive evidence or
  an attributed EA-0008-gated decision (ECR-0014/ECR-0020).
- **CSPM owns no verdict** — normalized objects forbid severity/score/compliance
  status/finding/action fields, and per-owner routing outcomes expose partial
  failure rather than smoothing it (ECR-0020).
- **Cloud baselines are EA-0012 `Baseline` data** — CIS-AWS/Azure/GCP shipped as
  configuration, not code.
- **IS-029 SSPM (next) is the same shape** — a SaaS normalizer feeding the same
  owners. The event/type check should be run on it too; if it, too, is
  "normalize + route", it may share this engine's pattern (and possibly warrant a
  shared posture-normalization base — an ECR to consider at that turn).
