"""F3 acceptance tests for Digital Forensics timeline and verification."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore
from aqelyn.forensics import (
    Artifact,
    ArtifactStore,
    InMemoryArtifactStore,
    PostgresArtifactStore,
    build_timeline,
    custody_chain,
    explain,
    verify_artifact,
    verify_case,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="forensics-f3-test")
COLLECTOR = ActorRef(actor_type="user", actor_id="forensics-f3-collector")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
CASE_ID = new_id("inc")
NOW = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)


@dataclass
class F3Harness:
    kind: str
    evidence: EvidenceStore
    artifacts: ArtifactStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def f3_harness(request: pytest.FixtureRequest) -> AsyncIterator[F3Harness]:
    if request.param == "inmemory":
        yield F3Harness(
            kind="inmemory",
            evidence=InMemoryEvidenceStore(),
            artifacts=InMemoryArtifactStore(),
        )
        return

    if PG_URL is None:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.evidence.postgres import PostgresEvidenceStore

    evidence = await PostgresEvidenceStore.connect(PG_URL)
    artifacts = await PostgresArtifactStore.connect(PG_URL)
    async with evidence._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_evidence_custody, aq_evidence_package, aq_evidence RESTART IDENTITY"
        )
    async with artifacts._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_forensics_artifact")
    try:
        yield F3Harness(kind="postgres", evidence=evidence, artifacts=artifacts)
    finally:
        await artifacts.close()
        await evidence.close()


async def test_dfe_custody_chain(f3_harness: F3Harness) -> None:
    artifact, record = await _stored_artifact(f3_harness, name="custody")
    await f3_harness.evidence.get(record.id, actor=SYS)

    chain = await custody_chain(
        artifact.id,
        artifact_store=f3_harness.artifacts,
        evidence_store=f3_harness.evidence,
    )

    assert [entry["action"] for entry in chain] == ["intake", "read"]
    assert chain[0]["actor"] == COLLECTOR.model_dump()
    assert chain[1]["actor"] == SYS.model_dump()


async def test_dfe_timeline(f3_harness: F3Harness) -> None:
    first, _ = await _stored_artifact(
        f3_harness,
        name="first",
        metadata={
            "timeline_events": [
                {
                    "at": (NOW + timedelta(minutes=2)).isoformat(),
                    "kind": "browser_visit",
                    "detail": {"url": "https://example.test/a"},
                }
            ]
        },
        first_seen_at=NOW + timedelta(minutes=20),
    )
    second, _ = await _stored_artifact(
        f3_harness,
        name="second",
        metadata={
            "timeline_events": [
                {
                    "at": (NOW + timedelta(minutes=1)).isoformat(),
                    "kind": "file_opened",
                    "detail": {"path": "/case/file.txt"},
                }
            ]
        },
        first_seen_at=NOW + timedelta(minutes=10),
    )
    third, _ = await _stored_artifact(
        f3_harness,
        name="third",
        metadata={
            "timeline_events": [
                {
                    "at": (NOW + timedelta(minutes=3)).isoformat(),
                    "kind": "process_seen",
                    "detail": {"pid": 42},
                }
            ]
        },
        first_seen_at=NOW,
    )

    left = await build_timeline(
        artifact_store=f3_harness.artifacts,
        tenant_id=None,
        case_id=CASE_ID,
        artifact_ids=[first.id, second.id, third.id],
        limit=2,
    )
    right = await build_timeline(
        artifact_store=f3_harness.artifacts,
        tenant_id=None,
        case_id=CASE_ID,
        artifact_ids=[third.id, first.id, second.id],
        limit=2,
    )

    assert left.model_dump(mode="json") == right.model_dump(mode="json")
    assert left.truncated is True
    assert [event.kind for event in left.events] == ["file_opened", "browser_visit"]
    assert [event.artifact_id for event in left.events] == [second.id, first.id]
    assert all(event.evidence_id for event in left.events)
    detail = explain(left.events[0])
    assert detail["artifact_id"] == second.id
    assert detail["evidence_id"] == second.evidence_id
    assert "cited evidence" in detail["reason"]


async def test_dfe_verify_tamper(f3_harness: F3Harness) -> None:
    artifact, record = await _stored_artifact(
        f3_harness,
        name="tamper",
        tenant_id=TENANT_A,
        case_id=CASE_ID,
    )
    before = await f3_harness.evidence.custody_of(record.id)
    await _tamper_evidence(f3_harness, record.id)

    artifact_report = await verify_artifact(
        artifact.id,
        artifact_store=f3_harness.artifacts,
        evidence_store=f3_harness.evidence,
    )
    assert artifact_report.subject_id == artifact.id
    assert artifact_report.ok is False
    assert artifact_report.broken_at == f"seq:{record.seq}"
    assert artifact_report.detail == "content hash mismatch"

    case_report = await verify_case(
        CASE_ID,
        tenant_id=TENANT_A,
        artifact_store=f3_harness.artifacts,
        evidence_store=f3_harness.evidence,
    )
    assert case_report.ok is False
    assert case_report.broken_at == f"seq:{record.seq}"

    await verify_case(
        CASE_ID,
        tenant_id=TENANT_A,
        artifact_store=f3_harness.artifacts,
        evidence_store=f3_harness.evidence,
    )
    await verify_case(
        CASE_ID,
        tenant_id=TENANT_A,
        artifact_store=f3_harness.artifacts,
        evidence_store=f3_harness.evidence,
    )
    after = await f3_harness.evidence.custody_of(record.id)
    assert after == before


async def _stored_artifact(
    harness: F3Harness,
    *,
    name: str,
    tenant_id: str | None = None,
    case_id: str | None = CASE_ID,
    metadata: dict[str, object] | None = None,
    first_seen_at: datetime = NOW,
) -> tuple[Artifact, EvidenceRecord]:
    evidence = await harness.evidence.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="forensics.artifact_cataloged",
            schema_version=1,
            subject=Subject(object_ids=[new_id("obj")]),
            collected_at=first_seen_at,
            recorded_at=utc_now(),
            collector=COLLECTOR,
            source_id=new_id("src"),
            method="forensics.f3-test/v1",
            content={"name": name, "metadata": dict(metadata or {})},
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0016", "kind": "artifact_cataloged"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    artifact = await harness.artifacts.put(
        Artifact(
            id="",
            tenant_id=tenant_id,
            artifact_type="browser",
            acquisition_id=new_id("acq"),
            object_id=evidence.subject.object_ids[0],
            evidence_id=evidence.id,
            metadata=dict(metadata or {}),
            linked_asset_ids=[],
            first_seen_at=first_seen_at,
            case_id=case_id,
        )
    )
    return artifact, evidence


async def _tamper_evidence(harness: F3Harness, evidence_id: str) -> None:
    if harness.kind == "inmemory":
        store = cast(Any, harness.evidence)
        rec = store._by_id[evidence_id]
        assert rec.content is not None
        rec.content["tampered"] = True
        return

    store = cast(Any, harness.evidence)
    async with store._pool.acquire() as conn:
        await conn.execute(
            "UPDATE aq_evidence SET content = jsonb_set(content, '{tampered}', 'true'::jsonb) "
            "WHERE id=$1",
            evidence_id,
        )
