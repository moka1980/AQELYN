"""S-004 privileged attribution and owner-routed exposure derivation.

Private capture values stay inside this tools-only layer. The public result keeps
the detailed rows local; only existing count-only summaries may reach reporting.
"""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, model_validator
from tools.first_run import FactorReading
from tools.s003_estate import EstateAsset, ListenerObservation
from tools.s003_surface import (
    InventorySurfaceOwner,
    SurfaceApplication,
    attribute_listener_observations,
    build_surface_application_from_observations,
    classify_bind,
    register_service_assets,
)
from tools.s004_handin import HandedInCaptureSet, ProxyRouteDeclaration

from aqelyn.exposure import (
    AssetRef,
    AttackSurfaceAsset,
    ExposureBasis,
    ExposureConfig,
    ExposureStore,
    KnownDataExposureEngine,
    KnownSurfaceRecord,
    KnownSurfaceSource,
    Reachability,
)
from aqelyn.inventory import DiscoverySource, InventoryKnownSurfaceSource
from aqelyn.vuln import FactorUnknownCause

TopologyState = Literal["derived", "off_estate", "join_unavailable"]

CONFIGURATION_ROUTE_DERIVED = "proxy route derived from fresh configuration and host state"
UPSTREAM_OFF_ESTATE = "proxy upstream is not present in the host listener observations"
TOPOLOGY_JOIN_UNAVAILABLE = "proxy route cannot be joined uniquely to host assets"


class S004RouteError(RuntimeError):
    """The fresh capture set cannot be routed to its owners honestly."""


class S004SurfaceDerivation(BaseModel):
    """Detailed local result of the W4 owner handoff."""

    model_config = ConfigDict(extra="forbid")

    registered_asset_ids: dict[str, str]
    attributed_listeners: list[ListenerObservation]
    application: SurfaceApplication
    attack_surface: list[AttackSurfaceAsset]

    @model_validator(mode="after")
    def _roster_is_consistent(self) -> S004SurfaceDerivation:
        registered = set(self.registered_asset_ids.values())
        if {row.asset_ref.ref_id for row in self.attack_surface} != registered:
            raise ValueError("EA-0023 attack surface must cover the registered service roster")
        derived = {
            outcome.asset_id
            for outcome in self.application.outcomes
            if outcome.state == "derived" and outcome.asset_id is not None
        }
        observed = {row.asset_id for row in self.application.observed_surface}
        if derived != observed:
            raise ValueError("W4 derived outcomes must match the observed surface overlay")
        return self


class ProxyTopologyOutcome(BaseModel):
    """One private route outcome; identifying refs never cross the count-only boundary."""

    model_config = ConfigDict(extra="forbid")

    state: TopologyState
    frontend_ref: str
    upstream_ref: str
    frontend_asset_id: str | None = None
    upstream_asset_id: str | None = None
    reachability: Reachability | None = None
    unknown_cause: FactorUnknownCause | None = None
    reason: str
    configuration_ref: str
    certificate_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _state_is_total(self) -> ProxyTopologyOutcome:
        if not all(
            value.strip()
            for value in (
                self.frontend_ref,
                self.upstream_ref,
                self.reason,
                self.configuration_ref,
            )
        ):
            raise ValueError("proxy topology references and reason must not be empty")
        if self.state == "derived":
            if self.frontend_asset_id is None or self.upstream_asset_id is None:
                raise ValueError("derived proxy topology requires both local assets")
            if self.reachability is None:
                raise ValueError("derived proxy topology requires a reachability state")
            expected_cause = "source_cannot_assert" if self.reachability == "unknown" else None
            if self.unknown_cause != expected_cause:
                raise ValueError("derived proxy topology cause contradicts its reachability")
            return self
        if self.upstream_asset_id is not None or self.reachability is not None:
            raise ValueError("unknown proxy topology cannot claim a local upstream")
        if self.unknown_cause is None:
            raise ValueError("unknown proxy topology requires a typed cause")
        return self


class ProxyTopologySummary(BaseModel):
    """Count-only W5 output."""

    model_config = ConfigDict(extra="forbid")

    derived: int = 0
    off_estate: int = 0
    join_unavailable: int = 0


class ProxyTopologyApplication(BaseModel):
    """Private topology results and the exact EA-0023 overlay they justify."""

    model_config = ConfigDict(extra="forbid")

    outcomes: list[ProxyTopologyOutcome]
    surface_records: list[KnownSurfaceRecord]

    @model_validator(mode="after")
    def _records_are_justified(self) -> ProxyTopologyApplication:
        derived_ids = {
            outcome.upstream_asset_id for outcome in self.outcomes if outcome.state == "derived"
        }
        record_ids = {record.asset_ref.ref_id for record in self.surface_records}
        if derived_ids != record_ids:
            raise ValueError("configuration surface rows must match derived local upstreams")
        return self

    def aggregate(self) -> ProxyTopologySummary:
        counts = {"derived": 0, "off_estate": 0, "join_unavailable": 0}
        for outcome in self.outcomes:
            counts[outcome.state] += 1
        return ProxyTopologySummary.model_validate(counts)


class S004TopologyDerivation(BaseModel):
    """W4 attribution plus W5 configuration topology through the real owner."""

    model_config = ConfigDict(extra="forbid")

    registered_asset_ids: dict[str, str]
    attributed_listeners: list[ListenerObservation]
    surface_application: SurfaceApplication
    topology_application: ProxyTopologyApplication
    attack_surface: list[AttackSurfaceAsset]


class ConfigurationKnownSurfaceSource:
    """Overlay configuration-derived rows only onto assets the owner already knows."""

    def __init__(
        self,
        upstream: KnownSurfaceSource,
        records: Sequence[KnownSurfaceRecord],
    ) -> None:
        self.upstream = upstream
        selected = [
            KnownSurfaceRecord.model_validate(record.model_dump(mode="python"))
            for record in records
        ]
        refs = [record.asset_ref.ref_id for record in selected]
        if len(refs) != len(set(refs)):
            raise S004RouteError("configuration surface rows must be unique by asset")
        self._records = {record.asset_ref.ref_id: record for record in selected}

    async def list_known_surface(
        self,
        *,
        tenant_id: str | None,
    ) -> Sequence[KnownSurfaceRecord]:
        rows = await self.upstream.list_known_surface(tenant_id=tenant_id)
        by_ref = {row.asset_ref.ref_id: row for row in rows}
        if any(ref not in by_ref for ref in self._records):
            raise S004RouteError("configuration surface is not bound to current inventory")
        by_ref.update(self._records)
        return [by_ref[ref] for ref in sorted(by_ref)]


def build_privileged_surface_application(
    captures: HandedInCaptureSet,
    *,
    registered_asset_ids: Mapping[str, str],
    unregistered_assets: Sequence[EstateAsset] = (),
) -> tuple[list[ListenerObservation], SurfaceApplication]:
    """Attribute W1 listeners and retain U3's complete surface state machine."""

    selected = _validated_capture_set(captures)
    attributed = attribute_listener_observations(
        selected.privileged_sockets.listeners,
        selected.inventory,
    )
    application = build_surface_application_from_observations(
        attributed,
        selected.inventory,
        registered_asset_ids=registered_asset_ids,
        evidence_root=selected.privileged_sockets.capture.capture_id,
        observed_at=selected.privileged_sockets.capture.captured_at,
        unregistered_assets=unregistered_assets,
    )
    return attributed, application


def build_proxy_topology_application(
    captures: HandedInCaptureSet,
    *,
    attributed_listeners: Sequence[ListenerObservation],
    registered_asset_ids: Mapping[str, str],
) -> ProxyTopologyApplication:
    """Join only configuration routes supported by fresh host observations."""

    selected = _validated_capture_set(captures)
    outcomes: list[ProxyTopologyOutcome] = []
    records_by_asset: dict[str, list[ProxyTopologyOutcome]] = {}
    for route in selected.proxy_configuration.routes:
        outcome = _topology_outcome(
            route,
            attributed_listeners=attributed_listeners,
            registered_asset_ids=registered_asset_ids,
            configuration_capture_id=selected.proxy_configuration.capture.capture_id,
        )
        outcomes.append(outcome)
        if outcome.state == "derived" and outcome.upstream_asset_id is not None:
            records_by_asset.setdefault(outcome.upstream_asset_id, []).append(outcome)

    records = [
        _configuration_surface_record(
            asset_id,
            route_outcomes,
            configuration_captured_at=selected.proxy_configuration.capture.captured_at,
            socket_capture_id=selected.privileged_sockets.capture.capture_id,
            socket_captured_at=selected.privileged_sockets.capture.captured_at,
        )
        for asset_id, route_outcomes in sorted(records_by_asset.items())
    ]
    return ProxyTopologyApplication(outcomes=outcomes, surface_records=records)


def topology_factor_readings(
    application: ProxyTopologyApplication,
) -> list[FactorReading]:
    """Reduce W5 topology to countable facts without route or asset identifiers."""

    readings: list[FactorReading] = []
    for outcome in application.outcomes:
        if outcome.state == "derived":
            if outcome.reachability == "unknown":
                readings.append(
                    FactorReading(
                        name="exposure",
                        status="unknown",
                        reason=outcome.reason,
                        source="s004:configuration:route",
                        unknown_cause="source_cannot_assert",
                    )
                )
                continue
            readings.append(
                FactorReading(
                    name="exposure",
                    status="known",
                    reason=CONFIGURATION_ROUTE_DERIVED,
                    source="s004:configuration:route",
                    unknown_cause=None,
                )
            )
            continue
        cause = "source_cannot_assert" if outcome.state == "off_estate" else "input_missing"
        readings.append(
            FactorReading(
                name="exposure",
                status="unknown",
                reason=outcome.reason,
                source=f"s004:configuration:{outcome.state}",
                unknown_cause=cast(FactorUnknownCause, cause),
            )
        )
    return readings


async def derive_s004_surface(
    captures: HandedInCaptureSet,
    *,
    inventory_owner: InventorySurfaceOwner,
    exposure_store: ExposureStore,
    source: DiscoverySource,
    tenant_id: str | None,
    asset_ids_by_key: Mapping[str, str] | None = None,
    unregistered_assets: Sequence[EstateAsset] = (),
    exposure_config: ExposureConfig | None = None,
) -> S004SurfaceDerivation:
    """Drive W4 through the real EA-0025 to EA-0023 owner chain."""

    selected = _validated_capture_set(captures)
    registered = await register_service_assets(
        selected.inventory,
        owner=inventory_owner,
        source=source,
        tenant_id=tenant_id,
        asset_ids_by_key=asset_ids_by_key,
    )
    attributed, application = build_privileged_surface_application(
        selected,
        registered_asset_ids=registered,
        unregistered_assets=unregistered_assets,
    )
    known_surface = InventoryKnownSurfaceSource(
        inventory_owner,
        observed_surface=application.observed_surface,
    )
    exposure = KnownDataExposureEngine(
        exposure_store,
        known_surface,
        config=exposure_config,
    )
    derived = await exposure.derive_surface(tenant_id=tenant_id)
    return S004SurfaceDerivation(
        registered_asset_ids=registered,
        attributed_listeners=attributed,
        application=application,
        attack_surface=derived,
    )


async def derive_s004_topology(
    captures: HandedInCaptureSet,
    *,
    inventory_owner: InventorySurfaceOwner,
    exposure_store: ExposureStore,
    source: DiscoverySource,
    tenant_id: str | None,
    asset_ids_by_key: Mapping[str, str] | None = None,
    unregistered_assets: Sequence[EstateAsset] = (),
    exposure_config: ExposureConfig | None = None,
) -> S004TopologyDerivation:
    """Drive W4 and W5 through the real EA-0025 to EA-0023 owner chain."""

    selected = _validated_capture_set(captures)
    registered = await register_service_assets(
        selected.inventory,
        owner=inventory_owner,
        source=source,
        tenant_id=tenant_id,
        asset_ids_by_key=asset_ids_by_key,
    )
    attributed, surface_application = build_privileged_surface_application(
        selected,
        registered_asset_ids=registered,
        unregistered_assets=unregistered_assets,
    )
    topology_application = build_proxy_topology_application(
        selected,
        attributed_listeners=attributed,
        registered_asset_ids=registered,
    )
    inventory_surface = InventoryKnownSurfaceSource(
        inventory_owner,
        observed_surface=surface_application.observed_surface,
    )
    known_surface = ConfigurationKnownSurfaceSource(
        inventory_surface,
        topology_application.surface_records,
    )
    exposure = KnownDataExposureEngine(
        exposure_store,
        known_surface,
        config=exposure_config,
    )
    derived = await exposure.derive_surface(tenant_id=tenant_id)
    return S004TopologyDerivation(
        registered_asset_ids=registered,
        attributed_listeners=attributed,
        surface_application=surface_application,
        topology_application=topology_application,
        attack_surface=derived,
    )


def _validated_capture_set(captures: HandedInCaptureSet) -> HandedInCaptureSet:
    return HandedInCaptureSet.model_validate(captures.model_dump(mode="python"))


@dataclass(frozen=True)
class _Endpoint:
    address: str | None
    port: int


def _topology_outcome(
    route: ProxyRouteDeclaration,
    *,
    attributed_listeners: Sequence[ListenerObservation],
    registered_asset_ids: Mapping[str, str],
    configuration_capture_id: str,
) -> ProxyTopologyOutcome:
    configuration_ref = _configuration_route_ref(configuration_capture_id, route)
    frontend = _frontend_endpoint(route.frontend_ref)
    upstream = _upstream_endpoint(route.upstream_ref)
    frontend_rows = _matching_listeners(frontend, attributed_listeners)
    frontend_keys = _attributed_keys(frontend_rows)
    frontend_asset_id = _unique_registered_asset(frontend_keys, registered_asset_ids)
    if frontend is None or frontend_asset_id is None:
        return ProxyTopologyOutcome(
            state="join_unavailable",
            frontend_ref=route.frontend_ref,
            upstream_ref=route.upstream_ref,
            frontend_asset_id=frontend_asset_id,
            unknown_cause="input_missing",
            reason=TOPOLOGY_JOIN_UNAVAILABLE,
            configuration_ref=configuration_ref,
            certificate_refs=route.certificate_refs,
        )

    upstream_rows = _matching_listeners(upstream, attributed_listeners)
    upstream_keys = _attributed_keys(upstream_rows)
    upstream_asset_id = _unique_registered_asset(upstream_keys, registered_asset_ids)
    if upstream_asset_id is None:
        state: TopologyState = (
            "off_estate"
            if _is_explicitly_off_estate(upstream, upstream_rows)
            else "join_unavailable"
        )
        cause: FactorUnknownCause = (
            "source_cannot_assert" if state == "off_estate" else "input_missing"
        )
        return ProxyTopologyOutcome(
            state=state,
            frontend_ref=route.frontend_ref,
            upstream_ref=route.upstream_ref,
            frontend_asset_id=frontend_asset_id,
            unknown_cause=cause,
            reason=(UPSTREAM_OFF_ESTATE if state == "off_estate" else TOPOLOGY_JOIN_UNAVAILABLE),
            configuration_ref=configuration_ref,
            certificate_refs=route.certificate_refs,
        )

    reachability = _frontend_reachability(frontend_rows)
    return ProxyTopologyOutcome(
        state="derived",
        frontend_ref=route.frontend_ref,
        upstream_ref=route.upstream_ref,
        frontend_asset_id=frontend_asset_id,
        upstream_asset_id=upstream_asset_id,
        reachability=reachability,
        unknown_cause=("source_cannot_assert" if reachability == "unknown" else None),
        reason=CONFIGURATION_ROUTE_DERIVED,
        configuration_ref=configuration_ref,
        certificate_refs=route.certificate_refs,
    )


def _configuration_surface_record(
    asset_id: str,
    outcomes: Sequence[ProxyTopologyOutcome],
    *,
    configuration_captured_at: datetime,
    socket_capture_id: str,
    socket_captured_at: datetime,
) -> KnownSurfaceRecord:
    reachability = _strongest_reachability([outcome.reachability for outcome in outcomes])
    configuration_refs = sorted({outcome.configuration_ref for outcome in outcomes})
    return KnownSurfaceRecord(
        asset_ref=AssetRef(kind="asset", ref_id=asset_id),
        classification="configuration_declared_service",
        exposure_type="proxy_route",
        reachability=reachability,
        basis=[
            *[
                ExposureBasis(
                    kind="configuration",
                    ref=ref,
                    as_of=configuration_captured_at,
                )
                for ref in configuration_refs
            ],
            ExposureBasis(
                kind="host_state",
                ref=f"{socket_capture_id}:attributed-listeners",
                as_of=socket_captured_at,
            ),
        ],
        observed_at=max(configuration_captured_at, socket_captured_at),
        rationale=CONFIGURATION_ROUTE_DERIVED,
    )


def _configuration_route_ref(
    capture_id: str,
    route: ProxyRouteDeclaration,
) -> str:
    payload = "\0".join((route.frontend_ref, route.upstream_ref, *route.server_names))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"{capture_id}:route:sha256:{digest}"


def _frontend_endpoint(value: str) -> _Endpoint | None:
    selected = value.strip()
    if selected.isdigit():
        return _Endpoint(address=None, port=int(selected))
    return _host_port(selected)


def _upstream_endpoint(value: str) -> _Endpoint | None:
    selected = value.strip()
    if "://" not in selected:
        return _host_port(selected)
    try:
        parsed = urlsplit(selected)
        if parsed.hostname is None:
            return None
        default_port = 443 if parsed.scheme.casefold() == "https" else 80
        return _Endpoint(address=parsed.hostname, port=parsed.port or default_port)
    except ValueError:
        return None


def _host_port(value: str) -> _Endpoint | None:
    selected = value.strip()
    if selected.startswith("[") and "]:" in selected:
        address, _, port = selected[1:].partition("]:")
    elif ":" in selected:
        address, port = selected.rsplit(":", maxsplit=1)
    else:
        return None
    if not port.isdigit() or not 0 < int(port) < 65_536:
        return None
    return _Endpoint(address=(None if address in ("", "*") else address), port=int(port))


def _matching_listeners(
    endpoint: _Endpoint | None,
    observations: Sequence[ListenerObservation],
) -> list[ListenerObservation]:
    if endpoint is None:
        return []
    return [
        observation
        for observation in observations
        if observation.port == endpoint.port
        and (
            endpoint.address is None
            or _same_host_address(endpoint.address, observation.address)
            or _wildcard_address(observation.address)
        )
    ]


def _same_host_address(left: str, right: str) -> bool:
    if left.casefold() == "localhost":
        try:
            return ipaddress.ip_address(right.partition("%")[0]).is_loopback
        except ValueError:
            return False
    try:
        return ipaddress.ip_address(left.partition("%")[0]) == ipaddress.ip_address(
            right.partition("%")[0]
        )
    except ValueError:
        return left.casefold() == right.casefold()


def _wildcard_address(value: str) -> bool:
    if value == "*":
        return True
    try:
        return ipaddress.ip_address(value.partition("%")[0]).is_unspecified
    except ValueError:
        return False


def _attributed_keys(observations: Sequence[ListenerObservation]) -> set[str]:
    return {
        observation.asset_key for observation in observations if observation.asset_key is not None
    }


def _unique_registered_asset(
    asset_keys: set[str],
    registered_asset_ids: Mapping[str, str],
) -> str | None:
    if len(asset_keys) != 1:
        return None
    asset_key = next(iter(asset_keys))
    return registered_asset_ids.get(asset_key)


def _is_explicitly_off_estate(
    endpoint: _Endpoint | None,
    matches: Sequence[ListenerObservation],
) -> bool:
    if endpoint is None or matches:
        return False
    address = endpoint.address
    if address is None or address.casefold() == "localhost":
        return False
    try:
        parsed = ipaddress.ip_address(address.partition("%")[0])
    except ValueError:
        return False
    return not (parsed.is_loopback or parsed.is_unspecified)


def _frontend_reachability(
    observations: Sequence[ListenerObservation],
) -> Reachability:
    values = {classify_bind(observation.address) for observation in observations}
    if "external" in values:
        return "external"
    if values == {"internal"}:
        return "internal"
    return "unknown"


def _strongest_reachability(
    values: Sequence[Reachability | None],
) -> Reachability:
    selected = set(values)
    if "external" in selected:
        return "external"
    if "internal" in selected:
        return "internal"
    return "unknown"
