"""CertificationStore protocol and validation helpers (EA-0011 I3)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from aqelyn.conventions import require_typed_id
from aqelyn.conventions.errors import SchemaValidationError
from aqelyn.iag.models import Certification, CertificationStatus

VALID_CERTIFICATION_STATUSES: frozenset[str] = frozenset(
    ("open", "in_progress", "completed", "expired")
)


class CertificationStore(Protocol):
    async def put(
        self,
        cert: Certification,
        *,
        expected_version: int | None = None,
    ) -> Certification: ...

    async def get(self, cert_id: str) -> Certification | None: ...

    async def list(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
    ) -> list[Certification]: ...


def validate_certification_id(
    value: str, *, field: str = "certification_id", allow_empty: bool = False
) -> str:
    return require_typed_id(value, "cert", field=field, allow_empty=allow_empty)


def validate_review_item_id(
    value: str, *, field: str = "review_item_id", allow_empty: bool = False
) -> str:
    return require_typed_id(value, "rvi", field=field, allow_empty=allow_empty)


def validate_certification(cert: Certification) -> Certification:
    return Certification.model_validate(cert.model_dump(mode="json"))


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise SchemaValidationError(f"{field} must be >= 1")
    return value


def normalize_status_filter(status: Sequence[str] | None) -> tuple[CertificationStatus, ...] | None:
    if status is None:
        return None
    normalized: list[CertificationStatus] = []
    for value in status:
        if value not in VALID_CERTIFICATION_STATUSES:
            raise SchemaValidationError(f"unknown certification status: {value!r}")
        normalized.append(value)  # type: ignore[arg-type]
    return tuple(normalized)
