"""SOC alert correlation and priority composition (EA-0015 S3)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.mission import MissionImpactResult
from aqelyn.risk import Risk
from aqelyn.soc.models import Alert, Incident, SOCConfig


class MissionImpactProvider(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


async def correlate_alerts(
    alerts: Sequence[Alert],
    *,
    tenant_id: str | None,
    by: ActorRef,
    risks: Sequence[Risk] = (),
    mission_engine: MissionImpactProvider | None = None,
    config: SOCConfig | None = None,
    now: datetime | None = None,
) -> list[Incident]:
    selected_config = config or SOCConfig()
    at = now or utc_now()
    visible_alerts = [
        alert
        for alert in sorted(alerts, key=_alert_sort_key)
        if _tenant_visible(alert.tenant_id, tenant_id)
    ][: selected_config.batch_size]
    risk_index = _RiskIndex(risks, tenant_id=tenant_id)
    groups: dict[str, list[Alert]] = defaultdict(list)
    for alert in visible_alerts:
        groups[_group_key(alert)].append(alert)

    incidents = [
        await _incident_for_group(
            key,
            group,
            risk_index=risk_index,
            mission_engine=mission_engine,
            by=by,
            at=at,
        )
        for key, group in sorted(groups.items(), key=lambda item: item[0])
    ]
    return sorted(incidents, key=lambda incident: (-incident.priority, incident.id))


def explain(incident: Incident) -> dict[str, object]:
    return {
        "incident_id": incident.id,
        "method": "soc.correlation/v1",
        "tenant_id": incident.tenant_id,
        "status": incident.status,
        "priority": incident.priority,
        "risk_score": incident.risk_score,
        "top_mission_id": incident.top_mission_id,
        "alert_ids": list(incident.alert_ids),
        "affected_object_ids": list(incident.affected_object_ids),
        "timeline": [entry.model_dump(mode="json") for entry in incident.timeline],
        "evidence_ids": [
            entry.evidence_id for entry in incident.timeline if entry.evidence_id is not None
        ],
        "reason": (
            "SOC incident groups alerts by correlation key and derives priority from "
            "upstream Risk score plus Mission impact."
        ),
    }


async def _incident_for_group(
    key: str,
    alerts: Sequence[Alert],
    *,
    risk_index: _RiskIndex,
    mission_engine: MissionImpactProvider | None,
    by: ActorRef,
    at: datetime,
) -> Incident:
    ordered = sorted(alerts, key=_alert_sort_key)
    risks = risk_index.for_group(key, ordered)
    affected_object_ids = _affected_object_ids(key, ordered, risks)
    mission_factor, top_mission_id = await _mission_context(affected_object_ids, mission_engine)
    risk_score = max((risk.score for risk in risks), default=None)
    priority = max(risk_score or 0.0, mission_factor * 100.0)
    return Incident(
        tenant_id=_tenant_id(ordered),
        title=_title(key, ordered),
        status="new",
        priority=priority,
        alert_ids=[alert.id for alert in ordered],
        affected_object_ids=affected_object_ids,
        top_mission_id=top_mission_id or _risk_top_mission_id(risks),
        risk_score=risk_score,
        timeline=[],
        created_by=by,
        created_at=at,
        updated_at=at,
        version=1,
    )


class _RiskIndex:
    def __init__(self, risks: Sequence[Risk], *, tenant_id: str | None) -> None:
        visible = [risk for risk in risks if _tenant_visible(risk.tenant_id, tenant_id)]
        self.by_id: dict[str, Risk] = {risk.id: risk for risk in visible}
        self.by_correlation: dict[str, list[Risk]] = defaultdict(list)
        for risk in sorted(visible, key=lambda item: item.id):
            self.by_correlation[risk.correlation_key].append(risk)

    def for_group(self, key: str, alerts: Sequence[Alert]) -> list[Risk]:
        selected: dict[str, Risk] = {risk.id: risk for risk in self.by_correlation.get(key, [])}
        for alert in alerts:
            if alert.source_kind == "risk" and alert.source_ref in self.by_id:
                risk = self.by_id[alert.source_ref]
                selected[risk.id] = risk
        return [selected[risk_id] for risk_id in sorted(selected)]


def _group_key(alert: Alert) -> str:
    if alert.correlation_key is not None and alert.correlation_key.strip():
        return alert.correlation_key
    return f"{alert.source_kind}:{alert.source_ref}"


def _alert_sort_key(alert: Alert) -> tuple[str, str, str, str]:
    return (alert.tenant_id or "", _group_key(alert), alert.source_kind, alert.source_ref)


def _tenant_visible(record_tenant_id: str | None, tenant_id: str | None) -> bool:
    if tenant_id is None:
        return record_tenant_id is None
    return record_tenant_id == tenant_id


def _tenant_id(alerts: Sequence[Alert]) -> str | None:
    tenant_ids = {alert.tenant_id for alert in alerts}
    return next(iter(tenant_ids)) if len(tenant_ids) == 1 else None


def _title(key: str, alerts: Sequence[Alert]) -> str:
    kinds = sorted({alert.source_kind for alert in alerts})
    if len(kinds) == 1:
        return f"SOC incident for {kinds[0]} signal {key}"
    return f"SOC incident correlated by {key}"


def _affected_object_ids(key: str, alerts: Sequence[Alert], risks: Sequence[Risk]) -> list[str]:
    object_ids: set[str] = set()
    object_ids.update(_asset_ids_from_key(key))
    for alert in alerts:
        if alert.correlation_key is not None:
            object_ids.update(_asset_ids_from_key(alert.correlation_key))
    for risk in risks:
        object_ids.update(risk.affected_object_ids)
    return sorted(object_ids)


def _asset_ids_from_key(key: str) -> list[str]:
    if not key.startswith("asset:"):
        return []
    return [part for part in key.removeprefix("asset:").split(",") if part]


async def _mission_context(
    object_ids: Sequence[str],
    mission_engine: MissionImpactProvider | None,
) -> tuple[float, str | None]:
    if mission_engine is None:
        return 0.0, None
    best_factor = 0.0
    best_mission_id: str | None = None
    for object_id in sorted(object_ids):
        result = await mission_engine.mission_impact(object_id)
        for impact in result.impacts:
            candidate = impact.impact_score
            mission_id = impact.mission.id
            if candidate > best_factor or (
                candidate == best_factor
                and (best_mission_id is None or mission_id < best_mission_id)
            ):
                best_factor = candidate
                best_mission_id = mission_id
    return best_factor, best_mission_id


def _risk_top_mission_id(risks: Sequence[Risk]) -> str | None:
    mission_ids = sorted({risk.top_mission_id for risk in risks if risk.top_mission_id is not None})
    return mission_ids[0] if mission_ids else None
