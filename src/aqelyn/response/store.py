"""Response orchestration store protocols and validators (EA-0018 R2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ResponseConfigInvalid
from aqelyn.response.models import AutomationTrigger, CampaignStatus, ResponseCampaign

VALID_CAMPAIGN_STATUSES: frozenset[str] = frozenset(
    ("planned", "awaiting_approval", "running", "completed", "failed", "halted")
)


class CampaignStore(Protocol):
    async def upsert(self, campaign: ResponseCampaign) -> ResponseCampaign: ...

    async def get(
        self,
        campaign_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ResponseCampaign | None: ...

    async def query(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[ResponseCampaign]: ...


class TriggerStore(Protocol):
    async def put(self, trigger: AutomationTrigger) -> AutomationTrigger: ...

    async def list(
        self,
        *,
        tenant_id: str | None,
        enabled_only: bool = True,
    ) -> list[AutomationTrigger]: ...


def validate_campaign(campaign: ResponseCampaign) -> ResponseCampaign:
    return ResponseCampaign.model_validate(campaign.model_dump(mode="json"))


def validate_trigger(trigger: AutomationTrigger) -> AutomationTrigger:
    return AutomationTrigger.model_validate(trigger.model_dump(mode="json"))


def validate_campaign_id(
    value: str,
    *,
    field: str = "campaign_id",
    allow_empty: bool = False,
) -> str:
    return require_typed_id(value, "rsp", field=field, allow_empty=allow_empty)


def validate_trigger_id(
    value: str,
    *,
    field: str = "trigger_id",
    allow_empty: bool = False,
) -> str:
    return require_typed_id(value, "trg", field=field, allow_empty=allow_empty)


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise ResponseConfigInvalid(f"{field} must be >= 1")
    return value


def normalize_campaign_status_filter(
    status: Sequence[str] | None,
) -> tuple[CampaignStatus, ...] | None:
    if status is None:
        return None
    normalized: list[CampaignStatus] = []
    for value in status:
        if value not in VALID_CAMPAIGN_STATUSES:
            raise ResponseConfigInvalid(f"unknown campaign status: {value!r}")
        normalized.append(cast(CampaignStatus, value))
    return tuple(normalized)
