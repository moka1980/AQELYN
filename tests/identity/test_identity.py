"""ECR-0115: multi-user identity — accounts, invites, sessions.

The load-bearing property is isolation: a tenant is bound at session start from the account,
and never comes from the client. A bug here is a breach, so it gets the most witnesses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aqelyn.identity import (
    AccountStore,
    IdentityError,
    InviteError,
    SessionStore,
    hash_password,
    verify_password,
)
from aqelyn.identity.store import InviteStore

_T0 = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
# tenant_id is a UUID in this codebase (enterprise mode); fixed UUIDs keep assertions stable.
_TENANT_A = "11111111-1111-4111-8111-111111111111"
_TENANT_B = "22222222-2222-4222-8222-222222222222"


class _Clock:
    """A movable clock so expiry is deterministic without real waiting."""

    def __init__(self) -> None:
        self.at = _T0

    def __call__(self) -> datetime:
        return self.at


def _accounts(tmp_path: Path, clock: _Clock | None = None) -> AccountStore:
    return AccountStore(tmp_path / "accounts.json", now=(clock or _Clock()))


# --- passwords -----------------------------------------------------------------------------


def test_password_verifies_and_rejects() -> None:
    h = hash_password("00Milav80")
    assert verify_password("00Milav80", h)
    assert not verify_password("wrong", h)
    assert not verify_password("", h)


def test_password_hash_is_salted_not_plaintext() -> None:
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1.salt != h2.salt  # per-password salt
    assert h1.hash != h2.hash
    assert "same" not in h1.hash


def test_no_plaintext_password_is_ever_written(tmp_path: Path) -> None:
    store = _accounts(tmp_path)
    store.create(email="a@x.no", tenant_id=_TENANT_A, password="s3cretPW!")
    raw = (tmp_path / "accounts.json").read_text(encoding="utf-8")
    assert "s3cretPW!" not in raw


# --- invite-only registration --------------------------------------------------------------


def test_account_is_created_by_redeeming_an_invite(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    invites = InviteStore(tmp_path / "invites.json")
    inv = invites.create(tenant_id=_TENANT_A, email="a@x.no")
    acc = invites.redeem(token=inv.token, password="pw12345", accounts=accts)
    assert acc.tenant_id == _TENANT_A  # tenant comes from the invite
    assert accts.get_by_email("a@x.no") is not None


def test_an_invite_is_single_use(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    invites = InviteStore(tmp_path / "invites.json")
    inv = invites.create(tenant_id=_TENANT_A, email="a@x.no")
    invites.redeem(token=inv.token, password="pw12345", accounts=accts)
    with pytest.raises(InviteError):
        invites.redeem(token=inv.token, password="pw12345", accounts=accts)


def test_an_expired_invite_is_refused(tmp_path: Path) -> None:
    clock = _Clock()
    accts = _accounts(tmp_path, clock)
    invites = InviteStore(tmp_path / "invites.json", ttl=timedelta(days=1), now=clock)
    inv = invites.create(tenant_id=_TENANT_A, email="a@x.no")
    clock.at = _T0 + timedelta(days=2)
    with pytest.raises(InviteError):
        invites.redeem(token=inv.token, password="pw12345", accounts=accts)


def test_a_mismatched_email_is_refused(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    invites = InviteStore(tmp_path / "invites.json")
    inv = invites.create(tenant_id=_TENANT_A, email="a@x.no")
    with pytest.raises(InviteError):
        invites.redeem(token=inv.token, password="pw12345", accounts=accts, email="b@x.no")


def test_an_unknown_invite_is_refused(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    invites = InviteStore(tmp_path / "invites.json")
    with pytest.raises(InviteError):
        invites.redeem(token="nope", password="pw12345", accounts=accts)


def test_duplicate_email_is_refused(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    accts.create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    with pytest.raises(IdentityError):
        accts.create(email="A@X.NO", tenant_id=_TENANT_B, password="pw12345")


# --- authentication ------------------------------------------------------------------------


def test_authenticate_accepts_right_password_only(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    accts.create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    assert accts.authenticate("a@x.no", "pw12345") is not None
    assert accts.authenticate("a@x.no", "wrong") is None
    assert accts.authenticate("missing@x.no", "pw12345") is None


def test_a_disabled_account_cannot_authenticate(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    acc = accts.create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    data = json.loads((tmp_path / "accounts.json").read_text(encoding="utf-8"))
    data[acc.id]["status"] = "disabled"
    (tmp_path / "accounts.json").write_text(json.dumps(data), encoding="utf-8")
    assert accts.authenticate("a@x.no", "pw12345") is None


# --- sessions: the tenant is bound from the account, never the client ----------------------


def test_session_carries_the_accounts_tenant(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    acc = accts.create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    sessions = SessionStore()
    session = sessions.start(acc)
    assert session.tenant_id == _TENANT_A
    resolved = sessions.resolve(session.token)
    assert resolved is not None
    assert resolved.tenant_id == _TENANT_A  # tenant comes from the session, not any input


def test_two_tenants_sessions_never_cross(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    a = accts.create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    b = accts.create(email="b@x.no", tenant_id=_TENANT_B, password="pw12345")
    sessions = SessionStore()
    sa = sessions.start(a)
    sb = sessions.start(b)
    ra = sessions.resolve(sa.token)
    rb = sessions.resolve(sb.token)
    assert ra is not None
    assert rb is not None
    assert ra.tenant_id == _TENANT_A
    assert rb.tenant_id == _TENANT_B


def test_no_token_and_unknown_token_resolve_to_nothing() -> None:
    sessions = SessionStore()
    assert sessions.resolve(None) is None
    assert sessions.resolve("") is None
    assert sessions.resolve("bogus") is None


def test_an_expired_session_resolves_to_nothing(tmp_path: Path) -> None:
    clock = _Clock()
    accts = _accounts(tmp_path, clock)
    acc = accts.create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    sessions = SessionStore(ttl=timedelta(hours=1), now=clock)
    session = sessions.start(acc)
    clock.at = _T0 + timedelta(hours=2)
    assert sessions.resolve(session.token) is None


def test_ending_a_session_invalidates_it(tmp_path: Path) -> None:
    accts = _accounts(tmp_path)
    acc = accts.create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    sessions = SessionStore()
    session = sessions.start(acc)
    sessions.end(session.token)
    assert sessions.resolve(session.token) is None


# --- persistence ---------------------------------------------------------------------------


def test_accounts_persist_across_store_instances(tmp_path: Path) -> None:
    _accounts(tmp_path).create(email="a@x.no", tenant_id=_TENANT_A, password="pw12345")
    reopened = AccountStore(tmp_path / "accounts.json")
    assert reopened.get_by_email("a@x.no") is not None
