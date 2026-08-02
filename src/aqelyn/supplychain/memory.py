"""In-memory SBOMStore implementation (EA-0030 Q2)."""

from __future__ import annotations

import copy

from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    SupplyChainConfigInvalid,
)
from aqelyn.supplychain.models import (
    ComponentIdentity,
    ProvenanceStatus,
    QuarantinedSBOM,
    SoftwareComponent,
    SupplyChainAssessment,
)
from aqelyn.supplychain.store import (
    validate_assessment,
    validate_assessment_id,
    validate_component,
    validate_component_identity,
    validate_component_object_id,
    validate_component_read_cursor,
    validate_doc_id,
    validate_provenance_filter,
    validate_quarantine,
    validate_query_cursor,
    validate_query_limit,
    validate_tenant_scope,
    validate_write_tenant,
)


class InMemorySBOMStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._components: dict[tuple[str | None, str, str], SoftwareComponent] = {}
        self._component_ids: dict[str, tuple[str | None, str, str]] = {}
        self._assessments: dict[str, SupplyChainAssessment] = {}
        self._quarantine: dict[str, QuarantinedSBOM] = {}

    async def put_component(self, component: SoftwareComponent) -> SoftwareComponent:
        stored = validate_component(component)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        key = (stored.tenant_id, stored.identity.kind, stored.identity.value)
        id_key = self._component_ids.get(stored.object_id)
        if id_key is not None and id_key != key:
            if id_key[0] != stored.tenant_id:
                raise CrossTenantReference("software component tenant_id cannot change")
            raise SupplyChainConfigInvalid(
                "software component object_id cannot change identity kind or value"
            )
        existing = self._components.get(key)
        if existing is not None:
            stored = stored.model_copy(
                update={
                    "object_id": existing.object_id,
                    "locations": sorted({*existing.locations, *stored.locations}),
                },
                deep=True,
            )
        self._components[key] = stored.model_copy(deep=True)
        self._component_ids[stored.object_id] = key
        return stored.model_copy(deep=True)

    async def get_component(
        self,
        identity: ComponentIdentity | str,
        *,
        tenant_id: str | None,
    ) -> SoftwareComponent | None:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_identity = validate_component_identity(identity)
        record = self._components.get(
            (selected_tenant, selected_identity.kind, selected_identity.value)
        )
        return None if record is None else record.model_copy(deep=True)

    async def get_component_by_object_id(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> SoftwareComponent | None:
        selected_id = validate_component_object_id(object_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        key = self._component_ids.get(selected_id)
        if key is None or key[0] != selected_tenant:
            return None
        return self._components[key].model_copy(deep=True)

    async def put_assessment(self, assessment: SupplyChainAssessment) -> SupplyChainAssessment:
        stored = validate_assessment(assessment)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        existing = self._assessments.get(stored.id)
        if existing is not None:
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("supply-chain assessment tenant_id cannot change")
            raise OptimisticConcurrencyConflict("supply-chain assessments are append-only")
        self._assessments[stored.id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def get_assessment(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
    ) -> SupplyChainAssessment | None:
        selected_id = validate_assessment_id(assessment_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        record = self._assessments.get(selected_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return record.model_copy(deep=True)

    async def query(
        self,
        *,
        tenant_id: str | None,
        provenance: ProvenanceStatus | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[SoftwareComponent], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provenance = validate_provenance_filter(provenance)
        selected_limit = validate_query_limit(limit)
        selected_cursor = validate_query_cursor(cursor)
        rows = sorted(
            (
                record
                for record in self._components.values()
                if self._visible(record.tenant_id, selected_tenant)
                and (selected_provenance is None or record.provenance_status == selected_provenance)
                and (selected_cursor is None or record.object_id > selected_cursor)
            ),
            key=lambda record: record.object_id,
        )
        page = rows[:selected_limit]
        next_cursor = page[-1].object_id if len(rows) > selected_limit else None
        return [record.model_copy(deep=True) for record in page], next_cursor

    async def query_components_for_read(
        self,
        *,
        tenant_id: str | None,
        after: tuple[ProvenanceStatus, str] | None = None,
        limit: int = 100,
    ) -> tuple[list[SoftwareComponent], tuple[ProvenanceStatus, str] | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_after = validate_component_read_cursor(after)
        selected_limit = validate_query_limit(limit)
        rows = sorted(
            (
                record
                for record in self._components.values()
                if self._visible(record.tenant_id, selected_tenant)
                and (
                    selected_after is None
                    or (record.provenance_status, record.object_id) > selected_after
                )
            ),
            key=lambda record: (record.provenance_status, record.object_id),
        )
        page = rows[:selected_limit]
        next_key = (
            (page[-1].provenance_status, page[-1].object_id) if len(rows) > selected_limit else None
        )
        return [record.model_copy(deep=True) for record in page], next_key

    async def quarantine(self, item: QuarantinedSBOM) -> QuarantinedSBOM:
        stored = validate_quarantine(item)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        existing = self._quarantine.get(stored.doc_id)
        if existing is not None and existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("quarantined SBOM tenant_id cannot change")
        self._quarantine[stored.doc_id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def get_quarantine(
        self,
        doc_id: str,
        *,
        tenant_id: str | None,
    ) -> QuarantinedSBOM | None:
        selected_id = validate_doc_id(doc_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        record = self._quarantine.get(selected_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return copy.deepcopy(record)

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local":
            return row_tenant_id is None and requested_tenant_id is None
        return row_tenant_id == requested_tenant_id
