"""Secrets and cryptographic-asset engine (EA-0032 W2-W4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import (
    ActorRef,
    new_id,
    parse_id,
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
    EvidenceNotFound,
    EvidenceTampered,
    FindingNotFound,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.exposure import AssetRef, ExposureImpactContext, ExposureRecord
from aqelyn.findings import Finding, FindingStore
from aqelyn.governance import ComplianceSnapshot
from aqelyn.inventory import DiscoverySource, Ownership
from aqelyn.mission.models import MissionImpactResult
from aqelyn.objects import NaturalKey, ObjectQuery, ObjectStore
from aqelyn.risk.models import RiskConfig
from aqelyn.secrets.ingest import (
    CRYPTO_OBJECT_TYPES,
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
    CredentialGovernanceScore,
    CryptoAssessment,
    CryptoAsset,
    CryptoAssetKind,
    CryptoConfig,
    CryptographicExposure,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoQuery,
    CryptoScope,
    Lifecycle,
    SecretAsset,
    SecretScanDescriptor,
    StorageSafetyClassification,
)
from aqelyn.secrets.scoring import compose_credential_governance
from aqelyn.secrets.storage import classify_storage_safety
from aqelyn.secrets.store import CryptoStore
from aqelyn.workflow import Playbook, Run, Step

_SECRETS_ACTOR = ActorRef(actor_type="system", actor_id="secrets_engine")


class CryptoExposureOwner(Protocol):
    async def analyze_scored_exposure(
        self,
        *,
        asset_ref: AssetRef,
        impact_context: ExposureImpactContext,
        tenant_id: str | None,
    ) -> ExposureRecord: ...

    async def get_exposure(
        self,
        exposure_id: str,
        *,
        tenant_id: str | None,
    ) -> ExposureRecord | None: ...

    async def raise_exposure_finding(
        self,
        exposure: ExposureRecord,
        *,
        by: ActorRef | None = None,
    ) -> Finding: ...


class CryptoComplianceOwner(Protocol):
    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
        record_evidence: bool = True,
    ) -> ComplianceSnapshot: ...


class CryptoOwnershipOwner(Protocol):
    async def ownership(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> Ownership | None: ...


class CryptoMissionOwner(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class SecretsIntelligenceEngine:
    def __init__(
        self,
        store: CryptoStore,
        *,
        object_store: ObjectStore,
        inventory: CryptoInventoryOwner,
        evidence_store: EvidenceStore,
        trust: TrustAssessor,
        ownership_owner: CryptoOwnershipOwner | None = None,
        mission_owner: CryptoMissionOwner | None = None,
        authenticity_verifier: CertificateAuthenticityVerifier | None = None,
        exposure_owner: CryptoExposureOwner | None = None,
        compliance_owner: CryptoComplianceOwner | None = None,
        finding_store: FindingStore | None = None,
        workflow_engine: WorkflowProposer | None = None,
        config: CryptoConfig | None = None,
        risk_config: RiskConfig | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.trust = trust
        self.ownership_owner = ownership_owner
        self.mission_owner = mission_owner
        self.authenticity_verifier = authenticity_verifier
        self.exposure_owner = exposure_owner
        self.compliance_owner = compliance_owner
        self.finding_store = finding_store
        self.workflow_engine = workflow_engine
        self.config = config or CryptoConfig()
        self.risk_config = risk_config or RiskConfig()
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
            try:
                if isinstance(asset, CertificateAsset):
                    assessed.append(await self._assess_certificate(asset, now=now))
                elif isinstance(asset, CryptographicKey):
                    assessed.append(await self._assess_key(asset, now=now))
                else:
                    assessed.append(asset.model_copy(deep=True))
            except EvidenceNotFound:
                assessed.append(await self._record_missing_basis(asset))

        certificates = [asset for asset in assessed if isinstance(asset, CertificateAsset)]
        keys = [asset for asset in assessed if isinstance(asset, CryptographicKey)]
        secrets = [asset for asset in assessed if isinstance(asset, SecretAsset)]
        expiring = sum(
            expiring_soon(_certificate_descriptor(asset), config=self.config, now=now)
            for asset in certificates
            if asset.expiry.status != "invalid"
        )
        unknown = sum(_has_unknown_lifecycle(asset) for asset in assessed)
        governance_score_ids: list[str] = []
        governance_failures: list[str] = []
        if self._governance_scoring_ready():
            for asset in assessed:
                try:
                    score = await self._score_asset(asset, tenant_id=selected_tenant)
                except EvidenceNotFound as exc:
                    governance_failures.append(f"{asset.id}:{exc.code}")
                except AQError as exc:
                    if not exc.retriable:
                        raise
                    governance_failures.append(f"{asset.id}:{exc.code}")
                else:
                    governance_score_ids.append(score.id)
            governance_status = "partial" if governance_failures else "complete"
            governance_reason = (
                "Governance scoring was incomplete: " + ", ".join(governance_failures)
                if governance_failures
                else None
            )
        else:
            governance_status = "pending"
            governance_reason = "Governance scoring owners are not configured."
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
            governance_status=governance_status,
            governance_score_ids=governance_score_ids,
            governance_reason=governance_reason,
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
            governance_scoring_status=governance_status,
            governance_score_ids=governance_score_ids,
            governance_incomplete_reason=governance_reason,
            incomplete_reason=incomplete_reason,
            evidence_id=evidence.id,
        )
        return await self.store.put_assessment(assessment)

    async def score_credential(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> CredentialGovernanceScore:
        selected_tenant = require_tenant_id(tenant_id)
        asset = await self.store.get_asset(asset_id, tenant_id=selected_tenant)
        if asset is None:
            raise CryptoAssetNotFound(asset_id)
        if isinstance(asset, CertificateAsset):
            selected: CryptoAsset = await self._assess_certificate(asset, now=utc_now())
        elif isinstance(asset, CryptographicKey):
            selected = await self._assess_key(asset, now=utc_now())
        else:
            selected = asset.model_copy(deep=True)
        return await self._score_asset(selected, tenant_id=selected_tenant)

    async def classify_storage(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> StorageSafetyClassification:
        selected_tenant = require_tenant_id(tenant_id)
        asset = await self.store.get_asset(asset_id, tenant_id=selected_tenant)
        if asset is None:
            raise CryptoAssetNotFound(asset_id)
        return classify_storage_safety(
            asset,
            approved_location_prefixes=self.config.approved_storage_location_prefixes,
        )

    async def analyze_exposure(
        self,
        *,
        tenant_id: str | None,
        scope: CryptoScope | None = None,
    ) -> list[CryptographicExposure]:
        selected_tenant = require_tenant_id(tenant_id)
        owner = self.exposure_owner
        if owner is None:
            raise StoreUnavailable("EA-0023 crypto exposure owner is unavailable")
        selected_scope = scope or CryptoScope()
        assets, truncated = await self._bounded_assets(tenant_id=selected_tenant)
        if truncated:
            raise StoreUnavailable(
                "crypto exposure analysis exceeded max_work; refusing partial results"
            )
        results: list[CryptographicExposure] = []
        for asset in assets:
            if not _in_scope(asset, selected_scope):
                continue
            integrity, _ = await self._basis_integrity(asset)
            if integrity.status != "valid":
                results.append(
                    _pending_crypto_exposure(
                        asset,
                        reason="Credential sensitivity is unknown until evidence is readable.",
                    )
                )
                continue
            context = _credential_impact_context(asset)
            owner_record = await owner.analyze_scored_exposure(
                asset_ref=_crypto_asset_ref(asset),
                impact_context=context,
                tenant_id=selected_tenant,
            )
            _validate_owner_exposure(asset, owner_record, expected_context=context)
            if owner_record.reachability == "unknown":
                results.append(
                    _pending_crypto_exposure(
                        asset,
                        reason=owner_record.rationale,
                    )
                )
                continue
            results.append(
                CryptographicExposure(
                    id=f"crypto-exposure:{asset.id}:{owner_record.id}",
                    tenant_id=selected_tenant,
                    asset_id=asset.id,
                    surface_ref=asset.inventory_ref,
                    object_id=asset.object_id,
                    exposure_record_id=owner_record.id,
                    status="confirmed",
                    impact_context=context,
                    reason=owner_record.rationale,
                    evidence_id=asset.evidence_id,
                )
            )
        return [item.model_copy(deep=True) for item in results]

    async def exposures_to_findings(
        self,
        exposures: Sequence[CryptographicExposure],
        *,
        tenant_id: str | None,
        by: ActorRef,
    ) -> list[str]:
        selected_tenant = require_tenant_id(tenant_id)
        owner = self.exposure_owner
        if owner is None:
            raise StoreUnavailable("EA-0023 crypto finding owner is unavailable")
        finding_ids: list[str] = []
        for exposure in exposures:
            if exposure.tenant_id != selected_tenant:
                raise CrossTenantReference("crypto exposure tenant does not match request tenant")
            if exposure.status != "confirmed":
                continue
            if exposure.exposure_record_id is None:
                raise CryptoConfigInvalid("confirmed crypto exposure lacks an owner record")
            asset = await self.store.get_asset(
                exposure.asset_id,
                tenant_id=selected_tenant,
            )
            if asset is None:
                raise CryptoAssetNotFound(exposure.asset_id)
            owner_record = await owner.get_exposure(
                exposure.exposure_record_id,
                tenant_id=selected_tenant,
            )
            if owner_record is None:
                raise CryptoConfigInvalid(
                    f"EA-0023 exposure record not found: {exposure.exposure_record_id}"
                )
            _validate_owner_exposure(
                asset,
                owner_record,
                expected_context=exposure.impact_context,
            )
            finding = await owner.raise_exposure_finding(owner_record, by=by)
            finding_ids.append(finding.id)
        return finding_ids

    async def crypto_compliance(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery,
    ) -> ComplianceSnapshot:
        selected_tenant = require_tenant_id(tenant_id)
        if scope.tenant_id not in (None, selected_tenant):
            raise CrossTenantReference(
                "crypto compliance scope tenant does not match request tenant"
            )
        crypto_types = set(CRYPTO_OBJECT_TYPES.values())
        if scope.object_type not in crypto_types:
            raise CryptoConfigInvalid("crypto compliance scope requires one crypto object_type")
        owner = self.compliance_owner
        if owner is None:
            raise StoreUnavailable("EA-0010 crypto compliance owner is unavailable")
        selected_scope = scope.model_copy(
            update={"tenant_id": selected_tenant},
            deep=True,
        )
        return await owner.assess(
            tenant_id=selected_tenant,
            scope=selected_scope,
        )

    async def propose_rotation(
        self,
        finding_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        reason: str,
    ) -> Run:
        selected_tenant = require_tenant_id(tenant_id)
        if not reason.strip():
            raise CryptoConfigInvalid("rotation proposal reason must not be empty")
        if self.finding_store is None:
            raise StoreUnavailable("crypto finding read path is unavailable")
        if self.workflow_engine is None:
            raise StoreUnavailable("EA-0008 crypto proposal path is unavailable")
        finding = await self.finding_store.get(finding_id)
        if finding is None:
            raise FindingNotFound(finding_id)
        if finding.tenant_id != selected_tenant:
            raise CrossTenantReference("finding tenant does not match rotation request tenant")
        if (
            finding.finding_type != "attack_surface_exposure"
            or finding.source_engine != "exposure_engine"
        ):
            raise CryptoConfigInvalid("rotation requires an EA-0023 exposure finding")
        context = _finding_credential_context(finding)
        asset = await self.store.get_asset(
            context.source_ref,
            tenant_id=selected_tenant,
        )
        if asset is None:
            raise CryptoAssetNotFound(context.source_ref)
        if context.evidence_id != asset.evidence_id:
            raise CryptoConfigInvalid("finding evidence is not bound to the crypto asset")
        if asset.object_id not in finding.affected_object_ids:
            raise CryptoConfigInvalid("finding is not bound to the crypto asset object")
        if finding.automation.eligibility != "none":
            raise CryptoConfigInvalid("crypto rotation requires a non-automatic finding")
        return await self.workflow_engine.propose(
            _rotation_playbook(asset, finding=finding, reason=reason),
            by=by,
            source_finding=finding,
        )

    def explain(self, asset: CryptoAsset) -> dict[str, object]:
        lifecycle = _asset_lifecycle(asset)
        return {
            "asset_id": asset.id,
            "asset_kind": crypto_asset_kind(asset),
            "fingerprint": asset.fingerprint,
            "object_id": asset.object_id,
            "inventory_ref": asset.inventory_ref,
            "claim_confidence": asset.claim_confidence,
            "source_id": asset.source_id,
            "evidence_id": asset.evidence_id,
            "lifecycle": {name: value.model_dump(mode="json") for name, value in lifecycle.items()},
            "conflicts": [item.model_dump(mode="json") for item in asset.conflicts],
        }

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

    async def _record_missing_basis(self, asset: CryptoAsset) -> CryptoAsset:
        reason = f"Lifecycle is unknown because cited evidence {asset.evidence_id} was not found."
        if isinstance(asset, CertificateAsset):
            updated: CryptoAsset = CertificateAsset.model_validate(
                {
                    **asset.model_dump(mode="python"),
                    "expiry": Lifecycle(reason=reason),
                    "chain": Lifecycle(reason=reason),
                    "revocation": Lifecycle(reason=reason),
                    "integrity": Lifecycle(reason=reason),
                    "authenticity": Lifecycle(reason=reason),
                }
            )
        elif isinstance(asset, CryptographicKey):
            updated = CryptographicKey.model_validate(
                {
                    **asset.model_dump(mode="python"),
                    "strength": Lifecycle(reason=reason),
                    "rotation": Lifecycle(reason=reason),
                }
            )
        else:
            return asset.model_copy(deep=True)
        return await self.store.put_asset(updated)

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
        asset: CryptoAsset,
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
        governance_status: str,
        governance_score_ids: Sequence[str],
        governance_reason: str | None,
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
                    "governance_scoring_status": governance_status,
                    "governance_score_ids": list(governance_score_ids),
                    "governance_incomplete_reason": governance_reason,
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

    async def _score_asset(
        self,
        asset: CryptoAsset,
        *,
        tenant_id: str | None,
    ) -> CredentialGovernanceScore:
        ownership_owner = self.ownership_owner
        if ownership_owner is None:
            raise StoreUnavailable("EA-0025 credential ownership owner is unavailable")
        mission_owner = self.mission_owner
        if mission_owner is None:
            raise StoreUnavailable("EA-0007 credential mission owner is unavailable")
        if self.exposure_owner is None:
            raise StoreUnavailable("EA-0023 credential exposure owner is unavailable")
        if self.compliance_owner is None:
            raise StoreUnavailable("EA-0010 credential compliance owner is unavailable")

        _, basis_evidence = await self._basis_integrity(asset)
        trust = await self.trust.assess(
            f"crypto-governance:{asset.id}",
            [] if basis_evidence is None else [basis_evidence],
            now=asset_observed_at(asset),
        )
        ownership = await ownership_owner.ownership(
            asset.inventory_ref,
            tenant_id=tenant_id,
        )
        mission = await mission_owner.mission_impact(asset.object_id)
        [exposure] = await self.analyze_exposure(
            tenant_id=tenant_id,
            scope=CryptoScope(asset_ids=[asset.id]),
        )
        owner_exposure: ExposureRecord | None = None
        if exposure.exposure_record_id is not None:
            owner_exposure = await self.exposure_owner.get_exposure(
                exposure.exposure_record_id,
                tenant_id=tenant_id,
            )
            if owner_exposure is None:
                raise CryptoConfigInvalid(
                    f"EA-0023 exposure record not found: {exposure.exposure_record_id}"
                )
            _validate_owner_exposure(
                asset,
                owner_exposure,
                expected_context=exposure.impact_context,
            )
        kind = crypto_asset_kind(asset)
        compliance = await self.crypto_compliance(
            tenant_id=tenant_id,
            scope=ObjectQuery(
                tenant_id=tenant_id,
                object_type=CRYPTO_OBJECT_TYPES[kind],
                natural_key=NaturalKey(
                    namespace=f"crypto:{kind}:fingerprint",
                    value=asset.fingerprint,
                ),
                limit=1,
            ),
        )
        computed_at = utc_now()
        storage_safety = classify_storage_safety(
            asset,
            approved_location_prefixes=self.config.approved_storage_location_prefixes,
        )
        composed = compose_credential_governance(
            asset,
            ownership=ownership,
            exposure=exposure,
            owner_exposure=owner_exposure,
            trust=trust,
            mission=mission,
            compliance=compliance,
            storage_safety=storage_safety,
            factor_weights=self.config.governance_factor_weights,
            computed_at=computed_at,
            risk_config=self.risk_config,
        )
        score_id = new_id("cgs")
        result_evidence = await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=tenant_id,
                evidence_type="crypto.governance_score",
                schema_version=1,
                subject=Subject(object_ids=[asset.object_id]),
                collected_at=computed_at,
                recorded_at=computed_at,
                collector=self.actor,
                source_id=self.source_id,
                method="secrets.score_credential/v2",
                content={
                    "score_id": score_id,
                    "asset_id": asset.id,
                    "object_id": asset.object_id,
                    "score": composed.score,
                    "factors": [
                        {
                            "name": factor.name,
                            "status": factor.status,
                            "rating": factor.rating,
                            "weight": factor.weight,
                        }
                        for factor in composed.factors
                    ],
                    "active_critical_exposure_ids": list(composed.active_critical_exposure_ids),
                    "metadata_only": True,
                },
                content_hash="",
                confidence=composed.confidence,
                labels={"module": "EA-0032", "kind": "credential_governance_score"},
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        verification = await self.evidence_store.verify(result_evidence.id)
        if not verification.ok:
            detail = verification.detail or "integrity verification failed"
            raise EvidenceTampered(
                f"credential governance evidence failed integrity verification: {detail}"
            )
        score = CredentialGovernanceScore(
            id=score_id,
            tenant_id=tenant_id,
            asset_id=asset.id,
            object_id=asset.object_id,
            score=composed.score,
            factors=composed.factors,
            active_critical_exposure_ids=composed.active_critical_exposure_ids,
            derivation=composed.derivation,
            confidence=composed.confidence,
            statement=composed.statement,
            computed_at=computed_at,
            evidence_id=result_evidence.id,
        )
        return await self.store.put_score(score)

    def _governance_scoring_ready(self) -> bool:
        return all(
            owner is not None
            for owner in (
                self.ownership_owner,
                self.mission_owner,
                self.exposure_owner,
                self.compliance_owner,
            )
        )

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


def _crypto_asset_ref(asset: CryptoAsset) -> AssetRef:
    return AssetRef(
        kind="cert" if isinstance(asset, CertificateAsset) else "asset",
        ref_id=asset.inventory_ref,
        object_id=asset.object_id,
        evidence_id=asset.evidence_id,
    )


def _credential_impact_context(asset: CryptoAsset) -> ExposureImpactContext:
    return ExposureImpactContext(
        kind="credential_sensitivity",
        status="known",
        factor=1.0,
        source_ref=asset.id,
        evidence_id=asset.evidence_id,
        reason=(
            f"EA-0032 identified {crypto_asset_kind(asset)} metadata whose compromise "
            "would expose credential or cryptographic capability."
        ),
    )


def _pending_crypto_exposure(
    asset: CryptoAsset,
    *,
    reason: str,
) -> CryptographicExposure:
    return CryptographicExposure(
        id=f"crypto-exposure-pending:{asset.id}",
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        surface_ref=asset.inventory_ref,
        object_id=asset.object_id,
        exposure_record_id=None,
        status="reachability_pending",
        impact_context=ExposureImpactContext(
            kind="credential_sensitivity",
            status="unknown",
            factor=None,
            source_ref=asset.id,
            evidence_id=asset.evidence_id,
            reason=reason,
        ),
        reason=reason,
        evidence_id=asset.evidence_id,
    )


def _validate_owner_exposure(
    asset: CryptoAsset,
    exposure: ExposureRecord,
    *,
    expected_context: ExposureImpactContext,
) -> None:
    if exposure.tenant_id != asset.tenant_id:
        raise CrossTenantReference("EA-0023 exposure belongs to another tenant")
    expected_ref = _crypto_asset_ref(asset)
    if exposure.asset_ref != expected_ref:
        raise CryptoConfigInvalid("EA-0023 exposure is bound to a different crypto asset")
    if exposure.reachability == "unknown":
        if exposure.score is not None or exposure.derivation is not None:
            raise CryptoConfigInvalid("unknown EA-0023 reachability cannot be scored")
        return
    if exposure.impact_context != expected_context:
        raise CryptoConfigInvalid(
            "EA-0023 exposure did not preserve credential_sensitivity context"
        )
    if exposure.score is None or exposure.derivation is None:
        raise CryptoConfigInvalid("known EA-0023 exposure lacks replayable scoring")


def _finding_credential_context(finding: Finding) -> ExposureImpactContext:
    details = finding.expert_details
    raw = None if details is None else details.get("impact_context")
    if not isinstance(raw, dict):
        raise CryptoConfigInvalid("finding does not carry a crypto exposure impact context")
    context = ExposureImpactContext.model_validate(raw)
    if context.kind != "credential_sensitivity" or context.status != "known":
        raise CryptoConfigInvalid("finding is not a known credential-sensitivity exposure")
    try:
        prefix, _ = parse_id(context.source_ref)
    except ValueError as exc:
        raise CryptoConfigInvalid("impact context source_ref is not a crypto asset id") from exc
    if prefix not in {"sct", "cky", "x509"}:
        raise CryptoConfigInvalid("impact context source_ref is not a crypto asset id")
    return context


def _rotation_playbook(
    asset: CryptoAsset,
    *,
    finding: Finding,
    reason: str,
) -> Playbook:
    action = "crypto.revoke_certificate" if isinstance(asset, CertificateAsset) else "crypto.rotate"
    return Playbook(
        id=f"secrets-{action.replace('.', '-')}-{finding.id}",
        version=1,
        name=(
            "Propose certificate revocation"
            if isinstance(asset, CertificateAsset)
            else "Propose credential rotation"
        ),
        description=(
            "EA-0032 proposes only; EA-0008 re-validates capability, approval, "
            "and finding eligibility before execution."
        ),
        tenant_id=asset.tenant_id,
        steps=[
            Step(
                id="review-and-remediate",
                action_type=action,
                inputs={
                    "crypto_asset_id": asset.id,
                    "object_id": asset.object_id,
                    "inventory_ref": asset.inventory_ref,
                    "finding_id": finding.id,
                    "evidence_id": asset.evidence_id,
                    "reason": reason,
                },
                idempotency_key=f"secrets:{finding.id}:{action}",
                requires_approval=True,
            )
        ],
    )


def _asset_lifecycle(asset: CryptoAsset) -> dict[str, Lifecycle]:
    if isinstance(asset, SecretAsset):
        return {"rotation": asset.rotation.model_copy(deep=True)}
    if isinstance(asset, CryptographicKey):
        return {
            "strength": asset.strength.model_copy(deep=True),
            "rotation": asset.rotation.model_copy(deep=True),
        }
    return {
        "expiry": asset.expiry.model_copy(deep=True),
        "chain": asset.chain.model_copy(deep=True),
        "revocation": asset.revocation.model_copy(deep=True),
        "integrity": asset.integrity.model_copy(deep=True),
        "authenticity": asset.authenticity.model_copy(deep=True),
    }
