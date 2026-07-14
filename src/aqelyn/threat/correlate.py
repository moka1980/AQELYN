"""Threat indicator correlation against estate objects (EA-0014 T3)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from aqelyn.conventions import utc_now
from aqelyn.conventions.errors import ObjectNotFound, ThreatConfigInvalid
from aqelyn.graph import KnowledgeGraph, Path, Subgraph
from aqelyn.objects import AQObject, ObjectQuery, ObjectStore
from aqelyn.threat.models import (
    THREAT_OBJECT_TYPES,
    MatchReport,
    ThreatIndicator,
    ThreatMatch,
)
from aqelyn.threat.normalize import object_to_indicator

DEFAULT_CORRELATION_LIMIT = 100
DEFAULT_WITHIN_HOPS = 2
DEFAULT_MAX_NODES = 10_000


async def correlate(
    *,
    object_store: ObjectStore,
    graph: KnowledgeGraph,
    tenant_id: str | None,
    config: Mapping[str, object],
    min_match_confidence: float,
    scope: ObjectQuery | None = None,
    now: datetime | None = None,
) -> MatchReport:
    clock = _as_utc(now or utc_now())
    limits = _CorrelationLimits.from_config(config)
    indicators = await _active_indicators(
        object_store,
        tenant_id=tenant_id,
        limit=limits.limit,
        now=clock,
    )
    assets = await _assets(
        object_store,
        tenant_id=tenant_id,
        scope=scope,
        limit=limits.limit,
    )
    matches: dict[tuple[str, str], ThreatMatch] = {}
    truncated = False

    for indicator in indicators:
        if indicator.confidence < min_match_confidence:
            continue
        for asset in assets:
            match_type = _attribute_match_type(indicator, asset.attributes)
            if match_type is None:
                continue
            matches[(indicator.id, asset.id)] = _match(
                indicator,
                asset_id=asset.id,
                match_type=match_type,
                reason=(
                    f"{indicator.indicator_type} indicator {indicator.value!r} matched "
                    f"asset attribute on {asset.display_name}."
                ),
            )
        graph_result = await _safe_graph_correlate(
            graph,
            [indicator.id],
            within_hops=limits.within_hops,
            relation_types=limits.relation_types,
            max_nodes=limits.max_nodes,
        )
        if graph_result is not None:
            truncated = truncated or graph_result.truncated
            for node in graph_result.nodes:
                if node.id == indicator.id or node.object_type in THREAT_OBJECT_TYPES:
                    continue
                if node.tenant_id != tenant_id:
                    continue
                if (indicator.id, node.id) in matches:
                    continue
                via = await graph.shortest_path(
                    indicator.id,
                    node.id,
                    direction="both",
                    relation_types=limits.relation_types,
                    max_depth=limits.within_hops,
                )
                matches[(indicator.id, node.id)] = _match(
                    indicator,
                    asset_id=node.id,
                    match_type=f"graph:{indicator.indicator_type}",
                    reason=(
                        f"{indicator.indicator_type} indicator {indicator.value!r} reached "
                        f"asset {node.display_name} through the knowledge graph."
                    ),
                    via=via,
                )

    if matches:
        graph_context = await _safe_graph_correlate(
            graph,
            sorted({match.asset_id for match in matches.values()}),
            within_hops=limits.within_hops,
            relation_types=limits.relation_types,
            max_nodes=limits.max_nodes,
        )
        if graph_context is not None:
            truncated = truncated or graph_context.truncated

    ordered = sorted(matches.values(), key=lambda item: (item.indicator_id, item.asset_id))
    if len(ordered) > limits.limit:
        # The match list itself is bounded; dropping matches must be reported as
        # truncated so a partial result is never presented as complete (§11/FR-6).
        truncated = True
    return MatchReport(
        matches=ordered[: limits.limit],
        evaluated=len(indicators),
        truncated=truncated,
    )


def explain(match: ThreatMatch) -> dict[str, object]:
    return {
        "indicator_id": match.indicator_id,
        "asset_id": match.asset_id,
        "match_type": match.match_type,
        "confidence": match.confidence,
        "evidence_id": match.evidence_id,
        "reason": match.reason,
        "via": None if match.via is None else match.via.model_dump(mode="json"),
    }


class _CorrelationLimits:
    def __init__(
        self,
        *,
        limit: int,
        within_hops: int,
        max_nodes: int,
        relation_types: tuple[str, ...] | None,
    ) -> None:
        self.limit = limit
        self.within_hops = within_hops
        self.max_nodes = max_nodes
        self.relation_types = relation_types

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> _CorrelationLimits:
        return cls(
            limit=_positive_int(config.get("limit"), default=DEFAULT_CORRELATION_LIMIT),
            within_hops=_positive_int(config.get("within_hops"), default=DEFAULT_WITHIN_HOPS),
            max_nodes=_positive_int(config.get("max_nodes"), default=DEFAULT_MAX_NODES),
            relation_types=_string_tuple(config.get("relation_types")),
        )


async def _active_indicators(
    object_store: ObjectStore,
    *,
    tenant_id: str | None,
    limit: int,
    now: datetime,
) -> list[ThreatIndicator]:
    objects, _ = await object_store.query(
        ObjectQuery(
            tenant_id=tenant_id,
            object_type="threat_indicator",
            include_states=("active",),
            limit=limit,
        )
    )
    indicators: list[ThreatIndicator] = []
    for obj in objects:
        indicator = object_to_indicator(obj)
        if indicator.expires_at is not None and _as_utc(indicator.expires_at) <= now:
            continue
        indicators.append(indicator)
    return sorted(indicators, key=lambda item: item.id)


async def _assets(
    object_store: ObjectStore,
    *,
    tenant_id: str | None,
    scope: ObjectQuery | None,
    limit: int,
) -> list[AQObject]:
    # Exclude the engine's own threat objects at the query level so the limit
    # applies to estate assets, not to indicators competing for the budget
    # (ECR-0004). A post-filter alone would let indicators starve the asset page.
    scope_excludes = tuple(scope.exclude_object_types) if scope is not None else ()
    excludes = tuple(dict.fromkeys((*scope_excludes, *THREAT_OBJECT_TYPES)))
    query = (scope or ObjectQuery()).model_copy(
        update={
            "tenant_id": tenant_id,
            "include_states": ("active", "archived"),
            "exclude_object_types": excludes,
            "limit": min((scope.limit if scope is not None else limit), limit),
        }
    )
    objects, _ = await object_store.query(query)
    return sorted(
        [obj for obj in objects if obj.object_type not in THREAT_OBJECT_TYPES],
        key=lambda item: item.id,
    )


async def _safe_graph_correlate(
    graph: KnowledgeGraph,
    seed_ids: Sequence[str],
    *,
    within_hops: int,
    relation_types: Sequence[str] | None,
    max_nodes: int,
) -> Subgraph | None:
    if not seed_ids:
        return None
    try:
        return await graph.correlate(
            seed_ids,
            within_hops=within_hops,
            relation_types=relation_types,
            max_nodes=max_nodes,
        )
    except ObjectNotFound:
        return None


def _match(
    indicator: ThreatIndicator,
    *,
    asset_id: str,
    match_type: str,
    reason: str,
    via: Path | None = None,
) -> ThreatMatch:
    evidence_id = next(
        (source.evidence_id for source in indicator.sources if source.evidence_id is not None),
        None,
    )
    return ThreatMatch(
        indicator_id=indicator.id,
        asset_id=asset_id,
        match_type=match_type,
        confidence=indicator.confidence,
        evidence_id=evidence_id,
        reason=reason,
        via=via,
    )


def _attribute_match_type(indicator: ThreatIndicator, attributes: Mapping[str, Any]) -> str | None:
    if _contains_value(attributes, indicator.value):
        return f"attribute:{indicator.indicator_type}"
    return None


def _contains_value(value: object, needle: str) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == needle.lower()
    if isinstance(value, Mapping):
        return any(_contains_value(item, needle) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return any(_contains_value(item, needle) for item in value)
    return False


def _positive_int(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ThreatConfigInvalid("correlation bounds must be positive integers")
    if value < 1:
        raise ThreatConfigInvalid("correlation bounds must be >= 1")
    return value


def _string_tuple(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ThreatConfigInvalid("relation_types must be a sequence of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ThreatConfigInvalid("relation_types must contain non-empty strings")
        out.append(item)
    return tuple(out)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
