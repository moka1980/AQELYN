"""Threat Detection AQService wrapper and events (EA-0017 D5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, ObjectNotFound, StoreUnavailable
from aqelyn.detection.engine import ThreatDetectionEngine
from aqelyn.detection.models import DetectionConfig
from aqelyn.detection.store import ProfileStore, RuleStore
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus
from aqelyn.trust.models import TrustConfig

DETECTION_EVENTS: dict[str, int] = {
    "aqelyn.detection.threat_detected": 1,
    "aqelyn.detection.anomaly_detected": 1,
    "aqelyn.detection.profile_updated": 1,
}


def register_detection_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in DETECTION_EVENTS.items():
        registry.register(event_type, schema_version, None)


class ThreatDetectionService:
    def __init__(
        self,
        engine: ThreatDetectionEngine,
        *,
        rule_store: RuleStore,
        profile_store: ProfileStore,
        threat_engine: object | None = None,
        close_rule_store: Callable[[], Awaitable[None]] | None = None,
        close_profile_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "trust_engine",
            "mission_engine",
            "threat_fusion_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.rule_store = rule_store
        self.profile_store = profile_store
        self.threat_engine = threat_engine
        self._close_rule_store = close_rule_store
        self._close_profile_store = close_profile_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "detection_engine"

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
            if self._close_profile_store is not None:
                await self._close_profile_store()
            if self._close_rule_store is not None:
                await self._close_rule_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_rule_store()
            dependencies["rule_store"] = "healthy"
            await self._check_profile_store()
            dependencies["profile_store"] = "healthy"
            await self._check_trust_engine()
            dependencies["trust_engine"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
            await self._check_mission_engine()
            dependencies["mission_engine"] = "healthy"
            self._check_threat_engine()
            dependencies["threat_fusion_engine"] = "healthy"
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

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_rule_store()
        await self._check_profile_store()
        await self._check_trust_engine()
        await self._check_evidence_store()
        await self._check_finding_store()
        await self._check_mission_engine()
        self._check_threat_engine()

    def _check_config(self) -> None:
        DetectionConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_rule_store(self) -> None:
        try:
            await self.rule_store.get("healthcheck-detection-rule")
        except Exception as exc:
            raise StoreUnavailable(f"detection rule store unavailable: {exc}") from exc

    async def _check_profile_store(self) -> None:
        try:
            await self.profile_store.get(new_id("prf"))
        except Exception as exc:
            raise StoreUnavailable(f"detection profile store unavailable: {exc}") from exc

    async def _check_trust_engine(self) -> None:
        try:
            TrustConfig.model_validate(self.engine.trust_engine.config.model_dump(mode="json"))
            await self.engine.trust_engine.registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"detection trust engine unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        if self.engine.evidence_store is None:
            raise StoreUnavailable("detection evidence store unavailable")
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"detection evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("detection finding store unavailable")
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"detection finding store unavailable: {exc}") from exc

    async def _check_mission_engine(self) -> None:
        if self.engine.mission_engine is None:
            raise StoreUnavailable("detection mission engine unavailable")
        try:
            await self.engine.mission_engine.mission_impact(new_id("obj"))
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"detection mission engine unavailable: {exc}") from exc

    def _check_threat_engine(self) -> None:
        if self.threat_engine is None:
            raise StoreUnavailable("detection threat fusion engine unavailable")

    async def evaluate_rules(self, **kwargs: Any) -> object:
        return await self.engine.evaluate_rules(**kwargs)

    async def detect_anomalies(self, **kwargs: Any) -> object:
        return await self.engine.detect_anomalies(**kwargs)

    async def correlate_signals(self, **kwargs: Any) -> object:
        return await self.engine.correlate_signals(**kwargs)

    async def detections_to_findings(self, **kwargs: Any) -> object:
        return await self.engine.detections_to_findings(**kwargs)

    async def project(self, **kwargs: Any) -> object:
        return await self.engine.project(**kwargs)

    async def reproduce(self, detection_id: str) -> object:
        return await self.engine.reproduce(detection_id)
