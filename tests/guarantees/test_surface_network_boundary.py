"""ECR-0088: outbound stays absent; inbound is loopback and surface-owned."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aqelyn.kernel import AQELYNConfig
from aqelyn.surface import LOOPBACK_HOST, READ_ROUTES
from guarantees.surface_network_guard import discover_network_boundary

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "aqelyn"
BRANCHES = frozenset(("outbound", "listener", "literal"))


def test_surface_network_boundary_holds_in_shipped_source() -> None:
    signals = discover_network_boundary(SRC)

    assert signals.outbound_clients == ()
    assert signals.listeners_outside_surface == ()
    assert signals.network_literals == ()


def test_surface_network_guard_branch_roster_pinned() -> None:
    assert frozenset(("outbound", "listener", "literal")) == BRANCHES


@pytest.mark.parametrize(
    ("branch", "source", "attribute"),
    [
        ("outbound", "import httpx\n", "outbound_clients"),
        (
            "listener",
            (
                "import asyncio\nasync def run():\n"
                "    await asyncio.start_server(None, '127.0.0.1', 1)\n"
            ),
            "listeners_outside_surface",
        ),
        ("literal", 'transport = "requests"\n', "network_literals"),
    ],
)
def test_surface_network_guard_each_branch_has_a_unique_witness(
    tmp_path: Path,
    branch: str,
    source: str,
    attribute: str,
) -> None:
    package = tmp_path / "domain"
    package.mkdir()
    (package / "probe.py").write_text(source, encoding="utf-8")

    signals = discover_network_boundary(tmp_path)
    selected = getattr(signals, attribute)
    others = [
        getattr(signals, name)
        for name in ("outbound_clients", "listeners_outside_surface", "network_literals")
        if name != attribute
    ]
    disabled = discover_network_boundary(tmp_path, branches=BRANCHES - {branch})

    assert len(selected) == 1
    assert others == [(), ()]
    assert getattr(disabled, attribute) == ()


def test_surface_listener_is_loopback_without_a_configuration_knob() -> None:
    assert LOOPBACK_HOST == "127.0.0.1"
    assert not {"host", "bind_address", "surface_host"} & set(AQELYNConfig.model_fields)


def test_surface_route_table_contains_no_write_command() -> None:
    forbidden = ("action", "approve", "decommission", "ingest", "propose", "write")

    assert all(not any(word in route for word in forbidden) for route in READ_ROUTES)


def test_surface_imports_no_domain_engine_or_store() -> None:
    forbidden_suffixes = (".engine", ".memory", ".postgres", ".store")
    imports: set[str] = set()
    for path in (SRC / "surface").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module)

    assert not sorted(module for module in imports if module.endswith(forbidden_suffixes))
