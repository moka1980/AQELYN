"""PostgreSQL EvidenceStore (EA-0004 §9). Append-only hash-chained ledger."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions import ActorRef, new_id, sha256_hex, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    EvidenceNotFound,
    StoreUnavailable,
)
from aqelyn.events import Event, EventBus, Subject
from aqelyn.evidence.ddl import DDL
from aqelyn.evidence.models import EvidencePackage, EvidenceRecord, VerifyResult
from aqelyn.evidence.store import (
    compute_record_hash,
    validate_chain_tenant,
    validate_evidence_id,
    validate_evidence_ids,
    validate_package_id,
)

_COLS = (
    "id, tenant_id, evidence_type, schema_version, subject, collected_at, recorded_at, "
    "collector, source_id, method, content, content_ref, content_hash, confidence, labels, "
    "seq, prev_hash, record_hash, signature, anchor"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _row(r: asyncpg.Record) -> EvidenceRecord:
    d = dict(r)
    for jk in ("subject", "collector", "content", "content_ref", "labels", "signature", "anchor"):
        if isinstance(d[jk], str):
            d[jk] = json.loads(d[jk])
    return EvidenceRecord.model_validate(d)


class PostgresEvidenceStore:
    def __init__(
        self, pool: asyncpg.Pool, *, mode: str = "local", event_bus: EventBus | None = None
    ) -> None:
        self._pool = pool
        self.mode = mode
        self._bus = event_bus

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresEvidenceStore:
        try:
            pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(DDL)
        return cls(pool, **kw)

    async def close(self) -> None:
        await self._pool.close()

    def _content_hash(self, rec: EvidenceRecord) -> str:
        return sha256_hex(rec.content if rec.content is not None else rec.content_ref)

    async def add(self, record: EvidenceRecord) -> EvidenceRecord:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", record.tenant_id or "")
            tail = await conn.fetchrow(
                "SELECT seq, record_hash FROM aq_evidence "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 ORDER BY seq DESC LIMIT 1",
                record.tenant_id,
            )
            seq = (tail["seq"] + 1) if tail else 1
            prev_hash = tail["record_hash"] if tail else None
            content_hash = self._content_hash(record)
            base = record.model_copy(
                update={
                    "id": record.id or new_id("evd"),
                    "seq": seq,
                    "prev_hash": prev_hash,
                    "content_hash": content_hash,
                    "recorded_at": utc_now(),
                    "record_hash": "",
                }
            )
            rec = base.model_copy(
                update={"record_hash": compute_record_hash(base.model_dump(mode="json"), prev_hash)}
            )
            await conn.execute(
                f"INSERT INTO aq_evidence ({_COLS}) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)",
                rec.id,
                rec.tenant_id,
                rec.evidence_type,
                rec.schema_version,
                rec.subject.model_dump_json(),
                rec.collected_at,
                rec.recorded_at,
                json.dumps(rec.collector.model_dump()),
                rec.source_id,
                rec.method,
                json.dumps(rec.content) if rec.content is not None else None,
                rec.content_ref.model_dump_json() if rec.content_ref else None,
                rec.content_hash,
                rec.confidence,
                json.dumps(rec.labels),
                rec.seq,
                rec.prev_hash,
                rec.record_hash,
                json.dumps(rec.signature) if rec.signature else None,
                json.dumps(rec.anchor) if rec.anchor else None,
            )
            await conn.execute(
                "INSERT INTO aq_evidence_custody (evidence_id, action, actor, at) "
                "VALUES ($1,$2,$3,$4)",
                rec.id,
                "intake",
                json.dumps(rec.collector.model_dump()),
                rec.recorded_at,
            )
        if self._bus is not None:
            await self._bus.publish(
                Event(
                    id=new_id("evt"),
                    event_type="aqelyn.evidence.recorded",
                    schema_version=1,
                    tenant_id=rec.tenant_id,
                    occurred_at=rec.collected_at,
                    recorded_at=utc_now(),
                    producer=rec.collector,
                    subject=Subject(object_ids=rec.subject.object_ids, evidence_id=rec.id),
                    payload={"evidence_type": rec.evidence_type, "source_id": rec.source_id},
                    partition_key=rec.subject.object_ids[0] if rec.subject.object_ids else rec.id,
                )
            )
        return rec

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        validate_evidence_id(evidence_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {_COLS} FROM aq_evidence WHERE id=$1", evidence_id)
            if row is None:
                raise EvidenceNotFound(evidence_id)
            await conn.execute(
                "INSERT INTO aq_evidence_custody (evidence_id, action, actor) VALUES ($1,$2,$3)",
                evidence_id,
                "read",
                json.dumps(actor.model_dump()),
            )
        return _row(row)

    async def custody_count(self, evidence_id: str) -> int:
        validate_evidence_id(evidence_id)
        return len(await self.custody_of(evidence_id))

    async def custody_of(self, evidence_id: str) -> list[dict[str, Any]]:
        validate_evidence_id(evidence_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT seq, evidence_id, action, actor, at, context "
                "FROM aq_evidence_custody WHERE evidence_id=$1 ORDER BY seq",
                evidence_id,
            )
        out: list[dict[str, Any]] = []
        for row in rows:
            actor = row["actor"]
            context = row["context"]
            out.append(
                {
                    "seq": int(row["seq"]),
                    "evidence_id": row["evidence_id"],
                    "action": row["action"],
                    "actor": json.loads(actor) if isinstance(actor, str) else actor,
                    "at": row["at"].isoformat(),
                    "context": json.loads(context) if isinstance(context, str) else context,
                }
            )
        return out

    async def verify(self, evidence_id: str) -> VerifyResult:
        validate_evidence_id(evidence_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {_COLS} FROM aq_evidence WHERE id=$1", evidence_id)
        if row is None:
            raise EvidenceNotFound(evidence_id)
        rec = _row(row)
        if self._content_hash(rec) != rec.content_hash:
            return VerifyResult(ok=False, broken_at_seq=rec.seq, detail="content hash mismatch")
        expected = compute_record_hash(
            rec.model_copy(update={"record_hash": ""}).model_dump(mode="json"), rec.prev_hash
        )
        if expected != rec.record_hash:
            return VerifyResult(ok=False, broken_at_seq=rec.seq, detail="record hash mismatch")
        return VerifyResult(ok=True)

    async def verify_chain(
        self, *, tenant_id: str | None, from_seq: int = 0, to_seq: int | None = None
    ) -> VerifyResult:
        validate_chain_tenant(tenant_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_COLS} FROM aq_evidence WHERE tenant_id IS NOT DISTINCT FROM $1 "
                "ORDER BY seq",
                tenant_id,
            )
        prev: str | None = None
        for r in rows:
            rec = _row(r)
            if rec.seq <= from_seq:
                prev = rec.record_hash
                continue
            if to_seq is not None and rec.seq > to_seq:
                break
            if rec.prev_hash != prev:
                return VerifyResult(ok=False, broken_at_seq=rec.seq, detail="prev_hash mismatch")
            res = await self.verify(rec.id)
            if not res.ok:
                return res
            prev = rec.record_hash
        return VerifyResult(ok=True)

    async def package(
        self, evidence_ids: list[str], *, by: ActorRef, reason: str
    ) -> EvidencePackage:
        validate_evidence_ids(evidence_ids)
        async with self._pool.acquire() as conn, conn.transaction():
            tenant: str | None = None
            hashes: list[str] = []
            for i, eid in enumerate(evidence_ids):
                row = await conn.fetchrow(
                    "SELECT tenant_id, record_hash FROM aq_evidence WHERE id=$1", eid
                )
                if row is None:
                    raise EvidenceNotFound(eid)
                if i and row["tenant_id"] != tenant:
                    raise CrossTenantReference("package spans tenants")
                tenant = row["tenant_id"]
                hashes.append(row["record_hash"])
            manifest_hash = sha256_hex({"evidence": sorted(hashes), "reason": reason})
            now = utc_now()
            pkg = EvidencePackage(
                id=new_id("pkg"),
                tenant_id=tenant,
                evidence_ids=list(evidence_ids),
                manifest_hash=manifest_hash,
                package_hash=sha256_hex(
                    {"m": manifest_hash, "by": by.model_dump(), "at": now.isoformat()}
                ),
                created_by=by,
                created_at=now,
                reason=reason,
            )
            await conn.execute(
                "INSERT INTO aq_evidence_package (id, tenant_id, evidence_ids, manifest_hash, "
                "package_hash, created_by, created_at, reason) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8)",
                pkg.id,
                pkg.tenant_id,
                json.dumps(pkg.evidence_ids),
                pkg.manifest_hash,
                pkg.package_hash,
                json.dumps(by.model_dump()),
                pkg.created_at,
                reason,
            )
            for eid in evidence_ids:
                await conn.execute(
                    "INSERT INTO aq_evidence_custody (evidence_id, action, actor) "
                    "VALUES ($1,'package',$2)",
                    eid,
                    json.dumps(by.model_dump()),
                )
        return pkg

    async def verify_package(self, package_id: str) -> VerifyResult:
        validate_package_id(package_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT evidence_ids, manifest_hash, reason FROM aq_evidence_package WHERE id=$1",
                package_id,
            )
        if row is None:
            raise EvidenceNotFound(package_id)
        ids = row["evidence_ids"]
        if isinstance(ids, str):
            ids = json.loads(ids)
        hashes: list[str] = []
        for eid in ids:
            res = await self.verify(eid)
            if not res.ok:
                return res
            async with self._pool.acquire() as conn:
                rh = await conn.fetchval("SELECT record_hash FROM aq_evidence WHERE id=$1", eid)
            hashes.append(rh)
        manifest_hash = sha256_hex({"evidence": sorted(hashes), "reason": row["reason"]})
        if manifest_hash != row["manifest_hash"]:
            return VerifyResult(ok=False, detail="manifest hash mismatch")
        return VerifyResult(ok=True)
