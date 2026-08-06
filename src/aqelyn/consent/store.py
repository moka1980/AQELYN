"""Consent and audit store contracts (ECR-0117).

Two async protocols, each backed by an in-memory store for tests and an asyncpg store for
production, exactly like identity (ECR-0116). Both are **tenant-scoped**: every read and write
takes a ``tenant_id`` and touches only that tenant's rows. The audit log is **append-only** — it
exposes ``append`` and ``list`` and no way to update or delete a recorded event.
"""

from __future__ import annotations

from typing import Protocol

from aqelyn.consent.models import AuditAction, AuditEvent, ConsentRecord, ConsentScope


class ConsentError(Exception):
    """A consent operation was refused."""


class ConsentStore(Protocol):
    async def record(
        self, *, tenant_id: str, account_id: str, scope: ConsentScope, text_version: str
    ) -> ConsentRecord: ...

    async def active(self, *, tenant_id: str, scope: ConsentScope) -> ConsentRecord | None: ...

    async def revoke(self, *, tenant_id: str, scope: ConsentScope) -> None: ...


class AuditLog(Protocol):
    async def append(
        self, *, tenant_id: str, actor_account_id: str, action: AuditAction, detail: str
    ) -> AuditEvent: ...

    async def list(self, *, tenant_id: str) -> list[AuditEvent]: ...
