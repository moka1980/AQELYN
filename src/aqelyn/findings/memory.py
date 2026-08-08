"""In-memory FindingStore (Finding model). Reference implementation."""

from __future__ import annotations

import copy
from collections.abc import Callable

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    EvidenceRequired,
    FindingNotFound,
    InvalidFindingTransition,
    OptimisticConcurrencyConflict,
)
from aqelyn.events import Event, EventBus, Subject
from aqelyn.findings.models import (
    TRANSITIONS,
    AuditEntry,
    Finding,
    FindingQuery,
    decode_finding_cursor,
    encode_finding_cursor,
)
from aqelyn.findings.store import (
    EvidenceExists,
    validate_evidence_refs,
    validate_finding,
    validate_finding_id,
)


class InMemoryFindingStore:
    def __init__(
        self,
        *,
        mode: str = "local",
        event_bus: EventBus | None = None,
        evidence_exists: EvidenceExists | None = None,
    ) -> None:
        self._by_id: dict[str, Finding] = {}
        self._dedup: dict[tuple[str | None, str, str], str] = {}
        self.mode = mode
        self._bus = event_bus
        self._evidence_exists = evidence_exists

    async def _check_evidence(self, f: Finding) -> None:
        if self._evidence_exists is None:
            return
        for eid in f.evidence_ids:
            if not await self._evidence_exists(eid):
                raise EvidenceRequired(f"evidence not found: {eid}")

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
        live, event_type, payload, _undo = await self._raise_quiet(f)
        if event_type is not None:
            await self._emit(event_type, live, payload)
        return copy.deepcopy(live)

    async def _raise_quiet(
        self, f: Finding
    ) -> tuple[Finding, str | None, dict[str, object], Callable[[], None]]:
        """The raise without its event, plus a precise undo of THIS write only (ECR-0124).

        An atomic composite defers the returned event until its whole unit succeeds and calls
        the undo if it does not — touching nothing but the one finding this call wrote."""

        validate_finding(f)
        await self._check_evidence(f)
        key = (f.tenant_id, f.finding_type, f.dedup_key)
        existing_id = self._dedup.get(key)
        now = utc_now()
        if existing_id is not None:
            existing = self._by_id[existing_id]
            before = copy.deepcopy(existing)

            def _undo_update() -> None:
                self._by_id[existing_id] = before

            existing.last_detected_at = now
            existing.evidence_ids = list(dict.fromkeys([*existing.evidence_ids, *f.evidence_ids]))
            existing.affected_object_ids = list(
                dict.fromkeys([*existing.affected_object_ids, *f.affected_object_ids])
            )
            existing.version += 1
            # ECR-0063: escalation is visible without moving the sort key. The finding
            # keeps its original `severity_score` -- which is what keeps ECR-0062's
            # cursor safe -- while `current_severity_score` follows the latest emission.
            existing.current_severity_score = f.severity_score
            event_type: str | None = None
            payload: dict[str, object] = {}
            if existing.status == "resolved":
                existing.status = "open"
                existing.resolved_at = None
                existing.audit.append(
                    AuditEntry(
                        at=now,
                        actor=ActorRef(actor_type="system", actor_id=f.source_engine),
                        action="regressed",
                        from_status="resolved",
                        to_status="open",
                    )
                )
                event_type = "aqelyn.finding.regressed"
                payload = {"dedup_key": existing.dedup_key}
            return existing, event_type, payload, _undo_update
        created = f.model_copy(deep=True)
        if not created.id:
            created.id = new_id("fnd")
        created.version = 1
        if created.current_severity_score is None:
            created.current_severity_score = created.severity_score
        created.first_detected_at = now
        created.last_detected_at = now
        created.audit = [
            AuditEntry(
                at=now,
                actor=ActorRef(actor_type="system", actor_id=f.source_engine),
                action="raised",
                to_status=created.status,
            )
        ]
        self._by_id[created.id] = created
        self._dedup[key] = created.id
        created_id = created.id

        def _undo_create() -> None:
            self._by_id.pop(created_id, None)
            if self._dedup.get(key) == created_id:
                del self._dedup[key]

        return (
            created,
            "aqelyn.finding.raised",
            {"finding_type": created.finding_type, "severity": created.severity},
            _undo_create,
        )

    async def get(self, finding_id: str) -> Finding | None:
        validate_finding_id(finding_id)
        f = self._by_id.get(finding_id)
        return copy.deepcopy(f) if f else None

    async def query(self, q: FindingQuery) -> tuple[list[Finding], str | None]:
        rows: list[Finding] = []
        for f in self._by_id.values():
            if self.mode == "local" and f.tenant_id is not None:
                continue
            if q.tenant_id is not None and f.tenant_id != q.tenant_id:
                continue
            if q.status is not None and f.status not in q.status:
                continue
            if q.severity is not None and f.severity not in q.severity:
                continue
            if q.finding_type is not None and f.finding_type != q.finding_type:
                continue
            if q.affected_object_id is not None and q.affected_object_id not in (
                f.affected_object_ids
            ):
                continue
            rows.append(copy.deepcopy(f))
        rows.sort(key=lambda x: (-x.severity_score, x.id))
        if q.cursor is not None:
            # Resume after the complete sort key. `id`-only would be incoherent here:
            # a larger id sorts *before* the cursor row when its severity is higher.
            score, finding_id = decode_finding_cursor(q.cursor)
            rows = [
                row
                for row in rows
                if row.severity_score < score
                or (row.severity_score == score and row.id > finding_id)
            ]
        page = rows[: q.limit]
        next_cursor = (
            encode_finding_cursor(
                severity_score=page[-1].severity_score,
                finding_id=page[-1].id,
            )
            if len(rows) > q.limit
            else None
        )
        return page, next_cursor

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
        f = self._by_id.get(finding_id)
        if f is None:
            raise FindingNotFound(finding_id)
        if f.version != expected_version:
            raise OptimisticConcurrencyConflict(f"expected v{expected_version}, found v{f.version}")
        if to_status not in TRANSITIONS.get(f.status, set()):
            raise InvalidFindingTransition(f"{f.status} -> {to_status}")
        prev = f.status
        f.status = to_status  # type: ignore[assignment]
        f.version += 1
        now = utc_now()
        if to_status == "resolved":
            f.resolved_at = now
        f.audit.append(
            AuditEntry(
                at=now,
                actor=by,
                action="transition",
                from_status=prev,
                to_status=to_status,
                note=note,
            )
        )
        await self._emit("aqelyn.finding.status_changed", f, {"from": prev, "to": to_status})
        return copy.deepcopy(f)

    async def add_evidence(
        self, finding_id: str, evidence_ids: list[str], *, by: ActorRef, expected_version: int
    ) -> Finding:
        validate_finding_id(finding_id)
        validate_evidence_refs(evidence_ids)
        f = self._by_id.get(finding_id)
        if f is None:
            raise FindingNotFound(finding_id)
        if f.version != expected_version:
            raise OptimisticConcurrencyConflict("version conflict")
        f.evidence_ids = list(dict.fromkeys([*f.evidence_ids, *evidence_ids]))
        f.version += 1
        f.audit.append(AuditEntry(at=utc_now(), actor=by, action="add_evidence"))
        return copy.deepcopy(f)
