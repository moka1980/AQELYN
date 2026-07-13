"""Read-only asset drift assessment for Asset & Configuration Governance (A2)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from aqelyn.assetconfig.classify import classify
from aqelyn.assetconfig.comparators import MISSING, compare
from aqelyn.assetconfig.models import (
    ACGConfig,
    AssetDrift,
    Baseline,
    Check,
    DriftItem,
    DriftSnapshot,
)
from aqelyn.assetconfig.store import (
    BaselineStore,
    DriftSnapshotStore,
    new_drift_snapshot_id,
)
from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import EvidenceRequired, ObjectNotFound, StoreUnavailable
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.objects import AQObject, ObjectQuery, ObjectStore
from aqelyn.workflow import Playbook, Run, Step

ASSET_OBJECT_TYPE = "asset"
ACG_REMEDIATION_ACTION = "assetconfig.remediate"
_ACG_ACTOR = ActorRef(actor_type="system", actor_id="acg_engine")
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


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class AssetConfigAnalyzer:
    def __init__(
        self,
        object_store: ObjectStore,
        baselines: Sequence[Baseline],
        *,
        baseline_store: BaselineStore | None = None,
        snapshot_store: DriftSnapshotStore | None = None,
        evidence_store: EvidenceStore | None = None,
        finding_store: FindingStore | None = None,
        workflow_engine: WorkflowProposer | None = None,
        mission_engine: MissionPrioritizer | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
        config: ACGConfig | None = None,
    ) -> None:
        self.object_store = object_store
        self.baselines = tuple(sorted(baselines, key=lambda baseline: baseline.id))
        self.baseline_store = baseline_store
        self.snapshot_store = snapshot_store
        self.evidence_store = evidence_store
        self.finding_store = finding_store
        self.workflow_engine = workflow_engine
        self.mission_engine = mission_engine
        self.actor = actor or _ACG_ACTOR
        self.source_id = source_id or new_id("src")
        self.config = config or ACGConfig()

    async def classify(self, asset_id: str, *, tenant_id: str | None = None) -> str:
        asset = await self._asset(asset_id, tenant_id=tenant_id)
        return classify_asset(asset, self.config)

    async def assess_asset(
        self, asset_id: str, *, tenant_id: str | None = None
    ) -> list[AssetDrift]:
        asset = await self._asset(asset_id, tenant_id=tenant_id)
        return assess_asset(asset, await self._matching_baselines(asset), self.config)

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
        record_evidence: bool = True,
    ) -> DriftSnapshot:
        asset_drifts: list[AssetDrift] = []
        async for page in _asset_pages(
            self.object_store,
            tenant_id=tenant_id,
            scope=scope,
            batch_size=self.config.batch_size,
        ):
            for asset in sorted(page, key=lambda item: item.id):
                asset_drifts.extend(
                    assess_asset(asset, await self._matching_baselines(asset), self.config)
                )
        asset_drifts.sort(key=lambda item: (item.asset_id, item.baseline_id))
        baseline_ids = sorted({item.baseline_id for item in asset_drifts})
        snapshot = DriftSnapshot(
            id=new_drift_snapshot_id(),
            tenant_id=tenant_id,
            run_at=utc_now(),
            scope=_scope_dump(scope, tenant_id=tenant_id, batch_size=self.config.batch_size),
            baseline_ids=baseline_ids,
            overall_score=_mean([item.score for item in asset_drifts], default=1.0),
            asset_drifts=asset_drifts,
            evidence_id=None,
        )
        if record_evidence:
            evidence = await self._record_snapshot_evidence(snapshot)
            snapshot = snapshot.model_copy(update={"evidence_id": evidence.id}, deep=True)
        if self.snapshot_store is None:
            return snapshot
        return await self.snapshot_store.put(snapshot)

    async def trend(self, *, tenant_id: str | None, since: datetime) -> list[dict[str, object]]:
        if self.snapshot_store is None:
            return []
        snapshots = await self.snapshot_store.history(tenant_id=tenant_id, since=since)
        return [_trend_point(snapshot) for snapshot in snapshots]

    def explain(self, item: DriftItem) -> dict[str, object]:
        return explain(item)

    async def drift_to_findings(
        self,
        snapshot: DriftSnapshot,
        *,
        by: ActorRef,
        propose_remediation: bool = True,
        prioritize: bool = True,
    ) -> list[str]:
        if self.finding_store is None:
            raise StoreUnavailable("drift_to_findings requires a FindingStore")
        if snapshot.evidence_id is None:
            raise EvidenceRequired("snapshot evidence is required before raising findings")
        if propose_remediation and self.workflow_engine is None:
            raise StoreUnavailable("propose_remediation=True requires a WorkflowEngine")

        findings: list[Finding] = []
        for asset_drift in sorted(snapshot.asset_drifts, key=lambda item: item.asset_id):
            for item in _failing_items(asset_drift, self.config):
                check = await self._check_for(asset_drift.baseline_id, item.check_id)
                raised = await self.finding_store.raise_finding(
                    _finding_for_drift(
                        asset_drift,
                        item,
                        snapshot=snapshot,
                        evidence_id=snapshot.evidence_id,
                        check=check,
                        by=by,
                    )
                )
                findings.append(raised)

        if prioritize and self.mission_engine is not None and findings:
            items = await self.mission_engine.prioritize(findings)
            rank = {item.finding_id: index for index, item in enumerate(items)}
            findings.sort(key=lambda finding: rank.get(finding.id, len(rank)))

        if propose_remediation and self.workflow_engine is not None:
            for finding in findings:
                await self.workflow_engine.propose(
                    _playbook_for_drift(finding, snapshot=snapshot),
                    by=by,
                    source_finding=finding,
                )
        return [finding.id for finding in findings]

    async def _asset(self, asset_id: str, *, tenant_id: str | None) -> AQObject:
        asset = await self.object_store.get(asset_id, resolve_merged=False)
        if asset is None or asset.object_type != ASSET_OBJECT_TYPE:
            raise ObjectNotFound(asset_id)
        if tenant_id is not None and asset.tenant_id != tenant_id:
            raise ObjectNotFound(asset_id)
        return asset

    async def _matching_baselines(self, asset: AQObject) -> list[Baseline]:
        asset_class = classify_asset(asset, self.config)
        if self.baseline_store is not None:
            return await self.baseline_store.list(
                tenant_id=asset.tenant_id, asset_class=asset_class
            )
        return [
            baseline
            for baseline in self.baselines
            if baseline.asset_class == asset_class and _tenant_visible(baseline, asset.tenant_id)
        ]

    async def _check_for(self, baseline_id: str, check_id: str) -> Check | None:
        baseline: Baseline | None = None
        if self.baseline_store is not None:
            baseline = await self.baseline_store.get(baseline_id)
        if baseline is None:
            baseline = next(
                (candidate for candidate in self.baselines if candidate.id == baseline_id),
                None,
            )
        if baseline is None:
            return None
        return next((check for check in baseline.checks if check.id == check_id), None)

    async def _record_snapshot_evidence(self, snapshot: DriftSnapshot) -> EvidenceRecord:
        if self.evidence_store is None:
            raise StoreUnavailable("record_evidence=True requires an EvidenceStore")
        record = EvidenceRecord(
            id="",
            tenant_id=snapshot.tenant_id,
            evidence_type="asset_config.drift_snapshot",
            schema_version=1,
            subject=Subject(object_ids=_failing_subjects(snapshot, self.config)),
            collected_at=snapshot.run_at,
            recorded_at=utc_now(),
            collector=self.actor,
            source_id=self.source_id,
            method="assetconfig.assess/v1",
            content={
                "snapshot_id": snapshot.id,
                "tenant_id": snapshot.tenant_id,
                "scope": snapshot.scope,
                "baseline_ids": snapshot.baseline_ids,
                "overall_score": snapshot.overall_score,
                "asset_drifts": [drift.model_dump(mode="json") for drift in snapshot.asset_drifts],
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0012", "kind": "drift_snapshot"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self.evidence_store.add(record)


def classify_asset(asset: AQObject, config: ACGConfig) -> str:
    return classify(asset, config.classification_rules)


def assess_asset(
    asset: AQObject,
    baselines: Sequence[Baseline],
    config: ACGConfig,
) -> list[AssetDrift]:
    drifts = [
        _assess_baseline(asset, baseline, config)
        for baseline in sorted(baselines, key=lambda item: item.id)
    ]
    drifts.sort(key=lambda item: (item.asset_id, item.baseline_id))
    return drifts


def explain(item: DriftItem) -> dict[str, object]:
    return {
        "asset_id": item.asset_id,
        "check_id": item.check_id,
        "key": item.key,
        "expected": item.expected,
        "observed": item.observed,
        "status": item.status,
        "severity": item.severity,
        "reason": item.reason,
    }


def _failing_items(asset_drift: AssetDrift, config: ACGConfig) -> list[DriftItem]:
    return [
        item
        for item in sorted(asset_drift.items, key=lambda drift_item: drift_item.check_id)
        if item.status == "fail" or (item.status == "unknown" and config.unknown_is_fail)
    ]


def _failing_subjects(snapshot: DriftSnapshot, config: ACGConfig) -> list[str]:
    return sorted(
        {
            asset_drift.asset_id
            for asset_drift in snapshot.asset_drifts
            if _failing_items(asset_drift, config)
        }
    )


def _assess_baseline(asset: AQObject, baseline: Baseline, config: ACGConfig) -> AssetDrift:
    items = [
        _assess_check(asset, check, config) for check in sorted(baseline.checks, key=lambda c: c.id)
    ]
    passed = sum(1 for item in items if item.status == "pass")
    failed = sum(1 for item in items if item.status == "fail") + (
        sum(1 for item in items if item.status == "unknown") if config.unknown_is_fail else 0
    )
    evaluated = len(items)
    return AssetDrift(
        asset_id=asset.id,
        baseline_id=baseline.id,
        evaluated=evaluated,
        passed=passed,
        failed=failed,
        score=(passed / evaluated) if evaluated else 1.0,
        items=items,
    )


def _assess_check(asset: AQObject, check: Any, config: ACGConfig) -> DriftItem:
    observed = _observed_value(asset, check.key)
    if observed is MISSING:
        return DriftItem(
            asset_id=asset.id,
            check_id=check.id,
            key=check.key,
            expected=check.expected,
            observed=None,
            status="unknown",
            severity=check.severity,
            reason=f"Observed value for {check.key!r} is missing.",
        )
    passed = compare(check.comparator, observed, check.expected)
    return DriftItem(
        asset_id=asset.id,
        check_id=check.id,
        key=check.key,
        expected=check.expected,
        observed=observed,
        status="pass" if passed else "fail",
        severity=check.severity,
        reason=(
            f"{check.key!r} matches expected value."
            if passed
            else f"{check.key!r} expected {check.expected!r} but observed {observed!r}."
        ),
    )


def _observed_value(asset: AQObject, key: str) -> object:
    observed = asset.attributes.get("observed_state", MISSING)
    if not isinstance(observed, Mapping):
        return MISSING
    if key in observed:
        return observed[key]
    current: object = observed
    for part in key.split("."):
        if not part or not isinstance(current, Mapping):
            return MISSING
        current = current.get(part, MISSING)
        if current is MISSING:
            return MISSING
    return current


async def _asset_pages(
    object_store: ObjectStore,
    *,
    tenant_id: str | None,
    scope: ObjectQuery | None,
    batch_size: int,
) -> AsyncIterator[list[AQObject]]:
    cursor = scope.cursor if scope is not None else None
    remaining = scope.limit if scope is not None else None
    seen_cursors: set[str] = set()
    while True:
        limit = batch_size if remaining is None else min(batch_size, remaining)
        if limit < 1:
            break
        query = _asset_query(tenant_id=tenant_id, scope=scope, cursor=cursor, limit=limit)
        rows, next_cursor = await object_store.query(query)
        yield rows
        if remaining is not None:
            remaining -= len(rows)
            if remaining <= 0:
                break
        if next_cursor is None or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _asset_query(
    *,
    tenant_id: str | None,
    scope: ObjectQuery | None,
    cursor: str | None,
    limit: int,
) -> ObjectQuery:
    data = scope.model_dump() if scope is not None else {}
    data.update(
        {
            "tenant_id": tenant_id,
            "object_type": ASSET_OBJECT_TYPE,
            "include_states": ("active",),
            "limit": limit,
            "cursor": cursor,
        }
    )
    return ObjectQuery.model_validate(data)


def _scope_dump(
    scope: ObjectQuery | None,
    *,
    tenant_id: str | None,
    batch_size: int,
) -> dict[str, Any]:
    return _asset_query(
        tenant_id=tenant_id,
        scope=scope,
        cursor=scope.cursor if scope is not None else None,
        limit=min(scope.limit, batch_size) if scope is not None else batch_size,
    ).model_dump(mode="json")


def _tenant_visible(baseline: Baseline, tenant_id: str | None) -> bool:
    if tenant_id is None:
        return baseline.tenant_id is None
    return baseline.tenant_id in (None, tenant_id)


def _mean(values: Sequence[float], *, default: float) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _trend_point(snapshot: DriftSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.id,
        "run_at": snapshot.run_at,
        "overall_score": snapshot.overall_score,
        "asset_scores": {
            drift.asset_id: drift.score
            for drift in sorted(snapshot.asset_drifts, key=lambda item: item.asset_id)
        },
    }


def _finding_for_drift(
    asset_drift: AssetDrift,
    item: DriftItem,
    *,
    snapshot: DriftSnapshot,
    evidence_id: str,
    check: Check | None,
    by: ActorRef,
) -> Finding:
    remediation_summary = check.rationale if check is not None else item.reason
    references = [] if check is None else _framework_refs(check)
    observed = "missing" if item.status == "unknown" else repr(item.observed)
    return Finding(
        id="",
        tenant_id=snapshot.tenant_id,
        finding_type="asset_config.drift",
        schema_version=1,
        dedup_key=(
            f"asset_config.drift:{asset_drift.asset_id}:{asset_drift.baseline_id}:{item.check_id}"
        ),
        title=f"Configuration drift on asset {asset_drift.asset_id}: {item.key}",
        severity=item.severity,
        severity_score=_SEVERITY_SCORES[item.severity],
        status="open",
        what_happened=(
            f"Asset {asset_drift.asset_id} failed check {item.check_id} "
            f"from baseline {asset_drift.baseline_id}."
        ),
        why_it_matters=remediation_summary,
        how_determined=(
            f"Drift snapshot {snapshot.id} compared observed value {observed} "
            f"for {item.key!r} against expected value {item.expected!r}."
        ),
        risk_of_inaction=(
            "Leaving configuration drift unresolved can keep the asset outside its "
            "declared baseline and weaken governance posture."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=[asset_drift.asset_id],
        expert_details={
            "snapshot_id": snapshot.id,
            "baseline_id": asset_drift.baseline_id,
            "check_id": item.check_id,
            "key": item.key,
            "expected": item.expected,
            "observed": item.observed,
            "status": item.status,
            "reason": item.reason,
            "asset_score": asset_drift.score,
            "raised_by": by.model_dump(mode="json"),
        },
        remediation=Remediation(
            summary=remediation_summary,
            steps=[
                (
                    f"Review asset {asset_drift.asset_id} and confirm the observed value "
                    f"for {item.key!r}."
                ),
                f"Align {item.key!r} with expected value {item.expected!r}.",
                "Rerun asset configuration governance and confirm the check passes.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The affected asset satisfies its declared baseline.",
            references=references,
        ),
        automation=Automation(
            eligibility="assisted",
            action_ref=ACG_REMEDIATION_ACTION,
            requires_approval=True,
            risk_note="Configuration remediation must be proposed through Workflow and approved.",
        ),
        confidence=1.0,
        source_engine="acg_engine",
        correlation_id=snapshot.id,
        first_detected_at=snapshot.run_at,
        last_detected_at=snapshot.run_at,
    )


def _playbook_for_drift(finding: Finding, *, snapshot: DriftSnapshot) -> Playbook:
    details = finding.expert_details or {}
    baseline_id = str(details.get("baseline_id", "unknown-baseline"))
    check_id = str(details.get("check_id", "unknown-check"))
    asset_id = finding.affected_object_ids[0]
    step_id = f"remediate-{_slug(asset_id)}-{_slug(check_id)}"
    return Playbook(
        id=f"acg-remediate-{_slug(snapshot.id)}-{_slug(finding.id)}",
        version=1,
        name=f"Remediate asset configuration drift for {asset_id}",
        description=("Proposed remediation for an Asset & Configuration Governance drift finding."),
        tenant_id=finding.tenant_id,
        steps=[
            Step(
                id=step_id,
                action_type=ACG_REMEDIATION_ACTION,
                inputs={
                    "asset_id": asset_id,
                    "finding_id": finding.id,
                    "snapshot_id": snapshot.id,
                    "baseline_id": baseline_id,
                    "check_id": check_id,
                    "key": details.get("key"),
                    "expected": details.get("expected"),
                    "observed": details.get("observed"),
                    "evidence_ids": list(finding.evidence_ids),
                    "remediation": finding.remediation.summary,
                },
                idempotency_key=(
                    f"acg:{snapshot.id}:{finding.id}:{asset_id}:{baseline_id}:{check_id}"
                ),
                requires_approval=True,
            )
        ],
    )


def _framework_refs(check: Check) -> list[str]:
    return [
        f"{ref.framework}:{ref.requirement}"
        for ref in sorted(check.framework_refs, key=lambda ref: (ref.framework, ref.requirement))
    ]


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-") or "id"
