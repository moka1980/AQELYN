"""In-memory append-only ISPM store (EA-0033 G2)."""

from __future__ import annotations

from aqelyn.conventions.errors import (
    CrossTenantReference,
    ISPMConfigInvalid,
)
from aqelyn.ispm.models import NormalizedIdentity, NormalizedIdentityKind
from aqelyn.ispm.store import (
    validate_cursor,
    validate_external_id,
    validate_identity,
    validate_identity_kind,
    validate_limit,
    validate_object_id,
    validate_provider,
    validate_tenant_scope,
    validate_write_tenant,
)


class InMemoryISPMStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._history: dict[str, list[NormalizedIdentity]] = {}
        self._identities: dict[tuple[str | None, str, str], str] = {}

    async def upsert_identity(self, identity: NormalizedIdentity) -> NormalizedIdentity:
        stored = validate_identity(identity)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        key = (stored.tenant_id, stored.provider, stored.external_id)
        mapped = self._identities.get(key)
        if mapped is not None and mapped != stored.object_id:
            raise ISPMConfigInvalid("normalized identity key cannot change object_id")
        history = self._history.get(stored.object_id)
        if history:
            current = history[-1]
            if current.tenant_id != stored.tenant_id:
                raise CrossTenantReference("normalized identity tenant_id cannot change")
            if current.provider != stored.provider or current.external_id != stored.external_id:
                raise ISPMConfigInvalid("normalized identity object_id cannot change identity key")
            if current.model_dump(mode="json") == stored.model_dump(mode="json"):
                return current.model_copy(deep=True)
        self._identities[key] = stored.object_id
        self._history.setdefault(stored.object_id, []).append(stored.model_copy(deep=True))
        return stored.model_copy(deep=True)

    async def get_identity(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity | None:
        selected_id = validate_object_id(object_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        history = self._history.get(selected_id)
        if not history or not self._visible(history[-1].tenant_id, selected_tenant):
            return None
        return history[-1].model_copy(deep=True)

    async def get_identity_by_external(
        self,
        provider: str,
        external_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity | None:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provider = validate_provider(provider)
        if selected_provider is None:
            raise ISPMConfigInvalid("provider must not be empty")
        selected_external = validate_external_id(external_id)
        object_id = self._identities.get((selected_tenant, selected_provider, selected_external))
        if object_id is None:
            return None
        return self._history[object_id][-1].model_copy(deep=True)

    async def query_identities(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        identity_kind: NormalizedIdentityKind | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[NormalizedIdentity], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provider = validate_provider(provider)
        selected_kind = validate_identity_kind(identity_kind)
        selected_cursor = validate_cursor(cursor)
        selected_limit = validate_limit(limit)
        rows = sorted(
            (
                history[-1]
                for history in self._history.values()
                if self._visible(history[-1].tenant_id, selected_tenant)
                and (selected_provider is None or history[-1].provider == selected_provider)
                and (selected_kind is None or history[-1].identity_kind == selected_kind)
                and (selected_cursor is None or history[-1].object_id > selected_cursor)
            ),
            key=lambda item: item.object_id,
        )
        page = rows[:selected_limit]
        next_cursor = page[-1].object_id if len(rows) > selected_limit else None
        return [item.model_copy(deep=True) for item in page], next_cursor

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local":
            return row_tenant_id is None and requested_tenant_id is None
        return row_tenant_id == requested_tenant_id
