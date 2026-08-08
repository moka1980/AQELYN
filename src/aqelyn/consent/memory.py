"""In-memory consent and audit stores — the test and local-run backend (ECR-0117)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from aqelyn.consent.models import AuditAction, AuditEvent, ConsentRecord, ConsentScope
from aqelyn.conventions.ids import new_id


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InMemoryConsentStore:
    def __init__(self, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._records: list[ConsentRecord] = []
        self._now = now
        self._lock = asyncio.Lock()

    async def record(
        self, *, tenant_id: str, account_id: str, scope: ConsentScope, text_version: str
    ) -> ConsentRecord:
        async with self._lock:
            record = ConsentRecord(
                id=new_id("con"),
                tenant_id=tenant_id,
                account_id=account_id,
                scope=scope,
                text_version=text_version,
                granted_at=self._now(),
            )
            self._records.append(record)
            return record

    async def active(self, *, tenant_id: str, scope: ConsentScope) -> ConsentRecord | None:
        candidates = [
            r
            for r in self._records
            if r.tenant_id == tenant_id and r.scope == scope and r.revoked_at is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.granted_at)

    async def revoke(self, *, tenant_id: str, scope: ConsentScope) -> None:
        async with self._lock:
            now = self._now()
            for index, record in enumerate(self._records):
                if (
                    record.tenant_id == tenant_id
                    and record.scope == scope
                    and record.revoked_at is None
                ):
                    self._records[index] = record.model_copy(update={"revoked_at": now})

    def _snapshot(self) -> list[ConsentRecord]:
        """State capture for ECR-0124's atomic composites (memory backend only)."""

        return list(self._records)

    def _restore(self, snapshot: list[ConsentRecord]) -> None:
        self._records = list(snapshot)


class InMemoryAuditLog:
    def __init__(self, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._events: list[AuditEvent] = []
        self._now = now
        self._lock = asyncio.Lock()

    async def append(
        self, *, tenant_id: str, actor_account_id: str, action: AuditAction, detail: str
    ) -> AuditEvent:
        async with self._lock:
            event = AuditEvent(
                id=new_id("aud"),
                tenant_id=tenant_id,
                actor_account_id=actor_account_id,
                action=action,
                detail=detail,
                at=self._now(),
            )
            self._events.append(event)
            return event

    async def list(self, *, tenant_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.tenant_id == tenant_id]

    def _snapshot(self) -> tuple[AuditEvent, ...]:
        """State capture for ECR-0124's atomic composites (memory backend only). The public
        surface stays append-only; a restore is the composite's transaction rollback."""

        return tuple(self._events)

    def _restore(self, snapshot: tuple[AuditEvent, ...]) -> None:
        self._events = [*snapshot]
