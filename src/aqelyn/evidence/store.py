"""EvidenceStore + BlobStore protocols and chain helpers (EA-0004 §8)."""

from __future__ import annotations

from typing import Any, Protocol

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id, sha256_hex
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


def validate_evidence_id(value: str, *, field: str = "evidence_id") -> str:
    return require_typed_id(value, "evd", field=field)


def validate_package_id(value: str, *, field: str = "package_id") -> str:
    return require_typed_id(value, "pkg", field=field)


def validate_evidence_ids(values: list[str]) -> None:
    for value in values:
        validate_evidence_id(value, field="evidence_ids")


def validate_chain_tenant(tenant_id: str | None) -> None:
    require_tenant_id(tenant_id)


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
