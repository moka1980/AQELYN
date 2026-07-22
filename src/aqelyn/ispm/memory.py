"""In-memory append-only ISPM store (EA-0033 G2)."""

from __future__ import annotations

from aqelyn.conventions.errors import (
    CrossTenantReference,
    ISPMConfigInvalid,
    OptimisticConcurrencyConflict,
)
from aqelyn.ispm.models import (
    IdentityBaseline,
    IdentityDriftSnapshot,
    IdentityPostureScore,
    NormalizedIdentity,
    NormalizedIdentityKind,
)
from aqelyn.ispm.store import (
    validate_baseline,
    validate_baseline_id,
    validate_cursor,
    validate_drift,
    validate_drift_id,
    validate_external_id,
    validate_identity,
    validate_identity_kind,
    validate_limit,
    validate_object_id,
    validate_provider,
    validate_score,
    validate_score_id,
    validate_tenant_scope,
    validate_write_tenant,
)


class InMemoryISPMStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._history: dict[str, list[NormalizedIdentity]] = {}
        self._identities: dict[tuple[str | None, str, str], str] = {}
        self._scores: dict[str, IdentityPostureScore] = {}
        self._baselines: dict[str, list[IdentityBaseline]] = {}
        self._drifts: dict[str, IdentityDriftSnapshot] = {}

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

    async def put_score(self, score: IdentityPostureScore) -> IdentityPostureScore:
        stored = validate_score(score)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        current = self._scores.get(stored.id)
        if current is not None:
            if current.model_dump(mode="json") != stored.model_dump(mode="json"):
                raise OptimisticConcurrencyConflict("posture scores are append-only")
            return current.model_copy(deep=True)
        self._scores[stored.id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def get_score(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityPostureScore | None:
        selected_id = validate_score_id(score_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        stored = self._scores.get(selected_id)
        if stored is None or not self._visible(stored.tenant_id, selected_tenant):
            return None
        return validate_score(stored)

    async def put_baseline(self, baseline: IdentityBaseline) -> IdentityBaseline:
        stored = validate_baseline(baseline)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        history = self._baselines.setdefault(stored.id, [])
        if history:
            current = history[-1]
            if current.tenant_id != stored.tenant_id:
                raise CrossTenantReference("identity baseline tenant_id cannot change")
            if current.version == stored.version:
                if current.model_dump(mode="json") != stored.model_dump(mode="json"):
                    raise OptimisticConcurrencyConflict("identity baseline version is append-only")
                return current.model_copy(deep=True)
            if stored.version <= current.version:
                raise OptimisticConcurrencyConflict("identity baseline version must increase")
        history.append(stored.model_copy(deep=True))
        return stored.model_copy(deep=True)

    async def get_baseline(
        self,
        baseline_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityBaseline | None:
        selected_id = validate_baseline_id(baseline_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        history = self._baselines.get(selected_id)
        if not history or not self._visible(history[-1].tenant_id, selected_tenant):
            return None
        return validate_baseline(history[-1])

    async def put_drift(self, snapshot: IdentityDriftSnapshot) -> IdentityDriftSnapshot:
        stored = validate_drift(snapshot)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        current = self._drifts.get(stored.id)
        if current is not None:
            if current.model_dump(mode="json") != stored.model_dump(mode="json"):
                raise OptimisticConcurrencyConflict("identity drift snapshots are append-only")
            return current.model_copy(deep=True)
        self._drifts[stored.id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def get_drift(
        self,
        snapshot_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityDriftSnapshot | None:
        selected_id = validate_drift_id(snapshot_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        stored = self._drifts.get(selected_id)
        if stored is None or not self._visible(stored.tenant_id, selected_tenant):
            return None
        return validate_drift(stored)

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local":
            return row_tenant_id is None and requested_tenant_id is None
        return row_tenant_id == requested_tenant_id
