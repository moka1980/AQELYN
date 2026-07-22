"""C-032 J2 acceptance tests for credential governance scoring."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import PREFIXES, ActorRef, new_id
from aqelyn.conventions.errors import (
    CredentialGovernanceNotReplayable,
    OptimisticConcurrencyConflict,
)
from aqelyn.decision import replay
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.exposure import AssetRef, ExposureBasis, ExposureImpactContext, ExposureRecord
from aqelyn.governance import ComplianceSnapshot, ControlResult
from aqelyn.inventory import Ownership
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime
from aqelyn.mission import MissionImpactResult
from aqelyn.risk import Risk, RiskConfig
from aqelyn.risk.scoring import score_risk as real_score_risk
from aqelyn.secrets import (
    ComposedCredentialGovernance,
    CredentialGovernanceScore,
    CryptographicExposure,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoStore,
    GovernanceFactor,
    InMemoryCryptoStore,
    Lifecycle,
    PostgresCryptoStore,
    compose_credential_governance,
    governance_operation_registry,
    governance_score_result,
)
from aqelyn.secrets import scoring as scoring_module
from aqelyn.trust import TrustAssessment

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000320601"
OTHER_TENANT = "018f0000-0000-7000-8000-000000320602"
NOW = datetime(2026, 7, 22, 16, 0, tzinfo=UTC)
EVIDENCE_ID = new_id("evd")
SOURCE_ID = new_id("src")
OBJECT_ID = new_id("obj")
INVENTORY_ID = f"ast_{OBJECT_ID.split('_', 1)[1]}"
ASSET_ID = new_id("cky")


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[CryptoStore]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: CryptoStore = InMemoryCryptoStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresCryptoStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as connection:
            await connection.execute(
                "TRUNCATE aq_crypto_governance_score, aq_crypto_assessment, "
                "aq_crypto_asset_revision, aq_crypto_asset_identity "
                "RESTART IDENTITY CASCADE"
            )
        store = postgres
        closer = cast(_Closable, postgres)
    try:
        yield store
    finally:
        if closer is not None:
            await closer.close()


def _valid_lifecycle(reason: str) -> Lifecycle:
    return Lifecycle(
        status="valid",
        source_ref="EA-0032",
        evidence_id=EVIDENCE_ID,
        reason=reason,
    )


def _asset() -> CryptographicKey:
    return CryptographicKey(
        id=ASSET_ID,
        tenant_id=TENANT,
        object_id=OBJECT_ID,
        inventory_ref=INVENTORY_ID,
        external_key_ref="urn:aqelyn:key:governance-test",
        fingerprint=f"hmac-sha256:{601:064x}",
        algorithm="rsa",
        key_size=4096,
        usages=["signing"],
        last_rotated_at=NOW,
        strength=_valid_lifecycle("Key strength meets policy."),
        rotation=_valid_lifecycle("Key rotation meets policy."),
        claim_confidence=1.0,
        source_id=SOURCE_ID,
        observed_at=NOW,
        evidence_id=EVIDENCE_ID,
    )


def _crypto_exposure(
    asset: CryptographicKey,
    *,
    owner_id: str,
) -> CryptographicExposure:
    return CryptographicExposure(
        id=f"crypto-exposure:{asset.id}:{owner_id}",
        tenant_id=TENANT,
        asset_id=asset.id,
        surface_ref=asset.inventory_ref,
        object_id=asset.object_id,
        exposure_record_id=owner_id,
        status="confirmed",
        impact_context=ExposureImpactContext(
            kind="credential_sensitivity",
            status="known",
            factor=1.0,
            source_ref=asset.id,
            evidence_id=asset.evidence_id,
            reason="Credential capability is sensitivity context.",
        ),
        reason="EA-0023 established reachability.",
        evidence_id=asset.evidence_id,
    )


def _owner_exposure(
    asset: CryptographicKey,
    *,
    score: float,
    status: str = "open",
) -> ExposureRecord:
    exposure_id = new_id("exp")
    return ExposureRecord(
        id=exposure_id,
        tenant_id=TENANT,
        asset_ref=AssetRef(
            kind="asset",
            ref_id=asset.inventory_ref,
            object_id=asset.object_id,
            evidence_id=asset.evidence_id,
        ),
        exposure_type="credential_reachability",
        reachability="external",
        basis=[
            ExposureBasis(
                kind="inventory",
                ref=asset.inventory_ref,
                as_of=NOW,
                evidence_id=asset.evidence_id,
            )
        ],
        impact_context=ExposureImpactContext(
            kind="credential_sensitivity",
            status="known",
            factor=1.0,
            source_ref=asset.id,
            evidence_id=asset.evidence_id,
            reason="Credential capability is sensitivity context.",
        ),
        score=score,
        confidence=1.0,
        rationale="EA-0023 scored the known surface.",
        flagged=False,
        discovered_at=NOW,
        status=status,
    )


def _trust() -> TrustAssessment:
    return TrustAssessment(
        subject_ref=f"crypto-governance:{_asset().id}",
        score=1.0,
        level="high",
        method="fixture/v1",
        contributions=[],
        reason="The cited metadata evidence is trusted.",
        no_evidence=False,
        computed_at=NOW,
    )


def _compliance() -> ComplianceSnapshot:
    return ComplianceSnapshot(
        id=new_id("snap"),
        tenant_id=TENANT,
        run_at=NOW,
        scope={"object_type": "cryptographic_key"},
        overall_score=1.0,
        control_results=[
            ControlResult(
                control_id="crypto-control",
                evaluated=1,
                passed=1,
                failed=0,
                score=1.0,
                reason="The credential object passed the control.",
            )
        ],
        evidence_id=EVIDENCE_ID,
    )


def _ownership(state: str) -> Ownership | None:
    if state == "unknown":
        return None
    return Ownership(
        business_owner="team:payments" if state == "good" else None,
        rationale=(
            "EA-0025 records an attributed business owner."
            if state == "good"
            else "EA-0025 records that no owner is assigned."
        ),
        source_id=SOURCE_ID,
        evidence_id=EVIDENCE_ID,
        observed_at=NOW,
    )


def _composed(
    *,
    ownership_state: str = "good",
    exposure_score: float = 0.0,
    exposure_status: str = "closed",
) -> ComposedCredentialGovernance:
    asset = _asset()
    owner_exposure = _owner_exposure(
        asset,
        score=exposure_score,
        status=exposure_status,
    )
    return compose_credential_governance(
        asset,
        ownership=_ownership(ownership_state),
        exposure=_crypto_exposure(asset, owner_id=owner_exposure.id),
        owner_exposure=owner_exposure,
        trust=_trust(),
        mission=MissionImpactResult(),
        compliance=_compliance(),
        factor_weights={
            "owner_risk": 0.20,
            "lifecycle": 0.20,
            "ownership": 0.15,
            "exposure": 0.20,
            "trust": 0.10,
            "compliance": 0.15,
        },
        computed_at=NOW,
    )


def _score_record() -> CredentialGovernanceScore:
    asset = _asset()
    composed = _composed()
    return CredentialGovernanceScore(
        tenant_id=TENANT,
        asset_id=asset.id,
        object_id=asset.object_id,
        score=composed.score,
        factors=composed.factors,
        active_critical_exposure_ids=composed.active_critical_exposure_ids,
        derivation=composed.derivation,
        confidence=composed.confidence,
        statement=composed.statement,
        computed_at=NOW,
        evidence_id=EVIDENCE_ID,
    )


def test_crypto_gov_score_replay() -> None:
    score = _score_record()

    result = replay(score.derivation, registry=governance_operation_registry())

    assert result["score"] == score.score
    assert result["known_only_score"] == 100.0
    assert result["coverage_adjustment"] == 1.0
    assert result["uncertainty_penalty"] == 0.0


def test_crypto_gov_score_composed_not_rescored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Risk] = []

    def recording_score_risk(
        risk: Risk,
        *,
        config: RiskConfig | None = None,
        mission_factor: float = 0.0,
        top_mission_id: str | None = None,
    ) -> Risk:
        calls.append(risk)
        return real_score_risk(
            risk,
            config=config,
            mission_factor=mission_factor,
            top_mission_id=top_mission_id,
        )

    monkeypatch.setattr(scoring_module, "score_risk", recording_score_risk)

    composed = _composed(ownership_state="bad")
    replayed = replay(composed.derivation, registry=governance_operation_registry())

    assert len(calls) == 1
    assert calls[0].category == "credential_governance"
    assert replayed["score"] == composed.score
    assert len(calls) == 1
    assert composed.derivation.steps[0].params["ea0013_risk"]["id"] == _asset().id


def test_crypto_gov_unknown_three_way() -> None:
    good = _composed(ownership_state="good")
    bad = _composed(ownership_state="bad")
    unknown = _composed(ownership_state="unknown")

    assert len({good.score, bad.score, unknown.score}) == 3
    assert unknown.score < bad.score < good.score
    unknown_factor = next(factor for factor in unknown.factors if factor.name == "ownership")
    assert unknown_factor.status == "unknown"
    assert unknown_factor.rating is None


def test_crypto_gov_coverage_adjustment() -> None:
    factors = [
        GovernanceFactor(
            name=name,
            rating=1.0 if name == "trust" else None,
            weight=weight,
            status="known" if name == "trust" else "unknown",
            source_ref={"owner": "test"},
            reason="Known only for the trust control." if name == "trust" else "Not assessed.",
        )
        for name, weight in (
            ("owner_risk", 0.20),
            ("lifecycle", 0.20),
            ("ownership", 0.15),
            ("exposure", 0.20),
            ("trust", 0.10),
            ("compliance", 0.15),
        )
    ]

    result = governance_score_result(
        [],
        {
            "factors": [factor.model_dump(mode="json") for factor in factors],
            "active_critical_exposure_ids": [],
        },
    )

    assert result["known_only_score"] == 100.0
    assert result["coverage_adjustment"] == 0.1
    assert result["uncertainty_penalty"] == 9.0
    assert result["score"] == 1.0


def test_crypto_gov_exposure_not_averaged_away() -> None:
    exposed = _composed(exposure_score=95.0, exposure_status="open")

    assert exposed.score <= 69.0
    assert len(exposed.active_critical_exposure_ids) == 1
    assert "active critical exposure" in exposed.statement.casefold()
    assert exposed.derivation.steps[0].params["active_critical_exposure_ids"] == (
        exposed.active_critical_exposure_ids
    )
    assert "exposure_cap_applied" in exposed.derivation.result


def test_crypto_gov_statement_says_governance_not_safety() -> None:
    composed = _composed()

    assert "governance hygiene" in composed.statement.casefold()
    assert "not safety" in composed.statement.casefold()
    assert "compromise state" in composed.statement.casefold()


def test_crypto_gov_prefix_collision_free() -> None:
    score = _score_record()

    assert score.id.startswith("cgs_")
    assert PREFIXES["cgs"] == "credential_governance_score"
    assert len([prefix for prefix in PREFIXES if prefix == "cgs"]) == 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_crypto_gov_store_contract(kind: str) -> None:
    async with _store(kind) as store:
        score = _score_record()

        assert await store.put_score(score) == score
        assert await store.put_score(score) == score
        assert await store.get_score(score.id, tenant_id=TENANT) == score
        assert await store.get_score(score.id, tenant_id=OTHER_TENANT) is None

        step = score.derivation.steps[0]
        tampered_step = step.model_copy(
            update={"output": {**step.output, "score": score.score - 1.0}},
            deep=True,
        )
        tampered = score.model_copy(
            update={
                "id": new_id("cgs"),
                "derivation": score.derivation.model_copy(
                    update={"steps": [tampered_step]},
                    deep=True,
                ),
            },
            deep=True,
        )
        with pytest.raises(CredentialGovernanceNotReplayable):
            await store.put_score(tampered)

        changed = score.model_copy(update={"statement": f"{score.statement} changed"})
        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put_score(changed)


async def test_crypto_gov_factory_owner_handoff_and_assess_wiring() -> None:
    runtime = create_inmemory_runtime(AQELYNConfig())
    source_id = new_id("src")
    fingerprint = f"hmac-sha256:{602:064x}"
    evidence = await runtime.evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=None,
            evidence_type="crypto_descriptor",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ActorRef(actor_type="system", actor_id="crypto-j2-test"),
            source_id=source_id,
            method="handed_in_descriptor",
            content={"fingerprint": fingerprint, "metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    [asset] = await runtime.secrets_engine.ingest_crypto_assets(
        [
            CryptographicKeyDescriptor(
                external_key_ref="urn:aqelyn:key:runtime-governance",
                fingerprint=fingerprint,
                algorithm="rsa",
                key_size=4096,
                usages=["signing"],
                last_rotated_at=NOW,
                source_id=source_id,
                observed_at=NOW,
                evidence_id=evidence.id,
            )
        ],
        [],
        tenant_id=None,
    )

    score = await runtime.secrets_engine.score_credential(asset.id, tenant_id=None)
    assessment = await runtime.secrets_engine.assess(tenant_id=None)

    assert await runtime.secrets_store.get_score(score.id, tenant_id=None) == score
    assert score.derivation.steps[0].params["ownership"] is None
    assert score.derivation.steps[0].params["mission"]["owner"] == "EA-0007"
    assert score.derivation.steps[0].params["compliance"]["snapshot_id"].startswith("snap_")
    assert assessment.governance_scoring_status == "complete"
    assert len(assessment.governance_score_ids) == assessment.assets_evaluated == 1
