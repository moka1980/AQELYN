"""I4 acceptance tests for reuse, findings, and the right of reply."""

from __future__ import annotations

import inspect
import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

import aqelyn.idthreat as idthreat
from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import CrossTenantReference, OptimisticConcurrencyConflict
from aqelyn.detection import BehaviorProfile
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.findings import InMemoryFindingStore
from aqelyn.graph import Path
from aqelyn.iag import AccessPath, AccessRisk, AccessRiskReport
from aqelyn.idthreat import (
    IdentityDetection,
    IdentityDetectionStore,
    IdentityObservation,
    IdentityReview,
    IdentityThreatEngine,
    IdThreatConfig,
    InMemoryIdentityDetectionStore,
    PostgresIdentityDetectionStore,
    SignalRef,
)
from aqelyn.objects import ObjectQuery
from aqelyn.trust import TrustAssessment

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 18, 14, 0, tzinfo=UTC)
REVIEWED_AT = NOW + timedelta(hours=1)
TENANT = "018f0000-0000-7000-8000-000000270401"
OTHER_TENANT = "018f0000-0000-7000-8000-000000270402"
REVIEWER = ActorRef(actor_type="user", actor_id="security-reviewer")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _TrustAssessor:
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment:
        assert subject_ref == "acct:alice"
        assert len(evidence) == 2
        return TrustAssessment(
            subject_ref=subject_ref,
            score=0.91,
            level="high",
            method="noisy_or/v1",
            contributions=[],
            reason="Two independent evidence records support the account observation.",
            no_evidence=False,
            computed_at=now or NOW,
        )


class _ProfileSpy:
    def __init__(self, profile: BehaviorProfile) -> None:
        self.profile = profile
        self.calls: list[tuple[str, int | None]] = []

    async def get(
        self,
        profile_id: str,
        *,
        version: int | None = None,
    ) -> BehaviorProfile | None:
        self.calls.append((profile_id, version))
        if profile_id != self.profile.id or version != self.profile.version:
            return None
        return self.profile.model_copy(deep=True)


class _IAGSpy:
    def __init__(
        self,
        *,
        identity_id: str,
        account_id: str,
        entitlement_id: str,
    ) -> None:
        self.identity_id = identity_id
        self.account_id = account_id
        self.entitlement_id = entitlement_id
        self.access_calls: list[tuple[str, str | None]] = []
        self.risk_calls: list[tuple[str | None, ObjectQuery | None]] = []
        self.path = Path(
            node_ids=[identity_id, account_id, entitlement_id],
            edges=[],
            length=2,
        )

    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]:
        self.access_calls.append((identity_id, tenant_id))
        return [
            AccessPath(
                identity_id=self.identity_id,
                account_id=self.account_id,
                entitlement_ids=[self.entitlement_id],
                via=self.path,
            )
        ]

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        self.risk_calls.append((tenant_id, scope))
        return AccessRiskReport(
            risks=[
                AccessRisk(
                    kind="over_privilege",
                    subject_id=self.identity_id,
                    detail={"entitlement_id": self.entitlement_id},
                    severity="high",
                    evidence_path=self.path,
                    reason="EA-0011 already identifies this entitlement as over-privileged.",
                )
            ],
            evaluated=1,
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
        await conn.execute("TRUNCATE aq_identity_review, aq_identity_detection")
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


async def _evidence(
    store: InMemoryEvidenceStore,
    *,
    kind: str,
    detail: str,
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type=f"identity.{kind}",
            schema_version=1,
            subject=Subject(),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ActorRef(actor_type="system", actor_id="identity-collector"),
            source_id=new_id("src"),
            method="identity-observation/v1",
            content={"detail": detail},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


async def _detected(
    store: IdentityDetectionStore,
) -> tuple[
    IdentityThreatEngine,
    IdentityDetection,
    IdentityObservation,
    _ProfileSpy,
    _IAGSpy,
    InMemoryEvidenceStore,
    InMemoryFindingStore,
]:
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    first = await _evidence(evidence_store, kind="authentication", detail="Oslo login")
    second = await _evidence(evidence_store, kind="session", detail="Sao Paulo login")
    identity_id = new_id("obj")
    account_id = new_id("obj")
    entitlement_id = new_id("obj")
    profile = BehaviorProfile(
        id=new_id("prf"),
        tenant_id=TENANT,
        subject_ref="acct:alice",
        metric="authentication_locations",
        window_days=30,
        baseline={"usual_locations": ["Oslo"]},
        computed_at=NOW - timedelta(days=1),
        version=4,
    )
    profile_spy = _ProfileSpy(profile)
    iag_spy = _IAGSpy(
        identity_id=identity_id,
        account_id=account_id,
        entitlement_id=entitlement_id,
    )
    finding_store = InMemoryFindingStore(
        mode="enterprise",
        evidence_exists=evidence_store.exists,
    )
    engine = IdentityThreatEngine(
        store,
        evidence_store=evidence_store,
        trust_engine=_TrustAssessor(),
        profile_store=profile_spy,
        entitlement_analyzer=iag_spy,
        config=_config(),
        finding_store=finding_store,
        evidence_recorder=evidence_store,
        source_id=new_id("src"),
        clock=lambda: REVIEWED_AT,
    )
    observation = IdentityObservation(
        subject_ref="acct:alice",
        identity_id=identity_id,
        detection_type="impossible_travel",
        signals=[
            SignalRef(
                kind="authentication",
                ref="auth:alice:oslo",
                as_of=NOW,
                evidence_id=first.id,
            ),
            SignalRef(
                kind="session",
                ref="session:alice:sao-paulo",
                as_of=NOW + timedelta(minutes=1),
                evidence_id=second.id,
            ),
        ],
        profile_ref=profile.id,
        profile_version=profile.version,
        rule_ref="impossible-travel-rule",
        rule_version=3,
        detected_at=NOW + timedelta(minutes=2),
    )
    detection = await engine.detect(observation=observation, tenant_id=TENANT)
    assert detection is not None
    return (
        engine,
        detection,
        observation,
        profile_spy,
        iag_spy,
        evidence_store,
        finding_store,
    )


async def test_idt_profile_delegates_detection() -> None:
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    engine, detection, observation, profile, _iag, _evidence_store, _findings = await _detected(
        store
    )

    assert profile.calls == [(observation.profile_ref, observation.profile_version)]
    assert detection.profile_ref == observation.profile_ref
    profile_basis = next(item for item in detection.basis if item.kind == "profile")
    assert profile_basis.ref == f"{observation.profile_ref}:v{observation.profile_version}"
    assert profile_basis.as_of == profile.profile.computed_at
    assert not hasattr(engine, "build_profile")
    assert not hasattr(engine, "detect_anomalies")


async def test_idt_entitlements_cite_iag() -> None:
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    _engine, detection, observation, _profile, iag, _evidence_store, _findings = await _detected(
        store
    )

    assert iag.access_calls == [(observation.identity_id, TENANT)]
    assert iag.risk_calls == [(TENANT, None)]
    assert detection.entitlement_refs == [iag.entitlement_id]
    refs = {item.ref for item in detection.basis if item.kind == "entitlement"}
    assert refs == {
        f"iag-identity:{observation.identity_id}",
        iag.entitlement_id,
        f"iag-risk:over_privilege:{observation.identity_id}",
    }
    assert "entitlement_verdict" not in IdentityDetection.model_fields
    assert not hasattr(_engine, "evaluate_entitlements")


async def test_idt_profile_event_not_emitted() -> None:
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    engine, _detection, observation, profile, _iag, _evidence_store, _findings = await _detected(
        store
    )

    assert profile.calls == [(observation.profile_ref, observation.profile_version)]
    assert not hasattr(engine, "emit")
    assert not hasattr(engine, "publish")
    assert not hasattr(engine, "profile_updated")
    assert "behavior.profile.updated" not in vars(idthreat).values()


async def test_idt_finding_and_review() -> None:
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    engine, detection, _observation, _profile, iag, evidence_store, _findings = await _detected(
        store
    )

    finding = await engine.raise_detection(detection, by=REVIEWER)

    assert finding.source_engine == "idthreat_engine"
    assert finding.finding_type == "identity_threat.impossible_travel"
    assert finding.automation.eligibility == "none"
    assert finding.automation.requires_approval is True
    assert finding.automation.action_ref is None
    assert finding.affected_object_ids == sorted([iag.identity_id, iag.entitlement_id])
    assert finding.evidence_ids == sorted(
        signal.evidence_id for signal in detection.corroboration if signal.evidence_id is not None
    )
    expert_details = finding.expert_details
    assert expert_details is not None
    assert expert_details["person_verdict"] is False
    assert "employee" not in finding.title.lower()
    assert "person" not in finding.title.lower()

    reviewed = await engine.review(
        detection.id,
        by=REVIEWER,
        outcome="account owner confirmed travel was impossible",
        tenant_id=TENANT,
    )
    review = await store.review_for(detection.id, tenant_id=TENANT)

    assert reviewed.status == "reviewed"
    assert review is not None
    assert review.reviewed_by == REVIEWER
    assert review.outcome == "account owner confirmed travel was impossible"
    review_evidence = await evidence_store.get(review.evidence_id, actor=REVIEWER)
    assert review_evidence.evidence_type == "identity.detection_review"
    review_content = review_evidence.content
    assert review_content is not None
    assert review_content["detection_id"] == detection.id
    assert review_content["source_evidence_ids"] == finding.evidence_ids
    assert review_content["derivation"] == detection.derivation.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_idt_right_of_reply(kind: str) -> None:
    async for store in _store(kind):
        (
            engine,
            detection,
            _observation,
            _profile,
            _iag,
            _evidence_store,
            _findings,
        ) = await _detected(store)
        assert detection.status == "open"
        assert not hasattr(engine, "execute")
        assert not hasattr(engine, "propose")
        with pytest.raises(CrossTenantReference):
            await store.record_review(
                IdentityReview(
                    detection_id=detection.id,
                    tenant_id=OTHER_TENANT,
                    outcome="cross-tenant review must be refused",
                    reviewed_by=REVIEWER,
                    reviewed_at=REVIEWED_AT,
                    evidence_id=new_id("evd"),
                )
            )

        reviewed = await engine.review(
            detection.id,
            by=REVIEWER,
            outcome="account owner disputed the observation",
            tenant_id=TENANT,
        )
        materialized = await store.get(detection.id, tenant_id=TENANT)
        rows = await store.query(tenant_id=TENANT)
        persisted_review = await store.review_for(detection.id, tenant_id=TENANT)

        assert reviewed.status == "reviewed"
        assert materialized is not None
        assert materialized.status == "reviewed"
        assert [row.status for row in rows] == ["reviewed"]
        assert persisted_review is not None
        assert persisted_review.reviewed_by == REVIEWER
        with pytest.raises(OptimisticConcurrencyConflict):
            await engine.review(
                detection.id,
                by=REVIEWER,
                outcome="a second outcome must not replace the first",
                tenant_id=TENANT,
            )
        assert await store.review_for(detection.id, tenant_id=TENANT) == persisted_review

        if kind == "inmemory":
            memory = cast(InMemoryIdentityDetectionStore, store)
            assert memory._records[detection.id].status == "open"
        else:
            postgres = cast(PostgresIdentityDetectionStore, store)
            async with postgres._pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT status FROM aq_identity_detection WHERE id=$1",
                        detection.id,
                    )
                    == "open"
                )
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        "UPDATE aq_identity_review SET outcome=outcome WHERE detection_id=$1",
                        detection.id,
                    )
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        "DELETE FROM aq_identity_review WHERE detection_id=$1",
                        detection.id,
                    )


def test_idt_no_precrime() -> None:
    forbidden_callables = {
        "forecast",
        "predict",
        "project",
        "risk_of_person",
        "score_user",
    }
    public_callables = {
        name
        for name, value in inspect.getmembers(IdentityThreatEngine, callable)
        if not name.startswith("_")
    }

    assert public_callables.isdisjoint(forbidden_callables)
    assert set(IdentityDetection.model_fields).isdisjoint(
        {"person", "person_id", "predicted_behavior", "risk_score", "user_score"}
    )
    assert set(IdentityObservation.model_fields).isdisjoint(
        {"person", "person_id", "prediction", "forecast"}
    )


@pytest.mark.asyncio
async def test_idt_profile_mismatch_withholds_detection() -> None:
    """A profile source returning a different record withholds the detection (S7).

    The basis pins `profile_ref`, so accepting a mismatched record would cite a
    profile the detection never used — the accused would be shown the wrong
    baseline. This must be a withhold in the module's own taxonomy (§12), not an
    assertion that disappears under `python -O`.
    """
    store = InMemoryIdentityDetectionStore(config=_config(), mode="enterprise")
    engine, detection, observation, profile_spy, _iag, _ev, _fs = await _detected(store)

    class _MismatchedProfileSource:
        def __init__(self, real: _ProfileSpy) -> None:
            self.real = real

        async def get(
            self,
            profile_id: str,
            *,
            version: int | None = None,
        ) -> BehaviorProfile | None:
            profile = await self.real.get(profile_id, version=version)
            if profile is None:
                return None
            return profile.model_copy(update={"id": new_id("prf")})

    engine.profile_store = _MismatchedProfileSource(profile_spy)

    assert await engine.detect(observation=observation, tenant_id=detection.tenant_id) is None
