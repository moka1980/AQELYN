"""Authenticated portal contract tests (ECR-0118).

The highest-risk property is cross-tenant isolation: a customer's upload lands in their session's
tenant and only that tenant, and a customer reads back only their own findings
(``test_two_tenants_never_see_each_others_findings``). Everything else here is the gate that
protects the write: session required, consent required, hostile input refused, size bounded.
"""

from __future__ import annotations

import json
from typing import Any

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


def _auth(cookie: str) -> dict[str, str]:
    return {"cookie": cookie, "content-type": "application/json"}


def _payload(response: Any) -> Any:
    return json.loads(response.body.decode())


def _valid_posture(observation_id: str = "obs-1", *, ref: str = "host-a") -> dict[str, Any]:
    return {
        "observations": [
            {
                "observation_id": observation_id,
                "check": "listening_sockets_public",
                "what_happened": "A port is reachable from outside this machine.",
                "why_it_matters": "Anything reachable is something an attacker can try.",
                "how_determined": "Read the listening sockets and their bind addresses.",
                "risk_of_inaction": "The exposure stays open until it is closed.",
                "severity": "high",
                "severity_score": 70.0,
                "subject": {"ref": ref, "kind": "host"},
                "remediation": {
                    "summary": "Close the port or bind it to loopback.",
                    "expected_outcome": "The port is no longer reachable from outside.",
                    "difficulty": "medium",
                },
            }
        ]
    }


async def _consent(portal: Any, cookie: str) -> None:
    response = await portal.app.handle(
        "POST", "/api/v1/consent", _auth(cookie), json.dumps({"text_version": "v1"}).encode()
    )
    assert response.status == 201


async def _upload(portal: Any, cookie: str, document: dict[str, Any]) -> Any:
    return await portal.app.handle(
        "POST", "/api/v1/scans", _auth(cookie), json.dumps(document).encode()
    )


# --- auth + registration -------------------------------------------------------------


async def test_register_then_login(portal: Any) -> None:
    invite = await portal.invites.create(tenant_id=TENANT_A, email="a@example.com")
    registered = await portal.app.handle(
        "POST",
        "/api/v1/register",
        {"content-type": "application/json"},
        json.dumps(
            {"invite_token": invite.token, "email": "a@example.com", "password": "pw"}
        ).encode(),
    )
    assert registered.status == 201
    assert "Set-Cookie" in registered.headers

    login = await portal.app.handle(
        "POST",
        "/api/v1/login",
        {"content-type": "application/json"},
        json.dumps({"email": "a@example.com", "password": "pw"}).encode(),
    )
    assert login.status == 200
    assert "Set-Cookie" in login.headers


async def test_register_refuses_bad_invite(portal: Any) -> None:
    response = await portal.app.handle(
        "POST",
        "/api/v1/register",
        {"content-type": "application/json"},
        json.dumps({"invite_token": "nope", "email": "a@example.com", "password": "pw"}).encode(),
    )
    assert response.status == 403


async def test_login_rejects_wrong_password(portal: Any) -> None:
    await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    response = await portal.app.handle(
        "POST",
        "/api/v1/login",
        {"content-type": "application/json"},
        json.dumps({"email": "a@example.com", "password": "wrong"}).encode(),
    )
    assert response.status == 401


# --- the write gates -----------------------------------------------------------------


async def test_upload_without_session_is_unauthenticated(portal: Any) -> None:
    response = await portal.app.handle(
        "POST",
        "/api/v1/scans",
        {"content-type": "application/json"},
        json.dumps(_valid_posture()).encode(),
    )
    assert response.status == 401


async def test_upload_without_consent_is_refused(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    response = await _upload(portal, cookie, _valid_posture())
    assert response.status == 403
    assert _payload(response)["error"]["code"] == "consent_required"


async def test_upload_with_session_and_consent_ingests(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await _consent(portal, cookie)
    response = await _upload(portal, cookie, _valid_posture())
    assert response.status == 201
    body = _payload(response)
    assert body["ingested"] == 1
    assert body["findings"][0]["tenant_id"] == TENANT_A


async def test_malformed_posture_is_refused_not_repaired(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await _consent(portal, cookie)
    # observations must be a non-empty list; an empty one is refused with a located reason.
    response = await _upload(portal, cookie, {"observations": []})
    assert response.status == 422
    assert _payload(response)["error"]["code"] == "scan_refused"


async def test_non_json_upload_is_refused(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await _consent(portal, cookie)
    response = await portal.app.handle("POST", "/api/v1/scans", _auth(cookie), b"this is not json")
    assert response.status == 400


async def test_oversized_upload_is_refused(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await _consent(portal, cookie)
    huge = b'{"observations":[' + b"0," * 600_000 + b"]}"
    response = await portal.app.handle("POST", "/api/v1/scans", _auth(cookie), huge)
    assert response.status == 413


async def test_revoked_consent_blocks_upload(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await _consent(portal, cookie)
    await portal.consent.revoke(tenant_id=TENANT_A, scope="store_scan")
    response = await _upload(portal, cookie, _valid_posture())
    assert response.status == 403


# --- the load-bearing isolation property ---------------------------------------------


async def test_two_tenants_never_see_each_others_findings(portal: Any) -> None:
    cookie_a = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    cookie_b = await portal.account_cookie(tenant_id=TENANT_B, email="b@example.com")
    await _consent(portal, cookie_a)
    await _consent(portal, cookie_b)

    await _upload(portal, cookie_a, _valid_posture("a-obs", ref="host-a"))
    await _upload(portal, cookie_b, _valid_posture("b-obs-1", ref="host-b1"))
    await _upload(portal, cookie_b, _valid_posture("b-obs-2", ref="host-b2"))

    a_findings = _payload(await portal.app.handle("GET", "/api/v1/findings", _auth(cookie_a)))
    b_findings = _payload(await portal.app.handle("GET", "/api/v1/findings", _auth(cookie_b)))
    assert a_findings["returned"] == 1
    assert b_findings["returned"] == 2
    assert all(item["tenant_id"] == TENANT_A for item in a_findings["items"])
    assert all(item["tenant_id"] == TENANT_B for item in b_findings["items"])


async def test_findings_requires_a_session(portal: Any) -> None:
    response = await portal.app.handle("GET", "/api/v1/findings", {})
    assert response.status == 401


# --- audit ---------------------------------------------------------------------------


async def test_upload_is_audited_in_the_callers_tenant(portal: Any) -> None:
    cookie = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await _consent(portal, cookie)
    await _upload(portal, cookie, _valid_posture())
    events = await portal.audit.list(tenant_id=TENANT_A)
    actions = [e.action for e in events]
    assert "consent_granted" in actions
    assert "scan_ingested" in actions
    # Nothing leaked into the other tenant's audit trail.
    assert await portal.audit.list(tenant_id=TENANT_B) == []
