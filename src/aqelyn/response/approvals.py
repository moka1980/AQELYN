"""Approval routing helpers for response orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from aqelyn.conventions import ActorRef

from .models import ApprovalRequest


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_approval_request(
    *,
    workflow_run_id: str,
    step_ids: Sequence[str],
    routed_to: ActorRef | str,
    tenant_id: str | None,
    sla_seconds: int,
    escalate_to: ActorRef | str | None,
    requested_at: datetime | None = None,
) -> ApprovalRequest:
    return ApprovalRequest(
        tenant_id=tenant_id,
        workflow_run_id=workflow_run_id,
        step_ids=list(step_ids),
        routed_to=routed_to,
        sla_seconds=sla_seconds,
        escalate_to=escalate_to,
        requested_at=requested_at or utc_now(),
    )


def request_is_overdue(request: ApprovalRequest, *, now: datetime | None = None) -> bool:
    checked_at = now or utc_now()
    due_at = request.requested_at + timedelta(seconds=request.sla_seconds)
    return checked_at >= due_at


def escalate_request(request: ApprovalRequest) -> ApprovalRequest:
    if request.escalate_to is None:
        return request.model_copy(update={"status": "expired"}, deep=True)
    return request.model_copy(
        update={"status": "escalated", "routed_to": request.escalate_to},
        deep=True,
    )
