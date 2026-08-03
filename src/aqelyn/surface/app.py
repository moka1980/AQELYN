"""Read-only projections from the kernel into the local operator surface."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlsplit

from aqelyn.conventions.errors import (
    AQError,
    SchemaValidationError,
    SurfaceRequestInvalid,
    SurfaceUnavailable,
    TenantScopeRequired,
)
from aqelyn.conventions.ids import require_tenant_id
from aqelyn.findings.models import Finding
from aqelyn.inventory.models import InventoryReport
from aqelyn.kernel.factory import Runtime
from aqelyn.surface.html import APP_CSS, APP_JS, render_index
from aqelyn.surface.models import SurfaceResponse
from aqelyn.vuln.models import VulnerabilityAssessment

READ_ROUTES: tuple[str, ...] = (
    "/",
    "/health",
    "/api/v1/meta",
    "/api/v1/inventory",
    "/api/v1/findings",
    "/api/v1/vulnerabilities",
    "/api/v1/ispm",
    "/api/v1/exposure",
    "/api/v1/secrets",
    "/api/v1/supplychain",
    "/assets/app.css",
    "/assets/app.js",
)
DETAIL_ROUTES: Mapping[str, str] = {
    "/api/v1/ispm/": "ispm",
    "/api/v1/exposure/": "exposure",
    "/api/v1/secrets/": "crypto-assets",
    "/api/v1/supplychain/": "supplychain",
}
READ_METHODS = frozenset(("GET", "HEAD"))
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
SURFACE_WORK_BUDGET = 50_000


class _InventoryReader(Protocol):
    async def inventory(self, *, tenant_id: str | None) -> InventoryReport: ...


class _VulnerabilityReader(Protocol):
    async def assess(self, *, tenant_id: str | None) -> VulnerabilityAssessment: ...


class _FindingReader(Protocol):
    async def query(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Finding], str | None]: ...


class _SerializableRecord(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, Any]: ...


class _DomainReadItem(Protocol):
    record: _SerializableRecord
    explain: dict[str, Any] | None


class _DomainReadPage(Protocol):
    items: Sequence[_DomainReadItem]
    next_cursor: str | None
    degraded: bool
    degradation_reasons: Sequence[str]


class _ISPMReader(Protocol):
    async def list_postures(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> _DomainReadPage: ...

    async def get_posture(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> _DomainReadItem | None: ...


class _ExposureReader(Protocol):
    async def list_exposures(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> _DomainReadPage: ...

    async def get_exposure(
        self,
        exposure_id: str,
        *,
        tenant_id: str | None,
    ) -> _DomainReadItem | None: ...


class _SecretsReader(Protocol):
    async def list_assets(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> _DomainReadPage: ...

    async def get_asset(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> _DomainReadItem | None: ...


class _SupplyChainReader(Protocol):
    async def list_components(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> _DomainReadPage: ...

    async def get_component(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> _DomainReadItem | None: ...


@dataclass(frozen=True, slots=True)
class _PageRequest:
    limit: int
    offset: int


class SurfaceApplication:
    """Local, operator-only, read-only view over one factory-built Runtime."""

    def __init__(self, runtime: Runtime) -> None:
        self._kernel = runtime.kernel
        self._config = runtime.kernel.config

    async def handle(self, method: str, target: str) -> SurfaceResponse:
        selected_method = method.upper()
        try:
            if selected_method not in READ_METHODS:
                return _error(
                    405,
                    "method_not_allowed",
                    "the surface exposes read methods only",
                    headers={"Allow": "GET, HEAD"},
                )
            path, query = _target(target)
            if not _route_allowed(path):
                return _error(404, "route_not_found", "surface route not found")

            response = await self._dispatch(path, query)
            if selected_method == "HEAD":
                return SurfaceResponse(
                    status=response.status,
                    body=b"",
                    content_type=response.content_type,
                    headers={
                        **response.headers,
                        "Content-Length": str(len(response.body)),
                    },
                )
            return response
        except (SurfaceRequestInvalid, SchemaValidationError, TenantScopeRequired) as exc:
            return _error(400, exc.code, exc.message)
        except AQError as exc:
            status = 503 if exc.retriable else 422
            return _error(status, exc.code, exc.message)
        except KeyError:
            return _error(503, "service_unavailable", "required kernel service is not registered")

    async def _dispatch(
        self,
        path: str,
        query: Mapping[str, list[str]],
    ) -> SurfaceResponse:
        if path == "/":
            return SurfaceResponse.text(
                200,
                render_index(),
                content_type="text/html; charset=utf-8",
                headers={
                    "Content-Security-Policy": (
                        "default-src 'self'; script-src 'self'; style-src 'self'; "
                        "img-src 'self'; connect-src 'self'; object-src 'none'; "
                        "base-uri 'none'; frame-ancestors 'none'"
                    )
                },
            )
        if path == "/assets/app.css":
            return SurfaceResponse.text(
                200,
                APP_CSS,
                content_type="text/css; charset=utf-8",
            )
        if path == "/assets/app.js":
            return SurfaceResponse.text(
                200,
                APP_JS,
                content_type="text/javascript; charset=utf-8",
            )
        if path == "/health":
            state = await self._kernel.health()
            kernel_status = state.services.get("_kernel")
            status = 200 if kernel_status is None or kernel_status.ready else 503
            return SurfaceResponse.json(status, state.model_dump(mode="json"))
        if path == "/api/v1/meta":
            return SurfaceResponse.json(
                200,
                {
                    "backend": self._config.backend,
                    "tenant_mode": self._config.tenant_mode,
                    "trust_boundary": "local_operator",
                },
            )
        if path == "/api/v1/inventory":
            return await self._inventory(query)
        if path == "/api/v1/findings":
            return await self._findings(query)
        if path == "/api/v1/vulnerabilities":
            return await self._vulnerabilities(query)
        if path == "/api/v1/ispm":
            return await self._ispm(query)
        if path == "/api/v1/exposure":
            return await self._exposure(query)
        if path == "/api/v1/secrets":
            return await self._secrets(query)
        if path == "/api/v1/supplychain":
            return await self._supplychain(query)
        detail = _detail_route(path)
        if detail is not None:
            domain, record_id = detail
            return await self._domain_detail(query, domain=domain, record_id=record_id)
        raise SurfaceUnavailable("closed route table dispatched an unknown route")

    async def _inventory(self, query: Mapping[str, list[str]]) -> SurfaceResponse:
        tenant_id = self._tenant_id(query)
        page = _page_request(query, path="/api/v1/inventory", tenant_id=tenant_id)
        service = cast(_InventoryReader, self._kernel.get_service("inventory_engine"))
        report = await service.inventory(tenant_id=tenant_id)
        items = [{"asset_id": asset_id} for asset_id in report.assets]
        payload = _page(items, page=page, path="/api/v1/inventory", tenant_id=tenant_id)
        payload["inventory"] = {
            "as_of": report.as_of.isoformat(),
            "degraded": report.degraded,
            "source_freshness": {
                key: value.isoformat() for key, value in report.source_freshness.items()
            },
            "total": report.total,
        }
        return SurfaceResponse.json(200, payload)

    async def _findings(self, query: Mapping[str, list[str]]) -> SurfaceResponse:
        tenant_id = self._tenant_id(query)
        path = "/api/v1/findings"
        limit = _limit(query, allowed={"cursor", "limit", "tenant_id"})
        raw_cursor = _single(query, "cursor")
        cursor = (
            None
            if raw_cursor is None
            else _decode_inner_cursor(raw_cursor, path=path, tenant_id=tenant_id)
        )
        service = cast(_FindingReader, self._kernel.get_service("finding_read"))
        findings, next_inner_cursor = await service.query(
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
        )
        next_cursor = (
            None
            if next_inner_cursor is None
            else _encode_inner_cursor(
                path=path,
                tenant_id=tenant_id,
                inner=next_inner_cursor,
            )
        )
        return SurfaceResponse.json(
            200,
            {
                "items": [finding.model_dump(mode="json") for finding in findings],
                "limit": limit,
                "next_cursor": next_cursor,
                "returned": len(findings),
                "total": None,
            },
        )

    async def _vulnerabilities(self, query: Mapping[str, list[str]]) -> SurfaceResponse:
        tenant_id = self._tenant_id(query)
        path = "/api/v1/vulnerabilities"
        page = _page_request(query, path=path, tenant_id=tenant_id)
        service = cast(_VulnerabilityReader, self._kernel.get_service("vuln_engine"))
        assessment = await service.assess(tenant_id=tenant_id)
        items = [item.model_dump(mode="json") for item in assessment.priorities]
        payload = _page(items, page=page, path=path, tenant_id=tenant_id)
        payload["assessment"] = {
            "coverage": assessment.coverage.model_dump(mode="json"),
            "degraded": assessment.degraded,
            "generated_at": assessment.generated_at.isoformat(),
            "suppressed_count": assessment.suppressed_count,
            "unavailable": assessment.unavailable,
        }
        return SurfaceResponse.json(200, payload)

    async def _ispm(
        self,
        query: Mapping[str, list[str]],
    ) -> SurfaceResponse:
        tenant_id = self._tenant_id(query)
        limit = _limit(query, allowed={"cursor", "limit", "tenant_id"})
        cursor = _single(query, "cursor")
        service = cast(_ISPMReader, self._kernel.get_service("ispm_read"))
        page = await service.list_postures(
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
        )
        return SurfaceResponse.json(200, _domain_page_payload(page, limit=limit))

    async def _exposure(self, query: Mapping[str, list[str]]) -> SurfaceResponse:
        tenant_id = self._tenant_id(query)
        limit = _limit(query, allowed={"cursor", "limit", "tenant_id"})
        service = cast(_ExposureReader, self._kernel.get_service("exposure_read"))
        page = await service.list_exposures(
            tenant_id=tenant_id,
            limit=limit,
            cursor=_single(query, "cursor"),
        )
        return SurfaceResponse.json(200, _domain_page_payload(page, limit=limit))

    async def _secrets(self, query: Mapping[str, list[str]]) -> SurfaceResponse:
        tenant_id = self._tenant_id(query)
        limit = _limit(query, allowed={"cursor", "limit", "tenant_id"})
        service = cast(_SecretsReader, self._kernel.get_service("secrets_read"))
        page = await service.list_assets(
            tenant_id=tenant_id,
            limit=limit,
            cursor=_single(query, "cursor"),
        )
        return SurfaceResponse.json(200, _domain_page_payload(page, limit=limit))

    async def _supplychain(self, query: Mapping[str, list[str]]) -> SurfaceResponse:
        tenant_id = self._tenant_id(query)
        limit = _limit(query, allowed={"cursor", "limit", "tenant_id"})
        service = cast(_SupplyChainReader, self._kernel.get_service("supplychain_read"))
        page = await service.list_components(
            tenant_id=tenant_id,
            limit=limit,
            cursor=_single(query, "cursor"),
        )
        return SurfaceResponse.json(200, _domain_page_payload(page, limit=limit))

    async def _domain_detail(
        self,
        query: Mapping[str, list[str]],
        *,
        domain: str,
        record_id: str,
    ) -> SurfaceResponse:
        _limit(query, allowed={"tenant_id"})
        tenant_id = self._tenant_id(query)
        item: _DomainReadItem | None
        if domain == "ispm":
            service = cast(_ISPMReader, self._kernel.get_service("ispm_read"))
            item = await service.get_posture(record_id, tenant_id=tenant_id)
        elif domain == "exposure":
            exposure = cast(_ExposureReader, self._kernel.get_service("exposure_read"))
            item = await exposure.get_exposure(record_id, tenant_id=tenant_id)
        elif domain == "crypto-assets":
            secret_reader = cast(_SecretsReader, self._kernel.get_service("secrets_read"))
            item = await secret_reader.get_asset(record_id, tenant_id=tenant_id)
        else:
            supplychain = cast(
                _SupplyChainReader,
                self._kernel.get_service("supplychain_read"),
            )
            item = await supplychain.get_component(record_id, tenant_id=tenant_id)
        if item is None:
            return _error(404, "record_not_found", "domain record not found")
        return SurfaceResponse.json(200, {"item": _domain_item_payload(item)})

    def _tenant_id(self, query: Mapping[str, list[str]]) -> str | None:
        raw = _single(query, "tenant_id")
        if self._config.tenant_mode == "enterprise":
            if raw is None or not raw.strip():
                raise TenantScopeRequired(
                    "tenant_id is required for surface reads in enterprise mode"
                )
            return require_tenant_id(raw, field="surface tenant_id")
        if raw is not None:
            raise SurfaceRequestInvalid(
                "tenant_id must be omitted in local mode; null means this local estate, "
                "not all tenants"
            )
        return None


def _target(target: str) -> tuple[str, Mapping[str, list[str]]]:
    if len(target) > 8_192:
        raise SurfaceRequestInvalid("request target exceeds 8192 bytes")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        raise SurfaceRequestInvalid("request target must be an origin-form path")
    try:
        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=16,
        )
    except ValueError as exc:
        raise SurfaceRequestInvalid("request query is malformed") from exc
    return parsed.path, query


def _route_allowed(path: str) -> bool:
    return path in READ_ROUTES or _detail_route(path) is not None


def _detail_route(path: str) -> tuple[str, str] | None:
    for prefix, domain in DETAIL_ROUTES.items():
        if path.startswith(prefix):
            record_id = path.removeprefix(prefix)
            if record_id and "/" not in record_id:
                return domain, record_id
    return None


def _domain_item_payload(item: _DomainReadItem) -> dict[str, Any]:
    return {
        "record": item.record.model_dump(mode="json"),
        "explain": item.explain,
    }


def _domain_page_payload(page: _DomainReadPage, *, limit: int) -> dict[str, Any]:
    return {
        "items": [_domain_item_payload(item) for item in page.items],
        "limit": limit,
        "next_cursor": page.next_cursor,
        "returned": len(page.items),
        "total": None,
        "degraded": page.degraded,
        "degradation_reasons": list(page.degradation_reasons),
    }


def _single(query: Mapping[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if values is None:
        return None
    if len(values) != 1:
        raise SurfaceRequestInvalid(f"{name} must appear exactly once")
    return values[0]


def _page_request(
    query: Mapping[str, list[str]],
    *,
    path: str,
    tenant_id: str | None,
) -> _PageRequest:
    limit = _limit(query, allowed={"cursor", "limit", "tenant_id"})
    raw_cursor = _single(query, "cursor")
    offset = 0 if raw_cursor is None else _decode_cursor(raw_cursor, path=path, tenant_id=tenant_id)
    return _PageRequest(limit=limit, offset=offset)


def _limit(query: Mapping[str, list[str]], *, allowed: set[str]) -> int:
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise SurfaceRequestInvalid(f"unknown query parameter: {unknown[0]}")
    raw_limit = _single(query, "limit")
    try:
        limit = DEFAULT_PAGE_SIZE if raw_limit is None else int(raw_limit)
    except ValueError as exc:
        raise SurfaceRequestInvalid("limit must be an integer") from exc
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise SurfaceRequestInvalid(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    return limit


def _page(
    items: Sequence[dict[str, Any]],
    *,
    page: _PageRequest,
    path: str,
    tenant_id: str | None,
) -> dict[str, Any]:
    if len(items) > SURFACE_WORK_BUDGET:
        raise SurfaceUnavailable("surface collection exceeds the configured work budget")
    if page.offset > len(items):
        raise SurfaceRequestInvalid("cursor points beyond the current collection")
    end = min(page.offset + page.limit, len(items))
    next_cursor = (
        _encode_cursor(path=path, tenant_id=tenant_id, offset=end) if end < len(items) else None
    )
    return {
        "items": list(items[page.offset : end]),
        "limit": page.limit,
        "next_cursor": next_cursor,
        "returned": end - page.offset,
        "total": len(items),
    }


def _encode_cursor(*, path: str, tenant_id: str | None, offset: int) -> str:
    return _encode_scoped_cursor(
        path=path,
        tenant_id=tenant_id,
        value={"offset": offset},
    )


def _encode_inner_cursor(*, path: str, tenant_id: str | None, inner: str) -> str:
    return _encode_scoped_cursor(
        path=path,
        tenant_id=tenant_id,
        value={"inner": inner},
    )


def _encode_scoped_cursor(
    *,
    path: str,
    tenant_id: str | None,
    value: Mapping[str, object],
) -> str:
    raw = json.dumps(
        {"path": path, "tenant_id": tenant_id, **value},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str, *, path: str, tenant_id: str | None) -> int:
    payload = _decode_scoped_cursor(
        value,
        path=path,
        tenant_id=tenant_id,
        value_keys=frozenset(("offset",)),
    )
    offset = payload["offset"]
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise SurfaceRequestInvalid("cursor offset is invalid")
    return offset


def _decode_inner_cursor(value: str, *, path: str, tenant_id: str | None) -> str:
    payload = _decode_scoped_cursor(
        value,
        path=path,
        tenant_id=tenant_id,
        value_keys=frozenset(("inner",)),
    )
    inner = payload["inner"]
    if not isinstance(inner, str) or not inner:
        raise SurfaceRequestInvalid("cursor inner value is invalid")
    return inner


def _decode_scoped_cursor(
    value: str,
    *,
    path: str,
    tenant_id: str | None,
    value_keys: frozenset[str],
) -> dict[str, object]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded: object = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SurfaceRequestInvalid("cursor is malformed") from exc
    if not isinstance(decoded, dict):
        raise SurfaceRequestInvalid("cursor has an unknown shape")
    payload = cast(dict[str, object], decoded)
    if not {"path", "tenant_id"}.issubset(payload):
        raise SurfaceRequestInvalid("cursor has an unknown shape")
    if payload["path"] != path or payload["tenant_id"] != tenant_id:
        raise SurfaceRequestInvalid("cursor does not belong to this collection scope")
    if set(payload) != {"path", "tenant_id"} | value_keys:
        raise SurfaceRequestInvalid("cursor has an unknown shape")
    return payload


def _error(
    status: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> SurfaceResponse:
    response = SurfaceResponse.json(status, {"error": {"code": code, "message": message}})
    if headers is None:
        return response
    return SurfaceResponse(
        status=response.status,
        body=response.body,
        content_type=response.content_type,
        headers=dict(headers),
    )
