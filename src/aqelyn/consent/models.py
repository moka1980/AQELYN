"""Consent and audit types (ECR-0117, Charter UX-005).

An upload is a *write*, and UX-005 requires explicit consent for anything automated. A
``ConsentRecord`` is a tenant's standing agreement to store scans under a named scope; the
``AuditEvent`` log is the append-only record of who did what, when — the "audited command path"
the prototype login honestly admitted did not exist. Both are strictly tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from aqelyn.conventions.ids import require_tenant_id, require_typed_id

# Scopes a customer can consent to. Kept closed so a typo cannot invent a new, unreviewed scope.
ConsentScope = Literal["store_scan"]

# Every action the audit log records. Closed for the same reason.
AuditAction = Literal[
    "consent_granted",
    "consent_revoked",
    "scan_ingested",
    "data_deleted",
]


def _require_tenant(value: str) -> str:
    resolved = require_tenant_id(value)
    if resolved is None:
        raise ValueError("tenant_id must not be empty")
    return resolved


class ConsentRecord(BaseModel):
    id: str
    tenant_id: str
    account_id: str
    scope: ConsentScope
    text_version: str
    granted_at: datetime
    revoked_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "con", field="id")

    @field_validator("account_id")
    @classmethod
    def _account(cls, value: str) -> str:
        return require_typed_id(value, "acc", field="account_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant(cls, value: str) -> str:
        return _require_tenant(value)


class AuditEvent(BaseModel):
    id: str
    tenant_id: str
    actor_account_id: str
    action: AuditAction
    detail: str
    at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "aud", field="id")

    @field_validator("actor_account_id")
    @classmethod
    def _actor(cls, value: str) -> str:
        return require_typed_id(value, "acc", field="actor_account_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant(cls, value: str) -> str:
        return _require_tenant(value)
