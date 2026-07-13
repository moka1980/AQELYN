"""Identity & Access Governance campaign engine (EA-0011 I3/I4)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    CertificationNotFound,
    EvidenceRequired,
    IAGConfigInvalid,
    OptimisticConcurrencyConflict,
    ReviewItemNotFound,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.graph import KnowledgeGraph
from aqelyn.iag.analysis import IDENTITY_OBJECT_TYPE, IAGPolicyEvaluator, IdentityAccessAnalyzer
from aqelyn.iag.models import (
    AccessPath,
    AccessRisk,
    AccessRiskReport,
    Certification,
    IAGConfig,
    ReviewDecision,
    ReviewItem,
)
from aqelyn.iag.store import CertificationStore, validate_positive, validate_review_item_id
from aqelyn.objects import ObjectQuery, ObjectStore
from aqelyn.workflow import Playbook, Run, Step

_IAG_ACTOR = ActorRef(actor_type="system", actor_id="iag_engine")
_VALID_DECISIONS: frozenset[str] = frozenset(("approved", "revoked", "delegated"))
_PAGE_SIZE = 1_000
_SEVERITY_SCORES: dict[str, float] = {
    "info": 10.0,
    "low": 25.0,
    "medium": 50.0,
    "high": 75.0,
    "critical": 100.0,
}
_REMEDIATION_ACTION_TYPE = "iag.remediate_access"


class _PriorityItem(Protocol):
    finding_id: str


class MissionPrioritizer(Protocol):
    async def prioritize(self, findings: Sequence[Finding]) -> Sequence[_PriorityItem]: ...


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class IdentityAccessGovernanceEngine:
    def __init__(
        self,
        object_store: ObjectStore,
        knowledge_graph: KnowledgeGraph,
        policy_engine: IAGPolicyEvaluator,
        certification_store: CertificationStore,
        evidence_store: EvidenceStore,
        *,
        finding_store: FindingStore | None = None,
        workflow_engine: WorkflowProposer | None = None,
        mission_engine: MissionPrioritizer | None = None,
        config: IAGConfig | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self._objects = object_store
        self._knowledge_graph = knowledge_graph
        self._policy_engine = policy_engine
        self._certifications = certification_store
        self._evidence = evidence_store
        self._findings = finding_store
        self._workflow = workflow_engine
        self._mission = mission_engine
        self._config = config or IAGConfig()
        self._actor = actor or _IAG_ACTOR
        self._source_id = source_id or new_id("src")
        self._analyzer = IdentityAccessAnalyzer(
            object_store,
            knowledge_graph,
            policy_engine,
            config=self._config,
        )

    @property
    def config(self) -> IAGConfig:
        return self._config

    @property
    def object_store(self) -> ObjectStore:
        return self._objects

    @property
    def knowledge_graph(self) -> KnowledgeGraph:
        return self._knowledge_graph

    @property
    def policy_engine(self) -> IAGPolicyEvaluator:
        return self._policy_engine

    @property
    def certification_store(self) -> CertificationStore:
        return self._certifications

    @property
    def evidence_store(self) -> EvidenceStore:
        return self._evidence

    @property
    def finding_store(self) -> FindingStore | None:
        return self._findings

    @property
    def workflow_engine(self) -> WorkflowProposer | None:
        return self._workflow

    async def access_paths(
        self, identity_id: str, *, tenant_id: str | None = None
    ) -> list[AccessPath]:
        return await self._analyzer.access_paths(identity_id, tenant_id=tenant_id)

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        return await self._analyzer.analyze_risk(tenant_id=tenant_id, scope=scope)

    def explain(self, risk: AccessRisk) -> dict[str, object]:
        return self._analyzer.explain(risk)

    async def open_certification(
        self,
        *,
        tenant_id: str | None,
        name: str,
        scope: ObjectQuery,
        by: ActorRef,
        due_days: int | None = None,
    ) -> Certification:
        days = due_days if due_days is not None else self._config.review_default_due_days
        validate_positive(days, field="due_days")
        report = await self.analyze_risk(tenant_id=tenant_id, scope=scope)
        risk_index = _RiskIndex(report.risks)
        items: list[ReviewItem] = []
        async for page in _identity_pages(self._objects, tenant_id=tenant_id, scope=scope):
            for identity in sorted(page, key=lambda obj: obj.id):
                paths = await self.access_paths(identity.id, tenant_id=tenant_id)
                for path in paths:
                    for entitlement_id in path.entitlement_ids:
                        item = ReviewItem(
                            id=new_id("rvi"),
                            identity_id=identity.id,
                            account_id=path.account_id,
                            entitlement_id=entitlement_id,
                            current_state={
                                "access_path": path.model_dump(mode="json"),
                                "truncated": report.truncated,
                            },
                            recommendation=risk_index.recommendation(
                                identity_id=identity.id,
                                account_id=path.account_id,
                                entitlement_id=entitlement_id,
                            ),
                        )
                        items.append(item)
        now = utc_now()
        cert = Certification(
            id=new_id("cert"),
            tenant_id=tenant_id,
            name=name,
            scope=_scope_dump(scope, tenant_id=tenant_id),
            status="open",
            items=sorted(items, key=_review_item_sort_key),
            created_by=by,
            created_at=now,
            due_at=now + timedelta(days=days),
            version=1,
        )
        return await self._certifications.put(cert)

    async def decide_item(
        self,
        cert_id: str,
        item_id: str,
        *,
        decision: str,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Certification:
        validate_positive(expected_version, field="expected_version")
        validate_review_item_id(item_id)
        selected_decision = _validate_decision(decision)
        cert = await self._certifications.get(cert_id)
        if cert is None:
            raise CertificationNotFound(cert_id)
        if cert.version != expected_version:
            raise OptimisticConcurrencyConflict(
                f"expected v{expected_version}, found v{cert.version}"
            )
        item = _find_item(cert.items, item_id)
        decided_at = utc_now()
        evidence = await self._record_decision_evidence(
            cert,
            item,
            decision=selected_decision,
            by=by,
            note=note,
            decided_at=decided_at,
        )
        updated_item = item.model_copy(
            update={
                "decision": selected_decision,
                "decided_by": by,
                "decided_at": decided_at,
                "evidence_id": evidence.id,
                "note": note,
            },
            deep=True,
        )
        updated_items = [
            updated_item if existing.id == item_id else existing for existing in cert.items
        ]
        updated = cert.model_copy(
            update={
                "items": updated_items,
                "status": "in_progress",
            },
            deep=True,
        )
        return await self._certifications.put(updated, expected_version=expected_version)

    async def risks_to_findings(
        self,
        report: AccessRiskReport,
        *,
        by: ActorRef,
        prioritize: bool = True,
    ) -> list[str]:
        if self._findings is None:
            raise StoreUnavailable("risks_to_findings requires a FindingStore")
        findings: list[Finding] = []
        for risk in sorted(report.risks, key=_risk_sort_key):
            evidence = await self._record_risk_evidence(risk, by=by)
            finding = await self._findings.raise_finding(
                _finding_for_risk(risk, evidence_id=evidence.id)
            )
            findings.append(finding)
        if prioritize and self._mission is not None and findings:
            items = await self._mission.prioritize(findings)
            rank = {item.finding_id: index for index, item in enumerate(items)}
            findings.sort(key=lambda finding: rank.get(finding.id, len(rank)))
        return [finding.id for finding in findings]

    async def complete_certification(
        self,
        cert_id: str,
        *,
        by: ActorRef,
        raise_findings: bool = True,
    ) -> list[str]:
        cert = await self._certifications.get(cert_id)
        if cert is None:
            raise CertificationNotFound(cert_id)
        proposed_run_ids: list[str] = []
        if raise_findings:
            if self._findings is None:
                raise StoreUnavailable("complete_certification requires a FindingStore")
            if self._workflow is None:
                raise StoreUnavailable("complete_certification requires a WorkflowEngine")
            for item in sorted(
                [review_item for review_item in cert.items if review_item.decision == "revoked"],
                key=_review_item_sort_key,
            ):
                if item.evidence_id is None:
                    raise EvidenceRequired("revoked review item requires decision evidence")
                finding = await self._findings.raise_finding(
                    _finding_for_review_item(cert, item, evidence_id=item.evidence_id)
                )
                run = await self._workflow.propose(
                    _playbook_for_revoked_item(cert, item),
                    by=by,
                    source_finding=finding,
                )
                proposed_run_ids.append(run.id)

        completed = cert.model_copy(update={"status": "completed"}, deep=True)
        await self._certifications.put(completed, expected_version=cert.version)
        return proposed_run_ids

    async def _record_decision_evidence(
        self,
        cert: Certification,
        item: ReviewItem,
        *,
        decision: ReviewDecision,
        by: ActorRef,
        note: str | None,
        decided_at: datetime,
    ) -> EvidenceRecord:
        subject_ids = [
            value
            for value in (item.identity_id, item.account_id, item.entitlement_id)
            if value is not None
        ]
        record = EvidenceRecord(
            id="",
            tenant_id=cert.tenant_id,
            evidence_type="iag.certification_decision",
            schema_version=1,
            subject=Subject(object_ids=subject_ids),
            collected_at=decided_at,
            recorded_at=decided_at,
            collector=by,
            source_id=self._source_id,
            method="iag.decide_item/v1",
            content={
                "certification_id": cert.id,
                "review_item_id": item.id,
                "decision": decision,
                "note": note,
                "current_state": item.current_state,
                "recommendation": item.recommendation,
                "actor": by.model_dump(mode="json"),
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0011", "kind": "certification_decision"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self._evidence.add(record)

    async def _record_risk_evidence(self, risk: AccessRisk, *, by: ActorRef) -> EvidenceRecord:
        now = utc_now()
        record = EvidenceRecord(
            id="",
            tenant_id=None,
            evidence_type="iag.access_risk",
            schema_version=1,
            subject=Subject(object_ids=_affected_object_ids_for_risk(risk)),
            collected_at=now,
            recorded_at=now,
            collector=by,
            source_id=self._source_id,
            method="iag.risks_to_findings/v1",
            content={
                "risk": risk.model_dump(mode="json"),
                "evidence_path": (
                    risk.evidence_path.model_dump(mode="json")
                    if risk.evidence_path is not None
                    else None
                ),
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0011", "kind": "access_risk"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self._evidence.add(record)


class _RiskIndex:
    def __init__(self, risks: Sequence[AccessRisk]) -> None:
        self._by_identity: dict[str, set[str]] = {}
        self._by_account: dict[str, set[str]] = {}
        self._by_entitlement: dict[str, set[str]] = {}
        for risk in risks:
            self._by_identity.setdefault(risk.subject_id, set()).add(risk.kind)
            account_id = risk.detail.get("account_id")
            if isinstance(account_id, str):
                self._by_account.setdefault(account_id, set()).add(risk.kind)
            entitlement_id = risk.detail.get("entitlement_id")
            if isinstance(entitlement_id, str):
                self._by_entitlement.setdefault(entitlement_id, set()).add(risk.kind)

    def recommendation(
        self,
        *,
        identity_id: str,
        account_id: str | None,
        entitlement_id: str,
    ) -> str:
        kinds = set(self._by_identity.get(identity_id, set()))
        if account_id is not None:
            kinds.update(self._by_account.get(account_id, set()))
        kinds.update(self._by_entitlement.get(entitlement_id, set()))
        if not kinds:
            return "Approve if access remains business-justified."
        return f"Review access risk(s): {', '.join(sorted(kinds))}."


async def _identity_pages(
    object_store: ObjectStore,
    *,
    tenant_id: str | None,
    scope: ObjectQuery,
) -> AsyncIterator[list[Any]]:
    cursor = scope.cursor
    seen_cursors: set[str] = set()
    while True:
        query = _query_for_identity_page(tenant_id=tenant_id, scope=scope, cursor=cursor)
        rows, next_cursor = await object_store.query(query)
        yield rows
        if next_cursor is None or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _query_for_identity_page(
    *,
    tenant_id: str | None,
    scope: ObjectQuery,
    cursor: str | None,
) -> ObjectQuery:
    data = scope.model_dump()
    data.update(
        {
            "tenant_id": tenant_id,
            "object_type": IDENTITY_OBJECT_TYPE,
            "include_states": ("active",),
            "limit": min(scope.limit, _PAGE_SIZE),
            "cursor": cursor,
        }
    )
    return ObjectQuery.model_validate(data)


def _scope_dump(scope: ObjectQuery, *, tenant_id: str | None) -> dict[str, Any]:
    return _query_for_identity_page(tenant_id=tenant_id, scope=scope, cursor=None).model_dump(
        mode="json"
    )


def _find_item(items: Sequence[ReviewItem], item_id: str) -> ReviewItem:
    for item in items:
        if item.id == item_id:
            return item
    raise ReviewItemNotFound(item_id)


def _validate_decision(value: str) -> ReviewDecision:
    if value not in _VALID_DECISIONS:
        raise IAGConfigInvalid(f"unknown review decision: {value!r}")
    return value  # type: ignore[return-value]


def _review_item_sort_key(item: ReviewItem) -> tuple[str, str, str, str]:
    return (
        item.identity_id,
        item.account_id or "",
        item.entitlement_id or "",
        item.id,
    )


def _risk_sort_key(risk: AccessRisk) -> tuple[str, str, str, str]:
    return (
        risk.kind,
        risk.subject_id,
        str(risk.detail.get("account_id", "")),
        str(risk.detail.get("entitlement_id", "")),
    )


def _finding_for_risk(risk: AccessRisk, *, evidence_id: str) -> Finding:
    now = utc_now()
    affected_ids = _affected_object_ids_for_risk(risk)
    return Finding(
        id="",
        tenant_id=None,
        finding_type=f"iag.{risk.kind}",
        schema_version=1,
        dedup_key=_risk_dedup_key(risk),
        title=f"Identity access risk detected: {risk.kind.replace('_', ' ')}",
        severity=risk.severity,
        severity_score=_SEVERITY_SCORES[risk.severity],
        status="open",
        what_happened=risk.reason,
        why_it_matters=(
            "Identity and access governance risks can leave inappropriate access "
            "unreviewed or violate least-privilege expectations."
        ),
        how_determined=(
            "The Identity & Access Governance Engine evaluated object-store identity "
            "data, Knowledge Graph access paths, and Policy rules where applicable."
        ),
        risk_of_inaction=(
            "Leaving this risk unresolved can preserve excessive, stale, or conflicting "
            "access beyond the review window."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=affected_ids,
        expert_details={
            "risk": risk.model_dump(mode="json"),
            "affected_object_ids": affected_ids,
        },
        remediation=Remediation(
            summary="Review and remediate the flagged access through an approved workflow.",
            steps=[
                "Review the evidence-backed access path and risk reason.",
                "Confirm whether the access remains business-justified.",
                "If access should change, use an approved Workflow remediation run.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The access state is reviewed and any required change is delegated.",
            references=["EA-0011", "EA-0008"],
        ),
        automation=Automation(
            eligibility="assisted",
            action_ref=_REMEDIATION_ACTION_TYPE,
            requires_approval=True,
            risk_note="IAG never mutates access directly; remediation is delegated to Workflow.",
        ),
        confidence=1.0,
        source_engine="iag_engine",
        correlation_id=None,
        first_detected_at=now,
        last_detected_at=now,
    )


def _finding_for_review_item(cert: Certification, item: ReviewItem, *, evidence_id: str) -> Finding:
    now = utc_now()
    affected_ids = _affected_object_ids_for_item(item)
    return Finding(
        id="",
        tenant_id=cert.tenant_id,
        finding_type="iag.certification_revocation",
        schema_version=1,
        dedup_key=f"iag.certification_revocation:{cert.id}:{item.id}",
        title="Access review requested revocation",
        severity="high",
        severity_score=_SEVERITY_SCORES["high"],
        status="open",
        what_happened=(
            f"Reviewer decision for certification {cert.id} marked review item "
            f"{item.id} as revoked."
        ),
        why_it_matters=(
            "A reviewer has attested that this access should not remain in its current state."
        ),
        how_determined=(
            "The finding was raised from an evidenced IAG certification decision; the "
            "engine has not changed the access itself."
        ),
        risk_of_inaction=(
            "If the proposed remediation is not reviewed and executed through Workflow, "
            "the unwanted access may remain active."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=affected_ids,
        expert_details={
            "certification_id": cert.id,
            "review_item_id": item.id,
            "identity_id": item.identity_id,
            "account_id": item.account_id,
            "entitlement_id": item.entitlement_id,
            "decision": item.decision,
            "note": item.note,
        },
        remediation=Remediation(
            summary="Review and execute the proposed access-remediation workflow.",
            steps=[
                "Open the proposed Workflow run for this certification decision.",
                "Confirm the requested access change and blast radius.",
                "Approve and execute through Workflow if the change is still appropriate.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The unwanted access is remediated by an approved Workflow run.",
            references=["EA-0011 §0", "EA-0008"],
        ),
        automation=Automation(
            eligibility="assisted",
            action_ref=_REMEDIATION_ACTION_TYPE,
            requires_approval=True,
            risk_note="Certification decisions propose remediation; they never revoke directly.",
        ),
        confidence=1.0,
        source_engine="iag_engine",
        correlation_id=cert.id,
        first_detected_at=now,
        last_detected_at=now,
    )


def _playbook_for_revoked_item(cert: Certification, item: ReviewItem) -> Playbook:
    step_id = f"review-{item.id}"
    return Playbook(
        id=f"iag-remediate-{cert.id}-{item.id}",
        version=1,
        name="IAG access remediation proposal",
        description="Proposed remediation for an evidenced certification revocation decision.",
        tenant_id=cert.tenant_id,
        steps=[
            Step(
                id=step_id,
                action_type=_REMEDIATION_ACTION_TYPE,
                inputs={
                    "proposed_action": "revoke_access",
                    "certification_id": cert.id,
                    "review_item_id": item.id,
                    "identity_id": item.identity_id,
                    "account_id": item.account_id,
                    "entitlement_id": item.entitlement_id,
                    "decision_evidence_id": item.evidence_id,
                    "note": item.note,
                },
                idempotency_key=f"iag:{cert.id}:{item.id}:revoke_access",
                requires_approval=True,
            )
        ],
    )


def _risk_dedup_key(risk: AccessRisk) -> str:
    parts = [
        "iag.access_risk",
        risk.kind,
        risk.subject_id,
        str(risk.detail.get("account_id", "")),
        str(risk.detail.get("entitlement_id", "")),
        str(risk.detail.get("rule_id", "")),
    ]
    return ":".join(parts)


def _affected_object_ids_for_risk(risk: AccessRisk) -> list[str]:
    ids: set[str] = {risk.subject_id}
    if risk.evidence_path is not None:
        ids.update(risk.evidence_path.node_ids)
    for key in ("identity_id", "account_id", "entitlement_id"):
        value = risk.detail.get(key)
        if isinstance(value, str):
            ids.add(value)
    role_ids = risk.detail.get("role_ids")
    if isinstance(role_ids, list):
        ids.update(item for item in role_ids if isinstance(item, str))
    return sorted(ids)


def _affected_object_ids_for_item(item: ReviewItem) -> list[str]:
    return sorted(
        value
        for value in (item.identity_id, item.account_id, item.entitlement_id)
        if value is not None
    )
