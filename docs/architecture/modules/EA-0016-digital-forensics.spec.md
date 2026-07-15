# EA-0016 — Digital Forensics Engine — Implementation Specification

**Realizes:** EA-0016 / IS-016 (supersedes the placeholder `archive/EA-0016/EA-0016_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0004 (evidence hash-chain, custody, verify, packages — the forensic backbone)**, EA-0002 (artifacts as objects), EA-0005 (link artifacts↔assets), EA-0015 (attach to incidents/cases), the Finding model
**Consumed by:** the SOC analyst workspace (attach forensics to a case — a WCAG 2.2 AA surface), auditors & legal (court-ready evidence packages), EA-0013 (forensic findings as risk signal)
**Status:** Accepted
**Build milestone:** C-013 (see `C-013_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 0. Scope & safety boundary (read first)

- **Analyze and attest — never alter, never act.** Digital forensics examines
  acquired material and **proves its integrity**; it does **not** modify any
  source, and it takes **no response action** (that remains EA-0008 Workflow, via
  SOC). Forensic outputs are artifacts, timelines, verifications, findings, and
  evidence packages — all read/derive.
- **Acquisition accepts handed-in material; it does not reach into hosts.** An
  `Acquisition` is a **handed-in artifact** (a disk/memory/browser image or file,
  already captured) with its collector and hash. This engine does **not** open
  network connections, log into endpoints, or run remote collection — **live host
  acquisition is a connector/agent concern for a later EA** (same line drawn for
  EA-0014 feeds). The `Acquisition` seam is the handoff.
- **Chain of custody is sacred.** Every artifact and every access is recorded
  through the EA-0004 evidence hash-chain + custody log; integrity is
  independently verifiable. Forensics *is* the evidence discipline applied — it
  reuses the C-001 backbone, it does not invent a parallel one.
- Deterministic, explainable, tenant-scoped throughout. No new authorization
  surface.

## 1. Purpose

When an incident needs to be *proven*, the Digital Forensics Engine takes
acquired material — a disk image, a memory capture, browser artifacts — and turns
it into **verifiable evidence**: cataloged artifacts with unbroken chain of
custody, a reconstructed **forensic timeline**, integrity **verification**, and
**court-ready evidence packages**. It answers *what happened on this system, in
what order, and can we prove the evidence wasn't tampered with?* — to a standard
that holds up to an auditor or a court.

## 2. Design decisions

- **D1 — Forensics is the EA-0004 evidence backbone applied.** Every artifact is
  recorded via `EvidenceStore.add` (hash-chained, custody-logged); integrity uses
  `verify`/`verify_chain`; deliverables use `package`/`verify_package`. No new
  hashing or custody logic (reuse, single source of integrity truth).
- **D2 — Artifacts are objects; large blobs are BlobRefs.** An `Artifact` is an
  `AQObject` (`object_type "forensic_artifact"`) with metadata; raw content is a
  `BlobRef` (EA-0004 §BlobStore) — the engine handles references + hashes, not
  bytes in memory (bounded).
- **D3 — Acquisition is handed-in (§0).** No host/network access here; the
  `Acquisition` record captures collector, method, source, and hash of
  already-captured material.
- **D4 — Timeline is deterministic and provenance-carrying.** The forensic
  timeline orders artifact-derived events; each entry cites the artifact +
  evidence it came from. Same artifacts → same timeline (D-audit).
- **D5 — Verification is independent and continuous.** `verify_artifact` /
  `verify_case` re-check the hash-chain at any time; tampering is detected and
  surfaced, never hidden.
- **D6 — Read/derive only (§0).** Findings and packages are produced; nothing is
  altered or acted on. Registered as an `AQService` (D7). Tenant-scoped.

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Acquisition** | Handed-in captured material (image/dump/file) + collector + hash (§0). |
| **Artifact** | A cataloged forensic item (`object_type "forensic_artifact"`), content via `BlobRef`. |
| **Chain of custody** | The unbroken, evidence-backed record of who handled an artifact when (EA-0004). |
| **Forensic timeline** | The ordered, provenance-carrying reconstruction of events from artifacts. |
| **Verification** | Independent integrity re-check of the evidence hash-chain (EA-0004 `verify`). |
| **Evidence package** | A self-verifying, court-ready export (EA-0004 `package`). |

## 4. Types

```
Acquisition = { id, tenant_id, source_ref: str, collector: ActorRef,
                method: str, acquired_at: datetime, content_ref: "BlobRef",
                content_hash: str, case_id: str | null }     # handed-in (§0)
Artifact    = { id, tenant_id, artifact_type: str,           # "disk_image"|"memory"|"browser"|"file"|...
                acquisition_id: str, object_id: str,         # the AQObject cataloging it
                evidence_id: str, metadata: dict,
                linked_asset_ids: list[str], first_seen_at: datetime }
TimelineEvent = { at: datetime, artifact_id: str, kind: str, detail: dict,
                  evidence_id: str }                          # provenance-carrying (D4)
ForensicTimeline = { case_id: str | null, events: list[TimelineEvent], truncated: bool }
VerifyReport = { subject_id: str, ok: bool, broken_at: str | null, detail: str | null }
ForensicsConfig = { batch_size: int, timeline_window: dict | null }
```

Reuses EA-0004 `BlobRef`/`EvidenceRecord`/`EvidencePackage`/`VerifyResult`,
EA-0002 objects, `ActorRef`, EA-0015 case ids, the Finding model.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class ArtifactStore(Protocol):                              # metadata catalog (blobs via EA-0004 BlobStore)
    async def put(self, artifact: Artifact) -> Artifact: ...
    async def get(self, artifact_id: str) -> Artifact | None: ...
    async def list(self, *, tenant_id: str | None, case_id: str | None = None) -> list[Artifact]: ...

class DigitalForensicsEngine(Protocol):
    async def register_acquisition(self, acq: Acquisition, *, by: ActorRef) -> Acquisition: ...  # §0; records evidence + custody
    async def catalog_artifact(self, acquisition_id: str, *, artifact_type: str,
                               metadata: dict, by: ActorRef) -> Artifact: ...   # -> object + evidence (D1/D2)
    async def build_timeline(self, *, case_id: str | None,
                             artifact_ids: Sequence[str]) -> ForensicTimeline: ...  # D4
    async def verify_artifact(self, artifact_id: str) -> VerifyReport: ...      # EA-0004 verify (D5)
    async def verify_case(self, case_id: str) -> VerifyReport: ...
    async def link_to_assets(self, artifact_id: str) -> list[str]: ...          # via KG (D-audit)
    async def package_case(self, case_id: str, *, by: ActorRef, reason: str) -> str: ...  # EA-0004 package
    async def findings_from_artifacts(self, artifact_ids: Sequence[str], *,
                                      by: ActorRef) -> list[str]: ...
    def explain(self, event: TimelineEvent) -> dict: ...
```

`DigitalForensicsService` wraps the engine + `ArtifactStore` as an `AQService`
(name `"forensics_engine"`, depends on evidence/object/kg/finding stores + SOC;
health reflects their availability + config validity).

## 6. Computation (the reference model)

**Acquire (handed-in).** `register_acquisition` validates the handed-in material's
`content_hash`, stores content as a `BlobRef` (EA-0004 `BlobStore`), and writes an
`EvidenceRecord` + custody entry — establishing chain of custody at intake (§0/D1).

**Catalog.** `catalog_artifact` creates an `AQObject` (`forensic_artifact`) and an
`EvidenceRecord` binding it to its acquisition; large content stays a `BlobRef`
(D2).

**Timeline.** `build_timeline` derives ordered `TimelineEvent`s from artifact
metadata, each citing its artifact + evidence; deterministic; bounded (D4).

**Verify.** `verify_artifact`/`verify_case` call EA-0004 `verify`/`verify_chain`;
a broken chain returns `ok=False` with `broken_at` — surfaced, never suppressed
(D5).

**Link & findings.** `link_to_assets` correlates an artifact to estate assets via
KG; `findings_from_artifacts` raises evidence-cited forensic findings; `package_
case` produces a self-verifying EA-0004 `EvidencePackage` for legal/audit.
Nothing is altered or acted on (§0).

## 7. Requirements

### Functional (testable)

- **FR-1** `register_acquisition` SHALL accept handed-in material only (no host/network access), store content as a `BlobRef`, and write an `EvidenceRecord` + custody entry at intake (§0/D1/D3).
- **FR-2** Ingest SHALL verify the handed-in `content_hash`; a mismatch SHALL be rejected (`ArtifactIntegrityError`), never cataloged as trusted.
- **FR-3** `catalog_artifact` SHALL create an `AQObject` (`forensic_artifact`) + an `EvidenceRecord` binding it to its acquisition; content SHALL remain a `BlobRef` (D2).
- **FR-4** Every artifact and access SHALL be recorded through the EA-0004 hash-chain + custody log (D1); custody SHALL be reconstructable.
- **FR-5** `build_timeline` SHALL produce a deterministic, provenance-carrying timeline; each event SHALL cite its artifact + evidence; bounded (`truncated` flagged) (D4).
- **FR-6** `verify_artifact`/`verify_case` SHALL re-check the evidence hash-chain via EA-0004 and SHALL surface any break (`ok=False`, `broken_at`) (D5).
- **FR-7** `link_to_assets` SHALL correlate artifacts to estate assets via the Knowledge Graph, tenant-scoped.
- **FR-8** `package_case` SHALL produce a self-verifying EA-0004 `EvidencePackage`; `findings_from_artifacts` SHALL raise evidence-cited findings.
- **FR-9** The engine SHALL NOT modify any source, artifact content, or non-forensic object, and SHALL take no response action (§0/D6).
- **FR-10** All operations SHALL be tenant-scoped; no cross-tenant artifact/case appears.
- **FR-11** Invalid config (`batch_size ≤ 0`) or malformed acquisition SHALL raise `ForensicsConfigInvalid` / `ArtifactIntegrityError`.
- **FR-12** `ArtifactStore` in-memory and Postgres implementations SHALL pass one contract suite.
- **FR-13** `DigitalForensicsService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (integrity-first)** every forensic artifact is hash-chained + custody-logged via EA-0004; a tampered artifact is always detectable (`verify` proves it).
- **NFR-2 (no host/network/action surface)** no code path opens a socket, accesses a remote host, or executes a response; enforced by test/grep.
- **NFR-3 (bounded)** content handled by reference (`BlobRef`), not loaded whole; timelines/batches bounded.
- **NFR-4 (portability & typing)** in-memory + Postgres `ArtifactStore` pass one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Acquisition handed-in; evidence + custody at intake | `test_dfe_acquisition_custody` |
| AC-2 | No host/network access | `test_dfe_no_host_access` |
| AC-3 | Content-hash mismatch rejected | `test_dfe_integrity_reject` |
| AC-4 | Artifact → object + evidence, content as BlobRef | `test_dfe_catalog_artifact` |
| AC-5 | Custody reconstructable | `test_dfe_custody_chain` |
| AC-6 | Timeline deterministic + provenance | `test_dfe_timeline` |
| AC-7 | verify detects a broken chain | `test_dfe_verify_tamper` |
| AC-8 | Link to assets via KG | `test_dfe_link_assets` |
| AC-9 | Case package is self-verifying | `test_dfe_package_case` |
| AC-10 | Findings evidence-cited | `test_dfe_findings` |
| AC-11 | Engine alters no source / takes no action | `test_dfe_no_mutation_no_action` |
| AC-12 | Tenant isolation | `test_dfe_tenant_isolation` |
| AC-13 | Invalid config/acquisition rejected | `test_dfe_config_invalid` |
| AC-14 | In-memory & Postgres ArtifactStore pass one suite | `test_dfe_artifact_contract[inmemory]` / `[postgres]` |
| AC-15 | Registers as AQService with health | `test_dfe_service_health` |

## 9. Error taxonomy (contributions)

`ForensicsConfigInvalid`, `ArtifactIntegrityError`, `ArtifactNotFound` (added to
`conventions.errors` + CONVENTIONS §9). Reuses EA-0004 `EvidenceTampered`/
`ChainBroken`, `StoreUnavailable`, `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0016)

`aqelyn.forensics.artifact_cataloged`, `aqelyn.forensics.evidence_verified`,
`aqelyn.forensics.case_packaged` — via `register_forensics_events()` (EA-0003 §7).
(Archive uses `evidence.verified`; mapped into the platform namespace as
`aqelyn.forensics.evidence_verified`.)

## 11. Failure handling

- Invalid config / malformed acquisition → `ForensicsConfigInvalid` /
  `ArtifactIntegrityError`; service `unavailable` / record rejected.
- Evidence/blob store unavailable → `StoreUnavailable`; service `degraded`; no
  partial catalog presented as complete.
- `verify` finding a broken chain → `ok=False` returned and surfaced (never
  suppressed); the artifact is flagged, not silently dropped.
- A blob whose hash no longer matches its `BlobRef` → `EvidenceTampered`
  surfaced; the case package build SHALL fail closed rather than emit an
  unverifiable package.

## 12. Dependencies & consumers

- **Depends on:** **EA-0004 `EvidenceStore` + `BlobStore`** (hash-chain, custody,
  verify, packages); EA-0002 objects; EA-0005 `KnowledgeGraph`; EA-0015 case ids;
  the Finding model; EA-0001 `AQService`.
- **Consumed by:** the SOC analyst workspace (forensics attached to a case —
  **WCAG 2.2 AA** applies); auditors & legal (court-ready packages); EA-0013
  (forensic findings as a risk signal).

## 13. Resolved / deferred decisions

- **Forensics reuses the EA-0004 evidence backbone** — one integrity/custody
  truth; no parallel hashing.
- **Acquisition is handed-in; live host/endpoint collection is a later
  connector/agent EA** (§0). The `Acquisition` seam is the handoff, unchanged
  when collectors land.
- **Deep format parsers** (disk/memory/browser internals) are pluggable analyzers
  delivered incrementally; the engine's contract is the cataloged `Artifact` +
  its derived `TimelineEvent`s.
- **Analyze/attest only, never alter or act** (§0) is binding.
