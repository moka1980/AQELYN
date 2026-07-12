"""T6 acceptance tests for EA-0001 (§12)."""

from collections.abc import Sequence

import pytest

from aqelyn.conventions.errors import ConfigError, ServiceStartFailed
from aqelyn.events import InMemoryEventBus
from aqelyn.kernel import AQELYNConfig, AQKernel, HealthStatus, create_inmemory_runtime


class FakeService:
    def __init__(
        self,
        name: str,
        deps: Sequence[str] = (),
        *,
        critical: bool = True,
        log: list[tuple[str, str]] | None = None,
        fail_start: bool = False,
        status: str = "healthy",
        ready: bool = True,
    ) -> None:
        self._name = name
        self._deps = tuple(deps)
        self._critical = critical
        self._log = log if log is not None else []
        self._fail = fail_start
        self._status = status
        self._ready = ready

    @property
    def name(self) -> str:
        return self._name

    @property
    def dependencies(self) -> Sequence[str]:
        return self._deps

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        if self._fail:
            raise RuntimeError(f"{self._name} boom")
        self._log.append(("start", self._name))

    async def stop(self) -> None:
        self._log.append(("stop", self._name))

    async def health(self) -> HealthStatus:
        return HealthStatus(status=self._status, ready=self._ready)


def _kernel() -> AQKernel:
    return AQKernel(AQELYNConfig(backend="memory"), event_bus=InMemoryEventBus())


async def test_kernel_ordered_lifecycle() -> None:
    log: list[tuple[str, str]] = []
    k = _kernel()
    k.register(FakeService("db", log=log))
    k.register(FakeService("api", ["db"], log=log))
    await k.start()
    await k.stop()
    assert log[0] == ("start", "db")
    assert log[1] == ("start", "api")
    assert log[-2] == ("stop", "api")
    assert log[-1] == ("stop", "db")


async def test_kernel_cycle_detected() -> None:
    k = _kernel()
    k.register(FakeService("a", ["b"]))
    k.register(FakeService("b", ["a"]))
    with pytest.raises(ConfigError):
        await k.start()


async def test_kernel_critical_fail_aborts() -> None:
    k = _kernel()
    k.register(FakeService("ok"))
    k.register(FakeService("bad", ["ok"], critical=True, fail_start=True))
    with pytest.raises(ServiceStartFailed):
        await k.start()
    assert k.phase == "created"


async def test_kernel_degraded_mode() -> None:
    k = _kernel()
    k.register(FakeService("core"))
    k.register(FakeService("optional", critical=False, fail_start=True))
    await k.start()
    assert k.phase == "degraded"


async def test_kernel_dependency_injection() -> None:
    rt = create_inmemory_runtime()
    await rt.kernel.start()
    # object store's sink publishes to the SAME injected bus
    from datetime import UTC, datetime

    from aqelyn.conventions import ActorRef, new_id
    from aqelyn.objects import AQObject, SourceRef

    now = datetime.now(UTC)
    sys = ActorRef(actor_type="system", actor_id="t")
    await rt.object_store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            display_name="x",
            sources=[SourceRef(source_id=new_id("src"), observed_at=now, method="t")],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=sys,
            updated_by=sys,
        )
    )
    assert any(e.event_type == "aqelyn.object.created" for e in rt.event_bus.log)
    await rt.kernel.stop()


async def test_kernel_health_aggregation() -> None:
    k = _kernel()
    k.register(FakeService("core"))
    k.register(FakeService("side", critical=False, status="degraded"))
    await k.start()
    state = await k.health()
    assert state.services["_kernel"].status == "degraded"


async def test_kernel_readiness() -> None:
    k = _kernel()
    k.register(FakeService("core", ready=False))
    await k.start()
    state = await k.health()
    assert state.services["_kernel"].ready is False


async def test_kernel_lifecycle_events() -> None:
    bus = InMemoryEventBus()
    k = AQKernel(AQELYNConfig(backend="memory"), event_bus=bus)
    k.register(FakeService("core"))
    await k.start()
    await k.stop()
    types = [e.event_type for e in bus.log]
    assert "aqelyn.kernel.runtime_started" in types
    assert "aqelyn.kernel.runtime_stopped" in types


async def test_kernel_sigterm_graceful() -> None:
    k = _kernel()
    k.register(FakeService("core"))
    await k.start()
    await k.signal_stop()
    assert k.phase == "stopped"


async def test_kernel_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AQELYN_BACKEND", "postgres")
    monkeypatch.delenv("AQELYN_DATABASE_URL", raising=False)
    with pytest.raises(ConfigError):
        AQELYNConfig.load()


async def test_kernel_inmemory_only() -> None:
    rt = create_inmemory_runtime()
    await rt.kernel.start()
    state = await rt.kernel.health()
    assert state.phase in ("running", "degraded")
    await rt.kernel.stop()
    assert rt.kernel.phase == "stopped"
