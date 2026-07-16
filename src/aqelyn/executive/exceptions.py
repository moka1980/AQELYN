"""Material exception source contract for executive reports (EA-0022 X3)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from aqelyn.conventions.errors import ExceptionsUnavailable, StoreUnavailable
from aqelyn.executive.models import Figure


class MaterialExceptionSource(Protocol):
    async def material_exceptions(
        self, *, period: str, tenant_id: str | None
    ) -> Sequence[Figure]: ...


async def collect_material_exceptions(
    source: MaterialExceptionSource, *, period: str, tenant_id: str | None
) -> list[Figure]:
    try:
        rows = await source.material_exceptions(period=period, tenant_id=tenant_id)
    except ExceptionsUnavailable:
        raise
    except StoreUnavailable as exc:
        raise ExceptionsUnavailable(exc.message) from exc
    except Exception as exc:
        raise ExceptionsUnavailable(str(exc)) from exc
    return [Figure.model_validate(row.model_dump(mode="json")) for row in rows]
