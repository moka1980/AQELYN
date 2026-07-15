"""In-memory Response Orchestration stores (EA-0018 R2)."""

from __future__ import annotations

import copy
from collections.abc import Sequence

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    TenantScopeRequired,
)
from aqelyn.response.models import AutomationTrigger, ResponseCampaign
from aqelyn.response.store import (
    normalize_campaign_status_filter,
    validate_campaign,
    validate_campaign_id,
    validate_positive,
    validate_tenant,
    validate_trigger,
    validate_trigger_id,
)


class InMemoryCampaignStore:
    def __init__(self, *, mode: str = "local") -> None:
        self._campaigns: dict[str, ResponseCampaign] = {}
        self.mode = mode

    async def upsert(self, campaign: ResponseCampaign) -> ResponseCampaign:
        stored = validate_campaign(campaign)
        if not stored.id:
            stored.id = new_id("rsp")
        validate_campaign_id(stored.id, field="id")
        existing = self._campaigns.get(stored.id)
        if existing is None:
            created = stored.model_copy(update={"version": 1}, deep=True)
            self._campaigns[created.id] = created
            return copy.deepcopy(created)

        if existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("campaign tenant_id cannot change")
        validate_positive(stored.version, field="version")
        if existing.version != stored.version:
            raise OptimisticConcurrencyConflict(
                f"expected v{stored.version}, found v{existing.version}"
            )
        updated = stored.model_copy(
            update={
                "created_at": existing.created_at,
                "updated_at": max(utc_now(), existing.updated_at, stored.updated_at),
                "version": existing.version + 1,
            },
            deep=True,
        )
        self._campaigns[updated.id] = updated
        return copy.deepcopy(updated)

    async def get(
        self,
        campaign_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ResponseCampaign | None:
        validate_campaign_id(campaign_id)
        tenant_id = validate_tenant(tenant_id)
        campaign = self._campaigns.get(campaign_id)
        if campaign is None or not self._visible(campaign, tenant_id):
            return None
        return copy.deepcopy(campaign)

    async def query(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[ResponseCampaign]:
        tenant_id = validate_tenant(tenant_id)
        statuses = normalize_campaign_status_filter(status)
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("campaign query must be tenant-scoped in enterprise mode")
        rows = [
            copy.deepcopy(campaign)
            for campaign in self._campaigns.values()
            if self._visible(campaign, tenant_id)
            and (statuses is None or campaign.status in statuses)
        ]
        rows.sort(key=_campaign_sort_key)
        return rows[:limit]

    def _visible(self, campaign: ResponseCampaign, tenant_id: str | None) -> bool:
        if self.mode == "local" and campaign.tenant_id is not None:
            return False
        return tenant_id is None or campaign.tenant_id == tenant_id


class InMemoryTriggerStore:
    def __init__(self, *, mode: str = "local") -> None:
        self._triggers: dict[str, AutomationTrigger] = {}
        self.mode = mode

    async def put(self, trigger: AutomationTrigger) -> AutomationTrigger:
        stored = validate_trigger(trigger)
        if not stored.id:
            stored.id = new_id("trg")
        validate_trigger_id(stored.id, field="id")
        existing = self._triggers.get(stored.id)
        if existing is None:
            created = stored.model_copy(update={"version": 1}, deep=True)
            self._triggers[created.id] = created
            return copy.deepcopy(created)

        if existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("trigger tenant_id cannot change")
        validate_positive(stored.version, field="version")
        if existing.version != stored.version:
            raise OptimisticConcurrencyConflict(
                f"expected v{stored.version}, found v{existing.version}"
            )
        updated = stored.model_copy(update={"version": existing.version + 1}, deep=True)
        self._triggers[updated.id] = updated
        return copy.deepcopy(updated)

    async def list(
        self,
        *,
        tenant_id: str | None,
        enabled_only: bool = True,
    ) -> list[AutomationTrigger]:
        tenant_id = validate_tenant(tenant_id)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("trigger list must be tenant-scoped in enterprise mode")
        rows = [
            copy.deepcopy(trigger)
            for trigger in self._triggers.values()
            if self._visible(trigger, tenant_id) and (not enabled_only or trigger.enabled)
        ]
        rows.sort(key=lambda trigger: trigger.id)
        return rows

    def _visible(self, trigger: AutomationTrigger, tenant_id: str | None) -> bool:
        if self.mode == "local" and trigger.tenant_id is not None:
            return False
        return tenant_id is None or trigger.tenant_id == tenant_id


def _campaign_sort_key(campaign: ResponseCampaign) -> tuple[float, str]:
    return (-campaign.updated_at.timestamp(), campaign.id)
