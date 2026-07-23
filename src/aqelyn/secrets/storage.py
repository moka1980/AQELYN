"""Metadata-only storage-safety classification (C-032 J3)."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.secrets.models import (
    CertificateAsset,
    CryptoAsset,
    CryptoConfig,
    CryptographicKey,
    SecretAsset,
    StorageLocationKind,
    StorageSafetyClassification,
)


def classify_storage_safety(
    asset: CryptoAsset,
    *,
    approved_location_prefixes: Sequence[str],
) -> StorageSafetyClassification:
    validated_prefixes = CryptoConfig(
        approved_storage_location_prefixes=list(approved_location_prefixes)
    ).approved_storage_location_prefixes
    location_kind, location_ref = _location_metadata(asset)
    if isinstance(asset, SecretAsset) and asset.location.kind in {
        "repository",
        "configuration",
    }:
        return StorageSafetyClassification(
            asset_id=asset.id,
            status="unsafe",
            location_kind=location_kind,
            location_ref=location_ref,
            evidence_id=asset.evidence_id,
            reason=(f"EA-0032 classifies {asset.location.kind} storage as unsafe for secrets."),
            flagged=True,
        )

    matched = _matched_prefix(location_ref, validated_prefixes)
    eligible_for_approval = isinstance(asset, CryptographicKey) or (
        isinstance(asset, SecretAsset) and asset.location.kind == "vault_reference"
    )
    if matched is not None and eligible_for_approval:
        return StorageSafetyClassification(
            asset_id=asset.id,
            status="approved",
            location_kind=location_kind,
            location_ref=location_ref,
            matched_policy_prefix=matched,
            evidence_id=asset.evidence_id,
            reason="The metadata-only location matches an explicitly approved storage prefix.",
            flagged=False,
        )

    reason = (
        "Certificates do not report a storage location in the EA-0032 asset model."
        if isinstance(asset, CertificateAsset)
        else "The metadata-only location does not establish approved or unsafe storage."
    )
    return StorageSafetyClassification(
        asset_id=asset.id,
        status="unknown",
        location_kind=location_kind,
        location_ref=location_ref,
        evidence_id=asset.evidence_id,
        reason=reason,
        flagged=True,
    )


def _location_metadata(asset: CryptoAsset) -> tuple[StorageLocationKind, str | None]:
    if isinstance(asset, SecretAsset):
        return asset.location.kind, asset.location.resource_ref
    if isinstance(asset, CryptographicKey):
        return "external_key_reference", asset.external_key_ref
    return "unreported", None


def _matched_prefix(location_ref: str | None, prefixes: Sequence[str]) -> str | None:
    if location_ref is None:
        return None
    matches = [prefix for prefix in prefixes if location_ref.startswith(prefix)]
    return min(matches, key=lambda value: (-len(value), value)) if matches else None
