"""Decision store protocols and validation helpers (EA-0020 E2)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import DecisionConfigInvalid, SchemaValidationError
from aqelyn.decision.derive import validate_replayable_recommendation
from aqelyn.decision.models import ModelVersion, Recommendation


class RecommendationStore(Protocol):
    async def put(self, recommendation: Recommendation) -> Recommendation: ...

    async def get(
        self, recommendation_id: str, *, tenant_id: str | None = None
    ) -> Recommendation | None: ...

    async def query(
        self, *, tenant_id: str | None = None, limit: int = 100
    ) -> list[Recommendation]: ...


class ModelVersionStore(Protocol):
    async def put(
        self, model_version: ModelVersion, *, tenant_id: str | None = None
    ) -> ModelVersion: ...

    async def get(self, version: int, *, tenant_id: str | None = None) -> ModelVersion | None: ...

    async def active(self, *, tenant_id: str | None = None) -> ModelVersion: ...

    async def promote(
        self,
        version: int,
        *,
        by: ActorRef,
        reason: str,
        evidence_id: str,
        tenant_id: str | None = None,
    ) -> ModelVersion: ...


def validate_recommendation_id(value: str, *, field: str = "recommendation_id") -> str:
    return require_typed_id(value, "rec", field=field)


def validate_recommendation(recommendation: Recommendation) -> Recommendation:
    return validate_replayable_recommendation(recommendation)


def validate_model_version(model_version: ModelVersion) -> ModelVersion:
    return ModelVersion.model_validate(model_version.model_dump(mode="json"))


def validate_inactive_model_version(model_version: ModelVersion) -> ModelVersion:
    stored = validate_model_version(model_version)
    if stored.active:
        raise DecisionConfigInvalid("model versions must be activated by promote")
    return stored


def validate_model_version_number(value: int, *, field: str = "model version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DecisionConfigInvalid(f"{field} must be >= 1")
    return value


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DecisionConfigInvalid("limit must be >= 1")
    return value


def validate_promotion_reason(value: str) -> str:
    if not value.strip():
        raise DecisionConfigInvalid("promotion reason must not be empty")
    return value


def validate_promotion_actor(value: ActorRef) -> ActorRef:
    if not isinstance(value, ActorRef):
        raise DecisionConfigInvalid("promotion requires an attributed ActorRef")
    return value


def validate_promotion_evidence_id(value: str) -> str:
    try:
        return require_typed_id(value, "evd", field="promotion evidence_id")
    except SchemaValidationError as exc:
        raise DecisionConfigInvalid("promotion requires evidence_id") from exc
