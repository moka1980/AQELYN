"""ECR-0119 — adversarial per-tenant isolation audit + a structural route-census guard.

Two things live here:

1. **Adversarial probes.** Tenant A actively tries to reach tenant B's data and must fail — and
   fail *without an existence oracle*: a finding that belongs to B, one that does not exist, and one
   whose id is malformed all return the byte-identical 404.

2. **A route census.** ``OBJECT_ADDRESSED_ROUTES`` declares every route that addresses an object by
   id. The census walks it and refuses to let one ship without a registered cross-tenant probe here
   — so a future object-addressed route cannot be added without proving its isolation.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aqelyn.portal.app import OBJECT_ADDRESSED_ROUTES

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


def _auth(cookie: str) -> dict[str, str]:
    return {"cookie": cookie, "content-type": "application/json"}


def _payload(response: Any) -> Any:
    return json.loads(response.body.decode())


def _posture(observation_id: str, ref: str) -> dict[str, Any]:
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


async def _consent_and_upload(portal: Any, cookie: str, obs: str, ref: str) -> None:
    await portal.app.handle(
        "POST", "/api/v1/consent", _auth(cookie), json.dumps({"text_version": "v1"}).encode()
    )
    response = await portal.app.handle(
        "POST", "/api/v1/scans", _auth(cookie), json.dumps(_posture(obs, ref)).encode()
    )
    assert response.status == 201


async def _one_finding_id(portal: Any, cookie: str) -> str:
    listing = _payload(await portal.app.handle("GET", "/api/v1/findings", _auth(cookie)))
    return str(listing["items"][0]["id"])


# --- adversarial: the finding-detail route ------------------------------------------


async def test_a_cannot_read_bs_finding_by_id(portal: Any) -> None:
    cookie_a = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    cookie_b = await portal.account_cookie(tenant_id=TENANT_B, email="b@example.com")
    await _consent_and_upload(portal, cookie_b, "b-obs", "host-b")
    b_finding_id = await _one_finding_id(portal, cookie_b)

    # A knows B's real finding id and asks for it directly.
    response = await portal.app.handle("GET", f"/api/v1/findings/{b_finding_id}", _auth(cookie_a))
    assert response.status == 404


async def test_no_existence_oracle(portal: Any) -> None:
    cookie_a = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    cookie_b = await portal.account_cookie(tenant_id=TENANT_B, email="b@example.com")
    await _consent_and_upload(portal, cookie_b, "b-obs", "host-b")
    b_finding_id = await _one_finding_id(portal, cookie_b)

    # Three requests A makes: B's real id, an id that does not exist, and a malformed id.
    real_but_not_yours = await portal.app.handle(
        "GET", f"/api/v1/findings/{b_finding_id}", _auth(cookie_a)
    )
    does_not_exist = await portal.app.handle(
        "GET", "/api/v1/findings/fnd_00000000000000000000000000000000", _auth(cookie_a)
    )
    malformed = await portal.app.handle("GET", "/api/v1/findings/not-an-id", _auth(cookie_a))
    # All three are byte-identical: an attacker learns nothing from the difference.
    assert real_but_not_yours.status == 404
    assert real_but_not_yours.body == does_not_exist.body == malformed.body
    assert real_but_not_yours.status == does_not_exist.status == malformed.status


async def test_owner_can_read_their_own_finding(portal: Any) -> None:
    cookie_a = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await _consent_and_upload(portal, cookie_a, "a-obs", "host-a")
    a_finding_id = await _one_finding_id(portal, cookie_a)
    response = await portal.app.handle("GET", f"/api/v1/findings/{a_finding_id}", _auth(cookie_a))
    assert response.status == 200
    assert _payload(response)["item"]["tenant_id"] == TENANT_A


async def test_finding_detail_requires_a_session(portal: Any) -> None:
    response = await portal.app.handle(
        "GET", "/api/v1/findings/fnd_00000000000000000000000000000000", {}
    )
    assert response.status == 401


async def test_a_forged_tenant_in_the_body_is_ignored(portal: Any) -> None:
    cookie_a = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    await portal.app.handle(
        "POST", "/api/v1/consent", _auth(cookie_a), json.dumps({"text_version": "v1"}).encode()
    )
    document = _posture("a-obs", "host-a")
    # A tries to smuggle B's tenant into the upload; it must be ignored.
    document["tenant_id"] = TENANT_B
    document["observations"][0]["tenant_id"] = TENANT_B
    response = await portal.app.handle(
        "POST", "/api/v1/scans", _auth(cookie_a), json.dumps(document).encode()
    )
    assert response.status == 201
    assert _payload(response)["findings"][0]["tenant_id"] == TENANT_A


# --- the structural route census ----------------------------------------------------


@dataclass
class RouteProbe:
    """The three requests an attacker compares: a real-but-not-yours id, an id that does not
    exist, and a malformed id. ECR-0125: the census asserts these are byte-identical — a
    status-only census would let a future route leak existence through a distinguishing 404
    body (Codex review of ECR-0119, 2026-08-08)."""

    cross_tenant: Any
    nonexistent: Any
    malformed: Any


async def _probe_finding_route(portal: Any, cookie_a: str, cookie_b: str) -> RouteProbe:
    await _consent_and_upload(portal, cookie_b, "b-obs", "host-b")
    b_finding_id = await _one_finding_id(portal, cookie_b)
    return RouteProbe(
        cross_tenant=await portal.app.handle(
            "GET", f"/api/v1/findings/{b_finding_id}", _auth(cookie_a)
        ),
        nonexistent=await portal.app.handle(
            "GET", "/api/v1/findings/fnd_00000000000000000000000000000000", _auth(cookie_a)
        ),
        malformed=await portal.app.handle("GET", "/api/v1/findings/not-an-id", _auth(cookie_a)),
    )


# Every object-addressed route the app declares MUST have a prober here.
_PROBERS: dict[str, Callable[[Any, str, str], Awaitable[RouteProbe]]] = {
    "/api/v1/findings/": _probe_finding_route,
}


def test_every_object_addressed_route_has_a_cross_tenant_probe() -> None:
    # If a new object-addressed route is added to the app without a prober, this fails —
    # no object-addressed route ships without a cross-tenant isolation test.
    assert set(OBJECT_ADDRESSED_ROUTES) == set(_PROBERS)


async def test_route_census_every_object_route_refuses_with_no_oracle(portal: Any) -> None:
    cookie_a = await portal.account_cookie(tenant_id=TENANT_A, email="a@example.com")
    cookie_b = await portal.account_cookie(tenant_id=TENANT_B, email="b@example.com")
    for route in OBJECT_ADDRESSED_ROUTES:
        probe = await _PROBERS[route](portal, cookie_a, cookie_b)
        responses = (probe.cross_tenant, probe.nonexistent, probe.malformed)
        for response in responses:
            assert response.status == 404, f"{route} leaked cross-tenant (got {response.status})"
        # Byte-for-byte, not status-for-status: a distinguishing 404 body IS an oracle.
        assert probe.cross_tenant.body == probe.nonexistent.body == probe.malformed.body, (
            f"{route} answers the three cases with distinguishable bodies"
        )
        assert (
            probe.cross_tenant.content_type
            == probe.nonexistent.content_type
            == probe.malformed.content_type
        ), f"{route} answers the three cases with distinguishable content types"
