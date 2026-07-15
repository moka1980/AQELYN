# C-016 Security Data Lake & Telemetry — Implementation Task Bundle

**Milestone:** C-016 (Security Data Lake & Telemetry Platform, EA-0019)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0018 merged & green; EA-0019 spec **Accepted**; CONVENTIONS + EA-0004/0008/0009 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no network, no raw SQL, PII redacted by default, deletion fail-closed**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0019 §0 first.** This is the platform's first **infrastructure** module
and its first module that **deletes**. Build the catalog + safe query path (L1–L3)
**before** any retention code (L4). Never write string-built SQL; never delete on
incomplete information.

## Target source layout

```
src/aqelyn/lake/
├── __init__.py       # exports the lake, service, types, register_lake_events
├── models.py         # Dataset, TelemetryRecord, RetentionPolicy, Query, QueryResult,
│                     #   ArchiveRecord, RetentionReport, Quarantine, LakeConfig (L1)
├── catalog.py        # DatasetCatalog: schema + field classifications (L1)
├── ingest.py         # validate + normalize + quarantine; raw -> BlobRef (L2)
├── query.py          # Condition -> parameterized query; bounds; redaction (L3)
├── store.py          # record store + catalog protocols (L2)
├── memory.py         # in-memory implementations (L2)
├── postgres.py       # Postgres implementations + partitioned DDL (L2)
├── retention.py      # apply/archive/restore/legal_hold/propose_deletion (L4)
└── service.py        # DataLakeService(AQService) + register_lake_events (L5)
tests/lake/           # acceptance suite (in-memory + Postgres)
```

---

## L1 — Types, dataset catalog & classification

**Spec:** §5, §6, D1, FR-14; §10.
**Deliverables:** the models; `DatasetCatalog` (schema + per-field
`Classification`); config/dataset/policy validation (`LakeConfigInvalid` on
unknown classification, `ttl_days ≤ 0`, `batch_size ≤ 0`, unknown op); new error
codes in `conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0009 `Condition`, conventions.
**Acceptance:** `test_lake_config_invalid`.

## L2 — Ingest + record store (handed-in only)

**Spec:** §0 (S1/S2), §7, FR-1/2/3/13/15, D2/D3.
**Deliverables:** `ingest` (schema validation, normalization, **quarantine**
malformed, raw payload → `BlobRef`); record store + catalog (in-memory +
Postgres + partitioned DDL); **no network/collector code**; the lake stores no
entities/events/evidence.
**Depends on:** L1.
**Acceptance:** `test_lake_ingest_no_network`, `test_lake_quarantine`,
`test_lake_raw_by_ref`, `test_lake_not_a_second_store`,
`test_lake_catalog_contract[inmemory]`, `test_lake_catalog_contract[postgres]`,
`test_lake_store_contract[inmemory]`, `test_lake_store_contract[postgres]`.

## L3 — Safe query + redaction

**Spec:** §0 (S4), §7, FR-4/5/6, D4, NFR-2/NFR-3.
**Deliverables:** `query`/`count` — EA-0009 `Condition` compiled to
**parameterized** queries (never string-concatenated SQL, no `eval`);
tenant-scoped; `min(limit, max_query_rows)` with `truncated`; **redaction of
`pii`/`secret` fields unless Policy authorizes**, with `redacted_fields` listed.
**Depends on:** L2.
**Acceptance:** `test_lake_no_raw_sql`, `test_lake_query_bounded`,
`test_lake_redaction`.

## L4 — Retention, archive & the deletion boundary

**Spec:** §0 (S3), §7, FR-7/8/9/10/11/12, D5/D6, NFR-1.
**Deliverables:** `apply` (TTL expiry that **skips legal-hold** and **skips
evidence/finding/case-referenced** records, counting both; `dry_run`);
`archive`/`restore` (tiering with `content_hash`; restore refuses on mismatch);
`set_legal_hold`; `propose_deletion` (**gated EA-0008 run only**); evidence for
every lifecycle op; **retention refuses to run when reference-checking is
unavailable**.
**Depends on:** L3.
**Acceptance:** `test_lake_retention_legal_hold`, `test_lake_retention_referenced`,
`test_lake_retention_dry_run`, `test_lake_deletion_delegated`,
`test_lake_archive_restore`, `test_lake_lifecycle_evidence`.

## L5 — Service + events

**Spec:** FR-16, §11.
**Deliverables:** `DataLakeService` (`AQService`, name `"datalake_engine"`) +
`register_lake_events`; wired into the kernel factory.
**Depends on:** L4.
**Acceptance:** `test_lake_service_health`.

---

## Review protocol (Claude Code) — deletion + privacy get the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **Fail-closed deletion (the core property).** Trace `apply`: a record under
   legal hold or referenced by evidence/finding/case is **never** deleted — it is
   skipped and counted. If reference-checking is unavailable, retention **does not
   run**. No config can turn this off (S3/NFR-1).
2. **Ad-hoc deletion is delegated** — `propose_deletion` creates a gated EA-0008
   run and deletes nothing itself.
3. **No raw SQL / no injection** — filters are EA-0009 `Condition`s compiled to
   **parameterized** queries; grep for string-built SQL and `eval`.
4. **Privacy-first** — `pii`/`secret` fields redacted by default; a result never
   leaks an unauthorized classified field; `redacted_fields` makes redaction
   visible, not silent.
5. **No network/collector code**; the lake stores no entities/events/evidence
   (EA-0004 remains the integrity backbone, S2).
6. Archive is tiering (not deletion), hash-verified; restore refuses mismatch.
7. Everything tenant-scoped + bounded; `ruff` + `mypy --strict` clean.

Merge only on green review; then **report back to the owner** before the next
module.
