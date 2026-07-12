# EA-0004 — Evidence Record & Hash-Chain Integrity — Implementation Specification

**Realizes:** EA-0004 (supersedes the placeholder `archive/EA-0004/EA-0004_Master.md` for implementation)
**Depends on:** ADR-0001, EA-0002 (object refs, `ActorRef`, `SourceRef.evidence_id` seam), EA-0003 (`Subject.evidence_id`, `aqelyn.evidence.recorded`), CONVENTIONS (canonical JSON, sha256)
**Consumed by:** Finding model (findings cite evidence), every assessment engine (EA-0052+)
**Status:** Accepted
**Definition of Ready:** see §11

---

## 1. Purpose

Evidence is AQELYN's **proof layer**. The charter's "evidence before opinion"
and "how AQELYN knows" promises require that every asserted fact can be traced
to an immutable, tamper-evident record of what was observed and how. This spec
defines that record, the integrity mechanism that makes it trustworthy for
enterprise and government audit, and the packages used to export proof for
review.

## 2. Scope

**In scope:** the evidence record, content addressing, the tamper-evident
hash-chain, verification, evidence packages (bundled export), chain of custody
(access/export log), retention/legal-hold flags, and the `EvidenceStore` /
`BlobStore` interfaces + schema.

**Out of scope:** how engines *collect* observations (their EAs), cryptographic
signing/PKI key management (a later ADR — hooks are reserved here), and external
timestamp anchoring (reserved, §4 D4).

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Evidence record** | An immutable record of a single observation supporting a fact. `evd_…`. |
| **Content hash** | `sha256` of the canonical content (CONVENTIONS §3). Enables integrity + dedup. |
| **Hash-chain** | Each record binds the previous record's hash, making the log tamper-evident. |
| **Evidence package** | A signed/hashed bundle of evidence records for review/export. `pkg_…`. |
| **Chain of custody** | Append-only log of who accessed or exported evidence. |

## 4. Design decisions

- **D1 — Evidence is immutable and append-only.** No update or delete path.
  Corrections are *new* evidence. Enforced in code and schema (`EvidenceImmutable`).
- **D2 — Content-addressed.** `content_hash = sha256(canonical(content))`.
  Identical observations dedupe; any alteration changes the hash.
- **D3 — Tamper-evident hash-chain.** Records form an append-only ledger,
  partitioned by `tenant_id` (NULL partition for local). Each record stores
  `seq`, `prev_hash`, and `record_hash = sha256(canonical(record⊖record_hash) ||
  prev_hash)`. Altering any record breaks every subsequent link — detectable by
  verification.
- **D4 — Signing & external anchoring are reserved seams, not built now.**
  `signature` and `anchor` fields exist and are nullable; a later ADR fills them
  (e.g. periodic Merkle-root anchoring). This keeps C-001 lean without a
  breaking change later.
- **D5 — Large content lives in a BlobStore**, referenced by hash; small content
  inlines as JSONB. Same integrity guarantee either way.
- **D6 — Access is logged (chain of custody).** Reads/exports of evidence append
  a custody row — required for audit and future legal use.

## 5. The evidence record

| Field | Type | Req | Description |
|---|---|---|---|
| `id` | ID (`evd_…`) | yes | Immutable identifier. |
| `tenant_id` | UUID \| null | no | Owning tenant; NULL local. Defines the chain partition. |
| `evidence_type` | string | yes | Registered kind, e.g. `config.snapshot`, `network.observation`, `log.record`. |
| `schema_version` | int | yes | Version of the content schema. |
| `subject` | Subject | yes | Object(s) this evidence is about (reuses EA-0003 `Subject`). |
| `collected_at` | timestamp | yes | When the observation was made. |
| `recorded_at` | timestamp | yes | When AQELYN stored it. |
| `collector` | ActorRef | yes | Who/what collected it. |
| `source_id` | ID (`src_…`) | yes | Provenance source (links EA-0002 `SourceRef`). |
| `method` | string | yes | How it was obtained, e.g. `connector:intune`, `scan:tls`. |
| `content` | object \| null | cond | Inline canonical content (small). Null if in blob. |
| `content_ref` | BlobRef \| null | cond | Pointer to blob content (large). Exactly one of content/content_ref. |
| `content_hash` | hex(sha256) | yes | Hash of canonical content (D2). |
| `confidence` | float 0..1 | yes | Confidence in the observation. |
| `labels` | map<string,string> | no | Tags. |
| `seq` | bigint | yes | Position in the tenant chain (assigned by store). |
| `prev_hash` | hex \| null | yes | Previous record's `record_hash` (null for first). |
| `record_hash` | hex(sha256) | yes | Chain hash (D3). |
| `signature` | object \| null | no | Reserved (D4). |
| `anchor` | object \| null | no | Reserved external-anchor proof (D4). |

```
BlobRef = { hash: hex(sha256), size_bytes: int, media_type: string, uri: string }
```

## 5a. Events registered by this spec

This spec owns and registers the following event type in the EA-0003 registry:

| event_type | schema_version | Emitted when | Key payload |
|---|---|---|---|
| `aqelyn.evidence.recorded` | 1 | `EvidenceStore.add` succeeds | `{ evidence_type, source_id }`, `subject.evidence_id` set |

## 6. Evidence packages (review-ready export)

- `EvidencePackage` (`pkg_…`) bundles a set of `evidence_id`s with a manifest.
- `manifest_hash = sha256(canonical(sorted evidence hashes + metadata))`;
  `package_hash` binds the manifest + creator + time.
- Export produces a self-verifying artifact (manifest + records or blob refs) an
  auditor can validate offline by recomputing hashes and checking chain links.
- Charter tie-in: this is the "review-ready evidence package" the product
  promises for enterprise/government.

## 7. Verification

- `verify(evidence_id)` → recompute `content_hash` and `record_hash`; compare.
- `verify_chain(tenant, from_seq, to_seq)` → walk the partition, confirm each
  `prev_hash` link and `seq` continuity; return the first break if any.
- `verify_package(package_id)` → confirm every member verifies and the manifest
  hash matches.
- Any mismatch → `EvidenceTampered` / `ChainBroken` with the offending `seq`.

## 8. Interfaces (Python 3.12)

```python
from typing import Protocol
from datetime import datetime
from pydantic import BaseModel, Field
# ActorRef, Subject imported from EA-0002 / EA-0003 packages

class BlobRef(BaseModel):
    hash: str; size_bytes: int; media_type: str; uri: str

class EvidenceRecord(BaseModel):
    id: str
    tenant_id: str | None = None
    evidence_type: str
    schema_version: int
    subject: "Subject"
    collected_at: datetime
    recorded_at: datetime
    collector: "ActorRef"
    source_id: str
    method: str
    content: dict | None = None
    content_ref: BlobRef | None = None
    content_hash: str
    confidence: float = 1.0
    labels: dict[str, str] = Field(default_factory=dict)
    seq: int
    prev_hash: str | None
    record_hash: str
    signature: dict | None = None
    anchor: dict | None = None

class VerifyResult(BaseModel):
    ok: bool
    broken_at_seq: int | None = None
    detail: str | None = None

class BlobStore(Protocol):
    async def put(self, data: bytes, *, media_type: str) -> BlobRef: ...   # addressed by sha256
    async def get(self, ref: BlobRef) -> bytes: ...

class EvidenceStore(Protocol):
    async def add(self, record: EvidenceRecord) -> EvidenceRecord: ...     # assigns id/seq/prev_hash/record_hash, appends chain, logs custody
    async def get(self, evidence_id: str, *, actor: "ActorRef") -> EvidenceRecord: ...  # logs custody read
    async def verify(self, evidence_id: str) -> VerifyResult: ...
    async def verify_chain(self, *, tenant_id: str | None,
                           from_seq: int = 0, to_seq: int | None = None) -> VerifyResult: ...
    async def package(self, evidence_ids: list[str], *, by: "ActorRef",
                      reason: str) -> "EvidencePackage": ...
    async def verify_package(self, package_id: str) -> VerifyResult: ...

class EvidencePackage(BaseModel):
    id: str
    tenant_id: str | None = None
    evidence_ids: list[str]
    manifest_hash: str
    package_hash: str
    created_by: "ActorRef"
    created_at: datetime
    reason: str
```

`add()` is the only writer; it computes the chain fields — callers never set
`seq`/`prev_hash`/`record_hash`.

## 9. Persistence (PostgreSQL 16)

```sql
CREATE TABLE aq_evidence (
    id            uuid PRIMARY KEY,
    tenant_id     uuid        NULL,
    evidence_type text        NOT NULL,
    schema_version int        NOT NULL,
    subject       jsonb       NOT NULL,
    collected_at  timestamptz NOT NULL,
    recorded_at   timestamptz NOT NULL DEFAULT now(),
    collector     jsonb       NOT NULL,
    source_id     uuid        NOT NULL,
    method        text        NOT NULL,
    content       jsonb       NULL,
    content_ref   jsonb       NULL,
    content_hash  text        NOT NULL,
    confidence    double precision NOT NULL DEFAULT 1.0,
    labels        jsonb       NOT NULL DEFAULT '{}',
    seq           bigint      NOT NULL,
    prev_hash     text        NULL,
    record_hash   text        NOT NULL,
    signature     jsonb       NULL,
    anchor        jsonb       NULL,
    CHECK ((content IS NOT NULL) <> (content_ref IS NOT NULL))   -- exactly one
);
-- One monotonic chain per tenant partition (NULL = local):
CREATE UNIQUE INDEX uq_evidence_chain ON aq_evidence (tenant_id, seq);
CREATE INDEX ix_evidence_hash ON aq_evidence (content_hash);
-- No UPDATE/DELETE path in code (D1). Enforced by review + DB role grants.

CREATE TABLE aq_evidence_custody (
    seq         bigserial PRIMARY KEY,
    evidence_id uuid        NOT NULL,
    action      text        NOT NULL CHECK (action IN ('read','export','package')),
    actor       jsonb       NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    context     jsonb       NULL
);

CREATE TABLE aq_evidence_package (
    id            uuid PRIMARY KEY,
    tenant_id     uuid        NULL,
    evidence_ids  jsonb       NOT NULL,
    manifest_hash text        NOT NULL,
    package_hash  text        NOT NULL,
    created_by    jsonb       NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    reason        text        NOT NULL
);
```

The production DB role for evidence tables SHOULD be granted `INSERT`/`SELECT`
only (no `UPDATE`/`DELETE`) as defense-in-depth for D1.

## 10. Requirements

### Functional

- **FR-1** `add` SHALL assign `id`, `seq`, `prev_hash`, and compute `record_hash`; callers cannot set chain fields.
- **FR-2** `add` SHALL compute and store `content_hash` over canonical content (CONVENTIONS §3).
- **FR-3** Exactly one of `content` / `content_ref` SHALL be present (`SchemaValidationError` otherwise).
- **FR-4** Any attempt to update or delete an evidence record SHALL be rejected (`EvidenceImmutable`).
- **FR-5** `verify` SHALL detect any content or chain alteration (`EvidenceTampered`).
- **FR-6** `verify_chain` SHALL detect a broken/missing link and report the first offending `seq` (`ChainBroken`).
- **FR-7** Reads and exports SHALL append a chain-of-custody row (D6).
- **FR-8** `package`/`verify_package` SHALL produce and validate a self-verifying bundle (§6).
- **FR-9** Adding evidence SHALL emit `aqelyn.evidence.recorded` (EA-0003) with `subject.evidence_id` set.
- **FR-10** Evidence SHALL be tenant-scoped exactly as EA-0002/CONVENTIONS require; cross-tenant access rejected.
- **FR-11** `content_ref` blobs SHALL be content-addressed by sha256 and integrity-checked on retrieval.

### Non-functional (initial targets)

- **NFR-1** `add` p95 < 20 ms (inline content ≤ 32 KB) on M-tier hardware.
- **NFR-2** `verify_chain` of 1M records completes < 30 s (streaming, bounded memory).
- **NFR-3** Chain integrity holds across process restarts and concurrent writers (serialized per tenant partition).
- **NFR-4** In-memory and Postgres `EvidenceStore` pass one contract suite; `mypy --strict` + `ruff` clean.

## 11. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test |
|---|---|---|
| AC-1 | Chain fields computed by store, not caller | `test_evd_chain_fields_assigned` |
| AC-2 | Content hash matches canonical content | `test_evd_content_hash` |
| AC-3 | Exactly-one content/content_ref enforced | `test_evd_content_xor_ref` |
| AC-4 | Update/delete rejected | `test_evd_immutable` |
| AC-5 | Tampered content detected | `test_evd_verify_detects_tamper` |
| AC-6 | Broken chain reports first bad seq | `test_evd_verify_chain_break` |
| AC-7 | Read/export writes custody row | `test_evd_custody_logged` |
| AC-8 | Package verifies offline | `test_evd_package_self_verifying` |
| AC-9 | `aqelyn.evidence.recorded` emitted | `test_evd_emits_event` |
| AC-10 | Cross-tenant access rejected | `test_evd_tenant_isolation` |
| AC-11 | Blob integrity checked on get | `test_evd_blob_integrity` |
| AC-12 | In-memory & Postgres stores pass one suite | `test_evd_store_contract[inmemory]` / `[postgres]` |

## 12. Error taxonomy (contributions)

`EvidenceNotFound`, `EvidenceTampered`, `ChainBroken`, `EvidenceImmutable`
(see CONVENTIONS §9).

## 13. Failure handling

- Verification failure surfaces the exact `seq` and is itself an audit event.
- Blob store unavailable → `StoreUnavailable`; evidence metadata may still be
  read; integrity of retrieved blobs is always checked before use.
- Concurrent appends to one tenant chain are serialized so `seq`/`prev_hash`
  stay monotonic (advisory lock per tenant partition).

## 14. Dependencies & consumers

- **Depends on:** ADR-0001, EA-0002, EA-0003, CONVENTIONS. Library: stdlib
  `hashlib`; blob backend = filesystem (local) / object storage (later).
- **Consumed by:** Finding model (`evidence_ids`), all engines producing
  findings; fills `SourceRef.evidence_id` (EA-0002) and `Subject.evidence_id`
  (EA-0003).
