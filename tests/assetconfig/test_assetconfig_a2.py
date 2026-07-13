"""A2 acceptance tests for classification and drift detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from aqelyn.assetconfig import (
    ASSET_OBJECT_TYPE,
    ACGConfig,
    AssetConfigAnalyzer,
    Baseline,
    Check,
)
from aqelyn.conventions import ActorRef, new_id
from aqelyn.findings.models import Severity
from aqelyn.objects import AQObject, AQRelationship, InMemoryObjectStore, ObjectQuery, SourceRef

SYS = ActorRef(actor_type="system", actor_id="assetconfig-a2-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "assetconfig-a2-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


def _store(*, mode: str = "local") -> InMemoryObjectStore:
    store = InMemoryObjectStore(mode=mode)
    store.registry.register(ASSET_OBJECT_TYPE, 1, None)
    return store


def _asset(
    name: str,
    *,
    tenant_id: str | None = None,
    observed: dict[str, Any] | None = None,
    attrs: dict[str, Any] | None = None,
    labels: dict[str, str] | None = None,
) -> AQObject:
    now = _now()
    attributes = dict(attrs or {})
    attributes["observed_state"] = dict(observed or {})
    return AQObject(
        id="",
        object_type=ASSET_OBJECT_TYPE,
        schema_version=1,
        tenant_id=tenant_id,
        display_name=name,
        attributes=attributes,
        labels=labels or {},
        sources=[_source(f"asset:{name}")],
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )


def _check(
    check_id: str,
    key: str,
    expected: object,
    comparator: str = "eq",
    *,
    severity: Severity = "high",
) -> Check:
    return Check(
        id=check_id,
        key=key,
        expected=expected,
        comparator=comparator,
        severity=severity,
        rationale=f"{key} should satisfy {check_id}.",
        framework_refs=[],
    )


def _baseline(
    baseline_id: str,
    asset_class: str,
    *checks: Check,
    tenant_id: str | None = None,
) -> Baseline:
    return Baseline(
        id=baseline_id,
        name=f"Baseline {baseline_id}",
        asset_class=asset_class,
        version=1,
        checks=list(checks) or [_check("ssh-root", "ssh.permit_root_login", "no")],
        tenant_id=tenant_id,
        set_by=SYS,
        set_at=_now(),
    )


def _config(*, unknown_is_fail: bool = True, batch_size: int = 100) -> ACGConfig:
    return ACGConfig(
        batch_size=batch_size,
        unknown_is_fail=unknown_is_fail,
        classification_rules=[
            {
                "asset_class": "linux_server",
                "condition": {
                    "op": "eq",
                    "attr": "attributes.os_family",
                    "value": "linux",
                },
            },
            {
                "asset_class": "windows_server",
                "condition": {
                    "op": "eq",
                    "attr": "attributes.os_family",
                    "value": "windows",
                },
            },
        ],
    )


async def test_acg_classification() -> None:
    store = _store()
    linux = await store.upsert(
        _asset("linux-1", attrs={"os_family": "linux"}, observed={"ssh.root": "no"})
    )
    other = await store.upsert(
        _asset("unknown-1", attrs={"os_family": "network"}, observed={"ssh.root": "no"})
    )
    analyzer = AssetConfigAnalyzer(store, [], config=_config())

    assert await analyzer.classify(linux.id, tenant_id=None) == "linux_server"
    assert await analyzer.classify(other.id, tenant_id=None) == "unclassified"


async def test_acg_assess_estate() -> None:
    store = _store()
    passed = await store.upsert(
        _asset("passing", attrs={"os_family": "linux"}, observed={"ssh.root": "no"})
    )
    failed = await store.upsert(
        _asset("failing", attrs={"os_family": "linux"}, observed={"ssh.root": "yes"})
    )
    analyzer = AssetConfigAnalyzer(
        store,
        [_baseline("cis-linux", "linux_server", _check("ssh-root", "ssh.root", "no"))],
        config=_config(),
    )

    snapshot = await analyzer.assess(tenant_id=None, record_evidence=False)

    assert snapshot.evidence_id is None
    assert snapshot.baseline_ids == ["cis-linux"]
    assert snapshot.overall_score == 0.5
    by_asset = {drift.asset_id: drift for drift in snapshot.asset_drifts}
    assert by_asset[passed.id].passed == 1
    assert by_asset[passed.id].failed == 0
    assert by_asset[failed.id].passed == 0
    assert by_asset[failed.id].failed == 1


async def test_acg_deterministic() -> None:
    store = _store()
    await store.upsert(_asset("b", attrs={"os_family": "linux"}, observed={"ssh.root": "yes"}))
    await store.upsert(_asset("a", attrs={"os_family": "linux"}, observed={"ssh.root": "no"}))
    analyzer = AssetConfigAnalyzer(
        store,
        [
            _baseline(
                "cis-linux",
                "linux_server",
                _check("z-check", "ssh.root", "no"),
                _check("a-check", "kernel.panic", 0, "gte", severity="medium"),
            )
        ],
        config=_config(),
    )

    first = await analyzer.assess(tenant_id=None, record_evidence=False)
    second = await analyzer.assess(tenant_id=None, record_evidence=False)

    assert first.model_dump(mode="json", exclude={"id", "run_at"}) == second.model_dump(
        mode="json",
        exclude={"id", "run_at"},
    )


async def test_acg_drift_item() -> None:
    store = _store()
    asset = await store.upsert(
        _asset("linux-1", attrs={"os_family": "linux"}, observed={"ssh.root": "yes"})
    )
    analyzer = AssetConfigAnalyzer(
        store,
        [_baseline("cis-linux", "linux_server", _check("ssh-root", "ssh.root", "no"))],
        config=_config(),
    )

    drift = (await analyzer.assess_asset(asset.id, tenant_id=None))[0]
    item = drift.items[0]

    assert item.asset_id == asset.id
    assert item.check_id == "ssh-root"
    assert item.key == "ssh.root"
    assert item.expected == "no"
    assert item.observed == "yes"
    assert item.status == "fail"
    assert item.severity == "high"
    assert "expected" in item.reason
    assert analyzer.explain(item)["observed"] == "yes"


async def test_acg_unknown_handling() -> None:
    store = _store()
    asset = await store.upsert(_asset("linux-1", attrs={"os_family": "linux"}, observed={}))
    baseline = _baseline("cis-linux", "linux_server", _check("ssh-root", "ssh.root", "no"))
    fail_unknown = AssetConfigAnalyzer(store, [baseline], config=_config(unknown_is_fail=True))
    do_not_fail_unknown = AssetConfigAnalyzer(
        store,
        [baseline],
        config=_config(unknown_is_fail=False),
    )

    failing = (await fail_unknown.assess_asset(asset.id, tenant_id=None))[0]
    not_failing = (await do_not_fail_unknown.assess_asset(asset.id, tenant_id=None))[0]

    assert failing.items[0].status == "unknown"
    assert failing.items[0].observed is None
    assert failing.failed == 1
    assert not_failing.items[0].status == "unknown"
    assert not_failing.failed == 0


async def test_acg_baseline_scoping() -> None:
    store = _store()
    asset = await store.upsert(
        _asset("linux-1", attrs={"os_family": "linux"}, observed={"ssh.root": "no"})
    )
    analyzer = AssetConfigAnalyzer(
        store,
        [
            _baseline("cis-linux", "linux_server", _check("ssh-root", "ssh.root", "no")),
            _baseline(
                "cis-windows",
                "windows_server",
                _check("rdp-enabled", "rdp.enabled", False),
            ),
        ],
        config=_config(),
    )

    drifts = await analyzer.assess_asset(asset.id, tenant_id=None)

    assert [drift.baseline_id for drift in drifts] == ["cis-linux"]


async def test_acg_tenant_isolation() -> None:
    store = _store(mode="enterprise")
    asset_a = await store.upsert(
        _asset(
            "tenant-a",
            tenant_id=TENANT_A,
            attrs={"os_family": "linux"},
            observed={"ssh.root": "no", "audit.enabled": True},
        )
    )
    asset_b = await store.upsert(
        _asset(
            "tenant-b",
            tenant_id=TENANT_B,
            attrs={"os_family": "linux"},
            observed={"ssh.root": "yes", "audit.enabled": False},
        )
    )
    analyzer = AssetConfigAnalyzer(
        store,
        [
            _baseline("global-linux", "linux_server", _check("ssh-root", "ssh.root", "no")),
            _baseline(
                "tenant-a-linux",
                "linux_server",
                _check("audit", "audit.enabled", True),
                tenant_id=TENANT_A,
            ),
            _baseline(
                "tenant-b-linux",
                "linux_server",
                _check("audit", "audit.enabled", False),
                tenant_id=TENANT_B,
            ),
        ],
        config=_config(),
    )

    snapshot = await analyzer.assess(tenant_id=TENANT_A, record_evidence=False)

    assert {drift.asset_id for drift in snapshot.asset_drifts} == {asset_a.id}
    assert {drift.baseline_id for drift in snapshot.asset_drifts} == {
        "global-linux",
        "tenant-a-linux",
    }
    assert asset_b.id not in {drift.asset_id for drift in snapshot.asset_drifts}


async def test_acg_bounded_batches() -> None:
    assets = [
        _asset(
            f"asset-{index}",
            attrs={"os_family": "linux"},
            observed={"ssh.root": "no"},
        ).model_copy(update={"id": new_id("obj")})
        for index in range(5)
    ]
    store = _PagedReadOnlyStore(assets)
    analyzer = AssetConfigAnalyzer(
        cast(Any, store),
        [_baseline("cis-linux", "linux_server", _check("ssh-root", "ssh.root", "no"))],
        config=_config(batch_size=2),
    )

    snapshot = await analyzer.assess(tenant_id=None, record_evidence=False)

    assert len(snapshot.asset_drifts) == 5
    assert [call.limit for call in store.calls] == [2, 2, 2]
    assert [call.cursor for call in store.calls] == [None, "2", "4"]


@dataclass(frozen=True)
class _QueryCall:
    limit: int
    cursor: str | None


@dataclass
class _PagedReadOnlyStore:
    assets: list[AQObject]
    calls: list[_QueryCall] = field(default_factory=list)

    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        for asset in self.assets:
            if asset.id == object_id:
                return asset.model_copy(deep=True)
        return None

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        self.calls.append(_QueryCall(limit=q.limit, cursor=q.cursor))
        rows = [
            asset
            for asset in sorted(self.assets, key=lambda item: item.id)
            if q.object_type in (None, asset.object_type)
            and (q.tenant_id is None or asset.tenant_id == q.tenant_id)
            and asset.lifecycle_state in q.include_states
        ]
        start = int(q.cursor or "0")
        page = rows[start : start + q.limit]
        next_index = start + len(page)
        next_cursor = str(next_index) if next_index < len(rows) else None
        return [asset.model_copy(deep=True) for asset in page], next_cursor

    async def upsert(self, obj: AQObject) -> AQObject:
        raise AssertionError("A2 assessment must not mutate objects")

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        raise AssertionError("A2 assessment must not mutate objects")

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        raise AssertionError("A2 assessment must not mutate relationships")

    async def relationships(
        self,
        object_id: str,
        *,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[AQRelationship]:
        return []

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        raise AssertionError("A2 assessment must not mutate objects")

    async def set_state(
        self,
        object_id: str,
        state: str,
        *,
        by: ActorRef,
        expected_version: int,
    ) -> AQObject:
        raise AssertionError("A2 assessment must not mutate objects")

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        return []
