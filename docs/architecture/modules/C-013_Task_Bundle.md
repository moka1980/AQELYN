# C-013 Digital Forensics — Implementation Task Bundle

**Milestone:** C-013 (Digital Forensics Engine, EA-0016)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0015 merged & green; EA-0016 spec **Accepted**; CONVENTIONS + EA-0002/0004/0005/0015 + Finding model read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no host/network access; no source alteration; no action**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

This engine **is the EA-0004 evidence backbone applied to forensic artifacts** —
reuse `EvidenceStore`/`BlobStore` for hashing/custody/verify/packages; do not
build a parallel integrity mechanism. If a needed behavior isn't in the spec,
raise an ECR.

## Target source layout

```
src/aqelyn/forensics/
├── __init__.py       # exports the engine, service, types, register_forensics_events
├── models.py         # Acquisition, Artifact, TimelineEvent, ForensicTimeline, VerifyReport, ForensicsConfig (F1)
├── store.py          # ArtifactStore protocol (F2)
├── memory.py         # InMemoryArtifactStore (F2)
├── postgres.py       # PostgresArtifactStore + DDL (F2)
├── acquire.py        # register_acquisition + catalog_artifact (evidence/custody via EA-0004) (F1/F2)
├── timeline.py       # build_timeline + verify_artifact/verify_case (F3)
├── engine.py         # link_to_assets + package_case + findings_from_artifacts (F4)
└── service.py        # DigitalForensicsService(AQService) + register_forensics_events (F5)
tests/forensics/      # acceptance suite (in-memory + Postgres)
```

---

## F1 — Types, config & acquisition (handed-in, custody at intake)

**Spec:** §4, §6 (acquire/catalog), §0, FR-1/2/3/4/11, D1/D2/D3; §9.
**Deliverables:** the models; `register_acquisition` (handed-in only — **no host/
network code**; verify `content_hash`, store `BlobRef`, write `EvidenceRecord` +
custody); `catalog_artifact` (→ `AQObject` + evidence, content as `BlobRef`);
config/integrity validation (`ForensicsConfigInvalid`/`ArtifactIntegrityError`);
new error codes in `conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0004 evidence/blob, EA-0002 objects, conventions.
**Acceptance:** `test_dfe_acquisition_custody`, `test_dfe_no_host_access`,
`test_dfe_integrity_reject`, `test_dfe_catalog_artifact`, `test_dfe_config_invalid`.

## F2 — ArtifactStore

**Spec:** §5, FR-12, §0.
**Deliverables:** `ArtifactStore` (in-memory + Postgres + DDL); one parametrized
contract suite; tenant scoping.
**Depends on:** F1.
**Acceptance:** `test_dfe_tenant_isolation`,
`test_dfe_artifact_contract[inmemory]`, `test_dfe_artifact_contract[postgres]`.

## F3 — Timeline & verification

**Spec:** §6, FR-4/5/6, D4/D5.
**Deliverables:** `build_timeline` (deterministic, provenance-carrying, bounded);
`verify_artifact`/`verify_case` (EA-0004 `verify`/`verify_chain`, surface breaks);
custody reconstruction; `explain`.
**Depends on:** F2.
**Acceptance:** `test_dfe_custody_chain`, `test_dfe_timeline`,
`test_dfe_verify_tamper`.

## F4 — Linking, packaging & findings (analyze-only)

**Spec:** §0, §6, FR-7/8/9, D6, NFR-2; EA-0005 KG; EA-0004 package.
**Deliverables:** `link_to_assets` (KG); `package_case` (self-verifying EA-0004
package, **fail-closed** if any artifact fails verify); `findings_from_artifacts`
(evidence-cited). No source alteration, no action.
**Depends on:** F3.
**Acceptance:** `test_dfe_link_assets`, `test_dfe_package_case`,
`test_dfe_findings`, `test_dfe_no_mutation_no_action`.

## F5 — Service + events

**Spec:** FR-13, §10.
**Deliverables:** `DigitalForensicsService` (`AQService`, name
`"forensics_engine"`) + `register_forensics_events`; wired into the kernel factory.
**Depends on:** F4.
**Acceptance:** `test_dfe_service_health`.

---

## Review protocol (Claude Code) — integrity + boundaries get the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No host/network access and no response action** — grep for sockets/HTTP/
   remote exec; `register_acquisition` consumes handed-in material only (§0).
2. **No parallel integrity mechanism** — hashing/custody/verify/packages go
   through EA-0004; the engine does not re-implement them (D1).
3. Content-hash mismatch is rejected; a broken chain is surfaced (`ok=False`),
   never suppressed; `package_case` fails closed on any unverifiable artifact.
4. The engine alters no source/artifact content and mutates only its own
   forensic records + evidence.
5. Timelines deterministic + provenance-carrying; everything tenant-scoped.
6. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
