"""Recovery verification helpers for response orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.response.models import RecoveryVerification, ResponseCampaign
from aqelyn.workflow import Playbook, Step

RECOVERY_FOLLOW_UP_ACTION = "response.recovery.follow_up"


class RecoveryAssessor(Protocol):
    async def assess_recovery(
        self,
        campaign: ResponseCampaign,
        *,
        by: ActorRef,
    ) -> Sequence[Mapping[str, Any]]: ...


def normalize_checks(checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(check) for check in checks]


def checks_verified(checks: Sequence[Mapping[str, Any]]) -> bool:
    return bool(checks) and all(_check_verified(check) for check in checks)


def recovery_reason(checks: Sequence[Mapping[str, Any]], *, verified: bool) -> str:
    if verified:
        return "Recovery verification passed; all checks reported restored state."
    if not checks:
        return "Recovery verification could not prove restored state; no checks were returned."
    failed = [
        str(check.get("name", check.get("id", "unnamed-check")))
        for check in checks
        if not _check_verified(check)
    ]
    return f"Recovery verification failed for: {', '.join(failed)}."


def verification_result(
    campaign: ResponseCampaign,
    checks: Sequence[Mapping[str, Any]],
    *,
    reopened_finding_id: str | None = None,
) -> RecoveryVerification:
    normalized = normalize_checks(checks)
    verified = checks_verified(normalized)
    return RecoveryVerification(
        campaign_id=campaign.id,
        checks=normalized,
        verified=verified,
        reopened_finding_id=reopened_finding_id,
        reason=recovery_reason(normalized, verified=verified),
    )


def recovery_finding(
    campaign: ResponseCampaign,
    verification: RecoveryVerification,
    *,
    evidence_id: str,
) -> Finding:
    now = utc_now()
    affected_ids = _affected_object_ids(verification.checks)
    return Finding(
        id="",
        tenant_id=campaign.tenant_id,
        finding_type="response.recovery_unverified",
        schema_version=1,
        dedup_key=f"response.recovery_unverified:{campaign.id}",
        title="Recovery verification did not confirm restored state",
        severity="high",
        severity_score=75.0,
        status="open",
        what_happened=verification.reason,
        why_it_matters=(
            "A response campaign is not complete until the affected state is re-checked "
            "and proven restored."
        ),
        how_determined=(
            "The Response Orchestration Engine re-ran the configured governance recovery "
            "assessment and recorded the check results as evidence."
        ),
        risk_of_inaction=(
            "Leaving recovery unverified can allow the original exposure or access issue "
            "to remain unresolved."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=affected_ids,
        expert_details={
            "campaign_id": campaign.id,
            "incident_id": campaign.incident_id,
            "checks": verification.checks,
        },
        remediation=Remediation(
            summary="Review failed recovery checks and run an approved follow-up workflow.",
            steps=[
                "Inspect each failed recovery check and its evidence.",
                "Confirm the intended restored state.",
                "Approve and run the proposed follow-up workflow if remediation is required.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="Recovery is verified by a passing governance assessment.",
            references=["EA-0018", "EA-0008"],
        ),
        automation=Automation(
            eligibility="assisted",
            action_ref=RECOVERY_FOLLOW_UP_ACTION,
            requires_approval=True,
            risk_note=(
                "Recovery follow-up is proposed through Workflow; this engine never forces a fix."
            ),
        ),
        confidence=1.0,
        source_engine="response_engine",
        correlation_id=campaign.id,
        first_detected_at=now,
        last_detected_at=now,
    )


def follow_up_playbook(campaign: ResponseCampaign, finding: Finding) -> Playbook:
    step_id = f"follow-up-{_slug(campaign.id)}"
    return Playbook(
        id=f"response-follow-up-{_slug(campaign.id)}-{_slug(finding.id)}",
        version=1,
        name=f"Verify and remediate recovery gap for {campaign.id}",
        description="Proposed follow-up for an unverified response recovery check.",
        tenant_id=campaign.tenant_id,
        steps=[
            Step(
                id=step_id,
                action_type=RECOVERY_FOLLOW_UP_ACTION,
                inputs={
                    "campaign_id": campaign.id,
                    "finding_id": finding.id,
                    "incident_id": campaign.incident_id,
                    "evidence_ids": list(finding.evidence_ids),
                },
                idempotency_key=f"response:{campaign.id}:{finding.id}:recovery-follow-up",
                requires_approval=True,
            )
        ],
    )


def _check_verified(check: Mapping[str, Any]) -> bool:
    if isinstance(check.get("verified"), bool):
        return bool(check["verified"])
    if isinstance(check.get("ok"), bool):
        return bool(check["ok"])
    status = check.get("status")
    return status in {"pass", "passed", "verified", "ok"}


def _affected_object_ids(checks: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for check in checks:
        for key in ("object_id", "asset_id", "identity_id", "account_id"):
            value = check.get(key)
            if isinstance(value, str) and value.startswith("obj_") and value not in out:
                out.append(value)
    return out


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-") or "id"
