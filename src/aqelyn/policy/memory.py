"""In-memory PolicyStore implementation (EA-0009 P3)."""

from __future__ import annotations

import copy

from aqelyn.policy.models import Policy
from aqelyn.policy.store import validate_policy, validate_policy_id, validate_policy_tenant


class InMemoryPolicyStore:
    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}

    async def put(self, policy: Policy) -> Policy:
        stored = validate_policy(policy)
        self._policies[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, policy_id: str) -> Policy | None:
        validate_policy_id(policy_id)
        policy = self._policies.get(policy_id)
        if policy is None:
            return None
        return copy.deepcopy(policy)

    async def list(self, *, tenant_id: str | None = None) -> list[Policy]:
        tenant_id = validate_policy_tenant(tenant_id)
        rows = [
            copy.deepcopy(policy)
            for policy in self._policies.values()
            if _visible(policy, tenant_id)
        ]
        rows.sort(key=_policy_sort_key)
        return rows


def _visible(policy: Policy, tenant_id: str | None) -> bool:
    if tenant_id is None:
        return policy.tenant_id is None
    return policy.tenant_id is None or policy.tenant_id == tenant_id


def _policy_sort_key(policy: Policy) -> tuple[bool, str, str]:
    return (policy.tenant_id is not None, policy.tenant_id or "", policy.id)
