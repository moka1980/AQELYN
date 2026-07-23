"""Evidence-first crypto ingest and Trust reconciliation (EA-0032 W2)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    CryptoConfigInvalid,
    EvidenceTampered,
    StoreUnavailable,
)
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.inventory import AssetRecord, DiscoverySource, Ownership
from aqelyn.objects import AQObject, NaturalKey, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.secrets.models import (
    CertificateAsset,
    CertificateClaim,
    CertificateDescriptor,
    CredentialOwnershipClaim,
    CryptoAsset,
    CryptoAssetKind,
    CryptoClaim,
    CryptoClaimConflict,
    CryptoClaimField,
    CryptoConflictCandidate,
    CryptographicKey,
    CryptographicKeyDescriptor,
    KeyClaim,
    Lifecycle,
    SecretAsset,
    SecretClaim,
    SecretScanDescriptor,
)
from aqelyn.trust import TrustAssessment

CRYPTO_OBJECT_TYPES: dict[CryptoAssetKind, str] = {
    "secret": "secret_asset",
    "key": "cryptographic_key",
    "certificate": "x509_certificate",
}


class TrustAssessor(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


class CryptoInventoryOwner(Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, object]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...

    async def reconcile(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord: ...

    async def ownership(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> Ownership | None: ...


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


@dataclass(frozen=True)
class PreparedDescriptor:
    descriptor: SecretScanDescriptor | CryptographicKeyDescriptor | CertificateDescriptor
    evidence: EvidenceRecord
    confidence: float
    ownership_evidence: EvidenceRecord | None
    ownership_confidence: float | None


def ensure_crypto_object_types(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        for object_type in CRYPTO_OBJECT_TYPES.values():
            registry.register(object_type, 1, None)
        return
    if registry is not None:
        selected = cast(_ObjectStoreRegistry, object_store)
        for object_type in CRYPTO_OBJECT_TYPES.values():
            selected.registry.register(object_type, 1, None)


async def prepare_descriptor(
    descriptor: SecretScanDescriptor | CryptographicKeyDescriptor | CertificateDescriptor,
    *,
    evidence_store: EvidenceStore,
    trust: TrustAssessor,
    actor: ActorRef,
    tenant_id: str | None,
) -> PreparedDescriptor:
    if descriptor.tenant_id != tenant_id:
        raise CrossTenantReference("crypto descriptor tenant does not match request tenant")
    evidence = await evidence_store.get(descriptor.evidence_id, actor=actor)
    verification = await evidence_store.verify(descriptor.evidence_id)
    if evidence.tenant_id != tenant_id:
        raise CrossTenantReference("crypto evidence tenant does not match descriptor")
    if evidence.source_id != descriptor.source_id:
        raise CryptoConfigInvalid("crypto evidence source does not match descriptor source")
    if not verification.ok:
        detail = verification.detail or "integrity verification failed"
        raise EvidenceTampered(
            f"crypto descriptor evidence failed integrity verification: {detail}",
            details={
                "evidence_id": descriptor.evidence_id,
                "verification_detail": detail,
            },
        )
    if evidence.content is None or evidence.content.get("fingerprint") != descriptor.fingerprint:
        raise CryptoConfigInvalid(
            "crypto evidence fingerprint does not match descriptor fingerprint"
        )
    assessment = await trust.assess(
        f"crypto:{descriptor.fingerprint}",
        [evidence],
        now=descriptor.observed_at,
    )
    ownership_evidence: EvidenceRecord | None = None
    ownership_confidence: float | None = None
    if descriptor.ownership is not None:
        ownership_evidence = await evidence_store.get(
            descriptor.ownership.evidence_id,
            actor=actor,
        )
        ownership_verification = await evidence_store.verify(descriptor.ownership.evidence_id)
        if ownership_evidence.tenant_id != tenant_id:
            raise CrossTenantReference(
                "credential ownership evidence tenant does not match descriptor"
            )
        if ownership_evidence.source_id != descriptor.ownership.source_id:
            raise CryptoConfigInvalid(
                "credential ownership evidence source does not match the claim"
            )
        if not ownership_verification.ok:
            detail = ownership_verification.detail or "integrity verification failed"
            raise EvidenceTampered(
                f"credential ownership evidence failed integrity verification: {detail}",
                details={
                    "evidence_id": descriptor.ownership.evidence_id,
                    "verification_detail": detail,
                },
            )
        if (
            ownership_evidence.content is None
            or ownership_evidence.content.get("fingerprint") != descriptor.fingerprint
        ):
            raise CryptoConfigInvalid(
                "credential ownership evidence fingerprint does not match the descriptor"
            )
        ownership_assessment = await trust.assess(
            f"crypto-ownership:{descriptor.fingerprint}",
            [ownership_evidence],
            now=descriptor.ownership.observed_at,
        )
        ownership_confidence = ownership_assessment.score
    return PreparedDescriptor(
        descriptor=descriptor,
        evidence=evidence,
        confidence=assessment.score,
        ownership_evidence=ownership_evidence,
        ownership_confidence=ownership_confidence,
    )


def new_asset(prepared: PreparedDescriptor) -> CryptoAsset:
    descriptor = prepared.descriptor
    object_id = new_id("obj")
    inventory_id = inventory_ref(object_id)
    unknown_rotation = Lifecycle(reason="Rotation has not yet been assessed.")
    if isinstance(descriptor, SecretScanDescriptor):
        return SecretAsset(
            tenant_id=descriptor.tenant_id,
            object_id=object_id,
            inventory_ref=inventory_id,
            kind=descriptor.kind,
            fingerprint=descriptor.fingerprint,
            location=descriptor.location.model_copy(deep=True),
            rotation=unknown_rotation,
            claim_confidence=prepared.confidence,
            source_id=descriptor.source_id,
            detected_at=descriptor.observed_at,
            evidence_id=descriptor.evidence_id,
        )
    if isinstance(descriptor, CryptographicKeyDescriptor):
        return CryptographicKey(
            tenant_id=descriptor.tenant_id,
            object_id=object_id,
            inventory_ref=inventory_id,
            external_key_ref=descriptor.external_key_ref,
            fingerprint=descriptor.fingerprint,
            algorithm=descriptor.algorithm,
            key_size=descriptor.key_size,
            usages=list(descriptor.usages),
            last_rotated_at=descriptor.last_rotated_at,
            strength=Lifecycle(reason="Key strength has not yet been assessed."),
            rotation=unknown_rotation,
            claim_confidence=prepared.confidence,
            source_id=descriptor.source_id,
            observed_at=descriptor.observed_at,
            evidence_id=descriptor.evidence_id,
        )
    return CertificateAsset(
        tenant_id=descriptor.tenant_id,
        object_id=object_id,
        inventory_ref=inventory_id,
        fingerprint=descriptor.fingerprint,
        serial=descriptor.serial,
        subject=descriptor.subject,
        issuer=descriptor.issuer,
        not_after=descriptor.not_after,
        expiry=Lifecycle(reason="Certificate expiry has not yet been assessed."),
        chain=Lifecycle(reason="Certificate chain has not yet been assessed."),
        revocation=Lifecycle(reason="Certificate revocation has not yet been assessed."),
        integrity=Lifecycle(reason="Certificate integrity has not yet been assessed."),
        authenticity=Lifecycle(reason="Certificate authenticity has not yet been assessed."),
        claim_confidence=prepared.confidence,
        source_id=descriptor.source_id,
        observed_at=descriptor.observed_at,
        evidence_id=descriptor.evidence_id,
    )


def reconcile_asset(existing: CryptoAsset, incoming: CryptoAsset) -> CryptoAsset:
    if type(existing) is not type(incoming):
        raise StoreUnavailable("crypto fingerprint resolved to a different asset kind")
    old_claim = _claim(existing)
    new_claim = _claim(incoming)
    old_candidate = _candidate(existing, old_claim)
    new_candidate = _candidate(incoming, new_claim)
    if old_claim.model_dump(mode="json") == new_claim.model_dump(mode="json"):
        winner = max((existing, incoming), key=_winner_key)
        return _stable_asset(winner, existing=existing, conflicts=existing.conflicts)

    changed = cast(
        list[CryptoClaimField],
        sorted(
            field
            for field in type(old_claim).model_fields
            if field != "asset_kind"
            and old_claim.model_dump(mode="json").get(field)
            != new_claim.model_dump(mode="json").get(field)
        ),
    )
    candidates = sorted(
        (old_candidate, new_candidate),
        key=lambda item: (item.source_id, item.evidence_id, item.observed_at),
    )
    if existing.claim_confidence != incoming.claim_confidence:
        winner = existing if existing.claim_confidence > incoming.claim_confidence else incoming
        winner_candidate = old_candidate if winner is existing else new_candidate
        conflict = CryptoClaimConflict(
            fields=changed,
            candidates=candidates,
            resolved_by=winner_candidate.source_id,
            resolved_evidence_id=winner_candidate.evidence_id,
            unresolved=False,
            reason="higher EA-0006 Trust confidence",
        )
    else:
        winner = max((existing, incoming), key=_winner_key)
        conflict = CryptoClaimConflict(
            fields=changed,
            candidates=candidates,
            unresolved=True,
            reason=(
                "equal EA-0006 Trust confidence; a deterministic claim is retained "
                "while the conflict remains unresolved"
            ),
        )
    conflicts = _append_conflict(existing.conflicts, conflict)
    return _stable_asset(winner, existing=existing, conflicts=conflicts)


def crypto_object(asset: CryptoAsset, *, actor: ActorRef) -> AQObject:
    kind = crypto_asset_kind(asset)
    observed_at = asset_observed_at(asset)
    attributes: dict[str, object] = {
        "fingerprint": asset.fingerprint,
        "asset_kind": kind,
        "conflict_count": len(asset.conflicts),
        "unresolved_conflict": any(conflict.unresolved for conflict in asset.conflicts),
    }
    if isinstance(asset, SecretAsset):
        attributes.update(
            {
                "secret_kind": asset.kind,
                "location": asset.location.model_dump(mode="json"),
                "classification": asset.classification,
            }
        )
    elif isinstance(asset, CryptographicKey):
        attributes.update(
            {
                "external_key_ref": asset.external_key_ref,
                "algorithm": asset.algorithm,
                "key_size": asset.key_size,
                "usages": list(asset.usages),
                "last_rotated_at": (
                    None if asset.last_rotated_at is None else asset.last_rotated_at.isoformat()
                ),
            }
        )
    else:
        attributes.update(
            {
                "serial": asset.serial,
                "subject": asset.subject,
                "issuer": asset.issuer,
                "not_after": None if asset.not_after is None else asset.not_after.isoformat(),
            }
        )
    return AQObject(
        id=asset.object_id,
        object_type=CRYPTO_OBJECT_TYPES[kind],
        schema_version=1,
        tenant_id=asset.tenant_id,
        display_name=f"{kind}:{asset.fingerprint[-12:]}",
        attributes=attributes,
        labels={"module": "EA-0032", "kind": kind},
        natural_keys=[NaturalKey(namespace=f"crypto:{kind}:fingerprint", value=asset.fingerprint)],
        sources=[
            SourceRef(
                source_id=asset.source_id,
                evidence_id=asset.evidence_id,
                observed_at=observed_at,
                method="secrets.handed_in_descriptor/v1",
            )
        ],
        confidence=asset.claim_confidence,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        created_at=observed_at,
        updated_at=observed_at,
        created_by=actor,
        updated_by=actor,
    )


def inventory_report(
    asset: CryptoAsset,
    *,
    evidence_id: str,
    owner: Ownership | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "id": asset.inventory_ref,
        "asset_type": CRYPTO_OBJECT_TYPES[crypto_asset_kind(asset)],
        "classification": "secret" if isinstance(asset, SecretAsset) else "cryptographic",
        "lifecycle_state": "active",
        "evidence_id": evidence_id,
        "ref": f"secrets:{crypto_asset_kind(asset)}:{asset.fingerprint}",
    }
    if owner is not None:
        report["owner"] = owner.model_dump(mode="json")
    return report


def inventory_ownership(claim: CredentialOwnershipClaim) -> Ownership:
    return Ownership(
        business_owner=claim.business_owner,
        technical_owner=claim.technical_owner,
        custodian=claim.custodian,
        rationale=claim.rationale,
        source_id=claim.source_id,
        evidence_id=claim.evidence_id,
        observed_at=claim.observed_at,
    )


def inventory_ref(object_id: str) -> str:
    prefix, payload = parse_id(object_id)
    if prefix != "obj":
        raise StoreUnavailable("EA-0002 crypto object id must use obj_ prefix")
    return f"ast_{payload}"


def asset_observed_at(asset: CryptoAsset) -> datetime:
    if isinstance(asset, SecretAsset):
        return asset.detected_at
    return asset.observed_at


def crypto_asset_kind(asset: CryptoAsset) -> CryptoAssetKind:
    if isinstance(asset, SecretAsset):
        return "secret"
    if isinstance(asset, CryptographicKey):
        return "key"
    return "certificate"


def with_owner_identity(asset: CryptoAsset, object_id: str) -> CryptoAsset:
    return asset.model_copy(
        update={"object_id": object_id, "inventory_ref": inventory_ref(object_id)},
        deep=True,
    )


def _claim(asset: CryptoAsset) -> CryptoClaim:
    if isinstance(asset, SecretAsset):
        return SecretClaim(kind=asset.kind, location=asset.location.model_copy(deep=True))
    if isinstance(asset, CryptographicKey):
        return KeyClaim(
            external_key_ref=asset.external_key_ref,
            algorithm=asset.algorithm,
            key_size=asset.key_size,
            usages=list(asset.usages),
            last_rotated_at=asset.last_rotated_at,
        )
    return CertificateClaim(
        serial=asset.serial,
        subject=asset.subject,
        issuer=asset.issuer,
        not_after=asset.not_after,
    )


def _candidate(asset: CryptoAsset, claim: CryptoClaim) -> CryptoConflictCandidate:
    return CryptoConflictCandidate(
        source_id=asset.source_id,
        evidence_id=asset.evidence_id,
        observed_at=asset_observed_at(asset),
        reliability=asset.claim_confidence,
        claim=claim,
    )


def _winner_key(asset: CryptoAsset) -> tuple[float, datetime, str, str]:
    return (
        asset.claim_confidence,
        asset_observed_at(asset),
        asset.source_id,
        asset.evidence_id,
    )


def _stable_asset(
    selected: CryptoAsset,
    *,
    existing: CryptoAsset,
    conflicts: Sequence[CryptoClaimConflict],
) -> CryptoAsset:
    return selected.model_copy(
        update={
            "id": existing.id,
            "tenant_id": existing.tenant_id,
            "object_id": existing.object_id,
            "inventory_ref": existing.inventory_ref,
            "conflicts": [item.model_copy(deep=True) for item in conflicts],
        },
        deep=True,
    )


def _append_conflict(
    existing: Sequence[CryptoClaimConflict],
    incoming: CryptoClaimConflict,
) -> list[CryptoClaimConflict]:
    selected = [item.model_copy(deep=True) for item in existing]
    incoming_key = json.dumps(incoming.model_dump(mode="json"), sort_keys=True)
    if all(
        json.dumps(item.model_dump(mode="json"), sort_keys=True) != incoming_key
        for item in selected
    ):
        selected.append(incoming.model_copy(deep=True))
    return selected
