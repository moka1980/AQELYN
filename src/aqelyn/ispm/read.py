"""Read-only ISPM posture projection owned by the ISPM package."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.ispm.engine import ISPMEngine
from aqelyn.ispm.models import IdentityPostureScore
from aqelyn.ispm.store import ISPMStore
from aqelyn.kernel.read import ReadItem, ReadPage, decode_keyset_cursor, encode_keyset_cursor
from aqelyn.kernel.service import HealthStatus

_CURSOR_NAMESPACE = "ispm-posture-v1"
_HEALTH_TENANT = "00000000-0000-0000-0000-000000000000"


class ISPMReadService:
    """Expose persisted posture and its owner derivation without a write method."""

    def __init__(
        self,
        store: ISPMStore,
        engine: ISPMEngine,
        *,
        tenant_mode: Literal["local", "enterprise"],
        dependencies: Sequence[str] = ("ispm_engine",),
        critical: bool = False,
    ) -> None:
        self._store = store
        self._engine = engine
        self._tenant_mode = tenant_mode
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "ispm_read"

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

    async def list_postures(
        self,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> ReadPage[IdentityPostureScore]:
        after: tuple[str, str] | None = None
        namespace = _cursor_namespace(tenant_id)
        if cursor is not None:
            values = decode_keyset_cursor(cursor, namespace=namespace, arity=2)
            after = values[0], values[1]
        scores, next_key = await self._store.query_scores_for_read(
            tenant_id=tenant_id,
            after=after,
            limit=limit,
        )
        return ReadPage(
            items=tuple(
                ReadItem(record=score, explain=self._engine.explain(score)) for score in scores
            ),
            next_cursor=(
                None
                if next_key is None
                else encode_keyset_cursor(namespace=namespace, values=next_key)
            ),
        )

    async def get_posture(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> ReadItem[IdentityPostureScore] | None:
        score = await self._store.get_score(score_id, tenant_id=tenant_id)
        if score is None:
            return None
        return ReadItem(record=score, explain=self._engine.explain(score))

    async def _check_store(self) -> None:
        tenant_id = _HEALTH_TENANT if self._tenant_mode == "enterprise" else None
        try:
            await self._store.query_scores_for_read(tenant_id=tenant_id, limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"ISPM read store unavailable: {exc}") from exc


def _cursor_namespace(tenant_id: str | None) -> str:
    return f"{_CURSOR_NAMESPACE}:{tenant_id or 'local'}"
