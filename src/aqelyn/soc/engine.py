"""Security Operations engine for case work and response coordination (EA-0015)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import IncidentNotFound, SOCConfigInvalid, StoreUnavailable
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.graph import KnowledgeGraph, Subgraph
from aqelyn.objects import ObjectQuery, ObjectStore
from aqelyn.risk import Risk
from aqelyn.soc.correlate import MissionImpactProvider, correlate_alerts
from aqelyn.soc.correlate import explain as explain_incident
from aqelyn.soc.models import (
    Alert,
    Hunt,
    Incident,
    IncidentStatus,
    ResponseAction,
    SOCConfig,
    TimelineEntry,
)
from aqelyn.soc.store import VALID_INCIDENT_STATUSES, SOCStore, validate_positive
from aqelyn.workflow import Playbook, Step, WorkflowEngine

_ACTOR = ActorRef(actor_type="system", actor_id="soc_engine")


class SecurityOperationsEngine:
    def __init__(
        self,
        store: SOCStore,
        evidence_store: EvidenceStore,
        *,
        graph: KnowledgeGraph | None = None,
        mission_engine: MissionImpactProvider | None = None,
        workflow_engine: WorkflowEngine | None = None,
        object_store: ObjectStore | None = None,
        config: SOCConfig | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self.store = store
        self.evidence_store = evidence_store
        self.graph = graph
        self.mission_engine = mission_engine
        self.workflow_engine = workflow_engine
        self.object_store = object_store
        self.config = config or SOCConfig()
        self.actor = actor or _ACTOR
        self.source_id = source_id or new_id("src")

    async def correlate(
        self,
        *,
        tenant_id: str | None,
        alerts: Sequence[Alert],
        risks: Sequence[Risk] = (),
        by: ActorRef | None = None,
    ) -> list[Incident]:
        actor = by or self.actor
        stored_alerts = [await self.store.upsert_alert(alert) for alert in alerts]
        drafts = await correlate_alerts(
            stored_alerts,
            tenant_id=tenant_id,
            by=actor,
            risks=risks,
            mission_engine=self.mission_engine,
            config=self.config,
        )
        incidents: list[Incident] = []
        for draft in drafts:
            evidence = await self._record_evidence(
                draft,
                kind="correlated",
                by=actor,
                method="soc.correlate/v1",
                content={
                    "incident": _incident_summary(draft),
                    "alert_ids": list(draft.alert_ids),
                    "risk_score": draft.risk_score,
                    "top_mission_id": draft.top_mission_id,
                },
            )
            incident = draft.model_copy(
                update={
                    "timeline": [
                        TimelineEntry(
                            at=evidence.recorded_at,
                            actor=actor,
                            kind="correlated",
                            detail={
                                "alert_ids": list(draft.alert_ids),
                                "risk_score": draft.risk_score,
                                "top_mission_id": draft.top_mission_id,
                                "priority": draft.priority,
                            },
                            evidence_id=evidence.id,
                        )
                    ],
                    "created_at": evidence.recorded_at,
                    "updated_at": evidence.recorded_at,
                },
                deep=True,
            )
            incidents.append(await self.store.upsert_incident(incident))
        return incidents

    async def assign(
        self,
        incident_id: str,
        *,
        to: ActorRef,
        by: ActorRef,
        expected_version: int,
    ) -> Incident:
        incident = await self._incident(incident_id, expected_version=expected_version)
        evidence = await self._record_evidence(
            incident,
            kind="assigned",
            by=by,
            method="soc.assign/v1",
            content={
                "incident_id": incident.id,
                "from": None if incident.assignee is None else incident.assignee.model_dump(),
                "to": to.model_dump(),
                "expected_version": expected_version,
            },
        )
        return await self._append_timeline(
            incident,
            TimelineEntry(
                at=evidence.recorded_at,
                actor=by,
                kind="assigned",
                detail={"to": to.model_dump(mode="json")},
                evidence_id=evidence.id,
            ),
            update={"assignee": to},
        )

    async def transition(
        self,
        incident_id: str,
        to_status: str,
        *,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Incident:
        if to_status not in VALID_INCIDENT_STATUSES:
            raise SOCConfigInvalid(f"unknown incident status: {to_status!r}")
        incident = await self._incident(incident_id, expected_version=expected_version)
        selected_status = cast(IncidentStatus, to_status)
        evidence = await self._record_evidence(
            incident,
            kind="status_changed",
            by=by,
            method="soc.transition/v1",
            content={
                "incident_id": incident.id,
                "from_status": incident.status,
                "to_status": selected_status,
                "note": note,
                "expected_version": expected_version,
            },
        )
        return await self._append_timeline(
            incident,
            TimelineEntry(
                at=evidence.recorded_at,
                actor=by,
                kind="status_changed",
                detail={"from": incident.status, "to": selected_status, "note": note},
                evidence_id=evidence.id,
            ),
            update={"status": selected_status},
        )

    async def investigate(
        self,
        incident_id: str,
        *,
        pivot: Mapping[str, object],
        by: ActorRef,
        expected_version: int,
    ) -> Incident:
        if self.graph is None:
            raise StoreUnavailable("investigate requires a KnowledgeGraph")
        incident = await self._incident(incident_id, expected_version=expected_version)
        subgraph = await self._pivot(pivot)
        evidence = await self._record_evidence(
            incident,
            kind="investigated",
            by=by,
            method="soc.investigate/v1",
            content={
                "incident_id": incident.id,
                "pivot": dict(pivot),
                "subgraph": subgraph.model_dump(mode="json"),
                "expected_version": expected_version,
            },
            object_ids=_subject_objects(incident, extra=[node.id for node in subgraph.nodes]),
        )
        return await self._append_timeline(
            incident,
            TimelineEntry(
                at=evidence.recorded_at,
                actor=by,
                kind="investigated",
                detail={
                    "pivot": dict(pivot),
                    "node_count": len(subgraph.nodes),
                    "edge_count": len(subgraph.edges),
                    "truncated": subgraph.truncated,
                },
                evidence_id=evidence.id,
            ),
            update={"status": _investigating_status(incident.status)},
        )

    async def propose_response(
        self,
        incident_id: str,
        *,
        actions: Sequence[ResponseAction],
        by: ActorRef,
        expected_version: int,
    ) -> list[str]:
        if self.workflow_engine is None:
            raise StoreUnavailable("propose_response requires a WorkflowEngine")
        if not actions:
            raise SOCConfigInvalid("propose_response requires at least one action")

        incident = await self._incident(incident_id, expected_version=expected_version)
        current = incident
        run_ids: list[str] = []
        for index, action in enumerate(actions, start=1):
            run = await self.workflow_engine.propose(
                _response_playbook(current, action, index=index),
                by=by,
            )
            tracked_action = action.model_copy(
                update={"workflow_run_id": run.id, "status": run.status},
                deep=True,
            )
            evidence = await self._record_evidence(
                current,
                kind="response_proposed",
                by=by,
                method="soc.propose_response/v1",
                content={
                    "incident_id": current.id,
                    "action_index": index,
                    "response_action": tracked_action.model_dump(mode="json"),
                    "workflow_run_id": run.id,
                    "workflow_status": run.status,
                    "playbook_id": run.playbook_id,
                    "expected_version": current.version,
                },
            )
            current = await self._append_timeline(
                current,
                TimelineEntry(
                    at=evidence.recorded_at,
                    actor=by,
                    kind="response_proposed",
                    detail={
                        "action_index": index,
                        "response_action": tracked_action.model_dump(mode="json"),
                        "workflow_run_id": run.id,
                        "workflow_status": run.status,
                    },
                    evidence_id=evidence.id,
                ),
                update={},
            )
            run_ids.append(run.id)
        return run_ids

    async def hunt(self, hunt: Hunt) -> list[dict[str, object]]:
        if self.object_store is None:
            raise StoreUnavailable("hunt requires an ObjectStore")

        query = hunt.query
        limit = min(
            _positive_int(query.get("limit"), default=self.config.batch_size, field="hunt.limit"),
            self.config.batch_size,
        )
        object_type = _optional_string_value(query, "object_type")
        labels = _optional_string_mapping(query.get("labels"), field="hunt.labels")
        include_states = _include_states(query.get("include_states"))
        attribute_equals = _optional_object_mapping(
            query.get("attribute_equals"), field="hunt.attribute_equals"
        )

        matches: list[dict[str, object]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while len(matches) < limit:
            objects, next_cursor = await self.object_store.query(
                ObjectQuery(
                    tenant_id=hunt.tenant_id,
                    object_type=object_type,
                    labels=labels,
                    include_states=include_states,
                    limit=limit,
                    cursor=cursor,
                )
            )
            for obj in objects:
                if not _attributes_match(obj.attributes, attribute_equals):
                    continue
                matches.append(
                    {
                        "kind": "object",
                        "object_id": obj.id,
                        "object_type": obj.object_type,
                        "display_name": obj.display_name,
                        "labels": dict(obj.labels),
                        "attributes": dict(obj.attributes),
                        "reason": f"Matched bounded hunt query {hunt.id}",
                    }
                )
                if len(matches) == limit:
                    break
            if len(matches) == limit or next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise StoreUnavailable("ObjectStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return matches

    def explain(self, incident: Incident) -> dict[str, object]:
        return explain_incident(incident)

    async def _incident(self, incident_id: str, *, expected_version: int) -> Incident:
        validate_positive(expected_version, field="expected_version")
        incident = await self.store.get_incident(incident_id)
        if incident is None:
            raise IncidentNotFound(incident_id)
        if incident.version != expected_version:
            from aqelyn.conventions.errors import OptimisticConcurrencyConflict

            raise OptimisticConcurrencyConflict(
                f"expected v{expected_version}, found v{incident.version}"
            )
        return incident

    async def _append_timeline(
        self,
        incident: Incident,
        entry: TimelineEntry,
        *,
        update: Mapping[str, object],
    ) -> Incident:
        changed = incident.model_copy(
            update={
                **dict(update),
                "timeline": [*incident.timeline, entry],
                "updated_at": entry.at,
                "version": incident.version,
            },
            deep=True,
        )
        return await self.store.upsert_incident(changed)

    async def _record_evidence(
        self,
        incident: Incident,
        *,
        kind: str,
        by: ActorRef,
        method: str,
        content: dict[str, Any],
        object_ids: Sequence[str] | None = None,
    ) -> EvidenceRecord:
        now = utc_now()
        record = EvidenceRecord(
            id="",
            tenant_id=incident.tenant_id,
            evidence_type="soc.case_step",
            schema_version=1,
            subject=Subject(object_ids=_subject_objects(incident, extra=object_ids or [])),
            collected_at=now,
            recorded_at=now,
            collector=by,
            source_id=self.source_id,
            method=method,
            content={
                "kind": kind,
                "incident_id": incident.id,
                "tenant_id": incident.tenant_id,
                **content,
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0015", "kind": kind},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self.evidence_store.add(record)

    async def _pivot(self, pivot: Mapping[str, object]) -> Subgraph:
        assert self.graph is not None
        start_id = _string_value(pivot, "start_id")
        direction = _optional_string_value(pivot, "direction") or "both"
        relation_types = _string_sequence(pivot.get("relation_types"))
        max_depth = _positive_int(pivot.get("max_depth"), default=2, field="pivot.max_depth")
        max_nodes = _positive_int(pivot.get("max_nodes"), default=100, field="pivot.max_nodes")
        return await self.graph.subgraph(
            start_id,
            direction=direction,
            relation_types=relation_types,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )


def _incident_summary(incident: Incident) -> dict[str, object]:
    return {
        "id": incident.id,
        "tenant_id": incident.tenant_id,
        "title": incident.title,
        "priority": incident.priority,
        "status": incident.status,
        "alert_ids": list(incident.alert_ids),
        "affected_object_ids": list(incident.affected_object_ids),
    }


def _response_playbook(incident: Incident, action: ResponseAction, *, index: int) -> Playbook:
    action_slug = _slug(action.action_type)
    return Playbook(
        id=f"soc-response-{_slug(incident.id)}-{index}",
        version=1,
        name=f"SOC response proposal {index} for {incident.id}",
        description="Proposed, gated SOC response action delegated to Workflow.",
        tenant_id=incident.tenant_id,
        steps=[
            Step(
                id=f"response-{index}-{action_slug}",
                action_type=action.action_type,
                inputs={
                    **action.inputs,
                    "soc_incident_id": incident.id,
                    "soc_alert_ids": list(incident.alert_ids),
                    "soc_affected_object_ids": list(incident.affected_object_ids),
                    "soc_priority": incident.priority,
                },
                idempotency_key=f"soc:{incident.id}:{incident.version}:{index}:{action_slug}",
                requires_approval=True,
            )
        ],
    )


def _subject_objects(incident: Incident, *, extra: Sequence[str] = ()) -> list[str]:
    return sorted({*incident.affected_object_ids, *extra})


def _investigating_status(status: IncidentStatus) -> IncidentStatus:
    if status in {"resolved", "closed"}:
        return status
    return "investigating"


def _string_value(pivot: Mapping[str, object], key: str) -> str:
    value = pivot.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SOCConfigInvalid(f"pivot.{key} must be a non-empty string")
    return value


def _optional_string_value(pivot: Mapping[str, object], key: str) -> str | None:
    value = pivot.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SOCConfigInvalid(f"pivot.{key} must be a non-empty string when present")
    return value


def _string_sequence(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise SOCConfigInvalid("pivot.relation_types must be a sequence of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SOCConfigInvalid("pivot.relation_types must contain non-empty strings")
        out.append(item)
    return tuple(out)


def _positive_int(value: object, *, default: int, field: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SOCConfigInvalid(f"{field} must be >= 1")
    return value


def _optional_string_mapping(value: object, *, field: str) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SOCConfigInvalid(f"{field} must be a mapping")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise SOCConfigInvalid(f"{field} keys must be non-empty strings")
        if not isinstance(item, str) or not item.strip():
            raise SOCConfigInvalid(f"{field} values must be non-empty strings")
        out[key] = item
    return out


def _optional_object_mapping(value: object, *, field: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SOCConfigInvalid(f"{field} must be a mapping")
    out: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise SOCConfigInvalid(f"{field} keys must be non-empty strings")
        out[key] = item
    return out


def _include_states(value: object) -> tuple[str, ...]:
    if value is None:
        return ("active", "archived")
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise SOCConfigInvalid("hunt.include_states must be a sequence of strings")
    states: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SOCConfigInvalid("hunt.include_states must contain non-empty strings")
        states.append(item)
    if not states:
        raise SOCConfigInvalid("hunt.include_states must not be empty")
    return tuple(states)


def _attributes_match(attributes: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    return all(attributes.get(key) == value for key, value in expected.items())


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-") or "value"
