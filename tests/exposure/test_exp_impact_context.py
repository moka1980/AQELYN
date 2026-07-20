"""ECR-0041 impact-context contracts for the EA-0023 owner."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ExposureConfigInvalid
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.exposure import (
    AssetRef,
    ExposureBasis,
    ExposureImpactContext,
    ExposureRecord,
    ExposureStore,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    PostgresExposureStore,
    StaticKnownSurfaceSource,
    validate_replayable_exposure,
)
from aqelyn.findings import Finding, FindingStore
from aqelyn.mission import MissionImpactResult
from aqelyn.trust import TrustAssessment

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000310301"
ACTOR = ActorRef(actor_type="system", actor_id="exposure-impact-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _EvidenceLookup:
    def __init__(self, records: Sequence[EvidenceRecord]) -> None:
        self.records = {record.id: record for record in records}

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        _ = actor
        return self.records[evidence_id]


class _TrustProvider:
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment:
        return TrustAssessment(
            subject_ref=subject_ref,
            score=0.8,
            level="high",
            method="impact-context-test/v1",
            contributions=[],
            reason=f"Trusted {len(evidence)} evidence records.",
            no_evidence=False,
            computed_at=now or NOW,
        )


class _MissionProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        self.calls.append(object_id)
        return MissionImpactResult()


class _FindingStore:
    def __init__(self) -> None:
        self.raised: list[Finding] = []

    async def raise_finding(self, finding: Finding) -> Finding:
        self.raised.append(finding)
        return finding


@asynccontextmanager
async def _store(backend: str) -> AsyncIterator[ExposureStore]:
    if backend == "inmemory":
        yield InMemoryExposureStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresExposureStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as connection:
        await connection.execute("TRUNCATE aq_exposure_record")
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _evidence(evidence_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        tenant_id=TENANT,
        evidence_type="data.store_metadata",
        schema_version=1,
        subject=Subject(object_ids=[]),
        collected_at=NOW,
        recorded_at=NOW,
        collector=ACTOR,
        source_id=new_id("src"),
        method="dspm.metadata/v1",
        content={"classification": "pii", "reachability": "external"},
        content_hash="sha256:impact-context",
        confidence=1.0,
        seq=1,
        prev_hash=None,
        record_hash="sha256:impact-context-record",
    )


def _exposure(*, evidence_id: str, object_id: str | None = None) -> ExposureRecord:
    selected_object = object_id or new_id("obj")
    return ExposureRecord(
        tenant_id=TENANT,
        asset_ref=AssetRef(
            kind="asset",
            ref_id=new_id("ast"),
            object_id=selected_object,
            evidence_id=evidence_id,
        ),
        exposure_type="data_store_reachability",
        reachability="external",
        basis=[
            ExposureBasis(
                kind="inventory",
                ref="dspm:data_store",
                as_of=NOW,
                evidence_id=evidence_id,
            )
        ],
        rationale="The data store is externally reachable from known data.",
        flagged=False,
        discovered_at=NOW,
        validated_at=NOW,
    )


def _context(*, evidence_id: str, factor: float, sensitivity: str) -> ExposureImpactContext:
    return ExposureImpactContext(
        status="known",
        factor=factor,
        source_ref=f"dspm:data_asset:{sensitivity}",
        evidence_id=evidence_id,
        reason=f"DSPM classified the store as {sensitivity}.",
    )


def _engine(store: ExposureStore, evidence: EvidenceRecord) -> KnownDataExposureEngine:
    return KnownDataExposureEngine(
        store,
        StaticKnownSurfaceSource([]),
        evidence_lookup=_EvidenceLookup([evidence]),
        trust_provider=_TrustProvider(),
        mission_provider=_MissionProvider(),
    )


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_exp_impact_context_store_contract(backend: str) -> None:
    evidence_id = new_id("evd")
    evidence = _evidence(evidence_id)
    async with _store(backend) as store:
        scored = await _engine(store, evidence).score_exposure(
            _exposure(evidence_id=evidence_id),
            impact_context=_context(
                evidence_id=evidence_id,
                factor=0.8,
                sensitivity="pii",
            ),
        )

        saved = await store.put(scored)
        loaded = await store.get(saved.id, tenant_id=TENANT)

        assert loaded is not None
        assert loaded.impact_context == saved.impact_context
        assert validate_replayable_exposure(loaded) == loaded
        assert loaded.derivation is not None
        assert loaded.derivation.engine_version == "exposure-score/v2"


async def test_exp_impact_context() -> None:
    evidence_id = new_id("evd")
    evidence = _evidence(evidence_id)
    store = InMemoryExposureStore(mode="enterprise")
    engine = _engine(store, evidence)

    pii = await engine.score_exposure(
        _exposure(evidence_id=evidence_id),
        impact_context=_context(evidence_id=evidence_id, factor=0.8, sensitivity="pii"),
    )
    secret = await engine.score_exposure(
        _exposure(evidence_id=evidence_id),
        impact_context=_context(evidence_id=evidence_id, factor=1.0, sensitivity="secret"),
    )
    baseline = await engine.score_exposure(_exposure(evidence_id=evidence_id))

    assert pii.score is not None
    assert secret.score is not None
    assert secret.score >= pii.score
    assert baseline.score == secret.score
    assert baseline.derivation is not None
    assert baseline.derivation.engine_version == "exposure-score/v1"
    assert pii.derivation is not None
    assert pii.impact_context is not None
    assert pii.derivation.steps[1].params["impact_context"] == pii.impact_context.model_dump(
        mode="json"
    )


async def test_exp_impact_context_unknown_or_tampered() -> None:
    evidence_id = new_id("evd")
    evidence = _evidence(evidence_id)
    store = InMemoryExposureStore(mode="enterprise")
    engine = _engine(store, evidence)
    raw = _exposure(evidence_id=evidence_id)

    with pytest.raises(ExposureConfigInvalid, match="unknown impact context"):
        await engine.score_exposure(
            raw,
            impact_context=ExposureImpactContext(
                status="unknown",
                source_ref="dspm:data_asset:unknown",
                evidence_id=evidence_id,
                reason="Classification could not be completed.",
            ),
        )

    scored = await engine.score_exposure(
        raw,
        impact_context=_context(evidence_id=evidence_id, factor=0.8, sensitivity="pii"),
    )
    tampered = scored.model_copy(
        update={
            "impact_context": _context(
                evidence_id=evidence_id,
                factor=1.0,
                sensitivity="secret",
            )
        },
        deep=True,
    )
    with pytest.raises(ExposureConfigInvalid, match="does not match derivation"):
        await store.put(tampered)


async def test_exp_asset_ref_scoring_subject() -> None:
    evidence_id = new_id("evd")
    object_id = new_id("obj")
    evidence = _evidence(evidence_id)
    mission = _MissionProvider()
    findings = _FindingStore()
    engine = KnownDataExposureEngine(
        InMemoryExposureStore(mode="enterprise"),
        StaticKnownSurfaceSource([]),
        evidence_lookup=_EvidenceLookup([evidence]),
        trust_provider=_TrustProvider(),
        mission_provider=mission,
        finding_store=cast(FindingStore, findings),
    )

    scored = await engine.score_exposure(_exposure(evidence_id=evidence_id, object_id=object_id))
    finding = await engine.raise_exposure_finding(scored)

    assert mission.calls == [object_id]
    assert finding.affected_object_ids == [object_id]
    assert scored.asset_ref.ref_id in finding.dedup_key

    without_object = _exposure(evidence_id=evidence_id).model_copy(
        update={
            "asset_ref": AssetRef(
                kind="asset",
                ref_id=new_id("ast"),
                evidence_id=evidence_id,
            )
        },
        deep=True,
    )
    with pytest.raises(ExposureConfigInvalid, match=r"asset_ref\.ref_id"):
        await engine.score_exposure(without_object)


def test_exp_asset_ref_dual_identity_consistency() -> None:
    object_id = new_id("obj")
    assert AssetRef(kind="asset", ref_id=new_id("ast"), object_id=object_id).object_id == object_id

    with pytest.raises(ExposureConfigInvalid, match="must match ref_id"):
        AssetRef(kind="asset", ref_id=object_id, object_id=new_id("obj"))
