# EA-0011 — Identity & Access Governance Engine — Implementation Specification

**Realizes:** EA-0011 / IS-011 (supersedes the placeholder `archive/EA-0011/EA-0011_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0002 (identities/accounts/roles/entitlements as objects + relationships), EA-0005 (entitlement-path graph analysis), EA-0009 (SoD / access policy rules), EA-0004 (review & certification evidence), the Finding model; EA-0008 (remediation is proposed, gated, never direct)
**Consumed by:** access-review & certification UI (reviewer inboxes, campaigns — a WCAG 2.2 AA surface), the Finding pipeline (access risks become findings), EA-0010 governance reporting, auditors (certification evidence packages)
**Status:** Accepted
**Change control:** ECR-0030 (identity/risk enumeration follows object pages to exhaustion)
**Build milestone:** C-008 (see `C-008_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 0. Safety boundary (read first)

Identity and access are among the most sensitive things AQELYN touches, so the
boundary is explicit and narrow:

- **This engine detects, reviews, and certifies. It does NOT grant or revoke
  access.** It reads the identity/access estate, finds problems (orphaned or
  dormant accounts, over-privilege, SoD violations, un-reviewed privileged
  access), and runs review/certification campaigns that produce **decisions and
  evidence**. Any *change* to access (disable an account, remove an entitlement)
  is a **remediation action proposed to the Workflow Engine (EA-0008)** and
  authorized by the Policy Engine (EA-0009) — gated, approved, evidenced, and
  reversible per those specs. This engine never mutates access directly.
- **A certification decision is a record, not an execution.** "Revoke" as a
  reviewer decision creates a *finding + a proposed remediation run*; it does not
  itself remove anything.
- **Pure/read over the estate otherwise** — deterministic, explainable, tenant-
  scoped, evidence-recorded. All "can I act?" authority remains with EA-0008/0009.

## 1. Purpose

The Identity & Access Governance Engine answers *who has access to what, should
they, and can we prove it was reviewed?* It correlates identities to their
accounts and entitlements, surfaces access risk (least-privilege violations,
segregation-of-duties conflicts, orphaned/dormant/privileged accounts), and runs
**access reviews and certification campaigns** so an organization can attest —
with evidence — that access is appropriate.

## 2. Design decisions

- **D1 — Identity graph is modeled in EA-0002.** Identities, accounts, roles,
  and entitlements are `AQObject`s (`object_type ∈ {identity, account, role,
  entitlement}`); grants are relationships (`has_account`, `has_role`,
  `grants_entitlement`, `member_of`). Access *paths* are computed by the
  Knowledge Graph (EA-0005). No separate identity store.
- **D2 — SoD & access rules are Policy rules (EA-0009).** A segregation-of-duties
  conflict is a compliance/authorization rule; this engine *detects* using
  Policy evaluation + graph reachability, it doesn't embed its own rule language.
- **D3 — Detection is deterministic, pure, explainable.** Every risk carries the
  entitlement path and the rule/heuristic that flagged it. Charter "prove it."
- **D4 — Reviews and certifications are stateful, evidenced records.** A
  campaign, its items, reviewer decisions, and outcomes persist (in-memory +
  Postgres store) and each decision writes an `EvidenceRecord` (EA-0004).
- **D5 — Remediation is delegated (§0).** Outcomes that require change produce
  findings + proposed Workflow runs; nothing is revoked here.
- **D6 — Tenant-scoped and bounded** via the object store / KG it builds on.
  Object enumeration exhausts `next_cursor` in bounded pages; a repeated cursor
  fails closed rather than yielding a partial clean report (ECR-0030).
- **D7 — Registered as an `AQService`.**

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Identity** | A person/service principal (`object_type "identity"`). |
| **Account** | A credential/login at some system, linked to an identity (`has_account`). |
| **Role / Entitlement** | A bundle of / a specific permission, granted via relationships. |
| **Access path** | The relationship chain identity → account → role → entitlement (from EA-0005). |
| **Orphaned account** | An account with no owning identity. **Dormant** | an account unused past a threshold. |
| **Over-privilege** | Entitlements beyond a baseline/peer norm or policy. |
| **SoD conflict** | Two entitlements a single identity must not hold together (a Policy rule). |
| **Access review / certification** | A campaign in which reviewers attest each access item (approve / revoke / delegate). |

## 4. Types

```
AccessPath   = { identity_id: str, account_id: str | null,
                 entitlement_ids: list[str], via: "Path" }        # EA-0005 Path (explainable)
AccessRisk   = { kind: "orphaned"|"dormant"|"over_privilege"|"sod_conflict"|"privileged_unreviewed",
                 subject_id: str, detail: dict, severity: str,
                 evidence_path: "Path | null", reason: str }
AccessRiskReport = { risks: list[AccessRisk], evaluated: int, truncated: bool }

ReviewItem   = { id: str, identity_id: str, account_id: str | null,
                 entitlement_id: str | null, current_state: dict,
                 recommendation: str,                              # from risk analysis
                 decision: "pending"|"approved"|"revoked"|"delegated",
                 decided_by: ActorRef | null, decided_at: datetime | null,
                 evidence_id: str | null, note: str | null }
Certification = { id: str, tenant_id: str | null, name: str, scope: dict,
                  status: "open"|"in_progress"|"completed"|"expired",
                  items: list[ReviewItem], created_by: ActorRef,
                  created_at: datetime, due_at: datetime | null, version: int }

IAGConfig    = { dormant_days: int, privileged_roles: list[str],
                 peer_baseline: str | null, review_default_due_days: int }
```

Reuses EA-0005 `Path`, EA-0002 objects/relationships, `ActorRef`, the Finding
model, and EA-0009 rule evaluation.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class CertificationStore(Protocol):
    async def put(self, cert: Certification) -> Certification: ...          # optimistic version
    async def get(self, cert_id: str) -> Certification | None: ...
    async def list(self, *, tenant_id: str | None,
                   status: Sequence[str] | None = None) -> list[Certification]: ...

class IdentityAccessGovernanceEngine(Protocol):
    async def access_paths(self, identity_id: str) -> list[AccessPath]: ...   # via KG (D1)
    async def analyze_risk(self, *, tenant_id: str | None,
                           scope: "ObjectQuery | None" = None) -> AccessRiskReport: ...  # D2/D3
    async def open_certification(self, *, tenant_id: str | None, name: str,
                                 scope: "ObjectQuery", by: ActorRef,
                                 due_days: int | None = None) -> Certification: ...  # D4
    async def decide_item(self, cert_id: str, item_id: str, *, decision: str,
                          by: ActorRef, note: str | None,
                          expected_version: int) -> Certification: ...          # records evidence (D4)
    async def complete_certification(self, cert_id: str, *, by: ActorRef,
                                     raise_findings: bool = True) -> list[str]: ...  # revokes -> findings/runs (D5)
    async def risks_to_findings(self, report: AccessRiskReport, *, by: ActorRef,
                                prioritize: bool = True) -> list[str]: ...
    def explain(self, risk: AccessRisk) -> dict: ...
```

`IdentityAccessGovernanceService` wraps the engine + `CertificationStore` as an
`AQService` (name `"iag_engine"`, depends on object store, KG, policy engine,
evidence/finding stores; health reflects their availability + config validity).

## 6. Computation (the reference model)

**Access paths.** `access_paths(identity)` uses `KG.subgraph`/`neighbors` over
`has_account`/`has_role`/`grants_entitlement` to build explainable identity →
entitlement paths.

**Risk analysis (`analyze_risk`).** Over in-scope objects (paged, tenant-scoped):
- **orphaned** = `account` with no `has_account` edge from any identity;
- **dormant** = account whose `attributes.last_used_at` is older than
  `dormant_days` (or missing → flagged);
- **over_privilege** = entitlements exceeding the `peer_baseline` / a Policy rule;
- **sod_conflict** = identity holding two entitlements that a Policy SoD rule
  forbids together (detected via reachable entitlement set + `PolicyEngine`);
- **privileged_unreviewed** = identity holding a `privileged_roles` role with no
  passing certification within the review window.
Each risk carries its `evidence_path` and `reason`. `truncated` inherits from KG.

**Certifications.** `open_certification` builds `ReviewItem`s from the scoped
access (one per identity/entitlement), seeded with a `recommendation` from risk
analysis. `decide_item` records the reviewer decision + an `EvidenceRecord`.
`complete_certification` closes the campaign; each `revoked` item becomes a
finding + a **proposed** Workflow remediation run (§0/D5) — never a direct
revoke.

## 7. Requirements

### Functional (testable)

- **FR-1** `access_paths` SHALL return explainable identity→entitlement paths computed via the Knowledge Graph (D1).
- **FR-2** `analyze_risk` SHALL detect orphaned, dormant, over-privilege, SoD-conflict, and privileged-unreviewed risks over the tenant-scoped scope, each with an `evidence_path` + `reason` (D3).
- **FR-3** SoD conflicts SHALL be detected using `PolicyEngine` rules over an identity's reachable entitlement set — not a bespoke rule language (D2).
- **FR-4** `analyze_risk` SHALL be deterministic and pure (no mutation); identical estate + config → identical report (excluding ids/timestamps).
- **FR-5** `open_certification` SHALL create a persisted `Certification` with one `ReviewItem` per in-scope access, each carrying a risk-derived `recommendation`.
- **FR-6** `decide_item` SHALL enforce optimistic `version`, record decider/decision/time, and write an `EvidenceRecord` per decision (D4).
- **FR-7** `complete_certification` SHALL, for each `revoked` item, raise a finding and a **proposed** Workflow remediation run; it SHALL NOT grant or revoke access directly (§0/D5).
- **FR-8** `risks_to_findings` SHALL raise a finding per risk (severity from the risk), optionally Mission-prioritized, with the access path as evidence.
- **FR-9** All operations SHALL be tenant-scoped; no cross-tenant identity/account/entitlement appears (D6).
- **FR-10** Reports/campaigns SHALL exhaust object-store pages, inherit KG bounds, and propagate KG `truncated`; object pagination SHALL NOT silently cap the estate (ECR-0030).
- **FR-11** Invalid config (`dormant_days ≤ 0`, unknown `privileged_roles`, `review_default_due_days ≤ 0`) SHALL raise `IAGConfigInvalid`.
- **FR-12** `CertificationStore` in-memory and Postgres implementations SHALL pass one contract suite.
- **FR-13** `IdentityAccessGovernanceService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (no direct mutation of access)** there is no code path in this engine that grants/revokes access or edits an identity/account/entitlement object; enforced by tests asserting delegation to Workflow.
- **NFR-2 (determinism)** identical inputs → identical risk report.
- **NFR-3 (bounded)** estate processed in bounded batches; inherits KG hard caps.
- **NFR-4 (portability & typing)** in-memory + Postgres `CertificationStore` pass one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Access paths via KG, explainable | `test_iag_access_paths` |
| AC-2 | Orphaned/dormant detection | `test_iag_orphaned_dormant` |
| AC-3 | Over-privilege detection | `test_iag_over_privilege` |
| AC-4 | SoD conflict via Policy rules | `test_iag_sod_conflict` |
| AC-5 | Privileged-unreviewed detection | `test_iag_privileged_unreviewed` |
| AC-6 | Risk analysis deterministic + pure | `test_iag_analyze_deterministic` |
| AC-7 | Certification created with review items | `test_iag_open_certification` |
| AC-8 | decide_item records evidence + version | `test_iag_decide_item_evidence` |
| AC-9 | complete → findings + proposed runs, no direct revoke | `test_iag_complete_delegates` |
| AC-10 | Engine never mutates access directly | `test_iag_no_direct_access_mutation` |
| AC-11 | risks_to_findings raises prioritized findings | `test_iag_risks_to_findings` |
| AC-12 | Tenant isolation | `test_iag_tenant_isolation` |
| AC-13 | truncated propagates from KG | `test_iag_truncation_propagates` |
| AC-14 | Invalid config rejected | `test_iag_config_invalid` |
| AC-15 | In-memory & Postgres CertificationStore pass one suite | `test_iag_cert_contract[inmemory]` / `[postgres]` |
| AC-16 | Registers as AQService with health | `test_iag_service_health` |
| AC-17 | Risk analysis and certification include identities/accounts on later ObjectStore pages | `test_iag_pages_full_scope[inmemory|postgres]`, `test_iag_certification_pages_full_scope[inmemory|postgres]` |

## 9. Error taxonomy (contributions)

`IAGConfigInvalid`, `CertificationNotFound`, `ReviewItemNotFound` (added to
`conventions.errors` + CONVENTIONS §9). Reuses `OptimisticConcurrencyConflict`,
`StoreUnavailable`, `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0011)

`aqelyn.iag.risk_detected`, `aqelyn.iag.certification_opened`,
`aqelyn.iag.item_decided`, `aqelyn.iag.certification_completed` — via
`register_iag_events()` (EA-0003 §7). (Archive uses `governance.sod.violation.
detected`; represented here as an `aqelyn.iag.risk_detected` with
`kind="sod_conflict"` to stay within the platform event namespace.)

## 11. Failure handling

- Invalid config → `IAGConfigInvalid` at construction; service `unavailable`.
- Dependency (object/KG/policy/store) unavailable → `StoreUnavailable`; service
  `degraded`; a partial risk report is marked incomplete, never a clean pass.
- A single risk-check error is recorded on that risk (flagged) and does not abort
  the whole analysis.
- `complete_certification` failing to propose a Workflow run SHALL leave the
  finding raised and surface the delegation failure — it SHALL NOT attempt a
  direct access change as a fallback.

## 12. Dependencies & consumers

- **Depends on:** EA-0002 objects/relationships; EA-0005 `KnowledgeGraph`;
  EA-0009 `PolicyEngine` (SoD/access rules); EA-0004 `EvidenceStore.add`;
  EA-0007 (optional prioritization); the Finding model + pipeline; **EA-0008
  Workflow (all access change proposed + gated there)**; EA-0001 `AQService`.
- **Consumed by:** access-review/certification UI (reviewer inbox, campaigns —
  **WCAG 2.2 AA** applies to this surface); EA-0010 governance reporting;
  auditors (certification evidence packages).

## 13. Resolved / deferred decisions

- **Detect-and-certify, delegate all change** (§0) is the binding safety posture;
  it may not be weakened to let this engine mutate access directly.
- **SoD via Policy rules**, not a bespoke engine — one rule semantics.
- **Provisioning / access-request *fulfilment*** (actually creating accounts) is
  out of scope — those are Workflow actions from their own connectors; this
  engine governs and reviews, it does not provision.
- **Peer-group / ML entitlement baselining** is deferred; the reference
  over-privilege check uses explicit baseline/policy, extensible later without
  interface change.
