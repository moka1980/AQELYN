# CONVENTIONS — Platform-Wide Engineering Conventions — Specification

**Realizes:** Cross-cutting foundation conventions (referenced by EA-0001–EA-0005, Finding model, and all later EAs)
**Depends on:** ADR-0001 (Runtime & Stack)
**Status:** Accepted

This is the single source of truth for conventions every AQELYN spec and module
relies on. Other specs reference this rather than restating it.

---

## 1. Identifiers

- ID payload: **UUIDv7** (time-ordered), app-generated (`uuid-utils`).
- Canonical and persisted ID form: `{prefix}_{uuid-hex-without-dashes}` stored
  as PostgreSQL `text`. The prefix is part of the persisted key and foreign
  keys; implementations MUST validate the prefix and UUIDv7 payload with
  `parse_id` before persistence or cross-module reference.
- IDs are **immutable**. Reserved prefixes:

| Prefix | Family | Defined in |
|---|---|---|
| `obj` | Object | EA-0002 |
| `rel` | Relationship | EA-0002 |
| `src` | Source | EA-0002 |
| `evt` | Event | EA-0003 |
| `evd` | Evidence | EA-0004 |
| `pkg` | Evidence package | EA-0004 |
| `fnd` | Finding | Finding model |
| `run` | Workflow run | EA-0008 |
| `snap` | Compliance snapshot | EA-0010 |
| `svc` | Registered service/engine | EA-0001 |

New families MUST register a prefix here before use.

## 2. Timestamps & time

- All timestamps are **UTC**, RFC 3339, microsecond precision, stored as
  `timestamptz`. No local time anywhere in data or logs.
- `occurred_at`/`observed_at` = when the real-world thing happened;
  `recorded_at`/`created_at` = when AQELYN persisted it. Both are kept when they
  differ.

## 3. Canonical JSON (deterministic serialization)

Used wherever content is hashed or signed (Evidence hash-chain EA-0004, package
manifests). Rules:

- UTF-8; object keys sorted lexicographically (code points); no insignificant
  whitespace; `:` and `,` separators only.
- Numbers in shortest round-trip form; integers without decimal point; no `NaN`
  / `Infinity`.
- Strings NFC-normalized.
- The canonical form is what gets hashed. `sha256` is the platform hash.

## 4. Versioning

- **schema_version** — integer, per typed artifact (`object_type`,
  `event_type`, finding type). Incremented on any schema change; old versions
  remain readable (migration path required).
- **version** (optimistic concurrency) — integer starting at 1, +1 per mutation
  (EA-0002/EA-0003).
- **Platform/module version** — semantic versioning `MAJOR.MINOR.PATCH`.
- **Spec/ADR version** — the document's own status + Git history.

## 5. Tenancy convention

- `tenant_id: str | null` on every tenant-owned record, persisted as PostgreSQL
  `text NULL`. **NULL = local / single-tenant install.** Non-null = enterprise
  tenant and MUST validate as a UUID string.
- Local mode scopes all queries to `tenant_id IS NULL`. Enterprise mode requires
  an explicit tenant scope (or admin cross-tenant scope) and rejects unscoped
  access. Cross-tenant references are forbidden.

## 6. Actor references

**This is the canonical definition of `ActorRef`.** Other specs reuse it and
MUST NOT redefine it.

```
ActorRef = { actor_type: "system" | "connector" | "user" | "agent",
             actor_id: string }
```
Every created/changed record and every event carries the responsible actor.

## 7. Confidence

- Single scalar `confidence ∈ [0.0, 1.0]` on objects, relationships, evidence,
  and findings. `1.0` = certain. Per-attribute confidence is a future,
  additive extension (arrives with EA-0004 signals).

## 8. Naming

- `object_type`: lowercase snake, singular — `device`, `identity`, `certificate`.
- `relation_type`: lowercase snake, verb phrase from `from`→`to` — `owns`,
  `runs_on`, `member_of`.
- `event_type`: `aqelyn.<domain>.<past_tense>` dotted lowercase —
  `aqelyn.object.created`.
- Finding type: `aqelyn.finding.<domain>.<slug>`.
- Python: packages/modules `snake_case`, classes `PascalCase`, per EA-0058.
- Env vars: `AQELYN_<AREA>_<NAME>` (12-factor, ADR-0001 D9).

## 9. Error model & taxonomy

- Base exception: `AQError(code: str, message: str, details: dict | null,
  retriable: bool)`. Every raised error is an `AQError` subtype with a stable
  `code`.
- API error envelope:

```json
{ "error": { "code": "OptimisticConcurrencyConflict",
             "message": "…", "details": {}, "trace_id": "…" } }
```

- **Consolidated taxonomy** (contributed by the specs noted):

| Code | Source | Retriable |
|---|---|---|
| `ObjectNotFound` | EA-0002 | no |
| `UnknownObjectType` | EA-0002 | no |
| `SchemaValidationError` | EA-0002 | no |
| `MissingProvenance` | EA-0002 | no |
| `OptimisticConcurrencyConflict` | EA-0002 | yes |
| `TenantScopeRequired` | EA-0002 | no |
| `CrossTenantReference` | EA-0002 | no |
| `StoreUnavailable` | EA-0002 | yes |
| `UnknownEventType` | EA-0003 | no |
| `EventSchemaValidationError` | EA-0003 | no |
| `BusBackpressure` | EA-0003 | yes |
| `CrossTenantEvent` | EA-0003 | no |
| `SubscriptionClosed` | EA-0003 | no |
| `BusUnavailable` | EA-0003 | yes |
| `EvidenceNotFound` | EA-0004 | no |
| `EvidenceTampered` | EA-0004 | no |
| `ChainBroken` | EA-0004 | no |
| `EvidenceImmutable` | EA-0004 | no |
| `FindingNotFound` | Finding | no |
| `InvalidFindingTransition` | Finding | no |
| `EvidenceRequired` | Finding | no |
| `GraphQueryInvalid` | EA-0005 | no |
| `TrustConfigInvalid` | EA-0006 | no |
| `MissionConfigInvalid` | EA-0007 | no |
| `UnknownAction` | EA-0008 | no |
| `UnauthorizedAction` | EA-0008 | no |
| `ApprovalRequired` | EA-0008 | no |
| `ConfirmationRequired` | EA-0008 | no |
| `ActionFailed` | EA-0008 | no |
| `RunNotFound` | EA-0008 | no |
| `PolicyConfigInvalid` | EA-0009 | no |
| `PolicyNotFound` | EA-0009 | no |
| `GovernanceConfigInvalid` | EA-0010 | no |
| `SnapshotNotFound` | EA-0010 | no |
| `ServiceStartFailed` | EA-0001 | maybe |
| `DependencyUnavailable` | EA-0001 | yes |
| `ConfigError` | EA-0001 | no |

## 10. Structured logging

- JSON lines. Required fields: `ts` (UTC RFC3339), `level`, `msg`, `logger`,
  and when present `trace_id`, `correlation_id`, `tenant_id`, `actor`,
  `event_id`, `object_id`.
- **No secrets, credentials, or raw sensitive content in logs** (ADR-0001,
  EA-0058). Evidence content is referenced by `evd_` id, never inlined.

## 11. Consolidated glossary

Object, Relationship, Source/Provenance (EA-0002); Event, Consumer group,
partition_key, Dead-letter, Event log (EA-0003); Evidence record, Hash-chain,
Evidence package, Chain of custody (EA-0004); Finding, Severity, Remediation,
Automation eligibility, Progressive detail (Finding model); Service, Health,
Readiness, Degraded mode (EA-0001). Each term's authoritative definition lives
in the cited spec.

## 12. Acceptance (Definition of Ready)

| # | Criterion | Test |
|---|---|---|
| AC-1 | ID encode/decode round-trips with correct prefix | `test_conv_id_roundtrip` |
| AC-2 | Canonical JSON is stable across key orderings & equal inputs hash equal | `test_conv_canonical_json_stable` |
| AC-3 | `AQError` codes are unique and stable | `test_conv_error_codes_unique` |
| AC-4 | Log records never contain configured secret keys | `test_conv_logging_redaction` |
| AC-5 | Timestamps serialize as UTC RFC3339 microseconds | `test_conv_timestamp_format` |
