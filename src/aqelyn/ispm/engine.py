"""Identity Security Posture Management engine (EA-0033 G2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aqelyn.conventions import ActorRef, new_id, require_tenant_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    IdentityNotFound,
    ISPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.evidence import EvidenceStore
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.iag import AccessPath, AccessRiskReport, Certification
from aqelyn.inventory import DiscoverySource
from aqelyn.ispm.governance import (
    IdentityGovernanceOwner,
    complete_certification,
    decide_certification_item,
    governance_context,
    identity_access_paths,
    open_certification,
    risks_to_findings,
)
from aqelyn.ispm.models import IdentityDescriptor, ISPMConfig, NormalizedIdentity
from aqelyn.ispm.normalize import (
    HAS_ACCOUNT,
    IdentityInventoryOwner,
    IdentityObjectStore,
    PreparedIdentity,
    TrustAssessor,
    account_object,
    ensure_identity_object_types,
    identity_object,
    inventory_report,
    new_normalized_identity,
    prepare_identity,
    reconcile_identity,
    relationship,
    validate_edge_target,
)
from aqelyn.ispm.store import ISPMStore
from aqelyn.objects import AQObject, AQRelationship, NaturalKey, ObjectQuery

_ISPM_ACTOR = ActorRef(actor_type="system", actor_id="ispm_engine")


class ISPMEngine:
    def __init__(
        self,
        store: ISPMStore,
        *,
        object_store: IdentityObjectStore,
        inventory: IdentityInventoryOwner,
        evidence_store: EvidenceStore,
        trust: TrustAssessor,
        governance_owner: IdentityGovernanceOwner | None = None,
        config: ISPMConfig | None = None,
        actor: ActorRef | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.trust = trust
        self.governance_owner = governance_owner
        self.config = config or ISPMConfig()
        self.actor = actor or _ISPM_ACTOR
        ensure_identity_object_types(object_store)

    async def governance_context(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> AccessRiskReport:
        selected_tenant = require_tenant_id(tenant_id)
        identity = await self.store.get_identity(object_id, tenant_id=selected_tenant)
        if identity is None:
            raise IdentityNotFound(object_id)
        return await governance_context(
            self._governance_owner(),
            tenant_id=selected_tenant,
            scope=ObjectQuery(
                tenant_id=selected_tenant,
                limit=self.config.page_budget,
            ),
        )

    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None,
    ) -> list[AccessPath]:
        selected_tenant = require_tenant_id(tenant_id)
        identity = await self.store.get_identity(identity_id, tenant_id=selected_tenant)
        if identity is None:
            raise IdentityNotFound(identity_id)
        return await identity_access_paths(
            self._governance_owner(),
            identity_id,
            tenant_id=selected_tenant,
        )

    async def open_certification(
        self,
        *,
        tenant_id: str | None,
        name: str,
        scope: ObjectQuery,
        by: ActorRef,
        due_days: int | None = None,
    ) -> Certification:
        return await open_certification(
            self._governance_owner(),
            tenant_id=require_tenant_id(tenant_id),
            name=name,
            scope=scope,
            by=by,
            due_days=due_days,
        )

    async def decide_certification_item(
        self,
        cert_id: str,
        item_id: str,
        *,
        decision: str,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Certification:
        return await decide_certification_item(
            self._governance_owner(),
            cert_id,
            item_id,
            decision=decision,
            by=by,
            note=note,
            expected_version=expected_version,
        )

    async def complete_certification(
        self,
        cert_id: str,
        *,
        by: ActorRef,
        raise_findings: bool = True,
    ) -> list[str]:
        return await complete_certification(
            self._governance_owner(),
            cert_id,
            by=by,
            raise_findings=raise_findings,
        )

    async def risks_to_findings(
        self,
        report: AccessRiskReport,
        *,
        by: ActorRef,
        prioritize: bool = True,
    ) -> list[str]:
        return await risks_to_findings(
            self._governance_owner(),
            report,
            by=by,
            prioritize=prioritize,
        )

    def _governance_owner(self) -> IdentityGovernanceOwner:
        if self.governance_owner is None:
            raise StoreUnavailable("EA-0011 governance owner is unavailable")
        return self.governance_owner

    async def ingest_identities(
        self,
        descriptors: Sequence[IdentityDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[NormalizedIdentity]:
        selected_tenant = require_tenant_id(tenant_id)
        if len(descriptors) > self.config.batch_size:
            raise ISPMConfigInvalid(
                "identity descriptor count exceeds batch_size; partial acceptance is forbidden"
            )
        prepared = [
            await prepare_identity(
                descriptor,
                evidence_store=self.evidence_store,
                trust=self.trust,
                actor=self.actor,
                tenant_id=selected_tenant,
            )
            for descriptor in descriptors
        ]
        await self._validate_edge_targets(prepared, tenant_id=selected_tenant)
        stored = [await self._persist(item, tenant_id=selected_tenant) for item in prepared]
        return [item.model_copy(deep=True) for item in stored]

    async def _persist(
        self,
        prepared: PreparedIdentity,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity:
        descriptor = prepared.descriptor
        existing = await self.store.get_identity_by_external(
            descriptor.provider,
            descriptor.external_id,
            tenant_id=tenant_id,
        )
        incoming = new_normalized_identity(
            prepared,
            object_id=existing.object_id if existing is not None else new_id("obj"),
            tenant_id=tenant_id,
        )
        reconciled = await reconcile_identity(
            existing,
            incoming,
            incoming_evidence=prepared.evidence,
            incoming_confidence=prepared.confidence,
            evidence_store=self.evidence_store,
            trust=self.trust,
            actor=self.actor,
            observed_at=descriptor.observed_at,
        )
        current_object = (
            None
            if existing is None
            else await self.object_store.get(existing.object_id, resolve_merged=False)
        )
        selected_attributes = (
            descriptor.attributes
            if reconciled.incoming_won or current_object is None
            else current_object.attributes
        )
        selected_evidence = (
            prepared.evidence
            if reconciled.incoming_won
            else await self.evidence_store.get(reconciled.identity.evidence_id, actor=self.actor)
        )
        saved_identity = await self._upsert_object(
            identity_object(
                reconciled.identity,
                attributes=selected_attributes,
                source=selected_evidence,
                confidence=reconciled.confidence,
                actor=self.actor,
                observed_at=selected_evidence.collected_at,
            ),
            selected_confidence=reconciled.confidence,
        )
        if saved_identity.id != reconciled.identity.object_id:
            raise StoreUnavailable("EA-0002 identity changed across ISPM ingest")

        account_ids = set(reconciled.identity.account_object_ids)
        relationship_ids = set(reconciled.identity.relationship_ids)
        conflicts = list(reconciled.identity.conflicts)
        local_objects: dict[str, AQObject] = {descriptor.external_id: saved_identity}
        inventory_rows: list[dict[str, object]] = [
            inventory_report(saved_identity, evidence_id=prepared.evidence.id)
        ]
        for account in descriptor.accounts:
            evidence = prepared.account_evidence[account.external_id]
            confidence = prepared.account_confidence[account.external_id]
            account_candidate = account_object(
                account,
                provider=descriptor.provider,
                tenant_id=tenant_id,
                source=evidence,
                confidence=confidence,
                actor=self.actor,
            )
            selected_account, account_conflict = await self._reconcile_account(
                account_candidate,
                external_id=account.external_id,
                incoming_source=evidence,
                incoming_confidence=confidence,
                tenant_id=tenant_id,
            )
            if account_conflict is not None and account_conflict not in conflicts:
                conflicts.append(account_conflict)
            saved_account = await self._upsert_object(
                selected_account,
                selected_confidence=selected_account.confidence,
            )
            local_objects[account.external_id] = saved_account
            account_ids.add(saved_account.id)
            rel = await self._ensure_relationship(
                from_id=saved_identity.id,
                to_id=saved_account.id,
                relation_type=HAS_ACCOUNT,
                tenant_id=tenant_id,
                source=evidence,
                confidence=confidence,
                observed_at=account.observed_at,
            )
            relationship_ids.add(rel.id)
            inventory_rows.append(inventory_report(saved_account, evidence_id=evidence.id))

        for edge in descriptor.access_edges:
            source_object = local_objects[edge.from_external_id]
            target = await self.object_store.get(edge.to_object_id, resolve_merged=False)
            if target is None:
                raise ISPMConfigInvalid(f"access edge target does not exist: {edge.to_object_id}")
            if target.tenant_id != tenant_id:
                raise CrossTenantReference("ISPM access edge target belongs to another tenant")
            validate_edge_target(edge, target)
            key = (edge.from_external_id, edge.to_object_id, edge.relation_type)
            rel = await self._ensure_relationship(
                from_id=source_object.id,
                to_id=target.id,
                relation_type=edge.relation_type,
                tenant_id=tenant_id,
                source=prepared.edge_evidence[key],
                confidence=prepared.edge_confidence[key],
                observed_at=edge.observed_at,
            )
            relationship_ids.add(rel.id)

        final = reconciled.identity.model_copy(
            update={
                "account_object_ids": sorted(account_ids),
                "relationship_ids": sorted(relationship_ids),
                "conflicts": conflicts,
                "flagged": reconciled.identity.identity_kind == "unknown"
                or any(bool(conflict.get("unresolved")) for conflict in conflicts),
            },
            deep=True,
        )
        inventory_assets = await self.inventory.ingest(
            reports=inventory_rows,
            source=DiscoverySource(
                source_id=prepared.evidence.source_id,
                reliability=prepared.confidence,
                health="ok",
                as_of=descriptor.observed_at,
            ),
            tenant_id=tenant_id,
        )
        expected_inventory_ids = {str(row["id"]) for row in inventory_rows}
        if {asset.id for asset in inventory_assets} != expected_inventory_ids:
            raise StoreUnavailable("EA-0025 inventory did not accept every ISPM object")
        return await self.store.upsert_identity(final)

    async def _validate_edge_targets(
        self,
        prepared: Sequence[PreparedIdentity],
        *,
        tenant_id: str | None,
    ) -> None:
        for item in prepared:
            for edge in item.descriptor.access_edges:
                target = await self.object_store.get(edge.to_object_id, resolve_merged=False)
                if target is None:
                    raise ISPMConfigInvalid(
                        f"access edge target does not exist: {edge.to_object_id}"
                    )
                if target.tenant_id != tenant_id:
                    raise CrossTenantReference("ISPM access edge target belongs to another tenant")
                validate_edge_target(edge, target)

    async def _reconcile_account(
        self,
        incoming: AQObject,
        *,
        external_id: str,
        incoming_source: EvidenceRecord,
        incoming_confidence: float,
        tenant_id: str | None,
    ) -> tuple[AQObject, dict[str, object] | None]:
        rows, cursor = await self.object_store.query(
            ObjectQuery(
                tenant_id=tenant_id,
                object_type="account",
                natural_key=NaturalKey(
                    namespace=f"ispm:{incoming.attributes['provider']}:account",
                    value=external_id,
                ),
                limit=2,
            )
        )
        if cursor is not None or len(rows) > 1:
            raise StoreUnavailable("EA-0002 returned ambiguous ISPM account identity")
        if not rows:
            return incoming, None
        existing = rows[0]
        old_source_id = existing.labels.get("winning_source_id")
        old_evidence_id = existing.labels.get("winning_evidence_id")
        if old_source_id is None or old_evidence_id is None:
            raise StoreUnavailable("stored ISPM account is missing winner provenance")
        incoming_won = (
            incoming_confidence,
            incoming_source.source_id,
            incoming_source.id,
        ) > (existing.confidence, old_source_id, old_evidence_id)
        unresolved = incoming_confidence == existing.confidence
        selected = (
            incoming
            if incoming_won
            else incoming.model_copy(
                update={
                    "display_name": existing.display_name,
                    "attributes": dict(existing.attributes),
                    "labels": dict(existing.labels),
                    "confidence": existing.confidence,
                },
                deep=True,
            )
        )
        old_claim = {
            "display_name": existing.display_name,
            "attributes": existing.attributes,
        }
        new_claim = {
            "display_name": incoming.display_name,
            "attributes": incoming.attributes,
        }
        if old_claim == new_claim:
            return selected, None
        winner_source = incoming_source.source_id if incoming_won else old_source_id
        winner_evidence = incoming_source.id if incoming_won else old_evidence_id
        return selected, {
            "fields": [f"accounts.{external_id}"],
            "candidates": sorted(
                (
                    {
                        "value": old_claim,
                        "source_id": old_source_id,
                        "evidence_id": old_evidence_id,
                        "reliability": existing.confidence,
                    },
                    {
                        "value": new_claim,
                        "source_id": incoming_source.source_id,
                        "evidence_id": incoming_source.id,
                        "reliability": incoming_confidence,
                    },
                ),
                key=lambda item: (str(item["source_id"]), str(item["evidence_id"])),
            ),
            "resolved_by": None if unresolved else winner_source,
            "resolved_evidence_id": None if unresolved else winner_evidence,
            "unresolved": unresolved,
            "reason": (
                "equal EA-0006 Trust confidence; deterministic account retained "
                "and conflict surfaced"
                if unresolved
                else "higher EA-0006 Trust confidence"
            ),
        }

    async def _upsert_object(
        self,
        obj: AQObject,
        *,
        selected_confidence: float,
    ) -> AQObject:
        saved = await self.object_store.upsert(obj)
        if saved.confidence == selected_confidence:
            return saved
        return await self.object_store.update(
            saved.model_copy(update={"confidence": selected_confidence}, deep=True),
            expected_version=saved.version,
        )

    async def _ensure_relationship(
        self,
        *,
        from_id: str,
        to_id: str,
        relation_type: str,
        tenant_id: str | None,
        source: EvidenceRecord,
        confidence: float,
        observed_at: datetime,
    ) -> AQRelationship:
        existing = await self.object_store.relationships(
            from_id,
            direction="out",
            relation_type=relation_type,
        )
        for rel in existing:
            if rel.to_id == to_id:
                return rel
        return await self.object_store.relate(
            relationship(
                from_id=from_id,
                to_id=to_id,
                relation_type=relation_type,
                tenant_id=tenant_id,
                source=source,
                confidence=confidence,
                actor=self.actor,
                observed_at=observed_at,
            )
        )
