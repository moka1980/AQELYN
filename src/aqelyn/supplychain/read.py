"""Read-only component projection owned by the supply-chain package."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.kernel.read import ReadItem, ReadPage, decode_keyset_cursor, encode_keyset_cursor
from aqelyn.kernel.service import HealthStatus
from aqelyn.supplychain.models import ProvenanceStatus, SoftwareComponent
from aqelyn.supplychain.store import SBOMStore

_CURSOR_NAMESPACE = "supplychain-component-v1"
_HEALTH_TENANT = "00000000-0000-0000-0000-000000000000"


class SupplyChainReadService:
    """Expose component inventory; component-level explanation is not implemented."""

    def __init__(
        self,
        store: SBOMStore,
        *,
        tenant_mode: Literal["local", "enterprise"],
        dependencies: Sequence[str] = ("supplychain_engine",),
        critical: bool = False,
    ) -> None:
        self._store = store
        self._tenant_mode = tenant_mode
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "supplychain_read"

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

    async def list_components(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> ReadPage[SoftwareComponent]:
        after: tuple[ProvenanceStatus, str] | None = None
        namespace = _cursor_namespace(tenant_id)
        if cursor is not None:
            provenance, object_id = decode_keyset_cursor(
                cursor,
                namespace=namespace,
                arity=2,
            )
            after = cast(ProvenanceStatus, provenance), object_id
        records, next_key = await self._store.query_components_for_read(
            tenant_id=tenant_id,
            after=after,
            limit=limit,
        )
        return ReadPage(
            items=tuple(ReadItem(record=record, explain=None) for record in records),
            next_cursor=(
                None
                if next_key is None
                else encode_keyset_cursor(namespace=namespace, values=next_key)
            ),
        )

    async def get_component(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> ReadItem[SoftwareComponent] | None:
        record = await self._store.get_component_by_object_id(object_id, tenant_id=tenant_id)
        return None if record is None else ReadItem(record=record, explain=None)

    async def _check_store(self) -> None:
        tenant_id = _HEALTH_TENANT if self._tenant_mode == "enterprise" else None
        try:
            await self._store.query_components_for_read(tenant_id=tenant_id, limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"supply-chain read store unavailable: {exc}") from exc


def _cursor_namespace(tenant_id: str | None) -> str:
    return f"{_CURSOR_NAMESPACE}:{tenant_id or 'local'}"
