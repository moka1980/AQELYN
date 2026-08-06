"""Identity types. Pydantic, following the AQObject/Finding pattern in this codebase."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from aqelyn.conventions.ids import require_tenant_id, require_typed_id

AccountStatus = Literal["active", "disabled"]


class PasswordHash(BaseModel):
    salt: str
    hash: str
    n: int
    r: int
    p: int


class Account(BaseModel):
    id: str
    email: str
    tenant_id: str
    password: PasswordHash
    status: AccountStatus = "active"
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "acc", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant(cls, value: str) -> str:
        # Enterprise-mode tenancy: every account belongs to exactly one, non-empty tenant.
        resolved = require_tenant_id(value)
        if resolved is None:
            raise ValueError("account tenant_id must not be empty")
        return resolved


class Invite(BaseModel):
    id: str
    token: str
    tenant_id: str
    email: str | None = None
    created_at: datetime
    expires_at: datetime
    redeemed_by: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "inv", field="id")

    @field_validator("redeemed_by")
    @classmethod
    def _redeemed(cls, value: str | None) -> str | None:
        return None if value is None else require_typed_id(value, "acc", field="redeemed_by")
