"""Atomic audited writes for the portal (ECR-0124).

ECR-0118 persisted consent and scan state first and appended the required audit event as a
second, independent step — so a failing audit returned 500 while leaving persisted-but-unaudited
state behind (Codex review of ECR-0115…0121, 2026-08-08). These composites make the write and
its audit event one atomic unit on both backends:

- **Postgres**: every row — consent, object, evidence, finding, audit — is written on ONE
  connection inside ONE transaction. All stores live in the same database, so a failure anywhere
  rolls the whole unit back. Event-bus emission for evidence/findings is deferred until after
  the commit (the stores' own post-commit convention); object events still publish inside the
  transaction, a pre-existing property disclosed in the ECR.
- **Memory**: the composite snapshots the in-process stores, applies the writes, and restores
  every store on any failure. A lock serializes composites so a restore cannot revert a
  concurrent request's writes — the memory backend is the test/dev backend; the deployed portal
  runs Postgres.

The portal application performs its audited writes ONLY through this seam; it holds no direct
audit-log reference, so a future handler cannot quietly reintroduce the two-step shape.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
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
                return findings
            except BaseException:
                self._objects._restore(objects_snapshot)
                self._evidence._restore(evidence_snapshot)
                self._findings._restore(findings_snapshot)
                self._audit._restore(audit_snapshot)
                raise


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
        added_evidence: list[EvidenceRecord] = []
        deferred_events: list[tuple[str, Finding, dict[str, object]]] = []
        async with self._pool.acquire() as conn, conn.transaction():

            async def _upsert(obj: AQObject) -> AQObject:
                return await objects._upsert_on(conn, obj)

            async def _add(record: EvidenceRecord) -> EvidenceRecord:
                rec = await evidence._add_on(conn, record)
                added_evidence.append(rec)
                return rec

            async def _exists(evidence_id: str) -> bool:
                # The gate must look at THIS uncommitted transaction, not another connection.
                return await evidence._exists_on(conn, evidence_id)

            async def _raise(f: Finding) -> Finding:
                result, event_type, payload = await finding_store._raise_on(
                    conn, f, evidence_exists=_exists
                )
                if event_type is not None:
                    deferred_events.append((event_type, result, payload))
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
        # Only a committed unit announces itself (the stores' own post-commit convention).
        for rec in added_evidence:
            await evidence._emit_recorded(rec)
        for event_type, result, payload in deferred_events:
            await finding_store._emit(event_type, result, payload)
        return findings
