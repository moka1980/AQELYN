"""Identity & Access Governance campaign engine (EA-0011 I3)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from typing import Any

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    CertificationNotFound,
    IAGConfigInvalid,
    OptimisticConcurrencyConflict,
    ReviewItemNotFound,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.graph import KnowledgeGraph
from aqelyn.iag.analysis import IDENTITY_OBJECT_TYPE, IAGPolicyEvaluator, IdentityAccessAnalyzer
from aqelyn.iag.models import (
    AccessPath,
    AccessRisk,
    AccessRiskReport,
    Certification,
    IAGConfig,
    ReviewDecision,
    ReviewItem,
)
from aqelyn.iag.store import CertificationStore, validate_positive, validate_review_item_id
from aqelyn.objects import ObjectQuery, ObjectStore

_IAG_ACTOR = ActorRef(actor_type="system", actor_id="iag_engine")
_VALID_DECISIONS: frozenset[str] = frozenset(("approved", "revoked", "delegated"))
_PAGE_SIZE = 1_000


class IdentityAccessGovernanceEngine:
    def __init__(
        self,
        object_store: ObjectStore,
        knowledge_graph: KnowledgeGraph,
        policy_engine: IAGPolicyEvaluator,
        certification_store: CertificationStore,
        evidence_store: EvidenceStore,
        *,
        config: IAGConfig | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self._objects = object_store
        self._certifications = certification_store
        self._evidence = evidence_store
        self._config = config or IAGConfig()
        self._actor = actor or _IAG_ACTOR
        self._source_id = source_id or new_id("src")
        self._analyzer = IdentityAccessAnalyzer(
            object_store,
            knowledge_graph,
            policy_engine,
            config=self._config,
        )

    @property
    def config(self) -> IAGConfig:
        return self._config

    @property
    def certification_store(self) -> CertificationStore:
        return self._certifications

    async def access_paths(
        self, identity_id: str, *, tenant_id: str | None = None
    ) -> list[AccessPath]:
        return await self._analyzer.access_paths(identity_id, tenant_id=tenant_id)

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        return await self._analyzer.analyze_risk(tenant_id=tenant_id, scope=scope)

    def explain(self, risk: AccessRisk) -> dict[str, object]:
        return self._analyzer.explain(risk)

    async def open_certification(
        self,
        *,
        tenant_id: str | None,
        name: str,
        scope: ObjectQuery,
        by: ActorRef,
        due_days: int | None = None,
    ) -> Certification:
        days = due_days if due_days is not None else self._config.review_default_due_days
        validate_positive(days, field="due_days")
        report = await self.analyze_risk(tenant_id=tenant_id, scope=scope)
        risk_index = _RiskIndex(report.risks)
        items: list[ReviewItem] = []
        async for page in _identity_pages(self._objects, tenant_id=tenant_id, scope=scope):
            for identity in sorted(page, key=lambda obj: obj.id):
                paths = await self.access_paths(identity.id, tenant_id=tenant_id)
                for path in paths:
                    for entitlement_id in path.entitlement_ids:
                        item = ReviewItem(
                            id=new_id("rvi"),
                            identity_id=identity.id,
                            account_id=path.account_id,
                            entitlement_id=entitlement_id,
                            current_state={
                                "access_path": path.model_dump(mode="json"),
                                "truncated": report.truncated,
                            },
                            recommendation=risk_index.recommendation(
                                identity_id=identity.id,
                                account_id=path.account_id,
                                entitlement_id=entitlement_id,
                            ),
                        )
                        items.append(item)
        now = utc_now()
        cert = Certification(
            id=new_id("cert"),
            tenant_id=tenant_id,
            name=name,
            scope=_scope_dump(scope, tenant_id=tenant_id),
            status="open",
            items=sorted(items, key=_review_item_sort_key),
            created_by=by,
            created_at=now,
            due_at=now + timedelta(days=days),
            version=1,
        )
        return await self._certifications.put(cert)

    async def decide_item(
        self,
        cert_id: str,
        item_id: str,
        *,
        decision: str,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Certification:
        validate_positive(expected_version, field="expected_version")
        validate_review_item_id(item_id)
        selected_decision = _validate_decision(decision)
        cert = await self._certifications.get(cert_id)
        if cert is None:
            raise CertificationNotFound(cert_id)
        if cert.version != expected_version:
            raise OptimisticConcurrencyConflict(
                f"expected v{expected_version}, found v{cert.version}"
            )
        item = _find_item(cert.items, item_id)
        decided_at = utc_now()
        evidence = await self._record_decision_evidence(
            cert,
            item,
            decision=selected_decision,
            by=by,
            note=note,
            decided_at=decided_at,
        )
        updated_item = item.model_copy(
            update={
                "decision": selected_decision,
                "decided_by": by,
                "decided_at": decided_at,
                "evidence_id": evidence.id,
                "note": note,
            },
            deep=True,
        )
        updated_items = [
            updated_item if existing.id == item_id else existing for existing in cert.items
        ]
        updated = cert.model_copy(
            update={
                "items": updated_items,
                "status": "in_progress",
            },
            deep=True,
        )
        return await self._certifications.put(updated, expected_version=expected_version)

    async def _record_decision_evidence(
        self,
        cert: Certification,
        item: ReviewItem,
        *,
        decision: ReviewDecision,
        by: ActorRef,
        note: str | None,
        decided_at: datetime,
    ) -> EvidenceRecord:
        subject_ids = [
            value
            for value in (item.identity_id, item.account_id, item.entitlement_id)
            if value is not None
        ]
        record = EvidenceRecord(
            id="",
            tenant_id=cert.tenant_id,
            evidence_type="iag.certification_decision",
            schema_version=1,
            subject=Subject(object_ids=subject_ids),
            collected_at=decided_at,
            recorded_at=decided_at,
            collector=by,
            source_id=self._source_id,
            method="iag.decide_item/v1",
            content={
                "certification_id": cert.id,
                "review_item_id": item.id,
                "decision": decision,
                "note": note,
                "current_state": item.current_state,
                "recommendation": item.recommendation,
                "actor": by.model_dump(mode="json"),
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0011", "kind": "certification_decision"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self._evidence.add(record)


class _RiskIndex:
    def __init__(self, risks: Sequence[AccessRisk]) -> None:
        self._by_identity: dict[str, set[str]] = {}
        self._by_account: dict[str, set[str]] = {}
        self._by_entitlement: dict[str, set[str]] = {}
        for risk in risks:
            self._by_identity.setdefault(risk.subject_id, set()).add(risk.kind)
            account_id = risk.detail.get("account_id")
            if isinstance(account_id, str):
                self._by_account.setdefault(account_id, set()).add(risk.kind)
            entitlement_id = risk.detail.get("entitlement_id")
            if isinstance(entitlement_id, str):
                self._by_entitlement.setdefault(entitlement_id, set()).add(risk.kind)

    def recommendation(
        self,
        *,
        identity_id: str,
        account_id: str | None,
        entitlement_id: str,
    ) -> str:
        kinds = set(self._by_identity.get(identity_id, set()))
        if account_id is not None:
            kinds.update(self._by_account.get(account_id, set()))
        kinds.update(self._by_entitlement.get(entitlement_id, set()))
        if not kinds:
            return "Approve if access remains business-justified."
        return f"Review access risk(s): {', '.join(sorted(kinds))}."


async def _identity_pages(
    object_store: ObjectStore,
    *,
    tenant_id: str | None,
    scope: ObjectQuery,
) -> AsyncIterator[list[Any]]:
    cursor = scope.cursor
    seen_cursors: set[str] = set()
    while True:
        query = _query_for_identity_page(tenant_id=tenant_id, scope=scope, cursor=cursor)
        rows, next_cursor = await object_store.query(query)
        yield rows
        if next_cursor is None or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _query_for_identity_page(
    *,
    tenant_id: str | None,
    scope: ObjectQuery,
    cursor: str | None,
) -> ObjectQuery:
    data = scope.model_dump()
    data.update(
        {
            "tenant_id": tenant_id,
            "object_type": IDENTITY_OBJECT_TYPE,
            "include_states": ("active",),
            "limit": min(scope.limit, _PAGE_SIZE),
            "cursor": cursor,
        }
    )
    return ObjectQuery.model_validate(data)


def _scope_dump(scope: ObjectQuery, *, tenant_id: str | None) -> dict[str, Any]:
    return _query_for_identity_page(tenant_id=tenant_id, scope=scope, cursor=None).model_dump(
        mode="json"
    )


def _find_item(items: Sequence[ReviewItem], item_id: str) -> ReviewItem:
    for item in items:
        if item.id == item_id:
            return item
    raise ReviewItemNotFound(item_id)


def _validate_decision(value: str) -> ReviewDecision:
    if value not in _VALID_DECISIONS:
        raise IAGConfigInvalid(f"unknown review decision: {value!r}")
    return value  # type: ignore[return-value]


def _review_item_sort_key(item: ReviewItem) -> tuple[str, str, str, str]:
    return (
        item.identity_id,
        item.account_id or "",
        item.entitlement_id or "",
        item.id,
    )
