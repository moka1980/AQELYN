"""Secrets and cryptographic-asset engine (EA-0032 W2-W3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aqelyn.conventions import (
    ActorRef,
    new_id,
    require_tenant_id,
    require_typed_id,
    utc_now,
)
from aqelyn.conventions.errors import (
    AQError,
    CertificateNotFound,
    ChainBroken,
    CrossTenantReference,
    CryptoAssetNotFound,
    CryptoConfigInvalid,
    EvidenceTampered,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.inventory import DiscoverySource
from aqelyn.objects import ObjectStore
from aqelyn.secrets.ingest import (
    CryptoInventoryOwner,
    PreparedDescriptor,
    TrustAssessor,
    asset_observed_at,
    crypto_asset_kind,
    crypto_object,
    ensure_crypto_object_types,
    inventory_report,
    new_asset,
    prepare_descriptor,
    reconcile_asset,
    with_owner_identity,
)
from aqelyn.secrets.lifecycle import (
    CertificateAuthenticityVerifier,
    certificate_expiry,
    expiring_soon,
    key_rotation,
    key_strength,
)
from aqelyn.secrets.models import (
    AssessmentStatus,
    AuthenticityCheck,
    CertificateAsset,
    CertificateDescriptor,
    CryptoAssessment,
    CryptoAsset,
    CryptoAssetKind,
    CryptoConfig,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoQuery,
    CryptoScope,
    Lifecycle,
    SecretAsset,
    SecretScanDescriptor,
)
from aqelyn.secrets.store import CryptoStore

_SECRETS_ACTOR = ActorRef(actor_type="system", actor_id="secrets_engine")


class SecretsIntelligenceEngine:
    def __init__(
        self,
        store: CryptoStore,
        *,
        object_store: ObjectStore,
        inventory: CryptoInventoryOwner,
        evidence_store: EvidenceStore,
        trust: TrustAssessor,
        authenticity_verifier: CertificateAuthenticityVerifier | None = None,
        config: CryptoConfig | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.trust = trust
        self.authenticity_verifier = authenticity_verifier
        self.config = config or CryptoConfig()
        self.actor = actor or _SECRETS_ACTOR
        self.source_id = require_typed_id(
            source_id or new_id("src"),
            "src",
            field="source_id",
        )
        ensure_crypto_object_types(object_store)

    async def ingest_secrets(
        self,
        descriptors: Sequence[SecretScanDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[SecretAsset]:
        selected_tenant = require_tenant_id(tenant_id)
        prepared = await self._prepare_all(descriptors, tenant_id=selected_tenant)
        stored: list[SecretAsset] = []
        for item in prepared:
            asset = await self._persist(item, tenant_id=selected_tenant)
            if not isinstance(asset, SecretAsset):
                raise StoreUnavailable("secret ingest produced a non-secret asset")
            stored.append(asset)
        return [item.model_copy(deep=True) for item in stored]

    async def ingest_crypto_assets(
        self,
        keys: Sequence[CryptographicKeyDescriptor],
        certificates: Sequence[CertificateDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[CryptoAsset]:
        selected_tenant = require_tenant_id(tenant_id)
        descriptors: list[CryptographicKeyDescriptor | CertificateDescriptor] = [
            *keys,
            *certificates,
        ]
        prepared = await self._prepare_all(descriptors, tenant_id=selected_tenant)
        stored = [await self._persist(item, tenant_id=selected_tenant) for item in prepared]
        return [item.model_copy(deep=True) for item in stored]

    async def assess_certificate(
        self,
        certificate_id: str,
        *,
        tenant_id: str | None,
    ) -> CertificateAsset:
        selected_tenant = require_tenant_id(tenant_id)
        asset = await self.store.get_asset(certificate_id, tenant_id=selected_tenant)
        if asset is None:
            raise CertificateNotFound(f"certificate not found: {certificate_id}")
        if not isinstance(asset, CertificateAsset):
            raise CertificateNotFound(f"crypto asset is not a certificate: {certificate_id}")
        return await self._assess_certificate(asset, now=utc_now())

    async def assess_key(
        self,
        key_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptographicKey:
        selected_tenant = require_tenant_id(tenant_id)
        asset = await self.store.get_asset(key_id, tenant_id=selected_tenant)
        if asset is None:
            raise CryptoAssetNotFound(f"cryptographic key not found: {key_id}")
        if not isinstance(asset, CryptographicKey):
            raise CryptoAssetNotFound(f"crypto asset is not a key: {key_id}")
        return await self._assess_key(asset, now=utc_now())

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: CryptoScope | None = None,
    ) -> CryptoAssessment:
        selected_tenant = require_tenant_id(tenant_id)
        selected_scope = scope or CryptoScope()
        assets, truncated = await self._bounded_assets(tenant_id=selected_tenant)
        selected = [asset for asset in assets if _in_scope(asset, selected_scope)]
        now = utc_now()
        assessed: list[CryptoAsset] = []
        for asset in selected:
            if isinstance(asset, CertificateAsset):
                assessed.append(await self._assess_certificate(asset, now=now))
            elif isinstance(asset, CryptographicKey):
                assessed.append(await self._assess_key(asset, now=now))
            else:
                assessed.append(asset.model_copy(deep=True))

        certificates = [asset for asset in assessed if isinstance(asset, CertificateAsset)]
        keys = [asset for asset in assessed if isinstance(asset, CryptographicKey)]
        secrets = [asset for asset in assessed if isinstance(asset, SecretAsset)]
        expiring = sum(
            expiring_soon(_certificate_descriptor(asset), config=self.config, now=now)
            for asset in certificates
            if asset.expiry.status != "invalid"
        )
        unknown = sum(_has_unknown_lifecycle(asset) for asset in assessed)
        status: AssessmentStatus = "truncated" if truncated else "complete"
        incomplete_reason = (
            f"CryptoStore scan stopped at max_work={self.config.max_work}." if truncated else None
        )
        evidence = await self._record_assessment(
            tenant_id=selected_tenant,
            scope=selected_scope,
            status=status,
            assets=assessed,
            secrets=len(secrets),
            keys=len(keys),
            certificates=len(certificates),
            expiring=expiring,
            unknown=unknown,
            incomplete_reason=incomplete_reason,
            now=now,
        )
        assessment = CryptoAssessment(
            tenant_id=selected_tenant,
            run_at=now,
            scope=selected_scope.model_copy(deep=True),
            status=status,
            assets_evaluated=len(assessed),
            secrets=len(secrets),
            keys=len(keys),
            certificates=len(certificates),
            expiring_soon=expiring,
            unknown_lifecycle=unknown,
            incomplete_reason=incomplete_reason,
            evidence_id=evidence.id,
        )
        return await self.store.put_assessment(assessment)

    async def _assess_certificate(
        self,
        asset: CertificateAsset,
        *,
        now: datetime,
    ) -> CertificateAsset:
        integrity, _ = await self._basis_integrity(asset)
        descriptor = _certificate_descriptor(asset)
        if integrity.status == "valid":
            expiry = certificate_expiry(descriptor, now=now)
            authenticity = await self._certificate_authenticity(asset, descriptor)
        else:
            expiry = Lifecycle(reason="Certificate expiry is unknown until evidence is readable.")
            authenticity = Lifecycle(
                reason="Certificate authenticity is unknown until evidence integrity succeeds."
            )
        updated = CertificateAsset.model_validate(
            {
                **asset.model_dump(mode="python"),
                "expiry": expiry,
                "chain": Lifecycle(
                    reason="Certificate chain is unknown because no chain verifier is configured."
                ),
                "revocation": Lifecycle(
                    reason=(
                        "Certificate revocation is unknown because no revocation "
                        "source is configured."
                    )
                ),
                "integrity": integrity,
                "authenticity": authenticity,
            }
        )
        stored = await self.store.put_asset(updated)
        if not isinstance(stored, CertificateAsset):
            raise StoreUnavailable("CryptoStore returned a non-certificate asset")
        return stored

    async def _assess_key(
        self,
        asset: CryptographicKey,
        *,
        now: datetime,
    ) -> CryptographicKey:
        integrity, _ = await self._basis_integrity(asset)
        if integrity.status == "valid":
            strength = key_strength(asset, config=self.config)
            rotation = key_rotation(asset, config=self.config, now=now)
        else:
            strength = Lifecycle(reason="Key strength is unknown until evidence is readable.")
            rotation = Lifecycle(reason="Key rotation is unknown until evidence is readable.")
        updated = CryptographicKey.model_validate(
            {
                **asset.model_dump(mode="python"),
                "strength": strength,
                "rotation": rotation,
            }
        )
        stored = await self.store.put_asset(updated)
        if not isinstance(stored, CryptographicKey):
            raise StoreUnavailable("CryptoStore returned a non-key asset")
        return stored

    async def _basis_integrity(
        self,
        asset: CertificateAsset | CryptographicKey,
    ) -> tuple[Lifecycle, EvidenceRecord | None]:
        try:
            evidence = await self.evidence_store.get(asset.evidence_id, actor=self.actor)
            verification = await self.evidence_store.verify(asset.evidence_id)
        except (EvidenceTampered, ChainBroken) as exc:
            raise EvidenceTampered(
                f"crypto lifecycle evidence failed integrity: {exc.code}"
            ) from exc
        except AQError as exc:
            if not exc.retriable:
                raise
            return (
                Lifecycle(reason=f"EA-0004 evidence verification is unavailable: {exc.code}."),
                None,
            )
        if evidence.tenant_id != asset.tenant_id:
            raise CrossTenantReference("crypto lifecycle evidence belongs to another tenant")
        if evidence.source_id != asset.source_id:
            raise CryptoConfigInvalid("crypto lifecycle evidence source does not match asset")
        if not verification.ok:
            detail = verification.detail or "integrity verification failed"
            raise EvidenceTampered(
                f"crypto lifecycle evidence failed integrity verification: {detail}",
                details={"evidence_id": asset.evidence_id, "verification_detail": detail},
            )
        if evidence.content is None or evidence.content.get("fingerprint") != asset.fingerprint:
            raise CryptoConfigInvalid(
                "crypto lifecycle evidence fingerprint does not match asset fingerprint"
            )
        return (
            Lifecycle(
                status="valid",
                source_ref="EA-0004",
                evidence_id=evidence.id,
                reason="EA-0004 verified the cited descriptor evidence integrity.",
            ),
            evidence,
        )

    async def _certificate_authenticity(
        self,
        asset: CertificateAsset,
        descriptor: CertificateDescriptor,
    ) -> Lifecycle:
        verifier = self.authenticity_verifier
        if verifier is None:
            return Lifecycle(
                reason="Certificate authenticity is unknown because no verifier is configured."
            )
        try:
            checked = await verifier.verify(descriptor)
        except AQError as exc:
            if not exc.retriable:
                raise
            return Lifecycle(
                reason=f"Certificate authenticity verifier is unavailable: {exc.code}."
            )
        if checked.certificate_fingerprint != descriptor.fingerprint:
            raise CryptoConfigInvalid(
                "authenticity result fingerprint does not match the certificate"
            )
        if checked.basis_evidence_id != descriptor.evidence_id:
            raise CryptoConfigInvalid(
                "authenticity result basis evidence does not match the certificate"
            )
        try:
            recorded = await self.evidence_store.add(
                self._authenticity_evidence(asset, checked, recorded_at=utc_now())
            )
            verification = await self.evidence_store.verify(recorded.id)
        except AQError as exc:
            if not exc.retriable:
                raise
            return Lifecycle(reason=f"Authenticity result recording is unavailable: {exc.code}.")
        if not verification.ok:
            detail = verification.detail or "integrity verification failed"
            raise EvidenceTampered(
                f"recorded authenticity result failed integrity verification: {detail}"
            )
        return Lifecycle(
            status=checked.status,
            source_ref=self.source_id,
            evidence_id=recorded.id,
            reason=checked.reason,
        )

    def _authenticity_evidence(
        self,
        asset: CertificateAsset,
        checked: AuthenticityCheck,
        *,
        recorded_at: datetime,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            id="",
            tenant_id=asset.tenant_id,
            evidence_type="crypto.certificate_authenticity_verification",
            schema_version=1,
            subject=Subject(object_ids=[asset.object_id]),
            collected_at=recorded_at,
            recorded_at=recorded_at,
            collector=self.actor,
            source_id=self.source_id,
            method="secrets.verify_certificate_authenticity/v1",
            content={
                "certificate_id": asset.id,
                "certificate_fingerprint": checked.certificate_fingerprint,
                "basis_evidence_id": checked.basis_evidence_id,
                "status": checked.status,
                "reason": checked.reason,
            },
            content_hash="",
            confidence=1.0 if checked.status in {"valid", "invalid"} else 0.0,
            labels={"module": "EA-0032", "kind": "certificate_authenticity"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )

    async def _record_assessment(
        self,
        *,
        tenant_id: str | None,
        scope: CryptoScope,
        status: AssessmentStatus,
        assets: Sequence[CryptoAsset],
        secrets: int,
        keys: int,
        certificates: int,
        expiring: int,
        unknown: int,
        incomplete_reason: str | None,
        now: datetime,
    ) -> EvidenceRecord:
        recorded = await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=tenant_id,
                evidence_type="crypto.lifecycle_assessment",
                schema_version=1,
                subject=Subject(object_ids=[asset.object_id for asset in assets]),
                collected_at=now,
                recorded_at=now,
                collector=self.actor,
                source_id=self.source_id,
                method="secrets.assess_lifecycle/v1",
                content={
                    "scope": scope.model_dump(mode="json"),
                    "status": status,
                    "asset_ids": [asset.id for asset in assets],
                    "assets_evaluated": len(assets),
                    "secret_asset_count": secrets,
                    "key_count": keys,
                    "certificate_count": certificates,
                    "expiring_soon": expiring,
                    "unknown_lifecycle": unknown,
                    "incomplete_reason": incomplete_reason,
                },
                content_hash="",
                confidence=1.0,
                labels={"module": "EA-0032", "kind": "lifecycle_assessment"},
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        verification = await self.evidence_store.verify(recorded.id)
        if not verification.ok:
            detail = verification.detail or "integrity verification failed"
            raise EvidenceTampered(
                f"crypto assessment evidence failed integrity verification: {detail}"
            )
        return recorded

    async def _prepare_all(
        self,
        descriptors: Sequence[
            SecretScanDescriptor | CryptographicKeyDescriptor | CertificateDescriptor
        ],
        *,
        tenant_id: str | None,
    ) -> list[PreparedDescriptor]:
        if len(descriptors) > self.config.batch_size:
            raise CryptoConfigInvalid(
                "crypto descriptor count exceeds batch_size; partial acceptance is forbidden"
            )
        prepared: list[PreparedDescriptor] = []
        for descriptor in descriptors:
            prepared.append(
                await prepare_descriptor(
                    descriptor,
                    evidence_store=self.evidence_store,
                    trust=self.trust,
                    actor=self.actor,
                    tenant_id=tenant_id,
                )
            )
        return prepared

    async def _persist(
        self,
        prepared: PreparedDescriptor,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset:
        incoming = new_asset(prepared)
        kind = crypto_asset_kind(incoming)
        existing = await self.store.get_asset_by_fingerprint(
            kind,
            incoming.fingerprint,
            tenant_id=tenant_id,
        )
        selected = incoming if existing is None else reconcile_asset(existing, incoming)
        saved_object = await self.object_store.upsert(crypto_object(selected, actor=self.actor))
        if existing is not None and saved_object.id != existing.object_id:
            raise StoreUnavailable("EA-0002 crypto identity changed across ingest")
        selected = with_owner_identity(selected, saved_object.id)
        inventory_rows = await self.inventory.ingest(
            reports=[inventory_report(selected)],
            source=DiscoverySource(
                source_id=selected.source_id,
                reliability=selected.claim_confidence,
                health="ok",
                as_of=asset_observed_at(selected),
            ),
            tenant_id=tenant_id,
        )
        if len(inventory_rows) != 1 or inventory_rows[0].id != selected.inventory_ref:
            raise StoreUnavailable("EA-0025 inventory did not accept the crypto asset")
        return await self.store.put_asset(selected)

    async def _bounded_assets(
        self,
        *,
        tenant_id: str | None,
        kind: CryptoAssetKind | None = None,
    ) -> tuple[list[CryptoAsset], bool]:
        """Page under max_work; the boolean says the result was truncated."""
        selected_tenant = require_tenant_id(tenant_id)
        remaining = self.config.max_work
        cursor: str | None = None
        seen_cursors: set[str] = set()
        assets: list[CryptoAsset] = []
        while True:
            rows, next_cursor = await self.store.query_assets(
                CryptoQuery(
                    tenant_id=selected_tenant,
                    kind=kind,
                    limit=min(self.config.batch_size, remaining),
                    cursor=cursor,
                )
            )
            if len(rows) > remaining:
                raise StoreUnavailable("CryptoStore exceeded the requested work budget")
            assets.extend(rows)
            remaining -= len(rows)
            if next_cursor is None:
                return [item.model_copy(deep=True) for item in assets], False
            if next_cursor in seen_cursors:
                raise StoreUnavailable("CryptoStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            if remaining == 0:
                return [item.model_copy(deep=True) for item in assets], True
            cursor = next_cursor


def _certificate_descriptor(asset: CertificateAsset) -> CertificateDescriptor:
    return CertificateDescriptor(
        tenant_id=asset.tenant_id,
        fingerprint=asset.fingerprint,
        serial=asset.serial,
        subject=asset.subject,
        issuer=asset.issuer,
        not_after=asset.not_after,
        source_id=asset.source_id,
        observed_at=asset.observed_at,
        evidence_id=asset.evidence_id,
    )


def _in_scope(asset: CryptoAsset, scope: CryptoScope) -> bool:
    if scope.asset_ids and asset.id not in scope.asset_ids:
        return False
    return not scope.kinds or crypto_asset_kind(asset) in scope.kinds


def _has_unknown_lifecycle(asset: CryptoAsset) -> int:
    if isinstance(asset, SecretAsset):
        return int(asset.rotation.status == "unknown")
    if isinstance(asset, CryptographicKey):
        return int(asset.strength.status == "unknown" or asset.rotation.status == "unknown")
    return int(
        any(
            lifecycle.status == "unknown"
            for lifecycle in (
                asset.expiry,
                asset.chain,
                asset.revocation,
                asset.integrity,
                asset.authenticity,
            )
        )
    )
