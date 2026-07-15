"""R1 acceptance tests for Response Orchestration types and config."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, is_valid, new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, ResponseConfigInvalid, SchemaValidationError
from aqelyn.response import (
    ApprovalRequest,
    AutomationTrigger,
    Phase,
    RecoveryVerification,
    ResponseCampaign,
    ResponseConfig,
    ResponseMetrics,
    RunRef,
)

TENANT = "018f0000-0000-7000-8000-000000000018"
NOW = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="analyst@example.com")


def test_resp_tenant_version_config() -> None:
    run_ref = RunRef(
        workflow_run_id=new_id("run"),
        action_type="contain-host",
        effect="reversible",
        status="proposed",
    )
    campaign = ResponseCampaign(
        tenant_id=TENANT,
        incident_id=new_id("inc"),
        source_finding_id=new_id("fnd"),
        phases=[
            Phase(name="contain", order=1, run_refs=[run_ref]),
            Phase(name="remediate", order=2, depends_on=["contain"]),
            Phase(name="recover", order=3, depends_on=["remediate"]),
        ],
        created_by=ACTOR,
        created_at=NOW,
        updated_at=NOW,
        evidence_ids=[new_id("evd")],
        version=1,
    )
    trigger = AutomationTrigger(
        tenant_id=TENANT,
        name="Auto-start reversible containment",
        condition={"op": "eq", "attr": "finding.automation.eligibility", "value": "automatic"},
        playbook_id="pb-contain-host",
        max_effect="reversible",
        version=2,
    )
    approval = ApprovalRequest(
        tenant_id=TENANT,
        workflow_run_id=run_ref.workflow_run_id,
        step_ids=["step-1"],
        routed_to="soc-duty-manager",
        sla_seconds=900,
        requested_at=NOW,
    )
    verification = RecoveryVerification(
        campaign_id=campaign.id,
        checks=[{"engine": "assetconfig", "status": "restored"}],
        verified=True,
        reason="Baseline compliance restored.",
    )
    metrics = ResponseMetrics(
        window={"since": NOW.isoformat()},
        mttd_seconds=30.0,
        mttr_seconds=900.0,
        containment_seconds=120.0,
        campaigns=1,
        automated_pct=0.0,
    )

    assert is_valid(campaign.id, "rsp")
    assert is_valid(trigger.id, "trg")
    assert is_valid(approval.id, "apr")
    assert campaign.tenant_id == TENANT
    assert trigger.version == 2
    assert verification.verified is True
    assert metrics.mttr_seconds == 900.0
    assert ResponseConfig().phase_order == ("contain", "remediate", "recover")

    with pytest.raises(SchemaValidationError, match="tenant_id"):
        ResponseCampaign(
            tenant_id="not-a-uuid",
            phases=[Phase(name="contain", order=1)],
            created_by=ACTOR,
            created_at=NOW,
            updated_at=NOW,
        )
    with pytest.raises(ResponseConfigInvalid, match="campaign version"):
        ResponseCampaign(
            tenant_id=TENANT,
            phases=[Phase(name="contain", order=1)],
            created_by=ACTOR,
            created_at=NOW,
            updated_at=NOW,
            version=0,
        )
    with pytest.raises(ResponseConfigInvalid, match="phase_order"):
        ResponseConfig(phase_order=("contain", "contain"))
    with pytest.raises(ResponseConfigInvalid, match="batch_size"):
        ResponseConfig(batch_size=0)

    assert "ResponseConfigInvalid" in ALL_ERROR_CODES
    assert "CampaignNotFound" in ALL_ERROR_CODES
    assert "TriggerNotFound" in ALL_ERROR_CODES
    assert "PhaseBlocked" in ALL_ERROR_CODES


def test_resp_no_auto_destructive() -> None:
    assert (
        AutomationTrigger(
            tenant_id=TENANT,
            name="Read-only trigger",
            condition={"op": "exists", "attr": "finding.id"},
            playbook_id="pb-gather-context",
            max_effect="read_only",
        ).max_effect
        == "read_only"
    )

    assert (
        AutomationTrigger(
            tenant_id=TENANT,
            name="Reversible trigger",
            condition={"op": "exists", "attr": "finding.id"},
            playbook_id="pb-isolate-host",
            max_effect="reversible",
        ).max_effect
        == "reversible"
    )

    with pytest.raises(ResponseConfigInvalid, match="max_effect"):
        AutomationTrigger(
            tenant_id=TENANT,
            name="Never auto destructive",
            condition={"op": "exists", "attr": "finding.id"},
            playbook_id="pb-destroy-host",
            max_effect="destructive",
        )

    with pytest.raises(ResponseConfigInvalid, match="unsupported fields"):
        AutomationTrigger(
            tenant_id=TENANT,
            name="Structured predicates only",
            condition={"script": "return true"},
            playbook_id="pb-gather-context",
            max_effect="read_only",
        )
