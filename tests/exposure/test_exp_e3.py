"""E3 acceptance tests for owner-engine delegation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from aqelyn.conventions import new_id
from aqelyn.exposure import (
    AssetRef,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    StaticKnownSurfaceSource,
)
from aqelyn.forecast import BasisRef, TrendRecord
from aqelyn.graph import EdgeView, Path
from aqelyn.iag import AccessPath, AccessRisk, AccessRiskReport
from aqelyn.objects import SourceRef

NOW = datetime(2026, 7, 16, 22, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000230201"


class _GraphSpy:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[dict[str, object]] = []

    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
        max_work: int = 50_000,
    ) -> list[Path]:
        self.calls.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "direction": direction,
                "relation_types": relation_types,
                "max_depth": max_depth,
                "max_paths": max_paths,
                "max_work": max_work,
            }
        )
        return [self.path]


class _IAGSpy:
    def __init__(self, path: Path, risk_report: AccessRiskReport) -> None:
        self.path = path
        self.risk_report = risk_report
        self.access_calls: list[tuple[str, str | None]] = []
        self.risk_calls: list[tuple[str | None, object | None]] = []

    async def access_paths(
        self, identity_id: str, *, tenant_id: str | None = None
    ) -> list[AccessPath]:
        self.access_calls.append((identity_id, tenant_id))
        return [
            AccessPath(
                identity_id=identity_id,
                account_id=None,
                entitlement_ids=[],
                via=self.path,
            )
        ]

    async def analyze_risk(
        self, *, tenant_id: str | None, scope: object | None = None
    ) -> AccessRiskReport:
        self.risk_calls.append((tenant_id, scope))
        return self.risk_report


class _TrendSpy:
    def __init__(self, trend_record: TrendRecord) -> None:
        self.trend_record = trend_record
        self.calls: list[tuple[str, int, str | None]] = []

    async def analyze_trend(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> TrendRecord:
        self.calls.append((metric, window_days, tenant_id))
        return self.trend_record


def _asset_ref(kind: str, ref_id: str) -> AssetRef:
    return AssetRef(kind=kind, ref_id=ref_id, evidence_id=new_id("evd"))


def _edge(from_id: str, to_id: str) -> EdgeView:
    return EdgeView(
        id=new_id("rel"),
        from_id=from_id,
        to_id=to_id,
        relation_type="reachable_from",
        confidence=0.9,
        sources=[
            SourceRef(
                source_id=new_id("src"),
                evidence_id=new_id("evd"),
                observed_at=NOW,
                method="exposure-test",
            )
        ],
    )


def _path(from_id: str, to_id: str) -> Path:
    return Path(
        node_ids=[from_id, to_id],
        edges=[_edge(from_id, to_id)],
        length=1,
    )


async def test_exp_paths_delegate_kg() -> None:
    root_id = new_id("obj")
    target_id = new_id("obj")
    graph = _GraphSpy(_path(root_id, target_id))
    engine = KnownDataExposureEngine(
        InMemoryExposureStore(mode="enterprise"),
        StaticKnownSurfaceSource([]),
        graph=graph,
        path_roots=[root_id],
    )

    paths = await engine.reachable_paths(target_ref=target_id, tenant_id=TENANT)

    assert graph.calls == [
        {
            "from_id": root_id,
            "to_id": target_id,
            "direction": "out",
            "relation_types": None,
            "max_depth": 6,
            "max_paths": 20,
            "max_work": 50_000,
        }
    ]
    assert len(paths) == 1
    assert paths[0].target_ref == target_id
    assert paths[0].path == [root_id, target_id]
    assert paths[0].via == "graph"


async def test_exp_identity_cites_iag() -> None:
    identity_id = new_id("obj")
    entitlement_id = new_id("obj")
    path = _path(identity_id, entitlement_id)
    risk_report = AccessRiskReport(
        risks=[
            AccessRisk(
                kind="over_privilege",
                subject_id=identity_id,
                detail={"entitlement_id": entitlement_id},
                severity="high",
                evidence_path=path,
                reason="IAG detected over-privilege.",
            )
        ],
        evaluated=1,
        truncated=False,
    )
    iag = _IAGSpy(path, risk_report)
    store = InMemoryExposureStore(mode="enterprise")
    engine = KnownDataExposureEngine(
        store,
        StaticKnownSurfaceSource([]),
        identity_provider=iag,
    )

    exposure = await engine.identity_exposure(
        asset_ref=_asset_ref("identity", identity_id),
        tenant_id=TENANT,
    )

    assert iag.access_calls == [(identity_id, TENANT)]
    assert iag.risk_calls == [(TENANT, None)]
    assert exposure.exposure_type == "identity_access"
    assert exposure.reachability == "unknown"
    assert exposure.flagged is True
    assert "no entitlement verdict" in exposure.rationale
    assert {basis.kind for basis in exposure.basis} == {"access"}
    assert {basis.evidence_id for basis in exposure.basis} == {path.edges[0].sources[0].evidence_id}
    assert [row.id for row in await store.query(tenant_id=TENANT)] == [exposure.id]


async def test_exp_trend_delegates_forecast() -> None:
    trend = TrendRecord(
        tenant_id=TENANT,
        metric="external_exposure_count",
        window_days=30,
        slope=1.5,
        r_squared=0.7,
        direction="up",
        basis=[
            BasisRef(
                kind="metric",
                ref="exposure:external_exposure_count",
                window={"days": 30},
                evidence_id=new_id("evd"),
            )
        ],
        reason="External exposure count is increasing.",
    )
    forecast = _TrendSpy(trend)
    engine = KnownDataExposureEngine(
        InMemoryExposureStore(mode="enterprise"),
        StaticKnownSurfaceSource([]),
        trend_provider=forecast,
    )

    result = await engine.trend(
        category="external_exposure_count",
        window_days=30,
        tenant_id=TENANT,
    )

    assert result == trend
    assert forecast.calls == [("external_exposure_count", 30, TENANT)]
