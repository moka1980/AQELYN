"""Multi-user identity — accounts, invite-only registration, sessions.

Foundation for the customer scan flow (the brief's ECR-A). ECR-0115 shipped a file-backed,
synchronous bootstrap; ECR-0116 moves it onto the standard backend pair — ``InMemory*`` for
local runs and tests, ``Postgres*`` for durable production — behind the async protocols in
``store``, selected by ``build_identity_stores``. Method names and semantics are unchanged. The
single load-bearing isolation rule: **a tenant is resolved from the session, never from client
input** — see ``SessionStore``.
"""

from aqelyn.identity.factory import IdentityStores, build_identity_stores
from aqelyn.identity.memory import (
    InMemoryAccountStore,
    InMemoryInviteStore,
    InMemorySessionStore,
)
from aqelyn.identity.models import Account, Invite, PasswordHash
from aqelyn.identity.passwords import hash_password, verify_password
from aqelyn.identity.store import (
    AccountStore,
    IdentityError,
    InviteError,
    InviteStore,
    Session,
    SessionStore,
)

__all__ = [
    "Account",
    "AccountStore",
    "IdentityError",
    "IdentityStores",
    "InMemoryAccountStore",
    "InMemoryInviteStore",
    "InMemorySessionStore",
    "Invite",
    "InviteError",
    "InviteStore",
    "PasswordHash",
    "Session",
    "SessionStore",
    "build_identity_stores",
    "hash_password",
    "verify_password",
]
