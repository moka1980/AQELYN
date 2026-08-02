"""AST discovery for ECR-0088's relocated network boundary."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

OUTBOUND_MODULES = frozenset(("aiohttp", "http.client", "httpx", "requests", "urllib.request"))
LISTENER_MODULES = frozenset(("http.server", "socket", "socketserver"))
LISTENER_CALLS = frozenset(
    (
        "asyncio.start_server",
        "asyncio.start_unix_server",
        "socket.socket",
    )
)
NETWORK_LITERALS = OUTBOUND_MODULES | LISTENER_MODULES


@dataclass(frozen=True)
class NetworkBoundarySignals:
    outbound_clients: tuple[str, ...]
    listeners_outside_surface: tuple[str, ...]
    network_literals: tuple[str, ...]


def discover_network_boundary(
    root: Path,
    *,
    branches: frozenset[str] = frozenset(("outbound", "listener", "literal")),
) -> NetworkBoundarySignals:
    outbound: list[str] = []
    listeners: list[str] = []
    literals: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        in_surface = relative == "surface.py" or relative.startswith("surface/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if "outbound" in branches:
                outbound.extend(_outbound_hits(node, relative))
            if "listener" in branches and not in_surface:
                listeners.extend(_listener_hits(node, relative))
            if (
                "literal" in branches
                and isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in NETWORK_LITERALS
            ):
                literals.append(f"{relative}:{node.lineno}: {node.value}")
    return NetworkBoundarySignals(
        outbound_clients=tuple(outbound),
        listeners_outside_surface=tuple(listeners),
        network_literals=tuple(literals),
    )


def _outbound_hits(node: ast.AST, relative: str) -> list[str]:
    hits: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name in OUTBOUND_MODULES:
                hits.append(f"{relative}:{node.lineno}: {alias.name}")
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        imported = {alias.name for alias in node.names}
        if module in OUTBOUND_MODULES or (module == "urllib" and "request" in imported):
            hits.append(f"{relative}:{node.lineno}: {module}")
    elif isinstance(node, ast.Call):
        name = _qualified_name(node.func)
        if name in {"asyncio.open_connection", "socket.create_connection"}:
            hits.append(f"{relative}:{node.lineno}: {name}")
    return hits


def _listener_hits(node: ast.AST, relative: str) -> list[str]:
    hits: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name in LISTENER_MODULES:
                hits.append(f"{relative}:{node.lineno}: {alias.name}")
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        imported = {alias.name for alias in node.names}
        if module in LISTENER_MODULES:
            hits.append(f"{relative}:{node.lineno}: {module}")
        elif module == "http" and "server" in imported:
            hits.append(f"{relative}:{node.lineno}: http.server")
        elif module == "asyncio" and imported & {"start_server", "start_unix_server"}:
            selected = sorted(imported & {"start_server", "start_unix_server"})[0]
            hits.append(f"{relative}:{node.lineno}: asyncio.{selected}")
    elif isinstance(node, ast.Call):
        name = _qualified_name(node.func)
        if name in LISTENER_CALLS or name.endswith((".create_server", ".create_unix_server")):
            hits.append(f"{relative}:{node.lineno}: {name}")
    return hits


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""
