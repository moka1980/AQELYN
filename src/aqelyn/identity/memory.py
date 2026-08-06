"""In-memory identity stores — the test and local-run backend (ECR-0116).

Ephemeral (a restart empties them), which is exactly the ``backend=memory`` posture the rest of
the platform runs locally. Production durability is the Postgres backend. These hold the same
contract and the same guards as the file-backed ECR-0115 bootstrap they replace, now async.
"""

from __future__ import annotations

import asyncio

# Aliased: the GC-004 persisted-field census matches the bare name `secrets` against the
# secrets package's exempt `secrets` field. The alias keeps our stdlib use unambiguous.
import secrets as _rand
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from aqelyn.conventions.ids import new_id
from aqelyn.identity.models import Account, Invite
from aqelyn.identity.passwords import hash_password, verify_password
from aqelyn.identity.store import IdentityError, InviteError, Session


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InMemoryAccountStore:
    def __init__(self, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._by_id: dict[str, Account] = {}
        self._now = now
        self._lock = asyncio.Lock()

    async def get(self, account_id: str) -> Account | None:
        return self._by_id.get(account_id)

    async def get_by_email(self, email: str) -> Account | None:
        return next((a for a in self._by_id.values() if a.email.lower() == email.lower()), None)

    async def create(self, *, email: str, tenant_id: str, password: str) -> Account:
        async with self._lock:
            if any(a.email.lower() == email.lower() for a in self._by_id.values()):
                raise IdentityError("email already registered")
            account = Account(
                id=new_id("acc"),
                email=email,
                tenant_id=tenant_id,
                password=hash_password(password),
                created_at=self._now(),
            )
            self._by_id[account.id] = account
            return account

    async def authenticate(self, email: str, password: str) -> Account | None:
        account = await self.get_by_email(email)
        if account is None or account.status != "active":
            return None
        return account if verify_password(password, account.password) else None


class InMemoryInviteStore:
    def __init__(
        self,
        accounts: InMemoryAccountStore,
        *,
        ttl: timedelta = timedelta(days=7),
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._accounts = accounts
        self._by_token: dict[str, Invite] = {}
        self._ttl = ttl
        self._now = now
        self._lock = asyncio.Lock()

    async def create(self, *, tenant_id: str, email: str | None = None) -> Invite:
        async with self._lock:
            invite = Invite(
                id=new_id("inv"),
                token=_rand.token_urlsafe(32),
                tenant_id=tenant_id,
                email=email,
                created_at=self._now(),
                expires_at=self._now() + self._ttl,
            )
            self._by_token[invite.token] = invite
            return invite

    async def redeem(self, *, token: str, password: str, email: str | None = None) -> Account:
        async with self._lock:
            invite = self._by_token.get(token)
            if invite is None:
                raise InviteError("unknown invite")
            if invite.redeemed_by is not None:
                raise InviteError("invite already used")
            if self._now() > invite.expires_at:
                raise InviteError("invite expired")
            address = invite.email or email
            if address is None:
                raise InviteError("an email is required to redeem this invite")
            if (
                invite.email is not None
                and email is not None
                and email.lower() != invite.email.lower()
            ):
                raise InviteError("email does not match the invite")
            account = await self._accounts.create(
                email=address, tenant_id=invite.tenant_id, password=password
            )
            self._by_token[token] = invite.model_copy(update={"redeemed_by": account.id})
            return account


class InMemorySessionStore:
    def __init__(
        self, *, ttl: timedelta = timedelta(hours=12), now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl
        self._now = now
        self._lock = asyncio.Lock()

    async def start(self, account: Account) -> Session:
        async with self._lock:
            self._reap()
            session = Session(
                token=_rand.token_urlsafe(32),
                account_id=account.id,
                # tenant is bound here from the account, never from the client
                tenant_id=account.tenant_id,
                expires_at=self._now() + self._ttl,
            )
            self._sessions[session.token] = session
            return session

    async def resolve(self, token: str | None) -> Session | None:
        if not token:
            return None
        async with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if self._now() > session.expires_at:
                self._sessions.pop(token, None)
                return None
            return session

    async def end(self, token: str) -> None:
        async with self._lock:
            self._sessions.pop(token, None)

    def _reap(self) -> None:
        now = self._now()
        for token in [t for t, s in self._sessions.items() if s.expires_at <= now]:
            self._sessions.pop(token, None)
