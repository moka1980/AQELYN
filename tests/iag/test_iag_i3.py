"""I3 acceptance tests for IAG certification campaigns and stores."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import OptimisticConcurrencyConflict
from aqelyn.evidence import EvidenceStore, InMemoryEvidenceStore
from aqelyn.graph import KnowledgeGraph
from aqelyn.iag import (
    ACCOUNT_OBJECT_TYPE,
    ENTITLEMENT_OBJECT_TYPE,
    GRANTS_ENTITLEMENT,
    HAS_ACCOUNT,
    HAS_ROLE,
    IDENTITY_OBJECT_TYPE,
    ROLE_OBJECT_TYPE,
    IdentityAccessGovernanceEngine,
    InMemoryCertificationStore,
    PostgresCertificationStore,
)
from aqelyn.iag.models import Certification, ReviewItem
from aqelyn.iag.store import CertificationStore
from aqelyn.objects import AQObject, AQRelationship, ObjectQuery, ObjectStore, SourceRef
from aqelyn.policy import PolicyEngine

SYS = ActorRef(actor_type="system", actor_id="iag-i3-test")
PG_URL = os.getenv("AQELYN_DATABASE_URL")
_IAG_OBJECT_TYPES = (
    IDENTITY_OBJECT_TYPE,
    ACCOUNT_OBJECT_TYPE,
    ROLE_OBJECT_TYPE,
    ENTITLEMENT_OBJECT_TYPE,
)


@dataclass
class CertHarness:
    kind: str
    store: CertificationStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def cert_harness(request: pytest.FixtureRequest) -> AsyncIterator[CertHarness]:
    if request.param == "inmemory":
        yield CertHarness(kind="inmemory", store=InMemoryCertificationStore())
        return
    if PG_URL is None:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresCertificationStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_iag_certification")
    try:
        yield CertHarness(kind="postgres", store=store)
    finally:
        await store.close()


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "iag-i3-test") -> SourceRef:
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
    attrs: dict[str, Any] | None = None,
) -> AQObject:
    now = _now()
    return AQObject(
        id="",
        object_type=object_type,
        schema_version=1,
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
    attrs: dict[str, Any] | None = None,
) -> AQObject:
    _register_iag_types(store)
    return await store.upsert(_obj(object_type, name, attrs=attrs))


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
    role = await _add_obj(store, ROLE_OBJECT_TYPE, "Engineering")
    entitlement = await _add_obj(store, ENTITLEMENT_OBJECT_TYPE, "deploy-prod")
    await _relate(store, identity, account, HAS_ACCOUNT)
    await _relate(store, account, role, HAS_ROLE)
    await _relate(store, role, entitlement, GRANTS_ENTITLEMENT)
    return identity, account, role, entitlement


def _register_iag_types(store: ObjectStore) -> None:
    registry = cast(Any, store).registry
    for object_type in _IAG_OBJECT_TYPES:
        registry.register(object_type, 1, None)


def _engine(
    object_store: ObjectStore,
    graph: KnowledgeGraph,
    *,
    cert_store: CertificationStore | None = None,
    evidence_store: EvidenceStore | None = None,
) -> IdentityAccessGovernanceEngine:
    return IdentityAccessGovernanceEngine(
        object_store,
        graph,
        PolicyEngine([]),
        cert_store or InMemoryCertificationStore(),
        evidence_store or InMemoryEvidenceStore(),
    )


def _cert(name: str = "Quarterly access review") -> Certification:
    return Certification(
        id="",
        name=name,
        scope={"object_type": IDENTITY_OBJECT_TYPE},
        status="open",
        items=[
            ReviewItem(
                id="",
                identity_id=new_id("obj"),
                account_id=new_id("obj"),
                entitlement_id=new_id("obj"),
                current_state={"granted": True},
                recommendation="Review access.",
            )
        ],
        created_by=SYS,
        created_at=_now(),
        due_at=_now() + timedelta(days=14),
    )


async def test_iag_open_certification(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    identity, account, _, entitlement = await _access_graph(store)
    cert_store = InMemoryCertificationStore()
    engine = _engine(store, cast(KnowledgeGraph, graph_harness.graph), cert_store=cert_store)

    cert = await engine.open_certification(
        tenant_id=None,
        name="Q3 access review",
        scope=ObjectQuery(limit=100),
        by=SYS,
        due_days=7,
    )

    assert cert.id.startswith("cert_")
    assert cert.name == "Q3 access review"
    assert cert.status == "open"
    assert cert.version == 1
    assert cert.due_at is not None
    assert cert.due_at > cert.created_at
    assert len(cert.items) == 1
    item = cert.items[0]
    assert item.id.startswith("rvi_")
    assert item.identity_id == identity.id
    assert item.account_id == account.id
    assert item.entitlement_id == entitlement.id
    assert item.decision == "pending"
    assert "access_path" in item.current_state
    assert "Approve" in item.recommendation
    assert await cert_store.get(cert.id) == cert


async def test_iag_decide_item_evidence(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    await _access_graph(store)
    cert_store = InMemoryCertificationStore()
    evidence_store = InMemoryEvidenceStore()
    engine = _engine(
        store,
        cast(KnowledgeGraph, graph_harness.graph),
        cert_store=cert_store,
        evidence_store=evidence_store,
    )
    cert = await engine.open_certification(
        tenant_id=None,
        name="Q3 access review",
        scope=ObjectQuery(limit=100),
        by=SYS,
    )
    item = cert.items[0]

    updated = await engine.decide_item(
        cert.id,
        item.id,
        decision="revoked",
        by=SYS,
        note="No longer required.",
        expected_version=cert.version,
    )

    assert updated.version == cert.version + 1
    assert updated.status == "in_progress"
    decided = updated.items[0]
    assert decided.decision == "revoked"
    assert decided.decided_by == SYS
    assert decided.evidence_id is not None
    assert decided.note == "No longer required."
    evidence = await evidence_store.get(decided.evidence_id, actor=SYS)
    assert evidence.evidence_type == "iag.certification_decision"
    assert evidence.content is not None
    assert evidence.content["certification_id"] == cert.id
    assert evidence.content["review_item_id"] == item.id
    assert evidence.content["decision"] == "revoked"
    assert (await evidence_store.verify(evidence.id)).ok is True


async def test_iag_cert_contract(cert_harness: CertHarness) -> None:
    store = cert_harness.store
    created = await store.put(_cert())

    assert created.id.startswith("cert_")
    assert created.items[0].id.startswith("rvi_")
    assert created.version == 1
    assert await store.get(created.id) == created
    assert [cert.id for cert in await store.list(tenant_id=None)] == [created.id]
    assert [cert.id for cert in await store.list(tenant_id=None, status=["open"])] == [created.id]
    assert await store.list(tenant_id=None, status=["completed"]) == []

    updated = created.model_copy(update={"status": "in_progress"}, deep=True)
    saved = await store.put(updated, expected_version=created.version)
    assert saved.version == 2
    assert saved.status == "in_progress"

    with pytest.raises(OptimisticConcurrencyConflict):
        await store.put(created, expected_version=created.version)
