"""In-memory CertificationStore implementation (EA-0011 I3)."""

from __future__ import annotations

import copy
from collections.abc import Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import (
    CertificationNotFound,
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    TenantScopeRequired,
)
from aqelyn.iag.models import Certification, CertificationStatus
from aqelyn.iag.store import (
    normalize_status_filter,
    validate_certification,
    validate_certification_id,
    validate_positive,
)


class InMemoryCertificationStore:
    def __init__(self, *, mode: str = "local") -> None:
        self._certs: dict[str, Certification] = {}
        self.mode = mode

    def _visible(self, cert: Certification, tenant_id: str | None) -> bool:
        if self.mode == "local" and cert.tenant_id is not None:
            return False
        return tenant_id is None or cert.tenant_id == tenant_id

    async def put(
        self,
        cert: Certification,
        *,
        expected_version: int | None = None,
    ) -> Certification:
        incoming = _materialize_ids(cert)
        stored = validate_certification(incoming)
        existing = self._certs.get(stored.id)
        if existing is None:
            if expected_version is not None:
                raise CertificationNotFound(stored.id)
            created = stored.model_copy(update={"version": 1}, deep=True)
            self._certs[created.id] = created
            return copy.deepcopy(created)

        expected = expected_version if expected_version is not None else stored.version
        validate_positive(expected, field="expected_version")
        if existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("certification tenant_id cannot change")
        if existing.version != expected:
            raise OptimisticConcurrencyConflict(f"expected v{expected}, found v{existing.version}")

        updated = stored.model_copy(
            update={
                "version": existing.version + 1,
                "created_by": existing.created_by,
                "created_at": existing.created_at,
            },
            deep=True,
        )
        self._certs[updated.id] = updated
        return copy.deepcopy(updated)

    async def get(self, cert_id: str) -> Certification | None:
        validate_certification_id(cert_id)
        cert = self._certs.get(cert_id)
        if cert is None:
            return None
        return copy.deepcopy(cert)

    async def list(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
    ) -> list[Certification]:
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("certification list must be tenant-scoped in enterprise mode")
        statuses = normalize_status_filter(status)
        rows = [
            copy.deepcopy(cert)
            for cert in self._certs.values()
            if self._visible(cert, tenant_id) and _status_visible(cert.status, statuses)
        ]
        rows.sort(key=lambda cert: cert.id)
        return rows


def _materialize_ids(cert: Certification) -> Certification:
    items = [
        item if item.id else item.model_copy(update={"id": new_id("rvi")}) for item in cert.items
    ]
    return cert.model_copy(
        update={
            "id": cert.id or new_id("cert"),
            "items": items,
        },
        deep=True,
    )


def _status_visible(
    value: CertificationStatus, statuses: tuple[CertificationStatus, ...] | None
) -> bool:
    return statuses is None or value in statuses
