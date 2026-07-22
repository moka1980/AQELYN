"""Identity Security Posture Management engine (EA-0033 G2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import (
    AQError,
    CrossTenantReference,
    EvidenceNotFound,
    EvidenceTampered,
    FindingNotFound,
    IdentityBaselineNotFound,
    IdentityNotFound,
    ISPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceStore
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.exposure import ExposureRecord
from aqelyn.findings import Finding, FindingStore
from aqelyn.iag import AccessPath, AccessRiskReport, Certification
from aqelyn.inventory import DiscoverySource
from aqelyn.ispm.drift import drift_snapshot, identity_drift_items, validate_drift_scope
from aqelyn.ispm.exposure import (
    IdentityExposureOwner,
    identity_asset_ref,
    identity_impact_context,
    validate_identity_exposure,
)
from aqelyn.ispm.governance import (
    IdentityGovernanceOwner,
    complete_certification,
    decide_certification_item,
    governance_context,
    identity_access_paths,
    open_certification,
    risks_to_findings,
)
from aqelyn.ispm.models import (
    IdentityDescriptor,
    IdentityDriftItem,
    IdentityDriftSnapshot,
    IdentityPostureScore,
    ISPMAssessment,
    ISPMConfig,
    NormalizedIdentity,
)
from aqelyn.ispm.normalize import (
    HAS_ACCOUNT,
    IdentityInventoryOwner,
    IdentityObjectStore,
    PreparedIdentity,
    TrustAssessor,
    account_object,
    ensure_identity_object_types,
    identity_object,
    inventory_ownership,
    inventory_report,
    new_normalized_identity,
    ownership_state,
    prepare_identity,
    reconcile_identity,
    relationship,
    validate_edge_target,
)
from aqelyn.ispm.scoring import IdentityMissionOwner, compose_posture, validate_replayable_score
from aqelyn.ispm.store import ISPMStore
from aqelyn.objects import AQObject, AQRelationship, NaturalKey, ObjectQuery
from aqelyn.risk import RiskConfig
from aqelyn.workflow import Playbook, Step, WorkflowEngine

_ISPM_ACTOR = ActorRef(actor_type="system", actor_id="ispm_engine")


class ISPMEngine:
    def __init__(
        self,
        store: ISPMStore,
        *,
        object_store: IdentityObjectStore,
        inventory: IdentityInventoryOwner,
        evidence_store: EvidenceStore,
        trust: TrustAssessor,
        governance_owner: IdentityGovernanceOwner | None = None,
        mission_owner: IdentityMissionOwner | None = None,
        exposure_owner: IdentityExposureOwner | None = None,
        finding_store: FindingStore | None = None,
        workflow_engine: WorkflowEngine | None = None,
        risk_config: RiskConfig | None = None,
        config: ISPMConfig | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.trust = trust
        self.governance_owner = governance_owner
        self.mission_owner = mission_owner
        self.exposure_owner = exposure_owner
        self.finding_store = finding_store
        self.workflow_engine = workflow_engine
        self.risk_config = risk_config or RiskConfig()
        self.config = config or ISPMConfig()
        self.actor = actor or _ISPM_ACTOR
        self.source_id = source_id or new_id("src")
        ensure_identity_object_types(object_store)

    async def governance_context(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> AccessRiskReport:
        selected_tenant = require_tenant_id(tenant_id)
        identity = await self.store.get_identity(object_id, tenant_id=selected_tenant)
        if identity is None:
            raise IdentityNotFound(object_id)
        return await governance_context(
            self._governance_owner(),
            tenant_id=selected_tenant,
            scope=ObjectQuery(
                tenant_id=selected_tenant,
                limit=self.config.page_budget,
            ),
        )

    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None,
    ) -> list[AccessPath]:
        selected_tenant = require_tenant_id(tenant_id)
        identity = await self.store.get_identity(identity_id, tenant_id=selected_tenant)
        if identity is None:
            raise IdentityNotFound(identity_id)
        return await identity_access_paths(
            self._governance_owner(),
            identity_id,
            tenant_id=selected_tenant,
        )

    async def open_certification(
        self,
        *,
        tenant_id: str | None,
        name: str,
        scope: ObjectQuery,
        by: ActorRef,
        due_days: int | None = None,
    ) -> Certification:
        return await open_certification(
            self._governance_owner(),
            tenant_id=require_tenant_id(tenant_id),
            name=name,
            scope=scope,
            by=by,
            due_days=due_days,
        )

    async def decide_certification_item(
        self,
        cert_id: str,
        item_id: str,
        *,
        decision: str,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Certification:
        return await decide_certification_item(
            self._governance_owner(),
            cert_id,
            item_id,
            decision=decision,
            by=by,
            note=note,
            expected_version=expected_version,
        )

    async def complete_certification(
        self,
        cert_id: str,
        *,
        by: ActorRef,
        raise_findings: bool = True,
    ) -> list[str]:
        return await complete_certification(
            self._governance_owner(),
            cert_id,
            by=by,
            raise_findings=raise_findings,
        )

    async def risks_to_findings(
        self,
        report: AccessRiskReport,
        *,
        by: ActorRef,
        prioritize: bool = True,
        tenant_id: str | None = None,
    ) -> list[str]:
        return await risks_to_findings(
            self._governance_owner(),
            report,
            by=by,
            prioritize=prioritize,
            tenant_id=require_tenant_id(tenant_id),
        )

    def _governance_owner(self) -> IdentityGovernanceOwner:
        if self.governance_owner is None:
            raise StoreUnavailable("EA-0011 governance owner is unavailable")
        return self.governance_owner

    async def score_identity(
        self,
        account_object_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityPostureScore:
        selected_tenant = require_tenant_id(tenant_id)
        identity = await self._identity_for_account(
            account_object_id,
            tenant_id=selected_tenant,
        )
        report = await self.governance_context(
            identity.object_id,
            tenant_id=selected_tenant,
        )
        if report.truncated:
            raise StoreUnavailable("EA-0011 risk report was truncated")
        if self.mission_owner is None:
            raise StoreUnavailable("EA-0007 mission owner is unavailable")
        subject_ids = {identity.object_id, account_object_id}
        risks = [risk for risk in report.risks if risk.subject_id in subject_ids]
        evidence = await self._verified_score_evidence(identity)
        computed_at = utc_now()
        trust = await self.trust.assess(
            f"ispm:{account_object_id}",
            evidence,
            now=max(record.collected_at for record in evidence),
        )
        mission = await self.mission_owner.mission_impact(account_object_id)
        composed = compose_posture(
            identity,
            account_object_id,
            iag_risks=risks,
            trust=trust,
            mission=mission,
            factor_weights=self.config.factor_weights,
            risk_config=self.risk_config,
            computed_at=computed_at,
        )
        score_id = new_id("ips")
        result_evidence = await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=selected_tenant,
                evidence_type="ispm.posture_score",
                schema_version=1,
                subject=Subject(object_ids=sorted(subject_ids)),
                collected_at=computed_at,
                recorded_at=computed_at,
                collector=self.actor,
                source_id=self.source_id,
                method="ispm.posture_score/v1",
                content={
                    "score_id": score_id,
                    "subject_ref": account_object_id,
                    "score": composed.score,
                    "factors": [
                        {
                            "name": factor.name,
                            "status": factor.status,
                            "value": factor.value,
                            "weight": factor.weight,
                        }
                        for factor in composed.factors
                    ],
                    "iag_risk_count": len(composed.iag_risks),
                    "metadata_only": True,
                },
                content_hash="",
                confidence=composed.confidence,
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        score = IdentityPostureScore(
            id=score_id,
            tenant_id=selected_tenant,
            subject_ref=account_object_id,
            score=composed.score,
            factors=composed.factors,
            iag_risks=composed.iag_risks,
            derivation=composed.derivation,
            confidence=composed.confidence,
            statement=composed.statement,
            computed_at=computed_at,
            evidence_id=result_evidence.id,
        )
        return await self.store.put_score(score)

    def explain(self, score: IdentityPostureScore) -> dict[str, object]:
        stored = validate_replayable_score(score)
        return {
            "score_id": stored.id,
            "subject_ref": stored.subject_ref,
            "score": stored.score,
            "statement": stored.statement,
            "confidence": stored.confidence,
            "factors": [factor.model_dump(mode="json") for factor in stored.factors],
            "iag_risks": [risk.model_dump(mode="json") for risk in stored.iag_risks],
            "inputs": [item.model_dump(mode="json") for item in stored.derivation.inputs],
            "steps": [step.model_dump(mode="json") for step in stored.derivation.steps],
            "result": stored.derivation.result,
        }

    async def detect_drift(
        self,
        *,
        baseline_id: str,
        tenant_id: str | None,
        scope: dict[str, object] | None = None,
    ) -> IdentityDriftSnapshot:
        selected_tenant = require_tenant_id(tenant_id)
        baseline = await self.store.get_baseline(
            baseline_id,
            tenant_id=selected_tenant,
        )
        if baseline is None:
            raise IdentityBaselineNotFound(baseline_id)
        if baseline.approved_by is None or baseline.approved_at is None:
            raise ISPMConfigInvalid("identity drift requires an approved baseline")
        provider = validate_drift_scope(scope)
        items: list[IdentityDriftItem] = []
        cursor: str | None = None
        next_cursor: str | None = None
        seen_cursors: set[str] = set()
        evaluated_identities = 0
        while evaluated_identities < self.config.page_budget:
            remaining = self.config.page_budget - evaluated_identities
            rows, next_cursor = await self.store.query_identities(
                tenant_id=selected_tenant,
                provider=provider,
                identity_kind=baseline.identity_kind,
                cursor=cursor,
                limit=min(100, remaining),
            )
            for identity in rows:
                established = await self._established_control_evidence(identity)
                items.extend(
                    identity_drift_items(
                        identity,
                        baseline,
                        established_evidence=established,
                    )
                )
            evaluated_identities += len(rows)
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise StoreUnavailable("ISPMStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        if next_cursor is not None and evaluated_identities >= self.config.page_budget:
            raise StoreUnavailable("identity drift scope exceeds page_budget")
        run_at = utc_now()
        snapshot_id = new_id("idr")
        evidence = await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=selected_tenant,
                evidence_type="ispm.identity_drift",
                schema_version=1,
                subject=Subject(object_ids=sorted({item.identity_id for item in items})),
                collected_at=run_at,
                recorded_at=run_at,
                collector=self.actor,
                source_id=self.source_id,
                method="ispm.identity_drift/v1",
                content={
                    "snapshot_id": snapshot_id,
                    "baseline_id": baseline.id,
                    "baseline_version": baseline.version,
                    "evaluated": len(items),
                    "passed": sum(item.status == "pass" for item in items),
                    "failed": sum(item.status == "fail" for item in items),
                    "unknown": sum(item.status == "unknown" for item in items),
                    "metadata_only": True,
                },
                content_hash="",
                confidence=1.0,
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        snapshot = drift_snapshot(
            snapshot_id=snapshot_id,
            tenant_id=selected_tenant,
            baseline=baseline,
            items=items,
            run_at=run_at,
            evidence_id=evidence.id,
        )
        return await self.store.put_drift(snapshot)

    async def analyze_identity_exposure(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> ExposureRecord:
        selected_tenant = require_tenant_id(tenant_id)
        score = await self.store.get_score(score_id, tenant_id=selected_tenant)
        if score is None:
            raise IdentityNotFound(score_id)
        owner = self.exposure_owner
        if owner is None:
            raise StoreUnavailable("EA-0023 identity exposure owner is unavailable")
        context = identity_impact_context(score)
        exposure = await owner.analyze_scored_exposure(
            asset_ref=identity_asset_ref(score),
            impact_context=context,
            tenant_id=selected_tenant,
        )
        return validate_identity_exposure(exposure, score=score, context=context)

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: dict[str, object] | None = None,
    ) -> ISPMAssessment:
        selected_tenant = require_tenant_id(tenant_id)
        selected_scope = _assessment_scope(scope)
        selected_provider = selected_scope.get("provider")
        if selected_provider is not None and not isinstance(selected_provider, str):
            raise ISPMConfigInvalid("assessment provider must be a string")
        run_at = utc_now()
        inventory_note = await self._inventory_note(tenant_id=selected_tenant)
        score_ids: list[str] = []
        subject_ids: set[str] = set()
        identities_evaluated = 0
        unknown_controls = 0
        cursor: str | None = None
        seen_cursors: set[str] = set()
        status = "computed"
        incomplete_reason: str | None = None

        try:
            while identities_evaluated < self.config.page_budget:
                remaining = self.config.page_budget - identities_evaluated
                rows, next_cursor = await self.store.query_identities(
                    tenant_id=selected_tenant,
                    provider=selected_provider,
                    cursor=cursor,
                    limit=min(100, remaining),
                )
                stopped_inside_identity = False
                for identity in rows:
                    if not identity.account_object_ids:
                        identities_evaluated += 1
                        unknown_controls += 3
                        continue
                    for account_id in identity.account_object_ids:
                        if identities_evaluated >= self.config.page_budget:
                            stopped_inside_identity = True
                            break
                        score = await self.score_identity(
                            account_id,
                            tenant_id=selected_tenant,
                        )
                        score_ids.append(score.id)
                        subject_ids.add(score.subject_ref)
                        unknown_controls += sum(
                            factor.status == "unknown"
                            for factor in score.factors
                            if factor.name != "iag_risk"
                        )
                        identities_evaluated += 1
                    if stopped_inside_identity:
                        break
                if stopped_inside_identity:
                    status = "truncated"
                    incomplete_reason = "page_budget exhausted within a normalized identity"
                    break
                if next_cursor is None:
                    break
                if next_cursor == cursor or next_cursor in seen_cursors:
                    raise StoreUnavailable("ISPMStore returned a repeated pagination cursor")
                if identities_evaluated >= self.config.page_budget:
                    status = "truncated"
                    incomplete_reason = "page_budget exhausted before cursor completion"
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        except AQError as exc:
            if not exc.retriable:
                raise
            status = "pending" if identities_evaluated == 0 else "truncated"
            incomplete_reason = exc.message

        if status == "pending":
            return await self.store.put_assessment(
                ISPMAssessment(
                    tenant_id=selected_tenant,
                    run_at=run_at,
                    scope=selected_scope,
                    status="pending",
                    inventory_complete=False,
                    inventory_note=f"{inventory_note} Assessment pending: {incomplete_reason}.",
                )
            )

        drift_snapshot_id: str | None = None
        if self.config.baseline_ids:
            snapshot = await self.detect_drift(
                baseline_id=self.config.baseline_ids[0],
                tenant_id=selected_tenant,
                scope=selected_scope,
            )
            drift_snapshot_id = snapshot.id
        assessment_id = new_id("ipa")
        evidence = await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=selected_tenant,
                evidence_type="ispm.assessment",
                schema_version=1,
                subject=Subject(object_ids=sorted(subject_ids)),
                collected_at=run_at,
                recorded_at=run_at,
                collector=self.actor,
                source_id=self.source_id,
                method="ispm.assessment/v1",
                content={
                    "assessment_id": assessment_id,
                    "status": status,
                    "identities_evaluated": identities_evaluated,
                    "score_ids": score_ids,
                    "unknown_controls": unknown_controls,
                    "drift_snapshot_id": drift_snapshot_id,
                    "inventory_complete": False,
                    "inventory_note": inventory_note,
                    "incomplete_reason": incomplete_reason,
                    "metadata_only": True,
                },
                content_hash="",
                confidence=1.0,
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        assessment = ISPMAssessment(
            id=assessment_id,
            tenant_id=selected_tenant,
            run_at=run_at,
            scope=selected_scope,
            identities_evaluated=identities_evaluated,
            scored=len(score_ids),
            score_ids=score_ids,
            unknown_controls=unknown_controls,
            drift_snapshot_id=drift_snapshot_id,
            status=status,
            inventory_complete=False,
            inventory_note=(
                inventory_note
                if incomplete_reason is None
                else f"{inventory_note} Assessment truncated: {incomplete_reason}."
            ),
            evidence_id=evidence.id,
        )
        return await self.store.put_assessment(assessment)

    async def posture_to_findings(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        propose_remediation: bool = True,
    ) -> list[str]:
        selected_tenant = require_tenant_id(tenant_id)
        assessment = await self.store.get_assessment(
            assessment_id,
            tenant_id=selected_tenant,
        )
        if assessment is None:
            raise ISPMConfigInvalid(f"assessment not found: {assessment_id}")
        if assessment.status != "computed":
            raise ISPMConfigInvalid("findings require a computed, non-truncated assessment")
        risks = []
        seen_risks: set[str] = set()
        for score_id in assessment.score_ids:
            score = await self.store.get_score(score_id, tenant_id=selected_tenant)
            if score is None:
                raise StoreUnavailable(f"assessment score is unavailable: {score_id}")
            for risk in score.iag_risks:
                key = risk.model_dump_json()
                if key not in seen_risks:
                    risks.append(risk)
                    seen_risks.add(key)
        report = AccessRiskReport(
            risks=risks,
            evaluated=assessment.identities_evaluated,
            truncated=False,
        )
        finding_ids = await risks_to_findings(
            self._governance_owner(),
            report,
            by=by,
            prioritize=True,
            tenant_id=selected_tenant,
        )
        if not propose_remediation:
            return finding_ids
        if self.finding_store is None:
            raise StoreUnavailable("ISPM finding read path is unavailable")
        if self.workflow_engine is None:
            raise StoreUnavailable("EA-0008 ISPM proposal path is unavailable")
        for finding_id in finding_ids:
            finding = await self.finding_store.get(finding_id)
            if finding is None:
                raise FindingNotFound(finding_id)
            if finding.tenant_id != selected_tenant:
                raise CrossTenantReference("finding tenant does not match ISPM assessment")
            await self.workflow_engine.propose(
                _remediation_playbook(finding),
                by=by,
                source_finding=finding,
            )
        return finding_ids

    async def _inventory_note(self, *, tenant_id: str | None) -> str:
        try:
            report = await self.inventory.inventory(tenant_id=tenant_id)
        except AQError as exc:
            if exc.retriable:
                return f"EA-0025 inventory unavailable: {exc.message}"
            raise
        return (
            "EA-0025 reported "
            f"{report.total} assets, but ECR-0034's 10,000-row cap is unresolved; "
            "the inventory is not claimed exhaustive."
        )

    async def _identity_for_account(
        self,
        account_object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        evaluated = 0
        while evaluated < self.config.page_budget:
            remaining = self.config.page_budget - evaluated
            rows, next_cursor = await self.store.query_identities(
                tenant_id=tenant_id,
                cursor=cursor,
                limit=min(100, remaining),
            )
            matches = [
                identity for identity in rows if account_object_id in identity.account_object_ids
            ]
            if matches:
                if len(matches) != 1:
                    raise ISPMConfigInvalid(
                        "account object belongs to multiple normalized identities"
                    )
                return matches[0]
            evaluated += len(rows)
            if next_cursor is None:
                raise IdentityNotFound(account_object_id)
            if next_cursor in seen_cursors:
                raise StoreUnavailable("ISPMStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise StoreUnavailable("account lookup exceeds page_budget")

    async def _verified_score_evidence(
        self,
        identity: NormalizedIdentity,
    ) -> list[EvidenceRecord]:
        evidence_ids = {identity.evidence_id}
        evidence_ids.update(
            fact.evidence_id
            for fact in (
                identity.controls.mfa,
                identity.controls.lifecycle,
                identity.controls.last_activity,
            )
            if fact.evidence_id is not None
        )
        records: list[EvidenceRecord] = []
        for evidence_id in sorted(evidence_ids):
            record = await self.evidence_store.get(evidence_id, actor=self.actor)
            if record.tenant_id != identity.tenant_id:
                raise CrossTenantReference("ISPM score evidence belongs to another tenant")
            verification = await self.evidence_store.verify(evidence_id)
            if not verification.ok:
                raise EvidenceTampered(
                    verification.detail or "ISPM score evidence failed verification"
                )
            records.append(record)
        if not records:
            raise StoreUnavailable("ISPM score requires evidence")
        return records

    async def _established_control_evidence(
        self,
        identity: NormalizedIdentity,
    ) -> dict[str, bool]:
        evidence_ids = {
            fact.evidence_id
            for fact in (
                identity.controls.mfa,
                identity.controls.lifecycle,
                identity.controls.last_activity,
            )
            if fact.evidence_id is not None
        }
        established: dict[str, bool] = {}
        for evidence_id in sorted(evidence_ids):
            try:
                record = await self.evidence_store.get(evidence_id, actor=self.actor)
                if record.tenant_id != identity.tenant_id:
                    raise CrossTenantReference("ISPM control evidence belongs to another tenant")
                established[evidence_id] = (await self.evidence_store.verify(evidence_id)).ok
            except (EvidenceNotFound, EvidenceTampered):
                established[evidence_id] = False
        return established

    async def ingest_identities(
        self,
        descriptors: Sequence[IdentityDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[NormalizedIdentity]:
        selected_tenant = require_tenant_id(tenant_id)
        if len(descriptors) > self.config.batch_size:
            raise ISPMConfigInvalid(
                "identity descriptor count exceeds batch_size; partial acceptance is forbidden"
            )
        prepared = [
            await prepare_identity(
                descriptor,
                evidence_store=self.evidence_store,
                trust=self.trust,
                actor=self.actor,
                tenant_id=selected_tenant,
            )
            for descriptor in descriptors
        ]
        await self._validate_edge_targets(prepared, tenant_id=selected_tenant)
        stored = [await self._persist(item, tenant_id=selected_tenant) for item in prepared]
        return [item.model_copy(deep=True) for item in stored]

    async def _persist(
        self,
        prepared: PreparedIdentity,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity:
        descriptor = prepared.descriptor
        existing = await self.store.get_identity_by_external(
            descriptor.provider,
            descriptor.external_id,
            tenant_id=tenant_id,
        )
        incoming = new_normalized_identity(
            prepared,
            object_id=existing.object_id if existing is not None else new_id("obj"),
            tenant_id=tenant_id,
        )
        reconciled = await reconcile_identity(
            existing,
            incoming,
            incoming_evidence=prepared.evidence,
            incoming_confidence=prepared.confidence,
            evidence_store=self.evidence_store,
            trust=self.trust,
            actor=self.actor,
            observed_at=descriptor.observed_at,
        )
        current_object = (
            None
            if existing is None
            else await self.object_store.get(existing.object_id, resolve_merged=False)
        )
        selected_attributes = (
            descriptor.attributes
            if reconciled.incoming_won or current_object is None
            else current_object.attributes
        )
        selected_evidence = (
            prepared.evidence
            if reconciled.incoming_won
            else await self.evidence_store.get(reconciled.identity.evidence_id, actor=self.actor)
        )
        saved_identity = await self._upsert_object(
            identity_object(
                reconciled.identity,
                attributes=selected_attributes,
                source=selected_evidence,
                confidence=reconciled.confidence,
                actor=self.actor,
                observed_at=selected_evidence.collected_at,
            ),
            selected_confidence=reconciled.confidence,
        )
        if saved_identity.id != reconciled.identity.object_id:
            raise StoreUnavailable("EA-0002 identity changed across ISPM ingest")

        account_ids = set(reconciled.identity.account_object_ids)
        relationship_ids = set(reconciled.identity.relationship_ids)
        conflicts = list(reconciled.identity.conflicts)
        local_objects: dict[str, AQObject] = {descriptor.external_id: saved_identity}
        ownership_claim = descriptor.ownership
        if ownership_claim is None:
            identity_owner = None
            identity_inventory_evidence = prepared.evidence
            identity_inventory_confidence = prepared.confidence
            identity_inventory_observed_at = descriptor.observed_at
        else:
            if prepared.ownership_evidence is None or prepared.ownership_confidence is None:
                raise StoreUnavailable("prepared ownership claim is missing verified provenance")
            identity_owner = inventory_ownership(ownership_claim)
            identity_inventory_evidence = prepared.ownership_evidence
            identity_inventory_confidence = prepared.ownership_confidence
            identity_inventory_observed_at = ownership_claim.observed_at
        inventory_requests: list[tuple[dict[str, object], DiscoverySource]] = [
            (
                inventory_report(
                    saved_identity,
                    evidence_id=identity_inventory_evidence.id,
                    owner=identity_owner,
                ),
                DiscoverySource(
                    source_id=identity_inventory_evidence.source_id,
                    reliability=identity_inventory_confidence,
                    health="ok",
                    as_of=identity_inventory_observed_at,
                ),
            )
        ]
        for account in descriptor.accounts:
            evidence = prepared.account_evidence[account.external_id]
            confidence = prepared.account_confidence[account.external_id]
            account_candidate = account_object(
                account,
                provider=descriptor.provider,
                tenant_id=tenant_id,
                source=evidence,
                confidence=confidence,
                actor=self.actor,
            )
            selected_account, account_conflict = await self._reconcile_account(
                account_candidate,
                external_id=account.external_id,
                incoming_source=evidence,
                incoming_confidence=confidence,
                tenant_id=tenant_id,
            )
            if account_conflict is not None and account_conflict not in conflicts:
                conflicts.append(account_conflict)
            saved_account = await self._upsert_object(
                selected_account,
                selected_confidence=selected_account.confidence,
            )
            local_objects[account.external_id] = saved_account
            account_ids.add(saved_account.id)
            rel = await self._ensure_relationship(
                from_id=saved_identity.id,
                to_id=saved_account.id,
                relation_type=HAS_ACCOUNT,
                tenant_id=tenant_id,
                source=evidence,
                confidence=confidence,
                observed_at=account.observed_at,
            )
            relationship_ids.add(rel.id)
            inventory_requests.append(
                (
                    inventory_report(saved_account, evidence_id=evidence.id),
                    DiscoverySource(
                        source_id=evidence.source_id,
                        reliability=confidence,
                        health="ok",
                        as_of=account.observed_at,
                    ),
                )
            )

        for edge in descriptor.access_edges:
            source_object = local_objects[edge.from_external_id]
            target = await self.object_store.get(edge.to_object_id, resolve_merged=False)
            if target is None:
                raise ISPMConfigInvalid(f"access edge target does not exist: {edge.to_object_id}")
            if target.tenant_id != tenant_id:
                raise CrossTenantReference("ISPM access edge target belongs to another tenant")
            validate_edge_target(edge, target)
            key = (edge.from_external_id, edge.to_object_id, edge.relation_type)
            rel = await self._ensure_relationship(
                from_id=source_object.id,
                to_id=target.id,
                relation_type=edge.relation_type,
                tenant_id=tenant_id,
                source=prepared.edge_evidence[key],
                confidence=prepared.edge_confidence[key],
                observed_at=edge.observed_at,
            )
            relationship_ids.add(rel.id)

        inventory_assets = []
        for report, source in inventory_requests:
            inventory_assets.extend(
                await self.inventory.ingest(
                    reports=[report],
                    source=source,
                    tenant_id=tenant_id,
                )
            )
        expected_inventory_ids = {str(report["id"]) for report, _ in inventory_requests}
        if {asset.id for asset in inventory_assets} != expected_inventory_ids:
            raise StoreUnavailable("EA-0025 inventory did not accept every ISPM object")
        identity_inventory_ref = str(inventory_requests[0][0]["id"])
        identity_asset = await self.inventory.reconcile(
            identity_inventory_ref,
            tenant_id=tenant_id,
        )
        selected_owner = await self.inventory.ownership(
            identity_inventory_ref,
            tenant_id=tenant_id,
        )
        if selected_owner != identity_asset.owner:
            raise StoreUnavailable("EA-0025 ownership read disagrees with reconciled asset")
        selected_ownership = ownership_state(identity_asset)
        provenance = dict(reconciled.identity.field_provenance)
        provenance["ownership"] = (
            selected_ownership.evidence_id
            if selected_ownership.evidence_id is not None
            else f"unknown:{selected_ownership.reason}"
        )
        final = reconciled.identity.model_copy(
            update={
                "account_object_ids": sorted(account_ids),
                "relationship_ids": sorted(relationship_ids),
                "ownership": selected_ownership,
                "field_provenance": provenance,
                "conflicts": conflicts,
                "flagged": reconciled.identity.identity_kind == "unknown"
                or any(bool(conflict.get("unresolved")) for conflict in conflicts),
            },
            deep=True,
        )
        return await self.store.upsert_identity(final)

    async def _validate_edge_targets(
        self,
        prepared: Sequence[PreparedIdentity],
        *,
        tenant_id: str | None,
    ) -> None:
        for item in prepared:
            for edge in item.descriptor.access_edges:
                target = await self.object_store.get(edge.to_object_id, resolve_merged=False)
                if target is None:
                    raise ISPMConfigInvalid(
                        f"access edge target does not exist: {edge.to_object_id}"
                    )
                if target.tenant_id != tenant_id:
                    raise CrossTenantReference("ISPM access edge target belongs to another tenant")
                validate_edge_target(edge, target)

    async def _reconcile_account(
        self,
        incoming: AQObject,
        *,
        external_id: str,
        incoming_source: EvidenceRecord,
        incoming_confidence: float,
        tenant_id: str | None,
    ) -> tuple[AQObject, dict[str, object] | None]:
        rows, cursor = await self.object_store.query(
            ObjectQuery(
                tenant_id=tenant_id,
                object_type="account",
                natural_key=NaturalKey(
                    namespace=f"ispm:{incoming.attributes['provider']}:account",
                    value=external_id,
                ),
                limit=2,
            )
        )
        if cursor is not None or len(rows) > 1:
            raise StoreUnavailable("EA-0002 returned ambiguous ISPM account identity")
        if not rows:
            return incoming, None
        existing = rows[0]
        old_source_id = existing.labels.get("winning_source_id")
        old_evidence_id = existing.labels.get("winning_evidence_id")
        if old_source_id is None or old_evidence_id is None:
            raise StoreUnavailable("stored ISPM account is missing winner provenance")
        incoming_won = (
            incoming_confidence,
            incoming_source.source_id,
            incoming_source.id,
        ) > (existing.confidence, old_source_id, old_evidence_id)
        unresolved = incoming_confidence == existing.confidence
        selected = (
            incoming
            if incoming_won
            else incoming.model_copy(
                update={
                    "display_name": existing.display_name,
                    "attributes": dict(existing.attributes),
                    "labels": dict(existing.labels),
                    "confidence": existing.confidence,
                },
                deep=True,
            )
        )
        old_claim = {
            "display_name": existing.display_name,
            "attributes": existing.attributes,
        }
        new_claim = {
            "display_name": incoming.display_name,
            "attributes": incoming.attributes,
        }
        if old_claim == new_claim:
            return selected, None
        winner_source = incoming_source.source_id if incoming_won else old_source_id
        winner_evidence = incoming_source.id if incoming_won else old_evidence_id
        return selected, {
            "fields": [f"accounts.{external_id}"],
            "candidates": sorted(
                (
                    {
                        "value": old_claim,
                        "source_id": old_source_id,
                        "evidence_id": old_evidence_id,
                        "reliability": existing.confidence,
                    },
                    {
                        "value": new_claim,
                        "source_id": incoming_source.source_id,
                        "evidence_id": incoming_source.id,
                        "reliability": incoming_confidence,
                    },
                ),
                key=lambda item: (str(item["source_id"]), str(item["evidence_id"])),
            ),
            "resolved_by": None if unresolved else winner_source,
            "resolved_evidence_id": None if unresolved else winner_evidence,
            "unresolved": unresolved,
            "reason": (
                "equal EA-0006 Trust confidence; deterministic account retained "
                "and conflict surfaced"
                if unresolved
                else "higher EA-0006 Trust confidence"
            ),
        }

    async def _upsert_object(
        self,
        obj: AQObject,
        *,
        selected_confidence: float,
    ) -> AQObject:
        saved = await self.object_store.upsert(obj)
        if saved.confidence == selected_confidence:
            return saved
        return await self.object_store.update(
            saved.model_copy(update={"confidence": selected_confidence}, deep=True),
            expected_version=saved.version,
        )

    async def _ensure_relationship(
        self,
        *,
        from_id: str,
        to_id: str,
        relation_type: str,
        tenant_id: str | None,
        source: EvidenceRecord,
        confidence: float,
        observed_at: datetime,
    ) -> AQRelationship:
        existing = await self.object_store.relationships(
            from_id,
            direction="out",
            relation_type=relation_type,
        )
        for rel in existing:
            if rel.to_id == to_id:
                return rel
        return await self.object_store.relate(
            relationship(
                from_id=from_id,
                to_id=to_id,
                relation_type=relation_type,
                tenant_id=tenant_id,
                source=source,
                confidence=confidence,
                actor=self.actor,
                observed_at=observed_at,
            )
        )


def _assessment_scope(scope: dict[str, object] | None) -> dict[str, object]:
    if scope is None:
        return {}
    unknown = set(scope) - {"provider"}
    if unknown:
        raise ISPMConfigInvalid(
            f"unknown ISPM assessment scope fields: {', '.join(sorted(unknown))}"
        )
    provider = scope.get("provider")
    if provider is None:
        return {}
    if not isinstance(provider, str) or not provider.strip():
        raise ISPMConfigInvalid("assessment provider must be a non-empty string")
    return {"provider": provider}


def _remediation_playbook(finding: Finding) -> Playbook:
    action_ref = finding.automation.action_ref
    if action_ref is None:
        raise ISPMConfigInvalid("ISPM finding has no owner remediation action")
    step_id = f"remediate-{finding.id}"
    return Playbook(
        id=f"ispm-remediate-{finding.id}",
        version=1,
        name="ISPM access-control remediation proposal",
        description=(
            "Proposed EA-0011 remediation for an evidence-backed identity posture finding."
        ),
        tenant_id=finding.tenant_id,
        steps=[
            Step(
                id=step_id,
                action_type=action_ref,
                inputs={
                    "proposed_action": "review_identity_access",
                    "finding_id": finding.id,
                    "affected_object_ids": list(finding.affected_object_ids),
                    "evidence_ids": list(finding.evidence_ids),
                },
                idempotency_key=f"ispm:{finding.id}:review_identity_access",
                requires_approval=True,
            )
        ],
    )
