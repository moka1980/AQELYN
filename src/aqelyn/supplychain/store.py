"""Supply-chain persistence contract and validation helpers (EA-0030 Q2)."""

from __future__ import annotations

from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SupplyChainConfigInvalid, TenantScopeRequired
from aqelyn.supplychain.models import (
    VALID_PROVENANCE_STATUSES,
    ProvenanceStatus,
    QuarantinedSBOM,
    SoftwareComponent,
    SupplyChainAssessment,
)


class SBOMStore(Protocol):
    async def put_component(self, component: SoftwareComponent) -> SoftwareComponent: ...

    async def get_component(
        self,
        purl: str,
        *,
        tenant_id: str | None,
    ) -> SoftwareComponent | None: ...

    async def put_assessment(self, assessment: SupplyChainAssessment) -> SupplyChainAssessment: ...

    async def get_assessment(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
    ) -> SupplyChainAssessment | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        provenance: ProvenanceStatus | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[SoftwareComponent], str | None]: ...

    async def quarantine(self, item: QuarantinedSBOM) -> QuarantinedSBOM: ...

    async def get_quarantine(
        self,
        doc_id: str,
        *,
        tenant_id: str | None,
    ) -> QuarantinedSBOM | None: ...


def validate_component(component: SoftwareComponent) -> SoftwareComponent:
    stored = SoftwareComponent.model_validate(component.model_dump(mode="json"))
    require_typed_id(stored.object_id, "obj", field="object_id")
    return stored


def validate_assessment(assessment: SupplyChainAssessment) -> SupplyChainAssessment:
    stored = SupplyChainAssessment.model_validate(assessment.model_dump(mode="json"))
    require_typed_id(stored.id, "sca", field="assessment_id")
    return stored


def validate_quarantine(item: QuarantinedSBOM) -> QuarantinedSBOM:
    return QuarantinedSBOM.model_validate(item.model_dump(mode="json"))


def validate_tenant_scope(value: str | None, *, mode: str) -> str | None:
    tenant_id = require_tenant_id(value)
    if mode == "enterprise" and tenant_id is None:
        raise TenantScopeRequired("SBOM store read must be tenant-scoped")
    return tenant_id


def validate_write_tenant(value: str | None, *, mode: str) -> str | None:
    tenant_id = validate_tenant_scope(value, mode=mode)
    if mode == "local" and tenant_id is not None:
        raise SupplyChainConfigInvalid("local SBOM store writes require tenant_id=null")
    return tenant_id


def validate_purl(value: str) -> str:
    if not value.strip() or not value.startswith("pkg:"):
        raise SupplyChainConfigInvalid("purl must be a package URL")
    return value


def validate_provenance_filter(value: str | None) -> ProvenanceStatus | None:
    if value is None:
        return None
    if value not in VALID_PROVENANCE_STATUSES:
        raise SupplyChainConfigInvalid(f"unknown provenance filter: {value!r}")
    return cast(ProvenanceStatus, value)


def validate_query_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 10_000:
        raise SupplyChainConfigInvalid("limit must be in [1,10000]")
    return value


def validate_query_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return require_typed_id(value, "obj", field="cursor")


def validate_assessment_id(value: str) -> str:
    return require_typed_id(value, "sca", field="assessment_id")


def validate_doc_id(value: str) -> str:
    return require_typed_id(value, "sbm", field="doc_id")
