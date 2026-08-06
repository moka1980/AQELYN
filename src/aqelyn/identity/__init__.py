"""ECR-0115: multi-user identity — accounts, invite-only registration, sessions.

Foundation for the customer scan flow (the brief's ECR-A). File-backed today (the platform's
``auth.json`` pattern) so identity is durable without waiting on the Postgres move (ECR-0116),
into which it migrates with no change to this API. The single load-bearing isolation rule:
**a tenant is resolved from the session, never from client input** — see ``SessionStore``.
"""

from aqelyn.identity.models import Account, Invite, PasswordHash
from aqelyn.identity.passwords import hash_password, verify_password
from aqelyn.identity.store import (
    AccountStore,
    IdentityError,
    InviteError,
    Session,
    SessionStore,
)

__all__ = [
    "Account",
    "AccountStore",
    "IdentityError",
    "Invite",
    "InviteError",
    "PasswordHash",
    "Session",
    "SessionStore",
    "hash_password",
    "verify_password",
]
