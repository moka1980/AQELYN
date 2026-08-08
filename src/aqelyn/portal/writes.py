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
- **Memory**: the same shape as Postgres, through the same injected-ops seam — each store
  exposes a quiet write (`_upsert_quiet`/`_add_quiet`/`_raise_quiet`) that returns its event
  and a precise undo of that one write. The composite defers the events and, on failure, runs
  the undos in reverse — touching ONLY the rows its own unit wrote, so an unrelated concurrent
  write is never rolled back with it, and no shared wiring is ever mutated. The audit append is
  the unit's final write, so a failed audit has nothing of its own to undo. A lock still
  serializes composites against each other.

The portal application performs its audited writes ONLY through this seam; it holds no direct
audit-log reference, so a future handler cannot quietly reintroduce the two-step shape.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from aqelyn.consent.memory import InMemoryAuditLog, InMemoryConsentStore
from aqelyn.consent.models import ConsentRecord, ConsentScope
from aqelyn.consent.postgres import PostgresAuditLog, PostgresConsentStore
from aqelyn.conventions import ActorRef
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
    """All-or-nothing via per-write undo journaling — only the unit's own rows roll back."""

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
            record = await self._consent.record(
                tenant_id=tenant_id,
                account_id=account_id,
                scope=scope,
                text_version=text_version,
            )
            try:
                await self._audit.append(
                    tenant_id=tenant_id,
                    actor_account_id=account_id,
                    action="consent_granted",
                    detail=text_version,
                )
            except BaseException:
                # The audit append is the unit's final write: undo exactly the consent row
                # this unit wrote, nothing else.
                self._consent._discard(record.id)
                raise
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
        async with self._lock:
            # The Postgres shape through the same seam: quiet per-write ops that return their
            # event and a precise undo. A failed unit undoes ONLY its own rows (in reverse) and
            # its events are never published; shared wiring is never touched, so an unrelated
            # concurrent write survives the rollback untouched.
            undo_stack: list[Callable[[], None]] = []
            deferred: list[Callable[[], Awaitable[None]]] = []

            async def _upsert(obj: AQObject) -> AQObject:
                live, event_type, event_actor, payload, undo = await objects._upsert_quiet(obj)
                undo_stack.append(undo)

                async def _replay() -> None:
                    await objects._emit(event_type, live, event_actor, payload)

                deferred.append(_replay)
                return copy.deepcopy(live)

            async def _add(record: EvidenceRecord) -> EvidenceRecord:
                rec, undo = await evidence._add_quiet(record)
                undo_stack.append(undo)

                async def _replay() -> None:
                    if evidence._bus is not None:
                        await evidence._emit(rec)

                deferred.append(_replay)
                return rec

            async def _raise(f: Finding) -> Finding:
                live, event_type, payload, undo = await finding_store._raise_quiet(f)
                undo_stack.append(undo)
                if event_type is not None:
                    fixed_event_type = event_type

                    async def _replay() -> None:
                        await finding_store._emit(fixed_event_type, live, payload)

                    deferred.append(_replay)
                return copy.deepcopy(live)

            try:
                findings = await ingest_posture_document(
                    self._runtime,
                    document,
                    tenant_id=tenant_id,
                    digest=digest,
                    observed_at=observed_at,
                    actor=actor,
                    ops=IngestWriteOps(upsert=_upsert, add_evidence=_add, raise_finding=_raise),
                )
                # The audit append is the unit's final write; if it fails, nothing of the
                # unit survives — and nothing was ever announced.
                await self._audit.append(
                    tenant_id=tenant_id,
                    actor_account_id=account_id,
                    action="scan_ingested",
                    detail=digest,
                )
            except BaseException:
                for undo in reversed(undo_stack):
                    undo()
                raise
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
