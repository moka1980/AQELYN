"""F1 acceptance tests for Digital Forensics intake and cataloging."""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    ALL_ERROR_CODES,
    ArtifactIntegrityError,
    ForensicsConfigInvalid,
)
from aqelyn.evidence import BlobStore, EvidenceStore, InMemoryBlobStore, InMemoryEvidenceStore
from aqelyn.forensics import (
    FORENSIC_ARTIFACT_OBJECT_TYPE,
    Acquisition,
    ForensicsConfig,
    catalog_artifact,
    register_acquisition,
)
from aqelyn.objects import InMemoryObjectStore, ObjectStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="forensics-f1-test")
COLLECTOR = ActorRef(actor_type="user", actor_id="forensic-collector")
NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
CONTENT = b"captured browser artifact bytes"


@dataclass
class ForensicsHarness:
    kind: str
    evidence: EvidenceStore
    blobs: BlobStore
    objects: ObjectStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def forensics_harness(
    request: pytest.FixtureRequest,
) -> AsyncIterator[ForensicsHarness]:
    if request.param == "inmemory":
        yield ForensicsHarness(
            kind="inmemory",
            evidence=InMemoryEvidenceStore(),
            blobs=InMemoryBlobStore(),
            objects=InMemoryObjectStore(),
        )
        return

    if PG_URL is None:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.evidence.postgres import PostgresEvidenceStore
    from aqelyn.objects.postgres import PostgresObjectStore

    evidence_store = await PostgresEvidenceStore.connect(PG_URL)
    object_store = await PostgresObjectStore.connect(PG_URL)
    async with evidence_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_evidence_custody, aq_evidence_package, aq_evidence RESTART IDENTITY"
        )
    async with object_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield ForensicsHarness(
            kind="postgres",
            evidence=evidence_store,
            blobs=InMemoryBlobStore(),
            objects=object_store,
        )
    finally:
        await object_store.close()
        await evidence_store.close()


async def test_dfe_acquisition_custody(forensics_harness: ForensicsHarness) -> None:
    acquisition = await _registered_acquisition(forensics_harness)

    assert acquisition.content_ref is not None
    assert acquisition.content_ref.hash == acquisition.content_hash
    assert acquisition.evidence_id is not None
    record = await forensics_harness.evidence.get(acquisition.evidence_id, actor=SYS)
    assert record.evidence_type == "forensics.acquisition"
    assert record.content is not None
    assert record.content["acquisition"]["id"] == acquisition.id
    custody = await forensics_harness.evidence.custody_of(acquisition.evidence_id)
    assert [entry["action"] for entry in custody] == ["intake", "read"]
    assert custody[0]["actor"] == COLLECTOR.model_dump()


def test_dfe_no_host_access() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "forensics"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))

    forbidden = (
        "socket",
        "requests",
        "httpx",
        "urllib",
        "paramiko",
        "subprocess",
        "open_connection",
        "ftplib",
        "telnet",
        "ssh",
    )
    assert all(term not in source for term in forbidden)


async def test_dfe_integrity_reject(forensics_harness: ForensicsHarness) -> None:
    with pytest.raises(ArtifactIntegrityError):
        await register_acquisition(
            _acquisition(content_hash="0" * 64),
            content=CONTENT,
            blob_store=forensics_harness.blobs,
            evidence_store=forensics_harness.evidence,
            by=SYS,
        )


async def test_dfe_catalog_artifact(forensics_harness: ForensicsHarness) -> None:
    acquisition = await _registered_acquisition(forensics_harness)
    assert acquisition.content_ref is not None

    artifact = await catalog_artifact(
        acquisition,
        artifact_type="browser",
        metadata={"profile": "Default", "event_count": 4},
        object_store=forensics_harness.objects,
        evidence_store=forensics_harness.evidence,
        by=SYS,
    )

    assert artifact.acquisition_id == acquisition.id
    assert artifact.evidence_id
    assert artifact.case_id == acquisition.case_id
    obj = await forensics_harness.objects.get(artifact.object_id)
    assert obj is not None
    assert obj.object_type == FORENSIC_ARTIFACT_OBJECT_TYPE
    assert obj.attributes["content_ref"] == acquisition.content_ref.model_dump(mode="json")
    assert obj.attributes["metadata"] == {"profile": "Default", "event_count": 4}
    assert obj.sources[0].evidence_id == acquisition.evidence_id

    evidence = await forensics_harness.evidence.get(artifact.evidence_id, actor=SYS)
    assert evidence.method == "forensics.catalog_artifact/v1"
    assert evidence.subject.object_ids == [artifact.object_id]
    assert evidence.content is not None
    assert evidence.content["content_ref"] == acquisition.content_ref.model_dump(mode="json")
    assert (await forensics_harness.evidence.verify(artifact.evidence_id)).ok


def test_dfe_config_invalid() -> None:
    with pytest.raises(ForensicsConfigInvalid):
        ForensicsConfig(batch_size=0)
    with pytest.raises(ForensicsConfigInvalid):
        Acquisition(
            tenant_id=None,
            source_ref="browser-export",
            collector=COLLECTOR,
            method="manual-copy",
            acquired_at=NOW,
            content_hash="not-a-hash",
        )
    with pytest.raises(ForensicsConfigInvalid):
        Acquisition(
            tenant_id=None,
            source_ref="",
            collector=COLLECTOR,
            method="manual-copy",
            acquired_at=NOW,
            content_hash=_content_hash(CONTENT),
        )
    assert "ForensicsConfigInvalid" in ALL_ERROR_CODES
    assert "ArtifactIntegrityError" in ALL_ERROR_CODES
    assert "ArtifactNotFound" in ALL_ERROR_CODES


async def _registered_acquisition(harness: ForensicsHarness) -> Acquisition:
    return await register_acquisition(
        _acquisition(content_hash=_content_hash(CONTENT)),
        content=CONTENT,
        blob_store=harness.blobs,
        evidence_store=harness.evidence,
        by=SYS,
        media_type="application/octet-stream",
    )


def _acquisition(*, content_hash: str) -> Acquisition:
    return Acquisition(
        tenant_id=None,
        source_ref="browser-export",
        collector=COLLECTOR,
        method="manual-copy",
        acquired_at=NOW,
        content_hash=content_hash,
        case_id=new_id("inc"),
    )


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
