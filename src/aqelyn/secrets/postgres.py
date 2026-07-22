"""PostgreSQL CryptoStore implementation (EA-0032 W2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    CrossTenantReference,
    CryptoConfigInvalid,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.secrets.ddl import DDL
from aqelyn.secrets.models import (
    CredentialGovernanceScore,
    CryptoAssessment,
    CryptoAsset,
    CryptoAssetKind,
    CryptoQuery,
)
from aqelyn.secrets.store import (
    asset_kind,
    validate_assessment,
    validate_assessment_id,
    validate_asset,
    validate_asset_id,
    validate_fingerprint,
    validate_kind,
    validate_query,
    validate_score,
    validate_score_id,
    validate_tenant_scope,
    validate_write_tenant,
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


class PostgresCryptoStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresCryptoStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put_asset(self, asset: CryptoAsset) -> CryptoAsset:
        stored = validate_asset(asset)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        kind = asset_kind(stored)
        encoded = json.dumps(stored.model_dump(mode="json"))
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO aq_crypto_asset_identity (id, tenant_id, kind, fingerprint) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                stored.id,
                stored.tenant_id,
                kind,
                stored.fingerprint,
            )
            by_id = await conn.fetchrow(
                "SELECT tenant_id, kind, fingerprint FROM aq_crypto_asset_identity WHERE id=$1",
                stored.id,
            )
            identity_id = await conn.fetchval(
                "SELECT id FROM aq_crypto_asset_identity "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 AND kind=$2 AND fingerprint=$3",
                stored.tenant_id,
                kind,
                stored.fingerprint,
            )
            if by_id is None:
                if identity_id is not None and identity_id != stored.id:
                    raise CryptoConfigInvalid("crypto fingerprint identity cannot change asset id")
                raise StoreUnavailable("crypto identity insert was not visible")
            if by_id["tenant_id"] != stored.tenant_id:
                raise CrossTenantReference("crypto asset tenant_id cannot change")
            if by_id["kind"] != kind or by_id["fingerprint"] != stored.fingerprint:
                raise CryptoConfigInvalid("crypto asset id cannot change kind or fingerprint")
            if identity_id != stored.id:
                raise CryptoConfigInvalid("crypto fingerprint identity cannot change asset id")
            current = await conn.fetchval(
                "SELECT record FROM aq_crypto_asset_revision WHERE id=$1 "
                "ORDER BY revision DESC LIMIT 1",
                stored.id,
            )
            if current is not None and _json_value(current) == stored.model_dump(mode="json"):
                return stored.model_copy(deep=True)
            await conn.execute(
                "INSERT INTO aq_crypto_asset_revision "
                "(id, tenant_id, kind, fingerprint, record) VALUES ($1,$2,$3,$4,$5::jsonb)",
                stored.id,
                stored.tenant_id,
                kind,
                stored.fingerprint,
                encoded,
            )
        return stored.model_copy(deep=True)

    async def get_asset(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset | None:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["r.id=$1"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant, alias="r")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT r.record FROM aq_crypto_asset_revision r "
                f"WHERE {' AND '.join(clauses)} ORDER BY r.revision DESC LIMIT 1",
                *args,
            )
        return None if row is None else _row_to_asset(row["record"])

    async def get_asset_by_fingerprint(
        self,
        kind: CryptoAssetKind,
        fingerprint: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset | None:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_kind = validate_kind(kind)
        selected_fingerprint = validate_fingerprint(fingerprint)
        args: list[Any] = [selected_kind, selected_fingerprint]
        clauses = ["i.kind=$1", "i.fingerprint=$2"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant, alias="i")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT r.record FROM aq_crypto_asset_identity i "
                "JOIN LATERAL (SELECT record FROM aq_crypto_asset_revision "
                "WHERE id=i.id ORDER BY revision DESC LIMIT 1) r ON true "
                f"WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_asset(row["record"])

    async def query_assets(
        self,
        query: CryptoQuery,
    ) -> tuple[list[CryptoAsset], str | None]:
        selected = validate_query(query, mode=self.mode)
        args: list[Any] = []
        clauses: list[str] = []
        _add_tenant_clause(
            clauses,
            args,
            mode=self.mode,
            tenant_id=selected.tenant_id,
            alias="latest",
        )
        if selected.kind is not None:
            args.append(selected.kind)
            clauses.append(f"latest.kind=${len(args)}")
        if selected.cursor is not None:
            args.append(selected.cursor)
            clauses.append(f"latest.id>${len(args)}")
        args.append(selected.limit + 1)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = list(
                await conn.fetch(
                    "WITH latest AS ("
                    "SELECT DISTINCT ON (id) id, tenant_id, kind, record "
                    "FROM aq_crypto_asset_revision ORDER BY id, revision DESC"
                    ") SELECT id, record FROM latest "
                    f"{where}ORDER BY id LIMIT ${len(args)}",
                    *args,
                )
            )
        has_more = len(rows) > selected.limit
        page = rows[: selected.limit]
        next_cursor = str(page[-1]["id"]) if has_more else None
        return [_row_to_asset(row["record"]) for row in page], next_cursor

    async def put_assessment(self, assessment: CryptoAssessment) -> CryptoAssessment:
        stored = validate_assessment(assessment)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO aq_crypto_assessment (id, tenant_id, record) "
                    "VALUES ($1,$2,$3::jsonb)",
                    stored.id,
                    stored.tenant_id,
                    json.dumps(stored.model_dump(mode="json")),
                )
        except asyncpg.UniqueViolationError as exc:
            async with self._pool.acquire() as conn:
                tenant = await conn.fetchval(
                    "SELECT tenant_id FROM aq_crypto_assessment WHERE id=$1",
                    stored.id,
                )
            if tenant != stored.tenant_id:
                raise CrossTenantReference("crypto assessment tenant_id cannot change") from exc
            raise OptimisticConcurrencyConflict("crypto assessments are append-only") from exc
        return stored.model_copy(deep=True)

    async def get_assessment(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAssessment | None:
        selected_id = validate_assessment_id(assessment_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["id=$1"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT record FROM aq_crypto_assessment WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else CryptoAssessment.model_validate(_json_value(row["record"]))

    async def put_score(
        self,
        score: CredentialGovernanceScore,
    ) -> CredentialGovernanceScore:
        stored = validate_score(score)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        payload = stored.model_dump(mode="json")
        async with self._pool.acquire() as conn:
            current = await conn.fetchrow(
                "SELECT tenant_id, record FROM aq_crypto_governance_score WHERE id=$1",
                stored.id,
            )
            if current is not None:
                if current["tenant_id"] != stored.tenant_id:
                    raise CrossTenantReference(
                        "credential governance score tenant_id cannot change"
                    )
                existing = CredentialGovernanceScore.model_validate(_json_value(current["record"]))
                if existing.model_dump(mode="json") != payload:
                    raise OptimisticConcurrencyConflict(
                        "credential governance scores are append-only"
                    )
                return validate_score(existing)
            try:
                await conn.execute(
                    "INSERT INTO aq_crypto_governance_score "
                    "(id, tenant_id, asset_id, object_id, record) VALUES ($1,$2,$3,$4,$5::jsonb)",
                    stored.id,
                    stored.tenant_id,
                    stored.asset_id,
                    stored.object_id,
                    json.dumps(payload),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    "credential governance scores are append-only"
                ) from exc
        return stored.model_copy(deep=True)

    async def get_score(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> CredentialGovernanceScore | None:
        selected_id = validate_score_id(score_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["id=$1"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT record FROM aq_crypto_governance_score WHERE {' AND '.join(clauses)}",
                *args,
            )
        if row is None:
            return None
        return validate_score(CredentialGovernanceScore.model_validate(_json_value(row["record"])))


def _add_tenant_clause(
    clauses: list[str],
    args: list[Any],
    *,
    mode: str,
    tenant_id: str | None,
    alias: str | None = None,
) -> None:
    field = "tenant_id" if alias is None else f"{alias}.tenant_id"
    if mode == "local":
        clauses.append(f"{field} IS NULL")
    elif tenant_id is not None:
        args.append(tenant_id)
        clauses.append(f"{field}=${len(args)}")


def _row_to_asset(value: Any) -> CryptoAsset:
    data = _json_value(value)
    asset_id = str(data.get("id", ""))
    prefix, _ = asset_id.split("_", 1) if "_" in asset_id else ("", "")
    if prefix == "sct":
        from aqelyn.secrets.models import SecretAsset

        return SecretAsset.model_validate(data)
    if prefix == "cky":
        from aqelyn.secrets.models import CryptographicKey

        return CryptographicKey.model_validate(data)
    if prefix == "x509":
        from aqelyn.secrets.models import CertificateAsset

        return CertificateAsset.model_validate(data)
    raise CryptoConfigInvalid("stored crypto asset has an invalid id")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value
