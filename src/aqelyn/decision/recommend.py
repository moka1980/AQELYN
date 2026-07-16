"""Recommendation engine for AI Decision Intelligence (EA-0020 E3)."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import DecisionConfigInvalid, RecommendationNotFound
from aqelyn.decision.derive import build_derivation, explain, replay
from aqelyn.decision.learning import build_learning_record, proposed_model_params
from aqelyn.decision.models import (
    VALID_DECISIONS,
    ClaimRef,
    DecisionConfig,
    DecisionRecord,
    Derivation,
    DerivationStep,
    LearningRecord,
    ModelVersion,
    Recommendation,
    SimilarityHit,
)
from aqelyn.decision.similarity import CaseCorpus
from aqelyn.decision.similarity import similar_cases as compute_similar_cases
from aqelyn.decision.store import ModelVersionStore, RecommendationStore, validate_limit
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Finding
from aqelyn.trust import TrustAssessment, TrustEngine
from aqelyn.workflow import Playbook, Run, Step

_ENGINE_VERSION = "decision-e3/v1"
_SYSTEM_ACTOR = ActorRef(actor_type="system", actor_id="decision-engine")


class ClaimSource(Protocol):
    async def claims_for(
        self, *, subject_ref: str, tenant_id: str | None
    ) -> Sequence[ClaimRef]: ...


class TrustAssessor(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class DecisionIntelligenceEngine:
    def __init__(
        self,
        recommendation_store: RecommendationStore,
        model_store: ModelVersionStore,
        *,
        claim_source: ClaimSource,
        evidence_store: EvidenceStore,
        trust_engine: TrustAssessor | None = None,
        workflow_engine: WorkflowProposer | None = None,
        config: DecisionConfig | None = None,
        case_corpus: CaseCorpus | None = None,
        source_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.recommendation_store = recommendation_store
        self.model_store = model_store
        self.claim_source = claim_source
        self.evidence_store = evidence_store
        self.trust_engine = trust_engine or TrustEngine()
        self.workflow_engine = workflow_engine
        self.config = config or DecisionConfig()
        self.case_corpus = case_corpus or {}
        self.source_id = source_id or new_id("src")
        self._clock = clock or utc_now
        self._decisions: dict[str, DecisionRecord] = {}
        self._learning: dict[str, LearningRecord] = {}

    async def recommend(self, *, subject_ref: str, tenant_id: str | None) -> list[Recommendation]:
        _validate_subject_ref(subject_ref)
        active_model = await self.model_store.active(tenant_id=tenant_id)
        claims = await self._claims(subject_ref=subject_ref, tenant_id=tenant_id)
        if not claims:
            return []
        evidence = await self._evidence_for_claims(claims)
        assessed_at = self._clock()
        assessment = await self.trust_engine.assess(subject_ref, evidence, now=assessed_at)
        derivation = self._derivation(
            claims=claims,
            model_version=active_model.version,
            model_params=active_model.params,
            confidence=assessment.score,
            subject_ref=subject_ref,
        )
        if int(derivation.result.get("count", 0)) < 1:
            return []
        recommendation = Recommendation(
            tenant_id=tenant_id,
            subject_ref=subject_ref,
            statement=_statement(subject_ref=subject_ref, derivation_result=derivation.result),
            action_hint={
                "action_type": "decision.review",
                "subject_ref": subject_ref,
                "claim_count": len(claims),
            },
            confidence=assessment.score,
            derivation=derivation,
            created_at=assessed_at,
        )
        return [await self.recommendation_store.put(recommendation)]

    async def record_decision(
        self,
        rec_id: str,
        *,
        decision: str,
        by: ActorRef,
        reason: str,
        propose_run: bool = False,
    ) -> DecisionRecord:
        _validate_decision(decision)
        _validate_reason(reason)
        recommendation = await self.recommendation_store.get(rec_id)
        if recommendation is None:
            raise RecommendationNotFound(rec_id)
        at = self._clock()
        run_id: str | None = None
        if propose_run:
            if self.workflow_engine is None:
                raise DecisionConfigInvalid("workflow_engine is required to propose a run")
            run = await self.workflow_engine.propose(
                _playbook_for_decision(recommendation),
                by=by,
                source_finding=None,
            )
            run_id = run.id
        evidence = await self._record_decision_evidence(
            recommendation,
            decision=decision,
            by=by,
            reason=reason,
            proposed_run_id=run_id,
            at=at,
        )
        record = DecisionRecord(
            recommendation_id=recommendation.id,
            decision=decision,
            decided_by=by,
            reason=reason,
            at=at,
            workflow_run_id=run_id,
            evidence_id=evidence.id,
        )
        self._decisions[record.id] = record.model_copy(deep=True)
        return copy.deepcopy(record)

    async def similar_cases(self, case_id: str, *, limit: int = 5) -> list[SimilarityHit]:
        return compute_similar_cases(case_id, self.case_corpus, limit=limit)

    async def record_feedback(
        self,
        rec_id: str,
        *,
        feedback: str,
        by: ActorRef,
    ) -> LearningRecord:
        recommendation = await self.recommendation_store.get(rec_id)
        if recommendation is None:
            raise RecommendationNotFound(rec_id)
        record = build_learning_record(
            recommendation,
            feedback=feedback,
            by=by,
            at=self._clock(),
        )
        self._learning[record.id] = record.model_copy(deep=True)
        return copy.deepcopy(record)

    async def propose_model_version(
        self,
        *,
        from_learning: Sequence[str],
        by: ActorRef,
        tenant_id: str | None = None,
    ) -> ModelVersion:
        records = self._learning_records(from_learning)
        selected_tenant = await self._learning_tenant(records, tenant_id=tenant_id)
        active_model = await self.model_store.active(tenant_id=selected_tenant)
        proposed = ModelVersion(
            version=active_model.version + 1,
            params=proposed_model_params(active_model, records, by=by),
        )
        return await self.model_store.put(proposed, tenant_id=selected_tenant)

    async def promote(
        self,
        version: int,
        *,
        by: ActorRef,
        reason: str,
        evidence_id: str,
        tenant_id: str | None = None,
    ) -> ModelVersion:
        return await self.model_store.promote(
            version,
            by=by,
            reason=reason,
            evidence_id=evidence_id,
            tenant_id=tenant_id,
        )

    def explain(self, recommendation: Recommendation) -> dict[str, object]:
        return explain(recommendation)

    async def replay(self, recommendation: Recommendation) -> dict[str, object]:
        return replay(recommendation.derivation)

    def _learning_records(self, learning_ids: Sequence[str]) -> list[LearningRecord]:
        if not learning_ids:
            raise DecisionConfigInvalid("from_learning must not be empty")
        records: list[LearningRecord] = []
        seen: set[str] = set()
        for learning_id in learning_ids:
            if learning_id in seen:
                raise DecisionConfigInvalid("from_learning must not contain duplicates")
            seen.add(learning_id)
            record = self._learning.get(learning_id)
            if record is None:
                raise DecisionConfigInvalid(f"unknown learning record: {learning_id}")
            records.append(record.model_copy(deep=True))
        return records

    async def _learning_tenant(
        self, records: Sequence[LearningRecord], *, tenant_id: str | None
    ) -> str | None:
        tenants: set[str | None] = set()
        for record in records:
            recommendation = await self.recommendation_store.get(record.recommendation_id)
            if recommendation is None:
                raise RecommendationNotFound(record.recommendation_id)
            tenants.add(recommendation.tenant_id)
        if len(tenants) != 1:
            raise DecisionConfigInvalid("learning records must belong to one tenant")
        selected = next(iter(tenants))
        if tenant_id is not None and tenant_id != selected:
            raise DecisionConfigInvalid("learning tenant does not match requested tenant")
        return selected

    async def _claims(self, *, subject_ref: str, tenant_id: str | None) -> list[ClaimRef]:
        raw_claims = await self.claim_source.claims_for(
            subject_ref=subject_ref,
            tenant_id=tenant_id,
        )
        selected = [ClaimRef.model_validate(claim.model_dump(mode="json")) for claim in raw_claims]
        selected.sort(key=lambda claim: (claim.kind, claim.ref_id, claim.evidence_id or ""))
        if len(selected) > self.config.batch_size:
            selected = selected[: self.config.batch_size]
        for claim in selected:
            if claim.evidence_id is None:
                raise DecisionConfigInvalid("claim inputs must cite evidence")
        return selected

    async def _evidence_for_claims(self, claims: Sequence[ClaimRef]) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        for claim in claims:
            assert claim.evidence_id is not None
            records.append(await self.evidence_store.get(claim.evidence_id, actor=_SYSTEM_ACTOR))
        records.sort(key=lambda record: record.id)
        return records

    def _derivation(
        self,
        *,
        claims: Sequence[ClaimRef],
        model_version: int,
        model_params: Mapping[str, object],
        confidence: float,
        subject_ref: str,
    ) -> Derivation:
        _require_step_budget(self.config.max_steps)
        claim_payloads = [claim.model_dump(mode="json") for claim in claims]
        selected = {"claims": claim_payloads, "count": len(claim_payloads)}
        weighted_items = [
            {**claim.model_dump(mode="json"), "weight": confidence} for claim in claims
        ]
        weighted = {"items": weighted_items}
        mission_factor = _unit_param(model_params, "mission_factor", default=1.0)
        mission_weighted_items = [
            {**item, "score": _clamp_unit(float(item["weight"]) * mission_factor)}
            for item in weighted_items
        ]
        mission_weighted = {"items": mission_weighted_items, "factor": mission_factor}
        limit = _int_param(model_params, "limit", default=max(len(claims), 1))
        ranked_items = sorted(
            mission_weighted_items,
            key=lambda item: (-float(item["score"]), str(item["ref_id"])),
        )[:limit]
        ranked = {"items": ranked_items, "count": min(limit, len(mission_weighted_items))}
        min_confidence = _unit_param(
            model_params, "min_confidence", default=self.config.min_confidence
        )
        final_items = [item for item in ranked_items if float(item["score"]) >= min_confidence]
        thresholded = {
            "items": final_items,
            "count": len(final_items),
            "min_score": min_confidence,
        }
        steps = [
            DerivationStep(
                seq=1,
                op="select_claims",
                input_refs=[claim.ref_id for claim in claims],
                params={"kinds": sorted({claim.kind for claim in claims})},
                output=selected,
                note="Select cited platform claims.",
            ),
            DerivationStep(
                seq=2,
                op="weigh",
                input_refs=["step:1"],
                params={"weight_field": "confidence", "default": confidence},
                output=weighted,
                note="Apply Trust confidence as claim weight.",
            ),
            DerivationStep(
                seq=3,
                op="mission_weight",
                input_refs=["step:2"],
                params={"factor": mission_factor},
                output=mission_weighted,
                note="Apply configured mission weighting.",
            ),
            DerivationStep(
                seq=4,
                op="rank",
                input_refs=["step:3"],
                params={"score_field": "score", "limit": limit},
                output=ranked,
                note="Rank claims by deterministic score.",
            ),
            DerivationStep(
                seq=5,
                op="threshold",
                input_refs=["step:4"],
                params={"score_field": "score", "min_score": min_confidence},
                output=thresholded,
                note="Keep claims meeting the confidence threshold.",
            ),
        ]
        derivation = build_derivation(
            inputs=list(claims),
            steps=steps,
            model_version=model_version,
            engine_version=_ENGINE_VERSION,
            max_steps=self.config.max_steps,
        )
        _validate_subject_ref(subject_ref)
        return derivation

    async def _record_decision_evidence(
        self,
        recommendation: Recommendation,
        *,
        decision: str,
        by: ActorRef,
        reason: str,
        proposed_run_id: str | None,
        at: datetime,
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            id="",
            tenant_id=recommendation.tenant_id,
            evidence_type="decision.record",
            schema_version=1,
            subject=Subject(),
            collected_at=at,
            recorded_at=at,
            collector=by,
            source_id=self.source_id,
            method="decision.record/v1",
            content={
                "recommendation_id": recommendation.id,
                "subject_ref": recommendation.subject_ref,
                "decision": decision,
                "reason": reason,
                "proposed_run_id": proposed_run_id,
                "actor": by.model_dump(mode="json"),
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0020", "kind": "decision_record"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self.evidence_store.add(record)


def _require_step_budget(max_steps: int) -> None:
    if max_steps < 5:
        raise DecisionConfigInvalid("max_steps must allow the E3 recommendation derivation")


def _statement(*, subject_ref: str, derivation_result: Mapping[str, object]) -> str:
    raw_count = derivation_result.get("count", 0)
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raise DecisionConfigInvalid("derivation result count must be an integer")
    count = raw_count
    noun = "claim" if count == 1 else "claims"
    return f"Review {count} cited {noun} for {subject_ref}."


def _playbook_for_decision(recommendation: Recommendation) -> Playbook:
    action_type = "decision.review"
    if recommendation.action_hint is not None:
        selected = recommendation.action_hint.get("action_type")
        if isinstance(selected, str) and selected.strip():
            action_type = selected
    return Playbook(
        id=f"decision-{recommendation.id}",
        version=1,
        name="Decision recommendation follow-up",
        description="Proposed follow-up for an analyst decision.",
        tenant_id=recommendation.tenant_id,
        steps=[
            Step(
                id="follow_up",
                action_type=action_type,
                inputs={
                    "recommendation_id": recommendation.id,
                    "subject_ref": recommendation.subject_ref,
                    "statement": recommendation.statement,
                },
                idempotency_key=f"decision:{recommendation.id}:follow_up",
                requires_approval=True,
            )
        ],
    )


def _validate_subject_ref(value: str) -> str:
    if not value.strip():
        raise DecisionConfigInvalid("subject_ref must not be empty")
    return value


def _validate_decision(value: str) -> str:
    if value not in VALID_DECISIONS:
        raise DecisionConfigInvalid(f"unknown decision: {value!r}")
    return value


def _validate_reason(value: str) -> str:
    if not value.strip():
        raise DecisionConfigInvalid("decision reason must not be empty")
    return value


def _unit_param(params: Mapping[str, object], name: str, *, default: float) -> float:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise DecisionConfigInvalid(f"{name} must be numeric")
    value = float(raw)
    if value < 0.0 or value > 1.0:
        raise DecisionConfigInvalid(f"{name} must be in [0,1]")
    return value


def _int_param(params: Mapping[str, object], name: str, *, default: int) -> int:
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise DecisionConfigInvalid(f"{name} must be >= 1")
    validate_limit(raw)
    return raw


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))
