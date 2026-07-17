"""Vulnerability Intelligence AQService wrapper and events (EA-0024 V5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.assetconfig.models import DriftSnapshot
from aqelyn.assetconfig.store import DriftSnapshotStore
from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    CoverageUnavailable,
    ObjectNotFound,
    StoreUnavailable,
    VulnConfigInvalid,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.exposure.store import ExposureStore
from aqelyn.findings import Finding
from aqelyn.forecast import TrendRecord
from aqelyn.kernel.service import HealthStatus
from aqelyn.risk import CorrelationSignal
from aqelyn.vuln.engine import PriorityFactor, VulnerabilityIntelligenceEngine
from aqelyn.vuln.models import (
    CarriedScore,
    CoverageReport,
    RemediationPlan,
    VulnBasis,
    VulnConfig,
    VulnerabilityAssessment,
    VulnerabilityRecord,
    VulnPriority,
)
from aqelyn.vuln.store import VulnerabilityStore

VULN_EVENTS: dict[str, int] = {
    "aqelyn.vuln.discovered": 1,
    "aqelyn.vuln.prioritized": 1,
    "aqelyn.vuln.exploit_correlated": 1,
    "aqelyn.vuln.remediation_recommended": 1,
    "aqelyn.vuln.reassessed": 1,
}


def register_vuln_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in VULN_EVENTS.items():
        registry.register(event_type, schema_version, None)


class InertVulnerabilityCoverageProvider:
    """Refusing coverage default until wired to an authoritative asset inventory.

    Per ECR-0013, an unwired dependency's default must be inert or refusing, never
    optimistic. Reporting ``unscanned=[]`` from the vulnerability store alone (which
    knows only ingested vulns, not the asset universe) would present incomplete
    coverage as complete - the exact "not scanned = clean" outcome EA-0024 S4 exists
    to prevent. So this refuses; ``assess()`` refuses in turn. EA-0025 ``inventory()``
    supplies the real coverage denominator (C-022 N6), replacing this.
    """

    async def coverage(self, *, tenant_id: str | None) -> CoverageReport:
        _ = tenant_id
        raise CoverageUnavailable(
            "vulnerability coverage is not wired to an authoritative asset inventory "
            "(ECR-0013): refusing rather than reporting incomplete coverage as complete"
        )


class ThreatSignalFactorProvider:
    def __init__(self, threat_engine: object) -> None:
        self.threat_engine = threat_engine

    async def exploitation_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        signals = _risk_signals(self.threat_engine)
        matching = [
            signal for signal in signals if _signal_matches_vulnerability(signal, vulnerability)
        ]
        if not matching:
            return PriorityFactor(
                0.0,
                "threat:none",
                "EA-0014 threat fusion has no matching exploitation signal.",
            )
        selected = max(
            matching,
            key=lambda signal: (signal.weight * signal.impact, signal.ref_id),
        )
        return PriorityFactor(
            _clamp_unit(selected.weight * selected.impact),
            f"threat:{selected.ref_id}",
            selected.reason or "EA-0014 threat fusion supplied a matching exploitation signal.",
        )


class ExposureStoreReachabilityProvider:
    def __init__(self, exposure_store: ExposureStore, *, limit: int = 1000) -> None:
        self.exposure_store = exposure_store
        self.limit = limit

    async def reachability_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        rows = await self.exposure_store.query(tenant_id=vulnerability.tenant_id, limit=self.limit)
        matching = [
            row
            for row in rows
            if row.asset_ref.kind == vulnerability.asset_ref.kind
            and row.asset_ref.ref_id == vulnerability.asset_ref.ref_id
        ]
        if not matching:
            return PriorityFactor(
                0.0,
                "exposure:none",
                "EA-0023 exposure has no matching reachability record.",
            )
        selected = max(
            matching,
            key=lambda row: (_reachability_factor(row.reachability), row.id),
        )
        return PriorityFactor(
            _reachability_factor(selected.reachability),
            f"exposure:{selected.id}",
            f"EA-0023 reports {selected.reachability} reachability.",
        )


class DriftSnapshotBlockingProvider:
    def __init__(self, snapshot_store: DriftSnapshotStore) -> None:
        self.snapshot_store = snapshot_store

    async def blocking_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        snapshot = await self.snapshot_store.latest(tenant_id=vulnerability.tenant_id)
        if snapshot is None:
            return PriorityFactor(
                0.0,
                "baseline:none",
                "EA-0012 has no drift snapshot for this tenant.",
            )
        return _blocking_from_snapshot(snapshot, vulnerability)


class VulnerabilityIntelligenceService:
    def __init__(
        self,
        engine: VulnerabilityIntelligenceEngine,
        *,
        store: VulnerabilityStore,
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "inventory_engine",
            "threat_fusion_engine",
            "exposure_engine",
            "mission_engine",
            "acg_engine",
            "trust_engine",
            "forecast_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.store = store
        self._close_store = close_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "vuln_engine"

    @property
    def dependencies(self) -> Sequence[str]:
        return self._dependencies

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_available()
        self._started = True

    async def stop(self) -> None:
        try:
            if self._close_store is not None:
                await self._close_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_store()
            dependencies["vulnerability_store"] = "healthy"
            dependencies["coverage_provider"] = await self._check_coverage_provider()
            await self._check_threat_provider()
            dependencies["threat_fusion_engine"] = "healthy"
            await self._check_exposure_provider()
            dependencies["exposure_engine"] = "healthy"
            await self._check_mission_provider()
            dependencies["mission_engine"] = "healthy"
            await self._check_baseline_provider()
            dependencies["acg_engine"] = "healthy"
            await self._check_trust_provider()
            dependencies["trust_engine"] = "healthy"
            self._check_trend_provider()
            dependencies["forecast_engine"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
        except VulnConfigInvalid as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
        except Exception as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=str(exc),
                dependencies=dependencies,
            )

        if not self._started:
            return HealthStatus(
                status="degraded",
                ready=False,
                detail="service not started",
                dependencies=dependencies,
            )
        return HealthStatus(status="healthy", ready=True, dependencies=dependencies)

    async def ingest(
        self,
        *,
        records: Sequence[VulnerabilityRecord],
        tenant_id: str | None,
    ) -> list[VulnerabilityRecord]:
        return await self.engine.ingest(records=records, tenant_id=tenant_id)

    async def prioritize(self, vulnerability_id: str, *, tenant_id: str | None) -> VulnPriority:
        return await self.engine.prioritize(vulnerability_id, tenant_id=tenant_id)

    async def assess(self, *, tenant_id: str | None) -> VulnerabilityAssessment:
        return await self.engine.assess(tenant_id=tenant_id)

    async def recommend(self, priority: VulnPriority, *, tenant_id: str | None) -> RemediationPlan:
        return await self.engine.recommend(priority, tenant_id=tenant_id)

    async def raise_vulnerability(self, priority: VulnPriority, *, by: ActorRef) -> Finding:
        return await self.engine.raise_vulnerability(priority, by=by)

    async def trend(
        self, *, metric: str = "vulnerabilities.open", window_days: int = 30, tenant_id: str | None
    ) -> TrendRecord:
        return await self.engine.trend(metric=metric, window_days=window_days, tenant_id=tenant_id)

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_store()
        await self._check_coverage_provider()
        await self._check_threat_provider()
        await self._check_exposure_provider()
        await self._check_mission_provider()
        await self._check_baseline_provider()
        await self._check_trust_provider()
        self._check_trend_provider()
        await self._check_finding_store()

    def _check_config(self) -> None:
        VulnConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self.store.get(new_id("vln"), tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability store unavailable: {exc}") from exc

    async def _check_coverage_provider(self) -> str:
        provider = self.engine.coverage_provider
        if provider is None:
            raise StoreUnavailable("vulnerability coverage provider unavailable")
        # An intentionally inert/refusing default (ECR-0013) is an acceptable known
        # state: the service still ingests and prioritizes, and assess() refuses
        # rather than reporting incomplete coverage as complete.
        if isinstance(provider, InertVulnerabilityCoverageProvider):
            return "inert"
        try:
            await provider.coverage(tenant_id=None)
        except CoverageUnavailable as exc:
            raise StoreUnavailable(exc.message) from exc
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability coverage provider unavailable: {exc}") from exc
        return "healthy"

    async def _check_threat_provider(self) -> None:
        if self.engine.threat_provider is None:
            raise StoreUnavailable("vulnerability threat provider unavailable")
        try:
            await self.engine.threat_provider.exploitation_factor(_health_vulnerability())
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability threat provider unavailable: {exc}") from exc

    async def _check_exposure_provider(self) -> None:
        if self.engine.exposure_provider is None:
            raise StoreUnavailable("vulnerability exposure provider unavailable")
        try:
            await self.engine.exposure_provider.reachability_factor(_health_vulnerability())
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability exposure provider unavailable: {exc}") from exc

    async def _check_mission_provider(self) -> None:
        if self.engine.mission_provider is None:
            raise StoreUnavailable("vulnerability mission provider unavailable")
        try:
            await self.engine.mission_provider.mission_impact(new_id("obj"))
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability mission provider unavailable: {exc}") from exc

    async def _check_baseline_provider(self) -> None:
        if self.engine.baseline_provider is None:
            raise StoreUnavailable("vulnerability baseline provider unavailable")
        try:
            await self.engine.baseline_provider.blocking_factor(_health_vulnerability())
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability baseline provider unavailable: {exc}") from exc

    async def _check_trust_provider(self) -> None:
        if self.engine.trust_provider is None:
            raise StoreUnavailable("vulnerability trust provider unavailable")
        try:
            await self.engine.trust_provider.scanner_trust(_health_vulnerability())
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability trust provider unavailable: {exc}") from exc

    def _check_trend_provider(self) -> None:
        if not callable(getattr(self.engine.trend_provider, "analyze_trend", None)):
            raise StoreUnavailable("vulnerability forecast provider unavailable")

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("vulnerability finding store unavailable")
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"vulnerability finding store unavailable: {exc}") from exc


def _risk_signals(source: object) -> Sequence[CorrelationSignal]:
    selected = getattr(source, "risk_signals", ())
    if callable(selected):
        selected = selected()
    if not isinstance(selected, Sequence) or isinstance(selected, str | bytes):
        return ()
    return [signal for signal in selected if isinstance(signal, CorrelationSignal)]


def _signal_matches_vulnerability(
    signal: CorrelationSignal, vulnerability: VulnerabilityRecord
) -> bool:
    asset_id = vulnerability.asset_ref.ref_id
    if asset_id in signal.affected_object_ids:
        return True
    haystack = " ".join((signal.ref_id, signal.correlation_key, signal.title, signal.category))
    return vulnerability.cve_id in haystack


def _blocking_from_snapshot(
    snapshot: DriftSnapshot,
    vulnerability: VulnerabilityRecord,
) -> PriorityFactor:
    matching = [
        drift for drift in snapshot.asset_drifts if drift.asset_id == vulnerability.asset_ref.ref_id
    ]
    if not matching:
        return PriorityFactor(
            0.0,
            f"baseline:{snapshot.id}",
            "EA-0012 latest drift snapshot has no matching asset drift.",
        )
    selected = max(matching, key=lambda drift: (drift.score, drift.baseline_id))
    return PriorityFactor(
        _clamp_unit(selected.score),
        f"baseline:{snapshot.id}:{selected.baseline_id}",
        "EA-0012 latest drift snapshot indicates existing baseline control coverage.",
    )


def _reachability_factor(reachability: str) -> float:
    if reachability == "external":
        return 1.0
    if reachability == "internal":
        return 0.45
    return 0.15


def _health_vulnerability() -> VulnerabilityRecord:
    now = utc_now()
    return VulnerabilityRecord(
        tenant_id=None,
        cve_id="CVE-2099-0000",
        scanner="healthcheck",
        asset_ref={"kind": "asset", "ref_id": new_id("obj"), "evidence_id": new_id("evd")},
        severity="none",
        cvss=CarriedScore(source="healthcheck", value=0.0, vector=None, as_of=now),
        epss=None,
        confidence=0.0,
        basis=[
            VulnBasis(
                kind="scanner",
                ref="healthcheck",
                as_of=now,
                evidence_id=new_id("evd"),
            )
        ],
        discovered_at=now,
    )


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))
