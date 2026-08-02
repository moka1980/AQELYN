"""Read-only AQService projection for the Finding owner."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.findings.models import Finding, FindingQuery
from aqelyn.findings.store import FindingStore
from aqelyn.kernel.service import HealthStatus

_HEALTH_TENANT = "00000000-0000-0000-0000-000000000000"


class FindingReadService:
    """Expose the owner's existing keyset query without adding a write path."""

    def __init__(
        self,
        store: FindingStore,
        *,
        tenant_mode: Literal["local", "enterprise"],
        dependencies: Sequence[str] = ("event_bus",),
        critical: bool = False,
    ) -> None:
        self.store = store
        self.tenant_mode = tenant_mode
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "finding_read"

    @property
    def dependencies(self) -> Sequence[str]:
        return self._dependencies

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_store()
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def health(self) -> HealthStatus:
        try:
            await self._check_store()
        except StoreUnavailable as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)
        if not self._started:
            return HealthStatus(status="degraded", ready=False, detail="service not started")
        return HealthStatus(status="healthy", ready=True)

    async def query(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Finding], str | None]:
        return await self.store.query(FindingQuery(tenant_id=tenant_id, limit=limit, cursor=cursor))

    async def _check_store(self) -> None:
        tenant_id = _HEALTH_TENANT if self.tenant_mode == "enterprise" else None
        try:
            await self.store.query(FindingQuery(tenant_id=tenant_id, limit=1))
        except Exception as exc:
            raise StoreUnavailable(f"finding read store unavailable: {exc}") from exc
