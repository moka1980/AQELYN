"""In-memory decision stores (EA-0020 E2)."""

from __future__ import annotations

import copy

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    ModelVersionNotFound,
    OptimisticConcurrencyConflict,
    TenantScopeRequired,
)
from aqelyn.decision.models import ModelVersion, Recommendation
from aqelyn.decision.store import (
    validate_limit,
    validate_model_version,
    validate_model_version_number,
    validate_promotion_reason,
    validate_recommendation,
    validate_recommendation_id,
    validate_tenant,
)


class InMemoryRecommendationStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._recommendations: dict[str, Recommendation] = {}

    async def put(self, recommendation: Recommendation) -> Recommendation:
        stored = validate_recommendation(recommendation)
        if stored.id in self._recommendations:
            raise OptimisticConcurrencyConflict(f"recommendation already exists: {stored.id}")
        self._recommendations[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(
        self, recommendation_id: str, *, tenant_id: str | None = None
    ) -> Recommendation | None:
        validate_recommendation_id(recommendation_id)
        tenant_id = validate_tenant(tenant_id)
        recommendation = self._recommendations.get(recommendation_id)
        if recommendation is None or not self._visible(recommendation.tenant_id, tenant_id):
            return None
        return copy.deepcopy(recommendation)

    async def query(
        self, *, tenant_id: str | None = None, limit: int = 100
    ) -> list[Recommendation]:
        tenant_id = validate_tenant(tenant_id)
        validate_limit(limit)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("recommendation query must be tenant-scoped")
        rows = [
            copy.deepcopy(row)
            for row in self._recommendations.values()
            if self._visible(row.tenant_id, tenant_id)
        ]
        rows.sort(key=lambda row: (row.created_at.isoformat(), row.id))
        return rows[:limit]

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id


class InMemoryModelVersionStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._versions: dict[tuple[str | None, int], ModelVersion] = {}

    async def put(
        self, model_version: ModelVersion, *, tenant_id: str | None = None
    ) -> ModelVersion:
        tenant_id = validate_tenant(tenant_id)
        stored = validate_model_version(model_version)
        key = (tenant_id, stored.version)
        if key in self._versions:
            raise OptimisticConcurrencyConflict(f"model version already exists: {stored.version}")
        if stored.active:
            self._deactivate(tenant_id)
        self._versions[key] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, version: int, *, tenant_id: str | None = None) -> ModelVersion | None:
        version = validate_model_version_number(version)
        tenant_id = validate_tenant(tenant_id)
        selected = self._versions.get((tenant_id, version))
        if selected is None:
            return None
        return copy.deepcopy(selected)

    async def active(self, *, tenant_id: str | None = None) -> ModelVersion:
        tenant_id = validate_tenant(tenant_id)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("active model version must be tenant-scoped")
        candidates = [
            version
            for (stored_tenant, _), version in self._versions.items()
            if stored_tenant == tenant_id and version.active
        ]
        if not candidates:
            raise ModelVersionNotFound("no active model version")
        selected = max(candidates, key=lambda version: version.version)
        return copy.deepcopy(selected)

    async def promote(
        self,
        version: int,
        *,
        by: ActorRef,
        reason: str,
        tenant_id: str | None = None,
        evidence_id: str | None = None,
    ) -> ModelVersion:
        version = validate_model_version_number(version)
        tenant_id = validate_tenant(tenant_id)
        validate_promotion_reason(reason)
        key = (tenant_id, version)
        existing = self._versions.get(key)
        if existing is None:
            raise ModelVersionNotFound(f"model version not found: {version}")
        self._deactivate(tenant_id)
        promoted = existing.model_copy(
            update={
                "active": True,
                "promoted_by": by,
                "promoted_at": utc_now(),
                "evidence_id": evidence_id or new_id("evd"),
            },
            deep=True,
        )
        self._versions[key] = validate_model_version(promoted)
        return copy.deepcopy(self._versions[key])

    def _deactivate(self, tenant_id: str | None) -> None:
        for key, version in list(self._versions.items()):
            if key[0] == tenant_id and version.active:
                self._versions[key] = version.model_copy(update={"active": False}, deep=True)
