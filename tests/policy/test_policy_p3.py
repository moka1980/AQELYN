"""P3 acceptance tests for PolicyStore persistence."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import PolicyConfigInvalid, SchemaValidationError
from aqelyn.policy import (
    Condition,
    InMemoryPolicyStore,
    Policy,
    PolicyStore,
    PostgresPolicyStore,
    Rule,
    Target,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="policy-p3-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _condition(payload: dict[str, object]) -> Condition:
    return Condition.model_validate(payload)


def _rule(rule_id: str = "permit-read", *, effect: str = "permit") -> Rule:
    return Rule(
        id=rule_id,
        kind="authorization",
        description=f"Allow workflow read via {rule_id}",
        target=Target(actions=["workflow.read"], resource_types=["device"]),
        condition=_condition({"op": "eq", "attr": "resource.type", "value": "device"}),
        effect=effect,
        obligations=[],
        priority=0,
    )


def _policy(
    policy_id: str,
    *,
    tenant_id: str | None = None,
    version: int = 1,
    set_by: ActorRef = SYS,
    set_at: datetime | None = None,
) -> Policy:
    return Policy(
        id=policy_id,
        version=version,
        name=f"Policy {policy_id}",
        description="P3 persistence policy",
        tenant_id=tenant_id,
        rules=[_rule()],
        standard="aqelyn/test",
        set_by=set_by,
        set_at=set_at or datetime.now(UTC),
    )


async def _postgres_store() -> PostgresPolicyStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresPolicyStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_policy RESTART IDENTITY")
    return store


async def _store(kind: str) -> AsyncIterator[PolicyStore]:
    if kind == "inmemory":
        yield InMemoryPolicyStore()
        return
    store = await _postgres_store()
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_policy_store_contract(kind: str) -> None:
    async for store in _store(kind):
        original = _policy("policy-contract")
        stored = await store.put(original)

        assert stored.model_dump(mode="json") == original.model_dump(mode="json")
        assert stored is not original

        loaded = await store.get(original.id)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == original.model_dump(mode="json")
        assert loaded is not stored

        loaded.rules[0].description = "mutated locally"
        reloaded = await store.get(original.id)
        assert reloaded is not None
        assert reloaded.model_dump(mode="json") == original.model_dump(mode="json")

        replacement = _policy("policy-contract", version=2)
        await store.put(replacement)
        latest = await store.get("policy-contract")
        assert latest is not None
        assert latest.version == 2
        assert latest.model_dump(mode="json") == replacement.model_dump(mode="json")

        assert await store.get("missing-policy") is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_policy_tenant_scoping(kind: str) -> None:
    async for store in _store(kind):
        global_policy = await store.put(_policy("policy-global"))
        tenant_a = await store.put(_policy("policy-a", tenant_id=TENANT_A))
        tenant_b = await store.put(_policy("policy-b", tenant_id=TENANT_B))

        rows_a = await store.list(tenant_id=TENANT_A)
        assert [policy.id for policy in rows_a] == [global_policy.id, tenant_a.id]
        assert tenant_b.id not in [policy.id for policy in rows_a]

        rows_global = await store.list()
        assert [policy.id for policy in rows_global] == [global_policy.id]

        with pytest.raises(SchemaValidationError):
            await store.list(tenant_id="not-a-uuid")


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_policy_provenance(kind: str) -> None:
    async for store in _store(kind):
        actor = ActorRef(actor_type="user", actor_id="policy-owner")
        set_at = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
        policy = await store.put(
            _policy("policy-provenance", version=3, set_by=actor, set_at=set_at)
        )

        loaded = await store.get(policy.id)

        assert loaded is not None
        assert loaded.version == 3
        assert loaded.set_by == actor
        assert loaded.set_at == set_at
        assert loaded.standard == "aqelyn/test"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_policy_store_revalidates_at_put(kind: str) -> None:
    async for store in _store(kind):
        invalid_rule = Rule.model_construct(
            id="invalid",
            kind="authorization",
            description="invalid rule bypassing constructors",
            target=Target(actions=["workflow.read"], resource_types=["device"]),
            condition=None,
            effect="require",
            obligations=[],
            priority=0,
        )
        invalid = Policy.model_construct(
            id="policy-invalid",
            version=1,
            name="Invalid policy",
            description="Bypasses construction-time validation",
            tenant_id=None,
            rules=[invalid_rule],
            standard=None,
            set_by=SYS,
            set_at=datetime.now(UTC),
        )

        with pytest.raises(PolicyConfigInvalid):
            await store.put(invalid)
