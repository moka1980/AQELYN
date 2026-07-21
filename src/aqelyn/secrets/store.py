"""Secrets and cryptographic-asset persistence contract (EA-0032 W2)."""

from __future__ import annotations

import re
from typing import Protocol, cast

from aqelyn.conventions import parse_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import CryptoConfigInvalid, TenantScopeRequired
from aqelyn.secrets.models import (
    VALID_CRYPTO_ASSET_KINDS,
    CertificateAsset,
    CryptoAssessment,
    CryptoAsset,
    CryptoAssetKind,
    CryptographicKey,
    CryptoQuery,
    SecretAsset,
)

_FINGERPRINT_RE = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")


class CryptoStore(Protocol):
    async def put_asset(self, asset: CryptoAsset) -> CryptoAsset: ...

    async def get_asset(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset | None: ...

    async def get_asset_by_fingerprint(
        self,
        kind: CryptoAssetKind,
        fingerprint: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset | None: ...

    async def query_assets(
        self,
        query: CryptoQuery,
    ) -> tuple[list[CryptoAsset], str | None]: ...

    async def put_assessment(self, assessment: CryptoAssessment) -> CryptoAssessment: ...

    async def get_assessment(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAssessment | None: ...


def asset_kind(asset: CryptoAsset) -> CryptoAssetKind:
    if isinstance(asset, SecretAsset):
        return "secret"
    if isinstance(asset, CryptographicKey):
        return "key"
    if isinstance(asset, CertificateAsset):
        return "certificate"
    raise CryptoConfigInvalid("unsupported crypto asset type")


def validate_asset(asset: CryptoAsset) -> CryptoAsset:
    prefix, _ = parse_id(asset.id)
    dumped = asset.model_dump(mode="json")
    if prefix == "sct":
        return SecretAsset.model_validate(dumped)
    if prefix == "cky":
        return CryptographicKey.model_validate(dumped)
    if prefix == "x509":
        return CertificateAsset.model_validate(dumped)
    raise CryptoConfigInvalid("crypto asset id must use sct_, cky_, or x509_ prefix")


def validate_assessment(assessment: CryptoAssessment) -> CryptoAssessment:
    return CryptoAssessment.model_validate(assessment.model_dump(mode="json"))


def validate_asset_id(value: str, *, field: str = "asset_id") -> str:
    try:
        prefix, _ = parse_id(value)
    except ValueError as exc:
        raise CryptoConfigInvalid(f"{field} must use sct_, cky_, or x509_ prefix") from exc
    if prefix not in {"sct", "cky", "x509"}:
        raise CryptoConfigInvalid(f"{field} must use sct_, cky_, or x509_ prefix")
    return require_typed_id(value, prefix, field=field)


def validate_assessment_id(value: str) -> str:
    return require_typed_id(value, "cas", field="assessment_id")


def validate_kind(value: str) -> CryptoAssetKind:
    if value not in VALID_CRYPTO_ASSET_KINDS:
        raise CryptoConfigInvalid(f"unknown crypto asset kind: {value!r}")
    return cast(CryptoAssetKind, value)


def validate_fingerprint(value: str) -> str:
    if _FINGERPRINT_RE.fullmatch(value) is None:
        raise CryptoConfigInvalid("fingerprint must be hmac-sha256 followed by 64 lowercase hex")
    return value


def validate_tenant_scope(value: str | None, *, mode: str) -> str | None:
    tenant_id = require_tenant_id(value)
    if mode == "enterprise" and tenant_id is None:
        raise TenantScopeRequired("crypto store read must be tenant-scoped")
    return tenant_id


def validate_write_tenant(value: str | None, *, mode: str) -> str | None:
    tenant_id = validate_tenant_scope(value, mode=mode)
    if mode == "local" and tenant_id is not None:
        raise CryptoConfigInvalid("local crypto store writes require tenant_id=null")
    return tenant_id


def validate_query(query: CryptoQuery, *, mode: str) -> CryptoQuery:
    selected = CryptoQuery.model_validate(query.model_dump(mode="json"))
    validate_tenant_scope(selected.tenant_id, mode=mode)
    if selected.kind is not None:
        validate_kind(selected.kind)
    if selected.cursor is not None:
        validate_asset_id(selected.cursor, field="cursor")
    return selected
