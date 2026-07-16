"""E2 acceptance tests for replayable derivations and decision stores."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    DerivationNotReplayable,
    ModelVersionNotFound,
    OptimisticConcurrencyConflict,
    TenantScopeRequired,
)
from aqelyn.decision import (
    ClaimRef,
    Derivation,
    DerivationStep,
    InMemoryModelVersionStore,
    InMemoryRecommendationStore,
    ModelVersion,
    ModelVersionStore,
    Recommendation,
    RecommendationStore,
    build_derivation,
    explain,
    replay,
    validate_replayable_recommendation,
)
from aqelyn.decision.postgres import PostgresModelVersionStore, PostgresRecommendationStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000201"
TENANT_B = "018f0000-0000-7000-8000-000000000202"
NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="decision-reviewer@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


def _claim(ref_id: str = "finding:alpha") -> ClaimRef:
    return ClaimRef(kind="finding", ref_id=ref_id, evidence_id=new_id("evd"))


def _derivation() -> Derivation:
    claim = _claim()
    step = DerivationStep(
        seq=1,
        op="select_claims",
        input_refs=[claim.ref_id],
        params={"kinds": ["finding"]},
        output={"claims": [claim.model_dump(mode="json")], "count": 1},
        note="Select the cited finding claim.",
    )
    return build_derivation(
        inputs=[claim],
        steps=[step],
        model_version=1,
        engine_version="0.2.0",
    )


def _recommendation(*, tenant_id: str | None = TENANT_A) -> Recommendation:
    return Recommendation(
        tenant_id=tenant_id,
        subject_ref="case:alpha",
        statement="Review finding alpha before taking action.",
        confidence=0.82,
        derivation=_derivation(),
        created_at=NOW,
    )


def _model(version: int, *, active: bool = False) -> ModelVersion:
    return ModelVersion(
        version=version,
        params={"threshold": 0.65 + (version / 100)},
        active=active,
        promoted_by=ACTOR if active else None,
        promoted_at=NOW if active else None,
        evidence_id=new_id("evd") if active else None,
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


async def _rec_store(kind: str, *, mode: str = "local") -> AsyncIterator[RecommendationStore]:
    if kind == "inmemory":
        yield InMemoryRecommendationStore(mode=mode)
        return
    store = await _postgres_rec_store(mode=mode)
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


async def _model_store(kind: str, *, mode: str = "local") -> AsyncIterator[ModelVersionStore]:
    if kind == "inmemory":
        yield InMemoryModelVersionStore(mode=mode)
        return
    store = await _postgres_model_store(mode=mode)
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


def test_dec_derivation_required() -> None:
    payload = {
        "tenant_id": TENANT_A,
        "subject_ref": "case:alpha",
        "statement": "This cannot exist without a derivation.",
        "confidence": 0.7,
        "created_at": NOW,
    }
    with pytest.raises(DerivationNotReplayable):
        Recommendation.model_validate(payload)

    raw = Recommendation.model_construct(
        id=new_id("rec"),
        tenant_id=TENANT_A,
        subject_ref="case:alpha",
        statement="Bypassed constructor.",
        confidence=0.7,
        derivation=_derivation(),
        advisory=True,
        created_at=NOW,
    )
    object.__setattr__(raw, "derivation", None)
    with pytest.raises(DerivationNotReplayable):
        validate_replayable_recommendation(raw)


def test_dec_replay_equals_result() -> None:
    recommendation = _recommendation()

    assert replay(recommendation.derivation) == recommendation.derivation.result
    assert validate_replayable_recommendation(recommendation) == recommendation


def test_dec_replay_mismatch_rejected() -> None:
    recommendation = _recommendation()
    tampered = recommendation.model_copy(
        update={
            "derivation": recommendation.derivation.model_copy(
                update={"result": {"claims": [], "count": 0}},
                deep=True,
            )
        },
        deep=True,
    )

    with pytest.raises(DerivationNotReplayable):
        replay(tampered.derivation)
    with pytest.raises(DerivationNotReplayable):
        validate_replayable_recommendation(tampered)


def test_dec_explanation_from_derivation() -> None:
    recommendation = _recommendation()

    rendered = explain(recommendation)

    assert rendered["statement"] == recommendation.statement
    assert rendered["result"] == recommendation.derivation.result
    assert rendered["steps"] == [
        {
            "seq": 1,
            "operation": "select_claims",
            "input_refs": ["finding:alpha"],
            "params": {"kinds": ["finding"]},
            "note": "Select the cited finding claim.",
            "output": recommendation.derivation.steps[0].output,
        }
    ]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_rec_contract(kind: str) -> None:
    async for store in _rec_store(kind, mode="enterprise"):
        stored = await store.put(_recommendation(tenant_id=TENANT_A))
        other = await store.put(_recommendation(tenant_id=TENANT_B))

        assert await store.get(stored.id, tenant_id=TENANT_A) == stored
        assert await store.get(stored.id, tenant_id=TENANT_B) is None
        assert [row.id for row in await store.query(tenant_id=TENANT_A)] == [stored.id]
        assert other.id not in [row.id for row in await store.query(tenant_id=TENANT_A)]

        with pytest.raises(TenantScopeRequired):
            await store.query(tenant_id=None)
        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(stored)

        tampered = _recommendation(tenant_id=TENANT_A).model_copy(
            update={
                "derivation": _derivation().model_copy(
                    update={"result": {"tampered": True}},
                    deep=True,
                )
            },
            deep=True,
        )
        with pytest.raises(DerivationNotReplayable):
            await store.put(tampered)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_dec_model_contract(kind: str) -> None:
    async for store in _model_store(kind, mode="enterprise"):
        with pytest.raises(TenantScopeRequired):
            await store.active(tenant_id=None)

        await store.put(_model(1, active=True), tenant_id=TENANT_A)
        await store.put(_model(2), tenant_id=TENANT_A)
        await store.put(_model(1, active=True), tenant_id=TENANT_B)

        assert (await store.active(tenant_id=TENANT_A)).version == 1
        promoted = await store.promote(
            2,
            by=ACTOR,
            reason="Human-approved threshold update.",
            tenant_id=TENANT_A,
            evidence_id=new_id("evd"),
        )
        assert promoted.active is True
        assert promoted.promoted_by == ACTOR
        assert (await store.active(tenant_id=TENANT_A)).version == 2
        assert (await store.active(tenant_id=TENANT_B)).version == 1

        assert await store.get(2, tenant_id=TENANT_A) == promoted
        assert await store.get(2, tenant_id=TENANT_B) is None
        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(_model(2), tenant_id=TENANT_A)
        with pytest.raises(ModelVersionNotFound):
            await store.promote(
                99,
                by=ACTOR,
                reason="Missing version.",
                tenant_id=TENANT_A,
                evidence_id=new_id("evd"),
            )
