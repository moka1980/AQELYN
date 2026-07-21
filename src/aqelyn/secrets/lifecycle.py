"""Pure cryptographic lifecycle decisions and authenticity adapter contract."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from aqelyn.secrets.models import (
    AuthenticityCheck,
    CertificateDescriptor,
    CryptoConfig,
    CryptographicKey,
    Lifecycle,
)


class CertificateAuthenticityVerifier(Protocol):
    """Trusted adapter that verifies the exact integrity-checked certificate."""

    async def verify(self, certificate: CertificateDescriptor) -> AuthenticityCheck: ...


def certificate_expiry(
    certificate: CertificateDescriptor,
    *,
    now: datetime,
) -> Lifecycle:
    if certificate.not_after is None:
        return Lifecycle(reason="Certificate expiry is unknown because not_after was not reported.")
    status = "invalid" if certificate.not_after <= now else "valid"
    reason = (
        f"Certificate expired at {certificate.not_after.isoformat()}."
        if status == "invalid"
        else f"Certificate remains valid until {certificate.not_after.isoformat()}."
    )
    return Lifecycle(
        status=status,
        source_ref=certificate.source_id,
        evidence_id=certificate.evidence_id,
        reason=reason,
    )


def key_strength(key: CryptographicKey, *, config: CryptoConfig) -> Lifecycle:
    if key.algorithm is None:
        return Lifecycle(reason="Key strength is unknown because the algorithm was not reported.")
    algorithm = key.algorithm.casefold()
    weak = {item.casefold() for item in config.weak_algorithms}
    minimums = {name.casefold(): size for name, size in config.min_key_sizes.items()}
    if algorithm in weak:
        return Lifecycle(
            status="invalid",
            source_ref=key.source_id,
            evidence_id=key.evidence_id,
            reason=f"Algorithm {key.algorithm} is configured as weak.",
        )
    minimum = minimums.get(algorithm)
    if minimum is None:
        return Lifecycle(
            reason=f"Key strength is unknown because algorithm {key.algorithm} is not recognized."
        )
    if key.key_size is None:
        return Lifecycle(
            reason=f"Key strength is unknown because {key.algorithm} key size was not reported."
        )
    status = "valid" if key.key_size >= minimum else "invalid"
    comparison = "meets" if status == "valid" else "is below"
    return Lifecycle(
        status=status,
        source_ref=key.source_id,
        evidence_id=key.evidence_id,
        reason=(
            f"Reported {key.algorithm} key size {key.key_size} {comparison} "
            f"the configured minimum {minimum}."
        ),
    )


def key_rotation(
    key: CryptographicKey,
    *,
    config: CryptoConfig,
    now: datetime,
) -> Lifecycle:
    if key.last_rotated_at is None:
        return Lifecycle(reason="Key rotation is unknown because no rotation time was reported.")
    oldest_allowed = now - timedelta(days=config.max_key_age_days)
    status = "invalid" if key.last_rotated_at < oldest_allowed else "valid"
    reason = (
        f"Last rotation at {key.last_rotated_at.isoformat()} exceeds the configured age limit."
        if status == "invalid"
        else (
            f"Last rotation at {key.last_rotated_at.isoformat()} is within the "
            "configured age limit."
        )
    )
    return Lifecycle(
        status=status,
        source_ref=key.source_id,
        evidence_id=key.evidence_id,
        reason=reason,
    )


def expiring_soon(
    certificate: CertificateDescriptor,
    *,
    config: CryptoConfig,
    now: datetime,
) -> bool:
    return certificate.not_after is not None and now < certificate.not_after <= now + timedelta(
        days=config.expiry_warning_days
    )
