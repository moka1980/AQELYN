"""C-030 G4 acceptance tests for replayable scoring and identity drift."""

from __future__ import annotations

import inspect
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest
from pydantic import ValidationError

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    ISPMConfigInvalid,
    OptimisticConcurrencyConflict,
    PostureScoreNotReplayable,
)
from aqelyn.decision import replay
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.iag import AccessRisk, AccessRiskReport
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.ispm import (
    ControlFact,
    IdentityBaseline,
    IdentityBaselineEntry,
    IdentityControls,
    IdentityDriftItem,
    IdentityGovernanceOwner,
    IdentityPostureScore,
    InMemoryISPMStore,
    ISPMEngine,
    ISPMStore,
    NormalizedIdentity,
    PostgresISPMStore,
)
from aqelyn.ispm import scoring as scoring_module
from aqelyn.ispm.models import ControlState
from aqelyn.ispm.scoring import posture_operation_registry
from aqelyn.mission import MissionImpactResult
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.risk import Risk, RiskConfig
from aqelyn.risk.scoring import score_risk as real_score_risk
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000330401"
NOW = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="system", actor_id="ispm-g4-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _GovernanceOwner:
    def __init__(self, report: AccessRiskReport) -> None:
        self.report = report
        self.calls: list[tuple[str | None, ObjectQuery | None]] = []

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        self.calls.append((tenant_id, scope))
        return self.report


class _MissionOwner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        self.calls.append(object_id)
        return MissionImpactResult()


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[ISPMStore]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: ISPMStore = InMemoryISPMStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresISPMStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_ispm_posture_score, aq_ispm_baseline_revision, "
                "aq_ispm_drift_snapshot, aq_ispm_identity_revision, aq_ispm_identity_key "
                "RESTART IDENTITY CASCADE"
            )
        store = postgres
        closer = cast(_Closable, postgres)
    try:
        yield store
    finally:
        if closer is not None:
            await closer.close()


async def _evidence(store: InMemoryEvidenceStore, *object_ids: str) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="identity.controls",
            schema_version=1,
            subject=Subject(object_ids=list(object_ids)),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=new_id("src"),
            method="ispm-g4-fixture/v1",
            content={"metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


def _fact(state: ControlState, evidence_id: str | None = None) -> ControlFact:
    if state == "unknown":
        return ControlFact(reason="The control has not been established.")
    return ControlFact(
        state=state,
        established_by="provider:entra",
        evidence_id=evidence_id,
        reason=f"The provider reported the control as {state}.",
    )


async def _engine_with_identity(
    store: ISPMStore,
    *,
    mfa: ControlState,
    risks: list[AccessRisk] | None = None,
    reliability: float = 0.8,
) -> tuple[ISPMEngine, NormalizedIdentity, str, _GovernanceOwner, _MissionOwner]:
    account_id = new_id("obj")
    identity_id = new_id("obj")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    evidence = await _evidence(evidence_store, identity_id, account_id)
    identity = NormalizedIdentity(
        object_id=identity_id,
        tenant_id=TENANT,
        external_id=f"identity:{identity_id}",
        provider="entra",
        identity_kind="human",
        account_object_ids=[account_id],
        relationship_ids=[new_id("rel")],
        controls=IdentityControls(
            mfa=_fact(mfa, evidence.id),
            lifecycle=_fact("present", evidence.id),
            last_activity=_fact("present", evidence.id),
        ),
        field_provenance={"identity_kind": "provider:/identity/type"},
        evidence_id=evidence.id,
    )
    await store.upsert_identity(identity)
    owner = _GovernanceOwner(AccessRiskReport(risks=risks or [], evaluated=1, truncated=False))
    mission = _MissionOwner()
    engine = ISPMEngine(
        store,
        object_store=InMemoryObjectStore(mode="enterprise"),
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise")),
        evidence_store=evidence_store,
        trust=TrustEngine(
            registry=InMemorySourceReliabilityRegistry(default_reliability=reliability)
        ),
        governance_owner=cast(IdentityGovernanceOwner, owner),
        mission_owner=mission,
    )
    return engine, identity, account_id, owner, mission


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_ispm_score_cites_real_iag_risk(kind: str) -> None:
    async with _store(kind) as store:
        account_id = new_id("obj")
        owner_risk = AccessRisk(
            kind="dormant",
            subject_id=account_id,
            detail={"last_used_days": 180},
            severity="medium",
            reason="EA-0011 observed a dormant account.",
        )
        engine, identity, stored_account_id, owner, mission = await _engine_with_identity(
            store,
            mfa="present",
            risks=[owner_risk.model_copy(update={"subject_id": account_id})],
        )
        selected_risk = owner.report.risks[0].model_copy(update={"subject_id": stored_account_id})
        owner.report = owner.report.model_copy(update={"risks": [selected_risk]})

        score = await engine.score_identity(stored_account_id, tenant_id=TENANT)

        assert score.iag_risks == [selected_risk]
        assert score.derivation.steps[0].params["iag_risks"] == [
            selected_risk.model_dump(mode="json")
        ]
        assert score.derivation.steps[0].params["ea0013_risk"]["category"] == (
            "identity_control_posture"
        )
        assert score.derivation.steps[0].params["trust"]["subject_ref"] == (
            f"ispm:{stored_account_id}"
        )
        assert owner.calls
        assert owner.calls[0][0] == TENANT
        assert mission.calls == [stored_account_id]
        assert identity.object_id in {claim.ref_id for claim in score.derivation.inputs}


async def test_ispm_unknown_not_favourable() -> None:
    async with _store("inmemory") as store:
        scores: dict[ControlState, IdentityPostureScore] = {}
        for state in ("present", "absent", "unknown"):
            engine, _, account_id, _, _ = await _engine_with_identity(store, mfa=state)
            scores[state] = await engine.score_identity(account_id, tenant_id=TENANT)

        assert scores["unknown"].score <= scores["absent"].score
        assert scores["unknown"].score < scores["present"].score
        unknown_factor = next(
            factor for factor in scores["unknown"].factors if factor.name == "mfa"
        )
        assert unknown_factor.status == "unknown"
        assert unknown_factor.value is None
        output = scores["unknown"].derivation.result
        assert output["known_only_score"] == 100.0
        assert output["coverage_adjustment"] == 0.8


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_ispm_score_replay(kind: str) -> None:
    async with _store(kind) as store:
        engine, _, account_id, _, _ = await _engine_with_identity(store, mfa="present")
        score = await engine.score_identity(account_id, tenant_id=TENANT)

        assert replay(score.derivation, registry=posture_operation_registry()) == {
            "score": score.score,
            "known_only_score": 100.0,
            "coverage_adjustment": 1.0,
            "known_weight": 1.0,
        }
        assert await store.get_score(score.id, tenant_id=TENANT) == score

        step = score.derivation.steps[0]
        tampered_step = step.model_copy(
            update={"output": {**step.output, "score": score.score - 1.0}},
            deep=True,
        )
        tampered_derivation = score.derivation.model_copy(
            update={"steps": [tampered_step]},
            deep=True,
        )
        with pytest.raises(PostureScoreNotReplayable):
            await store.put_score(
                score.model_copy(update={"derivation": tampered_derivation}, deep=True)
            )


async def test_ispm_score_composed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Risk, RiskConfig | None, float, str | None]] = []

    def recording_score_risk(
        risk: Risk,
        *,
        config: RiskConfig | None = None,
        mission_factor: float = 0.0,
        top_mission_id: str | None = None,
    ) -> Risk:
        calls.append((risk, config, mission_factor, top_mission_id))
        return real_score_risk(
            risk,
            config=config,
            mission_factor=mission_factor,
            top_mission_id=top_mission_id,
        )

    monkeypatch.setattr(scoring_module, "score_risk", recording_score_risk)
    async with _store("inmemory") as store:
        engine, _, account_id, owner, _ = await _engine_with_identity(store, mfa="present")
        owner.report = AccessRiskReport(
            risks=[
                AccessRisk(
                    kind="dormant",
                    subject_id=account_id,
                    severity="medium",
                    reason="EA-0011 observed a dormant account.",
                )
            ],
            evaluated=1,
        )

        first = await engine.score_identity(account_id, tenant_id=TENANT)
        second = await engine.score_identity(account_id, tenant_id=TENANT)
        low_trust_engine, _, low_trust_account, low_trust_owner, _ = await _engine_with_identity(
            store, mfa="present", reliability=0.2
        )
        low_trust_owner.report = AccessRiskReport(
            risks=[
                AccessRisk(
                    kind="dormant",
                    subject_id=low_trust_account,
                    severity="medium",
                    reason="EA-0011 observed the same dormant control state.",
                )
            ],
            evaluated=1,
        )
        low_trust = await low_trust_engine.score_identity(
            low_trust_account,
            tenant_id=TENANT,
        )

        assert len(calls) == 3
        assert all(call[0].category == "identity_control_posture" for call in calls)
        assert all(call[1] == engine.risk_config for call in calls)
        assert first.score == second.score
        assert low_trust.score == first.score
        assert low_trust.confidence < first.confidence
        assert [
            (factor.name, factor.value, factor.weight, factor.status) for factor in first.factors
        ] == [
            (factor.name, factor.value, factor.weight, factor.status) for factor in second.factors
        ]
        params = first.derivation.steps[0].params
        assert set(params) == {"factors", "iag_risks", "ea0013_risk", "trust", "mission"}


def test_ispm_no_person_score() -> None:
    assert list(inspect.signature(ISPMEngine.score_identity).parameters) == [
        "self",
        "account_object_id",
        "tenant_id",
    ]
    assert not any(
        hasattr(ISPMEngine, name)
        for name in ("score_person", "score_user", "aggregate_person_score")
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_ispm_drift_shape(kind: str) -> None:
    async with _store(kind) as store:
        engine, identity, _, _, _ = await _engine_with_identity(store, mfa="present")
        baseline = IdentityBaseline(
            tenant_id=TENANT,
            name="Human account controls",
            identity_kind="human",
            entries=[
                IdentityBaselineEntry(
                    key="mfa", expected="present", comparator="eq", severity="high"
                ),
                IdentityBaselineEntry(
                    key="lifecycle", expected="absent", comparator="eq", severity="high"
                ),
                IdentityBaselineEntry(
                    key="unrepresented_control",
                    expected="present",
                    comparator="eq",
                    severity="medium",
                ),
            ],
            approved_by=ACTOR,
            approved_at=NOW,
        )
        await store.put_baseline(baseline)

        snapshot = await engine.detect_drift(baseline_id=baseline.id, tenant_id=TENANT)

        assert (snapshot.passed, snapshot.failed, snapshot.unknown) == (1, 1, 1)
        unknown = next(item for item in snapshot.items if item.status == "unknown")
        assert unknown.identity_id == identity.object_id
        assert unknown.observed is None
        assert await store.get_drift(snapshot.id, tenant_id=TENANT) == snapshot

        changed = snapshot.model_copy(
            update={
                "items": [
                    item.model_copy(update={"reason": f"{item.reason} changed"}, deep=True)
                    for item in snapshot.items
                ]
            },
            deep=True,
        )
        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put_drift(changed)

        with pytest.raises((ISPMConfigInvalid, ValidationError)):
            IdentityDriftItem(
                identity_id=identity.object_id,
                key="mfa",
                expected="present",
                observed="present",
                status="unknown",
                reason="Unknown cannot carry a favourable observation.",
            )
