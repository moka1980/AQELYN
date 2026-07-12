"""EvidenceStore + BlobStore protocols and chain helpers (EA-0004 §8)."""

from __future__ import annotations

from typing import Any, Protocol

from aqelyn.conventions import ActorRef, sha256_hex
from aqelyn.evidence.models import (
    BlobRef,
    EvidencePackage,
    EvidenceRecord,
    VerifyResult,
)


def compute_record_hash(record: dict[str, Any], prev_hash: str | None) -> str:
    """record_hash = sha256(canonical(record without record_hash) || prev_hash)."""
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return sha256_hex({"body": body, "prev": prev_hash})


class BlobStore(Protocol):
    async def put(self, data: bytes, *, media_type: str) -> BlobRef: ...
    async def get(self, ref: BlobRef) -> bytes: ...


class EvidenceStore(Protocol):
    async def add(self, record: EvidenceRecord) -> EvidenceRecord: ...
    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord: ...
    async def verify(self, evidence_id: str) -> VerifyResult: ...
    async def verify_chain(
        self, *, tenant_id: str | None, from_seq: int = 0, to_seq: int | None = None
    ) -> VerifyResult: ...
    async def package(
        self, evidence_ids: list[str], *, by: ActorRef, reason: str
    ) -> EvidencePackage: ...
    async def verify_package(self, package_id: str) -> VerifyResult: ...
