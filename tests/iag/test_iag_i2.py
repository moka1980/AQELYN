"""I2 acceptance tests for identity graph and access-risk analysis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.graph import EdgeView, ImpactResult, KnowledgeGraph, Path, Subgraph
from aqelyn.graph.models import NodeView
from aqelyn.iag import (
    ACCOUNT_OBJECT_TYPE,
    ENTITLEMENT_OBJECT_TYPE,
    GRANTS_ENTITLEMENT,
    HAS_ACCOUNT,
    HAS_ROLE,
    IDENTITY_OBJECT_TYPE,
    ROLE_OBJECT_TYPE,
    IAGConfig,
    IdentityAccessAnalyzer,
)
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    InMemoryObjectStore,
    ObjectQuery,
    ObjectStore,
    SourceRef,
)
from aqelyn.policy import Condition, Policy, PolicyEngine, Rule, Target

SYS = ActorRef(actor_type="system", actor_id="iag-i2-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"
_IAG_OBJECT_TYPES = (
    IDENTITY_OBJECT_TYPE,
    ACCOUNT_OBJECT_TYPE,
    ROLE_OBJECT_TYPE,
    ENTITLEMENT_OBJECT_TYPE,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "iag-i2-test") -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=_now(),
        method=method,
    )


def _obj(
    object_type: str,
    name: str,
    *,
    tenant_id: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> AQObject:
    now = _now()
    return AQObject(
        id="",
        object_type=object_type,
        schema_version=1,
        tenant_id=tenant_id,
        display_name=name,
        attributes=attrs or {},
        sources=[_source(f"object:{name}")],
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )


async def _add_obj(
    store: ObjectStore,
    object_type: str,
    name: str,
    *,
    tenant_id: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> AQObject:
    _register_iag_types(store)
    return await store.upsert(_obj(object_type, name, tenant_id=tenant_id, attrs=attrs))


async def _relate(
    store: ObjectStore,
    from_obj: AQObject,
    to_obj: AQObject,
    relation_type: str,
) -> AQRelationship:
    now = _now()
    return await store.relate(
        AQRelationship(
            id="",
            from_id=from_obj.id,
            to_id=to_obj.id,
            relation_type=relation_type,
            sources=[_source(relation_type)],
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


async def _access_graph(store: ObjectStore) -> tuple[AQObject, AQObject, AQObject, AQObject]:
    identity = await _add_obj(store, IDENTITY_OBJECT_TYPE, "Ada")
    account = await _add_obj(
        store,
        ACCOUNT_OBJECT_TYPE,
        "ada@example.test",
        attrs={"last_used_at": utc_now().isoformat()},
    )
    role = await _add_obj(store, ROLE_OBJECT_TYPE, "Engineering admin")
    entitlement = await _add_obj(store, ENTITLEMENT_OBJECT_TYPE, "prod-admin")
    await _relate(store, identity, account, HAS_ACCOUNT)
    await _relate(store, account, role, HAS_ROLE)
    await _relate(store, role, entitlement, GRANTS_ENTITLEMENT)
    return identity, account, role, entitlement


def _policy(entitlement_a_id: str, entitlement_b_id: str) -> Policy:
    return Policy(
        id="iag-sod",
        version=1,
        name="IAG SoD policy",
        description="Identity access must not hold conflicting entitlements.",
        tenant_id=None,
        rules=[
            Rule(
                id="no-conflict",
                kind="compliance",
                description="Identity must not hold entitlement-a and entitlement-b together.",
                target=Target(actions=None, resource_types=["identity_access"]),
                condition=Condition.model_validate(
                    {
                        "not": {
                            "all": [
                                {
                                    "op": "contains",
                                    "attr": "resource.attributes.entitlement_ids",
                                    "value": entitlement_a_id,
                                },
                                {
                                    "op": "contains",
                                    "attr": "resource.attributes.entitlement_ids",
                                    "value": entitlement_b_id,
                                },
                            ]
                        }
                    }
                ),
                effect="require",
            )
        ],
        standard="aqelyn/iag-test",
        set_by=SYS,
        set_at=_now(),
    )


def _register_iag_types(store: ObjectStore) -> None:
    registry = cast(Any, store).registry
    for object_type in _IAG_OBJECT_TYPES:
        registry.register(object_type, 1, None)


def _analyzer(
    store: ObjectStore,
    graph: KnowledgeGraph,
    *,
    policies: list[Policy] | None = None,
    config: IAGConfig | None = None,
    max_nodes: int = 10_000,
) -> IdentityAccessAnalyzer:
    return IdentityAccessAnalyzer(
        store,
        graph,
        PolicyEngine(policies or []),
        config=config,
        max_nodes=max_nodes,
    )


async def test_iag_access_paths(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    identity, account, _, entitlement = await _access_graph(store)
    analyzer = _analyzer(store, cast(KnowledgeGraph, graph_harness.graph))

    paths = await analyzer.access_paths(identity.id)

    assert len(paths) == 1
    assert paths[0].identity_id == identity.id
    assert paths[0].account_id == account.id
    assert paths[0].entitlement_ids == [entitlement.id]
    assert [edge.relation_type for edge in paths[0].via.edges] == [
        HAS_ACCOUNT,
        HAS_ROLE,
        GRANTS_ENTITLEMENT,
    ]
    assert paths[0].via.edges[0].sources[0].evidence_id is not None


async def test_iag_orphaned_dormant(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    old = utc_now() - timedelta(days=120)
    account = await _add_obj(
        store,
        ACCOUNT_OBJECT_TYPE,
        "orphaned-old",
        attrs={"last_used_at": old.isoformat()},
    )
    analyzer = _analyzer(
        store, cast(KnowledgeGraph, graph_harness.graph), config=IAGConfig(dormant_days=90)
    )

    report = await analyzer.analyze_risk(tenant_id=None)

    assert {risk.kind for risk in report.risks if risk.subject_id == account.id} == {
        "orphaned",
        "dormant",
    }


async def test_iag_over_privilege(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    identity, _, _, entitlement = await _access_graph(store)
    stored = await store.get(identity.id)
    assert stored is not None
    updated = stored.model_copy(update={"attributes": {"allowed_entitlement_ids": [new_id("obj")]}})
    await store.update(updated, expected_version=stored.version)
    analyzer = _analyzer(store, cast(KnowledgeGraph, graph_harness.graph))

    report = await analyzer.analyze_risk(tenant_id=None)

    risks = [risk for risk in report.risks if risk.kind == "over_privilege"]
    assert len(risks) == 1
    assert risks[0].subject_id == identity.id
    assert risks[0].detail["entitlement_id"] == entitlement.id
    assert risks[0].evidence_path is not None


async def test_iag_sod_conflict(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    identity = await _add_obj(store, IDENTITY_OBJECT_TYPE, "Sam")
    account = await _add_obj(
        store,
        ACCOUNT_OBJECT_TYPE,
        "sam@example.test",
        attrs={"last_used_at": utc_now().isoformat()},
    )
    role = await _add_obj(store, ROLE_OBJECT_TYPE, "Conflicting role")
    entitlement_a = await _add_obj(
        store,
        ENTITLEMENT_OBJECT_TYPE,
        "entitlement-a",
        attrs={"external_id": "entitlement-a"},
    )
    entitlement_b = await _add_obj(
        store,
        ENTITLEMENT_OBJECT_TYPE,
        "entitlement-b",
        attrs={"external_id": "entitlement-b"},
    )
    await _relate(store, identity, account, HAS_ACCOUNT)
    await _relate(store, account, role, HAS_ROLE)
    await _relate(store, role, entitlement_a, GRANTS_ENTITLEMENT)
    await _relate(store, role, entitlement_b, GRANTS_ENTITLEMENT)
    analyzer = _analyzer(
        store,
        cast(KnowledgeGraph, graph_harness.graph),
        policies=[_policy(entitlement_a.id, entitlement_b.id)],
    )

    report = await analyzer.analyze_risk(tenant_id=None)

    risks = [risk for risk in report.risks if risk.kind == "sod_conflict"]
    assert len(risks) == 1
    assert risks[0].detail["policy_id"] == "iag-sod"
    assert risks[0].detail["rule_id"] == "no-conflict"


async def test_iag_privileged_unreviewed(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    identity, _, role, _ = await _access_graph(store)
    analyzer = _analyzer(
        store,
        cast(KnowledgeGraph, graph_harness.graph),
        config=IAGConfig(privileged_roles=[role.display_name], review_default_due_days=30),
    )

    report = await analyzer.analyze_risk(tenant_id=None)

    risks = [risk for risk in report.risks if risk.kind == "privileged_unreviewed"]
    assert len(risks) == 1
    assert risks[0].subject_id == identity.id
    assert risks[0].detail["role_ids"] == [role.id]


async def test_iag_analyze_deterministic(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    await _access_graph(store)
    await _add_obj(store, ACCOUNT_OBJECT_TYPE, "missing-last-used")
    analyzer = _analyzer(store, cast(KnowledgeGraph, graph_harness.graph))

    first = await analyzer.analyze_risk(tenant_id=None)
    second = await analyzer.analyze_risk(tenant_id=None)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


async def test_iag_pages_full_scope(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    accounts = [
        await _add_obj(
            store,
            ACCOUNT_OBJECT_TYPE,
            f"dormant-{index}",
            attrs={"last_used_at": (utc_now() - timedelta(days=120)).isoformat()},
        )
        for index in range(3)
    ]
    analyzer = _analyzer(
        store,
        cast(KnowledgeGraph, _EmptyGraph()),
        config=IAGConfig(dormant_days=90),
    )

    report = await analyzer.analyze_risk(tenant_id=None, scope=ObjectQuery(limit=1))

    assert report.evaluated == 3
    assert {risk.subject_id for risk in report.risks if risk.kind == "dormant"} == {
        account.id for account in accounts
    }


async def test_iag_tenant_isolation() -> None:
    store = InMemoryObjectStore(mode="enterprise")
    tenant_a = await _add_obj(
        store,
        ACCOUNT_OBJECT_TYPE,
        "tenant-a",
        tenant_id=TENANT_A,
        attrs={"last_used_at": (utc_now() - timedelta(days=120)).isoformat()},
    )
    tenant_b = await _add_obj(
        store,
        ACCOUNT_OBJECT_TYPE,
        "tenant-b",
        tenant_id=TENANT_B,
        attrs={"last_used_at": (utc_now() - timedelta(days=120)).isoformat()},
    )
    analyzer = _analyzer(
        store, cast(KnowledgeGraph, _EmptyGraph()), config=IAGConfig(dormant_days=90)
    )

    report = await analyzer.analyze_risk(tenant_id=TENANT_A)

    assert {risk.subject_id for risk in report.risks} == {tenant_a.id}
    assert tenant_b.id not in {risk.subject_id for risk in report.risks}


async def test_iag_truncation_propagates() -> None:
    store = InMemoryObjectStore()
    identity = await _add_obj(store, IDENTITY_OBJECT_TYPE, "truncated")
    graph = _TruncatedGraph(identity.id)
    analyzer = _analyzer(store, cast(KnowledgeGraph, graph))

    report = await analyzer.analyze_risk(tenant_id=None)

    assert report.truncated is True


class _EmptyGraph:
    async def neighbors(
        self,
        node_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
    ) -> list[EdgeView]:
        return []

    async def subgraph(
        self,
        start_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        return Subgraph(nodes=[], edges=[], truncated=False)

    async def shortest_path(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
    ) -> Path | None:
        return None

    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
        max_work: int = 50_000,
    ) -> list[Path]:
        return []

    async def impact(
        self,
        node_id: str,
        *,
        direction: str = "in",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> ImpactResult:
        return ImpactResult()

    async def correlate(
        self,
        seed_ids: list[str] | tuple[str, ...],
        *,
        within_hops: int = 2,
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        return Subgraph()

    async def explain_path(self, path: Path) -> list[dict[str, object]]:
        return []


class _TruncatedGraph(_EmptyGraph):
    def __init__(self, identity_id: str) -> None:
        self._identity_id = identity_id

    async def subgraph(
        self,
        start_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        return Subgraph(
            nodes=[
                NodeView(
                    id=self._identity_id,
                    object_type=IDENTITY_OBJECT_TYPE,
                    display_name="truncated",
                )
            ],
            edges=[],
            truncated=True,
        )
