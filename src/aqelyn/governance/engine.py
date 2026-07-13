"""Compliance assessment engine (EA-0010 G2-G4)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import EvidenceRequired, GovernanceConfigInvalid, StoreUnavailable
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.governance.memory import InMemorySnapshotStore
from aqelyn.governance.models import (
    ComplianceSnapshot,
    Control,
    ControlResult,
    FrameworkCoverage,
    GovernanceConfig,
)
from aqelyn.governance.store import SnapshotStore
from aqelyn.objects import AQObject, ObjectQuery, ObjectStore
from aqelyn.policy import PolicyEngine

_GOVERNANCE_ACTOR = ActorRef(actor_type="system", actor_id="compliance_engine")
_SEVERITY_SCORES: dict[str, float] = {
    "info": 10.0,
    "low": 25.0,
    "medium": 50.0,
    "high": 75.0,
    "critical": 100.0,
}


class _PriorityItem(Protocol):
    finding_id: str


class MissionPrioritizer(Protocol):
    async def prioritize(self, findings: Sequence[Finding]) -> Sequence[_PriorityItem]: ...


class ComplianceEngine:
    """Runs configured governance controls across the object estate."""

    def __init__(
        self,
        object_store: ObjectStore,
        policy_engine: PolicyEngine,
        *,
        config: GovernanceConfig,
        snapshot_store: SnapshotStore | None = None,
        evidence_store: EvidenceStore | None = None,
        finding_store: FindingStore | None = None,
        mission_engine: MissionPrioritizer | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self._object_store = object_store
        self._policy_engine = policy_engine
        self._config = config.model_copy(deep=True)
        self._controls = {control.id: control for control in self._config.controls}
        self._snapshot_store = snapshot_store or InMemorySnapshotStore()
        self._evidence_store = evidence_store
        self._finding_store = finding_store
        self._mission_engine = mission_engine
        self._actor = actor or _GOVERNANCE_ACTOR
        self._source_id = source_id or new_id("src")

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
        record_evidence: bool = True,
    ) -> ComplianceSnapshot:
        accumulators = [_ControlAccumulator(control) for control in self._config.controls]
        async for page in self._pages(tenant_id=tenant_id, scope=scope):
            for obj in sorted(page, key=lambda item: item.id):
                resource = _resource_from_object(obj)
                for accumulator in accumulators:
                    result = await self._policy_engine.evaluate_compliance(
                        resource,
                        tenant_id=tenant_id,
                        policy_ids=set(accumulator.control.policy_ids),
                    )
                    accumulator.add(obj, compliant=result.compliant)

        control_results = [accumulator.result() for accumulator in accumulators]
        overall_score = _mean([result.score for result in control_results], default=1.0)
        snapshot = ComplianceSnapshot(
            id=new_id("snap"),
            tenant_id=tenant_id,
            run_at=utc_now(),
            scope=_scope_dump(scope, tenant_id=tenant_id, batch_size=self._config.batch_size),
            overall_score=overall_score,
            control_results=control_results,
            framework_scores=_framework_scores(self._config, control_results),
            evidence_id=None,
        )
        if record_evidence:
            evidence = await self._record_snapshot_evidence(snapshot)
            snapshot = snapshot.model_copy(update={"evidence_id": evidence.id})
        return await self._snapshot_store.put(snapshot)

    async def control_result(self, control_id: str, *, tenant_id: str | None) -> ControlResult:
        if control_id not in self._controls:
            raise GovernanceConfigInvalid(f"unknown control_id: {control_id!r}")
        snapshot = await self.assess(tenant_id=tenant_id, record_evidence=False)
        for result in snapshot.control_results:
            if result.control_id == control_id:
                return result
        raise GovernanceConfigInvalid(f"unknown control_id: {control_id!r}")

    def explain(self, result: ControlResult) -> dict[str, object]:
        return {
            "control_id": result.control_id,
            "evaluated": result.evaluated,
            "passed": result.passed,
            "failed": result.failed,
            "failing_subject_ids": list(result.failing_subject_ids),
            "score": result.score,
            "reason": result.reason,
        }

    async def coverage(self, *, tenant_id: str | None) -> list[FrameworkCoverage]:
        latest = await self._snapshot_store.latest(tenant_id=tenant_id)
        latest_scores = latest.framework_scores if latest is not None else {}
        covered_by_framework: dict[str, set[str]] = {
            framework: set() for framework in self._config.frameworks
        }
        for control in self._config.controls:
            for ref in control.framework_refs:
                if ref.framework in covered_by_framework:
                    covered_by_framework[ref.framework].add(ref.requirement)

        rows: list[FrameworkCoverage] = []
        for framework in sorted(self._config.frameworks):
            requirements = self._config.frameworks[framework]
            covered = len(covered_by_framework[framework])
            rows.append(
                FrameworkCoverage(
                    framework=framework,
                    requirements=len(requirements),
                    covered=covered,
                    coverage=covered / len(requirements),
                    score=latest_scores.get(framework, 0.0),
                )
            )
        return rows

    async def gaps_to_findings(
        self,
        snapshot: ComplianceSnapshot,
        *,
        by: ActorRef,
        prioritize: bool = True,
    ) -> list[str]:
        if self._finding_store is None:
            raise StoreUnavailable("gaps_to_findings requires a FindingStore")
        if snapshot.evidence_id is None:
            raise EvidenceRequired("snapshot evidence is required before raising findings")

        findings: list[Finding] = []
        results_by_control = {result.control_id: result for result in snapshot.control_results}
        for control in self._config.controls:
            result = results_by_control.get(control.id)
            if result is None or result.failed == 0:
                continue
            raised = await self._finding_store.raise_finding(
                _finding_for_gap(
                    control,
                    result,
                    snapshot=snapshot,
                    evidence_id=snapshot.evidence_id,
                    by=by,
                )
            )
            findings.append(raised)

        if prioritize and self._mission_engine is not None and findings:
            items = await self._mission_engine.prioritize(findings)
            rank = {item.finding_id: index for index, item in enumerate(items)}
            findings.sort(key=lambda finding: rank.get(finding.id, len(rank)))
        return [finding.id for finding in findings]

    async def trend(self, *, tenant_id: str | None, since: datetime) -> list[dict[str, object]]:
        snapshots = await self._snapshot_store.history(tenant_id=tenant_id, since=since)
        return [
            {
                "snapshot_id": snapshot.id,
                "run_at": snapshot.run_at.isoformat(),
                "overall_score": snapshot.overall_score,
                "control_scores": {
                    result.control_id: result.score for result in snapshot.control_results
                },
            }
            for snapshot in snapshots
        ]

    async def _record_snapshot_evidence(self, snapshot: ComplianceSnapshot) -> EvidenceRecord:
        if self._evidence_store is None:
            raise StoreUnavailable("record_evidence=True requires an EvidenceStore")
        record = EvidenceRecord(
            id="",
            tenant_id=snapshot.tenant_id,
            evidence_type="governance.compliance_snapshot",
            schema_version=1,
            subject=Subject(object_ids=_failing_subjects(snapshot.control_results)),
            collected_at=snapshot.run_at,
            recorded_at=utc_now(),
            collector=self._actor,
            source_id=self._source_id,
            method="governance.assess/v1",
            content={
                "snapshot_id": snapshot.id,
                "tenant_id": snapshot.tenant_id,
                "scope": snapshot.scope,
                "overall_score": snapshot.overall_score,
                "framework_scores": snapshot.framework_scores,
                "control_results": [
                    result.model_dump(mode="json") for result in snapshot.control_results
                ],
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0010", "kind": "compliance_snapshot"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self._evidence_store.add(record)

    async def _pages(
        self, *, tenant_id: str | None, scope: ObjectQuery | None
    ) -> AsyncIterator[list[AQObject]]:
        cursor = scope.cursor if scope is not None else None
        seen_cursors: set[str] = set()
        while True:
            query = _query_for_page(
                tenant_id=tenant_id,
                scope=scope,
                limit=self._config.batch_size,
                cursor=cursor,
            )
            rows, next_cursor = await self._object_store.query(query)
            yield rows
            if next_cursor is None or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor


class _ControlAccumulator:
    def __init__(self, control: Control) -> None:
        self.control = control
        self.evaluated = 0
        self.passed = 0
        self.failing_subject_ids: list[str] = []

    def add(self, obj: AQObject, *, compliant: bool) -> None:
        self.evaluated += 1
        if compliant:
            self.passed += 1
            return
        self.failing_subject_ids.append(obj.id)

    def result(self) -> ControlResult:
        failed = len(self.failing_subject_ids)
        if self.evaluated == 0:
            score = 1.0
            reason = f"Control {self.control.id} had no in-scope targets."
        else:
            score = self.passed / self.evaluated
            reason = (
                f"Control {self.control.id} evaluated {self.evaluated} target(s): "
                f"{self.passed} passed, {failed} failed."
            )
        return ControlResult(
            control_id=self.control.id,
            evaluated=self.evaluated,
            passed=self.passed,
            failed=failed,
            failing_subject_ids=self.failing_subject_ids,
            score=score,
            reason=reason,
        )


def _query_for_page(
    *,
    tenant_id: str | None,
    scope: ObjectQuery | None,
    limit: int,
    cursor: str | None,
) -> ObjectQuery:
    if scope is None:
        return ObjectQuery(tenant_id=tenant_id, limit=limit, cursor=cursor)
    data = scope.model_dump()
    data.update({"tenant_id": tenant_id, "limit": limit, "cursor": cursor})
    return ObjectQuery.model_validate(data)


def _resource_from_object(obj: AQObject) -> dict[str, Any]:
    return {
        "id": obj.id,
        "type": obj.object_type,
        "object_type": obj.object_type,
        "tenant_id": obj.tenant_id,
        "display_name": obj.display_name,
        "attributes": dict(obj.attributes),
        "labels": dict(obj.labels),
        "confidence": obj.confidence,
        "lifecycle_state": obj.lifecycle_state,
    }


def _scope_dump(
    scope: ObjectQuery | None, *, tenant_id: str | None, batch_size: int
) -> dict[str, Any]:
    query = _query_for_page(tenant_id=tenant_id, scope=scope, limit=batch_size, cursor=None)
    return query.model_dump(mode="json")


def _framework_scores(config: GovernanceConfig, results: list[ControlResult]) -> dict[str, float]:
    results_by_control = {result.control_id: result for result in results}
    framework_controls: dict[str, list[float]] = {framework: [] for framework in config.frameworks}
    for control in config.controls:
        result = results_by_control.get(control.id)
        if result is None:
            continue
        frameworks = {ref.framework for ref in control.framework_refs}
        for framework in frameworks:
            if framework in framework_controls:
                framework_controls[framework].append(result.score)
    return {
        framework: _mean(scores, default=0.0)
        for framework, scores in sorted(framework_controls.items())
    }


def _failing_subjects(results: list[ControlResult]) -> list[str]:
    subject_ids: set[str] = set()
    for result in results:
        subject_ids.update(result.failing_subject_ids)
    return sorted(subject_ids)


def _finding_for_gap(
    control: Control,
    result: ControlResult,
    *,
    snapshot: ComplianceSnapshot,
    evidence_id: str,
    by: ActorRef,
) -> Finding:
    failed_count = len(result.failing_subject_ids)
    return Finding(
        id="",
        tenant_id=snapshot.tenant_id,
        finding_type="governance.control_gap",
        schema_version=1,
        dedup_key=f"governance.control_gap:{control.id}",
        title=f"Governance control failed: {control.name}",
        severity=control.severity,
        severity_score=_SEVERITY_SCORES[control.severity],
        status="open",
        what_happened=(
            f"Control {control.id} failed for {failed_count} of "
            f"{result.evaluated} evaluated object(s)."
        ),
        why_it_matters=control.description,
        how_determined=(
            f"Compliance snapshot {snapshot.id} evaluated policy id(s) "
            f"{', '.join(control.policy_ids)} and found failing object id(s): "
            f"{', '.join(result.failing_subject_ids)}."
        ),
        risk_of_inaction=(
            "Leaving this governance gap unresolved can allow the non-compliant "
            "state to persist and weaken the mapped framework posture."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=list(result.failing_subject_ids),
        expert_details={
            "snapshot_id": snapshot.id,
            "control_id": control.id,
            "control_name": control.name,
            "policy_ids": list(control.policy_ids),
            "framework_refs": [ref.model_dump(mode="json") for ref in control.framework_refs],
            "evaluated": result.evaluated,
            "passed": result.passed,
            "failed": result.failed,
            "score": result.score,
            "raised_by": by.model_dump(mode="json"),
        },
        remediation=Remediation(
            summary=f"Remediate objects failing {control.name}.",
            steps=[
                f"Review the failing object id(s): {', '.join(result.failing_subject_ids)}.",
                (
                    "Apply the requirement described by policy id(s): "
                    f"{', '.join(control.policy_ids)}."
                ),
                "Rerun the governance assessment and confirm the control passes.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome=(
                "The affected objects satisfy the control and the next snapshot passes."
            ),
            references=[f"{ref.framework}:{ref.requirement}" for ref in control.framework_refs],
        ),
        automation=Automation(
            eligibility="none",
            requires_approval=True,
            risk_note="Governance gaps require human review before any remediation action.",
        ),
        confidence=1.0,
        source_engine="compliance_engine",
        correlation_id=snapshot.id,
        first_detected_at=snapshot.run_at,
        last_detected_at=snapshot.run_at,
    )


def _mean(values: list[float], *, default: float) -> float:
    if not values:
        return default
    return sum(values) / len(values)
