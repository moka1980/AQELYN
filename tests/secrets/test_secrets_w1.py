"""C-029 W1 acceptance tests for secrets/crypto types and structural gates."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import aqelyn.secrets as secrets
from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, is_valid, new_id
from aqelyn.conventions.errors import (
    CertificateNotFound,
    CryptoAssetNotFound,
    CryptoConfigInvalid,
    SchemaValidationError,
    SecretValueRejected,
)
from aqelyn.exposure.models import VALID_ASSET_KINDS, ExposureImpactContext
from aqelyn.secrets import (
    VALID_ASSESSMENT_STATUSES,
    VALID_CRYPTO_ASSET_KINDS,
    VALID_KEY_USAGES,
    VALID_LIFECYCLE_STATUSES,
    VALID_SECRET_KINDS,
    VALID_SECRET_LOCATION_KINDS,
    AuthenticityCheck,
    CertificateAsset,
    CertificateDescriptor,
    CryptoAssessment,
    CryptoConfig,
    CryptographicExposure,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoQuery,
    CryptoScope,
    Lifecycle,
    SecretAsset,
    SecretLocation,
    SecretScanDescriptor,
)

NOW = datetime(2026, 7, 20, 20, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000320001"
FINGERPRINT = "hmac-sha256:" + "a" * 64


def _location(**overrides: object) -> SecretLocation:
    data: dict[str, object] = {
        "kind": "repository",
        "resource_ref": "https://git.example.test/security/repository",
        "path_hint": "deploy/production.env",
        "line": 41,
    }
    data.update(overrides)
    return SecretLocation.model_validate(data)


def _unknown(reason: str = "The source did not report this lifecycle fact.") -> Lifecycle:
    return Lifecycle(reason=reason)


def _known(status: str = "valid") -> Lifecycle:
    return Lifecycle(
        status=status,
        source_ref="claim:crypto-policy:v1",
        evidence_id=new_id("evd"),
        reason="The evidenced policy check completed.",
    )


def _secret_descriptor(**overrides: object) -> SecretScanDescriptor:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "kind": "private_key",
        "fingerprint": FINGERPRINT,
        "location": _location(),
        "source_id": new_id("src"),
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return SecretScanDescriptor.model_validate(data)


def _key_descriptor(**overrides: object) -> CryptographicKeyDescriptor:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "external_key_ref": "arn:aws:kms:eu-north-1:123456789012:key/alias-signing",
        "fingerprint": FINGERPRINT,
        "algorithm": "rsa",
        "key_size": 3072,
        "usages": ["signing"],
        "last_rotated_at": NOW,
        "source_id": new_id("src"),
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return CryptographicKeyDescriptor.model_validate(data)


def _certificate_descriptor(**overrides: object) -> CertificateDescriptor:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "fingerprint": FINGERPRINT,
        "serial": "01:23:45:67:89",
        "subject": "CN=api.example.test",
        "issuer": "CN=AQELYN Test CA",
        "not_after": NOW,
        "source_id": new_id("src"),
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return CertificateDescriptor.model_validate(data)


def _secret_asset(**overrides: object) -> SecretAsset:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "object_id": new_id("obj"),
        "inventory_ref": new_id("ast"),
        "kind": "private_key",
        "fingerprint": FINGERPRINT,
        "location": _location(),
        "rotation": _unknown(),
        "claim_confidence": 0.8,
        "source_id": new_id("src"),
        "detected_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return SecretAsset.model_validate(data)


def _key_asset(**overrides: object) -> CryptographicKey:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "object_id": new_id("obj"),
        "inventory_ref": new_id("ast"),
        "external_key_ref": "urn:aqelyn:key:signing-2026",
        "fingerprint": FINGERPRINT,
        "algorithm": "rsa",
        "key_size": 3072,
        "usages": ["signing"],
        "strength": _known(),
        "rotation": _unknown(),
        "claim_confidence": 0.9,
        "source_id": new_id("src"),
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return CryptographicKey.model_validate(data)


def _certificate_asset(**overrides: object) -> CertificateAsset:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "object_id": new_id("obj"),
        "inventory_ref": new_id("ast"),
        "fingerprint": FINGERPRINT,
        "serial": "01:23:45:67:89",
        "subject": "CN=api.example.test",
        "issuer": "CN=AQELYN Test CA",
        "not_after": NOW,
        "expiry": _known(),
        "chain": _unknown(),
        "revocation": _unknown(),
        "integrity": _known(),
        "authenticity": _unknown(),
        "claim_confidence": 0.85,
        "source_id": new_id("src"),
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return CertificateAsset.model_validate(data)


def _assessment(**overrides: object) -> CryptoAssessment:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "run_at": NOW,
        "scope": CryptoScope(),
        "status": "pending",
    }
    data.update(overrides)
    return CryptoAssessment.model_validate(data)


def _crypto_exposure(impact_context: ExposureImpactContext) -> CryptographicExposure:
    return CryptographicExposure(
        id="crypto-exposure:private-key:repository",
        tenant_id=TENANT,
        asset_id=new_id("sct"),
        surface_ref=new_id("ast"),
        object_id=new_id("obj"),
        status="reachability_pending",
        impact_context=impact_context,
        reason="Reachability has not been established.",
        evidence_id=impact_context.evidence_id,
    )


def _model_payloads() -> list[tuple[type[BaseModel], dict[str, Any]]]:
    return [
        (SecretScanDescriptor, _secret_descriptor().model_dump()),
        (CryptographicKeyDescriptor, _key_descriptor().model_dump()),
        (CertificateDescriptor, _certificate_descriptor().model_dump()),
        (SecretAsset, _secret_asset().model_dump()),
        (CryptographicKey, _key_asset().model_dump()),
        (CertificateAsset, _certificate_asset().model_dump()),
        (CryptoAssessment, _assessment().model_dump()),
    ]


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "value",
        "VALUE",
        "raw_value",
        "sample-content",
        "payload",
        "binary_blob",
        "credential",
        "auth-token",
        "password",
        "private-key",
    ],
)
def test_crypto_no_secret_values(forbidden_key: str) -> None:
    rejected_value = "not-a-real-secret-but-must-never-be-echoed"
    for model_type, payload in _model_payloads():
        payload["extension"] = {"items": [{forbidden_key: rejected_value}]}
        with pytest.raises(SecretValueRejected) as raised:
            model_type.model_validate(payload)
        assert rejected_value not in str(raised.value)


@pytest.mark.parametrize("kind", sorted(VALID_SECRET_KINDS))
def test_crypto_secret_kind_values_are_metadata(kind: str) -> None:
    descriptor = _secret_descriptor(kind=kind)
    assert descriptor.kind == kind


def test_crypto_exposure_requires_credential_sensitivity() -> None:
    evidence_id = new_id("evd")
    credential_context = ExposureImpactContext(
        kind="credential_sensitivity",
        status="known",
        factor=1.0,
        source_ref="secrets:crypto_asset:private_key",
        evidence_id=evidence_id,
        reason="The handed-in claim identifies credential material.",
    )
    exposure = _crypto_exposure(credential_context)
    assert exposure.impact_context.kind == "credential_sensitivity"

    omitted_kind = ExposureImpactContext(
        status="known",
        factor=1.0,
        source_ref="secrets:crypto_asset:private_key",
        evidence_id=evidence_id,
        reason="An omitted kind must retain EA-0023's DSPM default.",
    )
    assert omitted_kind.kind == "data_sensitivity"
    with pytest.raises(CryptoConfigInvalid, match="credential_sensitivity"):
        _crypto_exposure(omitted_kind)


@pytest.mark.parametrize(
    "resource_ref",
    [
        "https://reader:password@example.test/repository",
        "https://example.test/repository?token=redacted",
        "https://example.test/repository?X-Amz-Signature=redacted",
        "https://example.test/repository?private-key=redacted",
    ],
)
def test_crypto_resource_ref_rejects_credentials(resource_ref: str) -> None:
    with pytest.raises(SecretValueRejected, match="credential"):
        _location(resource_ref=resource_ref)


def test_crypto_value_gate_survives_optimized_python() -> None:
    script = f"""
from datetime import datetime, timezone
from aqelyn.conventions import new_id
from aqelyn.conventions.errors import SecretValueRejected
from aqelyn.secrets import SecretScanDescriptor

base = {{
    'tenant_id': {TENANT!r},
    'kind': 'private_key',
    'fingerprint': {"hmac-sha256:" + "b" * 64!r},
    'location': {{'kind': 'repository', 'resource_ref': 'urn:repo:security'}},
    'source_id': new_id('src'),
    'observed_at': datetime.now(timezone.utc),
    'evidence_id': new_id('evd'),
}}
record = SecretScanDescriptor.model_validate(base)
if record.kind != 'private_key':
    raise SystemExit('positive private_key control failed')
base['extension'] = {{'nested': [{{'raw-value': 'must-not-escape'}}]}}
try:
    SecretScanDescriptor.model_validate(base)
except SecretValueRejected as exc:
    if 'must-not-escape' in str(exc):
        raise SystemExit('rejected value leaked in error')
else:
    raise SystemExit('optimized Python bypassed value gate')
"""
    environment = dict(os.environ)
    source = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source, environment.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_crypto_lifecycle_state_invariants() -> None:
    unknown = _unknown()
    known = _known()
    assert unknown.status == "unknown"
    assert unknown.evidence_id is None
    assert known.status == "valid"

    with pytest.raises(CryptoConfigInvalid, match="known lifecycle state"):
        Lifecycle(status="valid", reason="Missing evidence must not look valid.")
    with pytest.raises(CryptoConfigInvalid, match="supplied together"):
        Lifecycle(
            status="invalid",
            source_ref="claim:weak-key:v1",
            reason="Orphaned evidence is not a valid lifecycle claim.",
        )
    with pytest.raises(CryptoConfigInvalid, match="must not be empty"):
        Lifecycle(reason=" ")


def test_crypto_assessment_status_invariants() -> None:
    pending = _assessment()
    complete = _assessment(
        status="complete",
        assets_evaluated=3,
        secrets=1,
        keys=1,
        certificates=1,
        expiring_soon=1,
        unknown_lifecycle=1,
        exposure_ids=[new_id("exp")],
        evidence_id=new_id("evd"),
    )
    truncated = _assessment(
        status="truncated",
        assets_evaluated=1,
        secrets=1,
        incomplete_reason="The max_work budget was exhausted.",
        evidence_id=new_id("evd"),
    )
    assert {pending.status, complete.status, truncated.status} == {
        "pending",
        "complete",
        "truncated",
    }

    with pytest.raises(CryptoConfigInvalid, match="pending assessment"):
        _assessment(assets_evaluated=1, secrets=1)
    with pytest.raises(CryptoConfigInvalid, match="requires incomplete_reason"):
        _assessment(status="truncated", evidence_id=new_id("evd"))
    with pytest.raises(CryptoConfigInvalid, match="cannot carry incomplete_reason"):
        _assessment(
            status="complete",
            incomplete_reason="Contradictory complete state.",
            evidence_id=new_id("evd"),
        )
    with pytest.raises(CryptoConfigInvalid, match="asset-kind counts"):
        _assessment(
            status="complete",
            assets_evaluated=2,
            secrets=1,
            evidence_id=new_id("evd"),
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: _secret_descriptor(fingerprint="sha256:" + "a" * 64), "fingerprint"),
        (lambda: _key_descriptor(key_size=0), "key_size"),
        (lambda: _key_descriptor(usages=["signing", "signing"]), "duplicates"),
        (lambda: CryptoConfig(expiry_warning_days=0), "days"),
        (lambda: CryptoConfig(batch_size=1_001), "batch_size"),
        (lambda: CryptoConfig(max_work=100_001), "max_work"),
        (lambda: CryptoConfig(weak_algorithms=["md5", "md5"]), "duplicates"),
        (lambda: CryptoConfig(min_key_sizes={}), "non-empty"),
        (lambda: CryptoConfig(min_key_sizes={"rsa": 0}), "min_key_sizes"),
        (lambda: CryptoQuery(limit=1_001), "query limit"),
        (lambda: CryptoScope(kinds=["secret", "secret"]), "duplicates"),
    ],
)
def test_crypto_config_and_tenant_scope(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(CryptoConfigInvalid, match=message):
        factory()


def test_crypto_invalid_tenant_uses_platform_taxonomy() -> None:
    with pytest.raises(SchemaValidationError, match="tenant_id"):
        _secret_descriptor(tenant_id="not-a-uuid")


def test_crypto_taxonomy_and_false_friends() -> None:
    secret = _secret_asset()
    key = _key_asset()
    certificate = _certificate_asset()
    assessment = _assessment()

    assert is_valid(secret.id, "sct")
    assert is_valid(key.id, "cky")
    assert is_valid(certificate.id, "x509")
    assert is_valid(assessment.id, "cas")
    assert PREFIXES["cert"] == "iag_certification"
    assert PREFIXES["sct"] == "secret_asset"
    assert PREFIXES["cky"] == "cryptographic_key"
    assert PREFIXES["x509"] == "x509_certificate"
    assert PREFIXES["cas"] == "crypto_assessment"
    assert "cert" in VALID_ASSET_KINDS
    assert secret.classification == "secret"

    assert {"valid", "invalid", "unknown"} == VALID_LIFECYCLE_STATUSES
    assert {"pending", "complete", "truncated"} == VALID_ASSESSMENT_STATUSES
    assert {
        "repository",
        "configuration",
        "vault_reference",
        "runtime_reference",
        "other",
    } == VALID_SECRET_LOCATION_KINDS
    assert {
        "signing",
        "encryption",
        "authentication",
        "key_agreement",
        "other",
    } == VALID_KEY_USAGES
    assert {"secret", "key", "certificate"} == VALID_CRYPTO_ASSET_KINDS
    assert AuthenticityCheck(reason="Verification has not run.").status == "unknown"

    for error in (
        CryptoConfigInvalid,
        SecretValueRejected,
        CryptoAssetNotFound,
        CertificateNotFound,
    ):
        assert error.code in ALL_ERROR_CODES


def test_crypto_models_are_strict_and_surface_is_types_only() -> None:
    model_types = (
        Lifecycle,
        SecretLocation,
        SecretScanDescriptor,
        CryptographicKeyDescriptor,
        CertificateDescriptor,
        AuthenticityCheck,
        SecretAsset,
        CryptographicKey,
        CertificateAsset,
        CryptoScope,
        CryptoQuery,
        CryptographicExposure,
        CryptoAssessment,
        CryptoConfig,
    )
    for model_type in model_types:
        assert model_type.model_config.get("extra") == "forbid"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SecretLocation.model_validate(
            {
                "kind": "repository",
                "resource_ref": "urn:repo:security",
                "unrelated": "not part of the model",
            }
        )

    assert not hasattr(secrets, "scan")
    assert not hasattr(secrets, "connect")
    assert not hasattr(secrets, "execute")
