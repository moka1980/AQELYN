# EA-0019 — Security Data Lake & Telemetry Platform — Implementation Specification

**Realizes:** EA-0019 / IS-019 (supersedes the placeholder `archive/EA-0019/EA-0019_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0004 (`BlobStore` for raw payloads; evidence refs), EA-0009 (structured predicates for queries + retention rules), EA-0008 (ad-hoc deletion is a gated destructive action)
**Consumed by:** EA-0017 Detection (telemetry is what it detects over), EA-0015 SOC (investigation queries), EA-0016 Forensics (telemetry as artifact context), EA-0010 (retention/compliance evidence), the query/dataset UI (a WCAG 2.2 AA surface)
**Status:** Accepted
**Build milestone:** C-016 (see `C-016_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 0. Scope & safety boundaries (read first)

This is the platform's **first infrastructure module** and its **first module that
deletes**. Four boundaries govern it:

- **S1 — Ingestion accepts handed-in records; it does not collect.** `ingest`
  consumes `TelemetryRecord`s already delivered to the platform. This engine opens
  no sockets, runs no agents, and holds no credentials — **collectors/agents are a
  later connector EA** (the same line held for EA-0014 feeds and EA-0016
  acquisitions). The `TelemetryRecord` seam is the handoff.
- **S2 — The lake is not a second object store, event log, or evidence store.**
  It holds **high-volume raw telemetry** — the material too voluminous and
  semi-structured to be objects. Entities stay in EA-0002, platform events in
  EA-0003, and **integrity/chain-of-custody stays in EA-0004**. A telemetry record
  may be *referenced* by evidence; it never replaces the evidence backbone.
- **S3 — Deletion is fail-closed.** Retention expiry is a routine, policy-defined
  lifecycle operation (you cannot ask a human to approve every log line's
  expiry), but it is **hard-bounded**: a record SHALL NOT be deleted if it is
  under **legal hold** or **referenced by evidence, a finding, or a case**.
  Retention checks references and **skips + flags** rather than deleting on doubt.
  **Ad-hoc or bulk deletion outside policy is a destructive action → proposed,
  gated EA-0008 Workflow run** — never performed here. Every expiry is itself
  recorded (what, when, under which policy).
- **S4 — Queries are structured, bounded, and privacy-aware.** Callers pass
  **structured predicates** (the EA-0009 `Condition` model) — never raw SQL or
  query strings; no `eval`. Every query is tenant-scoped, row-limited, and
  **redacted per field classification** before results leave the engine.

Otherwise: deterministic, explainable, tenant-scoped. No new authorization
surface (Policy still decides; this engine enforces classification + scope).

## 1. Storage substrate & the deferred backend decision

Per ADR-0001 the platform is local-first on PostgreSQL. This spec therefore
realizes the lake over the **existing substrate**: normalized records in
partitioned PostgreSQL tables, raw payloads by reference in the EA-0004
`BlobStore`. The `DataLake` interface is deliberately backend-agnostic so a
purpose-built backend (columnar/object-store/lakehouse) can be substituted
**without changing callers** — exactly the pattern EA-0005 used for a graph
engine.

> **ADR flag.** Telemetry volume + retention is the first workload that will
> plausibly outgrow a local PostgreSQL. When real volumes are known, a
> **backend/deployment ADR refresh** should decide the production substrate. That
> decision is deferred here, not made implicitly; nothing in this spec assumes a
> particular store beyond the interface.

## 2. Purpose

Detection, SOC, and forensics all need the same thing: **the raw record of what
happened** — logs, flows, process events — retained long enough to investigate,
searchable fast enough to be useful, governed tightly enough to be legal. The
Data Lake is that substrate: it validates and normalizes handed-in telemetry into
governed **datasets**, indexes them for **bounded structured query**, classifies
fields so **PII is redacted by default**, and enforces **retention and archival**
without ever destroying something that is being relied upon.

## 3. Design decisions

- **D1 — Datasets are governed, schema'd, and classified.** A `Dataset` declares
  its schema and **per-field classification** (`public|internal|pii|secret`);
  classification drives redaction (S4) and retention (S3).
- **D2 — Normalize + validate at intake; quarantine malformed.** Untrusted input
  is validated against the dataset schema; failures are quarantined (flagged),
  never silently accepted or dropped.
- **D3 — Raw payload by reference.** Large/raw content goes to `BlobStore`
  (EA-0004) as a `BlobRef`; the record holds normalized fields + the ref
  (bounded memory).
- **D4 — Structured, bounded queries** (S4): EA-0009 `Condition` filters +
  explicit time range + `limit`; results carry `truncated` and
  `redacted_fields`.
- **D5 — Retention is declarative and fail-closed** (S3); **archive is tiering,
  not deletion** — an `ArchiveRecord` moves records to cold storage with a
  verifiable hash and can be restored.
- **D6 — Deterministic + evidence-recorded:** retention runs and archive
  operations write an `EvidenceRecord` (EA-0004) so data-lifecycle actions are
  auditable — the Charter's proof bar applied to data governance.
- **D7 — Registered as an `AQService`;** tenant-scoped, bounded batches.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Telemetry record** | One handed-in, normalized observation in a dataset (S1). |
| **Dataset** | A governed collection: schema + field classifications + retention policy. |
| **Classification** | Per-field sensitivity (`public|internal|pii|secret`) driving redaction + retention. |
| **Index** | A dataset index enabling bounded query on given fields. |
| **Retention policy** | Declarative TTL/archive rules; fail-closed on hold/reference (S3). |
| **Legal hold** | A flag that makes records undeletable regardless of TTL. |
| **Archive record** | A verifiable cold-tier export of a record range (tiering, not deletion). |

## 5. Types

```
Classification = "public" | "internal" | "pii" | "secret"

Dataset  = { name: str, tenant_id: str | null, schema: dict,          # field -> type
             classifications: dict[str, Classification],
             retention_policy_id: str | null, indexed_fields: list[str],
             set_by: ActorRef, set_at: datetime, version: int }

TelemetryRecord = { id, tenant_id, dataset: str, source_id: str,
                    occurred_at: datetime, ingested_at: datetime,
                    fields: dict,                        # normalized, schema-validated
                    raw_ref: "BlobRef | null",           # D3
                    schema_version: int,
                    retention_state: "active"|"archived"|"expired",
                    legal_hold: bool = False,
                    evidence_id: str | null }

RetentionPolicy = { id, dataset: str, tenant_id: str | null,
                    ttl_days: int | null, archive_after_days: int | null,
                    condition: "Condition | null",       # EA-0009 model
                    set_by: ActorRef, version: int }

Query    = { dataset: str, tenant_id: str | null, filter: "Condition | null",
             since: datetime | null, until: datetime | null,
             fields: list[str] | null, limit: int }      # S4
QueryResult = { rows: list[dict], count: int, truncated: bool,
                redacted_fields: list[str] }

ArchiveRecord = { id, dataset, tenant_id, range: dict, location: "BlobRef",
                  record_count: int, content_hash: str, archived_at: datetime,
                  evidence_id: str }
RetentionReport = { dataset, evaluated: int, archived: int, expired: int,
                    skipped_held: int, skipped_referenced: int,      # S3 transparency
                    evidence_id: str, reason: str }
Quarantine = { source_id, reason, received_at, raw_ref: "BlobRef | null" }
LakeConfig = { batch_size: int, max_query_rows: int, default_limit: int }
```

Reuses EA-0004 `BlobRef`, EA-0009 `Condition`, `ActorRef`.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class DatasetCatalog(Protocol):
    async def register(self, dataset: Dataset) -> Dataset: ...      # validates schema+classifications
    async def get(self, name: str, *, tenant_id: str | None) -> Dataset | None: ...
    async def list(self, *, tenant_id: str | None) -> list[Dataset]: ...

class DataLake(Protocol):                                            # backend-agnostic (§1)
    async def ingest(self, records: Sequence[TelemetryRecord], *,
                     tenant_id: str | None) -> tuple[int, list[Quarantine]]: ...   # S1/D2
    async def query(self, q: Query, *, actor: ActorRef) -> QueryResult: ...        # S4/D4
    async def count(self, q: Query) -> int: ...
    async def get_record(self, record_id: str) -> TelemetryRecord | None: ...

class RetentionEngine(Protocol):
    async def apply(self, *, dataset: str, tenant_id: str | None,
                    dry_run: bool = False) -> RetentionReport: ...   # fail-closed (S3)
    async def archive(self, *, dataset: str, tenant_id: str | None,
                      until: datetime, by: ActorRef) -> ArchiveRecord: ...  # tiering (D5)
    async def restore(self, archive_id: str, *, by: ActorRef) -> int: ...
    async def set_legal_hold(self, *, dataset: str, record_ids: Sequence[str],
                             hold: bool, by: ActorRef, reason: str) -> int: ...
    async def propose_deletion(self, *, dataset: str, filter: "Condition",
                               by: ActorRef, reason: str) -> str: ...  # -> gated Workflow run (S3)
```

`DataLakeService` wraps the lake + catalog + retention as an `AQService`
(name `"datalake_engine"`, depends on blob/evidence/policy/workflow stores;
health reflects availability + config validity).

## 7. Computation (the reference model)

**Ingest.** Validate each handed-in record against its `Dataset` schema;
normalize field types; store raw payload as a `BlobRef` (D3); write the record.
Invalid → `Quarantine` entry (flagged, not dropped, D2). Bounded batches. Emits
`aqelyn.telemetry.ingested`.

**Query.** Compile the structured `Condition` + time range to a parameterized
backend query (never string-concatenated SQL, S4); enforce `tenant_id` and
`min(limit, max_query_rows)`; then **redact**: any field classified `pii`/`secret`
is masked unless Policy authorizes the actor for it — the result lists
`redacted_fields` so redaction is visible, not silent.

**Retention (`apply`).** For each candidate record past `ttl_days` (and matching
the policy `condition`): **skip if `legal_hold`**; **skip if referenced** by an
evidence record, finding, or case; else expire. Past `archive_after_days` →
archive first. Returns a `RetentionReport` with `skipped_held`/
`skipped_referenced` counts, writes an `EvidenceRecord` (D6). `dry_run` reports
without acting.

**Archive/restore.** `archive` exports a range to a `BlobRef` with a
`content_hash`, marks records `archived`, records evidence; `restore` re-ingests
a verified archive (hash mismatch → refuse, fail closed).

**Ad-hoc deletion.** `propose_deletion` **proposes a destructive EA-0008 Workflow
run**; it deletes nothing itself (S3).

## 8. Requirements

### Functional (testable)

- **FR-1** `ingest` SHALL accept handed-in records only; the module SHALL open no network connection and hold no collector credentials (S1).
- **FR-2** Records SHALL be validated against the dataset schema; invalid records SHALL be quarantined with a reason, never silently dropped or accepted (D2).
- **FR-3** Raw payloads SHALL be stored by reference (`BlobRef`); the record SHALL hold normalized fields only (D3).
- **FR-4** `query` SHALL accept only structured `Condition` filters; the engine SHALL NOT accept or execute caller-supplied SQL/query strings and SHALL NOT `eval` (S4).
- **FR-5** Every query SHALL be tenant-scoped and row-bounded (`min(limit, max_query_rows)`), returning `truncated` when capped (S4).
- **FR-6** Fields classified `pii`/`secret` SHALL be redacted unless Policy authorizes the actor; `redacted_fields` SHALL list what was masked (S4/D1).
- **FR-7** Retention SHALL NOT delete a record under `legal_hold` (S3).
- **FR-8** Retention SHALL NOT delete a record referenced by evidence, a finding, or a case; such records SHALL be skipped and counted in `skipped_referenced` (S3).
- **FR-9** `apply(dry_run=True)` SHALL report what would happen and delete nothing.
- **FR-10** Ad-hoc/bulk deletion SHALL be a **proposed, gated EA-0008 Workflow run**; the engine SHALL NOT perform ad-hoc deletion directly (S3).
- **FR-11** `archive` SHALL export with a verifiable `content_hash` and mark records `archived` (not deleted); `restore` SHALL refuse on hash mismatch (D5, fail-closed).
- **FR-12** Retention and archive operations SHALL write an `EvidenceRecord` (D6); a data-lifecycle action SHALL be auditable.
- **FR-13** The lake SHALL NOT store entities, platform events, or act as an evidence store; evidence integrity remains EA-0004 (S2).
- **FR-14** Invalid config/dataset/policy (unknown classification, `ttl_days ≤ 0`, `batch_size ≤ 0`, unknown op) SHALL raise `LakeConfigInvalid` at `register`/`put`.
- **FR-15** `DatasetCatalog` and the lake's record store SHALL each pass one contract suite (in-memory + Postgres).
- **FR-16** `DataLakeService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (fail-closed deletion)** no configuration or code path deletes held or referenced data; proven by refusal tests (S3).
- **NFR-2 (no injection / no network)** structured predicates compile to parameterized queries; no raw SQL, no `eval`, no sockets; enforced by test+grep.
- **NFR-3 (privacy-first)** PII/secret fields are redacted by default; a query result never leaks an unauthorized classified field.
- **NFR-4 (bounded & typed)** ingest/retention batched, queries row-capped, payloads by reference; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Ingest handed-in only; no network | `test_lake_ingest_no_network` |
| AC-2 | Schema validation; malformed quarantined | `test_lake_quarantine` |
| AC-3 | Raw payload stored by BlobRef | `test_lake_raw_by_ref` |
| AC-4 | Structured filters only; no SQL/eval | `test_lake_no_raw_sql` |
| AC-5 | Query tenant-scoped + row-bounded + truncated | `test_lake_query_bounded` |
| AC-6 | PII/secret redacted; redacted_fields listed | `test_lake_redaction` |
| AC-7 | Legal hold blocks expiry | `test_lake_retention_legal_hold` |
| AC-8 | Evidence/finding/case-referenced never expired | `test_lake_retention_referenced` |
| AC-9 | dry_run deletes nothing | `test_lake_retention_dry_run` |
| AC-10 | Ad-hoc deletion → proposed gated run only | `test_lake_deletion_delegated` |
| AC-11 | Archive is tiering + hash-verified; restore refuses mismatch | `test_lake_archive_restore` |
| AC-12 | Retention/archive evidence-recorded | `test_lake_lifecycle_evidence` |
| AC-13 | Lake stores no entities/events/evidence | `test_lake_not_a_second_store` |
| AC-14 | Invalid config/dataset rejected | `test_lake_config_invalid` |
| AC-15 | Catalog & record store pass one suite each | `test_lake_catalog_contract[...]` / `test_lake_store_contract[...]` |
| AC-16 | Registers as AQService with health | `test_lake_service_health` |

## 10. Error taxonomy (contributions)

`LakeConfigInvalid`, `DatasetNotFound`, `RecordNotFound`, `ArchiveIntegrityError`,
`RetentionBlocked` (added to `conventions.errors` + CONVENTIONS §9). Reuses
`StoreUnavailable`, `TenantScopeRequired`, `UnauthorizedAction`.

## 11. Registered event types (owned by EA-0019)

`aqelyn.telemetry.ingested`, `aqelyn.telemetry.quarantined`,
`aqelyn.lake.retention_applied`, `aqelyn.lake.archived` — via
`register_lake_events()` (EA-0003 §7). (Archive uses `telemetry.ingested`; kept in
the platform namespace as `aqelyn.telemetry.ingested`.)

## 12. Failure handling

- Invalid config/dataset/policy → `LakeConfigInvalid` before any ingest/retention
  uses it.
- Blob/record store unavailable → `StoreUnavailable`; service `degraded`;
  **retention SHALL NOT run** when reference-checking is impossible — it fails
  closed rather than expiring on incomplete information (S3).
- Archive hash mismatch on restore → `ArchiveIntegrityError`, refuse (never
  restore unverifiable data).
- A single malformed record → quarantined + flagged; the batch continues.
- Query over an unindexed field → allowed but bounded; if the backend cannot
  satisfy it within limits, return `truncated` rather than run unbounded.

## 13. Dependencies & consumers

- **Depends on:** EA-0004 `BlobStore` + `EvidenceStore`; EA-0009 `Condition` +
  `authorize` (redaction authorization); **EA-0008 Workflow** (ad-hoc deletion
  proposed + gated); EA-0001 `AQService`; CONVENTIONS (redaction precedent).
- **Consumed by:** EA-0017 Detection (telemetry is the observation substrate);
  EA-0015 SOC (investigation queries); EA-0016 Forensics (telemetry context);
  EA-0010 (retention/compliance evidence); the query/dataset UI (**WCAG 2.2 AA**).

## 14. Resolved / deferred decisions

- **Realized over the existing Postgres + BlobStore substrate; backend is a swap
  seam** (§1). A production lakehouse/columnar backend requires a **deployment/
  backend ADR refresh** — flagged, not decided here.
- **Collectors/agents are a later connector EA** (S1); `TelemetryRecord` is the
  handoff seam.
- **Policy-driven expiry is automated but fail-closed; ad-hoc deletion is gated**
  (S3) — the deliberate split between routine lifecycle and destructive action.
- **The lake is not the evidence store** (S2) — EA-0004 remains the single
  integrity backbone.
