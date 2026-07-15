"""In-memory Threat Detection stores (EA-0017 D2)."""

from __future__ import annotations

import copy

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict
from aqelyn.detection.models import BehaviorProfile, DetectionRule
from aqelyn.detection.store import (
    normalize_enabled_only,
    validate_positive,
    validate_profile,
    validate_profile_id,
    validate_rule,
    validate_rule_id,
    validate_tenant,
)


class InMemoryRuleStore:
    def __init__(self) -> None:
        self._rules: dict[tuple[str, int], DetectionRule] = {}

    async def put(self, rule: DetectionRule) -> DetectionRule:
        stored = validate_rule(rule)
        key = (stored.id, stored.version)
        if key in self._rules:
            raise OptimisticConcurrencyConflict(
                f"detection rule version already exists: {stored.id} v{stored.version}"
            )
        self._rules[key] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, rule_id: str, *, version: int | None = None) -> DetectionRule | None:
        validate_rule_id(rule_id)
        if version is not None:
            validate_positive(version, field="version")
            rule = self._rules.get((rule_id, version))
            return None if rule is None else copy.deepcopy(rule)
        candidates = [rule for (stored_id, _), rule in self._rules.items() if stored_id == rule_id]
        if not candidates:
            return None
        latest = max(candidates, key=lambda rule: rule.version)
        return copy.deepcopy(latest)

    async def list(
        self, *, tenant_id: str | None, enabled_only: bool = True
    ) -> list[DetectionRule]:
        tenant_id = validate_tenant(tenant_id)
        enabled_only = normalize_enabled_only(enabled_only)
        latest_by_id: dict[str, DetectionRule] = {}
        for rule in self._rules.values():
            if not _visible(rule.tenant_id, tenant_id):
                continue
            if enabled_only and not rule.enabled:
                continue
            existing = latest_by_id.get(rule.id)
            if existing is None or rule.version > existing.version:
                latest_by_id[rule.id] = rule
        rows = [copy.deepcopy(rule) for rule in latest_by_id.values()]
        rows.sort(key=lambda rule: (rule.tenant_id is not None, rule.tenant_id or "", rule.id))
        return rows


class InMemoryProfileStore:
    def __init__(self) -> None:
        self._profiles: dict[tuple[str, int], BehaviorProfile] = {}

    async def put(self, profile: BehaviorProfile) -> BehaviorProfile:
        incoming = validate_profile(profile)
        latest = self._latest_for_logical(
            tenant_id=incoming.tenant_id,
            subject_ref=incoming.subject_ref,
            metric=incoming.metric,
        )
        stored = incoming.model_copy(
            update={
                "id": latest.id if latest is not None else incoming.id or new_id("prf"),
                "version": 1 if latest is None else latest.version + 1,
            },
            deep=True,
        )
        self._profiles[(stored.id, stored.version)] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, profile_id: str, *, version: int | None = None) -> BehaviorProfile | None:
        validate_profile_id(profile_id)
        if version is not None:
            validate_positive(version, field="version")
            profile = self._profiles.get((profile_id, version))
            return None if profile is None else copy.deepcopy(profile)
        candidates = [
            profile for (stored_id, _), profile in self._profiles.items() if stored_id == profile_id
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda profile: version_sort_key(profile))
        return copy.deepcopy(latest)

    async def latest(
        self, *, subject_ref: str, metric: str, tenant_id: str | None
    ) -> BehaviorProfile | None:
        tenant_id = validate_tenant(tenant_id)
        latest = self._latest_for_logical(
            tenant_id=tenant_id,
            subject_ref=subject_ref,
            metric=metric,
        )
        return None if latest is None else copy.deepcopy(latest)

    def _latest_for_logical(
        self, *, tenant_id: str | None, subject_ref: str, metric: str
    ) -> BehaviorProfile | None:
        candidates = [
            profile
            for profile in self._profiles.values()
            if profile.tenant_id == tenant_id
            and profile.subject_ref == subject_ref
            and profile.metric == metric
        ]
        if not candidates:
            return None
        return max(candidates, key=version_sort_key)


def _visible(rule_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
    if requested_tenant_id is None:
        return rule_tenant_id is None
    return rule_tenant_id is None or rule_tenant_id == requested_tenant_id


def version_sort_key(profile: BehaviorProfile) -> tuple[int, str]:
    return (profile.version, profile.computed_at.isoformat())
