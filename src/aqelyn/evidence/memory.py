"""In-memory EvidenceStore + BlobStore (EA-0004). Reference implementation."""

from __future__ import annotations

import hashlib
from typing import Any

from aqelyn.conventions import ActorRef, new_id, sha256_hex, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    EvidenceNotFound,
    EvidenceTampered,
)
from aqelyn.events import Event, EventBus, Subject
from aqelyn.evidence.models import (
    BlobRef,
    EvidencePackage,
    EvidenceRecord,
    VerifyResult,
)
from aqelyn.evidence.store import (
    compute_record_hash,
    validate_chain_tenant,
    validate_evidence_id,
    validate_evidence_ids,
    validate_package_id,
)


class InMemoryBlobStore:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def put(self, data: bytes, *, media_type: str) -> BlobRef:
        h = hashlib.sha256(data).hexdigest()
        self._blobs[h] = data
        return BlobRef(hash=h, size_bytes=len(data), media_type=media_type, uri=f"mem://{h}")

    async def get(self, ref: BlobRef) -> bytes:
        data = self._blobs.get(ref.hash)
        if data is None or hashlib.sha256(data).hexdigest() != ref.hash:
            raise EvidenceTampered("blob missing or integrity check failed")
        return data


class InMemoryEvidenceStore:
    def __init__(self, *, mode: str = "local", event_bus: EventBus | None = None) -> None:
        self._by_id: dict[str, EvidenceRecord] = {}
        self._chains: dict[str | None, list[EvidenceRecord]] = {}
        self._custody: list[dict[str, Any]] = []
        self._packages: dict[str, EvidencePackage] = {}
        self.mode = mode
        self._bus = event_bus

    def _content_hash(self, record: EvidenceRecord) -> str:
        return sha256_hex(record.content if record.content is not None else record.content_ref)

    async def add(self, record: EvidenceRecord) -> EvidenceRecord:
        chain = self._chains.setdefault(record.tenant_id, [])
        seq = len(chain) + 1
        prev_hash = chain[-1].record_hash if chain else None
        content_hash = self._content_hash(record)
        base = record.model_copy(
            update={
                "id": record.id or new_id("evd"),
                "seq": seq,
                "prev_hash": prev_hash,
                "content_hash": content_hash,
                "recorded_at": utc_now(),
                "record_hash": "",
            }
        )
        rec = base.model_copy(
            update={"record_hash": compute_record_hash(base.model_dump(mode="json"), prev_hash)}
        )
        chain.append(rec)
        self._by_id[rec.id] = rec
        if self._bus is not None:
            await self._emit(rec)
        return rec

    async def _emit(self, rec: EvidenceRecord) -> None:
        assert self._bus is not None
        now = utc_now()
        await self._bus.publish(
            Event(
                id=new_id("evt"),
                event_type="aqelyn.evidence.recorded",
                schema_version=1,
                tenant_id=rec.tenant_id,
                occurred_at=rec.collected_at,
                recorded_at=now,
                producer=rec.collector,
                subject=Subject(object_ids=rec.subject.object_ids, evidence_id=rec.id),
                payload={"evidence_type": rec.evidence_type, "source_id": rec.source_id},
                partition_key=rec.subject.object_ids[0] if rec.subject.object_ids else rec.id,
            )
        )

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        validate_evidence_id(evidence_id)
        rec = self._by_id.get(evidence_id)
        if rec is None:
            raise EvidenceNotFound(evidence_id)
        self._custody.append(
            {
                "evidence_id": evidence_id,
                "action": "read",
                "actor": actor.model_dump(),
                "at": utc_now().isoformat(),
            }
        )
        return rec

    async def exists(self, evidence_id: str) -> bool:
        validate_evidence_id(evidence_id)
        return evidence_id in self._by_id

    def custody_of(self, evidence_id: str) -> list[dict[str, Any]]:
        return [c for c in self._custody if c["evidence_id"] == evidence_id]

    async def verify(self, evidence_id: str) -> VerifyResult:
        validate_evidence_id(evidence_id)
        rec = self._by_id.get(evidence_id)
        if rec is None:
            raise EvidenceNotFound(evidence_id)
        if self._content_hash(rec) != rec.content_hash:
            return VerifyResult(ok=False, broken_at_seq=rec.seq, detail="content hash mismatch")
        expected = compute_record_hash(
            rec.model_copy(update={"record_hash": ""}).model_dump(mode="json"), rec.prev_hash
        )
        if expected != rec.record_hash:
            return VerifyResult(ok=False, broken_at_seq=rec.seq, detail="record hash mismatch")
        return VerifyResult(ok=True)

    async def verify_chain(
        self, *, tenant_id: str | None, from_seq: int = 0, to_seq: int | None = None
    ) -> VerifyResult:
        validate_chain_tenant(tenant_id)
        chain = self._chains.get(tenant_id, [])
        prev: str | None = None
        for rec in chain:
            if rec.seq <= from_seq:
                prev = rec.record_hash
                continue
            if to_seq is not None and rec.seq > to_seq:
                break
            if rec.prev_hash != prev:
                return VerifyResult(ok=False, broken_at_seq=rec.seq, detail="prev_hash mismatch")
            res = await self.verify(rec.id)
            if not res.ok:
                return res
            prev = rec.record_hash
        return VerifyResult(ok=True)

    async def package(
        self, evidence_ids: list[str], *, by: ActorRef, reason: str
    ) -> EvidencePackage:
        validate_evidence_ids(evidence_ids)
        tenant: str | None = None
        hashes: list[str] = []
        for eid in evidence_ids:
            rec = self._by_id.get(eid)
            if rec is None:
                raise EvidenceNotFound(eid)
            if hashes and rec.tenant_id != tenant:
                raise CrossTenantReference("package spans tenants")
            tenant = rec.tenant_id
            hashes.append(rec.record_hash)
        manifest_hash = sha256_hex({"evidence": sorted(hashes), "reason": reason})
        now = utc_now()
        pkg = EvidencePackage(
            id=new_id("pkg"),
            tenant_id=tenant,
            evidence_ids=list(evidence_ids),
            manifest_hash=manifest_hash,
            package_hash=sha256_hex(
                {"m": manifest_hash, "by": by.model_dump(), "at": now.isoformat()}
            ),
            created_by=by,
            created_at=now,
            reason=reason,
        )
        self._packages[pkg.id] = pkg
        for eid in evidence_ids:
            self._custody.append(
                {
                    "evidence_id": eid,
                    "action": "package",
                    "actor": by.model_dump(),
                    "at": now.isoformat(),
                }
            )
        return pkg

    async def verify_package(self, package_id: str) -> VerifyResult:
        validate_package_id(package_id)
        pkg = self._packages.get(package_id)
        if pkg is None:
            raise EvidenceNotFound(package_id)
        hashes: list[str] = []
        for eid in pkg.evidence_ids:
            res = await self.verify(eid)
            if not res.ok:
                return res
            hashes.append(self._by_id[eid].record_hash)
        manifest_hash = sha256_hex({"evidence": sorted(hashes), "reason": pkg.reason})
        if manifest_hash != pkg.manifest_hash:
            return VerifyResult(ok=False, detail="manifest hash mismatch")
        return VerifyResult(ok=True)
