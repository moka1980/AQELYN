"""SaaS posture normalization and owner routing engine (EA-0029 Z2)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id, utc_now
from aqelyn.conventions.errors import (
    AQError,
    IntegrationNotFound,
    SaaSConfigInvalid,
    SaaSObjectNotFound,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.objects import AQObject, NaturalKey, ObjectQuery, ObjectStore, SourceRef
from aqelyn.sspm.integration import (
    IntegrationGraph,
    IntegrationTrustProvider,
    blast_radius,
    existing_integration_object,
    integration_object,
    integration_raw_content,
    integration_reason,
    record_grant_edge,
    require_integration_endpoints,
    scope_status,
)
from aqelyn.sspm.models import (
    BlastRadius,
    IntegrationDescriptor,
    NormalizedSaaSObject,
    SaaSAppDescriptor,
    SaaSConfig,
    SaaSIntegration,
    SaaSRouteOwner,
    SaaSRoutingResult,
)
from aqelyn.sspm.normalize import (
    ensure_saas_object_types,
    extract_native_facts,
    normalized_to_object,
    object_type_for,
    saas_natural_key,
)
from aqelyn.sspm.route import SaaSAbsenceRouter, SaaSBaselineRouter, SaaSOwnerRouter
from aqelyn.sspm.store import SaaSNormalizationStore
from aqelyn.trust import SourceReliabilityRegistry
from aqelyn.workflow import Playbook, Run, Step

_ACTOR = ActorRef(actor_type="system", actor_id="sspm_engine")
_Z2_ROUTE_OWNERS: tuple[SaaSRouteOwner, ...] = (
    "inventory",
    "assetconfig",
    "compliance",
    "iag",
)


@dataclass(frozen=True)
class _Candidate:
    value: Any
    source_id: str
    evidence_id: str
    observed_at: datetime
    reliability: float
    path: str


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
    ) -> Run: ...


class SaaSPostureEngine:
    def __init__(
        self,
        store: SaaSNormalizationStore,
        *,
        object_store: ObjectStore,
        evidence_store: EvidenceStore,
        source_registry: SourceReliabilityRegistry,
        config: SaaSConfig,
        owner_routers: Sequence[SaaSOwnerRouter] = (),
        integration_graph: IntegrationGraph | None = None,
        trust_engine: IntegrationTrustProvider | None = None,
        baseline_router: SaaSBaselineRouter | None = None,
        workflow_engine: WorkflowProposer | None = None,
        absence_router: SaaSAbsenceRouter | None = None,
        actor: ActorRef | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.evidence_store = evidence_store
        self.source_registry = source_registry
        self.config = config
        self.owner_routers = _owner_router_map(owner_routers)
        self.integration_graph = integration_graph
        self.trust_engine = trust_engine
        self.baseline_router = baseline_router
        self.workflow_engine = workflow_engine
        self.absence_router = absence_router
        self.actor = actor or _ACTOR
        ensure_saas_object_types(object_store, config)

    async def normalize(
        self,
        descriptors: Sequence[SaaSAppDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[NormalizedSaaSObject]:
        selected_tenant = require_tenant_id(tenant_id)
        if len(descriptors) > self.config.batch_size:
            raise SaaSConfigInvalid(
                f"descriptor batch exceeds configured limit {self.config.batch_size}"
            )
        return [
            await self._normalize_one(descriptor, tenant_id=selected_tenant)
            for descriptor in descriptors
        ]

    async def route(
        self,
        object_ids: Sequence[str],
        *,
        tenant_id: str | None,
    ) -> list[SaaSRoutingResult]:
        selected_tenant = require_tenant_id(tenant_id)
        selected_ids = [
            require_typed_id(object_id, "obj", field="object_ids") for object_id in object_ids
        ]
        if len(selected_ids) > self.config.batch_size:
            raise SaaSConfigInvalid(
                f"route batch exceeds configured limit {self.config.batch_size}"
            )
        if len(selected_ids) != len(set(selected_ids)):
            raise SaaSConfigInvalid("object_ids must not contain duplicates")

        results: list[SaaSRoutingResult] = []
        for object_id in sorted(selected_ids):
            obj = await self.store.get(object_id, tenant_id=selected_tenant)
            if obj is None:
                raise SaaSObjectNotFound(object_id)
            await self._verify_route_evidence(obj, tenant_id=selected_tenant)
            results.append(await self._route_one(obj, tenant_id=selected_tenant))
        return results

    async def map_integration(
        self,
        descriptors: Sequence[IntegrationDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[SaaSIntegration]:
        selected_tenant = require_tenant_id(tenant_id)
        if len(descriptors) > self.config.batch_size:
            raise SaaSConfigInvalid(
                f"integration batch exceeds configured limit {self.config.batch_size}"
            )
        return [
            await self._map_integration_one(descriptor, tenant_id=selected_tenant)
            for descriptor in descriptors
        ]

    async def integration_blast_radius(
        self,
        integration_id: str,
        *,
        tenant_id: str | None,
    ) -> BlastRadius:
        selected_id = require_typed_id(integration_id, "obj", field="integration_id")
        selected_tenant = require_tenant_id(tenant_id)
        integration = await self.store.get_integration(
            selected_id,
            tenant_id=selected_tenant,
        )
        if integration is None:
            raise IntegrationNotFound(selected_id)
        if self.integration_graph is None:
            raise StoreUnavailable("knowledge graph is unavailable for integration traversal")
        result = await blast_radius(
            self.integration_graph,
            start_id=integration.third_party_app,
            max_nodes=self.config.integration_max_nodes,
        )
        if result.truncated and not result.object_ids:
            raise StoreUnavailable(
                "integration traversal exhausted its budget before learning reach"
            )
        return result

    async def apply_saas_baselines(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> str:
        selected_tenant = require_tenant_id(tenant_id)
        if self.baseline_router is None:
            raise StoreUnavailable("asset configuration engine is unavailable")
        return await self.baseline_router.apply(
            self.config.baseline_ids,
            tenant_id=selected_tenant,
            scope=scope,
        )

    async def mark_app_unreported(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> str:
        selected_id = require_typed_id(object_id, "obj", field="object_id")
        selected_tenant = require_tenant_id(tenant_id)
        if self.absence_router is None:
            raise StoreUnavailable("inventory lifecycle adapter is unavailable")
        obj = await self.store.get(selected_id, tenant_id=selected_tenant)
        if obj is None:
            raise SaaSObjectNotFound(selected_id)
        return await self.absence_router.mark_unreported(obj, tenant_id=selected_tenant)

    async def propose_revocation(
        self,
        integration_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        reason: str,
    ) -> Run:
        selected_id = require_typed_id(integration_id, "obj", field="integration_id")
        selected_tenant = require_tenant_id(tenant_id)
        if not reason.strip():
            raise SaaSConfigInvalid("revocation reason must not be empty")
        integration = await self.store.get_integration(
            selected_id,
            tenant_id=selected_tenant,
        )
        if integration is None:
            raise IntegrationNotFound(selected_id)
        if self.workflow_engine is None:
            raise StoreUnavailable("workflow engine is unavailable for revocation proposal")
        playbook = Playbook(
            id=f"sspm-revoke-{selected_id}",
            version=1,
            name="Propose SaaS integration revocation",
            description="SaaS grant revocation is delegated to Workflow for gating.",
            tenant_id=selected_tenant,
            steps=[
                Step(
                    id=f"revoke-{selected_id}",
                    action_type="saas.integration.revoke",
                    inputs={
                        "integration_object_id": selected_id,
                        "grantor_ref": integration.grantor_ref,
                        "third_party_app": integration.third_party_app,
                        "scopes": list(integration.scopes),
                        "evidence_id": integration.evidence_id,
                        "reason": reason,
                    },
                    idempotency_key=f"sspm:{selected_id}:revoke",
                    requires_approval=True,
                )
            ],
        )
        return await self.workflow_engine.propose(playbook, by=by)

    def explain(self, obj: NormalizedSaaSObject) -> dict[str, object]:
        return {
            "object_id": obj.object_id,
            "object_type": obj.object_type,
            "provider": obj.provider,
            "provider_tenant": obj.tenant,
            "field_provenance": dict(obj.field_provenance),
            "conflicts": copy.deepcopy(obj.conflicts),
            "evidence_id": obj.evidence_id,
            "flagged": obj.flagged,
            "reason": (
                "Flat SaaS facts were selected from handed-in provider data; "
                "each fact names its raw JSON Pointer and conflicts retain both candidates."
            ),
        }

    async def _route_one(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> SaaSRoutingResult:
        routed: list[SaaSRouteOwner] = []
        pending: list[SaaSRouteOwner] = []
        refs: dict[SaaSRouteOwner, list[str]] = {}
        for owner in _Z2_ROUTE_OWNERS:
            router = self.owner_routers.get(owner)
            if router is None or not obj.native_facts:
                pending.append(owner)
                continue
            try:
                owner_refs = list(
                    await router.route(obj.model_copy(deep=True), tenant_id=tenant_id)
                )
                if not owner_refs:
                    raise SaaSConfigInvalid(f"{owner} owner router returned no references")
            except AQError as exc:
                if not exc.retriable:
                    raise
                pending.append(owner)
                continue
            routed.append(owner)
            refs[owner] = owner_refs
        return SaaSRoutingResult(
            object_id=obj.object_id,
            routed_to=routed,
            routing_pending=pending,
            inventory_ref=_first_ref(refs.get("inventory")),
            iam_refs=refs.get("iag", []),
        )

    async def _map_integration_one(
        self,
        descriptor: IntegrationDescriptor,
        *,
        tenant_id: str | None,
    ) -> SaaSIntegration:
        await require_integration_endpoints(
            self.object_store,
            descriptor,
            tenant_id=tenant_id,
        )
        existing = await existing_integration_object(
            self.object_store,
            descriptor,
            tenant_id=tenant_id,
        )
        object_id = existing.id if existing is not None else new_id("obj")
        evidence = await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=tenant_id,
                evidence_type="saas.integration_descriptor",
                schema_version=1,
                subject=Subject(
                    object_ids=[object_id, descriptor.grantor_ref, descriptor.third_party_app],
                    evidence_id=descriptor.evidence_id,
                ),
                collected_at=descriptor.observed_at,
                recorded_at=utc_now(),
                collector=self.actor,
                source_id=descriptor.source_id,
                method="sspm.map_integration/v1",
                content=integration_raw_content(descriptor),
                content_hash="",
                confidence=1.0,
                labels={"module": "EA-0029", "kind": "saas_integration_descriptor"},
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )
        if self.trust_engine is None:
            raise StoreUnavailable("trust engine is unavailable for integration confidence")
        trust = await self.trust_engine.assess(
            f"sspm:integration:{object_id}",
            [evidence],
            now=descriptor.observed_at,
        )
        saved = await self.object_store.upsert(
            integration_object(
                descriptor,
                object_id=object_id,
                tenant_id=tenant_id,
                evidence_id=evidence.id,
                claim_confidence=trust.score,
                actor=self.actor,
            )
        )
        if saved.id != object_id:
            raise SaaSConfigInvalid("integration natural key changed object identity")
        await record_grant_edge(
            self.object_store,
            descriptor,
            integration_object_id=object_id,
            tenant_id=tenant_id,
            evidence_id=evidence.id,
            confidence=trust.score,
            actor=self.actor,
        )

        reachable: list[str] = []
        reach_status = "pending"
        try:
            if self.integration_graph is None:
                raise StoreUnavailable("knowledge graph is unavailable for integration traversal")
            radius = await blast_radius(
                self.integration_graph,
                start_id=descriptor.third_party_app,
                max_nodes=self.config.integration_max_nodes,
            )
            if radius.truncated and not radius.object_ids:
                raise StoreUnavailable(
                    "integration traversal exhausted its budget before learning reach"
                )
        except AQError as exc:
            if not exc.retriable:
                raise
        else:
            reachable = radius.object_ids
            reach_status = "truncated" if radius.truncated else "computed"
        status = scope_status(descriptor, sensitive_scopes=self.config.sensitive_scopes)
        integration = SaaSIntegration(
            object_id=object_id,
            tenant_id=tenant_id,
            integration_id=descriptor.integration_id,
            grantor_ref=descriptor.grantor_ref,
            grantor_kind=descriptor.grantor_kind,
            third_party_app=descriptor.third_party_app,
            third_party_external=descriptor.third_party_external,
            scopes=sorted(descriptor.scopes),
            over_scoped=status,
            reachable_object_ids=reachable,
            reach_status=reach_status,
            known_surface_ref=object_id if status == "over_scoped" else None,
            claim_confidence=trust.score,
            evidence_id=evidence.id,
            observed_at=descriptor.observed_at,
            reason=integration_reason(
                descriptor,
                status=status,
                reach_status=reach_status,
                reachable_object_ids=reachable,
            ),
        )
        return await self.store.put_integration(integration)

    async def _normalize_one(
        self,
        descriptor: SaaSAppDescriptor,
        *,
        tenant_id: str | None,
    ) -> NormalizedSaaSObject:
        object_type, selected_key = object_type_for(descriptor, self.config)
        incoming_facts, incoming_provenance = extract_native_facts(descriptor.raw)
        natural_key = saas_natural_key(descriptor)
        existing_object = await self._existing_object(natural_key, tenant_id=tenant_id)
        if existing_object is not None and existing_object.object_type != object_type:
            raise SaaSConfigInvalid(
                "SaaS app type mapping cannot change for an existing natural key"
            )
        object_id = existing_object.id if existing_object is not None else new_id("obj")
        evidence = await self._record_raw_evidence(
            descriptor,
            object_id=object_id,
            tenant_id=tenant_id,
        )
        existing = await self.store.get(object_id, tenant_id=tenant_id)
        incoming_reliability = (
            await self.source_registry.get(source_id=descriptor.source_id)
        ).weight
        facts, provenance, conflicts = await self._resolve_conflicts(
            existing,
            existing_object=existing_object,
            incoming_facts=incoming_facts,
            incoming_provenance=incoming_provenance,
            descriptor=descriptor,
            evidence_id=evidence.id,
            incoming_reliability=incoming_reliability,
        )
        projected = NormalizedSaaSObject(
            object_id=object_id,
            tenant_id=tenant_id,
            object_type=object_type,
            provider=descriptor.provider,
            tenant=descriptor.tenant,
            native_facts=facts,
            field_provenance=provenance,
            conflicts=conflicts,
            evidence_id=evidence.id,
            flagged=selected_key is None,
        )
        object_confidence = max(
            incoming_reliability,
            0.0 if existing_object is None else existing_object.confidence,
        )
        saved_object = await self.object_store.upsert(
            normalized_to_object(
                projected,
                descriptor=descriptor,
                actor=self.actor,
                confidence=object_confidence,
            )
        )
        if saved_object.id != projected.object_id:
            projected = projected.model_copy(update={"object_id": saved_object.id}, deep=True)
        return await self.store.put(projected)

    async def _existing_object(
        self,
        natural_key: NaturalKey,
        *,
        tenant_id: str | None,
    ) -> AQObject | None:
        rows, _cursor = await self.object_store.query(
            ObjectQuery(
                tenant_id=tenant_id,
                natural_key=natural_key,
                include_states=("active", "archived"),
                limit=10_000,
            )
        )
        if len(rows) > 1:
            raise SaaSConfigInvalid("SaaS natural key resolved to multiple objects")
        return None if not rows else rows[0]

    async def _record_raw_evidence(
        self,
        descriptor: SaaSAppDescriptor,
        *,
        object_id: str,
        tenant_id: str | None,
    ) -> EvidenceRecord:
        return await self.evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=tenant_id,
                evidence_type="saas.app_descriptor",
                schema_version=1,
                subject=Subject(object_ids=[object_id], evidence_id=descriptor.evidence_id),
                collected_at=descriptor.observed_at,
                recorded_at=utc_now(),
                collector=self.actor,
                source_id=descriptor.source_id,
                method="sspm.normalize/v1",
                content={
                    "provider": descriptor.provider,
                    "provider_tenant": descriptor.tenant,
                    "app_id": descriptor.app_id,
                    "app_name": descriptor.app_name,
                    "resource_type": descriptor.resource_type,
                    "upstream_evidence_id": descriptor.evidence_id,
                    "raw": copy.deepcopy(descriptor.raw),
                },
                content_hash="",
                confidence=1.0,
                labels={"module": "EA-0029", "kind": "saas_app_descriptor"},
                seq=0,
                prev_hash=None,
                record_hash="",
            )
        )

    async def _verify_route_evidence(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> None:
        verification = await self.evidence_store.verify(obj.evidence_id)
        if not verification.ok:
            detail = verification.detail or "integrity check failed"
            raise SaaSConfigInvalid(f"SaaS route evidence failed verification: {detail}")
        evidence = await self.evidence_store.get(obj.evidence_id, actor=self.actor)
        if evidence.tenant_id != tenant_id:
            raise SaaSConfigInvalid("SaaS route evidence tenant does not match object tenant")
        if obj.object_id not in evidence.subject.object_ids:
            raise SaaSConfigInvalid("SaaS route evidence does not name the normalized object")
        if evidence.evidence_type != "saas.app_descriptor":
            raise SaaSConfigInvalid("SaaS route evidence has the wrong evidence_type")
        content = evidence.content
        if not isinstance(content, Mapping):
            raise SaaSConfigInvalid("SaaS route evidence content is unavailable")
        expected = {
            "provider": obj.provider,
            "provider_tenant": obj.tenant,
        }
        for key, value in expected.items():
            if content.get(key) != value:
                raise SaaSConfigInvalid(
                    f"SaaS route evidence {key} does not match normalized object"
                )

    async def _resolve_conflicts(
        self,
        existing: NormalizedSaaSObject | None,
        *,
        existing_object: AQObject | None,
        incoming_facts: dict[str, Any],
        incoming_provenance: dict[str, str],
        descriptor: SaaSAppDescriptor,
        evidence_id: str,
        incoming_reliability: float,
    ) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]]:
        if existing is None:
            return incoming_facts, incoming_provenance, []
        facts = copy.deepcopy(existing.native_facts)
        provenance = dict(existing.field_provenance)
        conflicts = copy.deepcopy(existing.conflicts)
        for field in sorted(incoming_facts):
            if (
                field not in existing.native_facts
                or existing.native_facts[field] == incoming_facts[field]
            ):
                facts[field] = copy.deepcopy(incoming_facts[field])
                provenance[field] = incoming_provenance[field]
                continue
            old = await self._existing_candidate(
                existing,
                field=field,
                existing_object=existing_object,
            )
            incoming = _Candidate(
                value=copy.deepcopy(incoming_facts[field]),
                source_id=descriptor.source_id,
                evidence_id=evidence_id,
                observed_at=descriptor.observed_at,
                reliability=incoming_reliability,
                path=incoming_provenance[field],
            )
            winner, reason = _select_candidate(old, incoming)
            facts[field] = copy.deepcopy(winner.value)
            provenance[field] = winner.path
            conflicts.append(_conflict_record(field, old, incoming, winner=winner, reason=reason))
        return facts, provenance, conflicts

    async def _existing_candidate(
        self,
        existing: NormalizedSaaSObject,
        *,
        field: str,
        existing_object: AQObject | None,
    ) -> _Candidate:
        conflict_candidate = _candidate_from_conflicts(existing, field)
        if conflict_candidate is not None:
            current_reliability = (
                await self.source_registry.get(source_id=conflict_candidate.source_id)
            ).weight
            return _Candidate(
                value=conflict_candidate.value,
                source_id=conflict_candidate.source_id,
                evidence_id=conflict_candidate.evidence_id,
                observed_at=conflict_candidate.observed_at,
                reliability=current_reliability,
                path=conflict_candidate.path,
            )
        source = _source_for_evidence(existing_object, existing.evidence_id)
        if source is None:
            raise SaaSConfigInvalid(
                f"existing normalized field {field!r} has no source for evidence "
                f"{existing.evidence_id}"
            )
        reliability = (await self.source_registry.get(source_id=source.source_id)).weight
        return _Candidate(
            value=copy.deepcopy(existing.native_facts[field]),
            source_id=source.source_id,
            evidence_id=existing.evidence_id,
            observed_at=source.observed_at,
            reliability=reliability,
            path=existing.field_provenance[field],
        )


def _owner_router_map(routers: Sequence[SaaSOwnerRouter]) -> dict[SaaSRouteOwner, SaaSOwnerRouter]:
    selected: dict[SaaSRouteOwner, SaaSOwnerRouter] = {}
    for router in routers:
        if router.owner in selected:
            raise SaaSConfigInvalid(f"duplicate SaaS owner router: {router.owner!r}")
        selected[router.owner] = router
    return selected


def _first_ref(refs: list[str] | None) -> str | None:
    return None if not refs else refs[0]


def _source_for_evidence(obj: AQObject | None, evidence_id: str) -> SourceRef | None:
    if obj is None:
        return None
    for source in reversed(obj.sources):
        if source.evidence_id == evidence_id:
            return source
    return None


def _candidate_from_conflicts(
    existing: NormalizedSaaSObject,
    field: str,
) -> _Candidate | None:
    for conflict in reversed(existing.conflicts):
        if conflict.get("field") != field:
            continue
        evidence_id = conflict.get("resolved_evidence_id")
        candidates = conflict.get("candidates")
        if not isinstance(evidence_id, str) or not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict) or candidate.get("evidence_id") != evidence_id:
                continue
            source_id = candidate.get("source_id")
            observed_at = candidate.get("observed_at")
            reliability = candidate.get("reliability")
            path = candidate.get("path")
            if (
                not isinstance(source_id, str)
                or not isinstance(observed_at, str)
                or isinstance(reliability, bool)
                or not isinstance(reliability, int | float)
                or not isinstance(path, str)
            ):
                continue
            return _Candidate(
                value=copy.deepcopy(existing.native_facts[field]),
                source_id=source_id,
                evidence_id=evidence_id,
                observed_at=datetime.fromisoformat(observed_at),
                reliability=float(reliability),
                path=path,
            )
    return None


def _select_candidate(old: _Candidate, incoming: _Candidate) -> tuple[_Candidate, str]:
    if old.reliability != incoming.reliability:
        return (
            (old, "higher source reliability")
            if old.reliability > incoming.reliability
            else (incoming, "higher source reliability")
        )
    if old.observed_at != incoming.observed_at:
        return (
            (old, "newer observation")
            if old.observed_at > incoming.observed_at
            else (incoming, "newer observation")
        )
    winner = max(
        (old, incoming),
        key=lambda candidate: (candidate.source_id, candidate.evidence_id),
    )
    return winner, "deterministic source/evidence tie-break"


def _conflict_record(
    field: str,
    old: _Candidate,
    incoming: _Candidate,
    *,
    winner: _Candidate,
    reason: str,
) -> dict[str, Any]:
    candidates = sorted((old, incoming), key=lambda item: (item.source_id, item.evidence_id))
    return {
        "field": field,
        "candidates": [_candidate_dict(candidate) for candidate in candidates],
        "resolved_by": winner.source_id,
        "resolved_evidence_id": winner.evidence_id,
        "resolved_value": copy.deepcopy(winner.value),
        "reason": reason,
    }


def _candidate_dict(candidate: _Candidate) -> dict[str, Any]:
    return {
        "value": copy.deepcopy(candidate.value),
        "source_id": candidate.source_id,
        "evidence_id": candidate.evidence_id,
        "observed_at": candidate.observed_at.isoformat(),
        "reliability": candidate.reliability,
        "path": candidate.path,
    }
