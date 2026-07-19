"""PostgreSQL SBOMStore implementation (EA-0030 Q2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
    SupplyChainConfigInvalid,
)
from aqelyn.supplychain.ddl import DDL
from aqelyn.supplychain.models import (
    ProvenanceStatus,
    QuarantinedSBOM,
    SoftwareComponent,
    SupplyChainAssessment,
)
from aqelyn.supplychain.store import (
    validate_assessment,
    validate_assessment_id,
    validate_component,
    validate_doc_id,
    validate_provenance_filter,
    validate_purl,
    validate_quarantine,
    validate_query_cursor,
    validate_query_limit,
    validate_tenant_scope,
    validate_write_tenant,
)

_COMPONENT_COLUMNS = (
    "object_id, tenant_id, purl, name, version, component_type, licenses, supplier, "
    "hashes, provenance_status, direct, source_id, observed_at, evidence_id, conflicts"
)
_ASSESSMENT_COLUMNS = (
    "id, tenant_id, run_at, subject_ref, components, direct, transitive, "
    "unverified_provenance, vulnerable_components, assessment_status, evidence_id"
)
_QUARANTINE_COLUMNS = (
    "doc_id, tenant_id, source_id, observed_at, evidence_id, raw, reason, flagged, quarantined_at"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect(url: str) -> asyncpg.Pool:
    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresSBOMStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresSBOMStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put_component(self, component: SoftwareComponent) -> SoftwareComponent:
        stored = validate_component(component)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        async with self._pool.acquire() as conn, conn.transaction():
            by_id = await conn.fetchrow(
                "SELECT tenant_id, purl FROM aq_supplychain_component "
                "WHERE object_id=$1 FOR UPDATE",
                stored.object_id,
            )
            if by_id is not None:
                if by_id["tenant_id"] != stored.tenant_id:
                    raise CrossTenantReference("software component tenant_id cannot change")
                if by_id["purl"] != stored.purl:
                    raise SupplyChainConfigInvalid(
                        "software component object_id cannot change purl"
                    )
            by_purl = await conn.fetchrow(
                f"SELECT {_COMPONENT_COLUMNS} FROM aq_supplychain_component "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 AND purl=$2 FOR UPDATE",
                stored.tenant_id,
                stored.purl,
            )
            if by_purl is not None:
                stored = stored.model_copy(
                    update={"object_id": str(by_purl["object_id"])}, deep=True
                )
                await conn.execute(
                    "UPDATE aq_supplychain_component SET "
                    "purl=$3, name=$4, version=$5, component_type=$6, licenses=$7, supplier=$8, "
                    "hashes=$9, provenance_status=$10, direct=$11, source_id=$12, "
                    "observed_at=$13, evidence_id=$14, conflicts=$15 "
                    "WHERE object_id=$1 AND tenant_id IS NOT DISTINCT FROM $2",
                    *_component_args(stored),
                )
            else:
                await conn.execute(
                    f"INSERT INTO aq_supplychain_component ({_COMPONENT_COLUMNS}) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
                    *_component_args(stored),
                )
        return stored.model_copy(deep=True)

    async def get_component(
        self,
        purl: str,
        *,
        tenant_id: str | None,
    ) -> SoftwareComponent | None:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [validate_purl(purl)]
        clauses = ["purl=$1"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COMPONENT_COLUMNS} FROM aq_supplychain_component "
                f"WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_component(row)

    async def put_assessment(self, assessment: SupplyChainAssessment) -> SupplyChainAssessment:
        stored = validate_assessment(assessment)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"INSERT INTO aq_supplychain_assessment ({_ASSESSMENT_COLUMNS}) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    *_assessment_args(stored),
                )
        except asyncpg.UniqueViolationError as exc:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT tenant_id FROM aq_supplychain_assessment WHERE id=$1",
                    stored.id,
                )
            if row is not None and row["tenant_id"] != stored.tenant_id:
                raise CrossTenantReference(
                    "supply-chain assessment tenant_id cannot change"
                ) from exc
            raise OptimisticConcurrencyConflict("supply-chain assessments are append-only") from exc
        return stored.model_copy(deep=True)

    async def get_assessment(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
    ) -> SupplyChainAssessment | None:
        selected_id = validate_assessment_id(assessment_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["id=$1"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_ASSESSMENT_COLUMNS} FROM aq_supplychain_assessment "
                f"WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else SupplyChainAssessment.model_validate(dict(row))

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
        args: list[Any] = []
        clauses: list[str] = []
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        if selected_provenance is not None:
            args.append(selected_provenance)
            clauses.append(f"provenance_status=${len(args)}")
        if selected_cursor is not None:
            args.append(selected_cursor)
            clauses.append(f"object_id>${len(args)}")
        args.append(selected_limit + 1)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = list(
                await conn.fetch(
                    f"SELECT {_COMPONENT_COLUMNS} FROM aq_supplychain_component "
                    f"{where}ORDER BY object_id LIMIT ${len(args)}",
                    *args,
                )
            )
        has_more = len(rows) > selected_limit
        page = rows[:selected_limit]
        next_cursor = str(page[-1]["object_id"]) if has_more else None
        return [_row_to_component(row) for row in page], next_cursor

    async def quarantine(self, item: QuarantinedSBOM) -> QuarantinedSBOM:
        stored = validate_quarantine(item)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT tenant_id FROM aq_supplychain_quarantine WHERE doc_id=$1 FOR UPDATE",
                stored.doc_id,
            )
            if row is not None and row["tenant_id"] != stored.tenant_id:
                raise CrossTenantReference("quarantined SBOM tenant_id cannot change")
            await conn.execute(
                f"INSERT INTO aq_supplychain_quarantine ({_QUARANTINE_COLUMNS}) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
                "ON CONFLICT (doc_id) DO UPDATE SET "
                "source_id=EXCLUDED.source_id, observed_at=EXCLUDED.observed_at, "
                "evidence_id=EXCLUDED.evidence_id, raw=EXCLUDED.raw, reason=EXCLUDED.reason, "
                "flagged=EXCLUDED.flagged, quarantined_at=EXCLUDED.quarantined_at",
                *_quarantine_args(stored),
            )
        return stored.model_copy(deep=True)

    async def get_quarantine(
        self,
        doc_id: str,
        *,
        tenant_id: str | None,
    ) -> QuarantinedSBOM | None:
        selected_id = validate_doc_id(doc_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["doc_id=$1"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_QUARANTINE_COLUMNS} FROM aq_supplychain_quarantine "
                f"WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_quarantine(row)


def _add_tenant_clause(
    clauses: list[str],
    args: list[Any],
    *,
    mode: str,
    tenant_id: str | None,
) -> None:
    if mode == "local":
        clauses.append("tenant_id IS NULL")
    elif tenant_id is not None:
        args.append(tenant_id)
        clauses.append(f"tenant_id=${len(args)}")


def _component_args(component: SoftwareComponent) -> tuple[Any, ...]:
    return (
        component.object_id,
        component.tenant_id,
        component.purl,
        component.name,
        component.version,
        component.component_type,
        json.dumps(component.licenses),
        component.supplier,
        json.dumps(component.hashes),
        component.provenance_status,
        component.direct,
        component.source_id,
        component.observed_at,
        component.evidence_id,
        json.dumps([conflict.model_dump(mode="json") for conflict in component.conflicts]),
    )


def _assessment_args(assessment: SupplyChainAssessment) -> tuple[Any, ...]:
    return (
        assessment.id,
        assessment.tenant_id,
        assessment.run_at,
        assessment.subject_ref,
        assessment.components,
        assessment.direct,
        assessment.transitive,
        assessment.unverified_provenance,
        assessment.vulnerable_components,
        assessment.assessment_status,
        assessment.evidence_id,
    )


def _quarantine_args(item: QuarantinedSBOM) -> tuple[Any, ...]:
    return (
        item.doc_id,
        item.tenant_id,
        item.source_id,
        item.observed_at,
        item.evidence_id,
        json.dumps(item.raw),
        item.reason,
        item.flagged,
        item.quarantined_at,
    )


def _row_to_component(row: asyncpg.Record) -> SoftwareComponent:
    data: dict[str, Any] = dict(row)
    for field in ("licenses", "hashes", "conflicts"):
        data[field] = _json_value(data[field])
    return SoftwareComponent.model_validate(data)


def _row_to_quarantine(row: asyncpg.Record) -> QuarantinedSBOM:
    data: dict[str, Any] = dict(row)
    data["raw"] = _json_value(data["raw"])
    return QuarantinedSBOM.model_validate(data)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value
