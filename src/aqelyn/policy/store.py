"""PolicyStore protocol and validation helpers (EA-0009 P3)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import require_tenant_id
from aqelyn.conventions.errors import PolicyConfigInvalid
from aqelyn.policy.models import Policy


class PolicyStore(Protocol):
    async def put(self, policy: Policy) -> Policy: ...

    async def get(self, policy_id: str) -> Policy | None: ...

    async def list(self, *, tenant_id: str | None = None) -> list[Policy]: ...


def validate_policy_id(value: str, *, field: str = "policy_id") -> str:
    if not value.strip():
        raise PolicyConfigInvalid(f"{field} must not be empty")
    return value


def validate_policy(policy: Policy) -> Policy:
    return Policy.model_validate(policy.model_dump(mode="json"))


def validate_policy_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)
