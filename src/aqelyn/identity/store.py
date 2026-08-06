"""Identity store contracts — the async surface every backend implements (ECR-0116).

ECR-0115 shipped a file-backed, synchronous bootstrap to pin down the model and the one
isolation rule that matters. ECR-0116 moves identity onto the standard backend pair every
other domain in this codebase uses — an in-memory store for tests and local runs, an asyncpg
store for durable production — behind these async protocols. Method names and semantics are
unchanged from ECR-0115; only sync→async and file→Postgres change, because asyncpg is the only
driver available and the authenticated ingest app (ECR-0118) is itself async.

**The isolation rule this module exists to hold, unchanged since ECR-0115:** a tenant is taken
from the session (``Session.tenant_id``, resolved from the authenticated account), never from
anything the client sends. Callers read ``session.tenant_id`` and pass it down; they never
accept a tenant id from a request body or query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aqelyn.identity.models import Account, Invite


class IdentityError(Exception):
    """An account operation was refused."""


class InviteError(IdentityError):
    """An invite could not be redeemed."""


@dataclass(frozen=True)
class Session:
    token: str
    account_id: str
    tenant_id: str
    expires_at: datetime


class AccountStore(Protocol):
    async def create(self, *, email: str, tenant_id: str, password: str) -> Account: ...
    async def get(self, account_id: str) -> Account | None: ...
    async def get_by_email(self, email: str) -> Account | None: ...
    async def authenticate(self, email: str, password: str) -> Account | None: ...


class InviteStore(Protocol):
    async def create(self, *, tenant_id: str, email: str | None = None) -> Invite: ...
    async def redeem(self, *, token: str, password: str, email: str | None = None) -> Account: ...


class SessionStore(Protocol):
    async def start(self, account: Account) -> Session: ...
    async def resolve(self, token: str | None) -> Session | None: ...
    async def end(self, token: str) -> None: ...
