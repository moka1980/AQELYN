"""G2 acceptance tests for Compliance & Governance assessment runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from aqelyn.conventions import ActorRef, new_id
from aqelyn.governance import ComplianceEngine, ControlResult, GovernanceConfig
from aqelyn.objects import AQObject, InMemoryObjectStore, ObjectQuery, ObjectStore, SourceRef
from aqelyn.policy import Condition, Policy, PolicyEngine, Rule, Target

SYS = ActorRef(actor_type="system", actor_id="governance-g2-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "governance-g2-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


def _obj(
    name: str,
    *,
    tenant_id: str | None = None,
    attrs: dict[str, Any] | None = None,
    state: str = "active",
) -> AQObject:
    now = _now()
    return AQObject(
        id="",
        object_type="generic",
        schema_version=1,
        tenant_id=tenant_id,
        display_name=name,
        attributes=attrs or {},
        sources=[_source(f"governance:{name}")],
        lifecycle_state=state,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )


def _condition(payload: dict[str, object]) -> Condition:
    return Condition.model_validate(payload)


def _policy(
    policy_id: str = "policy-mfa",
    *,
    tenant_id: str | None = None,
    attr: str = "mfa_enabled",
    expected: object = True,
) -> Policy:
    return Policy(
        id=policy_id,
        version=1,
        name=f"Policy {policy_id}",
        description=f"Require {attr}",
        tenant_id=tenant_id,
        rules=[
            Rule(
                id=f"{policy_id}-rule",
                kind="compliance",
                description=f"{attr} must be {expected!r}",
                target=Target(actions=None, resource_types=["generic"]),
                condition=_condition(
                    {"op": "eq", "attr": f"resource.attributes.{attr}", "value": expected}
                ),
                effect="require",
                obligations=[],
                priority=0,
            )
        ],
        standard="aqelyn/governance-test",
        set_by=SYS,
        set_at=_now(),
    )


def _config(policy_id: str = "policy-mfa", *, batch_size: int = 100) -> GovernanceConfig:
    return GovernanceConfig.model_validate(
        {
            "controls": [
                {
                    "id": "control-mfa",
                    "name": "MFA enabled",
                    "description": "Generic objects must have MFA enabled.",
                    "policy_ids": [policy_id],
                    "framework_refs": [{"framework": "AQ", "requirement": "AQ-1"}],
                    "severity": "high",
                }
            ],
            "frameworks": {"AQ": ["AQ-1"]},
            "batch_size": batch_size,
            "min_confidence": 0.0,
        },
        context={"known_policy_ids": {policy_id}},
    )


def _engine(
    object_store: ObjectStore,
    *,
    policy: Policy | None = None,
    policies: list[Policy] | None = None,
    config: GovernanceConfig | None = None,
) -> ComplianceEngine:
    selected_policies = policies or [policy or _policy()]
    return ComplianceEngine(
        object_store,
        PolicyEngine(selected_policies),
        config=config or _config(selected_policies[0].id),
    )


async def test_gov_assess_estate(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    passed = await store.upsert(_obj("passing", attrs={"mfa_enabled": True}))
    failed = await store.upsert(_obj("failing", attrs={"mfa_enabled": False}))
    engine = _engine(
        store,
        policies=[_policy(), _policy("policy-unrelated", attr="disk_encrypted")],
        config=_config("policy-mfa"),
    )

    snapshot = await engine.assess(tenant_id=None, record_evidence=False)

    result = snapshot.control_results[0]
    assert result.evaluated == 2
    assert result.passed == 1
    assert result.failed == 1
    assert result.failing_subject_ids == [failed.id]
    assert passed.id not in result.failing_subject_ids
    assert result.score == 0.5
    assert snapshot.overall_score == 0.5
    assert snapshot.evidence_id is None


async def test_gov_deterministic(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    await store.upsert(_obj("b", attrs={"mfa_enabled": False}))
    await store.upsert(_obj("a", attrs={"mfa_enabled": True}))
    engine = _engine(store)

    first = await engine.assess(tenant_id=None, record_evidence=False)
    second = await engine.assess(tenant_id=None, record_evidence=False)

    first_data = first.model_dump(mode="json", exclude={"id", "run_at"})
    second_data = second.model_dump(mode="json", exclude={"id", "run_at"})
    assert first_data == second_data


async def test_gov_control_result(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    await store.upsert(_obj("passing", attrs={"mfa_enabled": True}))
    failed = await store.upsert(_obj("failing", attrs={"mfa_enabled": False}))
    engine = _engine(store)

    result = await engine.control_result("control-mfa", tenant_id=None)
    explanation = engine.explain(result)

    assert result == ControlResult(
        control_id="control-mfa",
        evaluated=2,
        passed=1,
        failed=1,
        failing_subject_ids=[failed.id],
        score=0.5,
        reason="Control control-mfa evaluated 2 target(s): 1 passed, 1 failed.",
    )
    assert explanation["control_id"] == "control-mfa"
    assert explanation["failing_subject_ids"] == [failed.id]


async def test_gov_no_targets(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    engine = _engine(store)

    snapshot = await engine.assess(tenant_id=None, record_evidence=False)

    result = snapshot.control_results[0]
    assert result.evaluated == 0
    assert result.passed == 0
    assert result.failed == 0
    assert result.score == 1.0
    assert "no in-scope targets" in result.reason
    assert snapshot.overall_score == 1.0


async def test_gov_bounded_batches() -> None:
    objects = [
        _obj("one", attrs={"mfa_enabled": True}),
        _obj("two", attrs={"mfa_enabled": False}),
        _obj("three", attrs={"mfa_enabled": True}),
    ]
    for obj in objects:
        obj.id = new_id("obj")
    store = _PagedObjectStore(objects)
    engine = _engine(cast(ObjectStore, store), config=_config(batch_size=1))

    snapshot = await engine.assess(tenant_id=None, record_evidence=False)

    assert [query.limit for query in store.queries] == [1, 1, 1]
    assert [query.cursor for query in store.queries] == [None, "1", "2"]
    assert snapshot.control_results[0].evaluated == 3
    assert snapshot.control_results[0].failed == 1


async def test_gov_tenant_isolation() -> None:
    store = InMemoryObjectStore(mode="enterprise")
    tenant_a = await store.upsert(_obj("tenant-a", tenant_id=TENANT_A, attrs={"mfa_enabled": True}))
    tenant_b = await store.upsert(
        _obj("tenant-b", tenant_id=TENANT_B, attrs={"mfa_enabled": False})
    )
    engine = _engine(store)

    snapshot = await engine.assess(tenant_id=TENANT_A, record_evidence=False)

    result = snapshot.control_results[0]
    assert result.evaluated == 1
    assert result.passed == 1
    assert result.failed == 0
    assert tenant_a.id not in result.failing_subject_ids
    assert tenant_b.id not in result.failing_subject_ids
    assert snapshot.tenant_id == TENANT_A


async def test_gov_no_side_effects(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    obj = await store.upsert(_obj("unchanged", attrs={"mfa_enabled": False}))
    policy = _policy()
    policy_before = policy.model_dump_json()
    stored_before = await store.get(obj.id)
    assert stored_before is not None
    engine = _engine(store, policy=policy)

    await engine.assess(tenant_id=None, record_evidence=False)

    stored_after = await store.get(obj.id)
    assert stored_after is not None
    assert stored_after.model_dump(mode="json") == stored_before.model_dump(mode="json")
    assert policy.model_dump_json() == policy_before


class _PagedObjectStore:
    def __init__(self, objects: list[AQObject]) -> None:
        self._objects = sorted(objects, key=lambda obj: obj.id)
        self.queries: list[ObjectQuery] = []

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        self.queries.append(q)
        start = int(q.cursor or "0")
        stop = start + q.limit
        rows = [
            obj
            for obj in self._objects[start:stop]
            if obj.lifecycle_state in q.include_states
            and (q.tenant_id is None or obj.tenant_id == q.tenant_id)
            and (q.object_type is None or obj.object_type == q.object_type)
        ]
        next_cursor = str(stop) if stop < len(self._objects) else None
        return rows, next_cursor
