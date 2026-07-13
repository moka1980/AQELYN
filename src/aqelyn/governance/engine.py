"""Compliance assessment engine (EA-0010 G2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import GovernanceConfigInvalid
from aqelyn.governance.models import ComplianceSnapshot, Control, ControlResult, GovernanceConfig
from aqelyn.objects import AQObject, ObjectQuery, ObjectStore
from aqelyn.policy import PolicyEngine


class ComplianceEngine:
    """Runs configured governance controls across the object estate."""

    def __init__(
        self,
        object_store: ObjectStore,
        policy_engine: PolicyEngine,
        *,
        config: GovernanceConfig,
    ) -> None:
        self._object_store = object_store
        self._policy_engine = policy_engine
        self._config = config.model_copy(deep=True)
        self._controls = {control.id: control for control in self._config.controls}

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
        record_evidence: bool = True,
    ) -> ComplianceSnapshot:
        del record_evidence  # Evidence recording is introduced in C-007/G4.

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
        return ComplianceSnapshot(
            id=new_id("snap"),
            tenant_id=tenant_id,
            run_at=utc_now(),
            scope=_scope_dump(scope, tenant_id=tenant_id, batch_size=self._config.batch_size),
            overall_score=overall_score,
            control_results=control_results,
            framework_scores={},
            evidence_id=None,
        )

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


def _mean(values: list[float], *, default: float) -> float:
    if not values:
        return default
    return sum(values) / len(values)
