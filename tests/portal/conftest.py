"""Portal test harness (ECR-0118).

A fully in-memory portal: an enterprise-mode runtime (so tenant scoping is enforced), in-memory
identity and consent stores, and the PortalApplication wired to them. ``account_cookie`` registers
a tenant's account through the app and hands back its session cookie, so a test can act as a
specific customer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from aqelyn.consent.memory import InMemoryAuditLog, InMemoryConsentStore
from aqelyn.identity.memory import (
    InMemoryAccountStore,
    InMemoryInviteStore,
    InMemorySessionStore,
)
from aqelyn.kernel.config import AQELYNConfig
from aqelyn.kernel.factory import create_inmemory_runtime
from aqelyn.portal.app import COOKIE_NAME, PortalApplication


@dataclass
class PortalHarness:
    app: PortalApplication
    accounts: InMemoryAccountStore
    invites: InMemoryInviteStore
    sessions: InMemorySessionStore
    consent: InMemoryConsentStore
    audit: InMemoryAuditLog

    async def account_cookie(self, *, tenant_id: str, email: str, password: str = "pw") -> str:
        """Create an invite for the tenant, register through the app, return the session cookie."""

        invite = await self.invites.create(tenant_id=tenant_id, email=email)
        response = await self.app.handle(
            "POST",
            "/api/v1/register",
            {"content-type": "application/json"},
            json.dumps(
                {"invite_token": invite.token, "email": email, "password": password}
            ).encode(),
        )
        assert response.status == 201, response.body
        set_cookie = response.headers["Set-Cookie"]
        token = set_cookie.split(";", 1)[0].split("=", 1)[1]
        return f"{COOKIE_NAME}={token}"


@pytest.fixture
def portal() -> PortalHarness:
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode="enterprise"))
    accounts = InMemoryAccountStore()
    invites = InMemoryInviteStore(accounts)
    sessions = InMemorySessionStore()
    consent = InMemoryConsentStore()
    audit = InMemoryAuditLog()
    app = PortalApplication(
        runtime,
        accounts=accounts,
        invites=invites,
        sessions=sessions,
        consent=consent,
        audit=audit,
    )
    return PortalHarness(
        app=app,
        accounts=accounts,
        invites=invites,
        sessions=sessions,
        consent=consent,
        audit=audit,
    )
