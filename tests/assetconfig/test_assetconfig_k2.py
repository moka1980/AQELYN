"""C-023 K2 tests for EA-0012 drift trend delegation."""

from __future__ import annotations

from aqelyn.assetconfig import AssetConfigAnalyzer
from aqelyn.forecast import BasisRef, TrendRecord
from aqelyn.objects import InMemoryObjectStore

TENANT = "018f0000-0000-7000-8000-000000230201"


class _TrendSpy:
    def __init__(self, trend: TrendRecord) -> None:
        self.trend = trend
        self.calls: list[tuple[str, int, str | None]] = []

    async def analyze_trend(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> TrendRecord:
        self.calls.append((metric, window_days, tenant_id))
        return self.trend


async def test_acg_drift_trend_delegates_forecast() -> None:
    trend = TrendRecord(
        tenant_id=TENANT,
        metric="assetconfig.drift.overall_score",
        window_days=45,
        slope=-0.2,
        r_squared=0.91,
        direction="down",
        basis=[
            BasisRef(
                kind="metric",
                ref="assetconfig:drift-snapshots",
                window={"days": 45},
            )
        ],
        reason="EA-0021 computed drift trend from stored metric observations.",
    )
    spy = _TrendSpy(trend)
    analyzer = AssetConfigAnalyzer(
        InMemoryObjectStore(),
        [],
        trend_provider=spy,
    )

    result = await analyzer.trend(
        metric="assetconfig.drift.overall_score",
        window_days=45,
        tenant_id=TENANT,
    )

    assert result == trend
    assert spy.calls == [("assetconfig.drift.overall_score", 45, TENANT)]
