# EA-0003 — Event Envelope & Bus Contract — Implementation Specification

**Realizes:** EA-0003 (supersedes the placeholder `archive/EA-0003/EA-0003_Master.md` for implementation)
**Depends on:** ADR-0001 (Runtime & Stack), EA-0002 (Universal Object Model — object IDs, `ActorRef`, `SourceRef`, tenancy)
**Consumed by:** EA-0001 (Kernel wires the bus), EA-0004 (Evidence emits/records events), EA-0005 (Knowledge Graph reacts to object/edge events), Finding pipeline, and every engine (EA-0052+)
**Status:** Accepted
**Definition of Ready:** see §12

---

## 1. Purpose

The Event Bus is how AQELYN subsystems communicate **without direct coupling**:
a producer publishes a fact ("an object was created", "an assessment
completed"), and any number of consumers react. Events are also the platform's
**audit spine** — an append-only record of everything that happened, which
supports the charter's traceability and "how AQELYN knows" promises.

One contract serves both modes (ADR-0001): an **in-memory** bus for C-001 and
local single-process installs, and a **durable Redis Streams** bus for
multi-process / enterprise. Application code depends only on the interface.

## 2. Scope

**In scope:** the event envelope, the event-type registry, delivery semantics
(ordering, at-least-once, idempotency, retries, dead-letter, backpressure), the
`EventBus` / `EventHandler` / `Subscription` interfaces, the Redis Streams
mapping, and the append-only Postgres event log.

**Out of scope:** specific business event payloads beyond the foundation set
(each engine registers its own), workflow orchestration (EA-0032 territory),
and the observability/metrics backend (own ADR later).

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Event** | An immutable record that something happened (past tense). Never a command. |
| **event_type** | Namespaced key, e.g. `aqelyn.object.created`. Registered with a payload schema. |
| **Producer** | Code that publishes events. |
| **Consumer / Handler** | Code that subscribes and reacts. Must be idempotent. |
| **Subscription** | A live registration of a handler to an event-type pattern. |
| **Consumer group** | A set of competing consumers that share the load of a stream (Redis Streams). |
| **partition_key** | The key that defines ordering scope. Events with the same key are ordered; across keys they are not. |
| **Dead-letter (DLQ)** | Where an event goes after exhausting retries, so the stream is never blocked. |
| **Event log** | The append-only durable record of accepted events (audit + replay). |

## 4. Design decisions

- **D1 — Events are immutable facts, past tense.** No commands on the bus. This
  keeps the log a truthful audit record.
- **D2 — At-least-once delivery; consumers are idempotent.** Exactly-once is not
  promised (it is impractical across process crashes). Every handler must
  tolerate seeing an event more than once, keyed by `event.id` /
  `idempotency_key`.
- **D3 — Ordering is per `partition_key`, not global.** Events sharing a key
  (default: the subject object's id) are delivered FIFO; global ordering is not
  guaranteed, because it does not scale. This is a deliberate, honest limit.
- **D4 — Registered event types only.** Publishing an unregistered `event_type`
  is rejected (`UnknownEventType`). Payloads validate against the registered
  JSON Schema for `(event_type, schema_version)`. Governance requirement.
- **D5 — Durable path is an append-only log.** The Redis Streams implementation
  is inherently a log; it is additionally mirrored to a Postgres `aq_event_log`
  table for audit and replay. The in-memory bus (C-001) keeps a bounded buffer
  and is explicitly non-durable.
- **D6 — Poison messages never block the stream.** Retries with backoff, then
  dead-letter (D2/§9).
- **D7 — Same envelope, same contract tests, both implementations** (portability,
  mirrors EA-0002 D-store pattern).

## 5. The event envelope

| Field | Type | Req | Description |
|---|---|---|---|
| `id` | ID (`evt_…`) | yes | Immutable UUIDv7 identifier. |
| `event_type` | string | yes | Registered namespaced key (§7). |
| `schema_version` | int | yes | Version of the payload schema. |
| `tenant_id` | UUID \| null | no | Owning tenant; **NULL in local mode** (consistent with EA-0002). |
| `occurred_at` | timestamp (UTC) | yes | When the real-world thing happened. |
| `recorded_at` | timestamp (UTC) | yes | When the bus accepted the event. |
| `producer` | ActorRef | yes | Who/what emitted it (reuses EA-0002 `ActorRef`). |
| `subject` | Subject | yes | What the event is about (object/evidence/finding refs). |
| `payload` | object (JSONB) | yes | Type-specific body, validated against the registered schema. |
| `partition_key` | string | yes | Ordering scope (§6). Default = subject object id, else tenant, else `id`. |
| `correlation_id` | string | no | Groups all events of one logical workflow/request. |
| `causation_id` | ID \| null | no | The event/command that directly caused this one. |
| `trace_id` | string | no | Distributed-tracing id for observability. |
| `idempotency_key` | string | no | Producer-supplied dedup key; defaults to `id`. |

```
Subject = {
  object_ids:   list[ID(obj_…)]   # zero or more affected objects (EA-0002)
  evidence_id:  ID(evd_…) | null  # filled once EA-0004 exists
  finding_id:   ID(fnd_…) | null  # filled once Finding pipeline exists
}
```

Events are **immutable** once published; corrections are new events, never edits.

## 6. Identifiers, ordering & naming

- `event_type` naming: `aqelyn.<domain>.<past_tense_event>`, lowercase, dotted.
  Examples: `aqelyn.object.created`, `aqelyn.object.merged`,
  `aqelyn.kernel.runtime_started`.
- Subscriptions may use a trailing wildcard: `aqelyn.object.*`.
- `partition_key` resolution order: first subject `object_id` → else
  `tenant_id` (as string) → else the event `id`. This gives **per-object FIFO**
  ordering, which is what consumers actually need.

## 7. Event-type registry & foundation events

- An event type is registered with: `event_type`, `schema_version`, a JSON
  Schema for `payload`, and a `human_label`.
- **Foundation ships these core types** (enough for the C-001 skeleton and the
  standard EA-0002 object operations):

| event_type | Emitted when | Key payload |
|---|---|---|
| `aqelyn.kernel.runtime_started` | Kernel finishes startup | `{ version }` |
| `aqelyn.kernel.runtime_stopped` | Kernel begins shutdown | `{ reason }` |
| `aqelyn.object.created` | New object persisted (EA-0002) | `{ object_type }` |
| `aqelyn.object.updated` | Object mutated | `{ changed_fields }` |
| `aqelyn.object.state_changed` | Lifecycle transition | `{ from, to }` |
| `aqelyn.object.merged` | Two objects merged | `{ survivor_id, duplicate_id }` |
| `aqelyn.relationship.created` | Edge created | `{ relation_type, from_id, to_id }` |

- The EA-0002 `ObjectStore` operations SHOULD emit the corresponding events; the
  wiring (store → bus) is done in EA-0001. This spec defines the events; EA-0001
  connects them.
- **The registry is extensible: each spec registers the event types it owns.**
  This table is the *foundation core* (object/kernel/relationship). Evidence
  events (`aqelyn.evidence.recorded`) are registered by **EA-0004**; finding
  events (`aqelyn.finding.raised`, `aqelyn.finding.status_changed`,
  `aqelyn.finding.regressed`) are registered by the **Finding model**. A type
  must be registered by exactly one owning spec before it may be published.

## 8. Delivery semantics

- **At-least-once** (D2). Consumers dedupe on `id`/`idempotency_key`.
- **Per-partition FIFO** (D3).
- **Two subscription modes:**
  - *Broadcast* (no group): every subscriber to the pattern receives every
    matching event.
  - *Consumer group* (named group): events are load-balanced across the group's
    members; each event handled once per group.
- **Acknowledgement:** durable delivery requires ack. A handler that returns
  normally auto-acks; a handler that raises triggers retry (§9).
- **Backpressure:** queues/streams are bounded. On a full in-memory buffer,
  `publish` raises `BusBackpressure` (never silently drops). Redis Streams uses
  capped streams with monitored lag.

## 9. Retries & dead-letter

- On handler exception: retry with exponential backoff, `max_attempts` default
  **5** (100ms → 200 → 400 → 800 → 1600, jittered).
- After the last attempt: the event is written to the **dead-letter sink**
  (Redis stream `aqelyn:dlq` / Postgres `aq_event_dlq`) with the error and
  attempt count, and processing continues — the stream is never blocked (D6).
- Dead-lettered events are replayable after a fix (operator action).

## 10. Interfaces (Python 3.12)

```python
from typing import Protocol, Callable, Awaitable, Sequence
from datetime import datetime
from pydantic import BaseModel, Field
# ActorRef imported from the EA-0002 object model package

class Subject(BaseModel):
    object_ids: list[str] = Field(default_factory=list)
    evidence_id: str | None = None
    finding_id: str | None = None

class Event(BaseModel):
    id: str
    event_type: str
    schema_version: int
    tenant_id: str | None = None
    occurred_at: datetime
    recorded_at: datetime
    producer: "ActorRef"
    subject: Subject
    payload: dict = Field(default_factory=dict)
    partition_key: str
    correlation_id: str | None = None
    causation_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None

EventHandler = Callable[[Event], Awaitable[None]]   # idempotent; raises to trigger retry

class Subscription(Protocol):
    id: str
    async def unsubscribe(self) -> None: ...

class EventBus(Protocol):
    async def publish(self, event: Event) -> None: ...                 # validates + persists (durable) + dispatches
    async def publish_many(self, events: Sequence[Event]) -> None: ... # atomic batch
    async def subscribe(
        self,
        pattern: str,                     # exact type or trailing wildcard, e.g. "aqelyn.object.*"
        handler: EventHandler,
        *,
        group: str | None = None,         # None = broadcast; set = consumer group
    ) -> Subscription: ...
    async def replay(
        self,
        *,
        since: datetime,
        pattern: str | None = None,
        handler: EventHandler,
    ) -> int: ...                          # re-deliver from the log; returns count (durable only)
```

Two implementations, one contract: `InMemoryEventBus` (C-001) and
`RedisStreamsEventBus` (C-002+). Both pass the identical contract suite (§12
AC-11).

## 11. Persistence

**Durable transport:** Redis Streams — one stream per `event_type` root (or a
single stream partitioned by `partition_key`, chosen at wiring time), consumer
groups for competing consumers, `XAUTOCLAIM` for stuck entries.

**Audit log (append-only, Postgres):**

```sql
CREATE TABLE aq_event_log (
    seq             bigserial PRIMARY KEY,     -- global arrival order (audit only)
    id              uuid        NOT NULL UNIQUE,-- event id (dedup)
    event_type      text        NOT NULL,
    schema_version  int         NOT NULL,
    tenant_id       uuid        NULL,
    partition_key   text        NOT NULL,
    occurred_at     timestamptz NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    producer        jsonb       NOT NULL,
    subject         jsonb       NOT NULL,
    payload         jsonb       NOT NULL,
    correlation_id  text        NULL,
    causation_id    uuid        NULL,
    trace_id        text        NULL
);
CREATE INDEX ix_eventlog_type_time   ON aq_event_log (event_type, recorded_at);
CREATE INDEX ix_eventlog_partition   ON aq_event_log (partition_key, seq);
CREATE INDEX ix_eventlog_correlation ON aq_event_log (correlation_id);
-- Append-only: no UPDATE/DELETE path in code (mirrors EA-0002 history rule).

CREATE TABLE aq_event_dlq (
    seq          bigserial PRIMARY KEY,
    id           uuid        NOT NULL,
    event_type   text        NOT NULL,
    envelope     jsonb       NOT NULL,   -- full event
    error        text        NOT NULL,
    attempts     int         NOT NULL,
    dead_at      timestamptz NOT NULL DEFAULT now(),
    replayed_at  timestamptz NULL
);
```

The in-memory bus keeps a bounded ring buffer only; it is non-durable and
`replay` is limited to the buffer (documented, not silently different).

## 12. Requirements

### Functional (testable)

- **FR-1** `publish` SHALL assign/accept an `evt_` id and reject an event whose `event_type` is not registered (`UnknownEventType`).
- **FR-2** `publish` SHALL validate `payload` against the registered schema for `(event_type, schema_version)` (`EventSchemaValidationError`).
- **FR-3** The bus SHALL deliver each event to every matching broadcast subscriber and once per consumer group.
- **FR-4** Delivery SHALL be at-least-once; the bus SHALL NOT drop an accepted event without either delivering or dead-lettering it.
- **FR-5** Events sharing a `partition_key` SHALL be delivered in publish order (FIFO); cross-key ordering is not required.
- **FR-6** A handler that raises SHALL cause retry with backoff up to `max_attempts`, then dead-letter (§9); the stream SHALL continue.
- **FR-7** The durable bus SHALL append every accepted event to `aq_event_log` before/at delivery (audit), keyed uniquely by `id`.
- **FR-8** `replay(since=…)` SHALL re-deliver logged events in `partition_key` order to the given handler (durable only).
- **FR-9** On a full in-memory buffer, `publish` SHALL raise `BusBackpressure` rather than drop.
- **FR-10** Wildcard subscriptions (`a.b.*`) SHALL match all types under the prefix and nothing outside it.
- **FR-11** `tenant_id` on an event SHALL match the tenant of its subject objects; mismatches SHALL be rejected (`CrossTenantEvent`).
- **FR-12** `publish_many` SHALL be atomic: either all events are accepted+logged or none are.

### Non-functional (initial targets — validated by the C-001 skeleton, confirmed on M-tier hardware)

- **NFR-1 (latency)** in-memory `publish`→dispatch p95 < 2 ms; durable `publish` (incl. log append) p95 < 20 ms.
- **NFR-2 (throughput)** ≥ 5,000 events/s sustained on the durable path on an 8 GB host; ≥ 50,000/s in-memory.
- **NFR-3 (durability)** once `publish` returns on the durable bus, the event survives process restart (present in `aq_event_log`/stream).
- **NFR-4 (no loss/no block)** a poison handler never blocks or loses the stream (dead-letter proven).
- **NFR-5 (portability & typing)** in-memory and Redis buses pass the same contract suite; all modules pass `mypy --strict` + `ruff`.

## 13. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Acceptance criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Unregistered event type rejected | `test_bus_unknown_event_type_rejected` |
| AC-2 | Payload schema validated | `test_bus_payload_validated` |
| AC-3 | Broadcast reaches all subscribers | `test_bus_broadcast_fanout` |
| AC-4 | Consumer group handles once per group | `test_bus_consumer_group_once` |
| AC-5 | At-least-once redelivery on crash before ack | `test_bus_at_least_once_redelivery` |
| AC-6 | Per-partition FIFO preserved | `test_bus_partition_ordering` |
| AC-7 | Handler failure retries then dead-letters | `test_bus_retry_then_dlq` |
| AC-8 | Accepted event appears in `aq_event_log` | `test_bus_event_logged_for_audit` |
| AC-9 | Replay re-delivers from log in order | `test_bus_replay_since` |
| AC-10 | Full in-memory buffer raises backpressure | `test_bus_backpressure_raises` |
| AC-11 | In-memory and Redis buses pass one contract suite | `test_bus_contract[inmemory]` / `[redis]` |
| AC-12 | Cross-tenant event rejected | `test_bus_cross_tenant_rejected` |
| AC-13 | `publish_many` is all-or-nothing | `test_bus_publish_many_atomic` |

## 14. Error taxonomy (this spec's contributions)

`UnknownEventType`, `EventSchemaValidationError`, `BusBackpressure`,
`CrossTenantEvent`, `SubscriptionClosed`, `BusUnavailable`. (Full taxonomy in
the Conventions spec.)

## 15. Failure handling

- Validation failure → typed error, event not accepted, nothing logged.
- Handler failure → retry/backoff → dead-letter; never blocks the stream.
- Bus/broker unavailable → `BusUnavailable`; the Kernel (EA-0001) reports
  degraded state; producers may buffer per their own policy (not the bus's).
- Log write failure on the durable path → `publish` fails closed (event not
  considered accepted), so the audit log can never silently miss an event.

## 16. Dependencies & consumers

- **Depends on:** ADR-0001 (Redis available on Managed M+/self-host; Postgres),
  EA-0002 (`ActorRef`, object ids, tenancy). Library: `redis` (async client).
- **Consumed by:** EA-0001 wires bus + store; EA-0004 sets `subject.evidence_id`
  and emits `aqelyn.evidence.recorded`; Finding pipeline emits
  `aqelyn.finding.raised`; EA-0005 subscribes to `aqelyn.object.*` /
  `aqelyn.relationship.*`.

## 17. Resolved / deferred decisions

- **At-least-once + idempotent consumers** is the accepted delivery model
  (exactly-once explicitly out of scope). Binding for C-001.
- **Per-partition ordering** (not global) is accepted and binding.
- **Single vs per-type streams** for the Redis mapping is a wiring detail
  deferred to EA-0001; it does not affect this contract or its tests.
