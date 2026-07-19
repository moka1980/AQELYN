"""Supply-chain SBOM, dependency, provenance, and owner routing (EA-0030 Q2-Q5)."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef, new_id, parse_id, require_tenant_id, utc_now
from aqelyn.conventions.errors import (
    AQError,
    ComponentNotFound,
    ObjectNotFound,
    SBOMParseError,
    StoreUnavailable,
    SupplyChainConfigInvalid,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.graph import KnowledgeGraph, Path
from aqelyn.inventory import AssetRecord, DiscoverySource
from aqelyn.objects import AQObject, AQRelationship, NaturalKey, ObjectStore, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.policy.models import ComplianceResult
from aqelyn.risk.models import RiskSnapshot
from aqelyn.supplychain.models import (
    ComponentConflict,
    ComponentConflictCandidate,
    DependencyPathResult,
    DependencyRelationship,
    ProvenanceAttestation,
    ProvenanceResult,
    ProvenanceStatus,
    QuarantinedSBOM,
    ReachabilitySignal,
    SBOMDocument,
    SoftwareComponent,
    SupplyChainAssessment,
    SupplyChainConfig,
    path_ref,
)
from aqelyn.supplychain.parse import parse_sbom
from aqelyn.supplychain.provenance import ProvenanceVerifier, verify_attestation
from aqelyn.supplychain.store import SBOMStore
from aqelyn.trust import SourceReliabilityRegistry
from aqelyn.vuln import PriorityFactor, VulnerabilityRecord, VulnerabilityStore, VulnPriority
from aqelyn.workflow import Playbook, Run, Step

SOFTWARE_COMPONENT_OBJECT_TYPE = "software_component"
_SUPPLYCHAIN_ACTOR = ActorRef(actor_type="system", actor_id="supplychain_engine")


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


def ensure_supplychain_object_type(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        registry.register(SOFTWARE_COMPONENT_OBJECT_TYPE, 1, None)
        return
    if registry is not None:
        cast(_ObjectStoreRegistry, object_store).registry.register(
            SOFTWARE_COMPONENT_OBJECT_TYPE,
            1,
            None,
        )


class ComponentInventoryOwner(Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...


class ComponentVulnerabilityPrioritizer(Protocol):
    async def prioritize(
        self,
        vulnerability_id: str,
        *,
        tenant_id: str | None,
        exposure_override: PriorityFactor | None = None,
    ) -> VulnPriority: ...

    async def raise_vulnerability(self, priority: VulnPriority, *, by: ActorRef) -> Finding: ...


class LicensePolicyEvaluator(Protocol):
    async def evaluate_compliance(
        self,
        resource: dict[str, Any],
        *,
        tenant_id: str | None,
        policy_ids: set[str] | None = None,
    ) -> ComplianceResult: ...


class SupplyChainRiskAggregator(Protocol):
    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> RiskSnapshot: ...


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class SupplyChainEngine:
    def __init__(
        self,
        store: SBOMStore,
        *,
        inventory: ComponentInventoryOwner,
        source_registry: SourceReliabilityRegistry,
        object_store: ObjectStore,
        graph: KnowledgeGraph,
        evidence_store: EvidenceStore,
        provenance_verifier: ProvenanceVerifier | None = None,
        vulnerability_store: VulnerabilityStore | None = None,
        vulnerability_owner: ComponentVulnerabilityPrioritizer | None = None,
        license_policy_owner: LicensePolicyEvaluator | None = None,
        finding_store: FindingStore | None = None,
        risk_owner: SupplyChainRiskAggregator | None = None,
        workflow_engine: WorkflowProposer | None = None,
        config: SupplyChainConfig | None = None,
    ) -> None:
        self.store = store
        self.inventory = inventory
        self.source_registry = source_registry
        self.object_store = object_store
        self.graph = graph
        self.evidence_store = evidence_store
        self.provenance_verifier = provenance_verifier
        self.vulnerability_store = vulnerability_store
        self.vulnerability_owner = vulnerability_owner
        self.license_policy_owner = license_policy_owner
        self.finding_store = finding_store
        self.risk_owner = risk_owner
        self.workflow_engine = workflow_engine
        self.config = config or SupplyChainConfig()
        ensure_supplychain_object_type(object_store)

    async def ingest_sbom(
        self,
        doc: SBOMDocument,
        *,
        tenant_id: str | None,
    ) -> list[SoftwareComponent]:
        selected_tenant = require_tenant_id(tenant_id)
        try:
            parsed = parse_sbom(doc, tenant_id=selected_tenant)
            if len(parsed.components) > self.config.batch_size:
                raise SBOMParseError(
                    "SBOM component count exceeds the configured batch_size; "
                    "partial acceptance is forbidden"
                )
        except SBOMParseError as exc:
            await self.store.quarantine(
                QuarantinedSBOM(
                    doc_id=doc.doc_id,
                    tenant_id=selected_tenant,
                    source_id=doc.source_id,
                    observed_at=doc.observed_at,
                    evidence_id=doc.evidence_id,
                    raw=copy.deepcopy(doc.raw),
                    reason=str(exc),
                    quarantined_at=utc_now(),
                )
            )
            raise

        incoming_reliability = (await self.source_registry.get(source_id=doc.source_id)).weight
        stored: list[SoftwareComponent] = []
        for component in parsed.components:
            existing = await self.store.get_component(
                component.purl,
                tenant_id=selected_tenant,
            )
            if existing is None:
                selected = component.model_copy(update={"object_id": new_id("obj")}, deep=True)
            else:
                selected = await self._reconcile(
                    existing,
                    component,
                    incoming_reliability=incoming_reliability,
                )
            stored.append(await self.store.put_component(selected))

        await self._materialize_dependency_graph(
            stored,
            parsed.relationships,
            doc=doc,
            relationship_confidence=incoming_reliability,
        )

        for component in stored:
            reliability = (await self.source_registry.get(source_id=component.source_id)).weight
            assets = await self.inventory.ingest(
                reports=[_inventory_report(component)],
                source=DiscoverySource(
                    source_id=component.source_id,
                    reliability=reliability,
                    health="ok",
                    as_of=component.observed_at,
                ),
                tenant_id=selected_tenant,
            )
            if len(assets) != 1:
                raise StoreUnavailable(
                    "EA-0025 inventory did not accept a parsed software component"
                )
        return [component.model_copy(deep=True) for component in stored]

    async def dependency_paths(
        self,
        purl: str,
        *,
        direction: str,
        tenant_id: str | None,
    ) -> DependencyPathResult:
        selected_tenant = require_tenant_id(tenant_id)
        if direction not in {"up", "down"}:
            raise SupplyChainConfigInvalid("dependency direction must be 'up' or 'down'")
        component = await self.store.get_component(purl, tenant_id=selected_tenant)
        if component is None:
            raise ComponentNotFound(purl)
        result = await self.graph.impact(
            component.object_id,
            direction="in" if direction == "up" else "out",
            relation_types=("depends_on",),
            max_depth=self.config.max_depth,
            max_nodes=self.config.batch_size,
        )
        return DependencyPathResult(
            paths=[hit.via.model_copy(deep=True) for hit in result.hits],
            truncated=result.truncated,
        )

    async def reachability(
        self,
        component_purl: str,
        cve_id: str,
        *,
        tenant_id: str | None,
    ) -> ReachabilitySignal:
        selected_tenant = require_tenant_id(tenant_id)
        try:
            component = await self.store.get_component(component_purl, tenant_id=selected_tenant)
        except AQError as exc:
            if not exc.retriable:
                raise
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason=f"component catalog unavailable: {exc.code}",
            )
        if component is None:
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason="component is not cataloged; reachability was not computed",
            )
        if component.direct:
            return ReachabilitySignal(
                component_purl=component_purl,
                cve_id=cve_id,
                reachable="direct",
                depth=0,
                reason="the SBOM identifies the component as a direct dependency",
            )

        try:
            result = await self.dependency_paths(
                component_purl,
                direction="up",
                tenant_id=selected_tenant,
            )
            direct_paths: list[Path] = []
            for candidate in result.paths:
                if not candidate.node_ids:
                    continue
                ancestor = await self.object_store.get(
                    candidate.node_ids[-1],
                    resolve_merged=False,
                )
                if ancestor is not None and ancestor.attributes.get("direct") is True:
                    direct_paths.append(_forward_dependency_path(candidate))
        except (ObjectNotFound, StoreUnavailable) as exc:
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason=f"reachability owner unavailable: {exc.code}",
            )
        except AQError as exc:
            if not exc.retriable:
                raise
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason=f"reachability owner unavailable: {exc.code}",
            )

        if direct_paths:
            selected_path = min(
                direct_paths,
                key=lambda item: (item.length, item.node_ids, [edge.id for edge in item.edges]),
            )
            return ReachabilitySignal(
                component_purl=component_purl,
                cve_id=cve_id,
                reachable="transitive",
                depth=selected_path.length,
                path_ref=path_ref(selected_path),
                path=selected_path,
                reason=(
                    "an EA-0005 dependency path connects a direct component to the "
                    "vulnerable transitive component"
                ),
            )
        if result.truncated:
            return _unknown_reachability(
                component_purl,
                cve_id,
                reason="EA-0005 traversal was truncated before reachability could be disproved",
            )
        return ReachabilitySignal(
            component_purl=component_purl,
            cve_id=cve_id,
            reachable="unreachable",
            reason="complete EA-0005 traversal found no path from a direct component",
        )

    async def verify_provenance(
        self,
        attestations: Sequence[ProvenanceAttestation],
        *,
        tenant_id: str | None,
    ) -> list[ProvenanceResult]:
        selected_tenant = require_tenant_id(tenant_id)
        if len(attestations) > self.config.batch_size:
            raise SupplyChainConfigInvalid(
                "provenance attestation count exceeds the configured batch_size"
            )

        results: list[ProvenanceResult] = []
        components: dict[str, SoftwareComponent] = {}
        statuses: dict[str, list[ProvenanceStatus]] = {}
        for attestation in attestations:
            component = components.get(attestation.component_purl)
            if component is None:
                component = await self.store.get_component(
                    attestation.component_purl,
                    tenant_id=selected_tenant,
                )
                if component is None:
                    raise ComponentNotFound(attestation.component_purl)
                components[attestation.component_purl] = component
            result = await verify_attestation(
                attestation,
                component=component,
                evidence_store=self.evidence_store,
                verifier=self.provenance_verifier,
                actor=_SUPPLYCHAIN_ACTOR,
            )
            results.append(result)
            statuses.setdefault(component.purl, []).append(result.status)

        for purl in sorted(statuses):
            component = components[purl]
            status = _aggregate_provenance_status(statuses[purl])
            updated = await self.store.put_component(
                component.model_copy(update={"provenance_status": status}, deep=True)
            )
            confidence = (await self.source_registry.get(source_id=updated.source_id)).weight
            stored_object = await self.object_store.upsert(
                _component_object(updated, confidence=confidence)
            )
            if stored_object.id != updated.object_id:
                raise StoreUnavailable(
                    "EA-0002 resolved the component purl to a different object id"
                )
            assets = await self.inventory.ingest(
                reports=[_inventory_report(updated)],
                source=DiscoverySource(
                    source_id=updated.source_id,
                    reliability=confidence,
                    health="ok",
                    as_of=updated.observed_at,
                ),
                tenant_id=selected_tenant,
            )
            if len(assets) != 1:
                raise StoreUnavailable(
                    "EA-0025 inventory did not accept a provenance status update"
                )
        return [result.model_copy(deep=True) for result in results]

    async def component_vulns_to_prioritization(
        self,
        purls: Sequence[str],
        *,
        tenant_id: str | None,
        by: ActorRef,
    ) -> list[str]:
        selected_tenant = require_tenant_id(tenant_id)
        if self.vulnerability_store is None or self.vulnerability_owner is None:
            raise StoreUnavailable("EA-0024 vulnerability routing is unavailable")
        components = await self._components_for_purls(purls, tenant_id=selected_tenant)
        vulnerabilities = await self._component_vulnerabilities(
            components,
            tenant_id=selected_tenant,
        )
        by_object_id = {component.object_id: component for component in components}
        finding_ids: list[str] = []
        for vulnerability in vulnerabilities:
            component = by_object_id[vulnerability.asset_ref.ref_id]
            signal = await self.reachability(
                component.purl,
                vulnerability.cve_id,
                tenant_id=selected_tenant,
            )
            priority = await self.vulnerability_owner.prioritize(
                vulnerability.id,
                tenant_id=selected_tenant,
                exposure_override=_reachability_factor(signal),
            )
            finding = await self.vulnerability_owner.raise_vulnerability(priority, by=by)
            finding_ids.append(finding.id)
        return finding_ids

    async def license_findings(
        self,
        *,
        tenant_id: str | None,
        by: ActorRef,
    ) -> list[str]:
        selected_tenant = require_tenant_id(tenant_id)
        if self.config.license_policy_id is None:
            raise SupplyChainConfigInvalid(
                "license_policy_id is not configured; refusing to report licenses compliant"
            )
        if self.license_policy_owner is None or self.finding_store is None:
            raise StoreUnavailable("EA-0010 license compliance routing is unavailable")
        components, next_cursor = await self.store.query(
            tenant_id=selected_tenant,
            limit=self.config.batch_size,
        )
        if next_cursor is not None:
            raise StoreUnavailable(
                "license assessment exceeds the configured batch_size; refusing partial findings"
            )

        finding_ids: list[str] = []
        for component in components:
            result = await self.license_policy_owner.evaluate_compliance(
                _license_resource(component),
                tenant_id=selected_tenant,
                policy_ids={self.config.license_policy_id},
            )
            if result.evaluated == 0:
                raise StoreUnavailable(
                    "EA-0010 evaluated no license policy rules; compliance is unknown"
                )
            if result.compliant:
                continue
            evidence = await self.evidence_store.add(
                _license_evidence(
                    component,
                    result=result,
                    policy_id=self.config.license_policy_id,
                    by=by,
                )
            )
            finding = await self.finding_store.raise_finding(
                _license_finding(
                    component,
                    result=result,
                    policy_id=self.config.license_policy_id,
                    evidence_id=evidence.id,
                    by=by,
                )
            )
            finding_ids.append(finding.id)
        return finding_ids

    async def aggregate_risk(self, *, tenant_id: str | None) -> str:
        selected_tenant = require_tenant_id(tenant_id)
        if self.risk_owner is None:
            raise StoreUnavailable("EA-0013 supply-chain risk aggregation is unavailable")
        snapshot = await self.risk_owner.assess(
            tenant_id=selected_tenant,
            scope={"limit": self.config.batch_size},
        )
        return snapshot.id

    async def propose_remediation(
        self,
        component_purl: str,
        *,
        action: str,
        tenant_id: str | None,
        by: ActorRef,
    ) -> str:
        selected_tenant = require_tenant_id(tenant_id)
        if action not in {"upgrade", "remove"}:
            raise SupplyChainConfigInvalid("remediation action must be upgrade or remove")
        if self.workflow_engine is None:
            raise StoreUnavailable("EA-0008 workflow proposal path is unavailable")
        component = await self.store.get_component(component_purl, tenant_id=selected_tenant)
        if component is None:
            raise ComponentNotFound(component_purl)
        run = await self.workflow_engine.propose(
            _remediation_playbook(component, action=action),
            by=by,
        )
        return run.id

    async def assess(
        self,
        *,
        subject_ref: str,
        tenant_id: str | None,
    ) -> SupplyChainAssessment:
        selected_tenant = require_tenant_id(tenant_id)
        components, next_cursor = await self.store.query(
            tenant_id=selected_tenant,
            limit=self.config.batch_size,
        )
        vulnerabilities, vulnerabilities_truncated = await self._assessment_vulnerabilities(
            components,
            tenant_id=selected_tenant,
        )
        vulnerable_object_ids = {item.asset_ref.ref_id for item in vulnerabilities}
        status = "truncated" if next_cursor is not None or vulnerabilities_truncated else "complete"
        run_at = utc_now()
        evidence = await self.evidence_store.add(
            _assessment_evidence(
                components,
                vulnerable_object_ids=vulnerable_object_ids,
                subject_ref=subject_ref,
                tenant_id=selected_tenant,
                run_at=run_at,
                status=status,
            )
        )
        assessment = SupplyChainAssessment(
            tenant_id=selected_tenant,
            run_at=run_at,
            subject_ref=subject_ref,
            components=len(components),
            direct=sum(1 for component in components if component.direct),
            transitive=sum(1 for component in components if not component.direct),
            unverified_provenance=sum(
                1 for component in components if component.provenance_status != "verified"
            ),
            vulnerable_components=len(vulnerable_object_ids),
            assessment_status=status,
            evidence_id=evidence.id,
        )
        return await self.store.put_assessment(assessment)

    def explain(self, signal: ReachabilitySignal) -> dict[str, object]:
        return signal.model_dump(mode="json")

    async def _components_for_purls(
        self,
        purls: Sequence[str],
        *,
        tenant_id: str | None,
    ) -> list[SoftwareComponent]:
        selected = sorted(set(purls))
        if len(selected) > self.config.batch_size:
            raise SupplyChainConfigInvalid("purl count exceeds the configured batch_size")
        components: list[SoftwareComponent] = []
        for purl in selected:
            component = await self.store.get_component(purl, tenant_id=tenant_id)
            if component is None:
                raise ComponentNotFound(purl)
            components.append(component)
        return components

    async def _component_vulnerabilities(
        self,
        components: Sequence[SoftwareComponent],
        *,
        tenant_id: str | None,
    ) -> list[VulnerabilityRecord]:
        if self.vulnerability_store is None:
            raise StoreUnavailable("EA-0024 vulnerability catalog is unavailable")
        remaining = self.config.batch_size
        vulnerabilities: list[VulnerabilityRecord] = []
        for component in components:
            rows = await self.vulnerability_store.query(
                tenant_id=tenant_id,
                asset_ref_id=component.object_id,
                limit=remaining + 1,
            )
            if len(rows) > remaining:
                raise StoreUnavailable(
                    "component vulnerability route exceeds the configured batch_size"
                )
            vulnerabilities.extend(rows)
            remaining -= len(rows)
        return sorted(vulnerabilities, key=lambda item: (item.cve_id, item.id))

    async def _assessment_vulnerabilities(
        self,
        components: Sequence[SoftwareComponent],
        *,
        tenant_id: str | None,
    ) -> tuple[list[VulnerabilityRecord], bool]:
        if self.vulnerability_store is None:
            raise StoreUnavailable("EA-0024 vulnerability catalog is unavailable")
        remaining = self.config.batch_size
        vulnerabilities: list[VulnerabilityRecord] = []
        for index, component in enumerate(components):
            rows = await self.vulnerability_store.query(
                tenant_id=tenant_id,
                asset_ref_id=component.object_id,
                limit=remaining + 1,
            )
            if len(rows) > remaining:
                vulnerabilities.extend(rows[:remaining])
                return (
                    sorted(vulnerabilities, key=lambda item: (item.cve_id, item.id)),
                    True,
                )
            vulnerabilities.extend(rows)
            remaining -= len(rows)
            if remaining == 0 and index + 1 < len(components):
                return (
                    sorted(vulnerabilities, key=lambda item: (item.cve_id, item.id)),
                    True,
                )
        return (sorted(vulnerabilities, key=lambda item: (item.cve_id, item.id)), False)

    async def _materialize_dependency_graph(
        self,
        components: Sequence[SoftwareComponent],
        relationships: Sequence[DependencyRelationship],
        *,
        doc: SBOMDocument,
        relationship_confidence: float,
    ) -> None:
        by_purl = {component.purl: component for component in components}
        for component in components:
            component_confidence = (
                await self.source_registry.get(source_id=component.source_id)
            ).weight
            stored = await self.object_store.upsert(
                _component_object(component, confidence=component_confidence)
            )
            if stored.id != component.object_id:
                raise StoreUnavailable(
                    "EA-0002 resolved the component purl to a different object id"
                )

        source = SourceRef(
            source_id=doc.source_id,
            evidence_id=doc.evidence_id,
            observed_at=doc.observed_at,
            method="supplychain.sbom_dependency/v1",
        )
        for relationship in relationships:
            from_component = by_purl.get(relationship.from_purl)
            to_component = by_purl.get(relationship.to_purl)
            if from_component is None or to_component is None:
                raise StoreUnavailable("parsed dependency endpoint was not stored")
            existing = await self.object_store.relationships(
                from_component.object_id,
                direction="out",
                relation_type="depends_on",
            )
            if any(item.to_id == to_component.object_id for item in existing):
                continue
            await self.object_store.relate(
                AQRelationship(
                    id=relationship.edge_id,
                    tenant_id=from_component.tenant_id,
                    from_id=from_component.object_id,
                    to_id=to_component.object_id,
                    relation_type="depends_on",
                    attributes={
                        "version_constraint": relationship.version_constraint,
                        "scope": relationship.scope,
                    },
                    sources=[source],
                    confidence=relationship_confidence,
                    created_at=doc.observed_at,
                    updated_at=doc.observed_at,
                    created_by=_SUPPLYCHAIN_ACTOR,
                    updated_by=_SUPPLYCHAIN_ACTOR,
                )
            )

    async def _reconcile(
        self,
        existing: SoftwareComponent,
        incoming: SoftwareComponent,
        *,
        incoming_reliability: float,
    ) -> SoftwareComponent:
        existing_reliability = (await self.source_registry.get(source_id=existing.source_id)).weight
        existing_values = _component_values(existing)
        incoming_values = _component_values(incoming)
        if existing_values == incoming_values:
            winner = max(
                (
                    (existing_reliability, existing.observed_at, existing.source_id, existing),
                    (incoming_reliability, incoming.observed_at, incoming.source_id, incoming),
                ),
                key=lambda item: item[:3],
            )[3]
            return winner.model_copy(
                update={
                    "object_id": existing.object_id,
                    "tenant_id": existing.tenant_id,
                    "conflicts": copy.deepcopy(existing.conflicts),
                },
                deep=True,
            )

        old_candidate = _conflict_candidate(existing, reliability=existing_reliability)
        new_candidate = _conflict_candidate(incoming, reliability=incoming_reliability)
        if existing_reliability != incoming_reliability:
            winner = existing if existing_reliability > incoming_reliability else incoming
            winner_candidate = old_candidate if winner is existing else new_candidate
            conflict = ComponentConflict(
                fields=_changed_fields(existing_values, incoming_values),
                candidates=_sorted_candidates(old_candidate, new_candidate),
                resolved_by=winner_candidate.source_id,
                resolved_evidence_id=winner_candidate.evidence_id,
                unresolved=False,
                reason="higher EA-0006 source reliability",
            )
        else:
            winner = max(
                (existing, incoming),
                key=lambda item: (item.observed_at, item.source_id, item.evidence_id),
            )
            conflict = ComponentConflict(
                fields=_changed_fields(existing_values, incoming_values),
                candidates=_sorted_candidates(old_candidate, new_candidate),
                unresolved=True,
                reason=(
                    "equal EA-0006 source reliability; deterministic value retained "
                    "while the conflict remains unresolved"
                ),
            )
        conflicts = _append_conflict(existing.conflicts, conflict)
        return winner.model_copy(
            update={
                "object_id": existing.object_id,
                "tenant_id": existing.tenant_id,
                "conflicts": conflicts,
            },
            deep=True,
        )


def _component_object(component: SoftwareComponent, *, confidence: float) -> AQObject:
    source = SourceRef(
        source_id=component.source_id,
        evidence_id=component.evidence_id,
        observed_at=component.observed_at,
        method="supplychain.sbom_component/v1",
    )
    return AQObject(
        id=component.object_id,
        object_type=SOFTWARE_COMPONENT_OBJECT_TYPE,
        schema_version=1,
        tenant_id=component.tenant_id,
        display_name=f"{component.name}@{component.version}",
        attributes={
            "purl": component.purl,
            "name": component.name,
            "version": component.version,
            "component_type": component.component_type,
            "licenses": list(component.licenses),
            "supplier": component.supplier,
            "hashes": dict(component.hashes),
            "provenance_status": component.provenance_status,
            "direct": component.direct,
        },
        labels={"module": "EA-0030", "kind": SOFTWARE_COMPONENT_OBJECT_TYPE},
        natural_keys=[NaturalKey(namespace="purl", value=component.purl)],
        sources=[source],
        confidence=confidence,
        first_seen_at=component.observed_at,
        last_seen_at=component.observed_at,
        created_at=component.observed_at,
        updated_at=component.observed_at,
        created_by=_SUPPLYCHAIN_ACTOR,
        updated_by=_SUPPLYCHAIN_ACTOR,
    )


def _forward_dependency_path(path: Path) -> Path:
    return Path(
        node_ids=list(reversed(path.node_ids)),
        edges=list(reversed(path.edges)),
        length=path.length,
    )


def _unknown_reachability(
    component_purl: str,
    cve_id: str,
    *,
    reason: str,
) -> ReachabilitySignal:
    return ReachabilitySignal(
        component_purl=component_purl,
        cve_id=cve_id,
        reason=reason,
    )


def _aggregate_provenance_status(statuses: Sequence[ProvenanceStatus]) -> ProvenanceStatus:
    if "failed" in statuses:
        return "failed"
    if "unverified" in statuses:
        return "unverified"
    return "verified"


def _inventory_report(component: SoftwareComponent) -> dict[str, Any]:
    prefix, payload = parse_id(component.object_id)
    if prefix != "obj":
        raise StoreUnavailable("software component object_id must use obj_ prefix")
    return {
        "id": f"ast_{payload}",
        "asset_type": "software_component",
        "classification": component.component_type,
        "lifecycle_state": "active",
        "evidence_id": component.evidence_id,
        "ref": f"supplychain:{component.purl}",
        "purl": component.purl,
        "name": component.name,
        "version": component.version,
        "licenses": list(component.licenses),
        "supplier": component.supplier,
        "hashes": dict(component.hashes),
        "provenance_status": component.provenance_status,
        "flagged": component.provenance_status != "verified",
        "direct": component.direct,
        "conflicts": [conflict.model_dump(mode="json") for conflict in component.conflicts],
    }


def _reachability_factor(signal: ReachabilitySignal) -> PriorityFactor:
    source = f"supplychain:reachability:{signal.reachable}:{signal.component_purl}"
    if signal.reachable == "unknown":
        return PriorityFactor(
            0.0,
            source,
            (
                f"Supply-chain reachability is unknown and is excluded from the EA-0024 "
                f"score denominator rather than treated as low exposure: {signal.reason}"
            ),
            status="unknown",
        )
    if signal.reachable == "unreachable":
        return PriorityFactor(0.0, source, signal.reason)
    if signal.reachable == "direct":
        return PriorityFactor(1.0, source, signal.reason)
    if signal.depth is None:
        raise SupplyChainConfigInvalid("transitive reachability is missing depth")
    return PriorityFactor(
        1.0 / (signal.depth + 1.0),
        source,
        f"Reachable through a dependency path of depth {signal.depth}; {signal.reason}",
    )


def _license_resource(component: SoftwareComponent) -> dict[str, Any]:
    return {
        "id": component.object_id,
        "type": SOFTWARE_COMPONENT_OBJECT_TYPE,
        "object_type": SOFTWARE_COMPONENT_OBJECT_TYPE,
        "tenant_id": component.tenant_id,
        "attributes": {
            "purl": component.purl,
            "name": component.name,
            "version": component.version,
            "licenses": list(component.licenses),
            "supplier": component.supplier,
        },
        "labels": {"module": "EA-0030", "kind": SOFTWARE_COMPONENT_OBJECT_TYPE},
        "confidence": 1.0,
        "lifecycle_state": "active",
    }


def _license_evidence(
    component: SoftwareComponent,
    *,
    result: ComplianceResult,
    policy_id: str,
    by: ActorRef,
) -> EvidenceRecord:
    now = utc_now()
    return EvidenceRecord(
        id="",
        tenant_id=component.tenant_id,
        evidence_type="supplychain.license_assessment",
        schema_version=1,
        subject=Subject(object_ids=[component.object_id]),
        collected_at=component.observed_at,
        recorded_at=now,
        collector=by,
        source_id=component.source_id,
        method="supplychain.license_findings/v1",
        content={
            "component_purl": component.purl,
            "licenses": list(component.licenses),
            "policy_id": policy_id,
            "compliant": result.compliant,
            "evaluated": result.evaluated,
            "violations": [item.model_dump(mode="json") for item in result.violations],
            "component_evidence_id": component.evidence_id,
        },
        content_hash="",
        confidence=1.0,
        labels={"module": "EA-0030", "kind": "license_assessment"},
        seq=0,
        prev_hash=None,
        record_hash="",
    )


def _license_finding(
    component: SoftwareComponent,
    *,
    result: ComplianceResult,
    policy_id: str,
    evidence_id: str,
    by: ActorRef,
) -> Finding:
    now = utc_now()
    requirements = sorted({item.requirement for item in result.violations})
    return Finding(
        id=new_id("fnd"),
        tenant_id=component.tenant_id,
        finding_type="supplychain.license_compliance",
        schema_version=1,
        dedup_key=f"supplychain.license:{component.object_id}:{policy_id}",
        title=f"License policy gap: {component.name}@{component.version}",
        severity="medium",
        severity_score=50.0,
        status="open",
        what_happened=(
            f"EA-0010 policy {policy_id} found {len(result.violations)} license "
            f"violation(s) for {component.purl}."
        ),
        why_it_matters=(
            "A dependency license can impose obligations or restrictions that conflict "
            "with the organization's approved software policy."
        ),
        how_determined=(
            "EA-0030 identified the component licenses and delegated policy evaluation "
            f"to EA-0010; failed requirement(s): {', '.join(requirements)}."
        ),
        risk_of_inaction=(
            "Continuing to distribute or operate the dependency without review can retain "
            "an unresolved legal or governance obligation."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=[component.object_id],
        expert_details={
            "component_purl": component.purl,
            "licenses": list(component.licenses),
            "policy_id": policy_id,
            "violations": [item.model_dump(mode="json") for item in result.violations],
            "raised_by": by.model_dump(mode="json"),
        },
        remediation=Remediation(
            summary="Review or replace the dependency under the approved license policy.",
            steps=[
                "Review the cited EA-0010 license-policy violations.",
                "Select an approved version, replacement, or attributed exception.",
                "Propose any dependency change through the gated EA-0008 workflow path.",
            ],
            difficulty="medium",
            expected_outcome="The dependency satisfies the approved license policy.",
            references=[policy_id, component.purl, *requirements],
        ),
        automation=Automation(
            eligibility="none",
            action_ref=None,
            requires_approval=True,
            risk_note="License remediation is advisory and must use EA-0008 Workflow.",
        ),
        confidence=1.0,
        source_engine="supplychain_engine",
        correlation_id=f"supplychain:license:{component.object_id}",
        first_detected_at=now,
        last_detected_at=now,
    )


def _assessment_evidence(
    components: Sequence[SoftwareComponent],
    *,
    vulnerable_object_ids: set[str],
    subject_ref: str,
    tenant_id: str | None,
    run_at: datetime,
    status: str,
) -> EvidenceRecord:
    return EvidenceRecord(
        id="",
        tenant_id=tenant_id,
        evidence_type="supplychain.assessment",
        schema_version=1,
        subject=Subject(object_ids=sorted(component.object_id for component in components)),
        collected_at=run_at,
        recorded_at=run_at,
        collector=_SUPPLYCHAIN_ACTOR,
        source_id=new_id("src"),
        method="supplychain.assess/v1",
        content={
            "subject_ref": subject_ref,
            "status": status,
            "components": [component.model_dump(mode="json") for component in components],
            "vulnerable_object_ids": sorted(vulnerable_object_ids),
        },
        content_hash="",
        confidence=1.0,
        labels={"module": "EA-0030", "kind": "assessment"},
        seq=0,
        prev_hash=None,
        record_hash="",
    )


def _remediation_playbook(component: SoftwareComponent, *, action: str) -> Playbook:
    return Playbook(
        id=f"supplychain-{action}-{component.object_id}",
        version=1,
        name=f"{action.title()} dependency {component.name}",
        description=(
            "Proposed dependency remediation only; EA-0008 re-validates capability, "
            "approval, and action eligibility before execution."
        ),
        tenant_id=component.tenant_id,
        steps=[
            Step(
                id=f"{action}-dependency",
                action_type=f"supplychain.dependency.{action}",
                inputs={
                    "component_purl": component.purl,
                    "component_object_id": component.object_id,
                    "current_version": component.version,
                },
                idempotency_key=f"supplychain:{action}:{component.object_id}:{component.version}",
                requires_approval=True,
            )
        ],
    )


def _component_values(component: SoftwareComponent) -> dict[str, Any]:
    return {
        "name": component.name,
        "version": component.version,
        "component_type": component.component_type,
        "licenses": list(component.licenses),
        "supplier": component.supplier,
        "hashes": dict(component.hashes),
        "direct": component.direct,
    }


def _conflict_candidate(
    component: SoftwareComponent,
    *,
    reliability: float,
) -> ComponentConflictCandidate:
    return ComponentConflictCandidate(
        source_id=component.source_id,
        evidence_id=component.evidence_id,
        observed_at=component.observed_at,
        reliability=reliability,
        values=_component_values(component),
    )


def _sorted_candidates(
    first: ComponentConflictCandidate,
    second: ComponentConflictCandidate,
) -> list[ComponentConflictCandidate]:
    return sorted(
        (first, second),
        key=lambda item: (item.source_id, item.evidence_id),
    )


def _changed_fields(first: Mapping[str, Any], second: Mapping[str, Any]) -> list[str]:
    return sorted(key for key in first if first[key] != second[key])


def _append_conflict(
    existing: Sequence[ComponentConflict],
    conflict: ComponentConflict,
) -> list[ComponentConflict]:
    serialized = conflict.model_dump(mode="json")
    if any(item.model_dump(mode="json") == serialized for item in existing):
        return [item.model_copy(deep=True) for item in existing]
    return [*[item.model_copy(deep=True) for item in existing], conflict]
