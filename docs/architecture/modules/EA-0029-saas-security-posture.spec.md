# EA-0029 — SaaS Security Posture Management (SSPM) — Implementation Specification

**Realizes:** EA-0029 / IS-029 (supersedes the placeholder `archive/EA-0029/EA-0029_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0002 (SaaS apps are objects)**, **EA-0025 (inventory), EA-0012 (config/baseline), EA-0010 (compliance), EA-0011 (SaaS identity), EA-0013 (risk)** — owners it feeds; **EA-0005 (integration graph), EA-0023 (grant-as-exposure), EA-0006 (Trust)** — for the new integration-risk capability; EA-0004 (evidence)
**Consumed by:** the owner engines above; the SaaS posture UI (a WCAG 2.2 AA surface)
**Status:** Accepted
**Build milestone:** C-026 (see `C-026_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 0. Scope reconciliation — SSPM = the CSPM pattern + one genuinely-new capability

The ECR-0015 check confirms IS-029 is **structurally EA-0028 with a SaaS
vocabulary** — with **one** new, unowned surface.

| IS-029 component | Realization |
|---|---|
| SaaS App Inventory (`application.discovered/updated/removed`) | **EA-0025.** A SaaS app is an asset. `removed` is governed by **EA-0025 S3: absence ≠ decommission** — a vanished app becomes `unreported`, not deleted. |
| SaaS Config Assessment (`configuration.assessed`) | **EA-0012.** SaaS baselines are `Baseline` data (add `saas_*` to `ACGConfig.assessable_object_types`, inheriting the coverage declaration). |
| SaaS Compliance | **EA-0010.** |
| SaaS Identity / permissions (`identity.risk`, `permission.changed`) | **EA-0011** (governance) + **EA-0027** (behavioural). |
| SaaS Policy (`saas.policy.violation`) | **EA-0009/EA-0010.** |
| SaaS Remediation (`remediation.recommended`) | EA-0012 `drift_to_findings` + proposed gated run (per C-023). |
| **SaaS Integration Risk (`saas.integration.detected`, `SaaSIntegration`)** | **GENUINELY NEW (§2).** OAuth grants + app-to-app integrations — 0 shipped modules model this. |

So EA-0029 has **two parts**: (a) a **SaaS normalizer** (the EA-0028 pattern,
different vocabulary) feeding the existing owners, and (b) a **SaaS Integration
Risk** capability that is real new surface.

### 0.1 Boundary

SaaS app + integration data is **handed in** (`SaaSAppDescriptor` /
`IntegrationDescriptor` posted to the platform). No SaaS API calls, no stored
SaaS/OAuth tokens, no tenant enumeration — **live SaaS collection is an
EA-0008-gated connector action** (`saas.enumerate`), per EA-0025 §0.1.

### 0.2 Three decisions pinned before C-026 (from the reuse chain)

1. **No verdict/severity field on the normalized SaaS object.** The object
   carries facts + provenance; *severity/verdict belongs to the owner that
   assesses it* (EA-0012/EA-0023/EA-0013). A normalizer that pre-judges would
   fork severity.
2. **Trivial-route semantics decided up front** (the ECR-0013 lesson): if the
   integration/permission data needed to route or assess is **absent**, the
   object is normalized and stored but its routing is **`pending` + surfaced** —
   never silently treated as "no risk". Absence is not safety.
3. **No shared CSPM/SSPM normalization base is built inside this milestone.** With
   two instances now existing, extraction is worth *considering* — raised as
   **ECR-0032 (Proposed)** — but SSPM ships on its own footing first; refactoring
   into a shared base is a separate, optional step (§13).

## 1. Purpose (normalizer part)

SaaS is where the estate leaks without anyone touching a server: an over-shared
Google Drive, an admin-without-MFA in Salesforce, a forgotten Slack app with
read-everything scopes. AQELYN can already govern config, identity, and
compliance — SSPM makes SaaS apps **legible** to it (normalize + route, the
EA-0028 pattern) — and then adds the piece SaaS uniquely needs: **integration
risk**.

## 2. The new capability: SaaS Integration Risk

The distinctive SaaS threat is **the third-party integration** — an OAuth grant
or app-to-app connection that hands an outside application standing access to
your data, often with broad scopes, approved once by one user, and never
reviewed. This is genuinely unowned surface, and it composes cleanly:

- **S1 — Integrations are a graph** (`EA-0005`). An `Integration` is an **edge**:
  `(grantor_app | user) --grants[scopes]--> (third_party_app)`. "What could this
  compromised vendor reach?" is a KG traversal, explainable, bounded — not a new
  graph engine.
- **S2 — An over-scoped external grant is an exposure facet** (`EA-0023`). A
  third-party app with `read_all_files` and external ownership is a
  `SurfaceFacet` — EA-0023 scores its exposure by what it reaches (mission
  weighting) exactly as it does a public bucket. No new scorer.
- **S3 — Integration confidence is EA-0006 Trust**; risk aggregation is EA-0013.
  No new confidence or risk model.
- **S4 — Detect-and-propose.** Revoking a grant is destructive → a **proposed
  gated EA-0008 run**. SSPM flags and routes; it revokes nothing.
- **S5 — Findings, not verdicts on vendors (structural).** An over-scoped
  integration is a finding about *a grant and its blast radius*, evidence-backed —
  never a reputational judgement of the third party. This is enforced by the type
  system, not a rule: **no output type carries a vendor-level verdict, score, or
  trust field.** `SaaSIntegration` describes what a grant *can reach*
  (`reachable_object_ids`, `scopes`, `over_scoped`); there is no representation of
  "this vendor is (un)trustworthy" to populate. The judgement is *unrepresentable*
  — the same discipline as EA-0021 S8 (no individual-intent) and EA-0027 (no
  person-score): the platform states what a thing can reach, never what a party
  *is*.

So the **new** code here is: model integrations as graph edges with their scopes,
infer the blast radius via KG, and express over-scoped external grants as EA-0023
facets. Everything else routes.

## 3. Design decisions

- **D1 — `SaaSAppDescriptor`/`IntegrationDescriptor` in → `AQObject`s out**
  (`saas_app`, `saas_integration`), provider/tenant/app provenance preserved
  (the EA-0028 D1/D3 pattern).
- **D2 — Route to owners** (EA-0025/0012/0010/0011/0013), exactly as EA-0028.
- **D3 — Integrations become EA-0002 relationship edges** with scope metadata;
  blast radius via **EA-0005**; over-scoped external grants surfaced to
  **EA-0023** (S1/S2).
- **D4 — SaaS baselines are EA-0012 `Baseline` data**; `saas_*` added to
  `ACGConfig.assessable_object_types` **at both factory sites (ECR-0028(a))** —
  the widening ships correct-but-unreachable if only one site is updated, and will
  re-bite identically here. In return, EA-0012's coverage declaration
  (`coverage_complete`, per-type `truncated`, `unassessed_object_ids`) comes
  **free** — SSPM SHALL read it, never reimplement it.
- **D5 — No verdict/severity on the normalized object** (§0.2.1); **no
  collection** (§0.1); **no second inventory/config/compliance/identity/risk
  engine**.
- **D6 — Registered as an `AQService`;** store in-memory + Postgres.

## 4. Types

```
SaaSAppDescriptor = { provider: str, tenant: str, app_id: str, app_name: str,
                      resource_type: str, raw: dict, observed_at: datetime,
                      source_id: str, evidence_id: str | null }        # handed in (§0.1)

IntegrationDescriptor = { integration_id: str, grantor_ref: str,       # app/user granting
                          third_party_app: str, third_party_external: bool,
                          scopes: list[str], granted_by: str | null,
                          granted_at: datetime | null, raw: dict,
                          source_id: str, evidence_id: str | null }     # the NEW surface (§2)

NormalizedSaaSObject = { object_id, object_type: str, provider: str, tenant: str,
                         native_facts: dict, field_provenance: dict,
                         conflicts: list[dict], evidence_id: str }       # NO verdict/severity (§0.2.1)

SaaSIntegration = { object_id, integration_id, grantor_ref, third_party_app,
                    third_party_external: bool, scopes: list[str],
                    over_scoped: bool, reachable_object_ids: list[str],  # KG blast radius (S1)
                    exposure_facet_ref: str | null,                      # EA-0023 (S2)
                    confidence: float, evidence_id: str, reason: str }

SaaSRoutingResult = { object_id, routed_to: list[str], routing_pending: list[str],  # §0.2.2
                      inventory_ref: str | null, iam_refs: list[str],
                      facet_refs: list[str], integration_ref: str | null }
SaaSConfig = { type_map: dict, baseline_ids: list[str],
               sensitive_scopes: list[str], batch_size: int }           # scopes that make a grant over-scoped
```

Reuses EA-0002 objects/relationships, EA-0005 traversal, EA-0006 reliability,
EA-0012 `Baseline`, EA-0004 evidence.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class SaaSNormalizationStore(Protocol):
    async def put(self, obj: NormalizedSaaSObject) -> NormalizedSaaSObject: ...
    async def put_integration(self, i: SaaSIntegration) -> SaaSIntegration: ...
    async def get(self, object_id: str) -> NormalizedSaaSObject | None: ...
    async def query(self, *, tenant_id: str | None, provider: str | None = None,
                    limit: int = 1000) -> list[NormalizedSaaSObject]: ...

class SaaSPostureEngine(Protocol):
    async def normalize(self, descriptors: Sequence[SaaSAppDescriptor], *,
                        tenant_id: str | None) -> list[NormalizedSaaSObject]: ...   # D1
    async def route(self, object_ids: Sequence[str], *,
                    tenant_id: str | None) -> list[SaaSRoutingResult]: ...          # D2, pending-aware (§0.2.2)
    async def map_integration(self, descriptors: Sequence[IntegrationDescriptor], *,
                              tenant_id: str | None) -> list[SaaSIntegration]: ...  # NEW (§2): edge + KG + facet
    async def integration_blast_radius(self, integration_id: str) -> list[str]: ... # EA-0005 (S1)
    async def apply_saas_baselines(self, *, tenant_id: str | None,
                                   scope: dict | None = None) -> str: ...           # EA-0012 (D4)
    def explain(self, obj: NormalizedSaaSObject) -> dict: ...
```

`SaaSPostureService` wraps engine + store as an `AQService`
(name `"sspm_engine"`, depends on object/kg/inventory/assetconfig/compliance/iag/
exposure/risk/trust/evidence; health reflects availability + config validity).

**Deliberately absent:** any `enumerate()`/SaaS-API method (§0.1); any second
inventory/config/compliance/identity/risk analysis (§0); any verdict/severity on
the normalized object (§0.2.1).

## 6. Computation (the reference model)

**Normalize + route.** As EA-0028 §6: descriptor → `AQObject` with provenance,
conflicts recorded by EA-0006, unmapped → `saas_unknown` flagged; route to
owners; **absent routing data → `routing_pending`, surfaced** (§0.2.2). No
verdict attached.

**Map integrations (new).** For each `IntegrationDescriptor`: write an EA-0002
relationship edge `grantor --grants[scopes]--> third_party_app`; compute
`over_scoped = any(scope ∈ sensitive_scopes)` **and** `third_party_external`;
compute `reachable_object_ids` via **EA-0005** traversal (bounded); if over-scoped
+ external, emit an **EA-0023** `SurfaceFacet` (`api_endpoint`/`federated_
identity` family) so exposure is scored by what it reaches; `confidence` via
**EA-0006**; `reason` names the scopes and the reach. No revocation (S4).

**Baselines.** `apply_saas_baselines` → **EA-0012 `assess`** with SaaS baselines
(D4).

## 7. Requirements

### Functional (testable)

- **FR-1** `normalize`/`map_integration` SHALL accept handed-in descriptors only; no SaaS API call, no stored token, no enumerate method (§0.1).
- **FR-2** Normalized objects SHALL carry provider/tenant + `native_facts` + `field_provenance`; conflicts SHALL be resolved by EA-0006 and **recorded** (D1).
- **FR-3** A normalized SaaS object SHALL NOT carry a verdict/severity field; severity belongs to the assessing owner (§0.2.1).
- **FR-4** `route` SHALL hand objects to EA-0025/0012/0010/0011; missing routing/assessment data SHALL yield `routing_pending`, surfaced — never silently "no risk" (§0.2.2).
- **FR-5** An unmapped `resource_type` SHALL become `saas_unknown`, flagged, never dropped.
- **FR-6** `map_integration` SHALL write an EA-0002 edge with scopes; it SHALL NOT store a separate integration graph or traverse it itself — blast radius SHALL use **EA-0005** (S1/D3).
- **FR-7** An over-scoped external grant SHALL be expressed as an **EA-0023** exposure facet; the module SHALL NOT score exposure itself (S2).
- **FR-8** Integration `confidence` SHALL come from EA-0006; risk aggregation SHALL be EA-0013; no second model of either (S3).
- **FR-9** A `removed`/absent SaaS app SHALL be handled by EA-0025 as **`unreported`, not decommissioned** — a SaaS app vanishing from a provider listing is absence of evidence, not evidence of removal (§0, EA-0025 S3).
- **FR-10** Revoking a grant SHALL be a **proposed gated EA-0008 run**; the module SHALL revoke nothing (S4).
- **FR-10a** No output type (`SaaSIntegration`, `NormalizedSaaSObject`, or any emitted finding field) SHALL carry a vendor-level verdict/score/trust field; the vendor judgement SHALL be structurally unrepresentable (S5).
- **FR-10b** `saas_*` object types SHALL be registered in `ACGConfig.assessable_object_types` at **both** factory sites (ECR-0028(a)); SSPM SHALL consume EA-0012's coverage declaration and SHALL NOT reimplement coverage.
- **FR-11** SaaS config assessment SHALL be EA-0012; compliance EA-0010; identity EA-0011/0027; the module SHALL implement none (§0).
- **FR-12** All operations SHALL be tenant-scoped and bounded; invalid config (unknown `type_map` target/baseline, `batch_size ≤ 0`) SHALL raise `SaaSConfigInvalid`.
- **FR-13** `SaaSNormalizationStore` in-memory and Postgres implementations SHALL pass one contract suite.
- **FR-14** `SaaSPostureService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (normalizer + integration-mapper, not silo — structural)** no assessment/compliance/identity/risk method exists; delegation spies prove the owners do the analysis (incl. EA-0005 for blast radius, EA-0023 for exposure), per **ECR-0007**.
- **NFR-2 (no collection)** socket spy proves zero outbound; no enumerate/token method.
- **NFR-3 (no premature verdict)** the normalized object has no severity/verdict field (structural).
- **NFR-4 (bounded & typed)** batched; store passes one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Handed-in only; no SaaS API/enumerate/token | `test_sspm_no_collection` |
| AC-2 | Descriptor → AQObject w/ provenance | `test_sspm_normalize_object` |
| AC-3 | No verdict/severity on normalized object | `test_sspm_no_verdict_field` |
| AC-4 | Conflicts resolved by Trust, recorded | `test_sspm_conflict_recorded` |
| AC-5 | Unmapped → saas_unknown, flagged | `test_sspm_unknown_flagged` |
| AC-6 | Missing routing data → pending, surfaced | `test_sspm_routing_pending` |
| AC-7 | Integration → EA-0002 edge; blast radius via EA-0005 | `test_sspm_integration_graph` |
| AC-8 | Over-scoped external grant → EA-0023 facet | `test_sspm_grant_is_exposure` |
| AC-9 | Confidence from Trust; risk to EA-0013 | `test_sspm_delegations` |
| AC-10 | removed app → unreported (EA-0025), not deleted | `test_sspm_absence_not_removal` |
| AC-11 | Revocation proposed + gated | `test_sspm_revoke_gated` |
| AC-11a | Vendor verdict/score field structurally absent | `test_sspm_no_vendor_verdict` |
| AC-11b | saas_* registered at both factory sites; coverage inherited | `test_sspm_assessable_both_sites` |
| AC-12 | Config/compliance/identity all delegated | `test_sspm_all_delegations` |
| AC-13 | No direct findings/actions; tenant isolation | `test_sspm_no_side_effects` |
| AC-14 | Invalid config rejected | `test_sspm_config_invalid` |
| AC-15 | Store in-memory & Postgres pass one suite | `test_sspm_store_contract[inmemory]` / `[postgres]` |
| AC-16 | Registers as AQService with health | `test_sspm_service_health` |

## 9. Error taxonomy (contributions)

`SaaSConfigInvalid`, `SaaSObjectNotFound`, `IntegrationNotFound`,
`UnmappedSaaSType` (added to `conventions.errors` + CONVENTIONS §9). Reuses
`StoreUnavailable`, `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0029)

`aqelyn.saas.app_normalized`, `aqelyn.saas.integration_detected` (the new
surface), `aqelyn.saas.app_unclassified` — via `register_saas_events()`
(EA-0003 §7). Config/identity/compliance events stay with their owners
(§0); `saas.policy.violation` is an EA-0009/EA-0010 concern.

## 11. Failure handling

- Invalid config → `SaaSConfigInvalid` at construction.
- Owner unavailable → object normalized/stored, routing `pending`, surfaced
  (§0.2.2) — never dropped, never "no risk".
- Missing integration scopes → the integration is recorded with
  `over_scoped: unknown` (flagged) and routed pending — **absence of scope data
  is not absence of risk** (§0.2.2).
- KG/EA-0023 unavailable → blast radius / facet marked `pending`; the integration
  is still recorded (a known-but-unscored grant is surfaced, not hidden).
- Store unavailable → `StoreUnavailable`; service `degraded`.

## 12. Dependencies & consumers

- **Depends on / routes to:** **EA-0025, EA-0012, EA-0010, EA-0011, EA-0013**
  (owners); **EA-0005** (integration blast radius), **EA-0023** (grant exposure),
  **EA-0006** (Trust); EA-0002 (objects/edges); EA-0004 (evidence);
  **EA-0008** (revocation proposed + gated); EA-0001 `AQService`.
- **Consumed by:** the owners above; the SaaS posture UI (**WCAG 2.2 AA**).

## 13. Resolved / deferred decisions

- **SSPM = CSPM pattern + SaaS Integration Risk** (§0) — the normalizer restates
  EA-0028; the integration graph is the genuine new capability (§2).
- **No verdict on the normalized object; trivial-route = pending-not-safe;
  no shared base built here** — the three pins (§0.2).
- **Shared posture-normalization base — ECR-0032 (Proposed).** Two instances
  (CSPM, SSPM) now share the `normalize→object+provenance→route` shape; a
  `posture_normalization` base they both specialise is now worth *considering*.
  Not built in C-026; proposed for owner decision, to be done (if approved) as a
  refactor once both are green — never as a big-bang rewrite.
- **No SaaS collection** (§0.1) — `saas.enumerate` is an EA-0008-gated connector
  action.
