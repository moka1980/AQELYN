"""The authenticated customer portal — register, log in, consent, upload, read (ECR-0118).

This is the customer-facing write boundary the brief's ECR-D describes. It is deliberately NOT the
operator surface: the surface is read-only and loopback (ECR-0088) and must stay that way. This
application accepts POST bodies and performs writes, gated by a session and by consent.

The one property everything rests on: **the tenant is taken from the authenticated session, never
from the request.** A caller cannot name a tenant in a body, a query, or a cookie; ``session.
tenant_id`` (bound from the account in ECR-0115/0116) is the only tenant an upload can land in.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

from aqelyn.consent.models import ConsentScope
from aqelyn.consent.store import AuditLog, ConsentStore
from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import AQError
from aqelyn.findings.models import FindingQuery
from aqelyn.identity.store import (
    AccountStore,
    IdentityError,
    InviteError,
    InviteStore,
    Session,
    SessionStore,
)
from aqelyn.kernel.factory import Runtime
from aqelyn.portal.ingest import UploadRefused, ingest_posture_document
from aqelyn.surface.models import SurfaceResponse

COOKIE_NAME = "aq_portal"
CONSENT_SCOPE: ConsentScope = "store_scan"

# Object-addressed routes: a path prefix that is followed by a single object id. Every entry here
# MUST answer a cross-tenant or unknown id with the SAME 404 (no existence oracle). ECR-0119's
# route-census guard walks this tuple and refuses to let a new object-addressed route ship without
# a cross-tenant isolation test. Adding such a route means adding it here and to that test.
OBJECT_ADDRESSED_ROUTES: tuple[str, ...] = ("/api/v1/findings/",)
# The uploaded posture.json is hostile input; bound it before parsing.
MAX_UPLOAD_BYTES = 1_048_576
MAX_FINDINGS_RETURNED = 200
_SESSION_MAX_AGE = 43_200  # 12 hours, matching the session TTL


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _error(status: int, code: str, message: str) -> SurfaceResponse:
    return SurfaceResponse.json(status, {"error": {"code": code, "message": message}})


def _parse_cookies(header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not header:
        return cookies
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            cookies[name] = value
    return cookies


def _session_cookie(token: str) -> str:
    return (
        f"{COOKIE_NAME}={token}; HttpOnly; Secure; SameSite=Strict; "
        f"Path=/; Max-Age={_SESSION_MAX_AGE}"
    )


_CLEAR_COOKIE = f"{COOKIE_NAME}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0"


def _object_id(path: str, prefix: str) -> str | None:
    """Return the single object id after ``prefix``, or None if ``path`` is not that route."""

    if not path.startswith(prefix):
        return None
    rest = path.removeprefix(prefix)
    if not rest or "/" in rest:
        return None
    return rest


class PortalApplication:
    """Register / log in / consent / upload / read, all tenant-scoped by the session."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        accounts: AccountStore,
        invites: InviteStore,
        sessions: SessionStore,
        consent: ConsentStore,
        audit: AuditLog,
    ) -> None:
        self._runtime = runtime
        self._accounts = accounts
        self._invites = invites
        self._sessions = sessions
        self._consent = consent
        self._audit = audit

    async def handle(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> SurfaceResponse:
        selected = method.upper()
        head = {k.lower(): v for k, v in (headers or {}).items()}
        path = urlsplit(target).path
        try:
            return await self._route(selected, path, head, body)
        except _BadRequest as exc:
            return _error(400, "bad_request", exc.message)
        except Exception:
            # The boundary never leaks a traceback to a customer.
            return _error(500, "portal_error", "the request could not be completed")

    async def _route(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes
    ) -> SurfaceResponse:
        if path == "/api/v1/register" and method == "POST":
            return await self._register(body)
        if path == "/api/v1/login" and method == "POST":
            return await self._login(body)
        if path == "/api/v1/logout" and method == "POST":
            return await self._logout(headers)
        if path == "/api/v1/consent" and method == "POST":
            return await self._grant_consent(headers, body)
        if path == "/api/v1/scans" and method == "POST":
            return await self._upload(headers, body)
        if path == "/api/v1/findings" and method == "GET":
            return await self._findings(headers)
        finding_id = _object_id(path, "/api/v1/findings/")
        if finding_id is not None and method == "GET":
            return await self._finding_detail(headers, finding_id)
        return _error(404, "not_found", "portal route not found")

    # --- helpers ---------------------------------------------------------------------

    async def _session(self, headers: Mapping[str, str]) -> Session | None:
        token = _parse_cookies(headers.get("cookie")).get(COOKIE_NAME)
        return await self._sessions.resolve(token)

    def _json_body(self, body: bytes) -> dict[str, Any]:
        if len(body) > MAX_UPLOAD_BYTES:
            raise _BadRequest("request body is too large")
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _BadRequest("request body is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise _BadRequest("request body must be a JSON object")
        return parsed

    def _string_field(self, payload: Mapping[str, Any], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise _BadRequest(f"{name} is required")
        return value

    def _actor(self, account_id: str) -> ActorRef:
        return ActorRef(actor_type="user", actor_id=account_id)

    # --- routes ----------------------------------------------------------------------

    async def _register(self, body: bytes) -> SurfaceResponse:
        payload = self._json_body(body)
        token = self._string_field(payload, "invite_token")
        email = self._string_field(payload, "email")
        password = self._string_field(payload, "password")
        try:
            account = await self._invites.redeem(token=token, password=password, email=email)
        except InviteError as exc:
            return _error(403, "invite_refused", str(exc))
        except IdentityError as exc:
            return _error(409, "account_refused", str(exc))
        session = await self._sessions.start(account)
        return SurfaceResponse(
            status=201,
            body=SurfaceResponse.json(201, {"account_id": account.id}).body,
            content_type="application/json; charset=utf-8",
            headers={"Set-Cookie": _session_cookie(session.token)},
        )

    async def _login(self, body: bytes) -> SurfaceResponse:
        payload = self._json_body(body)
        email = self._string_field(payload, "email")
        password = self._string_field(payload, "password")
        account = await self._accounts.authenticate(email, password)
        if account is None:
            return _error(401, "invalid_credentials", "email or password is incorrect")
        session = await self._sessions.start(account)
        return SurfaceResponse(
            status=200,
            body=SurfaceResponse.json(200, {"account_id": account.id}).body,
            content_type="application/json; charset=utf-8",
            headers={"Set-Cookie": _session_cookie(session.token)},
        )

    async def _logout(self, headers: Mapping[str, str]) -> SurfaceResponse:
        token = _parse_cookies(headers.get("cookie")).get(COOKIE_NAME)
        if token:
            await self._sessions.end(token)
        return SurfaceResponse(
            status=200,
            body=SurfaceResponse.json(200, {"ok": True}).body,
            content_type="application/json; charset=utf-8",
            headers={"Set-Cookie": _CLEAR_COOKIE},
        )

    async def _grant_consent(self, headers: Mapping[str, str], body: bytes) -> SurfaceResponse:
        session = await self._session(headers)
        if session is None:
            return _error(401, "unauthenticated", "a valid session is required")
        payload = self._json_body(body)
        text_version = self._string_field(payload, "text_version")
        record = await self._consent.record(
            tenant_id=session.tenant_id,
            account_id=session.account_id,
            scope=CONSENT_SCOPE,
            text_version=text_version,
        )
        await self._audit.append(
            tenant_id=session.tenant_id,
            actor_account_id=session.account_id,
            action="consent_granted",
            detail=text_version,
        )
        return SurfaceResponse.json(201, {"consent_id": record.id})

    async def _upload(self, headers: Mapping[str, str], body: bytes) -> SurfaceResponse:
        session = await self._session(headers)
        if session is None:
            return _error(401, "unauthenticated", "a valid session is required")
        # UX-005: no write without recorded, active consent.
        consent = await self._consent.active(tenant_id=session.tenant_id, scope=CONSENT_SCOPE)
        if consent is None:
            return _error(403, "consent_required", "storing a scan requires consent first")
        if len(body) > MAX_UPLOAD_BYTES:
            return _error(413, "upload_too_large", "the uploaded scan is too large")
        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error(400, "invalid_json", "the uploaded scan is not valid JSON")
        if not isinstance(document, Mapping):
            return _error(400, "invalid_scan", "the uploaded scan must be a JSON object")
        digest = f"sha256:{sha256(body).hexdigest()}"
        try:
            findings = await ingest_posture_document(
                self._runtime,
                document,
                # The tenant is the session's, never anything the caller sent.
                tenant_id=session.tenant_id,
                digest=digest,
                observed_at=_utcnow(),
                actor=self._actor(session.account_id),
            )
        except UploadRefused as exc:
            return _error(422, "scan_refused", exc.message)
        await self._audit.append(
            tenant_id=session.tenant_id,
            actor_account_id=session.account_id,
            action="scan_ingested",
            detail=digest,
        )
        return SurfaceResponse.json(
            201,
            {
                "ingested": len(findings),
                "findings": [f.model_dump(mode="json") for f in findings],
            },
        )

    async def _findings(self, headers: Mapping[str, str]) -> SurfaceResponse:
        session = await self._session(headers)
        if session is None:
            return _error(401, "unauthenticated", "a valid session is required")
        found, _ = await self._runtime.finding_store.query(
            FindingQuery(tenant_id=session.tenant_id, limit=MAX_FINDINGS_RETURNED)
        )
        return SurfaceResponse.json(
            200,
            {
                "items": [f.model_dump(mode="json") for f in found],
                "returned": len(found),
            },
        )

    async def _finding_detail(self, headers: Mapping[str, str], finding_id: str) -> SurfaceResponse:
        session = await self._session(headers)
        if session is None:
            return _error(401, "unauthenticated", "a valid session is required")
        try:
            finding = await self._runtime.finding_store.get(finding_id)
        except AQError:
            # A malformed id is not a valid finding; answer exactly as for "not found"
            # so the shape of an id is not an oracle either.
            finding = None
        # No existence oracle: a finding that belongs to another tenant, one that does
        # not exist, and one whose id is malformed all return the SAME 404. An attacker
        # cannot tell "exists but not yours" from "does not exist".
        if finding is None or finding.tenant_id != session.tenant_id:
            return _error(404, "not_found", "finding not found")
        return SurfaceResponse.json(200, {"item": finding.model_dump(mode="json")})


class _BadRequest(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
