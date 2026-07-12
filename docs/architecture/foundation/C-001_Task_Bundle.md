# C-001 Foundation Runtime — Implementation Task Bundle

**Milestone:** C-001 (AQELYN Foundation Runtime)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prereqials:** all six foundation specs + ADR-0001 **Accepted**; CONVENTIONS read first.
**Definition of done for C-001:** every ticket's acceptance tests pass, the
walking skeleton (T7) is green, `mypy --strict` + `ruff` clean, and Claude Code
has signed off each ticket against its spec.

---

**BUILD STATUS: COMPLETE, PENDING ECR-0001 DECISION.** T0-T7 are implemented
and green - with Postgres + Redis enabled, 89 tests pass and 1 is skipped,
`ruff` + `mypy --strict` clean, and the C-001 walking skeleton (T7) runs end to
end. Source is under `src/aqelyn/`, tests under `tests/`. The tickets below are
retained as the specification of what was built and the acceptance criteria each
satisfies.

---

## How to use this bundle

- Build tickets **in order** (T0 → T7); each depends only on earlier ones.
- Each ticket lists its **spec**, **acceptance tests** (the exact pytest ids from
  the spec's Definition-of-Ready table), and **deliverables**.
- A ticket is complete only when its named tests exist and pass. Do not add
  behavior beyond the spec; raise an Engineering Change Request instead.
- Every store ticket ships **two implementations** (in-memory + Postgres) behind
  one interface, and both pass the **same** contract suite.

## Target source layout (under the fixed `src/` root)

```
src/aqelyn/
├── conventions/      # ids, time, canonical_json, errors, logging  (T1)
├── objects/          # AQObject/AQRelationship models + ObjectStore (T2)
├── events/           # Event model + EventBus (in-memory, redis)    (T3)
├── evidence/         # EvidenceRecord + EvidenceStore + BlobStore   (T4)
├── findings/         # Finding model + FindingStore                 (T5)
├── kernel/           # AQService, AQKernel, wiring, config, health  (T6)
└── __init__.py
tests/                # mirrors the package tree; contract suites shared
```

---

## T0 — Project scaffold & CI  ✅ DONE

**Deliverables:** `pyproject.toml` (name `aqelyn`, Python 3.12), `ruff` +
`mypy --strict` config, `pytest` + `pytest-asyncio`, `docker-compose.yml`
(app + Postgres 16 + Redis), `.env.example`, pre-commit, GitHub Actions running
lint+type+test. Dependencies: `pydantic>=2`, `pydantic-settings`, `uuid-utils`,
`asyncpg`/SQLAlchemy, `redis`.
**Depends on:** ADR-0001.
**Acceptance:** CI green on an empty test; `docker compose up` starts
Postgres+Redis; `mypy --strict` and `ruff` pass.

## T1 — Conventions library  ✅ DONE

**Spec:** `CONVENTIONS.spec.md`.
**Deliverables:** typed-ID encode/decode (`obj_…` etc.), UUIDv7 generation,
UTC RFC3339 helpers, **canonical JSON** serializer, `AQError` base + all error
codes, structured JSON logging with redaction, tenancy scoping helper.
**Depends on:** T0.
**Acceptance tests:** `test_conv_id_roundtrip`, `test_conv_canonical_json_stable`,
`test_conv_error_codes_unique`, `test_conv_logging_redaction`,
`test_conv_timestamp_format`.

## T2 — Universal Object Model  ✅ DONE

**Spec:** `EA-0002-universal-object-model.spec.md`.
**Deliverables:** Pydantic `AQObject`/`AQRelationship`/`Subject`-free types,
`ObjectStore` protocol, `InMemoryObjectStore`, `PostgresObjectStore` + DDL
(`aq_object`, `aq_object_natural_key`, `aq_object_source`, `aq_relationship`,
`aq_object_history`), type registry, upsert/merge, soft-delete + history,
optimistic concurrency, tenant scoping.
**Depends on:** T1.
**Acceptance tests:** `test_uom_id_assigned_and_immutable`,
`test_uom_unknown_object_type_rejected`, `test_uom_attributes_validated`,
`test_uom_upsert_dedup_by_natural_key`, `test_uom_optimistic_conflict`,
`test_uom_requires_provenance`, `test_uom_soft_delete_and_history`,
`test_uom_merge_survivor_redirect`, `test_uom_tenant_scoping`,
`test_uom_history_append_only`, `test_uom_store_contract[inmemory|postgres]`,
`test_uom_cross_tenant_edge_rejected`.

## T3 — Event Envelope & Bus  ✅ DONE

**Spec:** `EA-0003-event-envelope-and-bus.spec.md`.
**Deliverables:** `Event`/`Subject` models, event-type registry (+ core events),
`EventBus` protocol, `InMemoryEventBus`, `RedisStreamsEventBus`, append-only
`aq_event_log` + `aq_event_dlq`, retries/backoff/dead-letter, replay,
broadcast + consumer groups, backpressure.
**Depends on:** T2.
**Acceptance tests:** `test_bus_unknown_event_type_rejected`,
`test_bus_payload_validated`, `test_bus_broadcast_fanout`,
`test_bus_consumer_group_once`, `test_bus_at_least_once_redelivery`,
`test_bus_partition_ordering`, `test_bus_retry_then_dlq`,
`test_bus_event_logged_for_audit`, `test_bus_replay_since`,
`test_bus_backpressure_raises`, `test_bus_contract[inmemory|redis]`,
`test_bus_cross_tenant_rejected`, `test_bus_publish_many_atomic`.

## T4 — Evidence & Integrity  ✅ DONE

**Spec:** `EA-0004-evidence-and-integrity.spec.md`.
**Deliverables:** `EvidenceRecord`/`BlobRef`/`EvidencePackage` models,
`EvidenceStore` + `BlobStore` protocols, in-memory + Postgres stores + DDL
(`aq_evidence`, `aq_evidence_custody`, `aq_evidence_package`), hash-chain
append + verify + verify_chain, packages, custody logging, emits
`aqelyn.evidence.recorded` (registered here).
**Depends on:** T3.
**Acceptance tests:** `test_evd_chain_fields_assigned`, `test_evd_content_hash`,
`test_evd_content_xor_ref`, `test_evd_immutable`,
`test_evd_verify_detects_tamper`, `test_evd_verify_chain_break`,
`test_evd_custody_logged`, `test_evd_package_self_verifying`,
`test_evd_emits_event`, `test_evd_tenant_isolation`, `test_evd_blob_integrity`,
`test_evd_store_contract[inmemory|postgres]`.

## T5 — Finding model  ✅ DONE

**Spec:** `Finding-model.spec.md`.
**Deliverables:** `Finding`/`Remediation`/`Automation`/`AuditEntry` models,
`FindingStore` protocol, in-memory + Postgres stores + DDL (`aq_finding`,
`aq_finding_evidence`, `aq_finding_asset`, `aq_finding_audit`), mandatory-field
enforcement, evidence-required, dedup/reopen, transition validation, emits
`aqelyn.finding.raised|status_changed|regressed` (registered here).
**Depends on:** T4.
**Acceptance tests:** `test_finding_requires_explanation`,
`test_finding_requires_evidence`, `test_finding_dedup`,
`test_finding_regression_reopen`, `test_finding_invalid_transition`,
`test_finding_transition_audited`, `test_finding_raised_event`,
`test_finding_evidence_exists`, `test_finding_tenant_isolation`,
`test_finding_store_contract[inmemory|postgres]`.

## T6 — Kernel & wiring  ✅ DONE

**Spec:** `EA-0001-kernel.spec.md`.
**Deliverables:** `AQService`/`HealthStatus`/`KernelState`/`AQKernel`, service
registry + topo-sort, dependency-ordered start/stop, DI of all stores + bus +
config + logging, health/readiness aggregation, degraded mode, signal handling,
graceful shutdown, object→event emission wiring, `runtime_started|stopped`.
**Depends on:** T5.
**Acceptance tests:** `test_kernel_ordered_lifecycle`,
`test_kernel_cycle_detected`, `test_kernel_critical_fail_aborts`,
`test_kernel_degraded_mode`, `test_kernel_dependency_injection`,
`test_kernel_health_aggregation`, `test_kernel_readiness`,
`test_kernel_lifecycle_events`, `test_kernel_sigterm_graceful`,
`test_kernel_config_error`, `test_kernel_inmemory_only`.

## T7 — C-001 Walking Skeleton (the proof)  ✅ DONE

**Spec:** `EA-0001-kernel.spec.md` §9.
**Deliverables:** an end-to-end test/app path: `kernel.start()` → create a
`generic` object → `aqelyn.object.created` published → subscriber records an
`EvidenceRecord` → a `Finding` is raised citing that evidence + object →
`health() == healthy, ready` → `kernel.stop()` → `runtime_stopped`, phase
`stopped`. Runs on **in-memory infra with no external services**, and again on
the Postgres+Redis compose stack.
**Depends on:** T6.
**Acceptance test:** `test_c001_walking_skeleton` (green on both in-memory and
docker-compose profiles).

---

## Review protocol (Claude Code)

For each ticket, the reviewer confirms:
1. Every named acceptance test exists and passes (in-memory **and** backing-store
   variants where specified).
2. No field/type/event/error outside the spec; no undocumented behavior
   (START_HERE rule 4).
3. CONVENTIONS honored (IDs, timestamps, canonical JSON, tenancy, logging/no
   secrets).
4. Append-only audit surfaces have no update/delete code path.
5. `mypy --strict` + `ruff` clean; interfaces match the spec signatures exactly.

A ticket merges only on a green review. C-001 closes when T7 is green on both
profiles.
