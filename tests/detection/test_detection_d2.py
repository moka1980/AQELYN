"""D2 acceptance tests for versioned detection profiles and stores."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import DetectionConfigInvalid, OptimisticConcurrencyConflict
from aqelyn.detection import (
    BehaviorProfile,
    DetectionConfig,
    DetectionRule,
    InMemoryProfileStore,
    InMemoryRuleStore,
    ProfileStore,
    RuleStore,
    build_profile,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000171"
TENANT_B = "018f0000-0000-7000-8000-000000000172"
NOW = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


@dataclass
class DetectionStores:
    kind: str
    rules: RuleStore
    profiles: ProfileStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def rule_store(request: pytest.FixtureRequest) -> AsyncIterator[RuleStore]:
    if request.param == "inmemory":
        yield InMemoryRuleStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.detection.postgres import PostgresRuleStore

    store = await PostgresRuleStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_behavior_profile, aq_detection_rule")
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def profile_store(request: pytest.FixtureRequest) -> AsyncIterator[ProfileStore]:
    if request.param == "inmemory":
        yield InMemoryProfileStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.detection.postgres import PostgresProfileStore

    store = await PostgresProfileStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_behavior_profile, aq_detection_rule")
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def detection_stores(request: pytest.FixtureRequest) -> AsyncIterator[DetectionStores]:
    if request.param == "inmemory":
        yield DetectionStores(
            kind="inmemory",
            rules=InMemoryRuleStore(),
            profiles=InMemoryProfileStore(),
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.detection.postgres import PostgresProfileStore, PostgresRuleStore

    rules = await PostgresRuleStore.connect(PG_URL)
    profiles = await PostgresProfileStore.connect(PG_URL)
    async with rules._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_behavior_profile, aq_detection_rule")
    try:
        yield DetectionStores(kind="postgres", rules=rules, profiles=profiles)
    finally:
        await profiles.close()
        await rules.close()


async def test_det_profile_versioned(profile_store: ProfileStore) -> None:
    observations = _observations(3.0, 4.0, 5.0, 6.0, 7.0)
    config = DetectionConfig(window_days=30, min_samples=3)

    first = await build_profile(
        subject_ref="acct:alice",
        metric="logins_per_day",
        tenant_id=TENANT_A,
        observations=observations,
        profile_store=profile_store,
        config=config,
        as_of=NOW,
    )
    second = await build_profile(
        subject_ref="acct:alice",
        metric="logins_per_day",
        tenant_id=TENANT_A,
        observations=[*observations, (NOW, 47.0)],
        profile_store=profile_store,
        config=config,
        as_of=NOW + timedelta(minutes=1),
    )

    assert first.id == second.id
    assert (first.version, second.version) == (1, 2)
    assert first.insufficient_data is False
    assert first.baseline["n"] == 5
    assert second.baseline["n"] == 6

    loaded_first = await profile_store.get(first.id, version=1)
    assert loaded_first is not None
    assert loaded_first.baseline == first.baseline

    attempted_overwrite = first.model_copy(
        update={"baseline": {"n": 999, "insufficient_data": False}, "version": 1},
        deep=True,
    )
    third = await profile_store.put(attempted_overwrite)

    assert third.id == first.id
    assert third.version == 3
    loaded_first_again = await profile_store.get(first.id, version=1)
    assert loaded_first_again is not None
    assert loaded_first_again.baseline == first.baseline

    insufficient = await build_profile(
        subject_ref="acct:bob",
        metric="logins_per_day",
        tenant_id=TENANT_A,
        observations=[(NOW, 1.0)],
        profile_store=profile_store,
        config=config,
        as_of=NOW,
    )
    assert insufficient.insufficient_data is True
    assert insufficient.baseline["insufficient_data"] is True
    assert insufficient.baseline["n"] == 1


async def test_det_rule_contract(rule_store: RuleStore) -> None:
    global_v1 = await rule_store.put(_rule(rule_id="rule-login", version=1))
    global_v2_disabled = await rule_store.put(_rule(rule_id="rule-login", version=2, enabled=False))
    await rule_store.put(_rule(rule_id="rule-tenant", tenant_id=TENANT_A))
    await rule_store.put(_rule(rule_id="rule-other-tenant", tenant_id=TENANT_B))

    loaded_v1 = await rule_store.get("rule-login", version=1)
    assert loaded_v1 is not None
    assert loaded_v1.model_dump(mode="json") == global_v1.model_dump(mode="json")
    latest = await rule_store.get("rule-login")
    assert latest is not None
    assert latest.model_dump(mode="json") == global_v2_disabled.model_dump(mode="json")

    enabled = await rule_store.list(tenant_id=TENANT_A)
    assert [rule.id for rule in enabled] == ["rule-login", "rule-tenant"]
    assert [rule.version for rule in enabled if rule.id == "rule-login"] == [1]
    all_visible = await rule_store.list(tenant_id=TENANT_A, enabled_only=False)
    assert [rule.id for rule in all_visible] == ["rule-login", "rule-tenant"]
    assert [rule.version for rule in all_visible if rule.id == "rule-login"] == [2]
    assert "rule-other-tenant" not in {rule.id for rule in all_visible}

    global_only = await rule_store.list(tenant_id=None)
    assert [rule.id for rule in global_only] == ["rule-login"]

    with pytest.raises(OptimisticConcurrencyConflict):
        await rule_store.put(global_v1)

    loaded_v1.name = "mutated"
    reloaded_v1 = await rule_store.get("rule-login", version=1)
    assert reloaded_v1 is not None
    assert reloaded_v1.name == global_v1.name


async def test_det_profile_contract(profile_store: ProfileStore) -> None:
    first = await profile_store.put(_profile(subject_ref="acct:alice", tenant_id=TENANT_A))
    second = await profile_store.put(
        first.model_copy(
            update={
                "baseline": {"n": 6, "mean": 2.5, "insufficient_data": False},
                "version": 1,
            },
            deep=True,
        )
    )
    other_tenant = await profile_store.put(
        _profile(subject_ref="acct:alice", tenant_id=TENANT_B, mean=99.0)
    )

    assert first.id == second.id
    assert (first.version, second.version) == (1, 2)
    assert other_tenant.id != first.id
    assert other_tenant.version == 1

    loaded_first = await profile_store.get(first.id, version=1)
    assert loaded_first is not None
    assert loaded_first.baseline == first.baseline
    loaded_latest = await profile_store.get(first.id)
    assert loaded_latest is not None
    assert loaded_latest.version == 2

    latest_a = await profile_store.latest(
        subject_ref="acct:alice",
        metric="logins_per_day",
        tenant_id=TENANT_A,
    )
    latest_b = await profile_store.latest(
        subject_ref="acct:alice",
        metric="logins_per_day",
        tenant_id=TENANT_B,
    )
    assert latest_a is not None
    assert latest_a.id == first.id
    assert latest_a.version == 2
    assert latest_b is not None
    assert latest_b.id == other_tenant.id
    assert (
        await profile_store.latest(
            subject_ref="acct:alice",
            metric="logins_per_day",
            tenant_id=None,
        )
        is None
    )
    assert await profile_store.get(new_id("prf")) is None

    latest_a.baseline["n"] = 999
    reloaded_latest = await profile_store.get(first.id)
    assert reloaded_latest is not None
    assert reloaded_latest.baseline["n"] == 6

    with pytest.raises(DetectionConfigInvalid):
        await profile_store.get(first.id, version=0)


async def test_det_rule_and_profile_contract_same_backend(
    detection_stores: DetectionStores,
) -> None:
    rule = await detection_stores.rules.put(_rule(rule_id="rule-same-backend"))
    profile = await detection_stores.profiles.put(
        _profile(subject_ref="acct:same-backend", tenant_id=TENANT_A)
    )

    assert (await detection_stores.rules.get(rule.id)) is not None
    assert (await detection_stores.profiles.get(profile.id)) is not None


def _rule(
    *,
    rule_id: str,
    version: int = 1,
    tenant_id: str | None = None,
    enabled: bool = True,
) -> DetectionRule:
    return DetectionRule(
        id=rule_id,
        name=f"Rule {rule_id}",
        description="D2 rule contract.",
        kind="rule",
        condition={"op": "eq", "attr": "signal.type", "value": "login"},
        subject_type="identity",
        technique_ids=["T1078"],
        severity="high",
        enabled=enabled,
        version=version,
        tenant_id=tenant_id,
    )


def _profile(
    *,
    subject_ref: str,
    tenant_id: str | None,
    metric: str = "logins_per_day",
    mean: float = 2.0,
) -> BehaviorProfile:
    return BehaviorProfile(
        tenant_id=tenant_id,
        subject_ref=subject_ref,
        metric=metric,
        window_days=30,
        baseline={
            "n": 5,
            "mean": mean,
            "stddev": 1.0,
            "p95": mean + 2.0,
            "insufficient_data": False,
        },
        computed_at=NOW,
        version=1,
        insufficient_data=False,
    )


def _observations(*values: float) -> list[tuple[datetime, float]]:
    return [(NOW - timedelta(days=index + 1), value) for index, value in enumerate(values)]
