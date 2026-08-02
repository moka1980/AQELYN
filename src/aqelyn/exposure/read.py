"""Read-only exposure projection owned by the exposure package."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from aqelyn.conventions.errors import SchemaValidationError, StoreUnavailable
from aqelyn.exposure.models import ExposureRecord
from aqelyn.exposure.store import ExposureStore
from aqelyn.kernel.read import ReadItem, ReadPage, decode_keyset_cursor, encode_keyset_cursor
from aqelyn.kernel.service import HealthStatus

_CURSOR_NAMESPACE = "exposure-record-v1"
_HEALTH_TENANT = "00000000-0000-0000-0000-000000000000"


class ExposureReadService:
    """Expose persisted exposures; this domain has no record explanation API yet."""

    def __init__(
        self,
        store: ExposureStore,
        *,
        tenant_mode: Literal["local", "enterprise"],
        dependencies: Sequence[str] = ("exposure_engine",),
        critical: bool = False,
    ) -> None:
        self._store = store
        self._tenant_mode = tenant_mode
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "exposure_read"

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

    async def list_exposures(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> ReadPage[ExposureRecord]:
        namespace = _cursor_namespace(tenant_id)
        after = None if cursor is None else _decode_cursor(cursor, namespace=namespace)
        records, next_key = await self._store.query_for_read(
            tenant_id=tenant_id,
            after=after,
            limit=limit,
        )
        return ReadPage(
            items=tuple(ReadItem(record=record, explain=None) for record in records),
            next_cursor=(
                None
                if next_key is None
                else encode_keyset_cursor(
                    namespace=namespace,
                    values=(next_key[0].isoformat(), next_key[1]),
                )
            ),
        )

    async def get_exposure(
        self,
        exposure_id: str,
        *,
        tenant_id: str | None,
    ) -> ReadItem[ExposureRecord] | None:
        record = await self._store.get(exposure_id, tenant_id=tenant_id)
        return None if record is None else ReadItem(record=record, explain=None)

    async def _check_store(self) -> None:
        tenant_id = _HEALTH_TENANT if self._tenant_mode == "enterprise" else None
        try:
            await self._store.query_for_read(tenant_id=tenant_id, limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"exposure read store unavailable: {exc}") from exc


def _decode_cursor(value: str, *, namespace: str) -> tuple[datetime, str]:
    raw_time, exposure_id = decode_keyset_cursor(
        value,
        namespace=namespace,
        arity=2,
    )
    try:
        discovered_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaValidationError("exposure cursor timestamp is malformed") from exc
    return discovered_at, exposure_id


def _cursor_namespace(tenant_id: str | None) -> str:
    return f"{_CURSOR_NAMESPACE}:{tenant_id or 'local'}"
