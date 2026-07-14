"""Risk signal correlation (EA-0013 R2)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from aqelyn.conventions import require_tenant_id, utc_now
from aqelyn.conventions.errors import RiskConfigInvalid
from aqelyn.findings import Finding, FindingQuery, FindingStore
from aqelyn.risk.models import CorrelationSignal, Risk, RiskConfig, SignalRef

OPEN_FINDING_STATUSES = ("open", "acknowledged", "in_progress")
DEFAULT_CORRELATION_LIMIT = 100
MAX_CORRELATION_LIMIT = 10_000


class RiskCorrelator:
    """Correlates findings and governance signals into first-class Risk records."""

    def __init__(
        self,
        finding_store: FindingStore,
        *,
        config: RiskConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.finding_store = finding_store
        self.config = config or RiskConfig()
        self._clock = clock

    async def correlate(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
        signals: Sequence[CorrelationSignal] = (),
    ) -> list[Risk]:
        tenant_id = require_tenant_id(tenant_id)
        limit = _correlation_limit(self.config, scope)
        finding_status = _finding_status(scope)
        gathered = await self._finding_signals(
            tenant_id=tenant_id,
            status=finding_status,
            limit=limit,
        )
        gathered.extend(_visible_external_signals(signals, tenant_id=tenant_id, limit=limit))
        if not gathered:
            return []
        gathered = sorted(gathered, key=_signal_sort_key)

        grouped: dict[str, list[CorrelationSignal]] = defaultdict(list)
        for signal in gathered[:limit]:
            grouped[signal.correlation_key].append(signal)

        risks = [
            _risk_from_group(key, group, now=self._now())
            for key, group in sorted(grouped.items(), key=lambda item: item[0])
        ]
        return risks[:limit]

    def explain(self, risk: Risk) -> dict[str, object]:
        return explain(risk)

    async def _finding_signals(
        self,
        *,
        tenant_id: str | None,
        status: tuple[str, ...],
        limit: int,
    ) -> list[CorrelationSignal]:
        findings, _ = await self.finding_store.query(
            FindingQuery(tenant_id=tenant_id, status=status, limit=limit)
        )
        return [_signal_from_finding(finding) for finding in findings]

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else utc_now()


async def correlate(
    finding_store: FindingStore,
    *,
    tenant_id: str | None,
    scope: Mapping[str, object] | None = None,
    signals: Sequence[CorrelationSignal] = (),
    config: RiskConfig | None = None,
) -> list[Risk]:
    return await RiskCorrelator(finding_store, config=config).correlate(
        tenant_id=tenant_id,
        scope=scope,
        signals=signals,
    )


def explain(risk: Risk) -> dict[str, object]:
    return {
        "risk_id": risk.id,
        "method": "correlation_key/v1",
        "correlation_key": risk.correlation_key,
        "title": risk.title,
        "category": risk.category,
        "tenant_id": risk.tenant_id,
        "signal_count": len(risk.signals),
        "signals": [signal.model_dump(mode="json") for signal in risk.signals],
        "affected_object_ids": list(risk.affected_object_ids),
        "impact": risk.impact,
        "reason": risk.reason,
    }


def _signal_from_finding(finding: Finding) -> CorrelationSignal:
    affected = sorted(finding.affected_object_ids)
    return CorrelationSignal(
        kind="finding",
        ref_id=finding.id,
        tenant_id=finding.tenant_id,
        correlation_key=_finding_correlation_key(finding, affected),
        title=finding.title,
        category=finding.finding_type,
        weight=_unit(finding.confidence),
        impact=_unit(finding.severity_score / 100.0),
        affected_object_ids=affected,
        evidence_id=sorted(finding.evidence_ids)[0] if finding.evidence_ids else None,
        reason=finding.why_it_matters,
        observed_at=finding.last_detected_at,
    )


def _finding_correlation_key(finding: Finding, affected: Sequence[str]) -> str:
    if finding.correlation_id is not None and finding.correlation_id.strip():
        return finding.correlation_id
    if affected:
        return f"finding:{finding.finding_type}:{','.join(affected)}"
    return f"finding:{finding.finding_type}:{finding.dedup_key}"


def _risk_from_group(key: str, signals: Sequence[CorrelationSignal], *, now: datetime) -> Risk:
    ordered = sorted(signals, key=lambda signal: (signal.kind, signal.ref_id))
    risk_signals = [
        SignalRef(
            kind=signal.kind,
            ref_id=signal.ref_id,
            weight=signal.weight,
            evidence_id=signal.evidence_id,
        )
        for signal in ordered
    ]
    affected_object_ids = sorted(
        {object_id for signal in ordered for object_id in signal.affected_object_ids}
    )
    tenant_ids = {signal.tenant_id for signal in ordered}
    tenant_id = next(iter(tenant_ids)) if len(tenant_ids) == 1 else None
    impact = max((signal.impact for signal in ordered), default=0.0)
    title = _title_for(key, ordered)
    category = _category_for(ordered)
    reason = (
        f"Correlated {len(ordered)} signal(s) into risk {key}. "
        f"Signal refs: {', '.join(signal.ref_id for signal in ordered)}."
    )
    return Risk(
        id=_risk_id(tenant_id, key),
        tenant_id=tenant_id,
        correlation_key=key,
        title=title,
        category=category,
        likelihood=0.0,
        impact=impact,
        score=0.0,
        band="within_appetite",
        signals=risk_signals,
        affected_object_ids=affected_object_ids,
        reason=reason,
        factors={"max_signal_impact": impact},
        first_seen_at=now,
        last_scored_at=now,
    )


def _risk_id(tenant_id: str | None, key: str) -> str:
    """Tenant-qualified, deterministic risk id (ECR-0003).

    The correlation key alone is caller-controllable and can be shared across
    tenants (e.g. a governance signal or ``finding.correlation_id`` taxonomy).
    Since ``id`` is the ``aq_risk`` primary key, the tenant segment keeps two
    tenants that share a ``correlation_key`` from colliding on the PK. The
    tenant id is a UUID (or the literal ``global``), so the ``:``-delimited
    prefix is unambiguous.
    """
    return f"risk:{tenant_id or 'global'}:{key}"


def _title_for(key: str, signals: Sequence[CorrelationSignal]) -> str:
    titles = sorted({signal.title for signal in signals})
    if len(titles) == 1:
        return titles[0]
    return f"Risk correlated by {key}"


def _category_for(signals: Sequence[CorrelationSignal]) -> str:
    categories = sorted({signal.category for signal in signals})
    return categories[0] if len(categories) == 1 else "correlated"


def _visible_external_signals(
    signals: Sequence[CorrelationSignal],
    *,
    tenant_id: str | None,
    limit: int,
) -> list[CorrelationSignal]:
    return [
        signal
        for signal in sorted(signals, key=_signal_sort_key)
        if _tenant_visible(signal.tenant_id, tenant_id)
    ][:limit]


def _tenant_visible(signal_tenant_id: str | None, tenant_id: str | None) -> bool:
    if tenant_id is None:
        return signal_tenant_id is None
    return signal_tenant_id == tenant_id


def _correlation_limit(config: RiskConfig, scope: Mapping[str, object] | None) -> int:
    raw = None
    if scope is not None and "limit" in scope:
        raw = scope["limit"]
    elif "max_signals" in config.correlation:
        raw = config.correlation["max_signals"]
    if raw is None:
        return DEFAULT_CORRELATION_LIMIT
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise RiskConfigInvalid("correlation limit must be an integer")
    if raw < 1:
        raise RiskConfigInvalid("correlation limit must be >= 1")
    return min(raw, MAX_CORRELATION_LIMIT)


def _finding_status(scope: Mapping[str, object] | None) -> tuple[str, ...]:
    if scope is None or "finding_status" not in scope:
        return OPEN_FINDING_STATUSES
    raw = scope["finding_status"]
    if isinstance(raw, str):
        return (raw,)
    if not isinstance(raw, Sequence):
        raise RiskConfigInvalid("finding_status scope must be a string or sequence")
    status: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise RiskConfigInvalid("finding_status scope must contain non-empty strings")
        status.append(item)
    if not status:
        raise RiskConfigInvalid("finding_status scope must not be empty")
    return tuple(status)


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _signal_sort_key(signal: CorrelationSignal) -> tuple[str, str, str]:
    return (signal.correlation_key, signal.kind, signal.ref_id)
