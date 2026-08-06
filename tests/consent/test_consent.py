"""Consent + audit contract tests (ECR-0117), run on both backends.

The load-bearing properties: consent and audit are tenant-scoped (one tenant never sees
another's), a revoked consent is no longer active, and the audit log is append-only.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from aqelyn.conventions.ids import new_id

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
ACCOUNT_A = new_id("acc")
ACCOUNT_B = new_id("acc")

_SCOPE = "store_scan"


# --- consent -------------------------------------------------------------------------


async def test_no_consent_is_not_active(consent: Any) -> None:
    assert await consent.consent.active(tenant_id=TENANT_A, scope=_SCOPE) is None


async def test_recorded_consent_is_active(consent: Any) -> None:
    record = await consent.consent.record(
        tenant_id=TENANT_A, account_id=ACCOUNT_A, scope=_SCOPE, text_version="v1"
    )
    active = await consent.consent.active(tenant_id=TENANT_A, scope=_SCOPE)
    assert active is not None
    assert active.id == record.id
    assert active.text_version == "v1"


async def test_revoked_consent_is_not_active(consent: Any) -> None:
    await consent.consent.record(
        tenant_id=TENANT_A, account_id=ACCOUNT_A, scope=_SCOPE, text_version="v1"
    )
    await consent.consent.revoke(tenant_id=TENANT_A, scope=_SCOPE)
    assert await consent.consent.active(tenant_id=TENANT_A, scope=_SCOPE) is None


async def test_reconsent_after_revoke_is_active(consent: Any) -> None:
    await consent.consent.record(
        tenant_id=TENANT_A, account_id=ACCOUNT_A, scope=_SCOPE, text_version="v1"
    )
    await consent.consent.revoke(tenant_id=TENANT_A, scope=_SCOPE)
    consent.clock.advance(timedelta(minutes=1))
    again = await consent.consent.record(
        tenant_id=TENANT_A, account_id=ACCOUNT_A, scope=_SCOPE, text_version="v2"
    )
    active = await consent.consent.active(tenant_id=TENANT_A, scope=_SCOPE)
    assert active is not None
    assert active.id == again.id
    assert active.text_version == "v2"


async def test_consent_is_tenant_scoped(consent: Any) -> None:
    await consent.consent.record(
        tenant_id=TENANT_A, account_id=ACCOUNT_A, scope=_SCOPE, text_version="v1"
    )
    # Tenant B never sees tenant A's consent.
    assert await consent.consent.active(tenant_id=TENANT_B, scope=_SCOPE) is None


async def test_revoke_is_tenant_scoped(consent: Any) -> None:
    await consent.consent.record(
        tenant_id=TENANT_A, account_id=ACCOUNT_A, scope=_SCOPE, text_version="v1"
    )
    await consent.consent.record(
        tenant_id=TENANT_B, account_id=ACCOUNT_B, scope=_SCOPE, text_version="v1"
    )
    # Revoking B must not disturb A's consent.
    await consent.consent.revoke(tenant_id=TENANT_B, scope=_SCOPE)
    assert await consent.consent.active(tenant_id=TENANT_A, scope=_SCOPE) is not None
    assert await consent.consent.active(tenant_id=TENANT_B, scope=_SCOPE) is None


# --- audit ---------------------------------------------------------------------------


async def test_audit_append_and_list(consent: Any) -> None:
    await consent.audit.append(
        tenant_id=TENANT_A, actor_account_id=ACCOUNT_A, action="scan_ingested", detail="sha256:abc"
    )
    events = await consent.audit.list(tenant_id=TENANT_A)
    assert len(events) == 1
    assert events[0].action == "scan_ingested"
    assert events[0].detail == "sha256:abc"


async def test_audit_is_append_only_and_ordered(consent: Any) -> None:
    await consent.audit.append(
        tenant_id=TENANT_A, actor_account_id=ACCOUNT_A, action="consent_granted", detail="v1"
    )
    consent.clock.advance(timedelta(seconds=1))
    await consent.audit.append(
        tenant_id=TENANT_A, actor_account_id=ACCOUNT_A, action="scan_ingested", detail="sha256:abc"
    )
    events = await consent.audit.list(tenant_id=TENANT_A)
    # Both survive; appending never overwrites, and order is insertion order.
    assert [e.action for e in events] == ["consent_granted", "scan_ingested"]


async def test_audit_is_tenant_scoped(consent: Any) -> None:
    await consent.audit.append(
        tenant_id=TENANT_A, actor_account_id=ACCOUNT_A, action="scan_ingested", detail="a"
    )
    await consent.audit.append(
        tenant_id=TENANT_B, actor_account_id=ACCOUNT_B, action="scan_ingested", detail="b"
    )
    a_events = await consent.audit.list(tenant_id=TENANT_A)
    b_events = await consent.audit.list(tenant_id=TENANT_B)
    assert [e.detail for e in a_events] == ["a"]
    assert [e.detail for e in b_events] == ["b"]
