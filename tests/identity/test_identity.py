"""Identity contract tests (ECR-0115 behaviours, ECR-0116 async on both backends).

Each test runs on the in-memory and the Postgres backend (Postgres skipped without
``AQELYN_DATABASE_URL``). The load-bearing property is ``test_two_tenants_sessions_never_cross``:
a session's tenant comes from its account, never from client input.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from aqelyn.identity.passwords import hash_password, verify_password
from aqelyn.identity.store import IdentityError, InviteError

# Two distinct tenants for the cross-tenant isolation tests (accounts require a UUID tenant_id).
TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


async def _invited_account(h: Any, *, tenant: str, email: str, password: str) -> None:
    invite = await h.invites.create(tenant_id=tenant, email=email)
    await h.invites.redeem(token=invite.token, password=password, email=email)


# --- passwords -----------------------------------------------------------------------


def test_password_verifies_and_rejects() -> None:
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored) is True
    assert verify_password("wrong", stored) is False


def test_password_hash_is_salted_and_holds_no_plaintext() -> None:
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a.salt != b.salt
    assert a.hash != b.hash
    assert "same-password" not in a.model_dump_json()


def test_verify_is_fail_closed_on_empty_material() -> None:
    stored = hash_password("pw")
    assert verify_password("", stored) is False


# --- invite-only registration --------------------------------------------------------


async def test_registration_requires_an_invite(identity: Any) -> None:
    with pytest.raises(InviteError):
        await identity.invites.redeem(token="inv-does-not-exist", password="pw", email="x@y.z")


async def test_invite_creates_the_account_for_its_tenant(identity: Any) -> None:
    invite = await identity.invites.create(tenant_id=TENANT_A, email="a@example.com")
    account = await identity.invites.redeem(
        token=invite.token, password="pw", email="a@example.com"
    )
    assert account.tenant_id == TENANT_A
    assert account.email == "a@example.com"


async def test_an_invite_is_single_use(identity: Any) -> None:
    invite = await identity.invites.create(tenant_id=TENANT_A, email="once@example.com")
    await identity.invites.redeem(token=invite.token, password="pw", email="once@example.com")
    with pytest.raises(InviteError):
        await identity.invites.redeem(token=invite.token, password="pw", email="once@example.com")


async def test_an_expired_invite_is_refused(identity: Any) -> None:
    invite = await identity.invites.create(tenant_id=TENANT_A, email="late@example.com")
    identity.clock.advance(timedelta(days=8))
    with pytest.raises(InviteError):
        await identity.invites.redeem(token=invite.token, password="pw", email="late@example.com")


async def test_an_invite_refuses_a_mismatched_email(identity: Any) -> None:
    invite = await identity.invites.create(tenant_id=TENANT_A, email="bound@example.com")
    with pytest.raises(InviteError):
        await identity.invites.redeem(
            token=invite.token, password="pw", email="someone-else@example.com"
        )


# --- accounts ------------------------------------------------------------------------


async def test_duplicate_email_is_refused(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="dup@example.com", password="pw")
    invite = await identity.invites.create(tenant_id=TENANT_B, email="dup@example.com")
    with pytest.raises(IdentityError):
        await identity.invites.redeem(token=invite.token, password="pw", email="dup@example.com")


async def test_authenticate_accepts_right_password_only(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="auth@example.com", password="right")
    assert await identity.accounts.authenticate("auth@example.com", "right") is not None
    assert await identity.accounts.authenticate("auth@example.com", "wrong") is None


async def test_authenticate_rejects_unknown_email(identity: Any) -> None:
    assert await identity.accounts.authenticate("nobody@example.com", "pw") is None


async def test_a_disabled_account_cannot_authenticate(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="off@example.com", password="pw")
    account = await identity.accounts.get_by_email("off@example.com")
    assert account is not None
    disabled = account.model_copy(update={"status": "disabled"})
    # Reach into each backend to flip the status the way an admin path eventually will.
    await _set_status(identity, disabled)
    assert await identity.accounts.authenticate("off@example.com", "pw") is None


async def _set_status(identity: Any, account: object) -> None:
    from aqelyn.identity.memory import InMemoryAccountStore
    from aqelyn.identity.models import Account

    assert isinstance(account, Account)
    store = identity.accounts
    if isinstance(store, InMemoryAccountStore):
        store._by_id[account.id] = account
        return
    from aqelyn.identity.postgres import PostgresAccountStore

    assert isinstance(store, PostgresAccountStore)
    async with store._pool.acquire() as conn:
        await conn.execute(
            "UPDATE aq_account SET status=$2 WHERE id=$1", account.id, account.status
        )


# --- sessions: the isolation rule ----------------------------------------------------


async def test_session_carries_the_accounts_tenant(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="s@example.com", password="pw")
    account = await identity.accounts.get_by_email("s@example.com")
    assert account is not None
    session = await identity.sessions.start(account)
    assert session.tenant_id == TENANT_A
    resolved = await identity.sessions.resolve(session.token)
    assert resolved is not None
    assert resolved.tenant_id == TENANT_A


async def test_two_tenants_sessions_never_cross(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="a@t.co", password="pw")
    await _invited_account(identity, tenant=TENANT_B, email="b@t.co", password="pw")
    account_a = await identity.accounts.get_by_email("a@t.co")
    account_b = await identity.accounts.get_by_email("b@t.co")
    assert account_a is not None
    assert account_b is not None
    session_a = await identity.sessions.start(account_a)
    session_b = await identity.sessions.start(account_b)
    resolved_a = await identity.sessions.resolve(session_a.token)
    resolved_b = await identity.sessions.resolve(session_b.token)
    assert resolved_a is not None
    assert resolved_b is not None
    assert resolved_a.tenant_id == TENANT_A
    assert resolved_b.tenant_id == TENANT_B
    assert resolved_a.tenant_id != resolved_b.tenant_id


async def test_an_expired_session_resolves_to_nothing(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="exp@example.com", password="pw")
    account = await identity.accounts.get_by_email("exp@example.com")
    assert account is not None
    session = await identity.sessions.start(account)
    identity.clock.advance(timedelta(hours=13))
    assert await identity.sessions.resolve(session.token) is None


async def test_ending_a_session_logs_out(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="out@example.com", password="pw")
    account = await identity.accounts.get_by_email("out@example.com")
    assert account is not None
    session = await identity.sessions.start(account)
    await identity.sessions.end(session.token)
    assert await identity.sessions.resolve(session.token) is None


async def test_sessions_survive_a_new_store_instance(identity: Any) -> None:
    # The cross-worker / survives-restart property is the Postgres backend's job; the
    # in-memory backend is intentionally per-process, so this asserts only where it applies.
    from aqelyn.identity.postgres import PostgresSessionStore

    if not isinstance(identity.sessions, PostgresSessionStore):
        pytest.skip("cross-instance session durability is a Postgres-backend property")
    await _invited_account(identity, tenant=TENANT_A, email="dur@example.com", password="pw")
    account = await identity.accounts.get_by_email("dur@example.com")
    assert account is not None
    session = await identity.sessions.start(account)
    # A DIFFERENT store instance on the same database — i.e. another worker — resolves it.
    fresh = PostgresSessionStore(identity.sessions._pool, now=identity.clock)
    resolved = await fresh.resolve(session.token)
    assert resolved is not None
    assert resolved.tenant_id == TENANT_A


async def test_accounts_persist_and_round_trip_by_id(identity: Any) -> None:
    await _invited_account(identity, tenant=TENANT_A, email="rt@example.com", password="pw")
    by_email = await identity.accounts.get_by_email("rt@example.com")
    assert by_email is not None
    by_id = await identity.accounts.get(by_email.id)
    assert by_id is not None
    assert by_id.id == by_email.id
    assert by_id.tenant_id == TENANT_A
