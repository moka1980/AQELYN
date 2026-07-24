"""GC-002 event-namespace closure conformance (ECR-0058).

The fourth CI-enforced §0 guarantee. AC-1 freezes the registered event-type set
(grouped by owner); AC-2 asserts every prefix maps to a real shipped package via a
derived, reasoned allow-list; AC-3 runs both on every backend/tenant-mode and under
``python -O``. AC-1 and AC-2 catch *different* defects and neither substitutes for
the other (spec §2). GC-002 adds no runtime surface.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

import pytest

from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime, create_runtime
from guarantees.controls import (
    CYBER_EVENT,
    SMUGGLED_EVENT,
    register_cyber_event,
    register_smuggled_event,
)
from guarantees.discovery import GuaranteeViolation
from guarantees.event_ownership import (
    GOLDEN_EVENT_TYPES,
    PREFIX_OWNERSHIP,
    assert_event_types_frozen,
    assert_prefix_ownership,
    golden_event_types,
    prefix_of,
    registered_event_types,
    registered_prefixes,
    registry_of,
    source_root_has_no_guarantee_surface,
    this_helper_is_under_tests,
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


# --- AC-1: registered event-type closure (load-bearing) ------------------------
def test_gc_event_discovery_from_runtime() -> None:
    # Discovery, not declaration: the set comes from the wired runtime registry,
    # and a newly registered event appears without any golden-set edit.
    runtime = create_inmemory_runtime()
    before = registered_event_types(runtime)
    assert {"aqelyn.exposure.detected", "aqelyn.kernel.runtime_started"} <= before

    registry_of(runtime).register("aqelyn.exposure.gc_probe", 1, None)
    after = registered_event_types(runtime)
    assert "aqelyn.exposure.gc_probe" in after
    assert after - before == {"aqelyn.exposure.gc_probe"}


def test_gc_event_types_frozen() -> None:
    runtime = create_inmemory_runtime()
    assert_event_types_frozen(registered_event_types(runtime))
    # The golden set is grouped by owner (§3), so an addition is visible as
    # "<owner> gained an event", not one line lost in a flat list of hundreds.
    assert all(
        prefix_of(event_type) == prefix
        for prefix, group in GOLDEN_EVENT_TYPES.items()
        for event_type in group
    )
    assert golden_event_types() == registered_event_types(runtime)


def test_gc_negative_control_new_event_type() -> None:
    # AC-1c: mint a parallel `aqelyn.cyber.*` namespace; closure must flag it.
    runtime = create_inmemory_runtime()
    minted = register_cyber_event(registry_of(runtime))
    assert minted == CYBER_EVENT
    assert CYBER_EVENT in registered_event_types(runtime)
    with pytest.raises(GuaranteeViolation, match="outside the frozen golden set"):
        assert_event_types_frozen(registered_event_types(runtime))


def test_gc_closure_catches_new_event_under_existing_prefix() -> None:
    # AC-1's distinct value (spec §2): a new event under an owner that legitimately
    # exists slips past AC-2 but must be caught by the frozen closure.
    runtime = create_inmemory_runtime()
    minted = register_smuggled_event(registry_of(runtime))
    assert minted == SMUGGLED_EVENT
    assert prefix_of(SMUGGLED_EVENT) in PREFIX_OWNERSHIP  # AC-2 would pass it
    assert_prefix_ownership(registered_prefixes(runtime))  # AC-2 does not fire
    with pytest.raises(GuaranteeViolation, match="outside the frozen golden set"):
        assert_event_types_frozen(registered_event_types(runtime))  # AC-1 does


# --- AC-2: prefix ownership ----------------------------------------------------
def test_gc_prefix_ownership() -> None:
    runtime = create_inmemory_runtime()
    assert_prefix_ownership(registered_prefixes(runtime))
    # Every registered prefix has a reasoned entry; no extra entries linger.
    assert registered_prefixes(runtime) == frozenset(PREFIX_OWNERSHIP)


def test_gc_prefix_multi_ownership() -> None:
    # FR-5: ownership is many-to-one. One package owns several prefixes.
    assert PREFIX_OWNERSHIP["lake"].package == "lake"
    assert PREFIX_OWNERSHIP["telemetry"].package == "lake"
    assert PREFIX_OWNERSHIP["object"].package == "objects"
    assert PREFIX_OWNERSHIP["relationship"].package == "objects"
    # The map is not a bijection: fewer distinct packages than prefixes.
    packages = {entry.package for entry in PREFIX_OWNERSHIP.values()}
    assert len(packages) < len(PREFIX_OWNERSHIP)


def test_gc_prefix_allowlist_reasoned() -> None:
    for prefix, entry in PREFIX_OWNERSHIP.items():
        assert entry.reason.strip(), f"{prefix} entry has no reason"
        assert entry.package, f"{prefix} entry has no package"
        # CORE_EVENTS-seeded prefixes record registry-seeding as their reason (§4).
        if entry.core_seeded:
            assert prefix in {"kernel", "object", "relationship"}
            assert "CORE_EVENTS" in entry.reason


def test_gc_negative_control_unowned_prefix() -> None:
    # AC-2d: an unowned prefix (`aqelyn.cyber.`) must fail — the actual IS-037 case.
    runtime = create_inmemory_runtime()
    register_cyber_event(registry_of(runtime))
    assert "cyber" in registered_prefixes(runtime)
    with pytest.raises(GuaranteeViolation, match="has no owning package"):
        assert_prefix_ownership(registered_prefixes(runtime))


# --- AC-3: matrix + python -O --------------------------------------------------
@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_gc_event_matrix(backend: Backend, tenant_mode: TenantMode) -> None:
    runtime = await _runtime(backend, tenant_mode)
    try:
        assert_event_types_frozen(registered_event_types(runtime))
        assert_prefix_ownership(registered_prefixes(runtime))
        assert registered_event_types(runtime) == golden_event_types()
    finally:
        await _close_postgres_pools(runtime)


def test_gc_event_guards_survive_optimized_python() -> None:
    script = """
from aqelyn.kernel import create_inmemory_runtime
from guarantees.controls import register_cyber_event, register_smuggled_event
from guarantees.discovery import GuaranteeViolation
from guarantees.event_ownership import (
    assert_event_types_frozen,
    assert_prefix_ownership,
    registered_event_types,
    registered_prefixes,
    registry_of,
)

# Baseline: the real runtime passes both guards.
base = create_inmemory_runtime()
assert_event_types_frozen(registered_event_types(base))
assert_prefix_ownership(registered_prefixes(base))

# AC-1 negative control (new prefix) must raise explicitly, not be stripped by -O.
r1 = create_inmemory_runtime()
register_cyber_event(registry_of(r1))
try:
    assert_event_types_frozen(registered_event_types(r1))
except GuaranteeViolation:
    pass
else:
    raise SystemExit('optimized Python bypassed the event-closure control')

# AC-1 subtler control (new event, existing prefix) must still raise.
r2 = create_inmemory_runtime()
register_smuggled_event(registry_of(r2))
try:
    assert_event_types_frozen(registered_event_types(r2))
except GuaranteeViolation:
    pass
else:
    raise SystemExit('optimized Python bypassed the smuggled-event control')

# AC-2 negative control (unowned prefix) must raise explicitly.
try:
    assert_prefix_ownership(registered_prefixes(r1))
except GuaranteeViolation:
    pass
else:
    raise SystemExit('optimized Python bypassed the prefix-ownership control')
"""
    environment = dict(os.environ)
    root = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(root / "src"),
            str(root / "tests"),
            environment.get("PYTHONPATH", ""),
        )
        if part
    )
    completed = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


# --- AC-4: no runtime surface --------------------------------------------------
def test_gc_event_no_runtime_surface() -> None:
    assert source_root_has_no_guarantee_surface()
    assert this_helper_is_under_tests()


def _fresh_config(backend: Backend, tenant_mode: TenantMode) -> AQELYNConfig:
    return AQELYNConfig(backend=backend, tenant_mode=tenant_mode)


async def _runtime(backend: Backend, tenant_mode: TenantMode) -> Runtime:
    config = _fresh_config(backend, tenant_mode)
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
        if hasattr(result, "__await__"):
            await result
