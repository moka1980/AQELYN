"""Evidence-first ISPM normalization into EA-0011's object graph (EA-0033 G2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef, parse_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    EvidenceTampered,
    ISPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.inventory import AssetRecord, DiscoverySource, InventoryReport
from aqelyn.ispm.models import (
    ControlFact,
    IdentityAccessEdgeDescriptor,
    IdentityAccountDescriptor,
    IdentityControls,
    IdentityDescriptor,
    NormalizedIdentity,
)
from aqelyn.objects import AQObject, AQRelationship, NaturalKey, ObjectQuery, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.trust import TrustAssessment

IDENTITY_OBJECT_TYPE = "identity"
ACCOUNT_OBJECT_TYPE = "account"
HAS_ACCOUNT = "has_account"
_TARGET_TYPES: dict[str, frozenset[str]] = {
    "has_role": frozenset(("role",)),
    "grants_entitlement": frozenset(("entitlement",)),
    "member_of": frozenset(("role", "group")),
}


class TrustAssessor(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


class IdentityInventoryOwner(Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, object]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...

    async def inventory(self, *, tenant_id: str | None) -> InventoryReport: ...


class IdentityObjectStore(Protocol):
    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None: ...
    async def upsert(self, obj: AQObject) -> AQObject: ...
    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject: ...
    async def query(self, query: ObjectQuery) -> tuple[list[AQObject], str | None]: ...
    async def relate(self, rel: AQRelationship) -> AQRelationship: ...
    async def relationships(
        self,
        object_id: str,
        *,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[AQRelationship]: ...


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


@dataclass(frozen=True)
class PreparedIdentity:
    descriptor: IdentityDescriptor
    evidence: EvidenceRecord
    confidence: float
    account_evidence: dict[str, EvidenceRecord]
    account_confidence: dict[str, float]
    edge_evidence: dict[tuple[str, str, str], EvidenceRecord]
    edge_confidence: dict[tuple[str, str, str], float]


@dataclass(frozen=True)
class ReconciledIdentity:
    identity: NormalizedIdentity
    confidence: float
    incoming_won: bool


def ensure_identity_object_types(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        registry.register(IDENTITY_OBJECT_TYPE, 1, None)
        registry.register(ACCOUNT_OBJECT_TYPE, 1, None)
        return
    if registry is not None:
        selected = cast(_ObjectStoreRegistry, object_store)
        selected.registry.register(IDENTITY_OBJECT_TYPE, 1, None)
        selected.registry.register(ACCOUNT_OBJECT_TYPE, 1, None)


async def prepare_identity(
    descriptor: IdentityDescriptor,
    *,
    evidence_store: EvidenceStore,
    trust: TrustAssessor,
    actor: ActorRef,
    tenant_id: str | None,
) -> PreparedIdentity:
    if descriptor.evidence_id is None:
        raise ISPMConfigInvalid("identity descriptor requires evidence_id")
    evidence, confidence = await _verified_evidence(
        descriptor.evidence_id,
        source_id=descriptor.source_id,
        subject_ref=f"identity:{descriptor.provider}:{descriptor.external_id}",
        observed_at=descriptor.observed_at,
        evidence_store=evidence_store,
        trust=trust,
        actor=actor,
        tenant_id=tenant_id,
    )
    account_evidence: dict[str, EvidenceRecord] = {}
    account_confidence: dict[str, float] = {}
    for account in descriptor.accounts:
        record, score = await _verified_evidence(
            account.evidence_id,
            source_id=descriptor.source_id,
            subject_ref=f"account:{descriptor.provider}:{account.external_id}",
            observed_at=account.observed_at,
            evidence_store=evidence_store,
            trust=trust,
            actor=actor,
            tenant_id=tenant_id,
        )
        account_evidence[account.external_id] = record
        account_confidence[account.external_id] = score
    edge_evidence: dict[tuple[str, str, str], EvidenceRecord] = {}
    edge_confidence: dict[tuple[str, str, str], float] = {}
    for edge in descriptor.access_edges:
        key = _edge_key(edge)
        record, score = await _verified_evidence(
            edge.evidence_id,
            source_id=descriptor.source_id,
            subject_ref=f"identity-edge:{edge.from_external_id}:{edge.relation_type}:{edge.to_object_id}",
            observed_at=edge.observed_at,
            evidence_store=evidence_store,
            trust=trust,
            actor=actor,
            tenant_id=tenant_id,
        )
        edge_evidence[key] = record
        edge_confidence[key] = score
    return PreparedIdentity(
        descriptor=descriptor,
        evidence=evidence,
        confidence=confidence,
        account_evidence=account_evidence,
        account_confidence=account_confidence,
        edge_evidence=edge_evidence,
        edge_confidence=edge_confidence,
    )


def new_normalized_identity(
    prepared: PreparedIdentity,
    *,
    object_id: str,
    tenant_id: str | None,
) -> NormalizedIdentity:
    descriptor = prepared.descriptor
    kind = descriptor.identity_kind or "unknown"
    controls = normalize_controls(descriptor)
    provenance = {
        "identity_kind": descriptor.evidence_id or "unavailable",
        "controls.mfa": _control_provenance(controls.mfa),
        "controls.lifecycle": _control_provenance(controls.lifecycle),
        "controls.last_activity": _control_provenance(controls.last_activity),
    }
    return NormalizedIdentity(
        object_id=object_id,
        tenant_id=tenant_id,
        external_id=descriptor.external_id,
        provider=descriptor.provider,
        identity_kind=kind,
        controls=controls,
        field_provenance=provenance,
        conflicts=[],
        flagged=kind == "unknown",
        evidence_id=prepared.evidence.id,
    )


async def reconcile_identity(
    existing: NormalizedIdentity | None,
    incoming: NormalizedIdentity,
    *,
    incoming_evidence: EvidenceRecord,
    incoming_confidence: float,
    evidence_store: EvidenceStore,
    trust: TrustAssessor,
    actor: ActorRef,
    observed_at: datetime,
) -> ReconciledIdentity:
    if existing is None:
        return ReconciledIdentity(incoming, incoming_confidence, True)
    old_evidence = await evidence_store.get(existing.evidence_id, actor=actor)
    verification = await evidence_store.verify(existing.evidence_id)
    if not verification.ok:
        detail = verification.detail or "integrity verification failed"
        raise EvidenceTampered(
            f"stored ISPM identity evidence failed integrity verification: {detail}"
        )
    old_assessment = await trust.assess(
        f"identity:{existing.provider}:{existing.external_id}",
        [old_evidence],
        now=observed_at,
    )
    old_claim = _identity_claim(existing)
    new_claim = _identity_claim(incoming)
    incoming_won = _candidate_key(incoming_confidence, incoming_evidence) > _candidate_key(
        old_assessment.score,
        old_evidence,
    )
    winner = incoming if incoming_won else existing
    winner_confidence = incoming_confidence if incoming_won else old_assessment.score
    conflicts = list(existing.conflicts)
    if old_claim != new_claim:
        changed_fields = sorted(
            key for key in old_claim if old_claim.get(key) != new_claim.get(key)
        )
        unresolved = old_assessment.score == incoming_confidence
        winner_evidence = incoming_evidence if incoming_won else old_evidence
        conflict = {
            "fields": changed_fields,
            "candidates": sorted(
                (
                    _conflict_candidate(existing, old_evidence, old_assessment.score),
                    _conflict_candidate(incoming, incoming_evidence, incoming_confidence),
                ),
                key=lambda item: (str(item["source_id"]), str(item["evidence_id"])),
            ),
            "resolved_by": None if unresolved else winner_evidence.source_id,
            "resolved_evidence_id": None if unresolved else winner_evidence.id,
            "unresolved": unresolved,
            "reason": (
                "equal EA-0006 Trust confidence; deterministic content retained "
                "and conflict surfaced"
                if unresolved
                else "higher EA-0006 Trust confidence"
            ),
        }
        if conflict not in conflicts:
            conflicts.append(conflict)
    selected = winner.model_copy(
        update={
            "object_id": existing.object_id,
            "account_object_ids": sorted(
                set(existing.account_object_ids) | set(incoming.account_object_ids)
            ),
            "relationship_ids": sorted(
                set(existing.relationship_ids) | set(incoming.relationship_ids)
            ),
            "conflicts": conflicts,
            "flagged": winner.identity_kind == "unknown"
            or any(bool(conflict.get("unresolved")) for conflict in conflicts),
        },
        deep=True,
    )
    return ReconciledIdentity(selected, winner_confidence, incoming_won)


def identity_object(
    normalized: NormalizedIdentity,
    *,
    attributes: Mapping[str, Any],
    source: EvidenceRecord,
    confidence: float,
    actor: ActorRef,
    observed_at: datetime,
) -> AQObject:
    selected_attributes = dict(attributes)
    selected_attributes.update(
        {
            "external_id": normalized.external_id,
            "provider": normalized.provider,
            "identity_kind": normalized.identity_kind,
            "controls": normalized.controls.model_dump(mode="json"),
        }
    )
    flagged = normalized.identity_kind == "unknown" or any(
        bool(conflict.get("unresolved")) for conflict in normalized.conflicts
    )
    return _object(
        object_id=normalized.object_id,
        object_type=IDENTITY_OBJECT_TYPE,
        tenant_id=normalized.tenant_id,
        display_name=str(attributes.get("display_name") or normalized.external_id),
        attributes=selected_attributes,
        labels={
            "module": "EA-0033",
            "identity_kind": normalized.identity_kind,
            "flagged": str(flagged).lower(),
            "winning_source_id": source.source_id,
            "winning_evidence_id": source.id,
        },
        natural_key=NaturalKey(
            namespace=f"ispm:{normalized.provider}:identity",
            value=normalized.external_id,
        ),
        source=source,
        confidence=confidence,
        actor=actor,
        observed_at=observed_at,
    )


def account_object(
    descriptor: IdentityAccountDescriptor,
    *,
    provider: str,
    tenant_id: str | None,
    source: EvidenceRecord,
    confidence: float,
    actor: ActorRef,
) -> AQObject:
    attributes = dict(descriptor.attributes)
    attributes.update({"external_id": descriptor.external_id, "provider": provider})
    return _object(
        object_id="",
        object_type=ACCOUNT_OBJECT_TYPE,
        tenant_id=tenant_id,
        display_name=descriptor.display_name,
        attributes=attributes,
        labels={
            "module": "EA-0033",
            "provider": provider,
            "winning_source_id": source.source_id,
            "winning_evidence_id": source.id,
        },
        natural_key=NaturalKey(
            namespace=f"ispm:{provider}:account",
            value=descriptor.external_id,
        ),
        source=source,
        confidence=confidence,
        actor=actor,
        observed_at=descriptor.observed_at,
    )


def relationship(
    *,
    from_id: str,
    to_id: str,
    relation_type: str,
    tenant_id: str | None,
    source: EvidenceRecord,
    confidence: float,
    actor: ActorRef,
    observed_at: datetime,
) -> AQRelationship:
    now = utc_now()
    return AQRelationship(
        id="",
        tenant_id=tenant_id,
        from_id=from_id,
        to_id=to_id,
        relation_type=relation_type,
        attributes={"module": "EA-0033"},
        sources=[
            SourceRef(
                source_id=source.source_id,
                evidence_id=source.id,
                observed_at=observed_at,
                method="ispm.handed_in_descriptor/v1",
            )
        ],
        confidence=confidence,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
    )


def inventory_report(
    obj: AQObject,
    *,
    evidence_id: str,
) -> dict[str, object]:
    return {
        "id": inventory_ref(obj.id),
        "asset_type": obj.object_type,
        "lifecycle_state": "active",
        "evidence_id": evidence_id,
        "ref": f"ispm:{obj.object_type}:{obj.id}",
    }


def inventory_ref(object_id: str) -> str:
    prefix, payload = parse_id(object_id)
    if prefix != "obj":
        raise StoreUnavailable("EA-0002 identity object id must use obj_ prefix")
    return f"ast_{payload}"


def normalize_controls(descriptor: IdentityDescriptor) -> IdentityControls:
    return IdentityControls(
        mfa=_control_fact("mfa", descriptor),
        lifecycle=_control_fact("lifecycle", descriptor),
        last_activity=_control_fact("last_activity", descriptor),
    )


def validate_edge_target(edge: IdentityAccessEdgeDescriptor, target: AQObject) -> None:
    allowed = _TARGET_TYPES[edge.relation_type]
    if target.object_type not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ISPMConfigInvalid(
            f"{edge.relation_type} target must be one of [{expected}], got {target.object_type!r}"
        )


def _object(
    *,
    object_id: str,
    object_type: str,
    tenant_id: str | None,
    display_name: str,
    attributes: dict[str, Any],
    labels: dict[str, str],
    natural_key: NaturalKey,
    source: EvidenceRecord,
    confidence: float,
    actor: ActorRef,
    observed_at: datetime,
) -> AQObject:
    now = utc_now()
    return AQObject(
        id=object_id,
        object_type=object_type,
        schema_version=1,
        tenant_id=tenant_id,
        display_name=display_name,
        attributes=attributes,
        labels=labels,
        natural_keys=[natural_key],
        sources=[
            SourceRef(
                source_id=source.source_id,
                evidence_id=source.id,
                observed_at=observed_at,
                method="ispm.handed_in_descriptor/v1",
            )
        ],
        confidence=confidence,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
    )


async def _verified_evidence(
    evidence_id: str,
    *,
    source_id: str,
    subject_ref: str,
    observed_at: datetime,
    evidence_store: EvidenceStore,
    trust: TrustAssessor,
    actor: ActorRef,
    tenant_id: str | None,
) -> tuple[EvidenceRecord, float]:
    evidence = await evidence_store.get(evidence_id, actor=actor)
    verification = await evidence_store.verify(evidence_id)
    if evidence.tenant_id != tenant_id:
        raise CrossTenantReference("ISPM evidence tenant does not match request tenant")
    if evidence.source_id != source_id:
        raise ISPMConfigInvalid("ISPM evidence source does not match descriptor source")
    if not verification.ok:
        detail = verification.detail or "integrity verification failed"
        raise EvidenceTampered(
            f"ISPM descriptor evidence failed integrity verification: {detail}",
            details={"evidence_id": evidence_id, "verification_detail": detail},
        )
    assessment = await trust.assess(subject_ref, [evidence], now=observed_at)
    return evidence, assessment.score


def _control_fact(name: str, descriptor: IdentityDescriptor) -> ControlFact:
    raw = descriptor.controls.get(name)
    if raw is None:
        return ControlFact(reason=f"{name} was not supplied by the identity source.")
    if isinstance(raw, bool):
        state = "present" if raw else "absent"
    elif isinstance(raw, str) and raw.strip().lower() in {"present", "absent"}:
        state = raw.strip().lower()
    elif name == "lifecycle" and isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"active", "enabled"}:
            state = "present"
        elif lowered in {"inactive", "disabled", "deleted"}:
            state = "absent"
        else:
            return ControlFact(reason=f"{name} value could not be normalized.")
    elif name == "last_activity" and isinstance(raw, str) and raw.strip():
        state = "present"
    else:
        return ControlFact(reason=f"{name} value could not be normalized.")
    return ControlFact(
        state=state,
        established_by=f"{descriptor.provider}:{descriptor.source_id}",
        evidence_id=descriptor.evidence_id,
        reason=f"The handed-in {descriptor.provider} descriptor established {name} as {state}.",
    )


def _control_provenance(control: ControlFact) -> str:
    return control.evidence_id or f"unknown:{control.reason}"


def _identity_claim(identity: NormalizedIdentity) -> dict[str, object]:
    return {
        "identity_kind": identity.identity_kind,
        "controls": identity.controls.model_dump(mode="json"),
    }


def _candidate_key(confidence: float, evidence: EvidenceRecord) -> tuple[float, str, str]:
    return confidence, evidence.source_id, evidence.id


def _conflict_candidate(
    identity: NormalizedIdentity,
    evidence: EvidenceRecord,
    confidence: float,
) -> dict[str, object]:
    return {
        "value": _identity_claim(identity),
        "source_id": evidence.source_id,
        "evidence_id": evidence.id,
        "observed_at": evidence.collected_at.isoformat(),
        "reliability": confidence,
    }


def _edge_key(edge: IdentityAccessEdgeDescriptor) -> tuple[str, str, str]:
    return edge.from_external_id, edge.to_object_id, edge.relation_type
