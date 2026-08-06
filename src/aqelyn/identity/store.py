"""Account, invite and session stores for ECR-0115.

Accounts and invites are file-backed JSON (0600, atomic write-then-rename), which is durable
today and migrates into Postgres in ECR-0116 without changing this surface. Sessions are
in-memory: a restart requires re-login, which is acceptable and matches the platform login.

**The isolation rule this module exists to hold:** a tenant is taken from the session
(``Session.tenant_id``, resolved from the authenticated account), never from anything the
client sends. Callers must read ``session.tenant_id`` and pass it down; they must never accept
a tenant id from a request body or query.
"""

from __future__ import annotations

import json
import os

# Aliased: the GC-004 persisted-field census matches the bare name `secrets` against the
# secrets package's exempt `secrets` field. The alias keeps our stdlib use unambiguous.
import secrets as _rand
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aqelyn.conventions.ids import new_id
from aqelyn.identity.models import Account, Invite
from aqelyn.identity.passwords import hash_password, verify_password


class IdentityError(Exception):
    """An account operation was refused."""


class InviteError(IdentityError):
    """An invite could not be redeemed."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Session:
    token: str
    account_id: str
    tenant_id: str
    expires_at: datetime


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class _JsonFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._path, data)


class AccountStore:
    def __init__(self, path: str | Path, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._file = _JsonFile(Path(path))
        self._now = now
        self._lock = threading.Lock()

    def _all(self) -> dict[str, Account]:
        return {aid: Account.model_validate(rec) for aid, rec in self._file.load().items()}

    def get(self, account_id: str) -> Account | None:
        return self._all().get(account_id)

    def get_by_email(self, email: str) -> Account | None:
        return next((a for a in self._all().values() if a.email.lower() == email.lower()), None)

    def create(self, *, email: str, tenant_id: str, password: str) -> Account:
        with self._lock:
            data = self._file.load()
            if any(str(rec.get("email", "")).lower() == email.lower() for rec in data.values()):
                raise IdentityError("email already registered")
            account = Account(
                id=new_id("acc"),
                email=email,
                tenant_id=tenant_id,
                password=hash_password(password),
                created_at=self._now(),
            )
            data[account.id] = json.loads(account.model_dump_json())
            self._file.save(data)
            return account

    def authenticate(self, email: str, password: str) -> Account | None:
        """Return the account only if it is active and the password matches."""

        account = self.get_by_email(email)
        if account is None or account.status != "active":
            return None
        return account if verify_password(password, account.password) else None


class InviteStore:
    def __init__(
        self,
        path: str | Path,
        *,
        ttl: timedelta = timedelta(days=7),
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._file = _JsonFile(Path(path))
        self._ttl = ttl
        self._now = now
        self._lock = threading.Lock()

    def create(self, *, tenant_id: str, email: str | None = None) -> Invite:
        with self._lock:
            data = self._file.load()
            invite = Invite(
                id=new_id("inv"),
                token=_rand.token_urlsafe(32),
                tenant_id=tenant_id,
                email=email,
                created_at=self._now(),
                expires_at=self._now() + self._ttl,
            )
            data[invite.token] = json.loads(invite.model_dump_json())
            self._file.save(data)
            return invite

    def redeem(
        self, *, token: str, password: str, accounts: AccountStore, email: str | None = None
    ) -> Account:
        """Create the account for the invite's tenant.

        Single-use; refuses expired, used, or email-mismatched invites.
        """

        with self._lock:
            data = self._file.load()
            record = data.get(token)
            if record is None:
                raise InviteError("unknown invite")
            invite = Invite.model_validate(record)
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
            account = accounts.create(email=address, tenant_id=invite.tenant_id, password=password)
            record["redeemed_by"] = account.id
            self._file.save(data)
            return account


class SessionStore:
    def __init__(
        self, *, ttl: timedelta = timedelta(hours=12), now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl
        self._now = now
        self._lock = threading.Lock()

    def start(self, account: Account) -> Session:
        with self._lock:
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

    def resolve(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if self._now() > session.expires_at:
                self._sessions.pop(token, None)
                return None
            return session

    def end(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def _reap(self) -> None:
        now = self._now()
        for token in [t for t, s in self._sessions.items() if s.expires_at <= now]:
            self._sessions.pop(token, None)
