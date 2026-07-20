"""DSPM metadata classification, owner routing, and bounded assessment (EA-0031 P2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef, new_id, parse_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import (
    AQError,
    CrossTenantReference,
    DataAssetNotFound,
    DataExposureNotFound,
    DSPMConfigInvalid,
    EvidenceTampered,
    StoreUnavailable,
)
from aqelyn.decision import replay
from aqelyn.dspm.classify import ClassificationResult, TrustAssessor, classify_descriptor
from aqelyn.dspm.models import (
    AssetClassificationStatus,
    Classification,
    DataAccessClaim,
    DataAccessContext,
    DataAsset,
    DataExposure,
    DataPostureAssessment,
    DataStoreDescriptor,
    DSPMConfig,
    DSPMScope,
    FieldClassification,
    classification_order,
)
from aqelyn.dspm.store import DSPMStore
from aqelyn.evidence import EvidenceStore
from aqelyn.exposure import AssetRef, ExposureImpactContext, ExposureRecord
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.findings.models import Severity
from aqelyn.governance import ComplianceSnapshot
from aqelyn.iag import AccessPath, AccessRisk, AccessRiskReport
from aqelyn.inventory import AssetRecord, DiscoverySource
from aqelyn.objects import AQObject, NaturalKey, ObjectQuery, ObjectStore, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.workflow import Playbook, Run, Step

DATA_STORE_OBJECT_TYPE = "data_store"
_DSPM_ACTOR = ActorRef(actor_type="system", actor_id="dspm_engine")


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


class DataStoreInventoryOwner(Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...


class DataStoreExposureOwner(Protocol):
    async def analyze_exposure(
        self,
        *,
        asset_ref: AssetRef,
        tenant_id: str | None,
    ) -> ExposureRecord: ...

    async def score_exposure(
        self,
        exposure: ExposureRecord,
        *,
        impact_context: ExposureImpactContext | None = None,
    ) -> ExposureRecord: ...


class DataStoreIAGOwner(Protocol):
    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]: ...

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport: ...


class DataStoreComplianceOwner(Protocol):
    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
        record_evidence: bool = True,
    ) -> ComplianceSnapshot: ...


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


def ensure_data_store_object_type(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        registry.register(DATA_STORE_OBJECT_TYPE, 1, None)
        return
    if registry is not None:
        cast(_ObjectStoreRegistry, object_store).registry.register(
            DATA_STORE_OBJECT_TYPE,
            1,
            None,
        )


class DSPMEngine:
    def __init__(
        self,
        store: DSPMStore,
        *,
        object_store: ObjectStore,
        inventory: DataStoreInventoryOwner,
        evidence_store: EvidenceStore,
        trust: TrustAssessor,
        config: DSPMConfig,
        exposure_owner: DataStoreExposureOwner | None = None,
        iag_owner: DataStoreIAGOwner | None = None,
        compliance_owner: DataStoreComplianceOwner | None = None,
        finding_store: FindingStore | None = None,
        workflow_engine: WorkflowProposer | None = None,
        actor: ActorRef | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.trust = trust
        self.config = config
        self.exposure_owner = exposure_owner
        self.iag_owner = iag_owner
        self.compliance_owner = compliance_owner
        self.finding_store = finding_store
        self.workflow_engine = workflow_engine
        self.actor = actor or _DSPM_ACTOR
        ensure_data_store_object_type(object_store)

    async def ingest_store(
        self,
        descriptors: Sequence[DataStoreDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[DataAsset]:
        selected_tenant = require_tenant_id(tenant_id)
        stored: list[DataAsset] = []
        for descriptor in descriptors:
            self._validate_descriptor(descriptor, tenant_id=selected_tenant)
            result = await classify_descriptor(
                descriptor,
                rules=self.config.classifier_rules,
                evidence_store=self.evidence_store,
                trust=self.trust,
                actor=self.actor,
                tenant_id=selected_tenant,
            )
            existing = await self.store.get_asset_by_store_id(
                descriptor.store_id,
                tenant_id=selected_tenant,
            )
            saved_object = await self.object_store.upsert(
                _data_store_object(
                    descriptor,
                    result=result,
                    actor=self.actor,
                    object_id="" if existing is None else existing.object_id,
                )
            )
            if existing is not None and saved_object.id != existing.object_id:
                raise StoreUnavailable("EA-0002 data store identity changed across ingest")
            inventory_ref = _inventory_ref(saved_object.id)
            inventory_rows = await self.inventory.ingest(
                reports=[
                    _inventory_report(
                        descriptor,
                        result=result,
                        inventory_ref=inventory_ref,
                    )
                ],
                source=DiscoverySource(
                    source_id=descriptor.source_id,
                    reliability=result.descriptor_confidence,
                    health="ok",
                    as_of=descriptor.observed_at,
                ),
                tenant_id=selected_tenant,
            )
            if len(inventory_rows) != 1 or inventory_rows[0].id != inventory_ref:
                raise StoreUnavailable("EA-0025 inventory did not accept the data store")

            status, flagged = _asset_status(result)
            asset = DataAsset(
                id=new_id("dsa") if existing is None else existing.id,
                object_id=saved_object.id,
                inventory_ref=inventory_ref,
                tenant_id=selected_tenant,
                store_id=descriptor.store_id,
                store_type=descriptor.store_type,
                location=descriptor.location.model_copy(deep=True),
                field_classifications=[item.model_copy(deep=True) for item in result.fields],
                max_known_sensitivity=_max_sensitivity(result.fields),
                classification_status=status,
                flagged=flagged,
                conflicts=[item.model_copy(deep=True) for item in result.conflicts],
                access_claims=[item.model_copy(deep=True) for item in descriptor.access_claims],
                reachability_claim=(
                    None
                    if descriptor.reachability_claim is None
                    else descriptor.reachability_claim.model_copy(deep=True)
                ),
                observed_at=descriptor.observed_at,
                evidence_id=descriptor.evidence_id,
                version=1 if existing is None else existing.version + 1,
            )
            stored.append(await self.store.put_asset(asset))
        return [item.model_copy(deep=True) for item in stored]

    async def classify(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> list[FieldClassification]:
        selected_tenant = require_tenant_id(tenant_id)
        asset = await self.store.get_asset(asset_id, tenant_id=selected_tenant)
        if asset is None:
            raise DataAssetNotFound(asset_id)
        return [item.model_copy(deep=True) for item in asset.field_classifications]

    async def analyze_exposure(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope | None = None,
    ) -> list[DataExposure]:
        selected_tenant = require_tenant_id(tenant_id)
        if self.exposure_owner is None:
            raise StoreUnavailable("EA-0023 exposure owner is unavailable")
        selected_scope = (scope or DSPMScope(limit=self.config.max_work)).model_copy(deep=True)
        assets = await self._assets_for_exposure(
            tenant_id=selected_tenant,
            scope=selected_scope,
        )
        results: list[DataExposure] = []
        for asset in assets:
            if selected_scope.store_types and asset.store_type not in selected_scope.store_types:
                continue
            claim = asset.reachability_claim
            asset_ref = AssetRef(
                kind="asset",
                ref_id=asset.inventory_ref,
                object_id=asset.object_id,
                evidence_id=asset.evidence_id if claim is None else claim.evidence_id,
            )
            owner_exposure = await self.exposure_owner.analyze_exposure(
                asset_ref=asset_ref,
                tenant_id=selected_tenant,
            )
            evidence_ids = _exposure_evidence_ids(asset, owner_exposure)
            if owner_exposure.reachability == "unknown":
                pending = _dspm_exposure(
                    asset,
                    owner_exposure,
                    state="reachability_pending",
                    sensitivity=asset.max_known_sensitivity or "unknown",
                    score=None,
                    derivation=None,
                    evidence_ids=evidence_ids,
                    reason=(
                        "Reachability was not computed by EA-0023; no exposure score was assigned."
                    ),
                )
                results.append(await self.store.put_exposure(pending))
                continue

            if asset.max_known_sensitivity in {"pii", "secret"}:
                sensitivity = asset.max_known_sensitivity
                context = ExposureImpactContext(
                    status="known",
                    factor=self.config.sensitivity_factors[sensitivity],
                    source_ref=asset.id,
                    evidence_id=asset.evidence_id,
                    reason=(
                        f"DSPM classified {asset.store_id} with maximum known "
                        f"sensitivity {sensitivity}."
                    ),
                )
                scored = await self.exposure_owner.score_exposure(
                    owner_exposure,
                    impact_context=context,
                )
                confirmed = _dspm_exposure(
                    asset,
                    scored,
                    state="confirmed",
                    sensitivity=sensitivity,
                    score=scored.score,
                    derivation=scored.derivation,
                    evidence_ids=_exposure_evidence_ids(asset, scored),
                    reason=scored.rationale,
                )
                results.append(await self.store.put_exposure(confirmed))

            if asset.classification_status != "complete":
                gap = _dspm_exposure(
                    asset,
                    owner_exposure,
                    state="classification_gap",
                    sensitivity="unknown",
                    score=None,
                    derivation=None,
                    evidence_ids=evidence_ids,
                    reason=(
                        "Reachability is known, but at least one field classification is "
                        "unknown or unresolved."
                    ),
                )
                results.append(await self.store.put_exposure(gap))
        return [item.model_copy(deep=True) for item in results]

    def explain(self, exposure: DataExposure) -> dict[str, object]:
        return {
            "exposure_id": exposure.id,
            "data_asset_id": exposure.data_asset_id,
            "state": exposure.state,
            "sensitivity": exposure.sensitivity,
            "reachability": exposure.reachability,
            "score": exposure.score,
            "reason": exposure.reason,
            "evidence_ids": list(exposure.evidence_ids),
            "derivation": (
                None if exposure.derivation is None else exposure.derivation.model_dump(mode="json")
            ),
        }

    async def access_context(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAccessContext:
        selected_tenant = require_tenant_id(tenant_id)
        asset = await self.store.get_asset(asset_id, tenant_id=selected_tenant)
        if asset is None:
            raise DataAssetNotFound(asset_id)
        claims = sorted(
            (claim.model_copy(deep=True) for claim in asset.access_claims),
            key=lambda claim: (claim.identity_id, claim.claim_kind, claim.evidence_id),
        )
        if not claims:
            return DataAccessContext(
                data_asset_id=asset.id,
                status="pending",
                claims=[],
                reason="No evidenced identity access claims were handed in for this data store.",
            )
        iag_owner = self.iag_owner
        try:
            await self._verify_access_claims(claims, tenant_id=selected_tenant)
            if iag_owner is None:
                return DataAccessContext(
                    data_asset_id=asset.id,
                    status="pending",
                    claims=claims,
                    reason="EA-0011 access context is unavailable.",
                )
            paths: list[AccessPath] = []
            for identity_id in sorted({claim.identity_id for claim in claims}):
                identity_paths = await iag_owner.access_paths(
                    identity_id,
                    tenant_id=selected_tenant,
                )
                if any(path.identity_id != identity_id for path in identity_paths):
                    raise DSPMConfigInvalid(
                        "EA-0011 returned an access path for a different identity"
                    )
                paths.extend(identity_paths)
            report = await iag_owner.analyze_risk(
                tenant_id=selected_tenant,
                scope=ObjectQuery(tenant_id=selected_tenant, limit=self.config.max_work),
            )
        except AQError as exc:
            if not exc.retriable:
                raise
            return DataAccessContext(
                data_asset_id=asset.id,
                status="pending",
                claims=claims,
                reason=f"EA-0011 access context is unavailable: {exc.code}.",
            )

        paths = _deduplicate_access_paths(paths)
        subject_ids = {claim.identity_id for claim in claims}
        for path in paths:
            if path.account_id is not None:
                subject_ids.add(path.account_id)
            subject_ids.update(path.entitlement_ids)
        risks = sorted(
            (risk.model_copy(deep=True) for risk in report.risks if risk.subject_id in subject_ids),
            key=_access_risk_key,
        )
        return DataAccessContext(
            data_asset_id=asset.id,
            status="known",
            claims=claims,
            paths=paths,
            risks=risks,
            truncated=report.truncated,
            reason=(
                "EA-0011 evaluated the evidenced identity claims and returned "
                f"{len(paths)} matching access paths and {len(risks)} matching risks."
            ),
        )

    async def data_compliance(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery,
    ) -> ComplianceSnapshot:
        selected_tenant = require_tenant_id(tenant_id)
        if scope.tenant_id not in (None, selected_tenant):
            raise CrossTenantReference(
                "compliance scope tenant does not match explicit tenant scope"
            )
        if self.compliance_owner is None:
            raise StoreUnavailable("EA-0010 data compliance owner is unavailable")
        selected_scope = scope.model_copy(
            update={"tenant_id": selected_tenant, "object_type": DATA_STORE_OBJECT_TYPE},
            deep=True,
        )
        return await self.compliance_owner.assess(
            tenant_id=selected_tenant,
            scope=selected_scope,
        )

    async def exposures_to_findings(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        propose_remediation: bool = True,
    ) -> list[str]:
        selected_tenant = require_tenant_id(tenant_id)
        if self.finding_store is None:
            raise StoreUnavailable("finding path is unavailable")
        workflow = self.workflow_engine
        if propose_remediation and workflow is None:
            raise StoreUnavailable("workflow proposal path is unavailable")
        assessment = await self.store.get_assessment(
            assessment_id,
            tenant_id=selected_tenant,
        )
        if assessment is None:
            raise DSPMConfigInvalid(f"assessment not found: {assessment_id}")
        if assessment.coverage_status != "complete":
            raise DSPMConfigInvalid(
                "findings require a complete DSPM assessment; partial coverage is not clean"
            )

        exposure_ids = list(dict.fromkeys([*assessment.exposure_ids, *assessment.gap_ids]))
        exposures: list[DataExposure] = []
        if exposure_ids:
            for exposure_id in exposure_ids:
                exposure = await self.store.get_exposure(
                    exposure_id,
                    tenant_id=selected_tenant,
                )
                if exposure is None:
                    raise DataExposureNotFound(exposure_id)
                exposures.append(exposure)
        else:
            exposures = await self.analyze_exposure(
                tenant_id=selected_tenant,
                scope=assessment.scope,
            )

        material = sorted(
            (
                exposure
                for exposure in exposures
                if exposure.state in {"confirmed", "classification_gap"}
            ),
            key=lambda exposure: (exposure.object_id, exposure.state, exposure.id),
        )
        finding_ids: list[str] = []
        for exposure in material:
            if exposure.derivation is not None:
                replay(exposure.derivation)
            finding = await self.finding_store.raise_finding(
                _finding_for_data_exposure(
                    exposure,
                    assessment_id=assessment.id,
                    by=by,
                )
            )
            finding_ids.append(finding.id)
            if propose_remediation:
                if workflow is None:
                    raise StoreUnavailable("workflow proposal path became unavailable")
                # Eligibility "none" forbids finding-driven execution. The finding id remains
                # an explicit input while this separately proposed run stays human-gated.
                await workflow.propose(
                    _data_remediation_playbook(exposure, finding=finding),
                    by=by,
                )
        return finding_ids

    async def _verify_access_claims(
        self,
        claims: Sequence[DataAccessClaim],
        *,
        tenant_id: str | None,
    ) -> None:
        for claim in claims:
            evidence = await self.evidence_store.get(claim.evidence_id, actor=self.actor)
            verification = await self.evidence_store.verify(claim.evidence_id)
            if evidence.tenant_id != tenant_id:
                raise CrossTenantReference(
                    "access-claim evidence tenant does not match the data asset"
                )
            if not verification.ok:
                raise EvidenceTampered(
                    "access-claim evidence failed integrity verification",
                    details={"evidence_id": claim.evidence_id},
                )

    async def _assets_for_exposure(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope,
    ) -> list[DataAsset]:
        budget = min(scope.limit, self.config.max_work)
        cursor = scope.cursor
        seen_cursors: set[str] = set()
        assets: list[DataAsset] = []
        while len(assets) < budget:
            page, next_cursor = await self.store.query_assets(
                tenant_id=tenant_id,
                flagged=scope.flagged,
                limit=min(self.config.batch_size, budget - len(assets)),
                cursor=cursor,
            )
            assets.extend(page)
            if next_cursor is None:
                return assets
            if not page:
                raise StoreUnavailable("DSPMStore returned an empty page with a cursor")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise StoreUnavailable("DSPMStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        if cursor is not None:
            raise StoreUnavailable("DSPM exposure analysis exceeded its work budget")
        return assets

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope | None = None,
    ) -> DataPostureAssessment:
        selected_tenant = require_tenant_id(tenant_id)
        selected_scope = (scope or DSPMScope()).model_copy(deep=True)
        budget = min(selected_scope.limit, self.config.max_work)
        cursor = selected_scope.cursor
        seen_cursors: set[str] = set()
        stores_evaluated = 0
        classified_fields = 0
        unknown_fields = 0
        work = 0

        while work < budget:
            page_limit = min(self.config.batch_size, budget - work)
            try:
                rows, next_cursor = await self.store.query_assets(
                    tenant_id=selected_tenant,
                    flagged=selected_scope.flagged,
                    limit=page_limit,
                    cursor=cursor,
                )
            except AQError as exc:
                if not exc.retriable:
                    raise
                if work == 0:
                    return DataPostureAssessment(
                        tenant_id=selected_tenant,
                        run_at=utc_now(),
                        scope=selected_scope,
                        coverage_status="pending",
                        coverage_reason=f"DSPM store unavailable: {exc.code}",
                    )
                if cursor is None:
                    raise StoreUnavailable("DSPM pagination lost its continuation cursor") from exc
                assessment = DataPostureAssessment(
                    tenant_id=selected_tenant,
                    run_at=utc_now(),
                    scope=selected_scope,
                    coverage_status="truncated",
                    coverage_reason=f"DSPM store unavailable: {exc.code}",
                    next_cursor=cursor,
                    stores_evaluated=stores_evaluated,
                    classified_fields=classified_fields,
                    unknown_fields=unknown_fields,
                )
                return await self.store.put_assessment(assessment)

            work += len(rows)
            for asset in rows:
                if (
                    selected_scope.store_types
                    and asset.store_type not in selected_scope.store_types
                ):
                    continue
                stores_evaluated += 1
                classified_fields += sum(
                    item.status == "known" for item in asset.field_classifications
                )
                unknown_fields += sum(
                    item.status != "known" for item in asset.field_classifications
                )

            if next_cursor is None:
                assessment = DataPostureAssessment(
                    tenant_id=selected_tenant,
                    run_at=utc_now(),
                    scope=selected_scope,
                    coverage_status="complete",
                    stores_evaluated=stores_evaluated,
                    classified_fields=classified_fields,
                    unknown_fields=unknown_fields,
                )
                return await self.store.put_assessment(assessment)
            if not rows:
                raise StoreUnavailable("DSPMStore returned an empty page with a cursor")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise StoreUnavailable("DSPMStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        if cursor is None:
            raise StoreUnavailable("DSPM assessment exhausted work without a continuation cursor")
        assessment = DataPostureAssessment(
            tenant_id=selected_tenant,
            run_at=utc_now(),
            scope=selected_scope,
            coverage_status="truncated",
            coverage_reason="truncated",
            next_cursor=cursor,
            stores_evaluated=stores_evaluated,
            classified_fields=classified_fields,
            unknown_fields=unknown_fields,
        )
        return await self.store.put_assessment(assessment)

    def _validate_descriptor(
        self,
        descriptor: DataStoreDescriptor,
        *,
        tenant_id: str | None,
    ) -> None:
        if descriptor.tenant_id != tenant_id:
            raise CrossTenantReference("descriptor tenant does not match explicit tenant scope")
        if len(descriptor.fields) > self.config.max_fields_per_store:
            raise DSPMConfigInvalid("descriptor exceeds max_fields_per_store")
        if any(
            len(field.signals) > self.config.max_signals_per_field for field in descriptor.fields
        ):
            raise DSPMConfigInvalid("descriptor field exceeds max_signals_per_field")


def _deduplicate_access_paths(paths: Sequence[AccessPath]) -> list[AccessPath]:
    selected: dict[tuple[object, ...], AccessPath] = {}
    for path in paths:
        key = (
            path.identity_id,
            path.account_id,
            tuple(path.entitlement_ids),
            tuple(path.via.node_ids),
            tuple(edge.id for edge in path.via.edges),
        )
        selected[key] = path.model_copy(deep=True)
    return [selected[key] for key in sorted(selected, key=repr)]


def _access_risk_key(risk: AccessRisk) -> tuple[str, str, str]:
    return risk.subject_id, risk.kind, risk.reason


def _finding_for_data_exposure(
    exposure: DataExposure,
    *,
    assessment_id: str,
    by: ActorRef,
) -> Finding:
    confirmed = exposure.state == "confirmed"
    score = exposure.score if exposure.score is not None else 50.0
    severity = _finding_severity(score) if confirmed else "medium"
    title = (
        f"Sensitive data exposure on {exposure.object_id}"
        if confirmed
        else f"Data classification gap on {exposure.object_id}"
    )
    action = "data.restrict_access" if confirmed else "data.review_classification"
    return Finding(
        id=new_id("fnd"),
        tenant_id=exposure.tenant_id,
        finding_type="data_exposure" if confirmed else "data_classification_gap",
        schema_version=1,
        dedup_key=f"dspm:{exposure.object_id}:{exposure.state}",
        title=title,
        severity=severity,
        severity_score=round(score, 6),
        status="open",
        what_happened=exposure.reason,
        why_it_matters=(
            "Sensitive data with known reachability can increase the impact of unauthorized access."
            if confirmed
            else "Known reachability combined with incomplete classification can hide material "
            "data exposure."
        ),
        how_determined=(
            "DSPM intersected metadata-only classification with EA-0023 reachability and cited "
            "the evidence-backed owner records; it did not inspect data content."
        ),
        risk_of_inaction=(
            "Leaving this condition unresolved can expose sensitive data or preserve an "
            "unmeasured data-security gap."
        ),
        evidence_ids=list(exposure.evidence_ids),
        affected_object_ids=[exposure.object_id],
        expert_details={
            "assessment_id": assessment_id,
            "data_exposure_id": exposure.id,
            "data_asset_id": exposure.data_asset_id,
            "exposure_ref": exposure.exposure_ref,
            "state": exposure.state,
            "sensitivity": exposure.sensitivity,
            "reachability": exposure.reachability,
            "derivation": (
                None if exposure.derivation is None else exposure.derivation.model_dump(mode="json")
            ),
            "proposed_action": action,
            "requested_by": by.model_dump(mode="json"),
        },
        remediation=Remediation(
            summary="Review the evidence and route any change through the Workflow Engine.",
            steps=[
                "Validate the cited classification and reachability evidence.",
                "Decide whether access or classification metadata must change.",
                "Use the gated workflow proposal before changing the source system.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The exposure is reduced or the classification gap is resolved.",
        ),
        automation=Automation(
            eligibility="none",
            action_ref=None,
            requires_approval=True,
            risk_note="DSPM raises findings and proposes gated runs; it never acts directly.",
        ),
        confidence=1.0,
        source_engine="dspm_engine",
        correlation_id=assessment_id,
        first_detected_at=exposure.detected_at,
        last_detected_at=exposure.detected_at,
    )


def _data_remediation_playbook(
    exposure: DataExposure,
    *,
    finding: Finding,
) -> Playbook:
    action = (
        "data.restrict_access" if exposure.state == "confirmed" else "data.review_classification"
    )
    return Playbook(
        id=f"dspm-{action.replace('.', '-')}-{finding.id}",
        version=1,
        name=(
            "Propose data access restriction"
            if exposure.state == "confirmed"
            else "Propose data classification review"
        ),
        description=(
            "DSPM proposes remediation only; EA-0008 re-validates capability and approval "
            "before any execution."
        ),
        tenant_id=exposure.tenant_id,
        steps=[
            Step(
                id="review-and-remediate",
                action_type=action,
                inputs={
                    "data_asset_id": exposure.data_asset_id,
                    "object_id": exposure.object_id,
                    "exposure_id": exposure.id,
                    "finding_id": finding.id,
                    "evidence_ids": list(exposure.evidence_ids),
                },
                idempotency_key=f"dspm:{finding.id}:{action}",
                requires_approval=True,
            )
        ],
    )


def _finding_severity(score: float) -> Severity:
    if score >= 90.0:
        return "critical"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    return "low"


def _data_store_object(
    descriptor: DataStoreDescriptor,
    *,
    result: ClassificationResult,
    actor: ActorRef,
    object_id: str,
) -> AQObject:
    status, flagged = _asset_status(result)
    maximum = _max_sensitivity(result.fields)
    source = SourceRef(
        source_id=descriptor.source_id,
        evidence_id=descriptor.evidence_id,
        observed_at=descriptor.observed_at,
        method="dspm.metadata_descriptor/v1",
    )
    now = descriptor.observed_at
    return AQObject(
        id=object_id,
        object_type=DATA_STORE_OBJECT_TYPE,
        schema_version=1,
        tenant_id=descriptor.tenant_id,
        display_name=descriptor.store_id,
        attributes={
            "store_id": descriptor.store_id,
            "store_type": descriptor.store_type,
            "location": descriptor.location.model_dump(mode="json"),
            "field_classifications": [
                {
                    "field": item.field,
                    "classification": item.classification,
                    "status": item.status,
                    "flagged": item.flagged,
                }
                for item in result.fields
            ],
            "max_known_sensitivity": maximum,
            "classification_status": status,
            "flagged": flagged,
        },
        labels={"module": "EA-0031", "kind": DATA_STORE_OBJECT_TYPE},
        natural_keys=[NaturalKey(namespace="dspm:store", value=descriptor.store_id)],
        sources=[source],
        confidence=result.descriptor_confidence,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
    )


def _inventory_report(
    descriptor: DataStoreDescriptor,
    *,
    result: ClassificationResult,
    inventory_ref: str,
) -> dict[str, object]:
    return {
        "id": inventory_ref,
        "asset_type": DATA_STORE_OBJECT_TYPE,
        "classification": _max_sensitivity(result.fields) or "unknown",
        "lifecycle_state": "active",
        "evidence_id": descriptor.evidence_id,
        "ref": f"dspm:{descriptor.store_id}",
    }


def _inventory_ref(object_id: str) -> str:
    prefix, payload = parse_id(object_id)
    if prefix != "obj":
        raise StoreUnavailable("EA-0002 data store id must use obj_ prefix")
    # Preserve one stable payload while keeping each owner's typed identity distinct.
    return f"ast_{payload}"


def _max_sensitivity(fields: Sequence[FieldClassification]) -> Classification | None:
    known = {item.classification for item in fields if item.status == "known"}
    maximum: Classification | None = None
    for classification in classification_order():
        if classification in known:
            maximum = classification
    return maximum


def _asset_status(result: ClassificationResult) -> tuple[AssetClassificationStatus, bool]:
    known = [item for item in result.fields if item.status == "known"]
    non_known = [item for item in result.fields if item.status != "known"]
    if any(item.status == "conflict" for item in result.fields):
        return "conflict", True
    if known and not non_known:
        return "complete", False
    if known:
        return "partial", True
    return "unknown", True


def _exposure_evidence_ids(
    asset: DataAsset,
    exposure: ExposureRecord,
) -> list[str]:
    values = [asset.evidence_id]
    values.extend(basis.evidence_id for basis in exposure.basis if basis.evidence_id is not None)
    if exposure.asset_ref.evidence_id is not None:
        values.append(exposure.asset_ref.evidence_id)
    if exposure.impact_context is not None:
        values.append(exposure.impact_context.evidence_id)
    return sorted(set(values))


def _dspm_exposure(
    asset: DataAsset,
    owner: ExposureRecord,
    *,
    state: str,
    sensitivity: str,
    score: float | None,
    derivation: object,
    evidence_ids: list[str],
    reason: str,
) -> DataExposure:
    return DataExposure.model_validate(
        {
            "tenant_id": asset.tenant_id,
            "data_asset_id": asset.id,
            "object_id": asset.object_id,
            "exposure_ref": owner.id,
            "sensitivity": sensitivity,
            "reachability": owner.reachability,
            "state": state,
            "flagged": state != "confirmed",
            "score": score,
            "derivation": derivation,
            "access_evidence_ids": [],
            "reason": reason,
            "evidence_ids": evidence_ids,
            "detected_at": owner.discovered_at,
        }
    )
