"""GC1/GC2 discovery and execution-authority conformance."""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
from typing import Any, Literal

import pytest

from aqelyn.exposure import active_reachability_action_spec
from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime, create_runtime
from aqelyn.workflow import ActionSpec, ReadOnlyEchoHandler
from guarantees.controls import RogueEngine
from guarantees.discovery import (
    EXECUTION_SCAN_EXCLUSIONS,
    GuaranteeViolation,
    aqelyn_source_root,
    assert_no_direct_handler_invocations,
    assert_no_direct_handler_invocations_in,
    assert_runtime_action_authority,
    discover_packages,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
Backend = Literal["memory", "postgres"]
TenantMode = Literal["local", "enterprise"]
MATRIX: tuple[tuple[Backend, TenantMode], ...] = (
    ("memory", "local"),
    ("memory", "enterprise"),
    ("postgres", "local"),
    ("postgres", "enterprise"),
)


def test_gc_engine_discovery_complete(tmp_path: Path) -> None:
    actual = {package.name for package in discover_packages()}
    assert {"workflow", "risk", "vuln", "secrets", "ispm"} <= actual
    assert EXECUTION_SCAN_EXCLUSIONS == {
        "workflow": (
            "EA-0008 is the canonical execution owner; its handler dispatch is the "
            "behavior every other package must route through."
        )
    }

    temporary_root = tmp_path / "aqelyn"
    _package(temporary_root, "first")
    assert {package.name for package in discover_packages(temporary_root)} == {"first"}

    _package(temporary_root, "arrived_later")
    assert {package.name for package in discover_packages(temporary_root)} == {
        "arrived_later",
        "first",
    }


def test_gc_no_runtime_surface() -> None:
    source_root = aqelyn_source_root()
    assert not (source_root / "guarantees").exists()
    assert not (source_root / "gc001").exists()
    assert Path(__file__).resolve().parent.parent.name == "tests"


def test_gc_only_workflow_executes() -> None:
    runtime = create_inmemory_runtime()
    runtime.workflow_action_registry.register(ReadOnlyEchoHandler(action_type="gc.workflow-owned"))

    assert_runtime_action_authority(runtime)
    assert [spec.action_type for spec in runtime.workflow_action_registry.list()] == [
        "gc.workflow-owned"
    ]


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_gc_matrix(backend: Backend, tenant_mode: TenantMode) -> None:
    runtime = await _runtime(backend, tenant_mode)
    try:
        runtime.workflow_action_registry.register(
            ReadOnlyEchoHandler(action_type=f"gc.{backend}.{tenant_mode}")
        )
        assert_runtime_action_authority(runtime)
        assert_no_direct_handler_invocations()
    finally:
        await _close_postgres_pools(runtime)


def test_gc_benign_apply_not_flagged() -> None:
    root = aqelyn_source_root()
    sites = (
        ("cspm/baselines.py", "apply"),
        ("sspm/baselines.py", "apply"),
        ("cspm/route.py", "apply"),
        ("sspm/route.py", "apply"),
        ("lake/retention.py", "apply"),
    )
    for relative_path, function_name in sites:
        path = root / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert any(
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function_name
            for node in ast.walk(tree)
        )

    assert_no_direct_handler_invocations()


def test_gc_actionspec_reference_not_flagged() -> None:
    action = active_reachability_action_spec()

    assert isinstance(action, ActionSpec)
    assert action.action_type == "exposure.active_reachability_collection"
    assert action.capability == "scan.active"
    assert not hasattr(action, "execute")
    assert_no_direct_handler_invocations()


async def test_gc_negative_control_rogue_handler() -> None:
    runtime = create_inmemory_runtime()
    rogue = RogueEngine()

    outcome = await rogue.execute_outside_workflow()

    assert outcome["idempotency_key"] == "rogue-control"
    assert rogue.handler.executions == 1
    with pytest.raises(GuaranteeViolation, match="alternate ActionRegistry"):
        assert_runtime_action_authority(runtime, additional_roots=(rogue,))

    source = Path(inspect.getsourcefile(RogueEngine) or "")
    with pytest.raises(GuaranteeViolation, match="direct ActionHandler invocation"):
        assert_no_direct_handler_invocations_in((source,))


def _package(root: Path, name: str) -> None:
    selected = root / name
    selected.mkdir(parents=True)
    (selected / "__init__.py").write_text('"""Temporary discovered package."""\n', encoding="utf-8")


async def _runtime(backend: Backend, tenant_mode: TenantMode) -> Runtime:
    config = AQELYNConfig(backend=backend, tenant_mode=tenant_mode)
    if backend == "memory":
        return create_inmemory_runtime(config)
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    return await create_runtime(config.model_copy(update={"database_url": PG_URL}))


async def _close_postgres_pools(runtime: Runtime) -> None:
    pools: dict[int, Any] = {}
    for value in vars(runtime).values():
        pool = getattr(value, "_pool", None)
        if pool is not None and callable(getattr(pool, "close", None)):
            pools[id(pool)] = pool
    for pool in pools.values():
        result = pool.close()
        if inspect.isawaitable(result):
            await result
