"""Read-only asset drift assessment for Asset & Configuration Governance (A2)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from aqelyn.assetconfig.classify import classify
from aqelyn.assetconfig.comparators import MISSING, compare
from aqelyn.assetconfig.models import ACGConfig, AssetDrift, Baseline, DriftItem, DriftSnapshot
from aqelyn.conventions import utc_now
from aqelyn.conventions.errors import ObjectNotFound
from aqelyn.objects import AQObject, ObjectQuery, ObjectStore

ASSET_OBJECT_TYPE = "asset"


class AssetConfigAnalyzer:
    def __init__(
        self,
        object_store: ObjectStore,
        baselines: Sequence[Baseline],
        *,
        config: ACGConfig | None = None,
    ) -> None:
        self.object_store = object_store
        self.baselines = tuple(sorted(baselines, key=lambda baseline: baseline.id))
        self.config = config or ACGConfig()

    async def classify(self, asset_id: str, *, tenant_id: str | None = None) -> str:
        asset = await self._asset(asset_id, tenant_id=tenant_id)
        return classify_asset(asset, self.config)

    async def assess_asset(
        self, asset_id: str, *, tenant_id: str | None = None
    ) -> list[AssetDrift]:
        asset = await self._asset(asset_id, tenant_id=tenant_id)
        return assess_asset(asset, self._matching_baselines(asset), self.config)

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
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
                    assess_asset(asset, self._matching_baselines(asset), self.config)
                )
        asset_drifts.sort(key=lambda item: (item.asset_id, item.baseline_id))
        baseline_ids = sorted({item.baseline_id for item in asset_drifts})
        return DriftSnapshot(
            id="drift-snapshot",
            tenant_id=tenant_id,
            run_at=utc_now(),
            scope=_scope_dump(scope, tenant_id=tenant_id, batch_size=self.config.batch_size),
            baseline_ids=baseline_ids,
            overall_score=_mean([item.score for item in asset_drifts], default=1.0),
            asset_drifts=asset_drifts,
            evidence_id=None,
        )

    def explain(self, item: DriftItem) -> dict[str, object]:
        return explain(item)

    async def _asset(self, asset_id: str, *, tenant_id: str | None) -> AQObject:
        asset = await self.object_store.get(asset_id, resolve_merged=False)
        if asset is None or asset.object_type != ASSET_OBJECT_TYPE:
            raise ObjectNotFound(asset_id)
        if tenant_id is not None and asset.tenant_id != tenant_id:
            raise ObjectNotFound(asset_id)
        return asset

    def _matching_baselines(self, asset: AQObject) -> list[Baseline]:
        asset_class = classify_asset(asset, self.config)
        return [
            baseline
            for baseline in self.baselines
            if baseline.asset_class == asset_class and _tenant_visible(baseline, asset.tenant_id)
        ]


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
