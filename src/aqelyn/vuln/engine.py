"""Vulnerability Intelligence reference engine (EA-0024 V2)."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import CrossTenantReference, VulnNotFound
from aqelyn.vuln.models import Disposition, DispositionKind, VulnerabilityRecord
from aqelyn.vuln.store import VulnerabilityStore


class VulnerabilityIntelligenceEngine:
    def __init__(self, store: VulnerabilityStore) -> None:
        self.store = store

    async def ingest(
        self,
        *,
        records: Sequence[VulnerabilityRecord],
        tenant_id: str | None,
    ) -> list[VulnerabilityRecord]:
        stored: list[VulnerabilityRecord] = []
        for record in records:
            candidate = _with_tenant(record, tenant_id=tenant_id)
            existing = await self._matching_record(candidate, tenant_id=tenant_id)
            if existing is not None:
                candidate = candidate.model_copy(
                    update={
                        "id": existing.id,
                        "disposition": _reasserted_disposition(existing),
                        "status": "reasserted"
                        if existing.disposition is not None
                        else candidate.status,
                    },
                    deep=True,
                )
            stored.append(await self.store.put(candidate))
        return stored

    async def disposition(
        self,
        vulnerability_id: str,
        *,
        kind: DispositionKind,
        by: ActorRef,
        reason: str,
        tenant_id: str | None,
    ) -> VulnerabilityRecord:
        current = await self.store.get(vulnerability_id, tenant_id=tenant_id)
        if current is None:
            raise VulnNotFound(vulnerability_id)
        updated = current.model_copy(
            update={
                "disposition": Disposition(
                    actor=by,
                    kind=kind,
                    reason=reason,
                    at=utc_now(),
                    reasserted_by_scanner=False,
                )
            },
            deep=True,
        )
        return await self.store.put(updated)

    async def _matching_record(
        self,
        candidate: VulnerabilityRecord,
        *,
        tenant_id: str | None,
    ) -> VulnerabilityRecord | None:
        for record in await self.store.query(tenant_id=tenant_id, cve_id=candidate.cve_id):
            if (
                record.scanner == candidate.scanner
                and record.asset_ref.kind == candidate.asset_ref.kind
                and record.asset_ref.ref_id == candidate.asset_ref.ref_id
            ):
                return record
        return None


def _with_tenant(record: VulnerabilityRecord, *, tenant_id: str | None) -> VulnerabilityRecord:
    if tenant_id is None:
        return record
    if record.tenant_id is not None and record.tenant_id != tenant_id:
        raise CrossTenantReference("ingested vulnerability tenant_id does not match request")
    return record.model_copy(update={"tenant_id": tenant_id}, deep=True)


def _reasserted_disposition(record: VulnerabilityRecord) -> Disposition | None:
    if record.disposition is None:
        return None
    return record.disposition.model_copy(update={"reasserted_by_scanner": True}, deep=True)
