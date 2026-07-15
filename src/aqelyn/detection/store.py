"""Threat Detection persistence protocols and validation helpers (EA-0017 D2)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import DetectionConfigInvalid
from aqelyn.detection.models import BehaviorProfile, DetectionRule


class RuleStore(Protocol):
    async def put(self, rule: DetectionRule) -> DetectionRule: ...

    async def get(self, rule_id: str, *, version: int | None = None) -> DetectionRule | None: ...

    async def list(
        self, *, tenant_id: str | None, enabled_only: bool = True
    ) -> list[DetectionRule]: ...


class ProfileStore(Protocol):
    async def put(self, profile: BehaviorProfile) -> BehaviorProfile: ...

    async def get(
        self, profile_id: str, *, version: int | None = None
    ) -> BehaviorProfile | None: ...

    async def latest(
        self, *, subject_ref: str, metric: str, tenant_id: str | None
    ) -> BehaviorProfile | None: ...


def validate_rule_id(value: str, *, field: str = "rule_id") -> str:
    if not value.strip():
        raise DetectionConfigInvalid(f"{field} must not be empty")
    return value


def validate_profile_id(value: str, *, field: str = "profile_id") -> str:
    return require_typed_id(value, "prf", field=field)


def validate_rule(rule: DetectionRule) -> DetectionRule:
    return DetectionRule.model_validate(rule.model_dump(mode="json"))


def validate_profile(profile: BehaviorProfile) -> BehaviorProfile:
    return BehaviorProfile.model_validate(profile.model_dump(mode="json"))


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise DetectionConfigInvalid(f"{field} must be >= 1")
    return value


def normalize_enabled_only(value: bool) -> bool:
    if not isinstance(value, bool):
        raise DetectionConfigInvalid("enabled_only must be a bool")
    return value
