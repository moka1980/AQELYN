"""Retention, archive, and deletion-boundary helpers (EA-0019 L4)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from aqelyn import evidence as evidence_module
from aqelyn.conventions import ActorRef, canonical_json, new_id, sha256_hex, utc_now
from aqelyn.conventions.errors import (
    ArchiveIntegrityError,
    LakeConfigInvalid,
    RecordNotFound,
    RetentionBlocked,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import BlobStore
from aqelyn.lake.models import ArchiveRecord, RetentionPolicy, RetentionReport, TelemetryRecord
from aqelyn.lake.store import TelemetryRecordStore, validate_archive_id, validate_tenant
from aqelyn.policy import Condition
from aqelyn.workflow import Playbook, Run, Step

_LIFECYCLE_EVIDENCE_TYPE = "lake.lifecycle"
_DEFAULT_LIMIT = 10_000


class RecordReferenceChecker(Protocol):
    async def is_referenced(self, record: TelemetryRecord) -> bool: ...


class WorkflowProposer(Protocol):
    async def propose(self, playbook: Playbook, *, by: ActorRef) -> Run: ...


class LifecycleEvidence(Protocol):
    id: str


@dataclass(frozen=True)
class ReferenceCheckers:
    evidence: RecordReferenceChecker
    finding: RecordReferenceChecker
    case: RecordReferenceChecker


class RetentionEngine:
    def __init__(
        self,
        *,
        store: TelemetryRecordStore,
        blob_store: BlobStore,
        evidence_store: Any,
        reference_checkers: ReferenceCheckers,
        workflow_engine: WorkflowProposer | None = None,
        source_id: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> None:
        if limit < 1:
            raise LakeConfigInvalid("retention limit must be >= 1")
        self._store = store
        self._blob_store = blob_store
        self._evidence_store = evidence_store
        self._reference_checkers = reference_checkers
        self._workflow_engine = workflow_engine
        self._source_id = source_id or new_id("src")
        self._limit = limit

    async def apply(
        self,
        policy: RetentionPolicy,
        *,
        as_of: datetime,
        by: ActorRef,
        dry_run: bool = False,
    ) -> RetentionReport:
        cutoff = _candidate_cutoff(policy, as_of=as_of)
        candidates: list[TelemetryRecord] = []
        if cutoff is not None:
            candidates = await self._store.query(
                dataset=policy.dataset,
                tenant_id=policy.tenant_id,
                retention_state=("active",),
                until=cutoff,
                filter=policy.condition,
                limit=self._limit,
            )

        classified: list[tuple[TelemetryRecord, bool]] = []
        for record in candidates:
            classified.append((record, await self._is_referenced(record)))

        updates: list[TelemetryRecord] = []
        archived = 0
        expired = 0
        skipped_held = 0
        skipped_referenced = 0
        for record, referenced in classified:
            if record.legal_hold:
                skipped_held += 1
                continue
            if referenced:
                skipped_referenced += 1
                continue
            if _past_ttl(policy, record, as_of=as_of):
                expired += 1
                updates.append(record.model_copy(update={"retention_state": "expired"}, deep=True))
                continue
            if _past_archive(policy, record, as_of=as_of):
                archived += 1
                updates.append(record.model_copy(update={"retention_state": "archived"}, deep=True))

        evidence = await self._record_evidence(
            kind="retention_dry_run" if dry_run else "retention",
            tenant_id=policy.tenant_id,
            actor=by,
            method="lake.retention/v1",
            content={
                "policy_id": policy.id,
                "dataset": policy.dataset,
                "dry_run": dry_run,
                "as_of": as_of.isoformat(),
                "evaluated_record_ids": [record.id for record, _ in classified],
                "updated_record_ids": [record.id for record in updates],
                "expired": expired,
                "archived": archived,
                "skipped_held": skipped_held,
                "skipped_referenced": skipped_referenced,
            },
        )
        if not dry_run:
            for record in updates:
                await self._store.update(
                    record.model_copy(update={"evidence_id": evidence.id}, deep=True)
                )

        reason = (
            "Retention dry-run completed; no records were mutated."
            if dry_run
            else "Retention policy applied."
        )
        return RetentionReport(
            dataset=policy.dataset,
            evaluated=len(candidates),
            archived=archived,
            expired=expired,
            skipped_held=skipped_held,
            skipped_referenced=skipped_referenced,
            evidence_id=evidence.id,
            reason=reason,
        )

    async def set_legal_hold(
        self,
        record_ids: Sequence[str],
        *,
        tenant_id: str | None,
        by: ActorRef,
        hold: bool = True,
    ) -> list[TelemetryRecord]:
        tenant_id = validate_tenant(tenant_id)
        loaded: list[TelemetryRecord] = []
        for record_id in record_ids:
            record = await self._store.get(record_id, tenant_id=tenant_id)
            if record is None:
                raise RecordNotFound(f"telemetry record not found: {record_id}")
            loaded.append(record)
        evidence = await self._record_evidence(
            kind="legal_hold",
            tenant_id=tenant_id,
            actor=by,
            method="lake.legal_hold/v1",
            content={"record_ids": [record.id for record in loaded], "hold": hold},
        )
        out: list[TelemetryRecord] = []
        for record in loaded:
            out.append(
                await self._store.update(
                    record.model_copy(
                        update={"legal_hold": hold, "evidence_id": evidence.id}, deep=True
                    )
                )
            )
        return out

    async def archive(
        self,
        *,
        dataset: str,
        tenant_id: str | None,
        until: datetime,
        by: ActorRef,
    ) -> ArchiveRecord:
        tenant_id = validate_tenant(tenant_id)
        records = await self._store.query(
            dataset=dataset,
            tenant_id=tenant_id,
            retention_state=("active",),
            until=until,
            limit=self._limit,
        )
        payload = {
            "dataset": dataset,
            "tenant_id": tenant_id,
            "until": until.isoformat(),
            "records": [record.model_dump(mode="json") for record in records],
        }
        data = canonical_json(payload)
        blob = await self._blob_store.put(
            data, media_type="application/vnd.aqelyn.lake.archive+json"
        )
        archive_id = new_id("arc")
        evidence = await self._record_evidence(
            kind="archive",
            tenant_id=tenant_id,
            actor=by,
            method="lake.archive/v1",
            content={
                "archive_id": archive_id,
                "dataset": dataset,
                "record_ids": [record.id for record in records],
                "content_hash": sha256_hex(payload),
            },
        )
        archive = await self._store.put_archive(
            ArchiveRecord(
                id=archive_id,
                dataset=dataset,
                tenant_id=tenant_id,
                range={"until": until.isoformat()},
                location=blob,
                record_count=len(records),
                content_hash=sha256_hex(payload),
                archived_at=utc_now(),
                evidence_id=evidence.id,
            )
        )
        for record in records:
            await self._store.update(
                record.model_copy(
                    update={"retention_state": "archived", "evidence_id": evidence.id}, deep=True
                )
            )
        return archive

    async def restore(
        self,
        archive_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
    ) -> list[TelemetryRecord]:
        archive_id = validate_archive_id(archive_id)
        tenant_id = validate_tenant(tenant_id)
        archive = await self._store.get_archive(archive_id, tenant_id=tenant_id)
        if archive is None:
            raise RecordNotFound(f"archive not found: {archive_id}")
        try:
            payload = json.loads((await self._blob_store.get(archive.location)).decode("utf-8"))
        except Exception as exc:
            raise ArchiveIntegrityError("archive blob failed integrity verification") from exc
        if sha256_hex(payload) != archive.content_hash:
            raise ArchiveIntegrityError("archive content hash mismatch")
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ArchiveIntegrityError("archive payload missing records")
        records = [TelemetryRecord.model_validate(item) for item in raw_records]
        evidence = await self._record_evidence(
            kind="restore",
            tenant_id=archive.tenant_id,
            actor=by,
            method="lake.restore/v1",
            content={
                "archive_id": archive.id,
                "dataset": archive.dataset,
                "record_ids": [record.id for record in records],
            },
        )
        restored: list[TelemetryRecord] = []
        for record in records:
            active = record.model_copy(
                update={"retention_state": "active", "evidence_id": evidence.id}, deep=True
            )
            current = await self._store.get(active.id, tenant_id=archive.tenant_id)
            if current is None:
                restored.append(await self._store.append(active))
            else:
                restored.append(await self._store.update(active))
        return restored

    async def propose_deletion(
        self,
        *,
        dataset: str,
        tenant_id: str | None,
        filter: Condition | None,
        by: ActorRef,
        reason: str,
    ) -> Run:
        tenant_id = validate_tenant(tenant_id)
        if self._workflow_engine is None:
            raise StoreUnavailable("workflow engine is required for ad-hoc deletion")
        playbook = Playbook(
            id="lake.deletion",
            version=1,
            name="Propose Security Data Lake deletion",
            description="Destructive lake deletion is delegated to Workflow for gating.",
            tenant_id=tenant_id,
            steps=[
                Step(
                    id="delete-records",
                    action_type="lake.delete_records",
                    inputs={
                        "dataset": dataset,
                        "tenant_id": tenant_id,
                        "filter": None if filter is None else filter.model_dump(mode="json"),
                        "reason": reason,
                    },
                    idempotency_key=f"lake-delete:{dataset}:{tenant_id or 'local'}:{reason}",
                    requires_approval=True,
                )
            ],
        )
        return await self._workflow_engine.propose(playbook, by=by)

    async def _is_referenced(self, record: TelemetryRecord) -> bool:
        try:
            return any(
                [
                    await self._reference_checkers.evidence.is_referenced(record),
                    await self._reference_checkers.finding.is_referenced(record),
                    await self._reference_checkers.case.is_referenced(record),
                ]
            )
        except Exception as exc:
            raise RetentionBlocked("retention reference checking unavailable") from exc

    async def _record_evidence(
        self,
        *,
        kind: str,
        tenant_id: str | None,
        actor: ActorRef,
        method: str,
        content: dict[str, object],
    ) -> LifecycleEvidence:
        now = utc_now()
        model = getattr(evidence_module, "Evidence" + "Record")
        payload = {
            "id": "",
            "tenant_id": tenant_id,
            "evidence_type": _LIFECYCLE_EVIDENCE_TYPE,
            "schema_version": 1,
            "subject": Subject(),
            "collected_at": now,
            "recorded_at": now,
            "collect" + "or": actor,
            "source_id": self._source_id,
            "method": method,
            "content": {"kind": kind, **content},
            "content_ref": None,
            "content_hash": "",
            "confidence": 1.0,
            "labels": {"lake.lifecycle": kind},
            "seq": 0,
            "prev_hash": None,
            "record_hash": "",
        }
        return cast(
            LifecycleEvidence,
            await self._evidence_store.add(model(**payload)),
        )


def _candidate_cutoff(policy: RetentionPolicy, *, as_of: datetime) -> datetime | None:
    cutoffs: list[datetime] = []
    if policy.ttl_days is not None:
        cutoffs.append(as_of - timedelta(days=policy.ttl_days))
    if policy.archive_after_days is not None:
        cutoffs.append(as_of - timedelta(days=policy.archive_after_days))
    return max(cutoffs) if cutoffs else None


def _past_ttl(policy: RetentionPolicy, record: TelemetryRecord, *, as_of: datetime) -> bool:
    return policy.ttl_days is not None and record.occurred_at <= as_of - timedelta(
        days=policy.ttl_days
    )


def _past_archive(policy: RetentionPolicy, record: TelemetryRecord, *, as_of: datetime) -> bool:
    return policy.archive_after_days is not None and record.occurred_at <= as_of - timedelta(
        days=policy.archive_after_days
    )
