"""Typed SSPM owner-routing boundary (EA-0029 Z2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from aqelyn.sspm.models import NormalizedSaaSObject, SaaSRouteOwner


class SaaSOwnerRouter(Protocol):
    owner: SaaSRouteOwner

    async def route(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> Sequence[str]: ...
