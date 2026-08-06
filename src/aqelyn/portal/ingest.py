"""Tenant-scoped posture ingest for the authenticated portal (ECR-0118).

The offline report path (``reporting.analyze._ingest_posture``) raises findings into a throwaway
local runtime with no tenant. The customer portal is the other case: a long-lived runtime holding
many tenants' data, where **every** row a customer's upload creates must carry that customer's
``tenant_id`` — the object, the evidence, and the finding. The tenant comes from the caller's
session and is stamped here; it is never read from the uploaded document.

The uploaded document is hostile input. ``validate_posture_shape`` is the gate — it returns the
observation list or refuses the document with a located reason, and this function never repairs a
malformed upload.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from aqelyn.conventions import ActorRef, new_id
from aqelyn.events import Subject
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.findings.models import Finding
from aqelyn.kernel.factory import Runtime
from aqelyn.reporting.posture import (
    PostureDocumentError,
    ensure_posture_object_type,
    observation_to_finding,
    subject_object,
    validate_posture_shape,
)

# A valid, fixed src_ id for portal uploads (distinct from the report path's source).
PORTAL_SOURCE_ID = "src_019fa1f100007a119000000000000002"


class UploadRefused(Exception):
    """The uploaded posture document was refused; ``message`` locates why."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def ingest_posture_document(
    runtime: Runtime,
    document: Mapping[str, Any],
    *,
    tenant_id: str,
    digest: str,
    observed_at: datetime,
    actor: ActorRef,
) -> list[Finding]:
    """Validate and ingest a posture document into ``tenant_id``; return the findings raised."""

    try:
        observations = validate_posture_shape(document)
    except PostureDocumentError as exc:
        raise UploadRefused(str(exc)) from exc

    object_store = runtime.object_store
    evidence_store = runtime.evidence_store
    finding_store = runtime.finding_store
    ensure_posture_object_type(object_store)

    raised: list[Finding] = []
    for observation in observations:
        subject = subject_object(
            observation,
            source_id=PORTAL_SOURCE_ID,
            observed_at=observed_at,
            actor=actor,
        ).model_copy(update={"tenant_id": tenant_id})
        subject_id = (await object_store.upsert(subject)).id
        evidence = await evidence_store.add(
            EvidenceRecord(
                id="",
                evidence_type="posture.observation",
                schema_version=1,
                tenant_id=tenant_id,
                subject=Subject(object_ids=[subject_id]),
                collected_at=observed_at,
                recorded_at=observed_at,
                collector=actor,
                source_id=PORTAL_SOURCE_ID,
                method=str(observation.get("check", "posture observation")),
                content={
                    "sha256": digest,
                    "observation_id": str(observation.get("observation_id", "")),
                },
                content_hash="",
                confidence=1.0,
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        finding = observation_to_finding(
            observation,
            finding_id=new_id("fnd"),
            evidence_id=evidence.id,
            observed_at=observed_at,
            affected_object_ids=[subject_id],
        ).model_copy(update={"tenant_id": tenant_id})
        raised.append(await finding_store.raise_finding(finding))

    raised.sort(key=lambda item: (-item.severity_score, item.id))
    return raised
