"""Trigger evaluation helpers for response orchestration."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import ActorRef
from aqelyn.findings import Finding
from aqelyn.policy.interpreter import condition_matches
from aqelyn.policy.models import Decision, DecisionRequest, DecisionResource
from aqelyn.workflow.models import Playbook

from .models import AutomationTrigger


class PlaybookResolver(Protocol):
    async def resolve_playbook(self, playbook_id: str, *, tenant_id: str | None) -> Playbook: ...


class PolicyAuthorizer(Protocol):
    async def authorize(self, request: DecisionRequest) -> Decision: ...


def trigger_matches(trigger: AutomationTrigger, finding: Finding) -> bool:
    payload: dict[str, object] = {
        "finding": finding.model_dump(mode="json"),
        "trigger": trigger.model_dump(mode="json"),
    }
    return condition_matches(trigger.condition, payload)


def build_trigger_decision_request(
    *,
    trigger: AutomationTrigger,
    finding: Finding,
    actor: ActorRef,
) -> DecisionRequest:
    return DecisionRequest(
        subject=actor,
        action="response.auto_start",
        resource=DecisionResource(
            id=finding.id,
            type="finding",
            tenant_id=finding.tenant_id,
            attributes={
                "trigger_id": trigger.id,
                "playbook_id": trigger.playbook_id,
                "max_effect": trigger.max_effect,
                "automation_eligibility": finding.automation.eligibility,
                "requires_approval": finding.automation.requires_approval,
            },
        ),
        context={
            "trigger_id": trigger.id,
            "playbook_id": trigger.playbook_id,
            "finding_id": finding.id,
        },
    )


def can_auto_start(
    *,
    trigger: AutomationTrigger,
    finding: Finding,
    decision: Decision | None,
) -> bool:
    return (
        trigger.max_effect in {"read_only", "reversible"}
        and finding.automation.eligibility == "automatic"
        and not finding.automation.requires_approval
        and decision is not None
        and decision.effect == "permit"
    )
