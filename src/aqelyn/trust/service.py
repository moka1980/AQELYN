"""Trust Engine AQService wrapper (EA-0006 TR4)."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.conventions.errors import TrustConfigInvalid
from aqelyn.kernel.service import HealthStatus
from aqelyn.trust.engine import TrustEngine
from aqelyn.trust.models import TrustConfig


class TrustEngineService:
    def __init__(self, engine: TrustEngine, *, critical: bool = True) -> None:
        self.engine = engine
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "trust_engine"

    @property
    def dependencies(self) -> Sequence[str]:
        return ()

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_available()
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def health(self) -> HealthStatus:
        try:
            await self._check_available()
        except TrustConfigInvalid as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)
        except Exception as exc:
            return HealthStatus(
                status="unavailable", ready=False, detail=f"registry unavailable: {exc}"
            )
        if not self._started:
            return HealthStatus(status="degraded", ready=False, detail="service not started")
        return HealthStatus(status="healthy", ready=True)

    async def _check_available(self) -> None:
        self._check_config()
        await self.engine.registry.get()

    def _check_config(self) -> None:
        TrustConfig.model_validate(self.engine.config.model_dump())
