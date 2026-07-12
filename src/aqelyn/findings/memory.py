"""In-memory FindingStore (Finding model). Reference implementation."""

from __future__ import annotations

import copy

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    EvidenceRequired,
    FindingNotFound,
    InvalidFindingTransition,
    OptimisticConcurrencyConflict,
)
from aqelyn.events import Event, EventBus, Subject
from aqelyn.findings.models import TRANSITIONS, AuditEntry, Finding, FindingQuery
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
        validate_finding(f)
        await self._check_evidence(f)
        key = (f.tenant_id, f.finding_type, f.dedup_key)
        existing_id = self._dedup.get(key)
        now = utc_now()
        if existing_id is not None:
            existing = self._by_id[existing_id]
            existing.last_detected_at = now
            existing.evidence_ids = list(dict.fromkeys([*existing.evidence_ids, *f.evidence_ids]))
            existing.affected_object_ids = list(
                dict.fromkeys([*existing.affected_object_ids, *f.affected_object_ids])
            )
            existing.version += 1
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
                await self._emit(
                    "aqelyn.finding.regressed", existing, {"dedup_key": existing.dedup_key}
                )
            return copy.deepcopy(existing)
        created = f.model_copy(deep=True)
        if not created.id:
            created.id = new_id("fnd")
        created.version = 1
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
        await self._emit(
            "aqelyn.finding.raised",
            created,
            {"finding_type": created.finding_type, "severity": created.severity},
        )
        return copy.deepcopy(created)

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
        return rows[: q.limit], None

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
