"""Installed-command and lifecycle tests for the local operator surface."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import aqelyn.__main__ as installed
import aqelyn.surface.cli as surface_cli
from aqelyn.kernel import AQELYNConfig


def test_installed_command_dispatches_surface_without_breaking_report(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def surface(argv: list[str]) -> int:
        calls.append(("surface", argv))
        return 7

    def report(argv: list[str]) -> int:
        calls.append(("report", argv))
        return 8

    monkeypatch.setattr(installed, "surface_main", surface)
    monkeypatch.setattr(installed, "reporting_main", report)

    assert installed.main(["surface", "--port", "9000"]) == 7
    assert installed.main(["collection", "--reuse"]) == 8
    assert calls == [
        ("surface", ["--port", "9000"]),
        ("report", ["collection", "--reuse"]),
    ]


async def test_surface_cli_uses_factory_runtime_and_closes_both_lifecycles(
    monkeypatch: Any,
) -> None:
    lifecycle: list[str] = []

    class Kernel:
        async def start(self) -> None:
            lifecycle.append("kernel:start")

        async def stop(self, *, reason: str) -> None:
            lifecycle.append(f"kernel:stop:{reason}")

    runtime = SimpleNamespace(kernel=Kernel())

    async def create_runtime(_config: object) -> object:
        lifecycle.append("factory")
        return runtime

    class Server:
        def __init__(self, _application: object, *, port: int) -> None:
            assert port == 9000
            self.port = port

        async def start(self) -> None:
            lifecycle.append("server:start")

        async def serve_forever(self) -> None:
            lifecycle.append("server:serve")

        async def close(self) -> None:
            lifecycle.append("server:close")

    monkeypatch.setattr(AQELYNConfig, "load", lambda: object())
    monkeypatch.setattr(surface_cli, "create_runtime", create_runtime)
    monkeypatch.setattr(surface_cli, "SurfaceApplication", lambda selected: selected)
    monkeypatch.setattr(surface_cli, "SurfaceServer", Server)

    await surface_cli.run_surface(port=9000)

    assert lifecycle == [
        "factory",
        "kernel:start",
        "server:start",
        "server:serve",
        "server:close",
        "kernel:stop:surface_shutdown",
    ]
