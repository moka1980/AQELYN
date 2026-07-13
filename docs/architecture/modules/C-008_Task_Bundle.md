# C-008 Identity & Access Governance — Implementation Task Bundle

**Milestone:** C-008 (Identity & Access Governance, EA-0011)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0010 merged & green; EA-0011 spec **Accepted**; CONVENTIONS + EA-0002/0005/0008/0009 + Finding model read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **the engine never grants/revokes access directly**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

This engine **composes** the core (KG, Policy, ObjectStore, Evidence, Finding,
Workflow). All access *change* is delegated to EA-0008 (§0). If a needed behavior
isn't in the spec, raise an ECR.

## Target source layout

```
src/aqelyn/iag/
├── __init__.py       # exports the engine, service, types, register_iag_events
├── models.py         # AccessPath, AccessRisk(Report), ReviewItem, Certification, IAGConfig (I1)
├── analysis.py       # access_paths + analyze_risk (orphaned/dormant/over-priv/SoD/privileged) (I2)
├── store.py          # CertificationStore protocol (I3)
├── memory.py         # InMemoryCertificationStore (I3)
├── postgres.py       # PostgresCertificationStore + DDL (I3)
├── engine.py         # certifications + risks_to_findings + complete (delegates to Workflow) (I3/I4)
└── service.py        # IdentityAccessGovernanceService(AQService) + register_iag_events (I5)
tests/iag/            # acceptance suite (in-memory + Postgres)
```

---

## I1 — Types & config

**Spec:** §4, FR-11; §9.
**Deliverables:** the models; `IAGConfig` validation (`IAGConfigInvalid`); new
error codes in `conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0002/0005 types, conventions.
**Acceptance:** `test_iag_config_invalid`.

## I2 — Identity graph & risk detection

**Spec:** §6, FR-1/2/3/4/9/10, D1/D2/D3.
**Deliverables:** `access_paths` (via KG) and `analyze_risk` (orphaned, dormant,
over-privilege, SoD via `PolicyEngine`, privileged-unreviewed), deterministic,
pure, tenant-scoped, `truncated` propagated; `explain`.
**Depends on:** I1.
**Acceptance:** `test_iag_access_paths`, `test_iag_orphaned_dormant`,
`test_iag_over_privilege`, `test_iag_sod_conflict`,
`test_iag_privileged_unreviewed`, `test_iag_analyze_deterministic`,
`test_iag_tenant_isolation`, `test_iag_truncation_propagates`.

## I3 — Certification store & campaigns

**Spec:** §4/§6 (certifications), FR-5/6/12, D4.
**Deliverables:** `CertificationStore` (in-memory + Postgres + DDL, optimistic
version); `open_certification` (review items seeded from risk recommendations);
`decide_item` (records decision + `EvidenceRecord`).
**Depends on:** I2.
**Acceptance:** `test_iag_open_certification`, `test_iag_decide_item_evidence`,
`test_iag_cert_contract[inmemory]`, `test_iag_cert_contract[postgres]`.

## I4 — Findings & delegated remediation (no direct change)

**Spec:** §0, §6, FR-7/8, D5, NFR-1.
**Deliverables:** `risks_to_findings` (optional Mission prioritization) and
`complete_certification` (each `revoked` item → finding + **proposed** Workflow
run; never a direct revoke).
**Depends on:** I3.
**Acceptance:** `test_iag_risks_to_findings`, `test_iag_complete_delegates`,
`test_iag_no_direct_access_mutation`.

## I5 — Service + events

**Spec:** FR-13, §10.
**Deliverables:** `IdentityAccessGovernanceService` (`AQService`, name
`"iag_engine"`) + `register_iag_events`; wired into the kernel factory.
**Depends on:** I4.
**Acceptance:** `test_iag_service_health`.

---

## Review protocol (Claude Code) — the safety line gets the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No code path grants or revokes access, or edits an identity/account/
   entitlement object.** Every change is a *proposed* Workflow run (§0/D5). Trace
   `complete_certification` and `risks_to_findings` — they raise findings + propose
   runs, nothing more.
2. SoD detection uses `PolicyEngine` rules, not a bespoke rule language.
3. Risk analysis is deterministic, pure, tenant-scoped; `truncated` propagates.
4. Every reviewer decision writes an `EvidenceRecord`; campaigns use optimistic
   version.
5. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
