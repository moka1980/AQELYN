"""Handed-in forensic acquisition and cataloging helpers (EA-0016 F1)."""

from __future__ import annotations

from typing import Protocol, cast

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import ArtifactIntegrityError, ForensicsConfigInvalid
from aqelyn.events import Subject
from aqelyn.evidence import BlobStore, EvidenceRecord, EvidenceStore
from aqelyn.forensics.models import (
    FORENSIC_ARTIFACT_OBJECT_TYPE,
    Acquisition,
    Artifact,
)
from aqelyn.objects import AQObject, NaturalKey, ObjectStore, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry

_ACTOR = ActorRef(actor_type="system", actor_id="forensics_engine")


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


def register_forensic_object_types(registry: ObjectTypeRegistry) -> None:
    registry.register(FORENSIC_ARTIFACT_OBJECT_TYPE, 1, None)


def ensure_forensic_object_types(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        register_forensic_object_types(registry)
        return
    if registry is not None:
        register_forensic_object_types(cast(_ObjectStoreRegistry, object_store).registry)


async def register_acquisition(
    acquisition: Acquisition,
    *,
    content: bytes,
    blob_store: BlobStore,
    evidence_store: EvidenceStore,
    by: ActorRef,
    media_type: str = "application/octet-stream",
) -> Acquisition:
    if not content:
        raise ForensicsConfigInvalid("acquisition content must not be empty")
    if not media_type.strip():
        raise ForensicsConfigInvalid("media_type must not be empty")

    content_ref = await blob_store.put(content, media_type=media_type)
    if content_ref.hash != acquisition.content_hash:
        raise ArtifactIntegrityError("acquisition content_hash does not match handed-in content")

    recorded = acquisition.model_copy(
        update={
            "id": acquisition.id or new_id("acq"),
            "content_ref": content_ref,
        },
        deep=True,
    )
    evidence = await evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=recorded.tenant_id,
            evidence_type="forensics.acquisition",
            schema_version=1,
            subject=Subject(),
            collected_at=recorded.acquired_at,
            recorded_at=utc_now(),
            collector=recorded.collector,
            source_id=new_id("src"),
            method="forensics.register_acquisition/v1",
            content={
                "acquisition": recorded.model_dump(mode="json"),
                "registered_by": by.model_dump(mode="json"),
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0016", "kind": "acquisition"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    return recorded.model_copy(update={"evidence_id": evidence.id}, deep=True)


async def catalog_artifact(
    acquisition: Acquisition,
    *,
    artifact_type: str,
    metadata: dict[str, object],
    object_store: ObjectStore,
    evidence_store: EvidenceStore,
    by: ActorRef = _ACTOR,
) -> Artifact:
    if acquisition.content_ref is None:
        raise ForensicsConfigInvalid("acquisition must be registered before cataloging")
    if acquisition.evidence_id is None:
        raise ForensicsConfigInvalid("acquisition evidence_id is required before cataloging")
    if not artifact_type.strip():
        raise ForensicsConfigInvalid("artifact_type must not be empty")

    ensure_forensic_object_types(object_store)
    now = utc_now()
    artifact_object = await object_store.upsert(
        AQObject(
            id="",
            object_type=FORENSIC_ARTIFACT_OBJECT_TYPE,
            schema_version=1,
            tenant_id=acquisition.tenant_id,
            display_name=f"{artifact_type}:{acquisition.source_ref}",
            attributes={
                "artifact_type": artifact_type,
                "acquisition_id": acquisition.id,
                "case_id": acquisition.case_id,
                "source_ref": acquisition.source_ref,
                "method": acquisition.method,
                "content_ref": acquisition.content_ref.model_dump(mode="json"),
                "content_hash": acquisition.content_hash,
                "metadata": dict(metadata),
            },
            labels={
                "module": "EA-0016",
                "kind": "forensic_artifact",
                "artifact_type": artifact_type,
            },
            natural_keys=[
                NaturalKey(
                    namespace="forensics.acquisition_artifact",
                    value=f"{acquisition.id}:{artifact_type}",
                )
            ],
            sources=[
                SourceRef(
                    source_id=new_id("src"),
                    evidence_id=acquisition.evidence_id,
                    observed_at=acquisition.acquired_at,
                    method="forensics.acquisition/v1",
                )
            ],
            first_seen_at=acquisition.acquired_at,
            last_seen_at=acquisition.acquired_at,
            created_at=now,
            updated_at=now,
            created_by=by,
            updated_by=by,
        )
    )
    evidence = await evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=acquisition.tenant_id,
            evidence_type="forensics.artifact_cataloged",
            schema_version=1,
            subject=Subject(object_ids=[artifact_object.id]),
            collected_at=acquisition.acquired_at,
            recorded_at=now,
            collector=by,
            source_id=new_id("src"),
            method="forensics.catalog_artifact/v1",
            content={
                "acquisition_id": acquisition.id,
                "acquisition_evidence_id": acquisition.evidence_id,
                "artifact_type": artifact_type,
                "object_id": artifact_object.id,
                "content_ref": acquisition.content_ref.model_dump(mode="json"),
                "content_hash": acquisition.content_hash,
                "metadata": dict(metadata),
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0016", "kind": "artifact_cataloged"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    return Artifact(
        tenant_id=acquisition.tenant_id,
        artifact_type=artifact_type,
        acquisition_id=acquisition.id,
        object_id=artifact_object.id,
        evidence_id=evidence.id,
        metadata=dict(metadata),
        linked_asset_ids=[],
        first_seen_at=acquisition.acquired_at,
        case_id=acquisition.case_id,
    )
