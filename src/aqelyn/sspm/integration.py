"""SaaS integration mapping onto EA-0002 and EA-0005 owner contracts."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import CrossTenantReference, SaaSConfigInvalid
from aqelyn.evidence import EvidenceRecord
from aqelyn.graph import Subgraph
from aqelyn.objects import AQObject, AQRelationship, NaturalKey, ObjectQuery, ObjectStore, SourceRef
from aqelyn.sspm.models import BlastRadius, IntegrationDescriptor, OverScopedStatus
from aqelyn.sspm.normalize import SAAS_INTEGRATION_OBJECT_TYPE
from aqelyn.trust import TrustAssessment


class IntegrationGraph(Protocol):
    async def subgraph(
        self,
        start_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> Subgraph: ...


class IntegrationTrustProvider(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


def integration_natural_key(descriptor: IntegrationDescriptor) -> NaturalKey:
    return NaturalKey(namespace="saas_integration", value=descriptor.integration_id)


async def existing_integration_object(
    object_store: ObjectStore,
    descriptor: IntegrationDescriptor,
    *,
    tenant_id: str | None,
) -> AQObject | None:
    rows, cursor = await object_store.query(
        ObjectQuery(
            tenant_id=tenant_id,
            object_type=SAAS_INTEGRATION_OBJECT_TYPE,
            natural_key=integration_natural_key(descriptor),
            include_states=("active", "archived"),
            limit=2,
        )
    )
    if cursor is not None or len(rows) > 1:
        raise SaaSConfigInvalid("SaaS integration natural key resolved to multiple objects")
    return None if not rows else rows[0]


async def require_integration_endpoints(
    object_store: ObjectStore,
    descriptor: IntegrationDescriptor,
    *,
    tenant_id: str | None,
) -> tuple[AQObject, AQObject]:
    if descriptor.grantor_ref == descriptor.third_party_app:
        raise SaaSConfigInvalid("integration grantor and third-party app must differ")
    grantor = await object_store.get(descriptor.grantor_ref, resolve_merged=False)
    third_party = await object_store.get(descriptor.third_party_app, resolve_merged=False)
    if grantor is None or third_party is None:
        raise SaaSConfigInvalid("integration relationship endpoint is unavailable")
    if grantor.tenant_id != tenant_id or third_party.tenant_id != tenant_id:
        raise CrossTenantReference("integration relationship endpoints must match tenant scope")
    return grantor, third_party


def integration_object(
    descriptor: IntegrationDescriptor,
    *,
    object_id: str,
    tenant_id: str | None,
    evidence_id: str,
    claim_confidence: float,
    actor: ActorRef,
) -> AQObject:
    source = SourceRef(
        source_id=descriptor.source_id,
        evidence_id=evidence_id,
        observed_at=descriptor.observed_at,
        method="sspm.map_integration/v1",
    )
    return AQObject(
        id=object_id,
        object_type=SAAS_INTEGRATION_OBJECT_TYPE,
        schema_version=1,
        tenant_id=tenant_id,
        display_name=f"SaaS integration {descriptor.integration_id}",
        attributes={
            "integration_id": descriptor.integration_id,
            "grantor_ref": descriptor.grantor_ref,
            "grantor_kind": descriptor.grantor_kind,
            "third_party_app": descriptor.third_party_app,
            "third_party_external": descriptor.third_party_external,
            "scopes": sorted(descriptor.scopes),
            "granted_by": descriptor.granted_by,
            "granted_at": (
                None if descriptor.granted_at is None else descriptor.granted_at.isoformat()
            ),
            "evidence_id": evidence_id,
        },
        labels={"module": "EA-0029", "kind": "saas_integration"},
        natural_keys=[integration_natural_key(descriptor)],
        sources=[source],
        confidence=claim_confidence,
        first_seen_at=descriptor.observed_at,
        last_seen_at=descriptor.observed_at,
        created_at=descriptor.observed_at,
        updated_at=descriptor.observed_at,
        created_by=actor,
        updated_by=actor,
    )


async def record_grant_edge(
    object_store: ObjectStore,
    descriptor: IntegrationDescriptor,
    *,
    integration_object_id: str,
    tenant_id: str | None,
    evidence_id: str,
    confidence: float,
    actor: ActorRef,
) -> AQRelationship:
    existing = await object_store.relationships(
        descriptor.grantor_ref,
        direction="out",
        relation_type="grants",
    )
    expected_scopes = sorted(descriptor.scopes)
    for relationship in existing:
        if (
            relationship.to_id == descriptor.third_party_app
            and relationship.attributes.get("integration_object_id") == integration_object_id
            and relationship.attributes.get("scopes") == expected_scopes
        ):
            return relationship
    source = SourceRef(
        source_id=descriptor.source_id,
        evidence_id=evidence_id,
        observed_at=descriptor.observed_at,
        method="sspm.map_integration/v1",
    )
    now = utc_now()
    return await object_store.relate(
        AQRelationship(
            id="",
            tenant_id=tenant_id,
            from_id=descriptor.grantor_ref,
            to_id=descriptor.third_party_app,
            relation_type="grants",
            attributes={
                "integration_object_id": integration_object_id,
                "scopes": expected_scopes,
                "observed_at": descriptor.observed_at.isoformat(),
            },
            sources=[source],
            confidence=confidence,
            created_at=now,
            updated_at=now,
            created_by=actor,
            updated_by=actor,
        )
    )


async def blast_radius(
    graph: IntegrationGraph,
    *,
    start_id: str,
    max_nodes: int,
) -> BlastRadius:
    result = await graph.subgraph(
        start_id,
        direction="both",
        max_nodes=max_nodes,
    )
    object_ids = sorted({node.id for node in result.nodes if node.id != start_id})
    return BlastRadius(object_ids=object_ids, truncated=result.truncated)


def scope_status(
    descriptor: IntegrationDescriptor,
    *,
    sensitive_scopes: Sequence[str],
) -> OverScopedStatus:
    if not descriptor.scopes:
        return "unknown"
    if descriptor.third_party_external and set(descriptor.scopes) & set(sensitive_scopes):
        return "over_scoped"
    return "within_scope"


def integration_reason(
    descriptor: IntegrationDescriptor,
    *,
    status: OverScopedStatus,
    reach_status: str,
    reachable_object_ids: Sequence[str],
) -> str:
    scopes = ", ".join(sorted(descriptor.scopes)) if descriptor.scopes else "unknown"
    return (
        f"Observed grant scopes: {scopes}; scope status: {status}; "
        f"reach status: {reach_status}; reachable objects: {len(reachable_object_ids)}."
    )


def integration_raw_content(descriptor: IntegrationDescriptor) -> dict[str, object]:
    return {
        "integration_id": descriptor.integration_id,
        "grantor_ref": descriptor.grantor_ref,
        "grantor_kind": descriptor.grantor_kind,
        "third_party_app": descriptor.third_party_app,
        "third_party_external": descriptor.third_party_external,
        "scopes": sorted(descriptor.scopes),
        "granted_by": descriptor.granted_by,
        "granted_at": (
            None if descriptor.granted_at is None else descriptor.granted_at.isoformat()
        ),
        "upstream_evidence_id": descriptor.evidence_id,
        "raw": copy.deepcopy(descriptor.raw),
    }
