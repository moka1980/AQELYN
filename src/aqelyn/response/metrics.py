"""Read-only response orchestration metrics."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.response.models import Phase, ResponseCampaign, ResponseMetrics
from aqelyn.response.store import CampaignStore
from aqelyn.workflow import Run


class MetricsRunReader(Protocol):
    async def get(self, run_id: str, *, tenant_id: str | None = None) -> Run | None: ...


class IncidentLike(Protocol):
    created_at: datetime


class IncidentReader(Protocol):
    async def get_incident(
        self,
        incident_id: str,
        *,
        tenant_id: str | None = None,
    ) -> IncidentLike | None: ...


async def compute_metrics(
    *,
    campaign_store: CampaignStore,
    run_store: MetricsRunReader | None,
    incident_reader: IncidentReader | None,
    tenant_id: str | None,
    since: datetime,
    limit: int,
) -> ResponseMetrics:
    campaigns = [
        campaign
        for campaign in await campaign_store.query(tenant_id=tenant_id, status=None, limit=limit)
        if campaign.updated_at >= since
    ]
    mttr_values = [
        (campaign.updated_at - campaign.created_at).total_seconds()
        for campaign in campaigns
        if campaign.status == "completed"
    ]
    containment_values = (
        []
        if run_store is None
        else [
            value
            for campaign in campaigns
            for value in [await _containment_seconds(campaign, run_store)]
            if value is not None
        ]
    )
    mttd_values = (
        []
        if incident_reader is None
        else [
            value
            for campaign in campaigns
            for value in [await _mttd_seconds(campaign, incident_reader)]
            if value is not None
        ]
    )
    return ResponseMetrics(
        window={"since": since.isoformat(), "tenant_id": tenant_id, "limit": limit},
        mttd_seconds=_mean_or_none(mttd_values),
        mttr_seconds=_mean_or_none(mttr_values),
        containment_seconds=_mean_or_none(containment_values),
        campaigns=len(campaigns),
        automated_pct=_automated_pct(campaigns),
    )


async def _containment_seconds(
    campaign: ResponseCampaign,
    run_store: MetricsRunReader,
) -> float | None:
    contain = _phase(campaign.phases, "contain")
    if contain is None:
        return None
    completed: list[datetime] = []
    for ref in contain.run_refs:
        run = await run_store.get(ref.workflow_run_id, tenant_id=campaign.tenant_id)
        if run is not None and run.status == "completed":
            completed.append(run.updated_at)
    if not completed:
        return None
    return (max(completed) - campaign.created_at).total_seconds()


async def _mttd_seconds(
    campaign: ResponseCampaign,
    incident_reader: IncidentReader,
) -> float | None:
    if campaign.incident_id is None:
        return None
    incident = await incident_reader.get_incident(
        campaign.incident_id,
        tenant_id=campaign.tenant_id,
    )
    if incident is None:
        return None
    return max(0.0, (campaign.created_at - incident.created_at).total_seconds())


def _phase(phases: Sequence[Phase], name: str) -> Phase | None:
    return next((phase for phase in phases if phase.name == name), None)


def _mean_or_none(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _automated_pct(campaigns: Sequence[ResponseCampaign]) -> float:
    if not campaigns:
        return 0.0
    automated = sum(1 for campaign in campaigns if campaign.source_finding_id is not None)
    return (automated / len(campaigns)) * 100.0
