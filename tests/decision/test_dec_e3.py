"""E3 acceptance tests for advisory recommendations and similarity."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import DecisionConfigInvalid
from aqelyn.decision import (
    ClaimRef,
    DecisionConfig,
    DecisionIntelligenceEngine,
    InMemoryModelVersionStore,
    InMemoryRecommendationStore,
    ModelVersion,
    ModelVersionStore,
    RecommendationStore,
    similar_cases,
)
from aqelyn.decision.postgres import PostgresModelVersionStore, PostgresRecommendationStore
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore
from aqelyn.trust import TrustAssessment
from aqelyn.workflow import Playbook, Run

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000211"
NOW = datetime(2026, 7, 16, 11, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="decision-e3@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


class StaticClaimSource:
    def __init__(self, claims: Sequence[ClaimRef]) -> None:
        self.claims = list(claims)
        self.calls: list[tuple[str, str | None]] = []

    async def claims_for(self, *, subject_ref: str, tenant_id: str | None) -> Sequence[ClaimRef]:
        self.calls.append((subject_ref, tenant_id))
        return list(self.claims)


class SpyTrust:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls: list[tuple[str, list[str], datetime | None]] = []

    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment:
        self.calls.append((subject_ref, [record.id for record in evidence], now))
        return TrustAssessment(
            subject_ref=subject_ref,
            score=self.score,
            level="high",
            method="spy_trust/v1",
            contributions=[],
            reason="confidence supplied by EA-0006 Trust test double.",
            no_evidence=False,
            computed_at=now or NOW,
        )


class SpyWorkflow:
    def __init__(self) -> None:
        self.proposed: list[Playbook] = []
        self.executed = 0

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: object | None = None,
    ) -> Run:
        self.proposed.append(playbook)
        return Run(
            id=new_id("run"),
            playbook_id=playbook.id,
            playbook_version=playbook.version,
            tenant_id=playbook.tenant_id,
            status="proposed",
            source_finding_id=None,
            created_by=by,
            created_at=NOW,
            updated_at=NOW,
            version=1,
        )

    async def execute(self, run_id: str) -> None:
        self.executed += 1


async def _postgres_rec_store(*, mode: str = "local") -> PostgresRecommendationStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRecommendationStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_decision_recommendation RESTART IDENTITY")
    return store


async def _postgres_model_store(*, mode: str = "local") -> PostgresModelVersionStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresModelVersionStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_decision_model_version RESTART IDENTITY")
    return store


async def _stores(
    kind: str,
) -> AsyncIterator[tuple[RecommendationStore, ModelVersionStore]]:
    if kind == "inmemory":
        yield (
            InMemoryRecommendationStore(mode="enterprise"),
            InMemoryModelVersionStore(mode="enterprise"),
        )
        return
    rec_store = await _postgres_rec_store(mode="enterprise")
    model_store = await _postgres_model_store(mode="enterprise")
    try:
        yield rec_store, model_store
    finally:
        await cast(_Closable, rec_store).close()
        await cast(_Closable, model_store).close()


async def _evidence(
    store: EvidenceStore,
    *,
    tenant_id: str | None = TENANT_A,
    content: dict[str, object] | None = None,
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="decision.input",
            schema_version=1,
            subject=Subject(),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=new_id("src"),
            method="decision-test/v1",
            content=content or {"claim": "alpha"},
            content_hash="",
            confidence=0.9,
            labels={"module": "EA-0020", "kind": "test_input"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


async def _seed_active_model(store: ModelVersionStore) -> None:
    await store.put(
        ModelVersion(
            version=1,
            params={"limit": 5, "mission_factor": 1.0, "min_confidence": 0.0},
            active=True,
            promoted_by=ACTOR,
            promoted_at=NOW,
            evidence_id=new_id("evd"),
        ),
        tenant_id=TENANT_A,
    )


async def _engine(
    kind: str,
    *,
    trust_score: float = 0.77,
    config: DecisionConfig | None = None,
    workflow: SpyWorkflow | None = None,
    claims: Sequence[ClaimRef] | None = None,
    evidence_store: InMemoryEvidenceStore | None = None,
) -> AsyncIterator[tuple[DecisionIntelligenceEngine, SpyTrust, StaticClaimSource, EvidenceStore]]:
    evidence = evidence_store or InMemoryEvidenceStore(mode="enterprise")
    if claims is None:
        record = await _evidence(evidence)
        claims = [ClaimRef(kind="finding", ref_id="finding:alpha", evidence_id=record.id)]
    source = StaticClaimSource(claims)
    trust = SpyTrust(trust_score)
    async for rec_store, model_store in _stores(kind):
        await _seed_active_model(model_store)
        yield (
            DecisionIntelligenceEngine(
                rec_store,
                model_store,
                claim_source=source,
                evidence_store=evidence,
                trust_engine=trust,
                workflow_engine=workflow,
                config=config,
                clock=lambda: NOW,
            ),
            trust,
            source,
            evidence,
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_inputs_are_claims(kind: str) -> None:
    async for engine, _, source, _ in _engine(kind):
        [recommendation] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)

        assert source.calls == [("case:alpha", TENANT_A)]
        assert [claim.ref_id for claim in recommendation.derivation.inputs] == ["finding:alpha"]
        assert all(isinstance(claim, ClaimRef) for claim in recommendation.derivation.inputs)
        assert recommendation.derivation.inputs[0].evidence_id is not None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_advisory_only(kind: str) -> None:
    evidence = InMemoryEvidenceStore(mode="enterprise")
    async for engine, _, _, store in _engine(kind, evidence_store=evidence):
        before = len(cast(InMemoryEvidenceStore, store)._by_id)
        [recommendation] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)

        assert recommendation.advisory is True
        assert recommendation.id.startswith("rec_")
        assert len(cast(InMemoryEvidenceStore, store)._by_id) == before
        assert recommendation.derivation.result["count"] == 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_decision_proposes(kind: str) -> None:
    workflow = SpyWorkflow()
    async for engine, _, _, evidence in _engine(kind, workflow=workflow):
        [recommendation] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)
        before = len(cast(InMemoryEvidenceStore, evidence)._by_id)

        record = await engine.record_decision(
            recommendation.id,
            decision="accepted",
            by=ACTOR,
            reason="Analyst accepted the advisory recommendation.",
            propose_run=True,
        )

        assert record.workflow_run_id is not None
        assert record.evidence_id.startswith("evd_")
        assert [playbook.steps[0].action_type for playbook in workflow.proposed] == [
            "decision.review"
        ]
        assert workflow.executed == 0
        assert len(cast(InMemoryEvidenceStore, evidence)._by_id) == before + 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_confidence_from_trust(kind: str) -> None:
    async for engine, trust, _, _ in _engine(kind, trust_score=0.64):
        [recommendation] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)

        assert recommendation.confidence == pytest.approx(0.64)
        assert recommendation.derivation.steps[1].op == "weigh"
        assert recommendation.derivation.steps[1].params["default"] == pytest.approx(0.64)
        assert trust.calls[0][0] == "case:alpha"
        assert trust.calls[0][1] == [recommendation.derivation.inputs[0].evidence_id]


def test_dec_similarity_explicit() -> None:
    hits = similar_cases(
        "case-a",
        {
            "case-a": {
                "signal_kinds": ["finding", "risk"],
                "assets": ["obj_a", "obj_b"],
                "techniques": ["T1003"],
            },
            "case-b": {
                "signal_kinds": ["finding"],
                "assets": ["obj_a"],
                "techniques": ["T1003", "T1059"],
            },
            "case-c": {"signal_kinds": ["case"], "assets": ["obj_z"], "techniques": []},
        },
        limit=2,
    )

    assert [hit.case_id for hit in hits] == ["case-b", "case-c"]
    assert hits[0].shared == {
        "assets": ["obj_a"],
        "signal_kinds": ["finding"],
        "techniques": ["T1003"],
    }
    assert hits[0].score == pytest.approx(3 / 6)
    assert "shares 3 of 6 explicit features" in hits[0].reason


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_bounds_and_scope(kind: str) -> None:
    evidence = InMemoryEvidenceStore(mode="enterprise")
    records = [await _evidence(evidence, content={"claim": str(idx)}) for idx in range(3)]
    claims = [
        ClaimRef(kind="finding", ref_id=f"finding:{idx}", evidence_id=record.id)
        for idx, record in enumerate(records)
    ]
    async for engine, _, source, _ in _engine(
        kind,
        config=DecisionConfig(batch_size=2),
        claims=claims,
        evidence_store=evidence,
    ):
        [recommendation] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)
        assert source.calls == [("case:alpha", TENANT_A)]
        assert [claim.ref_id for claim in recommendation.derivation.inputs] == [
            "finding:0",
            "finding:1",
        ]

    async for engine, _, _, _ in _engine(
        kind,
        config=DecisionConfig(max_steps=4),
        evidence_store=InMemoryEvidenceStore(mode="enterprise"),
    ):
        with pytest.raises(DecisionConfigInvalid):
            await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)
