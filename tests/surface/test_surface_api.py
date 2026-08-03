"""Behavioral tests for ECR-0088's kernel-backed read projections."""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from aqelyn.kernel import AQELYNConfig, HealthStatus, create_inmemory_runtime
from aqelyn.surface.app import MAX_PAGE_SIZE, SURFACE_WORK_BUDGET, SurfaceApplication

NOW = datetime(2026, 8, 2, tzinfo=UTC)


@dataclass(frozen=True)
class _InventoryReport:
    assets: list[str]
    total: int
    as_of: datetime = NOW
    source_freshness: dict[str, datetime] | None = None
    degraded: bool = False

    def __post_init__(self) -> None:
        if self.source_freshness is None:
            object.__setattr__(self, "source_freshness", {})


@dataclass(frozen=True)
class _Priority:
    vulnerability_id: str
    score: float
    priority: str
    factors: dict[str, Any]

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {
            "vulnerability_id": self.vulnerability_id,
            "score": self.score,
            "priority": self.priority,
            "factors": self.factors,
        }


@dataclass(frozen=True)
class _Finding:
    id: str
    title: str

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {
            "id": self.id,
            "severity": "medium",
            "status": "open",
            "title": self.title,
            "why_it_matters": "Acceptance-scale pagination must not inline the corpus.",
        }


@dataclass(frozen=True)
class _Coverage:
    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {"scanned": [], "unscanned": [], "stale": [], "unassessable": []}


@dataclass(frozen=True)
class _Assessment:
    priorities: list[_Priority]
    coverage: _Coverage = _Coverage()
    suppressed_count: int = 0
    degraded: bool = False
    unavailable: list[dict[str, str]] | None = None
    generated_at: datetime = NOW

    def __post_init__(self) -> None:
        if self.unavailable is None:
            object.__setattr__(self, "unavailable", [])


@dataclass(frozen=True)
class _DomainRecord:
    id: str
    label: str

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {"id": self.id, "label": self.label}


@dataclass(frozen=True)
class _DomainItem:
    record: _DomainRecord
    explain: dict[str, Any] | None


@dataclass(frozen=True)
class _DomainPage:
    items: tuple[_DomainItem, ...]
    next_cursor: str | None
    degraded: bool
    degradation_reasons: tuple[str, ...]


class _DomainReadService:
    def __init__(self, name: str, *, explain: dict[str, Any] | None) -> None:
        self._name = name
        self._explain = explain
        self.calls: list[tuple[str, str | None, int | None, str | None]] = []

    async def list_postures(
        self, *, tenant_id: str | None, limit: int, cursor: str | None
    ) -> _DomainPage:
        return self._page("list_postures", tenant_id, limit, cursor)

    async def list_exposures(
        self, *, tenant_id: str | None, limit: int, cursor: str | None
    ) -> _DomainPage:
        return self._page("list_exposures", tenant_id, limit, cursor)

    async def list_assets(
        self, *, tenant_id: str | None, limit: int, cursor: str | None
    ) -> _DomainPage:
        return self._page("list_assets", tenant_id, limit, cursor)

    async def list_components(
        self, *, tenant_id: str | None, limit: int, cursor: str | None
    ) -> _DomainPage:
        return self._page("list_components", tenant_id, limit, cursor)

    async def get_posture(self, record_id: str, *, tenant_id: str | None) -> _DomainItem:
        return self._detail("get_posture", record_id, tenant_id)

    async def get_exposure(self, record_id: str, *, tenant_id: str | None) -> _DomainItem:
        return self._detail("get_exposure", record_id, tenant_id)

    async def get_asset(self, record_id: str, *, tenant_id: str | None) -> _DomainItem:
        return self._detail("get_asset", record_id, tenant_id)

    async def get_component(self, record_id: str, *, tenant_id: str | None) -> _DomainItem:
        return self._detail("get_component", record_id, tenant_id)

    def _page(
        self,
        method: str,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> _DomainPage:
        self.calls.append((method, tenant_id, limit, cursor))
        return _DomainPage(
            items=(_DomainItem(_DomainRecord("record_one", "Visible record"), self._explain),),
            next_cursor="owner-keyset-cursor",
            degraded=True,
            degradation_reasons=("owner read reports partial coverage",),
        )

    def _detail(self, method: str, record_id: str, tenant_id: str | None) -> _DomainItem:
        self.calls.append((method, tenant_id, None, record_id))
        return _DomainItem(_DomainRecord(record_id, "Visible detail"), self._explain)


class _ReadService:
    def __init__(
        self,
        name: str,
        *,
        inventory: _InventoryReport | None = None,
        assessment: _Assessment | None = None,
        findings: list[_Finding] | None = None,
    ) -> None:
        self._name = name
        self._inventory = inventory
        self._assessment = assessment
        self._findings = findings
        self.tenant_calls: list[str | None] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def dependencies(self) -> tuple[str, ...]:
        return ()

    @property
    def critical(self) -> bool:
        return False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> HealthStatus:
        return HealthStatus(status="healthy", ready=True)

    async def inventory(self, *, tenant_id: str | None) -> _InventoryReport:
        self.tenant_calls.append(tenant_id)
        assert self._inventory is not None
        return self._inventory

    async def assess(self, *, tenant_id: str | None) -> _Assessment:
        self.tenant_calls.append(tenant_id)
        assert self._assessment is not None
        return self._assessment

    async def query(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[_Finding], str | None]:
        self.tenant_calls.append(tenant_id)
        assert self._findings is not None
        offset = 0 if cursor is None else int(cursor)
        selected = self._findings[offset : offset + limit]
        next_offset = offset + len(selected)
        next_cursor = str(next_offset) if next_offset < len(self._findings) else None
        return selected, next_cursor


def _payload(body: bytes) -> dict[str, Any]:
    selected = json.loads(body)
    assert isinstance(selected, dict)
    return selected


def _app(
    *,
    tenant_mode: str = "local",
    inventory: _InventoryReport | None = None,
    assessment: _Assessment | None = None,
    findings: list[_Finding] | None = None,
) -> tuple[SurfaceApplication, _ReadService, _ReadService, _ReadService]:
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode=tenant_mode))
    inventory_service = _ReadService(
        "inventory_engine",
        inventory=inventory or _InventoryReport(assets=[], total=0),
    )
    vulnerability_service = _ReadService(
        "vuln_engine",
        assessment=assessment or _Assessment(priorities=[]),
    )
    finding_service = _ReadService(
        "finding_read",
        findings=[] if findings is None else findings,
    )
    runtime.kernel._services["inventory_engine"] = inventory_service
    runtime.kernel._services["vuln_engine"] = vulnerability_service
    runtime.kernel._services["finding_read"] = finding_service
    return SurfaceApplication(runtime), inventory_service, finding_service, vulnerability_service


def _domain_app(
    *,
    tenant_mode: str = "local",
) -> tuple[SurfaceApplication, dict[str, _DomainReadService]]:
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode=tenant_mode))
    services = {
        "ispm_read": _DomainReadService(
            "ispm_read",
            explain={"statement": "Posture follows the recorded factors."},
        ),
        "exposure_read": _DomainReadService("exposure_read", explain=None),
        "secrets_read": _DomainReadService(
            "secrets_read",
            explain={"lifecycle": {"rotation": {"status": "unknown"}}},
        ),
        "supplychain_read": _DomainReadService("supplychain_read", explain=None),
    }
    for name, service in services.items():
        runtime.kernel._services[name] = cast(Any, service)
    return SurfaceApplication(runtime), services


async def test_surface_inventory_uses_real_kernel_service_and_local_scope() -> None:
    app, inventory, _findings, _vulnerabilities = _app(
        inventory=_InventoryReport(assets=["ast_one", "ast_two"], total=2)
    )

    response = await app.handle("GET", "/api/v1/inventory?limit=1")
    payload = _payload(response.body)

    assert response.status == 200
    assert inventory.tenant_calls == [None]
    assert payload["items"] == [{"asset_id": "ast_one"}]
    assert payload["next_cursor"] is not None
    assert payload["inventory"]["degraded"] is False


async def test_surface_paginates_the_10173_finding_acceptance_scale() -> None:
    findings = [
        _Finding(id=f"fnd_acceptance_{index:05d}", title=f"Finding {index}")
        for index in range(10_173)
    ]
    app, _inventory, finding_service, _vulnerabilities = _app(findings=findings)
    cursor: str | None = None
    seen: list[str] = []

    while True:
        target = f"/api/v1/findings?limit={MAX_PAGE_SIZE}"
        if cursor is not None:
            target += f"&cursor={cursor}"
        response = await app.handle("GET", target)
        payload = _payload(response.body)
        assert response.status == 200
        assert payload["returned"] <= MAX_PAGE_SIZE
        seen.extend(item["id"] for item in payload["items"])
        cursor = payload["next_cursor"]
        if cursor is None:
            break

    assert seen == [finding.id for finding in findings]
    assert finding_service.tenant_calls == [None] * 102


async def test_surface_refuses_collection_beyond_work_budget() -> None:
    assets = [f"ast_over_budget_{index}" for index in range(SURFACE_WORK_BUDGET + 1)]
    app, _inventory, _findings, _vulnerabilities = _app(
        inventory=_InventoryReport(assets=assets, total=len(assets))
    )

    response = await app.handle("GET", "/api/v1/inventory")

    assert response.status == 503
    assert _payload(response.body)["error"]["code"] == "SurfaceUnavailable"


async def test_surface_cursor_is_bound_to_route_and_tenant_scope() -> None:
    app, _inventory, _findings, _vulnerabilities = _app(
        inventory=_InventoryReport(assets=["ast_one", "ast_two"], total=2)
    )
    first = _payload((await app.handle("GET", "/api/v1/inventory?limit=1")).body)

    response = await app.handle(
        "GET",
        f"/api/v1/vulnerabilities?limit=1&cursor={first['next_cursor']}",
    )

    assert response.status == 400
    assert "does not belong" in _payload(response.body)["error"]["message"]


async def test_findings_and_offset_cursors_refuse_cross_route_replay_both_directions() -> None:
    app, _inventory, _findings, _vulnerabilities = _app(
        inventory=_InventoryReport(assets=["ast_one", "ast_two"], total=2),
        findings=[_Finding(id="fnd_one", title="One"), _Finding(id="fnd_two", title="Two")],
    )
    inventory_page = _payload((await app.handle("GET", "/api/v1/inventory?limit=1")).body)
    findings_page = _payload((await app.handle("GET", "/api/v1/findings?limit=1")).body)

    findings_with_inventory_cursor = await app.handle(
        "GET",
        f"/api/v1/findings?limit=1&cursor={inventory_page['next_cursor']}",
    )
    inventory_with_findings_cursor = await app.handle(
        "GET",
        f"/api/v1/inventory?limit=1&cursor={findings_page['next_cursor']}",
    )

    assert findings_with_inventory_cursor.status == 400
    assert inventory_with_findings_cursor.status == 400
    assert "does not belong" in _payload(findings_with_inventory_cursor.body)["error"]["message"]
    assert "does not belong" in _payload(inventory_with_findings_cursor.body)["error"]["message"]


@pytest.mark.parametrize("route", ["inventory", "findings"])
async def test_surface_cursor_refuses_cross_tenant_replay(route: str) -> None:
    first_tenant = str(uuid4())
    second_tenant = str(uuid4())
    app, _inventory, _findings, _vulnerabilities = _app(
        tenant_mode="enterprise",
        inventory=_InventoryReport(assets=["ast_one", "ast_two"], total=2),
        findings=[_Finding(id="fnd_one", title="One"), _Finding(id="fnd_two", title="Two")],
    )
    first_page = _payload(
        (
            await app.handle(
                "GET",
                f"/api/v1/{route}?tenant_id={first_tenant}&limit=1",
            )
        ).body
    )

    response = await app.handle(
        "GET",
        f"/api/v1/{route}?tenant_id={second_tenant}&limit=1&cursor={first_page['next_cursor']}",
    )

    assert response.status == 400
    assert "does not belong" in _payload(response.body)["error"]["message"]


async def test_surface_refuses_pre_ecr0093_unscoped_finding_cursor_cleanly() -> None:
    app, _inventory, _findings, _vulnerabilities = _app(
        findings=[_Finding(id="fnd_one", title="One"), _Finding(id="fnd_two", title="Two")]
    )

    response = await app.handle("GET", "/api/v1/findings?limit=1&cursor=1")

    assert response.status == 400
    assert _payload(response.body)["error"]["code"] == "SurfaceRequestInvalid"


def test_only_named_snapshot_routes_use_offset_pagination() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(SurfaceApplication)))
    callers: set[str] = set()
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)):
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_page_request"
            for node in ast.walk(function)
        ):
            callers.add(function.name)

    assert callers == {"_inventory", "_vulnerabilities"}


async def test_named_snapshot_exemptions_keep_honesty_metadata_visible() -> None:
    app, _inventory, _findings, _vulnerabilities = _app(
        inventory=_InventoryReport(
            assets=["ast_one"],
            total=1,
            degraded=True,
            source_freshness={"asset_store": NOW},
        ),
        assessment=_Assessment(priorities=[], degraded=True),
    )

    inventory = _payload((await app.handle("GET", "/api/v1/inventory")).body)["inventory"]
    assessment = _payload((await app.handle("GET", "/api/v1/vulnerabilities")).body)["assessment"]

    assert inventory == {
        "as_of": NOW.isoformat(),
        "degraded": True,
        "source_freshness": {"asset_store": NOW.isoformat()},
        "total": 1,
    }
    assert assessment == {
        "coverage": {"scanned": [], "unscanned": [], "stale": [], "unassessable": []},
        "degraded": True,
        "generated_at": NOW.isoformat(),
        "suppressed_count": 0,
        "unavailable": [],
    }


async def test_surface_requires_explicit_enterprise_tenant() -> None:
    tenant_id = str(uuid4())
    app, inventory, _findings, _vulnerabilities = _app(tenant_mode="enterprise")

    missing = await app.handle("GET", "/api/v1/inventory")
    selected = await app.handle("GET", f"/api/v1/inventory?tenant_id={tenant_id}")

    assert missing.status == 400
    assert _payload(missing.body)["error"]["code"] == "TenantScopeRequired"
    assert selected.status == 200
    assert inventory.tenant_calls == [tenant_id]


async def test_surface_local_none_is_not_presented_as_an_all_tenants_wildcard() -> None:
    app, inventory, _findings, _vulnerabilities = _app()

    response = await app.handle("GET", f"/api/v1/inventory?tenant_id={uuid4()}")

    assert response.status == 400
    assert "this local estate, not all tenants" in _payload(response.body)["error"]["message"]
    assert inventory.tenant_calls == []


async def test_surface_preserves_unknown_factor_reasons() -> None:
    priority = _Priority(
        vulnerability_id="vln_one",
        score=0.64,
        priority="high",
        factors={
            "mission": {
                "status": "unknown",
                "reason": "no mission declaration supplied",
                "weight": 0.0,
            }
        },
    )
    app, _inventory, _findings, vulnerabilities = _app(
        assessment=_Assessment(priorities=[priority])
    )

    response = await app.handle("GET", "/api/v1/vulnerabilities")
    payload = _payload(response.body)

    assert response.status == 200
    assert vulnerabilities.tenant_calls == [None]
    assert payload["items"][0]["factors"]["mission"]["status"] == "unknown"
    assert payload["items"][0]["factors"]["mission"]["reason"] == (
        "no mission declaration supplied"
    )


@pytest.mark.parametrize(
    ("route", "service_name", "method_name", "has_explanation"),
    [
        ("ispm", "ispm_read", "list_postures", True),
        ("exposure", "exposure_read", "list_exposures", False),
        ("secrets", "secrets_read", "list_assets", True),
        ("supplychain", "supplychain_read", "list_components", False),
    ],
)
async def test_widened_routes_use_owner_reads_and_preserve_honesty_fields(
    route: str,
    service_name: str,
    method_name: str,
    has_explanation: bool,
) -> None:
    app, services = _domain_app()

    response = await app.handle("GET", f"/api/v1/{route}?limit=17")
    payload = _payload(response.body)

    assert response.status == 200
    assert services[service_name].calls == [(method_name, None, 17, None)]
    assert (payload["items"][0]["explain"] is not None) is has_explanation
    assert payload["degraded"] is True
    assert payload["degradation_reasons"] == ["owner read reports partial coverage"]
    assert payload["next_cursor"] == "owner-keyset-cursor"


@pytest.mark.parametrize(
    ("route", "service_name", "method_name"),
    [
        ("ispm", "ispm_read", "get_posture"),
        ("exposure", "exposure_read", "get_exposure"),
        ("secrets", "secrets_read", "get_asset"),
        ("supplychain", "supplychain_read", "get_component"),
    ],
)
async def test_widened_detail_routes_use_the_owner_detail_contract(
    route: str,
    service_name: str,
    method_name: str,
) -> None:
    app, services = _domain_app()

    response = await app.handle("GET", f"/api/v1/{route}/record_detail")
    payload = _payload(response.body)

    assert response.status == 200
    assert payload["item"]["record"]["id"] == "record_detail"
    assert services[service_name].calls == [(method_name, None, None, "record_detail")]


@pytest.mark.parametrize(
    ("route", "service_name", "method_name"),
    [
        ("ispm", "ispm_read", "list_postures"),
        ("exposure", "exposure_read", "list_exposures"),
        ("secrets", "secrets_read", "list_assets"),
        ("supplychain", "supplychain_read", "list_components"),
    ],
)
async def test_widened_routes_apply_the_enterprise_tenant_rule_before_owner_read(
    route: str,
    service_name: str,
    method_name: str,
) -> None:
    tenant_id = str(uuid4())
    app, services = _domain_app(tenant_mode="enterprise")

    missing = await app.handle("GET", f"/api/v1/{route}")
    selected = await app.handle("GET", f"/api/v1/{route}?tenant_id={tenant_id}")

    assert missing.status == 400
    assert selected.status == 200
    assert services[service_name].calls == [(method_name, tenant_id, 50, None)]


@pytest.mark.parametrize("route", ["ispm", "exposure", "secrets", "supplychain"])
async def test_widened_detail_routes_refuse_nested_paths(route: str) -> None:
    app, services = _domain_app()

    response = await app.handle("GET", f"/api/v1/{route}/record/extra")

    assert response.status == 404
    assert not [call for service in services.values() for call in service.calls]


async def test_surface_route_table_is_closed_and_read_only() -> None:
    app, _inventory, _findings, _vulnerabilities = _app()

    unknown = await app.handle("GET", "/api/v1/actions")
    write = await app.handle("POST", "/api/v1/inventory")

    assert unknown.status == 404
    assert write.status == 405
    assert write.headers["Allow"] == "GET, HEAD"


async def test_surface_html_is_local_and_dependency_free() -> None:
    app, _inventory, _findings, _vulnerabilities = _app()

    response = await app.handle("GET", "/")
    html = response.body.decode("utf-8")

    assert response.status == 200
    assert "AQELYN" in html
    assert "https://" not in html
    assert "http://" not in html
    assert "/assets/app.css" in html
    assert "/assets/app.js" in html
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


async def test_surface_serves_javascript_without_multiline_quote_strings() -> None:
    app, _inventory, _findings, _vulnerabilities = _app()

    response = await app.handle("GET", "/assets/app.js")
    script = response.body.decode("utf-8")
    unmatched_lines = [
        line_number
        for line_number, line in enumerate(script.splitlines(), start=1)
        if _unescaped_double_quote_count(line) % 2
    ]

    assert response.status == 200
    assert unmatched_lines == []
    assert '.join("\\n")' in script


def test_surface_javascript_quote_guard_rejects_a_consumed_newline_escape() -> None:
    broken = 'const summary = parts.join("\n");'

    unmatched_lines = [
        line_number
        for line_number, line in enumerate(broken.splitlines(), start=1)
        if _unescaped_double_quote_count(line) % 2
    ]

    assert unmatched_lines == [1, 2]


async def test_surface_hidden_state_overrides_component_display_rules() -> None:
    app, _inventory, _findings, _vulnerabilities = _app()

    response = await app.handle("GET", "/assets/app.css")
    css = response.body.decode("utf-8")

    assert response.status == 200
    assert "[hidden] { display: none !important; }" in css


def _unescaped_double_quote_count(line: str) -> int:
    count = 0
    escaped = False
    for character in line:
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            count += 1
    return count
