"""Identity graph traversal and risk analysis (EA-0011 I2)."""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from aqelyn.conventions import utc_now
from aqelyn.graph import EdgeView, KnowledgeGraph, Path, Subgraph
from aqelyn.iag.models import AccessPath, AccessRisk, AccessRiskReport, IAGConfig
from aqelyn.objects import AQObject, ObjectQuery, ObjectStore
from aqelyn.policy import ComplianceResult

IDENTITY_OBJECT_TYPE = "identity"
ACCOUNT_OBJECT_TYPE = "account"
ROLE_OBJECT_TYPE = "role"
ENTITLEMENT_OBJECT_TYPE = "entitlement"

HAS_ACCOUNT = "has_account"
HAS_ROLE = "has_role"
GRANTS_ENTITLEMENT = "grants_entitlement"
MEMBER_OF = "member_of"
ACCESS_RELATION_TYPES: tuple[str, ...] = (
    HAS_ACCOUNT,
    HAS_ROLE,
    GRANTS_ENTITLEMENT,
    MEMBER_OF,
)
_ACTIVE_STATES = ("active",)
_PAGE_SIZE = 1_000


class IAGPolicyEvaluator(Protocol):
    async def evaluate_compliance(
        self,
        resource: dict[str, Any],
        *,
        tenant_id: str | None,
        policy_ids: set[str] | None = None,
    ) -> ComplianceResult: ...


@dataclass(frozen=True)
class _AccessBundle:
    paths: list[AccessPath]
    truncated: bool
    node_types: dict[str, str]


class IdentityAccessAnalyzer:
    """Read-only IAG analyzer over objects, graph paths, and policy compliance."""

    def __init__(
        self,
        object_store: ObjectStore,
        knowledge_graph: KnowledgeGraph,
        policy_engine: IAGPolicyEvaluator,
        *,
        config: IAGConfig | None = None,
        max_depth: int = 4,
        max_nodes: int = 10_000,
    ) -> None:
        self._objects = object_store
        self._graph = knowledge_graph
        self._policy_engine = policy_engine
        self._config = config or IAGConfig()
        self._max_depth = max_depth
        self._max_nodes = max_nodes

    @property
    def config(self) -> IAGConfig:
        return self._config

    async def access_paths(
        self, identity_id: str, *, tenant_id: str | None = None
    ) -> list[AccessPath]:
        bundle = await self._access_paths(identity_id, tenant_id=tenant_id)
        return bundle.paths

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        identities = await self._query_type(
            IDENTITY_OBJECT_TYPE,
            tenant_id=tenant_id,
            scope=scope,
        )
        accounts = await self._query_type(
            ACCOUNT_OBJECT_TYPE,
            tenant_id=tenant_id,
            scope=scope,
        )
        risks: list[AccessRisk] = []
        truncated = False

        for account in accounts:
            risks.extend(await self._account_risks(account, tenant_id=tenant_id))

        for identity in identities:
            bundle = await self._access_paths(identity.id, tenant_id=tenant_id)
            truncated = truncated or bundle.truncated
            risks.extend(await self._identity_risks(identity, bundle, tenant_id=tenant_id))

        return AccessRiskReport(
            risks=sorted(risks, key=_risk_sort_key),
            evaluated=len(identities) + len(accounts),
            truncated=truncated,
        )

    def explain(self, risk: AccessRisk) -> dict[str, object]:
        return {
            "kind": risk.kind,
            "subject_id": risk.subject_id,
            "severity": risk.severity,
            "reason": risk.reason,
            "detail": dict(risk.detail),
            "evidence_path": (
                risk.evidence_path.model_dump(mode="json")
                if risk.evidence_path is not None
                else None
            ),
        }

    async def _identity_risks(
        self,
        identity: AQObject,
        bundle: _AccessBundle,
        *,
        tenant_id: str | None,
    ) -> list[AccessRisk]:
        entitlement_ids = sorted(
            {entitlement_id for path in bundle.paths for entitlement_id in path.entitlement_ids}
        )
        account_ids = sorted(
            {path.account_id for path in bundle.paths if path.account_id is not None}
        )
        role_ids = sorted(
            {
                node_id
                for path in bundle.paths
                for node_id in path.via.node_ids
                if bundle.node_types.get(node_id) == ROLE_OBJECT_TYPE
            }
        )

        risks: list[AccessRisk] = []
        risks.extend(
            self._over_privilege_risks(
                identity,
                entitlement_ids=entitlement_ids,
                paths=bundle.paths,
            )
        )
        risks.extend(
            await self._sod_risks(
                identity,
                entitlement_ids=entitlement_ids,
                role_ids=role_ids,
                account_ids=account_ids,
                paths=bundle.paths,
                tenant_id=tenant_id,
            )
        )
        risks.extend(
            await self._privileged_unreviewed_risks(
                identity,
                role_ids=role_ids,
                paths=bundle.paths,
            )
        )
        return risks

    async def _account_risks(
        self,
        account: AQObject,
        *,
        tenant_id: str | None,
    ) -> list[AccessRisk]:
        risks: list[AccessRisk] = []
        if not await self._has_identity_owner(account, tenant_id=tenant_id):
            risks.append(
                AccessRisk(
                    kind="orphaned",
                    subject_id=account.id,
                    detail={"account_id": account.id},
                    severity="high",
                    evidence_path=None,
                    reason="Account has no active identity owner via has_account.",
                )
            )

        dormant_detail = _dormant_detail(
            account,
            dormant_days=self._config.dormant_days,
        )
        if dormant_detail is not None:
            reason = (
                "Account is missing last-used evidence."
                if dormant_detail["last_used_at"] is None
                else f"Account has not been used for {dormant_detail['age_days']} days."
            )
            risks.append(
                AccessRisk(
                    kind="dormant",
                    subject_id=account.id,
                    detail=dormant_detail,
                    severity="medium",
                    evidence_path=None,
                    reason=reason,
                )
            )
        return risks

    async def _has_identity_owner(self, account: AQObject, *, tenant_id: str | None) -> bool:
        relationships = await self._objects.relationships(
            account.id,
            direction="in",
            relation_type=HAS_ACCOUNT,
        )
        for rel in sorted(relationships, key=lambda item: item.id):
            owner = await self._active_object(rel.from_id, tenant_id=tenant_id)
            if owner is not None and owner.object_type == IDENTITY_OBJECT_TYPE:
                return True
        return False

    def _over_privilege_risks(
        self,
        identity: AQObject,
        *,
        entitlement_ids: Sequence[str],
        paths: Sequence[AccessPath],
    ) -> list[AccessRisk]:
        allowed = _allowed_entitlements(identity, self._config)
        if allowed is None:
            return []
        excessive = sorted(set(entitlement_ids) - allowed)
        return [
            AccessRisk(
                kind="over_privilege",
                subject_id=identity.id,
                detail={
                    "identity_id": identity.id,
                    "entitlement_id": entitlement_id,
                    "allowed_entitlement_ids": sorted(allowed),
                },
                severity="high",
                evidence_path=_path_for_entitlement(paths, entitlement_id),
                reason="Identity holds an entitlement outside its peer baseline.",
            )
            for entitlement_id in excessive
        ]

    async def _sod_risks(
        self,
        identity: AQObject,
        *,
        entitlement_ids: Sequence[str],
        role_ids: Sequence[str],
        account_ids: Sequence[str],
        paths: Sequence[AccessPath],
        tenant_id: str | None,
    ) -> list[AccessRisk]:
        resource = _identity_access_resource(
            identity,
            entitlement_ids=entitlement_ids,
            role_ids=role_ids,
            account_ids=account_ids,
        )
        result = await self._policy_engine.evaluate_compliance(
            resource,
            tenant_id=tenant_id,
        )
        if result.compliant:
            return []
        evidence_path = paths[0].via if paths else None
        return [
            AccessRisk(
                kind="sod_conflict",
                subject_id=identity.id,
                detail={
                    "policy_id": violation.policy_id,
                    "rule_id": violation.rule_id,
                    "requirement": violation.requirement,
                    "entitlement_ids": list(entitlement_ids),
                    "role_ids": list(role_ids),
                },
                severity="critical",
                evidence_path=evidence_path,
                reason=violation.reason,
            )
            for violation in sorted(
                result.violations, key=lambda item: (item.policy_id, item.rule_id)
            )
        ]

    async def _privileged_unreviewed_risks(
        self,
        identity: AQObject,
        *,
        role_ids: Sequence[str],
        paths: Sequence[AccessPath],
    ) -> list[AccessRisk]:
        if not self._config.privileged_roles:
            return []
        roles = [
            role
            for role in await self._objects_by_id(role_ids)
            if _is_privileged(role, self._config)
        ]
        if not roles or _review_current(identity, self._config):
            return []
        return [
            AccessRisk(
                kind="privileged_unreviewed",
                subject_id=identity.id,
                detail={
                    "identity_id": identity.id,
                    "role_ids": sorted(role.id for role in roles),
                    "review_window_days": self._config.review_default_due_days,
                },
                severity="high",
                evidence_path=_path_for_role(paths, role.id),
                reason="Identity holds privileged access without a current passing review.",
            )
            for role in sorted(roles, key=lambda item: item.id)
        ]

    async def _access_paths(self, identity_id: str, *, tenant_id: str | None) -> _AccessBundle:
        identity = await self._active_object(identity_id, tenant_id=tenant_id)
        if identity is None:
            return _AccessBundle(paths=[], truncated=False, node_types={})
        subgraph = await self._graph.subgraph(
            identity_id,
            direction="out",
            relation_types=ACCESS_RELATION_TYPES,
            max_depth=self._max_depth,
            max_nodes=self._max_nodes,
        )
        paths = _paths_from_subgraph(identity_id, subgraph)
        return _AccessBundle(
            paths=paths,
            truncated=subgraph.truncated,
            node_types={node.id: node.object_type for node in subgraph.nodes},
        )

    async def _objects_by_id(self, object_ids: Sequence[str]) -> list[AQObject]:
        objects: list[AQObject] = []
        for object_id in sorted(set(object_ids)):
            obj = await self._objects.get(object_id, resolve_merged=False)
            if obj is not None and obj.lifecycle_state == "active":
                objects.append(obj)
        return objects

    async def _active_object(self, object_id: str, *, tenant_id: str | None) -> AQObject | None:
        obj = await self._objects.get(object_id, resolve_merged=False)
        if obj is None or obj.lifecycle_state != "active":
            return None
        if obj.tenant_id != tenant_id:
            return None
        return obj

    async def _query_type(
        self,
        object_type: str,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None,
    ) -> list[AQObject]:
        rows: list[AQObject] = []
        async for page in _query_pages(
            self._objects,
            object_type=object_type,
            tenant_id=tenant_id,
            scope=scope,
        ):
            rows.extend(page)
        return sorted(rows, key=lambda item: item.id)


async def _query_pages(
    object_store: ObjectStore,
    *,
    object_type: str,
    tenant_id: str | None,
    scope: ObjectQuery | None,
) -> AsyncIterator[list[AQObject]]:
    cursor = scope.cursor if scope is not None else None
    seen_cursors: set[str] = set()
    while True:
        query = _query_for_page(
            object_type=object_type,
            tenant_id=tenant_id,
            scope=scope,
            cursor=cursor,
        )
        rows, next_cursor = await object_store.query(query)
        yield rows
        if next_cursor is None or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _query_for_page(
    *,
    object_type: str,
    tenant_id: str | None,
    scope: ObjectQuery | None,
    cursor: str | None,
) -> ObjectQuery:
    if scope is None:
        return ObjectQuery(
            tenant_id=tenant_id,
            object_type=object_type,
            include_states=_ACTIVE_STATES,
            limit=_PAGE_SIZE,
            cursor=cursor,
        )
    data = scope.model_dump()
    data.update(
        {
            "tenant_id": tenant_id,
            "object_type": object_type,
            "include_states": _ACTIVE_STATES,
            "limit": min(scope.limit, _PAGE_SIZE),
            "cursor": cursor,
        }
    )
    return ObjectQuery.model_validate(data)


def _paths_from_subgraph(identity_id: str, subgraph: Subgraph) -> list[AccessPath]:
    node_types = {node.id: node.object_type for node in subgraph.nodes}
    adjacency: dict[str, list[EdgeView]] = {}
    for edge in subgraph.edges:
        adjacency.setdefault(edge.from_id, []).append(edge)
    for edges in adjacency.values():
        edges.sort(key=lambda edge: edge.id)

    access_paths: list[AccessPath] = []
    queue: deque[tuple[str, list[str], list[EdgeView]]] = deque([(identity_id, [identity_id], [])])
    while queue:
        current_id, node_ids, edges = queue.popleft()
        for edge in adjacency.get(current_id, []):
            next_id = edge.to_id
            if next_id in node_ids:
                continue
            next_node_ids = [*node_ids, next_id]
            next_edges = [*edges, edge]
            next_type = node_types.get(next_id)
            if next_type == ENTITLEMENT_OBJECT_TYPE:
                access_paths.append(
                    AccessPath(
                        identity_id=identity_id,
                        account_id=_account_id(next_node_ids, next_edges, node_types),
                        entitlement_ids=[next_id],
                        via=Path(
                            node_ids=next_node_ids,
                            edges=next_edges,
                            length=len(next_edges),
                        ),
                    )
                )
                continue
            queue.append((next_id, next_node_ids, next_edges))

    return sorted(access_paths, key=_access_path_sort_key)


def _account_id(
    node_ids: Sequence[str],
    edges: Sequence[EdgeView],
    node_types: dict[str, str],
) -> str | None:
    for index, edge in enumerate(edges):
        node_id = node_ids[index + 1]
        if edge.relation_type == HAS_ACCOUNT or node_types.get(node_id) == ACCOUNT_OBJECT_TYPE:
            return node_id
    return None


def _dormant_detail(account: AQObject, *, dormant_days: int) -> dict[str, object] | None:
    last_used = _datetime_attr(account.attributes.get("last_used_at"))
    if last_used is None:
        return {
            "account_id": account.id,
            "last_used_at": None,
            "dormant_days": dormant_days,
        }
    age_days = (utc_now() - last_used).days
    if age_days < dormant_days:
        return None
    return {
        "account_id": account.id,
        "last_used_at": last_used.isoformat(),
        "age_days": age_days,
        "dormant_days": dormant_days,
    }


def _datetime_attr(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=utc_now().tzinfo)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=utc_now().tzinfo)
    return None


def _allowed_entitlements(identity: AQObject, config: IAGConfig) -> set[str] | None:
    direct = _string_list_attr(identity.attributes.get("allowed_entitlement_ids"))
    if direct is not None:
        return direct
    if config.peer_baseline is None:
        return None
    baselines = identity.attributes.get("peer_baselines")
    if not isinstance(baselines, dict):
        return None
    return _string_list_attr(baselines.get(config.peer_baseline))


def _string_list_attr(value: object) -> set[str] | None:
    if not isinstance(value, list):
        return None
    strings: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        strings.add(item)
    return strings


def _identity_access_resource(
    identity: AQObject,
    *,
    entitlement_ids: Sequence[str],
    role_ids: Sequence[str],
    account_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "id": identity.id,
        "type": "identity_access",
        "object_type": "identity_access",
        "tenant_id": identity.tenant_id,
        "display_name": identity.display_name,
        "attributes": {
            "identity_id": identity.id,
            "entitlement_ids": list(entitlement_ids),
            "role_ids": list(role_ids),
            "account_ids": list(account_ids),
        },
    }


def _is_privileged(role: AQObject, config: IAGConfig) -> bool:
    aliases = {role.id, role.display_name}
    for key in ("name", "slug", "external_id"):
        value = role.attributes.get(key)
        if isinstance(value, str):
            aliases.add(value)
    return any(value in aliases for value in config.privileged_roles)


def _review_current(identity: AQObject, config: IAGConfig) -> bool:
    decision = identity.attributes.get("last_privileged_review_decision")
    if decision is not None and decision not in ("approved", "certified", "pass", "passed"):
        return False
    reviewed_at = _datetime_attr(
        identity.attributes.get("last_privileged_review_at")
        or identity.attributes.get("privileged_reviewed_at")
    )
    if reviewed_at is None:
        return False
    cutoff = utc_now() - timedelta(days=config.review_default_due_days)
    return reviewed_at >= cutoff


def _path_for_entitlement(paths: Sequence[AccessPath], entitlement_id: str) -> Path | None:
    for path in paths:
        if entitlement_id in path.entitlement_ids:
            return path.via
    return None


def _path_for_role(paths: Sequence[AccessPath], role_id: str) -> Path | None:
    for path in paths:
        if role_id in path.via.node_ids:
            return path.via
    return None


def _access_path_sort_key(path: AccessPath) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    return (
        path.identity_id,
        path.account_id or "",
        tuple(path.entitlement_ids),
        tuple(path.via.node_ids),
    )


def _risk_sort_key(risk: AccessRisk) -> tuple[str, str, str, str]:
    return (
        risk.kind,
        risk.subject_id,
        str(risk.detail.get("entitlement_id", "")),
        risk.reason,
    )
