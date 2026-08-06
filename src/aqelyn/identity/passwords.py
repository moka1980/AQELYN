"""scrypt password hashing (stdlib only), matching the shipped ``auth.json`` shape.

Salted per password, compared in constant time. The cost parameters travel with the hash so a
future raise does not strand old hashes.
"""

from __future__ import annotations

import hashlib
import hmac

# Aliased: the GC-004 persisted-field census matches the bare name `secrets` against the
# secrets package's exempt `secrets` field. The alias keeps our stdlib use unambiguous.
import secrets as _rand

from aqelyn.identity.models import PasswordHash

_N, _R, _P, _DKLEN, _SALT_BYTES = 16384, 8, 1, 32, 16


def hash_password(password: str) -> PasswordHash:
    if not password:
        raise ValueError("password must not be empty")
    salt = _rand.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return PasswordHash(salt=salt.hex(), hash=derived.hex(), n=_N, r=_R, p=_P)


def verify_password(password: str, stored: PasswordHash) -> bool:
    """Constant-time check. Any malformed stored hash fails closed, never raises."""

    if not password:
        return False
    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(stored.salt),
            n=stored.n,
            r=stored.r,
            p=stored.p,
            dklen=len(bytes.fromhex(stored.hash)),
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, stored.hash)
