"""C-032 J3 acceptance tests for metadata-only storage safety."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import CryptoConfigInvalid, SecretValueRejected
from aqelyn.secrets import (
    CertificateAsset,
    CryptoConfig,
    CryptographicKey,
    Lifecycle,
    SecretAsset,
    SecretLocation,
    StorageSafetyClassification,
    classify_storage_safety,
)

NOW = datetime(2026, 7, 22, 18, 0, tzinfo=UTC)
EVIDENCE_ID = new_id("evd")
SOURCE_ID = new_id("src")


def _unknown(reason: str) -> Lifecycle:
    return Lifecycle(status="unknown", reason=reason)


def _secret(*, kind: str, resource_ref: str) -> SecretAsset:
    object_id = new_id("obj")
    return SecretAsset(
        tenant_id=None,
        object_id=object_id,
        inventory_ref=f"ast_{object_id.split('_', 1)[1]}",
        kind="api_key",
        fingerprint=f"hmac-sha256:{701:064x}",
        location=SecretLocation.model_validate({"kind": kind, "resource_ref": resource_ref}),
        rotation=_unknown("Rotation was not reported."),
        claim_confidence=1.0,
        source_id=SOURCE_ID,
        detected_at=NOW,
        evidence_id=EVIDENCE_ID,
    )


def _key(*, external_key_ref: str) -> CryptographicKey:
    object_id = new_id("obj")
    return CryptographicKey(
        tenant_id=None,
        object_id=object_id,
        inventory_ref=f"ast_{object_id.split('_', 1)[1]}",
        external_key_ref=external_key_ref,
        fingerprint=f"hmac-sha256:{702:064x}",
        algorithm="rsa",
        key_size=4096,
        usages=["signing"],
        last_rotated_at=NOW,
        strength=_unknown("Strength was not assessed."),
        rotation=_unknown("Rotation was not assessed."),
        claim_confidence=1.0,
        source_id=SOURCE_ID,
        observed_at=NOW,
        evidence_id=EVIDENCE_ID,
    )


def _certificate() -> CertificateAsset:
    object_id = new_id("obj")
    unknown = _unknown("Not assessed.")
    return CertificateAsset(
        tenant_id=None,
        object_id=object_id,
        inventory_ref=f"ast_{object_id.split('_', 1)[1]}",
        fingerprint=f"hmac-sha256:{703:064x}",
        serial="01",
        subject="CN=service.example.test",
        issuer="CN=issuer.example.test",
        not_after=None,
        expiry=unknown,
        chain=unknown,
        revocation=unknown,
        integrity=unknown,
        authenticity=unknown,
        claim_confidence=1.0,
        source_id=SOURCE_ID,
        observed_at=NOW,
        evidence_id=EVIDENCE_ID,
    )


def test_crypto_location_classification() -> None:
    prefixes = ["vault://approved/", "arn:aws:kms:"]

    repository = classify_storage_safety(
        _secret(kind="repository", resource_ref="repo://billing/config"),
        approved_location_prefixes=prefixes,
    )
    vault = classify_storage_safety(
        _secret(kind="vault_reference", resource_ref="vault://approved/payments/api"),
        approved_location_prefixes=prefixes,
    )
    kms = classify_storage_safety(
        _key(external_key_ref="arn:aws:kms:eu-north-1:111122223333:key/abc"),
        approved_location_prefixes=prefixes,
    )

    assert repository.status == "unsafe"
    assert repository.flagged
    assert vault.status == "approved"
    assert vault.matched_policy_prefix == "vault://approved/"
    assert not vault.flagged
    assert kms.status == "approved"
    assert kms.matched_policy_prefix == "arn:aws:kms:"


def test_crypto_location_unknown_not_approved() -> None:
    unconfigured_vault = classify_storage_safety(
        _secret(kind="vault_reference", resource_ref="vault://unconfigured/payments/api"),
        approved_location_prefixes=[],
    )
    certificate = classify_storage_safety(
        _certificate(),
        approved_location_prefixes=["vault://approved/"],
    )

    assert CryptoConfig().approved_storage_location_prefixes == []
    assert unconfigured_vault.status == "unknown"
    assert unconfigured_vault.flagged
    assert unconfigured_vault.matched_policy_prefix is None
    assert certificate.status == "unknown"
    assert certificate.location_kind == "unreported"
    assert certificate.location_ref is None

    with pytest.raises(CryptoConfigInvalid, match="matched policy prefix"):
        StorageSafetyClassification(
            asset_id=unconfigured_vault.asset_id,
            status="approved",
            location_kind="vault_reference",
            location_ref="vault://unconfigured/payments/api",
            evidence_id=EVIDENCE_ID,
            reason="No policy matched.",
            flagged=False,
        )
    with pytest.raises(CryptoConfigInvalid, match="must end"):
        classify_storage_safety(
            _key(external_key_ref="vault://approved-evil/key"),
            approved_location_prefixes=["vault://approved"],
        )
    with pytest.raises(CryptoConfigInvalid, match="must be flagged"):
        StorageSafetyClassification.model_validate(
            {**unconfigured_vault.model_dump(), "flagged": False}
        )
    with pytest.raises(SecretValueRejected):
        StorageSafetyClassification.model_validate(
            {
                **unconfigured_vault.model_dump(),
                "raw_value": "must-never-enter-the-model",
            }
        )
