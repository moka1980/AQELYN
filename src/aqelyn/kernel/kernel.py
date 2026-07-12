"""AQKernel: lifecycle, health, dependency-ordered supervision (EA-0001)."""

from __future__ import annotations

import asyncio
from typing import Any

from aqelyn.conventions import configure_logging, get_logger, new_id, utc_now
from aqelyn.conventions.actors import ActorRef
from aqelyn.conventions.errors import ConfigError, ServiceStartFailed
from aqelyn.events import Event, EventBus, Subject
from aqelyn.kernel.service import AQService, HealthStatus, KernelState

_SYS = ActorRef(actor_type="system", actor_id="kernel")


def _topo_sort(services: dict[str, AQService]) -> list[str]:
    """Return start order; raise on missing dep or cycle."""
    order: list[str] = []
    temp: set[str] = set()
    done: set[str] = set()

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in done:
            return
        if name in temp:
            raise ConfigError(f"dependency cycle: {' -> '.join([*stack, name])}")
        if name not in services:
            raise ConfigError(f"unknown dependency: {name}")
        temp.add(name)
        for dep in services[name].dependencies:
            visit(dep, (*stack, name))
        temp.discard(name)
        done.add(name)
        order.append(name)

    for svc_name in services:
        visit(svc_name, ())
    return order


class AQKernel:
    def __init__(self, config: Any, *, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self._services: dict[str, AQService] = {}
        self._started: list[str] = []
        self.phase = "created"
        self._log = get_logger("aqelyn.kernel")

    def register(self, service: AQService) -> None:
        if self.phase != "created":
            raise ConfigError("cannot register services after start")
        self._services[service.name] = service

    async def start(self) -> None:
        configure_logging(getattr(self.config, "log_level", "INFO"))
        self.phase = "starting"
        order = _topo_sort(self._services)
        degraded = False
        for name in order:
            svc = self._services[name]
            try:
                await svc.start()
                self._started.append(name)
            except Exception as exc:
                if svc.critical:
                    await self._rollback()
                    self.phase = "created"
                    raise ServiceStartFailed(f"critical service {name} failed: {exc}") from exc
                degraded = True
                self._log.warning("non-critical service failed", extra={"service": name})
        self.phase = "degraded" if degraded else "running"
        await self._emit_lifecycle("aqelyn.kernel.runtime_started", {"version": "0.1.0"})

    async def _rollback(self) -> None:
        for name in reversed(self._started):
            try:
                await self._services[name].stop()
            except Exception:  # best-effort teardown
                self._log.warning("stop failed during rollback", extra={"service": name})
        self._started.clear()

    async def stop(self, *, reason: str = "shutdown") -> None:
        if self.phase in ("stopped", "stopping"):
            return
        self.phase = "stopping"
        await self._emit_lifecycle("aqelyn.kernel.runtime_stopped", {"reason": reason})
        for name in reversed(self._started):
            try:
                await asyncio.wait_for(self._services[name].stop(), timeout=10)
            except (TimeoutError, Exception):
                self._log.warning("service stop timeout/failure", extra={"service": name})
        self._started.clear()
        self.phase = "stopped"

    async def health(self) -> KernelState:
        statuses: dict[str, HealthStatus] = {}
        agg = "healthy"
        ready = True
        for name, svc in self._services.items():
            hs = await svc.health()
            statuses[name] = hs
            if svc.critical and hs.status == "unavailable":
                agg = "unavailable"
            elif hs.status != "healthy" and agg != "unavailable":
                agg = "degraded"
            if svc.critical and not hs.ready:
                ready = False
        phase = self.phase
        if phase == "running" and agg != "healthy":
            phase = "degraded"
        state = KernelState(phase=phase, services=statuses)
        # readiness surfaced via a synthetic entry
        state.services.setdefault(
            "_kernel", HealthStatus(status=agg, ready=ready, detail=f"phase={phase}")
        )
        return state

    def get_service(self, name: str) -> AQService:
        return self._services[name]

    async def _emit_lifecycle(self, event_type: str, payload: dict[str, object]) -> None:
        now = utc_now()
        await self.event_bus.publish(
            Event(
                id=new_id("evt"),
                event_type=event_type,
                schema_version=1,
                occurred_at=now,
                recorded_at=now,
                producer=_SYS,
                subject=Subject(),
                payload=payload,
                partition_key="kernel",
            )
        )

    def signal_stop(self) -> asyncio.Task[None]:
        """Schedule graceful shutdown (wired to SIGTERM/SIGINT)."""
        return asyncio.create_task(self.stop(reason="signal"))
