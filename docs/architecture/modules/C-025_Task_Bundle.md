# C-025 Cloud Security Posture Management — Implementation Task Bundle

**Milestone:** C-025 (Cloud Security Posture Management, EA-0028)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-024 complete; EA-0028 spec **Accepted**; **EA-0028 §0 + ECR-0020/0021/0022 read**; CONVENTIONS + EA-0002/0006/0010/0011/0012/0013/0023/0025 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no cloud collection; no second inventory/baseline/compliance/exposure/identity/risk engine; no verdict field in a CSPM model; no provider-deleted input may decommission an asset**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0028 §0 first.** "Cloud" is **a scope + a normalization layer**, not six
new engines. A cloud resource is an asset (EA-0025); a public bucket is a facet
(EA-0023); an IAM role is an entitlement (EA-0011); CIS-AWS is a framework
(EA-0010). This module's only genuinely new job (the archive's Decision 2) is
**multi-cloud normalization** — turning provider resources into AQELYN objects and
**routing** them to the owners that already do the analysis. If you find yourself
writing drift/compliance/exposure/risk logic here, stop and raise an ECR.

**Verification standard (ECR-0007/ECR-0020):** structural (no
assessment/score/detect method and no severity/score/compliance-status field
exists; models use `extra="forbid"`) + behavioural (delegation spies prove the six
owners do the work; socket spy proves no collection; lifecycle spy proves
provider-deleted → unreported, never decommissioned). Not textual checks.

## Target source layout

```
src/aqelyn/cspm/
├── __init__.py       # exports the engine, service, types, register_cloud_events
├── models.py         # CloudResourceDescriptor, NormalizedCloudObject,
│                     #   OwnerRouteOutcome, CloudRoutingResult,
│                     #   CloudNormalizationConfig (Y1)
├── normalize.py      # descriptor -> AQObject, provenance, conflict recording (Y2)
├── route.py          # hand normalized objects/signals to their owners (Y3)
├── baselines.py      # cloud Baseline data (EA-0012 model) + apply via EA-0012 (Y3)
├── store.py          # CloudNormalizationStore protocol (Y2)
├── memory.py         # in-memory store (Y2)
├── postgres.py       # Postgres store + DDL (Y2)
├── engine.py         # normalize + route + apply_cloud_baselines + explain (Y2/Y3)
└── service.py        # CloudPostureService(AQService) + register_cloud_events (Y4)
tests/cspm/           # acceptance suite (in-memory + Postgres)
```

**No analysis modules here.** No `drift.py`, `compliance.py`, `exposure.py`,
`risk.py` — those exist and are owned elsewhere.

---

## Y1 — Types & config

**Spec:** §4, FR-10; §9.
**Deliverables:** the models; config validation (`CloudConfigInvalid` on unknown
`type_map` target, unknown `baseline_id`, `batch_size ≤ 0`); new error codes in
`conventions.errors` + CONVENTIONS §9. Every model uses `extra="forbid"`;
`NormalizedCloudObject` has no severity/score/risk-score/compliance-status/
finding/action field, and construction rejects those reserved keys recursively and
**case-insensitively** inside `native_facts`, `field_provenance`, and `conflicts`;
provider verdicts stay only in raw EA-0004 evidence (FR-13/ECR-0020).
**The primary guarantee is provenance binding, not the name list (ECR-0021):**
`set(native_facts) == set(field_provenance)` is enforced at construction, so a key
with no declared raw source is unconstructable. The reserved-name check is a backstop.
**`native_facts` values are flat — scalars or lists of scalars (ECR-0023)** — so the
binding covers every key; a nested mapping would smuggle undeclared keys past it.
Structured provider material stays in the raw EA-0004 evidence block.
Per ECR-0022, `NormalizedCloudObject` carries a validated `tenant_id`; Y2 store
reads require an explicit tenant scope.
**Depends on:** EA-0002/0012 types, conventions.
**Acceptance:** `test_cspm_config_invalid`, `test_cspm_verdict_fields_rejected`,
`test_cspm_native_facts_provenance_bound`, `test_cspm_tenant_model_guard`.

## Y2 — Normalization (provenance + conflict recording) + store

**Spec:** §0.1, §6, FR-1/2/3/4/5/11, D1/D3, NFR-2/NFR-3.
**Deliverables:** `normalize` (**handed-in only — no cloud API/enumerate/socket**;
descriptor → `AQObject` with provider/account/region + `native_facts`; raw block
as evidence; `field_provenance` per field; cross-snapshot conflicts by **EA-0006**
reliability+recency, **recorded**; unmapped type → `cloud_unknown`, flagged);
`CloudNormalizationStore` (in-memory + Postgres + DDL).
**Depends on:** Y1.
**Acceptance:** `test_cspm_no_collection`, `test_cspm_normalize_object`,
`test_cspm_field_provenance`, `test_cspm_conflict_recorded`,
`test_cspm_unknown_flagged`,
`test_cspm_store_contract[inmemory]`, `test_cspm_store_contract[postgres]`.

## Y3 — Routing to owners + cloud baselines (delegate everything)

**Spec:** §6, FR-6/7/8/9, D2/D4, NFR-1.
**Deliverables:** `route` (hand normalized objects to **EA-0025** inventory,
**EA-0011** IAM, **EA-0023** facets, register for **EA-0012** assessment; record
one `OwnerRouteOutcome` per configured owner and overall
`complete`/`partial`/`failed`; **no self-analysis**); `apply_cloud_baselines`
(cloud `Baseline` data → **EA-0012 `assess`**); cloud findings flow to
**EA-0013** via the owners. A `reported_deleted` descriptor routes only to
**EA-0025 `mark_unreported`** / `aqelyn.inventory.asset_unreported`; it never
decommissions or deletes an asset (FR-14/ECR-0014/ECR-0020).
**Depends on:** Y2.
**Acceptance:** `test_cspm_routing`, `test_cspm_config_delegates`,
`test_cspm_all_delegations`, `test_cspm_no_side_effects`,
`test_cspm_tenant_isolation`, `test_cspm_partial_routing_visible`,
`test_cspm_deleted_maps_unreported`.

## Y4 — Service + events

**Spec:** FR-12, §10.
**Deliverables:** `CloudPostureService` (`AQService`, name `"cspm_engine"`) +
`register_cloud_events` (`resource_normalized`, `resource_unclassified` — **only
these two**); **no `misconfiguration_detected` event (ECR-0021)** — a cloud baseline
failure is EA-0012's `aqelyn.config.drift_detected` on a cloud object, and a second
name for one occurrence invites double-counting; no CSPM-owned deletion event; wired
into the kernel factory.
**Depends on:** Y3.
**Acceptance:** `test_cspm_service_health`.

---

## Review protocol (Claude Code) — "normalizer, not silo"

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No second analysis engine or verdict model.** Confirm **no**
   assessment/score/detect logic exists here and that `NormalizedCloudObject`
   forbids severity/score/risk-score/compliance-status/finding/action fields and
   recursively rejects those keys from nested normalized state.
   Delegation spies must prove config→EA-0012, compliance→EA-0010,
   exposure→EA-0023, identity→EA-0011, risk→EA-0013, inventory→EA-0025. If any
   analysis or verdict happens in `cspm/`, it's wrong (§0/NFR-1/ECR-0020).
2. **No cloud collection.** Socket spy proves zero outbound; no
   enumerate/scan/cloud-API method exists (§0.1).
3. **Provenance + recorded conflicts.** Every normalized field traces to a raw
   provider field; a cross-snapshot conflict is resolved by Trust and **recorded**,
   never smoothed.
4. **Unmapped ≠ dropped.** An unknown `resource_type` becomes `cloud_unknown`,
   flagged — an unclassified cloud resource is a posture gap, not noise.
5. **Owner-down ≠ silent drop or false success.** Every configured owner has an
   explicit accepted/failed outcome. A five-of-six handoff is `partial` and names
   the failed owner + reason.
6. **CSPM registers exactly two events** (`resource_normalized`,
   `resource_unclassified`). If `misconfiguration_detected` appears, it is wrong
   (ECR-0021): that fact is EA-0012's, and CSPM owns no verdict to detect.
   Also check `native_facts` keys are provenance-bound and values are flat (ECR-0023).
   An extractor that copies the provider block wholesale breaks both rules and refuses
   real AWS Config / Azure Policy payloads, which carry `complianceType` /
   `complianceState` / `Severity`. Y2 must **flatten** (e.g. `open_ports: [22, 3389]`),
   not copy — that flattening is the translation this engine exists to perform.
7. **Provider-deleted ≠ decommissioned.** A lifecycle spy proves the input maps to
   EA-0025 `mark_unreported` and never calls a delete/decommission path. No
   `cloud.resource.deleted` event is registered as a CSPM-owned fact.
8. `ruff` + `mypy --strict` clean; tenant-scoped; interfaces match the spec.

Merge only on green review; then **report back to the owner** before the next
module. **Note for IS-029 (SSPM):** run the event/type check; it is likely the
same normalize+route shape — consider a shared posture-normalization base then.
