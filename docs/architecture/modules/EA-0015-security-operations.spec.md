# EA-0015 — Security Operations (SOC) Engine — Implementation Specification

**Realizes:** EA-0015 / IS-015 (supersedes the placeholder `archive/EA-0015/EA-0015_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), the Finding model (alerts), EA-0008 (response = gated Workflow runs), EA-0013 (risk context), EA-0014 (threat matches), EA-0005 (investigation pivots), EA-0007 (prioritization + owner notify), EA-0004 (case-timeline evidence)
**Consumed by:** the analyst workspace + executive dashboard UI (queues, cases, timelines — a WCAG 2.2 AA surface), reporting, auditors (incident/case evidence packages)
**Status:** Accepted
**Change control:** ECR-0030 (hunts follow object pages until their result bound is satisfied)
**Build milestone:** C-012 (see `C-012_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 0. Safety boundary (read first)

The SOC Engine is the **operational layer where analysts work** — it correlates,
triages, investigates, and **coordinates response**. It does **not** execute
response actions itself:

- **Response is coordination, not execution.** A SOC response playbook
  **proposes a gated Workflow run (EA-0008)** for each action (isolate host,
  disable account, block indicator) — approval, capability, confirm-token,
  evidence, and rollback all remain EA-0008's. "Response Coordinator" here means
  *orchestrate + track proposed runs*, never a direct effect. The one thing SOC
  does directly is manage its **own** records (alerts/incidents/cases) and their
  timelines.
- **Detect/triage/investigate is read-analysis** over the estate and the outputs
  of the ten engines: deterministic where scored, explainable, tenant-scoped,
  evidence-recorded.
- **Case timelines are evidence-bound.** Every material step in an incident/case
  (created, correlated, assigned, action-proposed, resolved) writes an
  `EvidenceRecord` (EA-0004), so an investigation is fully auditable — "how
  AQELYN knows" for operations.
- No new authorization surface: all "can I act?" stays with EA-0008/EA-0009.

## 1. Purpose

Ten engines produce findings, risks, and threat matches; the SOC Engine is where
those become **operational work**: raw signals are correlated into **alerts**,
related alerts are grouped into **incidents**, incidents become **cases** an
analyst owns and works, with **investigation** (graph pivots, evidence
assembly), **threat hunting** (hypothesis-driven queries), and **coordinated
response** (proposing gated remediation). It answers *what's happening right now,
what matters most, who owns it, and what are we doing about it — provably.*

## 2. Design decisions

- **D1 — Alerts wrap signals, they don't duplicate them.** An `Alert` references
  a finding / threat match / risk (by id + evidence), adding triage state. The
  underlying signal stays the source of truth.
- **D2 — Correlation groups alerts into incidents deterministically.** A
  configurable correlation key (shared asset, actor, campaign, time window)
  groups alerts; identical inputs → identical grouping. Explainable.
- **D3 — Incidents/cases are stateful, versioned, evidence-bound records.**
  Lifecycle (`new → triaged → investigating → contained → resolved → closed`)
  with optimistic version; each transition + material step writes evidence (§0).
- **D4 — Prioritization reuses Mission + Risk.** Incident priority derives from
  its alerts' mission impact (EA-0007) and risk score (EA-0013) — not a new
  scoring model.
- **D5 — Investigation reuses the Knowledge Graph.** Pivots ("what else touches
  this asset/actor?") are KG traversals; results attach to the case as evidence.
- **D6 — Response is delegated (§0).** A response playbook proposes EA-0008
  Workflow runs; the SOC engine tracks their status but never executes.
- **D7 — Threat hunting is bounded, saved queries.** Hypothesis queries run over
  the object/finding/threat data with KG support; bounded and tenant-scoped.
- **D8 — Registered as an `AQService`;** tenant-scoped throughout.

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Alert** | A triageable wrapper over a finding / threat match / risk, with state. |
| **Incident** | A correlated group of alerts representing one situation. |
| **Case** | An analyst-owned incident under active work, with assignment + timeline. |
| **Investigation** | Evidence + KG pivots assembled on a case. |
| **Threat hunt** | A saved, hypothesis-driven query over the estate/signals. |
| **Response** | Coordinated remediation — **proposed** gated Workflow runs (§0). |
| **Timeline** | The evidence-bound ordered history of a case. |

## 4. Types

```
AlertState = "new" | "triaged" | "suppressed" | "escalated"
Alert   = { id, tenant_id, source_kind: "finding"|"threat_match"|"risk",
            source_ref: str, evidence_id: str | null, severity: str,
            state: AlertState, correlation_key: str | null,
            created_at: datetime, version: int }

IncidentStatus = "new"|"triaged"|"investigating"|"contained"|"resolved"|"closed"
Incident = { id, tenant_id, title, status: IncidentStatus, priority: float,
             alert_ids: list[str], affected_object_ids: list[str],
             top_mission_id: str | null, risk_score: float | null,
             assignee: ActorRef | null, timeline: list[TimelineEntry],
             created_by: ActorRef, created_at, updated_at, version: int }

TimelineEntry = { at: datetime, actor: ActorRef, kind: str, detail: dict,
                  evidence_id: str | null }
ResponseAction = { action_type: str, inputs: dict, workflow_run_id: str | null,
                   status: str }                          # status mirrors the EA-0008 run
Hunt    = { id, tenant_id, name, hypothesis: str, query: dict, saved_by: ActorRef }
SOCConfig = { correlation: dict, incident_window_seconds: int, batch_size: int }
```

Reuses the Finding model, EA-0013/0014 outputs, EA-0005 `Path`, `ActorRef`,
EA-0004 evidence.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class SOCStore(Protocol):                                  # alerts + incidents/cases
    async def upsert_alert(self, alert: Alert) -> Alert: ...
    async def upsert_incident(self, incident: Incident) -> Incident: ...   # optimistic version
    async def get_incident(self, incident_id: str) -> Incident | None: ...
    async def query_incidents(self, *, tenant_id: str | None,
                              status: Sequence[str] | None = None, limit: int = 100) -> list[Incident]: ...

class SecurityOperationsEngine(Protocol):
    async def intake(self, *, tenant_id: str | None) -> list[Alert]: ...    # findings/threat/risk -> alerts (D1)
    async def correlate(self, *, tenant_id: str | None) -> list[Incident]: ...  # alerts -> incidents (D2/D4)
    async def assign(self, incident_id: str, *, to: ActorRef, by: ActorRef,
                     expected_version: int) -> Incident: ...                 # evidence-bound (D3)
    async def investigate(self, incident_id: str, *, pivot: dict, by: ActorRef) -> Incident: ...  # KG (D5)
    async def transition(self, incident_id: str, to_status: str, *, by: ActorRef,
                         note: str | None, expected_version: int) -> Incident: ...
    async def propose_response(self, incident_id: str, *, actions: Sequence[ResponseAction],
                               by: ActorRef) -> list[str]: ...               # -> gated Workflow runs (§0/D6)
    async def hunt(self, hunt: Hunt) -> list[dict]: ...                      # bounded query (D7)
    def explain(self, incident: Incident) -> dict: ...
```

`SecurityOperationsService` wraps the engine + `SOCStore` as an `AQService`
(name `"soc_engine"`, depends on finding/risk/threat/mission/kg/evidence/workflow;
health reflects their availability + config validity).

## 6. Computation (the reference model)

**Intake.** Pull new findings (`FindingStore.query`), threat matches (EA-0014),
and risks (EA-0013) into `Alert`s (dedupe by `source_ref`), carrying evidence
(D1).

**Correlate.** Group alerts by `correlation_key` (shared asset/actor/campaign
within `incident_window_seconds`) into `Incident`s; priority from Mission impact
(EA-0007) + risk score (EA-0013) (D2/D4). Deterministic. Emits
`aqelyn.soc.incident_created`.

**Work a case.** `assign`/`transition`/`investigate` update the incident with
optimistic version; each writes a `TimelineEntry` + `EvidenceRecord` (D3).
`investigate` runs a KG pivot and attaches results as evidence (D5).

**Respond.** `propose_response` creates, per action, a **proposed** EA-0008
Workflow run and records a `ResponseAction` tracking its status; nothing executes
here (§0/D6). The incident timeline records each proposal.

**Hunt.** `hunt` runs a bounded, tenant-scoped saved query over objects/findings/
threat data (KG-assisted), returning matches; never mutates. Object pages are
followed until the requested match limit is filled or the filtered estate is
exhausted, so a page containing only post-query attribute non-matches cannot
hide a later match (ECR-0030).

## 7. Requirements

### Functional (testable)

- **FR-1** `intake` SHALL create `Alert`s referencing findings/threat-matches/risks (by id + evidence), deduped by `source_ref`, without duplicating the underlying signal (D1).
- **FR-2** `correlate` SHALL group alerts into incidents by the configured correlation key/window, deterministically (identical inputs → identical incidents) (D2).
- **FR-3** Incident priority SHALL derive from Mission impact (EA-0007) + risk score (EA-0013); a higher-mission or higher-risk incident SHALL rank no lower (D4).
- **FR-4** Incidents/cases SHALL be versioned; `assign`/`transition`/`investigate` SHALL enforce optimistic `version` and write a `TimelineEntry` + `EvidenceRecord` (D3).
- **FR-5** `investigate` SHALL run a Knowledge-Graph pivot and attach the result to the case as evidence (D5).
- **FR-6** `propose_response` SHALL create a **proposed** EA-0008 Workflow run per action and SHALL NOT execute any action directly (§0/D6); it SHALL track each run's status via `ResponseAction`.
- **FR-7** Every material case step SHALL be evidence-bound; a case SHALL reconstruct fully from its timeline + evidence (D3).
- **FR-8** `hunt` SHALL run bounded, tenant-scoped queries, follow object pages until its match limit is filled or the estate is exhausted, and SHALL NOT mutate any record (D7/ECR-0030).
- **FR-9** All operations SHALL be tenant-scoped; no cross-tenant alert/incident/asset appears (D8).
- **FR-10** The engine SHALL mutate only its own alert/incident/case records (+ evidence + proposed runs); it SHALL NOT mutate findings/objects/risks or execute actions.
- **FR-11** Invalid config (`incident_window_seconds ≤ 0`, `batch_size ≤ 0`, malformed correlation) SHALL raise `SOCConfigInvalid`.
- **FR-12** `SOCStore` in-memory and Postgres implementations SHALL pass one contract suite.
- **FR-13** `SecurityOperationsService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (no direct action)** no code path executes a response; response is proposed via Workflow (enforced by test).
- **NFR-2 (auditability)** every incident/case reconstructs fully from its timeline + evidence; no material step lacks an evidence record.
- **NFR-3 (bounded)** intake/correlation/hunt process in bounded batches; inherits KG caps.
- **NFR-4 (portability & typing)** in-memory + Postgres `SOCStore` pass one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Intake wraps signals as alerts, deduped | `test_soc_intake_alerts` |
| AC-2 | Correlation groups alerts deterministically | `test_soc_correlate_incidents` |
| AC-3 | Priority from Mission + Risk, monotonic | `test_soc_priority` |
| AC-4 | Incident transitions versioned + evidence | `test_soc_transition_evidence` |
| AC-5 | Assign writes timeline + evidence | `test_soc_assign` |
| AC-6 | Investigate runs KG pivot, attaches evidence | `test_soc_investigate_pivot` |
| AC-7 | Response proposes Workflow runs, no direct action | `test_soc_response_delegates` |
| AC-8 | Response tracks run status | `test_soc_response_status` |
| AC-9 | Case reconstructs from timeline + evidence | `test_soc_case_auditable` |
| AC-10 | Hunt bounded, read-only | `test_soc_hunt_readonly` |
| AC-11 | Engine mutates only its own records | `test_soc_no_side_effects` |
| AC-12 | Tenant isolation | `test_soc_tenant_isolation` |
| AC-13 | Invalid config rejected | `test_soc_config_invalid` |
| AC-14 | In-memory & Postgres SOCStore pass one suite | `test_soc_store_contract[inmemory]` / `[postgres]` |
| AC-15 | Registers as AQService with health | `test_soc_service_health` |
| AC-16 | Hunt reaches a matching object after a non-matching object page | `test_soc_hunt_pages_for_late_match[inmemory]` / `[postgres]` |

## 9. Error taxonomy (contributions)

`SOCConfigInvalid`, `IncidentNotFound`, `AlertNotFound` (added to
`conventions.errors` + CONVENTIONS §9). Reuses `OptimisticConcurrencyConflict`,
`StoreUnavailable`, `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0015)

`aqelyn.soc.alert_raised`, `aqelyn.soc.incident_created`,
`aqelyn.soc.incident_status_changed`, `aqelyn.soc.response_proposed` — via
`register_soc_events()` (EA-0003 §7). (Archive uses `incident.created`; mapped
into the platform namespace as `aqelyn.soc.incident_created`.)

## 11. Failure handling

- Invalid config → `SOCConfigInvalid` at construction; service `unavailable`.
- Dependency unavailable → `StoreUnavailable`; service `degraded`; partial intake/
  correlation marked incomplete, never a clean "no incidents".
- A single alert that fails to correlate is recorded unlinked (flagged); the batch
  continues.
- `propose_response` failing to create a Workflow run leaves the incident +
  timeline entry recorded and surfaces the delegation failure; it SHALL NOT
  attempt a direct action as a fallback.

## 12. Dependencies & consumers

- **Depends on:** the Finding model + `FindingStore.query`; EA-0013 risks;
  EA-0014 threat matches; EA-0007 `MissionEngine`; EA-0005 `KnowledgeGraph`;
  EA-0004 `EvidenceStore.add`; **EA-0008 Workflow (all response proposed +
  gated)**; EA-0001 `AQService`.
- **Consumed by:** the analyst workspace + executive dashboard UI (alert/incident
  queues, case timelines, hunt workbench — **WCAG 2.2 AA** applies, and this is a
  primary surface for the "world-best, user-friendly" goal); reporting; auditors
  (incident/case evidence packages).

## 13. Resolved / deferred decisions

- **Response is coordination, not execution** (§0) — binding; SOC proposes gated
  Workflow runs and never acts directly.
- **Alerts wrap, priority reuses Mission+Risk, investigation reuses KG** — no new
  scoring or traversal; compose the shipped engines.
- **Notifications / on-call paging** (the archive's `notify_mission_owner`) are
  proposed Workflow actions (a notify handler), not a bespoke SOC notifier.
- **The analyst UI** is a separate surface (UX turn, later EA); this spec provides
  the operational data + timelines it renders, and names it as the flagship
  WCAG 2.2 AA + design-excellence surface.
