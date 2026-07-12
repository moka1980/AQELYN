# Finding Model — Implementation Specification

**Realizes:** Charter v2 "Finding Communication Standard" + "Progressive Detail Model" (the product's core output object)
**Depends on:** ADR-0001, EA-0002 (affected object refs, tenancy), EA-0003 (finding events), EA-0004 (evidence refs), CONVENTIONS
**Consumed by:** every assessment engine (raises findings), UI/reporting (EA-0059), automation/remediation (EA-0032+)
**Status:** Accepted
**Definition of Ready:** see §11

---

## 1. Purpose

A **Finding** is what AQELYN ultimately delivers to a user: a single security
issue, explained so a non-expert understands it and an expert can act on it,
**backed by evidence**. This model encodes the charter's permanent product
principle — *every finding must be understandable by a non-expert and actionable
by an expert* — as a concrete, validated data contract, so no engine can emit a
finding that omits the explanation, the evidence, the action, or the expected
outcome.

## 2. Scope

**In scope:** the finding record, severity model, lifecycle/status, the
required explanatory fields, evidence + affected-asset linkage, remediation +
automation eligibility, progressive-detail mapping, deduplication, and the
`FindingStore` interface + schema.

**Out of scope:** detection logic (each engine's EA), report rendering
(EA-0059), and remediation execution (EA-0032). Prioritization *scoring inputs*
are defined here; cross-finding risk correlation is a later engine.

## 3. Charter mapping (non-negotiable fields)

The Charter's Required Finding Fields map 1:1 to this model:

| Charter field | Model field |
|---|---|
| Title | `title` |
| Severity | `severity` + `severity_score` |
| What Happened | `what_happened` |
| Why It Matters | `why_it_matters` |
| Evidence | `evidence_ids` (≥1, EA-0004) |
| Affected Assets | `affected_object_ids` (EA-0002) |
| Recommended Action | `remediation` |
| Fix Difficulty | `remediation.difficulty` |
| Automation Eligibility | `automation` |
| Expert Details | `expert_details` |
| Audit Trail | `audit` |

Plus two charter requirements made explicit: **How AQELYN knows** →
`how_determined`; **Expected outcome after remediation** →
`remediation.expected_outcome`; **Risk of inaction** → `risk_of_inaction`.

## 4. Progressive detail (Charter Principle 5)

The one record serves all six levels without duplicating data:

| Level | Question | Field(s) |
|---|---|---|
| 1 Summary | What is the problem? | `title`, `severity` |
| 2 Explanation | Why does it matter? | `what_happened`, `why_it_matters` |
| 3 Evidence | What proves it? | `evidence_ids` → EA-0004 |
| 4 Technical | Exact cause? | `expert_details`, `affected_object_ids` |
| 5 Remediation | What to do? | `remediation`, `automation` |
| 6 Audit | What changed/when? | `audit`, status history |

## 5. Design decisions

- **D1 — Explanation is mandatory, not optional.** `what_happened`,
  `why_it_matters`, `how_determined`, `remediation.summary`, and
  `remediation.expected_outcome` are required; a finding missing any is rejected
  at write. This enforces "explain before recommend" structurally.
- **D2 — Evidence is mandatory.** `evidence_ids` MUST contain ≥1 valid `evd_`
  reference (`EvidenceRequired`). No finding without proof.
- **D3 — Findings are deduplicated by `dedup_key`.** Re-detecting the same issue
  updates the existing finding (bumps `last_detected_at`, adds evidence) rather
  than creating duplicates — the charter's "too many alerts" problem.
- **D4 — Lifecycle is explicit and audited.** Status transitions are constrained
  and each writes an audit entry.
- **D5 — Severity has both a label and a score**, so UX shows a word and
  prioritization uses a number.

## 6. The finding record

| Field | Type | Req | Description |
|---|---|---|---|
| `id` | ID (`fnd_…`) | yes | Immutable typed ID with UUIDv7 payload. |
| `tenant_id` | str \| null | no | Owning tenant; NULL local; non-null validates as UUID string. |
| `finding_type` | string | yes | Registered type `aqelyn.finding.<domain>.<slug>`. |
| `schema_version` | int | yes | Type schema version. |
| `dedup_key` | string | yes | Stable identity of the issue (for D3). |
| `title` | string | yes | Plain-language summary (Level 1). |
| `severity` | enum | yes | `info`\|`low`\|`medium`\|`high`\|`critical`. |
| `severity_score` | float 0..100 | yes | Numeric priority. |
| `status` | enum | yes | `open`\|`acknowledged`\|`in_progress`\|`resolved`\|`risk_accepted`\|`false_positive`. |
| `what_happened` | text | yes | Plain explanation (Level 2). |
| `why_it_matters` | text | yes | Impact in plain language (Level 2). |
| `how_determined` | text | yes | How AQELYN concluded it (Charter "how AQELYN knows"). |
| `risk_of_inaction` | text | yes | What happens if ignored. |
| `evidence_ids` | list<ID `evd_`> | yes | ≥1 supporting evidence (Level 3, D2). |
| `affected_object_ids` | list<ID `obj_`> | yes | Affected assets/identities (Level 4). |
| `expert_details` | object | no | Technical expansion (Level 4): config, rule, raw refs. |
| `remediation` | Remediation | yes | Recommended action (Level 5). |
| `automation` | Automation | yes | Whether AQELYN can safely fix it (Level 5). |
| `confidence` | float 0..1 | yes | Confidence the finding is real (not a false positive). |
| `source_engine` | string | yes | Engine that raised it. |
| `correlation_id` | string | no | Groups related findings. |
| `first_detected_at` | timestamp | yes | First seen. |
| `last_detected_at` | timestamp | yes | Most recent detection. |
| `resolved_at` | timestamp \| null | no | When resolved. |
| `audit` | list<AuditEntry> | yes | Status/edit history (Level 6). |
| `version` | int | yes | Optimistic concurrency. |

```
Remediation = { summary: str, steps: list[str], difficulty: "trivial"|"easy"|"moderate"|"hard",
                estimated_effort: str | null, expected_outcome: str,
                references: list[str] }
Automation  = { eligibility: "none"|"assisted"|"automatic",
                action_ref: str | null, requires_approval: bool, risk_note: str | null }
AuditEntry  = { at: datetime, actor: ActorRef, action: str, from_status: str | null,
                to_status: str | null, note: str | null }
```

## 6a. Events registered by this spec

This spec owns and registers the following event types in the EA-0003 registry:

| event_type | schema_version | Emitted when | Key payload |
|---|---|---|---|
| `aqelyn.finding.raised` | 1 | A new finding is created | `{ finding_type, severity }`, `subject.finding_id` set |
| `aqelyn.finding.status_changed` | 1 | Status transition | `{ from, to }` |
| `aqelyn.finding.regressed` | 1 | A resolved finding reopens on re-detection | `{ dedup_key }` |

## 7. Lifecycle

```
open ──ack──▶ acknowledged ──start──▶ in_progress ──fix──▶ resolved
  │                │                        │
  ├── risk_accepted (terminal-ish, reopenable)
  └── false_positive (terminal-ish, reopenable)
resolved ──regress──▶ open   (re-detection of a resolved issue reopens it)
```

Transitions are validated; illegal transitions raise `InvalidFindingTransition`.
Every transition appends an `AuditEntry` and emits
`aqelyn.finding.status_changed`.

## 8. Deduplication & re-detection

- On `raise`, the store matches on `(tenant_id, finding_type, dedup_key)`.
- Match + finding open/ack/in_progress → update: `last_detected_at`, union
  `evidence_ids`/`affected_object_ids`, keep status.
- Match + finding resolved → **reopen** (status→`open`, audit entry,
  `aqelyn.finding.regressed`).
- No match → create new + emit `aqelyn.finding.raised`.

## 9. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime
from pydantic import BaseModel, Field
# ActorRef from EA-0002

class Remediation(BaseModel):
    summary: str
    steps: list[str] = Field(default_factory=list)
    difficulty: str
    estimated_effort: str | None = None
    expected_outcome: str
    references: list[str] = Field(default_factory=list)

class Automation(BaseModel):
    eligibility: str                 # none | assisted | automatic
    action_ref: str | None = None
    requires_approval: bool = True
    risk_note: str | None = None

class AuditEntry(BaseModel):
    at: datetime; actor: "ActorRef"; action: str
    from_status: str | None = None; to_status: str | None = None; note: str | None = None

class Finding(BaseModel):
    id: str
    tenant_id: str | None = None
    finding_type: str
    schema_version: int
    dedup_key: str
    title: str
    severity: str
    severity_score: float
    status: str = "open"
    what_happened: str
    why_it_matters: str
    how_determined: str
    risk_of_inaction: str
    evidence_ids: list[str]                       # >= 1 (D2)
    affected_object_ids: list[str] = Field(default_factory=list)
    expert_details: dict | None = None
    remediation: Remediation
    automation: Automation
    confidence: float = 1.0
    source_engine: str
    correlation_id: str | None = None
    first_detected_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None = None
    audit: list[AuditEntry] = Field(default_factory=list)
    version: int = 1

class FindingQuery(BaseModel):
    tenant_id: str | None = None
    status: Sequence[str] | None = None
    severity: Sequence[str] | None = None
    finding_type: str | None = None
    affected_object_id: str | None = None
    limit: int = 100
    cursor: str | None = None

class FindingStore(Protocol):
    async def raise_finding(self, f: Finding) -> Finding: ...          # dedup/reopen per §8
    async def get(self, finding_id: str) -> Finding | None: ...
    async def query(self, q: FindingQuery) -> tuple[list[Finding], str | None]: ...
    async def transition(self, finding_id: str, to_status: str, *, by: "ActorRef",
                        note: str | None, expected_version: int) -> Finding: ...
    async def add_evidence(self, finding_id: str, evidence_ids: list[str], *,
                        by: "ActorRef", expected_version: int) -> Finding: ...
```

## 10. Persistence (PostgreSQL 16)

```sql
CREATE TABLE aq_finding (
    id                 text PRIMARY KEY,
    tenant_id          text NULL,
    finding_type       text NOT NULL,
    schema_version     int  NOT NULL,
    dedup_key          text NOT NULL,
    title              text NOT NULL,
    severity           text NOT NULL CHECK (severity IN ('info','low','medium','high','critical')),
    severity_score     double precision NOT NULL CHECK (severity_score >= 0 AND severity_score <= 100),
    status             text NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open','acknowledged','in_progress','resolved','risk_accepted','false_positive')),
    what_happened      text NOT NULL,
    why_it_matters     text NOT NULL,
    how_determined     text NOT NULL,
    risk_of_inaction   text NOT NULL,
    expert_details     jsonb NULL,
    remediation        jsonb NOT NULL,
    automation         jsonb NOT NULL,
    confidence         double precision NOT NULL DEFAULT 1.0,
    source_engine      text NOT NULL,
    correlation_id     text NULL,
    first_detected_at  timestamptz NOT NULL,
    last_detected_at   timestamptz NOT NULL,
    resolved_at        timestamptz NULL,
    version            int NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX uq_finding_dedup ON aq_finding (tenant_id, finding_type, dedup_key);
CREATE INDEX ix_finding_status_sev ON aq_finding (tenant_id, status, severity_score DESC);

CREATE TABLE aq_finding_evidence (
    finding_id  text NOT NULL REFERENCES aq_finding(id),
    evidence_id text NOT NULL,
    PRIMARY KEY (finding_id, evidence_id)
);
CREATE TABLE aq_finding_asset (
    finding_id text NOT NULL REFERENCES aq_finding(id),
    object_id  text NOT NULL,
    PRIMARY KEY (finding_id, object_id)
);
CREATE TABLE aq_finding_audit (
    seq         bigserial PRIMARY KEY,
    finding_id  text NOT NULL REFERENCES aq_finding(id),
    at          timestamptz NOT NULL DEFAULT now(),
    actor       jsonb NOT NULL,
    action      text NOT NULL,
    from_status text NULL,
    to_status   text NULL,
    note        text NULL
);
```

## 11. Requirements & Acceptance (Definition of Ready)

### Functional

- **FR-1** A finding missing any required explanatory field (`what_happened`, `why_it_matters`, `how_determined`, `remediation.summary`, `remediation.expected_outcome`, `risk_of_inaction`) SHALL be rejected (D1).
- **FR-2** A finding with zero `evidence_ids` SHALL be rejected (`EvidenceRequired`, D2).
- **FR-3** `raise_finding` SHALL dedup on `(tenant_id, finding_type, dedup_key)` and update/reopen instead of duplicating (§8).
- **FR-4** Re-detection of a `resolved` finding SHALL reopen it and emit `aqelyn.finding.regressed`.
- **FR-5** Status transitions SHALL be validated; illegal ones raise `InvalidFindingTransition` (§7).
- **FR-6** Every transition SHALL append an `AuditEntry` and emit `aqelyn.finding.status_changed`.
- **FR-7** Creating a new finding SHALL emit `aqelyn.finding.raised` with `subject.finding_id` set.
- **FR-8** `severity` and `severity_score` SHALL both be present and within range.
- **FR-9** All `evidence_ids` SHALL reference existing evidence; dangling refs rejected.
- **FR-10** Findings SHALL be tenant-scoped per CONVENTIONS; cross-tenant refs rejected.

### Non-functional

- **NFR-1** `raise_finding` p95 < 20 ms; `query` by (status, severity) uses the index, p95 < 30 ms at 1M findings.
- **NFR-2** Dedup guarantees at most one live finding per `(tenant, type, dedup_key)`.
- **NFR-3** In-memory + Postgres `FindingStore` pass one contract suite; `mypy --strict` + `ruff` clean.

### Acceptance ↔ Tests

| # | Criterion | Test |
|---|---|---|
| AC-1 | Missing explanation field rejected | `test_finding_requires_explanation` |
| AC-2 | No-evidence finding rejected | `test_finding_requires_evidence` |
| AC-3 | Dedup updates instead of duplicating | `test_finding_dedup` |
| AC-4 | Resolved finding reopens on re-detection | `test_finding_regression_reopen` |
| AC-5 | Illegal transition rejected | `test_finding_invalid_transition` |
| AC-6 | Transition writes audit + event | `test_finding_transition_audited` |
| AC-7 | New finding emits `raised` | `test_finding_raised_event` |
| AC-8 | Dangling evidence ref rejected | `test_finding_evidence_exists` |
| AC-9 | Tenant isolation enforced | `test_finding_tenant_isolation` |
| AC-10 | In-memory & Postgres stores pass one suite | `test_finding_store_contract[inmemory]` / `[postgres]` |

## 12. Error taxonomy (contributions)

`FindingNotFound`, `InvalidFindingTransition`, `EvidenceRequired`
(see CONVENTIONS §9).

## 13. Dependencies & consumers

- **Depends on:** ADR-0001, EA-0002, EA-0003, EA-0004, CONVENTIONS.
- **Consumed by:** all assessment engines (raise findings); EA-0059 UI/reports
  render the six levels; EA-0032 automation reads `automation`.
