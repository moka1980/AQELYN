"""Atomic audited writes for the portal (ECR-0124).

ECR-0118 persisted consent and scan state first and appended the required audit event as a
second, independent step — so a failing audit returned 500 while leaving persisted-but-unaudited
state behind (Codex review of ECR-0115…0121, 2026-08-08). These composites make the write and
its audit event one atomic unit on both backends:

- **Postgres**: every row — consent, object, evidence, finding, audit — is written on ONE
  connection inside ONE transaction. All stores live in the same database, so a failure anywhere
  rolls the whole unit back. EVERY event (object, evidence, finding) is collected during the
  unit and published only after the commit, in original order — a rolled-back unit never
  announced anything (no phantom events).
- **Memory**: the composite snapshots the in-process stores, swaps their event sink/bus for
  buffers, applies the writes, and on any failure restores every store and drops the buffered
  events; on success the buffer flushes to the real bus in original order. A lock serializes
  composites so a restore cannot revert a concurrent request's writes — the memory backend is
  the test/dev backend; the deployed portal runs Postgres.

The portal application performs its audited writes ONLY through this seam; it holds no direct
audit-log reference, so a future handler cannot quietly reintroduce the two-step shape.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from aqelyn.consent.memory import InMemoryAuditLog, InMemoryConsentStore
from aqelyn.consent.models import ConsentRecord, ConsentScope
from aqelyn.consent.postgres import PostgresAuditLog, PostgresConsentStore
from aqelyn.conventions import ActorRef
from aqelyn.events import Event, EventBus
from aqelyn.events.bus import EventHandler, Subscription
from aqelyn.evidence.memory import InMemoryEvidenceStore
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.evidence.postgres import PostgresEvidenceStore
from aqelyn.findings.memory import InMemoryFindingStore
from aqelyn.findings.models import Finding
from aqelyn.findings.postgres import PostgresFindingStore
from aqelyn.kernel.factory import Runtime
from aqelyn.objects.memory import InMemoryObjectStore
from aqelyn.objects.models import AQObject
from aqelyn.objects.postgres import PostgresObjectStore
from aqelyn.portal.ingest import IngestWriteOps, ingest_posture_document


class _BufferedObjectSink:
    """Buffers `object_event` calls as replay thunks against the real sink (ECR-0124)."""

    def __init__(self, real: Any, deferred: list[Callable[[], Awaitable[None]]]) -> None:
        self._real = real
        self._deferred = deferred

    async def object_event(
        self,
        event_type: str,
        *,
        object_id: str,
        tenant_id: str | None,
        payload: dict[str, Any],
        actor: ActorRef,
    ) -> None:
        real = self._real

        async def _replay() -> None:
            await real.object_event(
                event_type,
                object_id=object_id,
                tenant_id=tenant_id,
                payload=payload,
                actor=actor,
            )

        self._deferred.append(_replay)


class _BufferedBus:
    """Buffers `publish` calls as replay thunks against the real bus (ECR-0124). The write
    path only publishes; subscribe/replay are not part of an atomic unit and refuse."""

    def __init__(self, real: EventBus, deferred: list[Callable[[], Awaitable[None]]]) -> None:
        self._real = real
        self._deferred = deferred

    async def publish(self, event: Event) -> None:
        real = self._real

        async def _replay() -> None:
            await real.publish(event)

        self._deferred.append(_replay)

    async def publish_many(self, events: list[Event]) -> None:
        for event in events:
            await self.publish(event)

    async def subscribe(
        self, pattern: str, handler: EventHandler, *, group: str | None = None
    ) -> Subscription:
        raise RuntimeError("a buffered bus only publishes")

    async def replay(
        self, *, since: object, pattern: str | None = None, handler: EventHandler
    ) -> int:
        raise RuntimeError("a buffered bus only publishes")


class AuditedWrites(Protocol):
    """A portal write paired with the audit event that records it, atomically."""

    async def grant_consent(
        self, *, tenant_id: str, account_id: str, scope: ConsentScope, text_version: str
    ) -> ConsentRecord: ...

    async def ingest_scan(
        self,
        document: Mapping[str, Any],
        *,
        tenant_id: str,
        account_id: str,
        digest: str,
        observed_at: datetime,
        actor: ActorRef,
    ) -> list[Finding]: ...


class MemoryAuditedWrites:
    """All-or-nothing via snapshot/restore of the in-process stores."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        consent: InMemoryConsentStore,
        audit: InMemoryAuditLog,
    ) -> None:
        if not (
            isinstance(runtime.object_store, InMemoryObjectStore)
            and isinstance(runtime.evidence_store, InMemoryEvidenceStore)
            and isinstance(runtime.finding_store, InMemoryFindingStore)
        ):
            raise TypeError("MemoryAuditedWrites requires the in-memory runtime stores")
        self._runtime = runtime
        self._objects = runtime.object_store
        self._evidence = runtime.evidence_store
        self._findings = runtime.finding_store
        self._consent = consent
        self._audit = audit
        self._lock = asyncio.Lock()

    async def grant_consent(
        self, *, tenant_id: str, account_id: str, scope: ConsentScope, text_version: str
    ) -> ConsentRecord:
        async with self._lock:
            consent_snapshot = self._consent._snapshot()
            audit_snapshot = self._audit._snapshot()
            try:
                record = await self._consent.record(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    scope=scope,
                    text_version=text_version,
                )
                await self._audit.append(
                    tenant_id=tenant_id,
                    actor_account_id=account_id,
                    action="consent_granted",
                    detail=text_version,
                )
                return record
            except BaseException:
                self._consent._restore(consent_snapshot)
                self._audit._restore(audit_snapshot)
                raise

    async def ingest_scan(
        self,
        document: Mapping[str, Any],
        *,
        tenant_id: str,
        account_id: str,
        digest: str,
        observed_at: datetime,
        actor: ActorRef,
    ) -> list[Finding]:
        async with self._lock:
            objects_snapshot = self._objects._snapshot()
            evidence_snapshot = self._evidence._snapshot()
            findings_snapshot = self._findings._snapshot()
            audit_snapshot = self._audit._snapshot()
            # Divert every event the stores would announce into a buffer; a failed unit's
            # events are dropped with its rows — the bus never hears about phantom state.
            deferred: list[Callable[[], Awaitable[None]]] = []
            real_sink = self._objects._sink
            real_evidence_bus = self._evidence._bus
            real_finding_bus = self._findings._bus
            if real_sink is not None:
                self._objects._sink = _BufferedObjectSink(real_sink, deferred)
            if real_evidence_bus is not None:
                self._evidence._bus = _BufferedBus(real_evidence_bus, deferred)
            if real_finding_bus is not None:
                self._findings._bus = _BufferedBus(real_finding_bus, deferred)
            try:
                findings = await ingest_posture_document(
                    self._runtime,
                    document,
                    tenant_id=tenant_id,
                    digest=digest,
                    observed_at=observed_at,
                    actor=actor,
                )
                await self._audit.append(
                    tenant_id=tenant_id,
                    actor_account_id=account_id,
                    action="scan_ingested",
                    detail=digest,
                )
            except BaseException:
                self._objects._restore(objects_snapshot)
                self._evidence._restore(evidence_snapshot)
                self._findings._restore(findings_snapshot)
                self._audit._restore(audit_snapshot)
                raise
            finally:
                self._objects._sink = real_sink
                self._evidence._bus = real_evidence_bus
                self._findings._bus = real_finding_bus
            # Only a committed unit announces itself, in original order.
            for replay in deferred:
                await replay()
            return findings


class PostgresAuditedWrites:
    """One connection, one transaction, every row — the durable production composite."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        consent: PostgresConsentStore,
        audit: PostgresAuditLog,
    ) -> None:
        if not (
            isinstance(runtime.object_store, PostgresObjectStore)
            and isinstance(runtime.evidence_store, PostgresEvidenceStore)
            and isinstance(runtime.finding_store, PostgresFindingStore)
        ):
            raise TypeError("PostgresAuditedWrites requires the Postgres runtime stores")
        if consent._pool is not audit._pool:
            raise ValueError("consent and audit must share one pool (ECR-0117's connect_pool)")
        self._runtime = runtime
        self._objects = runtime.object_store
        self._evidence = runtime.evidence_store
        self._findings = runtime.finding_store
        self._consent = consent
        self._audit = audit
        self._pool = audit._pool

    async def grant_consent(
        self, *, tenant_id: str, account_id: str, scope: ConsentScope, text_version: str
    ) -> ConsentRecord:
        async with self._pool.acquire() as conn, conn.transaction():
            record = await self._consent._record_on(
                conn,
                tenant_id=tenant_id,
                account_id=account_id,
                scope=scope,
                text_version=text_version,
            )
            await self._audit._append_on(
                conn,
                tenant_id=tenant_id,
                actor_account_id=account_id,
                action="consent_granted",
                detail=text_version,
            )
        return record

    async def ingest_scan(
        self,
        document: Mapping[str, Any],
        *,
        tenant_id: str,
        account_id: str,
        digest: str,
        observed_at: datetime,
        actor: ActorRef,
    ) -> list[Finding]:
        objects = self._objects
        evidence = self._evidence
        finding_store = self._findings
        # Every event the unit produces, in original order, published only after the commit —
        # a rolled-back unit never announced anything (no phantom events).
        deferred: list[Callable[[], Awaitable[None]]] = []
        async with self._pool.acquire() as conn, conn.transaction():

            async def _upsert(obj: AQObject) -> AQObject:
                result, event_type, event_actor, payload = await objects._upsert_on(conn, obj)

                async def _replay() -> None:
                    await objects._emit(event_type, result, event_actor, payload)

                deferred.append(_replay)
                return result

            async def _add(record: EvidenceRecord) -> EvidenceRecord:
                rec = await evidence._add_on(conn, record)

                async def _replay() -> None:
                    await evidence._emit_recorded(rec)

                deferred.append(_replay)
                return rec

            async def _exists(evidence_id: str) -> bool:
                # The gate must look at THIS uncommitted transaction, not another connection.
                return await evidence._exists_on(conn, evidence_id)

            async def _raise(f: Finding) -> Finding:
                result, event_type, payload = await finding_store._raise_on(
                    conn, f, evidence_exists=_exists
                )
                if event_type is not None:
                    fixed_event_type = event_type

                    async def _replay() -> None:
                        await finding_store._emit(fixed_event_type, result, payload)

                    deferred.append(_replay)
                return result

            findings = await ingest_posture_document(
                self._runtime,
                document,
                tenant_id=tenant_id,
                digest=digest,
                observed_at=observed_at,
                actor=actor,
                ops=IngestWriteOps(upsert=_upsert, add_evidence=_add, raise_finding=_raise),
            )
            await self._audit._append_on(
                conn,
                tenant_id=tenant_id,
                actor_account_id=account_id,
                action="scan_ingested",
                detail=digest,
            )
        # Only a committed unit announces itself, in original order.
        for replay in deferred:
            await replay()
        return findings
