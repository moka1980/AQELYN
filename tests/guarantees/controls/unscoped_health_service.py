"""A service whose health probe is not tenant-scoped, proving GC-003 has teeth (rule 19).

The control *performs* the omission — it registers a real `AQService` whose probe
issues an unscoped read — rather than asserting about it. Rule 11 says a probe issuing
tenant-scoped reads must be tenant-scoped itself; this is a service that forgot, which
is exactly what `idthreat_engine` and `response_engine` were before C-038.

If the guarantee is neutered, this control stops failing. That is how the suite is
verified by mutation.
"""

from __future__ import annotations

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects import ObjectQuery
from aqelyn.objects.store import ObjectStore


class UnscopedHealthService:
    """Registers cleanly, starts in `local`, and fails startup in `enterprise`.

    This is the shape rule 11 exists to prevent: the probe hardcodes `tenant_id=None`
    instead of deriving a probe tenant from the store's mode, so the service works in
    development and refuses to start for every enterprise deployment.
    """

    name = "unscoped_health_control"
    dependencies: tuple[str, ...] = ()
    critical = True

    def __init__(self, object_store: ObjectStore) -> None:
        self.object_store = object_store

    async def start(self) -> None:
        await self._probe()

    async def stop(self) -> None:
        return None

    async def health(self) -> HealthStatus:
        try:
            await self._probe()
        except Exception as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=f"unscoped health probe failed: {exc}",
                dependencies={},
            )
        return HealthStatus(status="healthy", ready=True, detail=None, dependencies={})

    async def _probe(self) -> None:
        try:
            # The omission: no `_health_tenant()`, so this is refused in enterprise.
            await self.object_store.query(ObjectQuery(tenant_id=None, limit=1))
        except Exception as exc:
            raise StoreUnavailable(f"object store unavailable: {exc}") from exc
