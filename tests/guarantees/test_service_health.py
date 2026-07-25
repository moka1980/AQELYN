"""GC-003: every registered service starts and reports ready in BOTH tenant modes.

Rule 11 exists *because* this was found once. It was then found again in C-038 —
`idthreat_engine` and `response_engine` both hardcoded `tenant_id=None` in their health
probes, so both failed enterprise startup outright, and neither the rule nor any test
caught it. `create_inmemory_runtime()` defaults to `tenant_mode="local"`, so driving the
factory-built runtime proved nothing about enterprise.

That is ECR-0057's argument verbatim: the refusal tests exist but are decentralized, and
**nothing fails when a new module omits one**. This converts rule 11 from a convention a
reviewer must remember into a mechanical check.

**Discovery-based, not a hardcoded list.** The suite enumerates whatever the kernel has
registered, so a service added tomorrow is covered without anyone remembering to add it
here — the same property that makes GC-001 and GC-002 worth having. A hardcoded roster
would need the same vigilance the rule already failed to get.

**Behavioural, not structural (ECR-0007).** It does not check that a health *test*
exists; it starts the real kernel in each mode and asserts every service actually
reports ready. Asserting a test exists would be satisfied by a test that asserts
nothing.
"""

from __future__ import annotations

import pytest

from aqelyn.conventions.errors import ServiceStartFailed, StoreUnavailable
from aqelyn.kernel.config import AQELYNConfig
from aqelyn.kernel.factory import create_inmemory_runtime
from aqelyn.objects import InMemoryObjectStore
from guarantees.controls import UnscopedHealthService

TENANT_MODES = ["local", "enterprise"]


@pytest.mark.parametrize("tenant_mode", TENANT_MODES)
async def test_gc_every_service_starts_in_both_tenant_modes(tenant_mode: str) -> None:
    """The kernel starts cleanly in each mode — no service refuses its own startup."""
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode=tenant_mode))

    await runtime.kernel.start()

    assert runtime.kernel._services, "discovery found no registered services"


@pytest.mark.parametrize("tenant_mode", TENANT_MODES)
async def test_gc_every_service_reports_ready_in_both_tenant_modes(tenant_mode: str) -> None:
    """Every discovered service is ready — enumerated, not sampled.

    A probe that issues tenant-scoped reads must be tenant-scoped itself (rule 11).
    In enterprise mode an unscoped read is refused, so this fails for exactly the
    services that forgot.
    """
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode=tenant_mode))
    await runtime.kernel.start()

    unready: list[tuple[str, str, str]] = []
    for name, service in sorted(runtime.kernel._services.items()):
        status = await service.health()
        if not status.ready:
            unready.append((name, status.status, status.detail or ""))

    assert unready == [], f"services not ready in {tenant_mode} mode: {unready}"


async def test_gc_health_discovery_covers_the_whole_registry() -> None:
    """Both modes register the same services, so neither can be checked in isolation.

    If enterprise registered a subset, the check above could pass while skipping the
    services most likely to have the defect.
    """
    local = create_inmemory_runtime(AQELYNConfig(tenant_mode="local"))
    enterprise = create_inmemory_runtime(AQELYNConfig(tenant_mode="enterprise"))

    assert set(local.kernel._services) == set(enterprise.kernel._services)
    assert len(local.kernel._services) >= 30


# --- negative control (rule 19: the control performs the omission) ----------------


async def test_gc_negative_control_unscoped_probe_fails_enterprise() -> None:
    """A service that omits `_health_tenant()` must fail — otherwise this suite is inert.

    Rule 24: a contract suite that has never been run against a broken implementation
    is an untested test. `UnscopedHealthService` is the real omission — a registered
    `AQService` whose probe hardcodes `tenant_id=None`, exactly as `idthreat_engine`
    and `response_engine` did before C-038.
    """
    control = UnscopedHealthService(InMemoryObjectStore(mode="enterprise"))

    with pytest.raises(StoreUnavailable, match="tenant"):
        await control.start()

    status = await control.health()
    assert status.ready is False


async def test_gc_negative_control_passes_in_local_mode() -> None:
    """The control is specifically a *both-modes* failure, not a broken service.

    It starts fine in `local` — which is why checking only the default mode is what let
    the real defect ship. If this ever fails, the control has become a service that is
    simply broken and no longer models the omission.
    """
    control = UnscopedHealthService(InMemoryObjectStore(mode="local"))

    await control.start()

    assert (await control.health()).ready is True


async def test_gc_negative_control_would_be_caught_by_the_registry_check() -> None:
    """Wired into a real kernel, the omission fails enterprise startup.

    This closes the loop: the control is not merely a class that raises, it is a
    service the kernel refuses to start — the same `ServiceStartFailed` the two real
    services produced before C-038.
    """
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode="enterprise"))
    runtime.kernel.register(UnscopedHealthService(InMemoryObjectStore(mode="enterprise")))

    with pytest.raises(ServiceStartFailed):
        await runtime.kernel.start()
