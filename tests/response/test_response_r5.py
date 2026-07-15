"""R5 acceptance tests for recovery verification, evidence trail, and metrics."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, is_valid, new_id
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.findings import Automation, Finding, InMemoryFindingStore, Remediation
from aqelyn.policy import Decision, DecisionRequest
from aqelyn.response import (
    RECOVERY_FOLLOW_UP_ACTION,
    AutomationTrigger,
    CampaignStore,
    InMemoryCampaignStore,
    InMemoryTriggerStore,
    PostgresCampaignStore,
    PostgresTriggerStore,
    ResponseOrchestrationEngine,
    TriggerStore,
)
from aqelyn.workflow import (
    ActionEffect,
    ActionSpec,
    InMemoryActionRegistry,
    InMemoryRunStore,
    Playbook,
    PostgresRunStore,
    Run,
    RunStore,
    Step,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="response-r5-test")
NOW = datetime(2026, 7, 15, 21, 0, tzinfo=UTC)
INCIDENT_ID = "inc_018f0000000070008000000000005150"


@dataclass
class _ActionHandler:
    spec: ActionSpec
    executed: int = 0

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        return {"inputs": dict(inputs), "tenant_id": tenant_id, "key": idempotency_key}

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        return None


class _WorkflowSpy:
    def __init__(self, inner: WorkflowEngine) -> None:
        self._inner = inner
        self.propose_calls: list[str] = []
        self.execute_calls: list[str] = []

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run:
        self.propose_calls.append(playbook.id)
        return await self._inner.propose(playbook, by=by, source_finding=source_finding)

    async def execute(self, run_id: str, *, by: ActorRef) -> Run:
        self.execute_calls.append(run_id)
        return await self._inner.execute(run_id, by=by)

    async def halt(self, run_id: str, *, by: ActorRef, reason: str) -> Run:
        return await self._inner.halt(run_id, by=by, reason=reason)


class _Resolver:
    def __init__(self, playbooks: dict[str, Playbook]) -> None:
        self._playbooks = playbooks

    async def resolve_playbook(self, playbook_id: str, *, tenant_id: str | None) -> Playbook:
        return self._playbooks[playbook_id].model_copy(update={"tenant_id": tenant_id}, deep=True)


class _PolicyStub:
    def __init__(self, effect: str) -> None:
        self.effect = effect
        self.requests: list[DecisionRequest] = []

    async def authorize(self, request: DecisionRequest) -> Decision:
        self.requests.append(request)
        return Decision(effect=self.effect, matched_rules=["pol-r5"], reason=self.effect)


class _RecoveryAssessor:
    def __init__(self, checks: Sequence[Mapping[str, Any]]) -> None:
        self.checks = [dict(check) for check in checks]
        self.calls: list[str] = []

    async def assess_recovery(
        self,
        campaign: Any,
        *,
        by: ActorRef,
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append(campaign.id)
        return list(self.checks)


class _Incident:
    def __init__(self, created_at: datetime) -> None:
        self.created_at = created_at


class _IncidentReader:
    def __init__(self, incident: _Incident) -> None:
        self.incident = incident
        self.calls: list[str] = []

    async def get_incident(self, incident_id: str, *, tenant_id: str | None = None) -> _Incident:
        self.calls.append(incident_id)
        return self.incident


@dataclass
class _Harness:
    campaign_store: CampaignStore
    trigger_store: TriggerStore
    run_store: RunStore
    evidence_store: InMemoryEvidenceStore
    finding_store: InMemoryFindingStore
    workflow: _WorkflowSpy
    engine: ResponseOrchestrationEngine
    primary_handler: _ActionHandler
    recovery_handler: _ActionHandler
    assessor: _RecoveryAssessor


def _handler(action_type: str, effect: ActionEffect = "read_only") -> _ActionHandler:
    return _ActionHandler(
        ActionSpec(
            action_type=action_type,
            capability=f"capability:{action_type}",
            effect=effect,
            reversible=effect == "reversible",
            description=f"{effect} response R5 action",
        )
    )


def _playbook(playbook_id: str, action_type: str) -> Playbook:
    return Playbook(
        id=playbook_id,
        version=1,
        name=f"Playbook {playbook_id}",
        description="R5 response playbook.",
        steps=[
            Step(
                id=f"{playbook_id}-step",
                action_type=action_type,
                inputs={"target": "asset-1"},
                idempotency_key=f"{playbook_id}:once",
            )
        ],
    )


def _trigger() -> AutomationTrigger:
    return AutomationTrigger(
        tenant_id=None,
        name="Route response for approval",
        condition={"op": "eq", "attr": "finding.severity", "value": "high"},
        playbook_id="pb-triggered",
        max_effect="read_only",
        enabled=True,
    )


def _finding() -> Finding:
    return Finding(
        id=new_id("fnd"),
        tenant_id=None,
        finding_type="response-r5",
        schema_version=1,
        dedup_key=new_id("fnd"),
        title="R5 finding",
        severity="high",
        severity_score=8.0,
        what_happened="A condition requiring response was observed.",
        why_it_matters="Response should be coordinated and verified.",
        how_determined="Synthetic R5 fixture.",
        risk_of_inaction="Recovery could remain unverified.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=[new_id("obj")],
        remediation=Remediation(
            summary="Review response.",
            steps=["Run approved playbook", "Verify recovery"],
            difficulty="medium",
            expected_outcome="Recovery is confirmed.",
        ),
        automation=Automation(
            eligibility="automatic",
            action_ref="response.auto_start",
            requires_approval=False,
            risk_note="R5 fixture.",
        ),
        confidence=0.9,
        source_engine="response-r5-test",
        first_detected_at=NOW,
        last_detected_at=NOW,
    )


async def _postgres_campaign_store() -> PostgresCampaignStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresCampaignStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_campaign RESTART IDENTITY")
    return store


async def _postgres_trigger_store() -> PostgresTriggerStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresTriggerStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_trigger RESTART IDENTITY")
    return store


async def _postgres_run_store() -> PostgresRunStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRunStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
    return store


async def _harness(
    kind: str,
    *,
    checks: Sequence[Mapping[str, Any]],
    policy_effect: str = "permit",
    with_incident: bool = False,
) -> AsyncIterator[_Harness]:
    if kind == "inmemory":
        campaign_store: CampaignStore = InMemoryCampaignStore()
        trigger_store: TriggerStore = InMemoryTriggerStore()
        run_store: RunStore = InMemoryRunStore()
        close_campaign = close_trigger = close_run = False
    else:
        campaign_store = await _postgres_campaign_store()
        trigger_store = await _postgres_trigger_store()
        run_store = await _postgres_run_store()
        close_campaign = close_trigger = close_run = True

    primary = _handler("response.collect-context")
    recovery = _handler(RECOVERY_FOLLOW_UP_ACTION, "reversible")
    registry = InMemoryActionRegistry()
    registry.register(primary)
    registry.register(recovery)
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore()
    workflow = _WorkflowSpy(
        WorkflowEngine(
            store=run_store,
            registry=registry,
            evidence_store=evidence_store,
            granted_capabilities={primary.spec.capability, recovery.spec.capability},
        )
    )
    playbook = _playbook("pb-triggered", primary.spec.action_type)
    assessor = _RecoveryAssessor(checks)
    try:
        yield _Harness(
            campaign_store=campaign_store,
            trigger_store=trigger_store,
            run_store=run_store,
            evidence_store=evidence_store,
            finding_store=finding_store,
            workflow=workflow,
            engine=ResponseOrchestrationEngine(
                campaign_store=campaign_store,
                workflow=workflow,
                run_store=run_store,
                trigger_store=trigger_store,
                playbook_resolver=_Resolver({playbook.id: playbook}),
                policy_authorizer=_PolicyStub(policy_effect),
                evidence_store=evidence_store,
                finding_store=finding_store,
                recovery_assessor=assessor,
                incident_reader=(
                    _IncidentReader(_Incident(NOW - timedelta(minutes=20)))
                    if with_incident
                    else None
                ),
            ),
            primary_handler=primary,
            recovery_handler=recovery,
            assessor=assessor,
        )
    finally:
        if close_campaign and isinstance(campaign_store, PostgresCampaignStore):
            await campaign_store.close()
        if close_trigger and isinstance(trigger_store, PostgresTriggerStore):
            await trigger_store.close()
        if close_run and isinstance(run_store, PostgresRunStore):
            await run_store.close()


async def _plan_contain_campaign(harness: _Harness, *, incident_id: str | None = None) -> str:
    campaign = await harness.engine.plan_campaign(
        incident_id=incident_id,
        tenant_id=None,
        playbooks=[
            {
                "playbook": _playbook("pb-contain", harness.primary_handler.spec.action_type),
                "phase": "contain",
                "effect": "read_only",
            }
        ],
        by=SYS,
        source_finding=_finding(),
    )
    return campaign.id


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_recovery_verify(kind: str) -> None:
    checks = [{"id": "restore-baseline", "asset_id": new_id("obj"), "verified": False}]
    async for harness in _harness(kind, checks=checks):
        campaign_id = await _plan_contain_campaign(harness)

        verification = await harness.engine.verify_recovery(campaign_id, by=SYS)

        assert not verification.verified
        assert is_valid(verification.reopened_finding_id or "", "fnd")
        assert harness.assessor.calls == [campaign_id]
        assert len(harness.workflow.propose_calls) == 2
        assert harness.workflow.propose_calls[1].startswith("response-follow-up-")
        assert harness.workflow.execute_calls == []
        assert harness.primary_handler.executed == 0
        assert harness.recovery_handler.executed == 0
        loaded = await harness.campaign_store.get(campaign_id)
        assert loaded is not None
        assert len(loaded.evidence_ids) >= 2


async def test_resp_evidence_trail() -> None:
    checks = [{"id": "restore-baseline", "verified": True}]
    async for harness in _harness("inmemory", checks=checks, policy_effect="deny"):
        await harness.trigger_store.put(_trigger())
        started = await harness.engine.evaluate_triggers(
            tenant_id=None,
            findings=[_finding()],
            by=SYS,
        )
        assert started == []
        campaigns = await harness.campaign_store.query(tenant_id=None)
        assert len(campaigns) == 1

        verification = await harness.engine.verify_recovery(campaigns[0].id, by=SYS)
        assert verification.verified

        loaded = await harness.campaign_store.get(campaigns[0].id)
        assert loaded is not None
        records = [
            await harness.evidence_store.get(evidence_id, actor=SYS)
            for evidence_id in loaded.evidence_ids
        ]
        kinds = {record.labels["kind"] for record in records}
        assert {
            "campaign_planned",
            "trigger_fired",
            "approval_routed",
            "recovery_verification",
        } <= kinds
        assert all(record.content is not None for record in records)
        assert all(
            record.content and record.content["campaign_id"] == loaded.id for record in records
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_metrics(kind: str) -> None:
    checks = [{"id": "restore-baseline", "verified": True}]
    async for harness in _harness(kind, checks=checks, with_incident=True):
        campaign_id = await _plan_contain_campaign(harness, incident_id=INCIDENT_ID)
        campaign = await harness.campaign_store.get(campaign_id)
        assert campaign is not None
        await harness.engine.advance(campaign.id, by=SYS, expected_version=campaign.version)
        before_campaigns = [
            item.model_dump(mode="json")
            for item in await harness.campaign_store.query(tenant_id=None)
        ]
        before_runs = [item.model_dump(mode="json") for item in await harness.run_store.list()]

        metrics = await harness.engine.metrics(
            tenant_id=None,
            since=NOW - timedelta(days=1),
        )

        assert metrics.campaigns == 1
        assert metrics.mttd_seconds is not None
        assert metrics.mttd_seconds >= 0.0
        assert metrics.mttr_seconds is not None
        assert metrics.mttr_seconds >= 0.0
        assert metrics.containment_seconds is not None
        assert metrics.containment_seconds >= 0.0
        assert metrics.automated_pct == 100.0
        after_campaigns = [
            item.model_dump(mode="json")
            for item in await harness.campaign_store.query(tenant_id=None)
        ]
        after_runs = [item.model_dump(mode="json") for item in await harness.run_store.list()]
        assert after_campaigns == before_campaigns
        assert after_runs == before_runs
