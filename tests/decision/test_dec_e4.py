"""E4 acceptance tests for learning and explicit model promotion."""

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
    DecisionIntelligenceEngine,
    InMemoryModelVersionStore,
    InMemoryRecommendationStore,
    ModelVersion,
    ModelVersionStore,
    RecommendationStore,
)
from aqelyn.decision.postgres import PostgresModelVersionStore, PostgresRecommendationStore
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore
from aqelyn.trust import TrustAssessment

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000221"
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="decision-e4@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


class StaticClaimSource:
    def __init__(self, claims: Sequence[ClaimRef]) -> None:
        self.claims = list(claims)

    async def claims_for(self, *, subject_ref: str, tenant_id: str | None) -> Sequence[ClaimRef]:
        return list(self.claims)


class FixedTrust:
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment:
        return TrustAssessment(
            subject_ref=subject_ref,
            score=0.73,
            level="high",
            method="fixed_trust/v1",
            contributions=[],
            reason="fixed confidence from Trust test double.",
            no_evidence=False,
            computed_at=now or NOW,
        )


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


async def _evidence(store: EvidenceStore) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT_A,
            evidence_type="decision.input",
            schema_version=1,
            subject=Subject(),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=new_id("src"),
            method="decision-e4-test/v1",
            content={"claim": "alpha"},
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
        ),
        tenant_id=TENANT_A,
    )
    await store.promote(
        1,
        by=ACTOR,
        reason="Initial human-approved version.",
        evidence_id=new_id("evd"),
        tenant_id=TENANT_A,
    )


async def _engine(
    kind: str,
) -> AsyncIterator[tuple[DecisionIntelligenceEngine, ModelVersionStore]]:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    evidence = await _evidence(evidence_store)
    claim = ClaimRef(kind="finding", ref_id="finding:alpha", evidence_id=evidence.id)
    source = StaticClaimSource([claim])
    async for rec_store, model_store in _stores(kind):
        await _seed_active_model(model_store)
        yield (
            DecisionIntelligenceEngine(
                rec_store,
                model_store,
                claim_source=source,
                evidence_store=evidence_store,
                trust_engine=FixedTrust(),
                clock=lambda: NOW,
            ),
            model_store,
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_feedback_not_applied(kind: str) -> None:
    async for engine, model_store in _engine(kind):
        [recommendation] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)

        feedback = await engine.record_feedback(
            recommendation.id,
            feedback="Raise the review threshold for similar recommendations.",
            by=ACTOR,
        )
        proposed = await engine.propose_model_version(
            from_learning=[feedback.id],
            by=ACTOR,
            tenant_id=TENANT_A,
        )

        assert feedback.applied is False
        assert feedback.proposed_change["pinned_model_version"] == 1
        assert proposed.active is False
        assert proposed.promoted_by is None
        assert proposed.params["learning_refs"] == [feedback.id]
        assert proposed.params["derived_from_model_version"] == 1
        assert (await model_store.active(tenant_id=TENANT_A)).version == 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_promotion_explicit(kind: str) -> None:
    async for _, model_store in _engine(kind):
        with pytest.raises(DecisionConfigInvalid):
            await model_store.put(
                ModelVersion(
                    version=2,
                    params={"limit": 3},
                    active=True,
                    promoted_by=ACTOR,
                    promoted_at=NOW,
                    evidence_id=new_id("evd"),
                ),
                tenant_id=TENANT_A,
            )

        await model_store.put(ModelVersion(version=2, params={"limit": 3}), tenant_id=TENANT_A)
        with pytest.raises(DecisionConfigInvalid):
            await model_store.promote(
                2,
                by=cast(ActorRef, None),
                reason="Missing actor must not activate.",
                evidence_id=new_id("evd"),
                tenant_id=TENANT_A,
            )
        with pytest.raises(DecisionConfigInvalid):
            await model_store.promote(
                2,
                by=ACTOR,
                reason="Missing evidence must not activate.",
                evidence_id="",
                tenant_id=TENANT_A,
            )

        promoted = await model_store.promote(
            2,
            by=ACTOR,
            reason="Human-approved promotion.",
            evidence_id=new_id("evd"),
            tenant_id=TENANT_A,
        )

        assert promoted.active is True
        assert promoted.promoted_by == ACTOR
        assert promoted.evidence_id is not None
        assert (await model_store.active(tenant_id=TENANT_A)).version == 2


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_pinned_version_replay(kind: str) -> None:
    async for engine, model_store in _engine(kind):
        [old] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)
        feedback = await engine.record_feedback(
            old.id,
            feedback="Try a narrower future version.",
            by=ACTOR,
        )
        proposed = await engine.propose_model_version(
            from_learning=[feedback.id],
            by=ACTOR,
            tenant_id=TENANT_A,
        )
        await engine.promote(
            proposed.version,
            by=ACTOR,
            reason="Human-approved promotion.",
            evidence_id=new_id("evd"),
            tenant_id=TENANT_A,
        )
        [new] = await engine.recommend(subject_ref="case:alpha", tenant_id=TENANT_A)

        assert old.derivation.model_version == 1
        assert new.derivation.model_version == 2
        assert (await model_store.active(tenant_id=TENANT_A)).version == 2
        assert await engine.replay(old) == old.derivation.result
