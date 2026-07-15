"""L4 acceptance tests for retention, archive, and the deletion boundary."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ArchiveIntegrityError, RetentionBlocked, StoreUnavailable
from aqelyn.evidence import InMemoryBlobStore, InMemoryEvidenceStore
from aqelyn.lake import (
    InMemoryTelemetryRecordStore,
    PostgresTelemetryRecordStore,
    ReferenceCheckers,
    RetentionEngine,
    RetentionPolicy,
    TelemetryRecord,
    TelemetryRecordStore,
)
from aqelyn.workflow import (
    ActionSpec,
    InMemoryActionRegistry,
    InMemoryRunStore,
    Playbook,
    Run,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000195"
TENANT_B = "018f0000-0000-7000-8000-000000000196"
ACTOR = ActorRef(actor_type="user", actor_id="lake-admin@example.com")
NOW = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)


class _ReferenceChecker:
    def __init__(self, referenced: set[str] | None = None, *, fail: bool = False) -> None:
        self.referenced = referenced or set()
        self.fail = fail
        self.calls: list[str] = []

    async def is_referenced(self, record: TelemetryRecord) -> bool:
        self.calls.append(record.id)
        if self.fail:
            raise StoreUnavailable("reference checker unavailable")
        return record.id in self.referenced


class _DeleteHandler:
    def __init__(self) -> None:
        self.spec = ActionSpec(
            action_type="lake.delete_records",
            capability="lake.delete",
            effect="destructive",
            reversible=False,
            description="Delete lake records after Workflow approval.",
        )
        self.execute_count = 0

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        return {"would_delete": True, "inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.execute_count += 1
        return {"deleted": 1, "idempotency_key": idempotency_key, "tenant_id": tenant_id}

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        return None


async def _postgres_store(*, mode: str = "enterprise") -> PostgresTelemetryRecordStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresTelemetryRecordStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_lake_archive, aq_lake_quarantine, aq_lake_record RESTART IDENTITY"
        )
    return store


async def _store(kind: str, *, mode: str = "enterprise") -> AsyncIterator[TelemetryRecordStore]:
    if kind == "inmemory":
        yield InMemoryTelemetryRecordStore(mode=mode)
        return
    store = await _postgres_store(mode=mode)
    try:
        yield store
    finally:
        await store.close()


def _record(
    *,
    tenant_id: str = TENANT_A,
    occurred_at: datetime | None = None,
    legal_hold: bool = False,
    account: str = "alice",
) -> TelemetryRecord:
    occurred = occurred_at or NOW - timedelta(days=90)
    return TelemetryRecord(
        tenant_id=tenant_id,
        dataset="endpoint_process",
        source_id=new_id("src"),
        occurred_at=occurred,
        ingested_at=occurred,
        fields={"account": account, "pid": 4242, "observed_at": occurred.isoformat()},
        legal_hold=legal_hold,
    )


def _policy(*, ttl_days: int | None = 30, archive_after_days: int | None = None) -> RetentionPolicy:
    return RetentionPolicy(
        dataset="endpoint_process",
        tenant_id=TENANT_A,
        ttl_days=ttl_days,
        archive_after_days=archive_after_days,
        set_by=ACTOR,
    )


def _engine(
    store: TelemetryRecordStore,
    *,
    checkers: ReferenceCheckers | None = None,
    workflow_engine: WorkflowEngine | None = None,
) -> tuple[RetentionEngine, InMemoryEvidenceStore, InMemoryBlobStore]:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    blob_store = InMemoryBlobStore()
    return (
        RetentionEngine(
            store=store,
            blob_store=blob_store,
            evidence_store=evidence_store,
            reference_checkers=checkers
            or ReferenceCheckers(
                evidence=_ReferenceChecker(),
                finding=_ReferenceChecker(),
                case=_ReferenceChecker(),
            ),
            workflow_engine=workflow_engine,
            source_id=new_id("src"),
        ),
        evidence_store,
        blob_store,
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_retention_legal_hold(kind: str) -> None:
    async for store in _store(kind):
        held = await store.append(_record(legal_hold=True))
        engine, evidence_store, _ = _engine(store)

        report = await engine.apply(_policy(), as_of=NOW, by=ACTOR)

        assert report.evaluated == 1
        assert report.expired == 0
        assert report.skipped_held == 1
        loaded = await store.get(held.id, tenant_id=TENANT_A)
        assert loaded is not None
        assert loaded.retention_state == "active"
        evidence = await evidence_store.get(report.evidence_id, actor=ACTOR)
        assert evidence.content is not None
        assert evidence.content["kind"] == "retention"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_retention_referenced(kind: str) -> None:
    async for store in _store(kind):
        evidence_ref = await store.append(_record(account="evidence"))
        finding_ref = await store.append(_record(account="finding"))
        case_ref = await store.append(_record(account="case"))
        expired = await store.append(_record(account="expired"))
        checkers = ReferenceCheckers(
            evidence=_ReferenceChecker({evidence_ref.id}),
            finding=_ReferenceChecker({finding_ref.id}),
            case=_ReferenceChecker({case_ref.id}),
        )
        engine, _, _ = _engine(store, checkers=checkers)

        report = await engine.apply(_policy(), as_of=NOW, by=ACTOR)

        assert report.evaluated == 4
        assert report.skipped_referenced == 3
        assert report.expired == 1
        for record in (evidence_ref, finding_ref, case_ref):
            loaded = await store.get(record.id, tenant_id=TENANT_A)
            assert loaded is not None
            assert loaded.retention_state == "active"
        loaded_expired = await store.get(expired.id, tenant_id=TENANT_A)
        assert loaded_expired is not None
        assert loaded_expired.retention_state == "expired"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_retention_reference_unavailable_blocks(kind: str) -> None:
    async for store in _store(kind):
        record = await store.append(_record())
        checkers = ReferenceCheckers(
            evidence=_ReferenceChecker(fail=True),
            finding=_ReferenceChecker(),
            case=_ReferenceChecker(),
        )
        engine, _, _ = _engine(store, checkers=checkers)

        with pytest.raises(RetentionBlocked):
            await engine.apply(_policy(), as_of=NOW, by=ACTOR)

        loaded = await store.get(record.id, tenant_id=TENANT_A)
        assert loaded is not None
        assert loaded.retention_state == "active"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_retention_dry_run(kind: str) -> None:
    async for store in _store(kind):
        record = await store.append(_record())
        engine, evidence_store, _ = _engine(store)

        report = await engine.apply(_policy(), as_of=NOW, by=ACTOR, dry_run=True)

        assert report.expired == 1
        assert "dry-run" in report.reason
        loaded = await store.get(record.id, tenant_id=TENANT_A)
        assert loaded is not None
        assert loaded.retention_state == "active"
        evidence = await evidence_store.get(report.evidence_id, actor=ACTOR)
        assert evidence.content is not None
        assert evidence.content["dry_run"] is True


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_deletion_delegated(kind: str) -> None:
    async for store in _store(kind):
        record = await store.append(_record())
        registry = InMemoryActionRegistry()
        handler = _DeleteHandler()
        registry.register(handler)
        workflow = WorkflowEngine(
            store=InMemoryRunStore(),
            registry=registry,
            evidence_store=InMemoryEvidenceStore(mode="enterprise"),
        )
        engine, _, _ = _engine(store, workflow_engine=workflow)

        run = await engine.propose_deletion(
            dataset="endpoint_process",
            tenant_id=TENANT_A,
            filter=None,
            by=ACTOR,
            reason="tenant retention deletion request",
        )

        assert run.status == "proposed"
        assert run.playbook_id == "lake.deletion"
        assert handler.execute_count == 0
        loaded = await store.get(record.id, tenant_id=TENANT_A)
        assert loaded is not None
        assert loaded.retention_state == "active"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_archive_restore(kind: str) -> None:
    async for store in _store(kind):
        one = await store.append(_record(account="one"))
        two = await store.append(_record(account="two"))
        await store.append(_record(tenant_id=TENANT_B, account="other tenant"))
        engine, _, blob_store = _engine(store)

        archive = await engine.archive(
            dataset="endpoint_process",
            tenant_id=TENANT_A,
            until=NOW,
            by=ACTOR,
        )

        assert archive.record_count == 2
        assert (await store.get_archive(archive.id, tenant_id=TENANT_A)) == archive
        for record in (one, two):
            loaded = await store.get(record.id, tenant_id=TENANT_A)
            assert loaded is not None
            assert loaded.retention_state == "archived"

        restored = await engine.restore(archive.id, tenant_id=TENANT_A, by=ACTOR)
        assert [record.id for record in restored] == [one.id, two.id]
        for record in (one, two):
            loaded = await store.get(record.id, tenant_id=TENANT_A)
            assert loaded is not None
            assert loaded.retention_state == "active"

        tampered = archive.model_copy(update={"content_hash": "0" * 64}, deep=True)
        tamper_store = InMemoryTelemetryRecordStore(mode="enterprise")
        await tamper_store.put_archive(tampered)
        tamper_engine = RetentionEngine(
            store=tamper_store,
            blob_store=blob_store,
            evidence_store=InMemoryEvidenceStore(mode="enterprise"),
            reference_checkers=ReferenceCheckers(
                evidence=_ReferenceChecker(),
                finding=_ReferenceChecker(),
                case=_ReferenceChecker(),
            ),
            source_id=new_id("src"),
        )
        with pytest.raises(ArchiveIntegrityError):
            await tamper_engine.restore(tampered.id, tenant_id=TENANT_A, by=ACTOR)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_lake_lifecycle_evidence(kind: str) -> None:
    async for store in _store(kind):
        record = await store.append(_record())
        engine, evidence_store, _ = _engine(store)

        report = await engine.apply(_policy(), as_of=NOW, by=ACTOR)
        archive = await engine.archive(
            dataset="endpoint_process",
            tenant_id=TENANT_A,
            until=NOW,
            by=ACTOR,
        )

        retention_evidence = await evidence_store.get(report.evidence_id, actor=ACTOR)
        archive_evidence = await evidence_store.get(archive.evidence_id, actor=ACTOR)
        assert retention_evidence.content is not None
        assert retention_evidence.content["updated_record_ids"] == [record.id]
        assert archive_evidence.content is not None
        assert archive_evidence.content["archive_id"] == archive.id
        assert archive.content_hash


async def _assert_proposer_protocol(workflow: WorkflowEngine, playbook: Playbook) -> Run:
    return await workflow.propose(playbook, by=ACTOR)
