"""PostgreSQL FindingStore (Finding model section 10)."""

from __future__ import annotations

import json
from typing import Any, cast

import asyncpg

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    EvidenceRequired,
    FindingNotFound,
    InvalidFindingTransition,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.events import Event, EventBus, Subject
from aqelyn.findings.ddl import DDL
from aqelyn.findings.models import TRANSITIONS, AuditEntry, Finding, FindingQuery
from aqelyn.findings.store import (
    EvidenceExists,
    validate_evidence_refs,
    validate_finding,
    validate_finding_id,
)

_FINDING_COLS = (
    "id, tenant_id, finding_type, schema_version, dedup_key, title, severity, severity_score, "
    "status, what_happened, why_it_matters, how_determined, risk_of_inaction, expert_details, "
    "remediation, automation, confidence, source_engine, correlation_id, first_detected_at, "
    "last_detected_at, resolved_at, version"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _base_row(r: asyncpg.Record) -> Finding:
    d: dict[str, Any] = dict(r)
    for key in ("expert_details", "remediation", "automation"):
        if d[key] is not None:
            d[key] = _json_value(d[key])
    d["evidence_ids"] = []
    d["affected_object_ids"] = []
    d["audit"] = []
    return Finding.model_validate(d)


def _audit_row(r: asyncpg.Record) -> AuditEntry:
    return AuditEntry.model_validate(
        {
            "at": r["at"],
            "actor": _json_value(r["actor"]),
            "action": r["action"],
            "from_status": r["from_status"],
            "to_status": r["to_status"],
            "note": r["note"],
        }
    )


class PostgresFindingStore:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        mode: str = "local",
        event_bus: EventBus | None = None,
        evidence_exists: EvidenceExists | None = None,
    ) -> None:
        self._pool = pool
        self.mode = mode
        self._bus = event_bus
        self._evidence_exists = evidence_exists

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresFindingStore:
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

    async def _check_evidence_ids(self, evidence_ids: list[str]) -> None:
        if self._evidence_exists is None:
            return
        for evidence_id in evidence_ids:
            if not await self._evidence_exists(evidence_id):
                raise EvidenceRequired(f"evidence not found: {evidence_id}")

    async def _hydrate(self, conn: asyncpg.Connection, row: asyncpg.Record) -> Finding:
        finding = _base_row(row)
        evidence_rows = await conn.fetch(
            "SELECT evidence_id FROM aq_finding_evidence WHERE finding_id=$1 ORDER BY evidence_id",
            finding.id,
        )
        asset_rows = await conn.fetch(
            "SELECT object_id FROM aq_finding_asset WHERE finding_id=$1 ORDER BY object_id",
            finding.id,
        )
        audit_rows = await conn.fetch(
            "SELECT at, actor, action, from_status, to_status, note "
            "FROM aq_finding_audit WHERE finding_id=$1 ORDER BY seq",
            finding.id,
        )
        finding.evidence_ids = [cast(str, r["evidence_id"]) for r in evidence_rows]
        finding.affected_object_ids = [cast(str, r["object_id"]) for r in asset_rows]
        finding.audit = [_audit_row(r) for r in audit_rows]
        return finding

    async def _insert_links(self, conn: asyncpg.Connection, finding: Finding) -> None:
        if finding.evidence_ids:
            await conn.executemany(
                "INSERT INTO aq_finding_evidence (finding_id, evidence_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                [(finding.id, evidence_id) for evidence_id in finding.evidence_ids],
            )
        if finding.affected_object_ids:
            await conn.executemany(
                "INSERT INTO aq_finding_asset (finding_id, object_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                [(finding.id, object_id) for object_id in finding.affected_object_ids],
            )

    async def _append_audit(
        self, conn: asyncpg.Connection, finding_id: str, entries: list[AuditEntry]
    ) -> None:
        if not entries:
            return
        await conn.executemany(
            "INSERT INTO aq_finding_audit "
            "(finding_id, at, actor, action, from_status, to_status, note) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            [
                (
                    finding_id,
                    entry.at,
                    entry.actor.model_dump_json(),
                    entry.action,
                    entry.from_status,
                    entry.to_status,
                    entry.note,
                )
                for entry in entries
            ],
        )

    async def _insert(self, conn: asyncpg.Connection, f: Finding) -> None:
        await conn.execute(
            f"INSERT INTO aq_finding ({_FINDING_COLS}) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,"
            "$22,$23)",
            f.id,
            f.tenant_id,
            f.finding_type,
            f.schema_version,
            f.dedup_key,
            f.title,
            f.severity,
            f.severity_score,
            f.status,
            f.what_happened,
            f.why_it_matters,
            f.how_determined,
            f.risk_of_inaction,
            json.dumps(f.expert_details) if f.expert_details else None,
            f.remediation.model_dump_json(),
            f.automation.model_dump_json(),
            f.confidence,
            f.source_engine,
            f.correlation_id,
            f.first_detected_at,
            f.last_detected_at,
            f.resolved_at,
            f.version,
        )
        await self._insert_links(conn, f)
        await self._append_audit(conn, f.id, f.audit)

    async def _save(self, conn: asyncpg.Connection, f: Finding) -> None:
        await conn.execute(
            "UPDATE aq_finding SET status=$2, last_detected_at=$3, resolved_at=$4, "
            "version=$5 WHERE id=$1",
            f.id,
            f.status,
            f.last_detected_at,
            f.resolved_at,
            f.version,
        )
        await self._insert_links(conn, f)

    async def _emit(self, event_type: str, f: Finding, payload: dict[str, object]) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            Event(
                id=new_id("evt"),
                event_type=event_type,
                schema_version=1,
                tenant_id=f.tenant_id,
                occurred_at=utc_now(),
                recorded_at=utc_now(),
                producer=ActorRef(actor_type="system", actor_id=f.source_engine),
                subject=Subject(object_ids=f.affected_object_ids, finding_id=f.id),
                payload=payload,
                partition_key=f.id,
            )
        )

    async def raise_finding(self, f: Finding) -> Finding:
        validate_finding(f)
        await self._check_evidence_ids(f.evidence_ids)
        now = utc_now()
        event_type: str | None = None
        event_payload: dict[str, object] = {}
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_FINDING_COLS} FROM aq_finding "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 AND finding_type=$2 "
                "AND dedup_key=$3 FOR UPDATE",
                f.tenant_id,
                f.finding_type,
                f.dedup_key,
            )
            if row is not None:
                result = await self._hydrate(conn, row)
                result.last_detected_at = now
                result.evidence_ids = list(dict.fromkeys([*result.evidence_ids, *f.evidence_ids]))
                result.affected_object_ids = list(
                    dict.fromkeys([*result.affected_object_ids, *f.affected_object_ids])
                )
                result.version += 1
                if result.status == "resolved":
                    result.status = "open"
                    result.resolved_at = None
                    audit_entry = AuditEntry(
                        at=now,
                        actor=ActorRef(actor_type="system", actor_id=f.source_engine),
                        action="regressed",
                        from_status="resolved",
                        to_status="open",
                    )
                    result.audit.append(audit_entry)
                    await self._append_audit(conn, result.id, [audit_entry])
                    event_type = "aqelyn.finding.regressed"
                    event_payload = {"dedup_key": result.dedup_key}
                await self._save(conn, result)
            else:
                result = f.model_copy(deep=True)
                if not result.id:
                    result.id = new_id("fnd")
                result.version = 1
                result.first_detected_at = now
                result.last_detected_at = now
                result.audit = [
                    AuditEntry(
                        at=now,
                        actor=ActorRef(actor_type="system", actor_id=f.source_engine),
                        action="raised",
                        to_status=result.status,
                    )
                ]
                await self._insert(conn, result)
                event_type = "aqelyn.finding.raised"
                event_payload = {"finding_type": result.finding_type, "severity": result.severity}
        if event_type is not None:
            await self._emit(event_type, result, event_payload)
        return result

    async def get(self, finding_id: str) -> Finding | None:
        validate_finding_id(finding_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_FINDING_COLS} FROM aq_finding WHERE id=$1", finding_id
            )
            if row is None:
                return None
            return await self._hydrate(conn, row)

    async def query(self, q: FindingQuery) -> tuple[list[Finding], str | None]:
        clauses: list[str] = ["TRUE"]
        args: list[Any] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if q.tenant_id is not None:
            args.append(q.tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if q.status is not None:
            args.append(list(q.status))
            clauses.append(f"status = ANY(${len(args)}::text[])")
        if q.severity is not None:
            args.append(list(q.severity))
            clauses.append(f"severity = ANY(${len(args)}::text[])")
        if q.finding_type is not None:
            args.append(q.finding_type)
            clauses.append(f"finding_type = ${len(args)}")
        if q.affected_object_id is not None:
            args.append(q.affected_object_id)
            clauses.append(
                "EXISTS (SELECT 1 FROM aq_finding_asset "
                f"WHERE aq_finding_asset.finding_id = aq_finding.id "
                f"AND aq_finding_asset.object_id = ${len(args)})"
            )
        args.append(q.limit)
        sql = (
            f"SELECT {_FINDING_COLS} FROM aq_finding WHERE {' AND '.join(clauses)} "
            f"ORDER BY severity_score DESC, id LIMIT ${len(args)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [await self._hydrate(conn, row) for row in rows], None

    async def transition(
        self,
        finding_id: str,
        to_status: str,
        *,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Finding:
        validate_finding_id(finding_id)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_FINDING_COLS} FROM aq_finding WHERE id=$1 FOR UPDATE", finding_id
            )
            if row is None:
                raise FindingNotFound(finding_id)
            result = await self._hydrate(conn, row)
            if result.version != expected_version:
                raise OptimisticConcurrencyConflict("version conflict")
            if to_status not in TRANSITIONS.get(result.status, set()):
                raise InvalidFindingTransition(f"{result.status} -> {to_status}")
            prev = result.status
            result.status = to_status  # type: ignore[assignment]
            result.version += 1
            now = utc_now()
            if to_status == "resolved":
                result.resolved_at = now
            audit_entry = AuditEntry(
                at=now,
                actor=by,
                action="transition",
                from_status=prev,
                to_status=to_status,
                note=note,
            )
            result.audit.append(audit_entry)
            await self._save(conn, result)
            await self._append_audit(conn, result.id, [audit_entry])
        await self._emit("aqelyn.finding.status_changed", result, {"from": prev, "to": to_status})
        return result

    async def add_evidence(
        self, finding_id: str, evidence_ids: list[str], *, by: ActorRef, expected_version: int
    ) -> Finding:
        validate_finding_id(finding_id)
        validate_evidence_refs(evidence_ids)
        await self._check_evidence_ids(evidence_ids)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_FINDING_COLS} FROM aq_finding WHERE id=$1 FOR UPDATE", finding_id
            )
            if row is None:
                raise FindingNotFound(finding_id)
            result = await self._hydrate(conn, row)
            if result.version != expected_version:
                raise OptimisticConcurrencyConflict("version conflict")
            result.evidence_ids = list(dict.fromkeys([*result.evidence_ids, *evidence_ids]))
            result.version += 1
            audit_entry = AuditEntry(at=utc_now(), actor=by, action="add_evidence")
            result.audit.append(audit_entry)
            await self._save(conn, result)
            await self._append_audit(conn, result.id, [audit_entry])
        return result
