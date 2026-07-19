# C-026 SaaS Security Posture Management — Implementation Task Bundle

**Milestone:** C-026 (SaaS Security Posture Management, EA-0029)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-025 (CSPM) merged & green; EA-0029 spec **Accepted**; **EA-0029 §0 + §2 read**; CONVENTIONS + EA-0005/0006/0011/0012/0023/0025 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no SaaS collection; no second inventory/config/compliance/identity/risk engine; no verdict field on the normalized object**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0029 §0 + §2 first.** SSPM has **two parts**: (a) the **CSPM
normalize-route pattern** with a SaaS vocabulary (restatement — reuse the shape),
and (b) **SaaS Integration Risk** — the one genuinely-new capability (OAuth
grants / app-to-app integrations as KG edges, over-scoped external grants as
EA-0023 facets). Keep them clearly separated; the new part is small and composes
existing owners.

**Four pins (EA-0029 §0.2 + ECR-0033), enforced as tests:**
1. **No verdict/severity field** on the normalized SaaS object.
2. **Trivial-route = pending, not safe** — absent routing/scope data is
   `over_scoped="unknown"` + surfaced as `pending`, never treated as "no risk"
   (the ECR-0013 lesson).
3. **No shared CSPM/SSPM base built here** — extraction is ECR-0032 (Proposed),
   a later optional refactor.
4. **Bounded does not mean silently short** — integration traversal uses
   EA-0005 `subgraph()` under `integration_max_nodes` and preserves its
   truncation signal on the result.

**Verification standard (ECR-0007):** structural (no verdict field; no
assessment method) + behavioural (delegation spies incl. EA-0005/EA-0023; socket
spy). Not textual checks.

## Target source layout

```
src/aqelyn/sspm/
├── __init__.py       # exports the engine, service, types, register_saas_events
├── models.py         # SaaSAppDescriptor, IntegrationDescriptor, NormalizedSaaSObject,
│                     #   SaaSIntegration, SaaSRoutingResult, SaaSConfig (Z1)
├── normalize.py      # descriptor -> AQObject, provenance, conflicts, NO verdict (Z2)
├── route.py          # route to owners; pending-aware (Z2)
├── integration.py    # NEW: edge -> EA-0005 blast radius -> EA-0023 facet (Z3)
├── baselines.py      # SaaS Baseline data (EA-0012 model) (Z3)
├── store.py          # SaaSNormalizationStore protocol (Z2)
├── memory.py / postgres.py  # stores + DDL (Z2)
├── engine.py         # normalize + route + map_integration + apply_saas_baselines (Z2/Z3)
└── service.py        # SaaSPostureService(AQService) + register_saas_events (Z4)
tests/sspm/           # acceptance suite (in-memory + Postgres)
```

**No analysis modules** (`compliance.py`, `risk.py`, …) — owned elsewhere.

---

## Z1 — Types & config

**Spec:** §4, FR-8/10a/12; §9. **Deliverables:** models (**normalized object has
no verdict/severity field** — §0.2.1); tri-state `over_scoped`;
`reachable_truncated`; source-claim-only `claim_confidence`; tenant-owned SaaS
records; config validation including `integration_max_nodes` (`SaaSConfigInvalid`); error codes in
`conventions.errors` + CONVENTIONS §9.
**Acceptance:** `test_sspm_no_verdict_field`, `test_sspm_no_vendor_verdict`,
`test_sspm_claim_confidence_not_vendor_score`, `test_sspm_config_invalid`.

## Z2 — Normalize + route (the reused CSPM pattern)

**Spec:** §0.1, §6, FR-1/2/4/5/13, D1/D2, NFR-2/NFR-3.
**Deliverables:** `normalize` (**handed-in only**; provenance; conflicts by
EA-0006 recorded; unmapped → `saas_unknown` flagged); `route` (to EA-0025/0012/
0010/0011; **missing data → `routing_pending`, surfaced**); `SaaSNormalizationStore`
(in-memory + Postgres + DDL) with explicit tenant scope on every read and stable
cursor pagination. Upgrade the existing
EA-0028 `CloudNormalizationStore` to the same EA-0002 D8 contract in this ticket
so the limit-only result is fixed once rather than copied.
**Depends on:** Z1.
**Acceptance:** `test_sspm_no_collection`, `test_sspm_normalize_object`,
`test_sspm_conflict_recorded`, `test_sspm_unknown_flagged`,
`test_sspm_routing_pending`,
`test_sspm_store_contract[inmemory]`, `test_sspm_store_contract[postgres]`,
`test_sspm_store_pagination[inmemory]`, `test_sspm_store_pagination[postgres]`,
`test_cspm_store_pagination[inmemory]`, `test_cspm_store_pagination[postgres]`.

## Z3 — SaaS Integration Risk (the new capability)

**Spec:** §2, §6, FR-6/7/8/10, D3, S1–S5.
**Deliverables:** `map_integration` (write EA-0002 edge with scopes; tri-state
`over_scoped`, with missing scopes = `"unknown"`); `integration_blast_radius`
via **EA-0005 `subgraph()`** under `integration_max_nodes`, returning a bounded
`BlastRadius` and propagating `Subgraph.truncated` to `reachable_truncated`;
over-scoped external grant → **EA-0023** facet;
`claim_confidence` from source evidence via **EA-0006**, never vendor data;
revocation = **proposed gated EA-0008 run**, no vendor verdict;
`apply_saas_baselines` → **EA-0012**.
**Depends on:** Z2.
**Acceptance:** `test_sspm_integration_graph`, `test_sspm_grant_is_exposure`,
`test_sspm_blast_radius_truncated`, `test_sspm_delegations`,
`test_sspm_claim_confidence_not_vendor_score`, `test_sspm_absence_not_removal`,
`test_sspm_revoke_gated`,
`test_sspm_all_delegations`, `test_sspm_no_side_effects`,
`test_sspm_tenant_isolation`.

## Z4 — Service + events

**Spec:** FR-14, §10. **Deliverables:** `SaaSPostureService` (`AQService`, name
`"sspm_engine"`) + `register_saas_events` (`app_normalized`,
`integration_detected`, `app_unclassified`); wired into the kernel factory.
**Depends on:** Z3. **Acceptance:** `test_sspm_service_health`.

---

## Review protocol (Claude Code)

**Reused-pattern part (Z2)** — same bar as C-025:
1. No SaaS collection (socket spy; no enumerate/token method).
2. **No verdict/severity field** on the normalized object (structural).
3. Provenance + recorded conflicts; unmapped flagged; **missing data → pending,
   not safe** (§0.2.2).
4. Config/compliance/identity all **delegated** — no analysis in `sspm/`.

**New-capability part (Z3)** — the genuinely-new surface:
5. Integrations are **EA-0002 edges**; blast radius is **EA-0005 traversal** — no
   local graph, no local traversal.
6. Over-scoped external grant becomes an **EA-0023 facet** — SSPM does not score
   exposure itself.
7. Revocation is a **proposed gated EA-0008 run**. The vendor-verdict boundary is
   **structural** (S5): confirm **no output type has a verdict/score/trust field**
   for the third party — the judgement must be unrepresentable, not merely
   unwritten. Try to set one and assert it doesn't exist (`test_sspm_no_vendor_verdict`).
8. **`saas_*` registered at BOTH `ACGConfig.assessable_object_types` factory
   sites (ECR-0028(a))** — a single-site widening ships correct-but-unreachable
   and re-bites identically. Drive both factory-built runtimes, not hand-built
   configs; assert SSPM reads EA-0012's coverage declaration rather than
   reimplementing it (`test_sspm_assessable_both_sites[inmemory|postgres]`).
9. `removed`/absent app → **EA-0025 `unreported`**, not deleted (S3).
10. Missing scopes are `over_scoped="unknown"`, never false; bounded KG reach
    propagates `reachable_truncated`; `claim_confidence` uses source evidence
    only and cannot become a vendor score (ECR-0033).

`ruff` + `mypy --strict` clean; tenant-scoped; interfaces match the spec. Merge
only on green review; then **report back to the owner**. **ECR-0032** (shared
normalization base) is a *separate* decision — do not fold a refactor into this
milestone.
