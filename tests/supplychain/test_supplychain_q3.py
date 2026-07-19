"""C-027 Q3 acceptance tests for dependency traversal and honest reachability."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import SupplyChainConfigInvalid
from aqelyn.graph import EdgeView, ImpactHit, ImpactResult, KnowledgeGraph, NodeView, Path
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.objects import InMemoryObjectStore
from aqelyn.supplychain import (
    InMemorySBOMStore,
    ReachabilitySignal,
    SBOMDocument,
    SupplyChainConfig,
    SupplyChainEngine,
    path_ref,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry

NOW = datetime(2026, 7, 19, 22, 0, tzinfo=UTC)
PURL_APP = "pkg:pypi/payments@1.0.0"
PURL_MIDDLE = "pkg:pypi/framework@2.0.0"
PURL_TARGET = "pkg:pypi/parser@3.0.0"
PURL_ISOLATED = "pkg:pypi/unused@4.0.0"


class _ImpactSpy:
    def __init__(self, result: ImpactResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def impact(
        self,
        node_id: str,
        *,
        direction: str = "in",
        relation_types: tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> ImpactResult:
        self.calls.append(
            {
                "node_id": node_id,
                "direction": direction,
                "relation_types": relation_types,
                "max_depth": max_depth,
                "max_nodes": max_nodes,
            }
        )
        return self.result.model_copy(deep=True)


def _document() -> SBOMDocument:
    return SBOMDocument(
        format="cyclonedx",
        subject_ref="artifact:payments:1.0.0",
        raw={
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"bom-ref": "external-root"}},
            "components": [
                _component("app", "payments", "1.0.0", PURL_APP, "application"),
                _component("middle", "framework", "2.0.0", PURL_MIDDLE),
                _component("target", "parser", "3.0.0", PURL_TARGET),
                _component("isolated", "unused", "4.0.0", PURL_ISOLATED),
            ],
            "dependencies": [
                {"ref": "external-root", "dependsOn": ["app"]},
                {"ref": "app", "dependsOn": ["middle"]},
                {"ref": "middle", "dependsOn": ["target"]},
                {"ref": "target", "dependsOn": []},
                {"ref": "isolated", "dependsOn": []},
            ],
        },
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


def _component(
    ref: str,
    name: str,
    version: str,
    purl: str,
    component_type: str = "library",
) -> dict[str, object]:
    return {
        "bom-ref": ref,
        "type": component_type,
        "name": name,
        "version": version,
        "purl": purl,
        "licenses": [{"license": {"id": "Apache-2.0"}}],
    }


def _engine(
    *,
    store: InMemorySBOMStore,
    object_store: Any,
    graph: KnowledgeGraph,
    max_depth: int,
) -> SupplyChainEngine:
    return SupplyChainEngine(
        store,
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore()),
        source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
        object_store=object_store,
        graph=graph,
        config=SupplyChainConfig(max_depth=max_depth, batch_size=100),
    )


async def test_sc_dependency_graph(graph_harness: Any) -> None:
    store = InMemorySBOMStore()
    engine = _engine(
        store=store,
        object_store=graph_harness.object_store,
        graph=graph_harness.graph,
        max_depth=6,
    )

    components = await engine.ingest_sbom(_document(), tenant_id=None)
    by_purl = {component.purl: component for component in components}
    app_edges = await graph_harness.object_store.relationships(
        by_purl[PURL_APP].object_id,
        direction="out",
        relation_type="depends_on",
    )
    middle_edges = await graph_harness.object_store.relationships(
        by_purl[PURL_MIDDLE].object_id,
        direction="out",
        relation_type="depends_on",
    )

    assert [(edge.to_id, edge.attributes["scope"]) for edge in app_edges] == [
        (by_purl[PURL_MIDDLE].object_id, "runtime")
    ]
    assert [(edge.to_id, edge.attributes["scope"]) for edge in middle_edges] == [
        (by_purl[PURL_TARGET].object_id, "runtime")
    ]

    down = await engine.dependency_paths(PURL_APP, direction="down", tenant_id=None)
    assert down.truncated is False
    assert {path.length for path in down.paths} == {1, 2}
    assert any(
        path.node_ids
        == [
            by_purl[PURL_APP].object_id,
            by_purl[PURL_MIDDLE].object_id,
            by_purl[PURL_TARGET].object_id,
        ]
        for path in down.paths
    )

    target = by_purl[PURL_TARGET]
    fake_path = Path(
        node_ids=[target.object_id, by_purl[PURL_MIDDLE].object_id],
        edges=[
            EdgeView(
                id=middle_edges[0].id,
                from_id=by_purl[PURL_MIDDLE].object_id,
                to_id=target.object_id,
                relation_type="depends_on",
            )
        ],
        length=1,
    )
    spy = _ImpactSpy(
        ImpactResult(
            hits=[
                ImpactHit(
                    node=NodeView(
                        id=by_purl[PURL_MIDDLE].object_id,
                        object_type="software_component",
                        display_name="framework@2.0.0",
                    ),
                    via=fake_path,
                )
            ],
            truncated=True,
        )
    )
    spy_engine = _engine(
        store=store,
        object_store=InMemoryObjectStore(),
        graph=cast(KnowledgeGraph, spy),
        max_depth=4,
    )
    delegated = await spy_engine.dependency_paths(PURL_TARGET, direction="up", tenant_id=None)

    assert delegated.paths == [fake_path]
    assert delegated.truncated is True
    assert spy.calls == [
        {
            "node_id": target.object_id,
            "direction": "in",
            "relation_types": ("depends_on",),
            "max_depth": 4,
            "max_nodes": 100,
        }
    ]


async def test_sc_reachability_unknown_not_safe(graph_harness: Any) -> None:
    store = InMemorySBOMStore()
    bounded = _engine(
        store=store,
        object_store=graph_harness.object_store,
        graph=graph_harness.graph,
        max_depth=1,
    )
    components = await bounded.ingest_sbom(_document(), tenant_id=None)
    by_purl = {component.purl: component for component in components}

    truncated = await bounded.dependency_paths(PURL_TARGET, direction="up", tenant_id=None)
    unknown = await bounded.reachability(PURL_TARGET, "CVE-2026-0001", tenant_id=None)

    assert truncated.truncated is True
    assert unknown.reachable == "unknown"
    assert unknown.depth is None
    assert unknown.path is None
    assert "truncated" in unknown.reason

    complete = _engine(
        store=store,
        object_store=graph_harness.object_store,
        graph=graph_harness.graph,
        max_depth=4,
    )
    transitive = await complete.reachability(PURL_TARGET, "CVE-2026-0001", tenant_id=None)
    direct = await complete.reachability(PURL_APP, "CVE-2026-0002", tenant_id=None)
    unreachable = await complete.reachability(
        PURL_ISOLATED,
        "CVE-2026-0003",
        tenant_id=None,
    )
    missing = await complete.reachability(
        "pkg:pypi/not-cataloged@1.0.0",
        "CVE-2026-0004",
        tenant_id=None,
    )

    assert transitive.reachable == "transitive"
    assert transitive.depth == 2
    assert transitive.path is not None
    assert transitive.path.node_ids == [
        by_purl[PURL_APP].object_id,
        by_purl[PURL_MIDDLE].object_id,
        by_purl[PURL_TARGET].object_id,
    ]
    assert transitive.path_ref == path_ref(transitive.path)
    assert direct.reachable == "direct"
    assert direct.depth == 0
    assert unreachable.reachable == "unreachable"
    assert missing.reachable == "unknown"

    assert transitive.path is not None
    with pytest.raises(SupplyChainConfigInvalid, match="content-address"):
        ReachabilitySignal(
            component_purl=transitive.component_purl,
            cve_id=transitive.cve_id,
            reachable="transitive",
            depth=transitive.depth,
            path_ref="sha256:" + "0" * 64,
            path=transitive.path,
            reason=transitive.reason,
        )
