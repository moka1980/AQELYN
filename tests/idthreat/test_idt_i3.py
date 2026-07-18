"""I3 acceptance tests for gate-first, replayable identity detections."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    IdentityCorroborationMissing,
    IdentityNotReplayable,
    IdThreatConfigInvalid,
    OptimisticConcurrencyConflict,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.idthreat import (
    IdentityDetection,
    IdentityDetectionStore,
    IdentityObservation,
    IdentityThreatEngine,
    IdThreatConfig,
    InMemoryIdentityDetectionStore,
    PostgresIdentityDetectionStore,
    SignalRef,
    dignity_gate,
    validate_replayable_detection,
)
from aqelyn.trust import TrustAssessment

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000270301"
OTHER_TENANT = "018f0000-0000-7000-8000-000000270302"


class _Closable(Protocol):
    async def close(self) -> None: ...


class _EvidenceLookup:
    def __init__(self, records: Sequence[EvidenceRecord]) -> None:
        self.records = {record.id: record for record in records}
        self.calls: list[str] = []

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        assert actor.actor_id == "idthreat-engine"
        self.calls.append(evidence_id)
        return self.records[evidence_id].model_copy(deep=True)


class _TrustSpy:
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
            method="noisy_or/v1",
            contributions=[],
            reason="EA-0006 test assessment.",
            no_evidence=False,
            computed_at=now or NOW,
        )


def _config() -> IdThreatConfig:
    return IdThreatConfig(
        min_corroboration=2,
        min_confidence=0.75,
        platform_default=0.5,
    )


async def _store(kind: str) -> AsyncIterator[IdentityDetectionStore]:
    if kind == "inmemory":
        yield InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresIdentityDetectionStore.connect(
        PG_URL,
        config=_config(),
        mode="enterprise",
    )
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_identity_detection")
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


def _evidence(*, evidence_id: str | None = None, tenant_id: str | None = TENANT) -> EvidenceRecord:
    selected_id = evidence_id or new_id("evd")
    return EvidenceRecord(
        id=selected_id,
        tenant_id=tenant_id,
        evidence_type="identity.authentication",
        schema_version=1,
        subject=Subject(),
        collected_at=NOW,
        recorded_at=NOW,
        collector=ActorRef(actor_type="system", actor_id="identity-collector"),
        source_id=new_id("src"),
        method="identity-observation/v1",
        content={"event": selected_id},
        content_hash="content-hash",
        confidence=1.0,
        seq=1,
        prev_hash=None,
        record_hash="record-hash",
    )


def _signal(
    kind: str,
    ref: str,
    *,
    evidence_id: str | None,
    offset: int = 0,
) -> SignalRef:
    return SignalRef(
        kind=kind,
        ref=ref,
        as_of=NOW + timedelta(minutes=offset),
        evidence_id=evidence_id,
    )


def _observation(
    evidence: Sequence[EvidenceRecord],
    *,
    subject_ref: str = "acct:alice",
    detection_type: str = "impossible_travel",
) -> IdentityObservation:
    return IdentityObservation(
        subject_ref=subject_ref,
        detection_type=detection_type,
        signals=[
            _signal("authentication", f"auth:{subject_ref}:oslo", evidence_id=evidence[0].id),
            _signal(
                "session",
                f"session:{subject_ref}:sao-paulo",
                evidence_id=evidence[1].id,
                offset=1,
            ),
        ],
        profile_ref=new_id("prf"),
        profile_version=3,
        rule_ref="impossible-travel-rule",
        rule_version=7,
        detected_at=NOW + timedelta(minutes=2),
    )


async def _detect(
    store: IdentityDetectionStore,
    *,
    tenant_id: str = TENANT,
    score: float = 0.91,
    subject_ref: str = "acct:alice",
) -> tuple[IdentityDetection, _TrustSpy, _EvidenceLookup]:
    records = [_evidence(tenant_id=tenant_id), _evidence(tenant_id=tenant_id)]
    evidence = _EvidenceLookup(records)
    trust = _TrustSpy(score)
    engine = IdentityThreatEngine(
        store,
        evidence_store=evidence,
        trust_engine=trust,
        config=_config(),
    )
    detection = await engine.detect(
        observation=_observation(records, subject_ref=subject_ref),
        tenant_id=tenant_id,
    )
    assert detection is not None
    return detection, trust, evidence


async def test_idt_corroboration_required() -> None:
    record = _evidence()
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    trust = _TrustSpy(0.99)
    engine = IdentityThreatEngine(
        store,
        evidence_store=_EvidenceLookup([record]),
        trust_engine=trust,
        config=_config(),
    )
    observation = _observation([record, record]).model_copy(
        update={"signals": [_signal("authentication", "auth:only", evidence_id=record.id)]},
        deep=True,
    )

    assert await engine.detect(observation=observation, tenant_id=TENANT) is None
    assert await store.query(tenant_id=TENANT) == []

    valid_records = [_evidence(), _evidence()]
    low_confidence_engine = IdentityThreatEngine(
        store,
        evidence_store=_EvidenceLookup(valid_records),
        trust_engine=_TrustSpy(0.75),
        config=_config(),
    )
    assert (
        await low_confidence_engine.detect(
            observation=_observation(valid_records),
            tenant_id=TENANT,
        )
        is None
    )
    assert await store.query(tenant_id=TENANT) == []

    accepted, _accepted_trust, _accepted_evidence = await _detect(store)
    laundered = accepted.model_copy(
        update={"id": new_id("idt"), "confidence": 0.1},
        deep=True,
    )
    with pytest.raises(IdThreatConfigInvalid):
        await store.put(laundered)


def test_idt_corroboration_independence_key() -> None:
    config = _config()
    first_evidence = new_id("evd")
    other_evidence = new_id("evd")
    same_ref = [
        _signal("authentication", "event:42", evidence_id=first_evidence),
        _signal("session", "event:42", evidence_id=other_evidence),
    ]
    same_evidence = [
        _signal("authentication", "event:42", evidence_id=first_evidence),
        _signal("session", "event:43", evidence_id=first_evidence),
    ]
    independent = [
        _signal("authentication", "event:42", evidence_id=first_evidence),
        _signal("session", "event:43", evidence_id=other_evidence),
    ]

    assert dignity_gate(same_ref, 0.9, config) is False
    assert dignity_gate(same_evidence, 0.9, config) is False
    assert dignity_gate(independent, 0.9, config) is True
    with pytest.raises(IdentityCorroborationMissing):
        IdentityDetection.model_validate(
            {
                **_minimal_detection_data(independent),
                "corroboration": [item.model_dump(mode="json") for item in same_ref],
            }
        )


async def test_idt_detection_replayable() -> None:
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    detection, _trust, _evidence_lookup = await _detect(store)

    validated = validate_replayable_detection(detection)

    assert validated == detection
    assert detection.derivation.model_version == 7
    assert detection.derivation.steps[-1].params["profile_version"] == 3
    assert detection.derivation.steps[-1].params["rule_version"] == 7


async def test_idt_replay_mismatch() -> None:
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    detection, _trust, _evidence_lookup = await _detect(store)
    step = detection.derivation.steps[0].model_copy(
        update={"output": {**detection.derivation.steps[0].output, "confidence": 0.01}},
        deep=True,
    )
    tampered = detection.model_copy(
        update={
            "id": new_id("idt"),
            "derivation": detection.derivation.model_copy(update={"steps": [step]}, deep=True),
        },
        deep=True,
    )

    with pytest.raises(IdentityNotReplayable):
        validate_replayable_detection(tampered)
    with pytest.raises(IdentityNotReplayable):
        await store.put(tampered)


async def test_idt_confidence_from_trust() -> None:
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    detection, trust, evidence = await _detect(store, score=0.83)

    assert detection.confidence == 0.83
    assert trust.calls == [
        (
            "acct:alice",
            sorted(evidence.records),
            NOW + timedelta(minutes=2),
        )
    ]
    assert evidence.calls == sorted(evidence.records)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_idt_store_contract(kind: str) -> None:
    async for store in _store(kind):
        first, _trust, _lookup = await _detect(store)
        other, _other_trust, _other_lookup = await _detect(
            store,
            tenant_id=OTHER_TENANT,
            subject_ref="acct:bob",
        )

        assert await store.get(first.id, tenant_id=TENANT) == first
        assert await store.get(first.id, tenant_id=OTHER_TENANT) is None
        assert [row.id for row in await store.query(tenant_id=TENANT)] == [first.id]
        assert [row.id for row in await store.query(tenant_id=OTHER_TENANT)] == [other.id]
        assert [
            row.id
            for row in await store.query(
                tenant_id=TENANT,
                subject_ref="acct:alice",
                detection_type="impossible_travel",
            )
        ] == [first.id]

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(first)
        with pytest.raises(CrossTenantReference):
            await store.put(first.model_copy(update={"tenant_id": OTHER_TENANT}, deep=True))

        if kind == "postgres":
            postgres = cast(PostgresIdentityDetectionStore, store)
            async with postgres._pool.acquire() as conn:
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        "UPDATE aq_identity_detection SET statement=statement WHERE id=$1",
                        first.id,
                    )
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute("DELETE FROM aq_identity_detection WHERE id=$1", first.id)


def _minimal_detection_data(signals: Sequence[SignalRef]) -> dict[str, object]:
    """Only used to prove model-level corroboration rejection before derivation use."""

    from aqelyn.decision import ClaimRef, Derivation, DerivationStep

    return {
        "tenant_id": TENANT,
        "subject_ref": "acct:alice",
        "detection_type": "impossible_travel",
        "statement": "This credential produced an observed authentication anomaly.",
        "corroboration": [item.model_dump(mode="json") for item in signals],
        "confidence": 0.9,
        "basis": [
            {
                "kind": "event",
                "ref": "event:42",
                "as_of": NOW.isoformat(),
                "evidence_id": signals[0].evidence_id,
            }
        ],
        "derivation": Derivation(
            inputs=[ClaimRef(kind="detection", ref_id="event:42")],
            steps=[
                DerivationStep(
                    seq=1,
                    op="select_claims",
                    input_refs=["event:42"],
                    output={"count": 1},
                    note="Model-construction proof only.",
                )
            ],
            result={"count": 1},
            model_version=1,
            engine_version="identity-threat/v1",
        ).model_dump(mode="json"),
        "profile_ref": new_id("prf"),
        "detected_at": NOW.isoformat(),
    }
