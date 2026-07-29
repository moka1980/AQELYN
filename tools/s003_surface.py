"""S-003 observed-host surface handoff to EA-0025 and EA-0023.

The private collection documents stay outside the repository under ECR-0069.
This module parses the handed-in socket table, registers discovered units through
the real inventory owner, and builds a measured host-state overlay for
``InventoryKnownSurfaceSource``. Only count-only summaries can reach the density
report.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from tools.first_run import FactorReading, RoadmapDependency
from tools.s003_estate import (
    EstateAsset,
    ListenerObservation,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
)

from aqelyn.conventions import new_id, require_typed_id
from aqelyn.exposure import (
    AttackSurfaceAsset,
    ExposureConfig,
    ExposureStore,
    KnownDataExposureEngine,
    Reachability,
)
from aqelyn.inventory import (
    AssetRecord,
    DiscoverySource,
    InventoryKnownSurfaceSource,
    InventoryProvider,
    ObservedHostSurface,
)
from aqelyn.vuln import FactorUnknownCause

NO_SURFACE_EVIDENCE = "no surface evidence"
OBSERVED_JOIN_UNAVAILABLE = "surface observed, join key unavailable"
ASSET_NOT_REGISTERED = "surface asset not registered"
AMBIGUOUS_BIND = "observed bind does not determine external reachability"
MEASURED_REACHABILITY = "reachability derived from observed host state"

SurfaceState = Literal[
    "derived",
    "no_surface_evidence",
    "observed_unattributable",
    "not_registered",
]

_PID = re.compile(r"\bpid=(\d+)\b")
_PROCESS_NAME = re.compile(r'\("([^"]+)"')


class S003SurfaceError(RuntimeError):
    """The handed-in surface cannot be routed honestly."""


class SurfaceOutcome(BaseModel):
    """One local result; identifying fields never feed the aggregate emitter."""

    model_config = ConfigDict(extra="forbid")

    factor: Literal["exposure"] = "exposure"
    state: SurfaceState
    asset_key: str | None = None
    asset_id: str | None = None
    reachability: Reachability | None = None
    unknown_cause: FactorUnknownCause | None = None
    reason: str

    @field_validator("asset_key")
    @classmethod
    def _asset_key(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("surface outcome asset_key must not be empty")
        return value

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "ast", field="surface outcome asset_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("surface outcome reason must not be empty")
        return value

    @model_validator(mode="after")
    def _state_is_total(self) -> SurfaceOutcome:
        if self.state == "derived":
            if self.asset_key is None or self.asset_id is None:
                raise ValueError("derived surface requires a registered asset")
            expected_cause = "source_cannot_assert" if self.reachability is None else None
            if self.unknown_cause != expected_cause:
                raise ValueError("derived surface unknown cause contradicts reachability")
            return self
        if self.reachability is not None:
            raise ValueError("non-derived surface states cannot carry reachability")
        if self.unknown_cause != "input_missing":
            raise ValueError("non-derived surface states require the input_missing cause")
        if self.state == "no_surface_evidence":
            if self.asset_key is None or self.asset_id is None:
                raise ValueError("no-surface state requires a registered asset")
        elif self.state == "observed_unattributable":
            if self.asset_key is not None or self.asset_id is not None:
                raise ValueError("unattributable observation cannot claim an asset")
        elif self.state == "not_registered" and (
            self.asset_key is None or self.asset_id is not None
        ):
            raise ValueError("unregistered state requires only the local asset key")
        return self


class SurfaceSummary(BaseModel):
    """Count-only boundary safe to pass to the density reporter."""

    model_config = ConfigDict(extra="forbid")

    derived_external: int = 0
    derived_internal: int = 0
    derived_unknown: int = 0
    no_surface_evidence: int = 0
    observed_unattributable: int = 0
    not_registered: int = 0

    @field_validator("*", mode="before")
    @classmethod
    def _nonnegative(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("surface summary counts must be non-negative integers")
        return value


class SurfaceApplication(BaseModel):
    """Local detailed outcomes and inventory-bound observed surface rows."""

    model_config = ConfigDict(extra="forbid")

    outcomes: list[SurfaceOutcome]
    observed_surface: list[ObservedHostSurface]

    @model_validator(mode="after")
    def _observations_are_bound(self) -> SurfaceApplication:
        derived_ids = {
            outcome.asset_id
            for outcome in self.outcomes
            if outcome.state == "derived" and outcome.asset_id is not None
        }
        observed_ids = {observation.asset_id for observation in self.observed_surface}
        if derived_ids != observed_ids:
            raise ValueError("observed host surface rows must match derived outcomes")
        return self

    def aggregate(self) -> SurfaceSummary:
        counts = {
            "derived_external": 0,
            "derived_internal": 0,
            "derived_unknown": 0,
            "no_surface_evidence": 0,
            "observed_unattributable": 0,
            "not_registered": 0,
        }
        for outcome in self.outcomes:
            if outcome.state == "derived":
                suffix = outcome.reachability or "unknown"
                counts[f"derived_{suffix}"] += 1
            else:
                counts[outcome.state] += 1
        return SurfaceSummary.model_validate(counts)


class InventorySurfaceOwner(InventoryProvider, Protocol):
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, object]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]: ...


def parse_listener_observations(
    surface: ServiceSurfaceDocument,
    inventory: UnitInventoryDocument,
) -> list[ListenerObservation]:
    """Parse the handed-in socket table and join only on observed process ids."""

    if surface.listeners_raw is None:
        raise S003SurfaceError("listener observations are unavailable")
    pid_to_assets: dict[int, set[str]] = defaultdict(set)
    for unit in inventory.units:
        if unit.main_pid is not None:
            pid_to_assets[unit.main_pid].add(unit.asset_key)

    observations = parse_listener_rows(surface.listeners_raw)
    return [
        observation.model_copy(
            update={
                "asset_key": _listener_asset_key(
                    observation,
                    pid_to_assets=pid_to_assets,
                )
            }
        )
        for observation in observations
    ]


def parse_listener_rows(raw: str) -> list[ListenerObservation]:
    """Parse a handed-in ``ss`` table without claiming an asset join."""

    observations: list[ListenerObservation] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split(maxsplit=6)
        if len(fields) < 6:
            raise S003SurfaceError("socket table contains an incomplete listener row")
        protocol = _protocol(fields[0])
        address, port = _endpoint(fields[4])
        process_ids = sorted({int(value) for value in _PID.findall(line)})
        process_names = sorted(set(_PROCESS_NAME.findall(line)))
        observations.append(
            ListenerObservation(
                protocol=protocol,
                address=address,
                port=port,
                process_ids=process_ids,
                process_names=process_names,
            )
        )
    return observations


def _listener_asset_key(
    observation: ListenerObservation,
    *,
    pid_to_assets: Mapping[int, set[str]],
) -> str | None:
    matched_assets = {
        asset_key
        for process_id in observation.process_ids
        for asset_key in pid_to_assets.get(process_id, set())
    }
    return next(iter(matched_assets)) if len(matched_assets) == 1 else None


def classify_bind(address: str) -> Reachability | None:
    """Classify only bind states the host-local address proves."""

    selected = address.strip()
    if selected == "*":
        return "external"
    without_scope = selected.partition("%")[0]
    try:
        parsed = ipaddress.ip_address(without_scope)
    except ValueError:
        return None
    if parsed.is_unspecified:
        return "external"
    if parsed.is_loopback:
        return "internal"
    if (
        isinstance(parsed, ipaddress.IPv6Address)
        and parsed.ipv4_mapped is not None
        and parsed.ipv4_mapped.is_loopback
    ):
        return "internal"
    return None


async def register_service_assets(
    inventory: UnitInventoryDocument,
    *,
    owner: InventorySurfaceOwner,
    source: DiscoverySource,
    tenant_id: str | None,
    asset_ids_by_key: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Register every discovered unit through the real EA-0025 owner."""

    if source.health != "ok":
        raise S003SurfaceError("service registration requires an ok discovery source")
    roster = {unit.asset_key for unit in inventory.units}
    if len(roster) != len(inventory.units):
        raise S003SurfaceError("unit inventory contains duplicate asset keys")
    selected_ids = (
        {asset_key: new_id("ast") for asset_key in roster}
        if asset_ids_by_key is None
        else dict(asset_ids_by_key)
    )
    if set(selected_ids) != roster:
        raise S003SurfaceError("service asset id roster differs from unit inventory")
    validated_ids = {
        asset_key: require_typed_id(asset_id, "ast", field="service asset id")
        for asset_key, asset_id in selected_ids.items()
    }
    reports = [
        {
            "id": validated_ids[unit.asset_key],
            "asset_type": unit.kind,
            "classification": "runtime_service",
            "ref": _asset_ref(unit.asset_key),
        }
        for unit in sorted(inventory.units, key=lambda value: value.asset_key)
    ]
    stored = await owner.ingest(reports=reports, source=source, tenant_id=tenant_id)
    if {record.id for record in stored} != set(validated_ids.values()):
        raise S003SurfaceError("EA-0025 did not return the registered service roster")
    return validated_ids


def build_surface_application(
    surface: ServiceSurfaceDocument,
    inventory: UnitInventoryDocument,
    *,
    registered_asset_ids: Mapping[str, str],
    unregistered_assets: Sequence[EstateAsset] = (),
) -> SurfaceApplication:
    """Build the three honest states and the inventory-bound host-state overlay."""

    roster = {unit.asset_key for unit in inventory.units}
    if set(registered_asset_ids) != roster:
        raise S003SurfaceError("registered asset roster differs from unit inventory")
    selected_ids = {
        asset_key: require_typed_id(asset_id, "ast", field="registered service asset id")
        for asset_key, asset_id in registered_asset_ids.items()
    }
    unregistered_keys = [asset.asset_key for asset in unregistered_assets]
    if len(unregistered_keys) != len(set(unregistered_keys)):
        raise S003SurfaceError("unregistered surface assets must be unique")
    if any(asset_key in roster for asset_key in unregistered_keys):
        raise S003SurfaceError("an unregistered surface asset is already registered")

    observations = parse_listener_observations(surface, inventory)
    attributed: dict[str, list[ListenerObservation]] = defaultdict(list)
    outcomes: list[SurfaceOutcome] = []
    for observation in observations:
        if observation.asset_key is None:
            outcomes.append(
                SurfaceOutcome(
                    state="observed_unattributable",
                    unknown_cause="input_missing",
                    reason=OBSERVED_JOIN_UNAVAILABLE,
                )
            )
            continue
        attributed[observation.asset_key].append(observation)
        reachability = classify_bind(observation.address)
        outcomes.append(
            SurfaceOutcome(
                state="derived",
                asset_key=observation.asset_key,
                asset_id=selected_ids[observation.asset_key],
                reachability=reachability,
                unknown_cause=("source_cannot_assert" if reachability is None else None),
                reason=AMBIGUOUS_BIND if reachability is None else MEASURED_REACHABILITY,
            )
        )

    evidence_root = _surface_ref(surface)
    observed_surface: list[ObservedHostSurface] = []
    for asset_key, asset_id in sorted(selected_ids.items()):
        asset_observations = attributed.get(asset_key, [])
        if not asset_observations:
            outcomes.append(
                SurfaceOutcome(
                    state="no_surface_evidence",
                    asset_key=asset_key,
                    asset_id=asset_id,
                    unknown_cause="input_missing",
                    reason=NO_SURFACE_EVIDENCE,
                )
            )
            continue
        reachability = _combined_reachability(asset_observations)
        observed_surface.append(
            ObservedHostSurface(
                asset_id=asset_id,
                reachability=reachability,
                basis_refs=sorted(
                    {
                        _observation_ref(evidence_root, observation)
                        for observation in asset_observations
                    }
                ),
                observed_at=surface.collected_at,
                rationale=(AMBIGUOUS_BIND if reachability is None else MEASURED_REACHABILITY),
            )
        )

    outcomes.extend(
        SurfaceOutcome(
            state="not_registered",
            asset_key=asset_key,
            unknown_cause="input_missing",
            reason=ASSET_NOT_REGISTERED,
        )
        for asset_key in sorted(unregistered_keys)
    )
    return SurfaceApplication(
        outcomes=outcomes,
        observed_surface=observed_surface,
    )


async def derive_surface_from_documents(
    surface: ServiceSurfaceDocument,
    inventory: UnitInventoryDocument,
    *,
    inventory_owner: InventorySurfaceOwner,
    exposure_store: ExposureStore,
    source: DiscoverySource,
    tenant_id: str | None,
    asset_ids_by_key: Mapping[str, str] | None = None,
    unregistered_assets: Sequence[EstateAsset] = (),
    exposure_config: ExposureConfig | None = None,
) -> tuple[SurfaceApplication, list[AttackSurfaceAsset]]:
    """Drive the handed-in documents through the real EA-0025→EA-0023 chain."""

    registered = await register_service_assets(
        inventory,
        owner=inventory_owner,
        source=source,
        tenant_id=tenant_id,
        asset_ids_by_key=asset_ids_by_key,
    )
    application = build_surface_application(
        surface,
        inventory,
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
    if {row.asset_ref.ref_id for row in derived} != set(registered.values()):
        raise S003SurfaceError("EA-0023 did not derive the registered service roster")
    return application, derived


def surface_factor_readings(summary: SurfaceSummary) -> list[FactorReading]:
    """Translate count-only U3 state into value-free roadmap facts."""

    readings: list[FactorReading] = []
    for count, source in (
        (summary.derived_external, "s003:host_state:external"),
        (summary.derived_internal, "s003:host_state:internal"),
    ):
        readings.extend(
            FactorReading(
                name="exposure",
                status="known",
                reason=MEASURED_REACHABILITY,
                source=source,
                unknown_cause=None,
            )
            for _ in range(count)
        )
    for count, reason, cause, source in (
        (
            summary.derived_unknown,
            AMBIGUOUS_BIND,
            "source_cannot_assert",
            "s003:host_state:ambiguous",
        ),
        (
            summary.no_surface_evidence,
            NO_SURFACE_EVIDENCE,
            "input_missing",
            "s003:host_state:not-observed",
        ),
        (
            summary.observed_unattributable,
            OBSERVED_JOIN_UNAVAILABLE,
            "input_missing",
            "s003:host_state:join-unavailable",
        ),
        (
            summary.not_registered,
            ASSET_NOT_REGISTERED,
            "input_missing",
            "s003:host_state:not-registered",
        ),
    ):
        readings.extend(
            FactorReading(
                name="exposure",
                status="unknown",
                reason=reason,
                source=source,
                unknown_cause=cast(FactorUnknownCause, cause),
            )
            for _ in range(count)
        )
    return readings


def surface_roadmap_dependencies(
    surface: ServiceSurfaceDocument,
    summary: SurfaceSummary,
) -> list[RoadmapDependency]:
    """Name the U3 capabilities gated by the shared privileged-read decision."""

    dependencies: list[RoadmapDependency] = []
    if surface.nginx_config is None:
        dependencies.append(
            RoadmapDependency(
                decision="privileged_read",
                dependent="surface:proxy_topology",
            )
        )
    if summary.observed_unattributable:
        dependencies.append(
            RoadmapDependency(
                decision="privileged_read",
                dependent="surface:listener_attribution",
            )
        )
    return dependencies


def _protocol(value: str) -> Literal["tcp", "udp"]:
    selected = value.lower()
    if selected.startswith("tcp"):
        return "tcp"
    if selected.startswith("udp"):
        return "udp"
    raise S003SurfaceError("socket table contains an unsupported protocol")


def _endpoint(value: str) -> tuple[str, int]:
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            raise S003SurfaceError("socket table contains a malformed bracketed endpoint")
        address = value[1:closing]
        suffix = value[closing + 1 :]
        if suffix.startswith(":"):
            raw_port = suffix[1:]
        elif suffix.startswith("%"):
            zone, separator, raw_port = suffix[1:].rpartition(":")
            if not separator or not zone:
                raise S003SurfaceError("socket table contains a malformed scoped endpoint")
            address = f"{address}%{zone}"
        else:
            raise S003SurfaceError("socket table contains a malformed bracketed endpoint")
    else:
        address, separator, raw_port = value.rpartition(":")
        if not separator:
            raise S003SurfaceError("socket table endpoint has no port")
    if not address:
        raise S003SurfaceError("socket table endpoint has no address")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise S003SurfaceError("socket table endpoint port is not numeric") from exc
    if port < 1 or port > 65_535:
        raise S003SurfaceError("socket table endpoint port is outside [1,65535]")
    return address, port


def _combined_reachability(
    observations: Sequence[ListenerObservation],
) -> Reachability | None:
    values = [classify_bind(observation.address) for observation in observations]
    if "external" in values:
        return "external"
    if values and all(value == "internal" for value in values):
        return "internal"
    return None


def _surface_ref(surface: ServiceSurfaceDocument) -> str:
    encoded = json.dumps(
        surface.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"s003:host-state:sha256:{hashlib.sha256(encoded).hexdigest()}"


def _observation_ref(root: str, observation: ListenerObservation) -> str:
    encoded = json.dumps(
        observation.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"{root}:{hashlib.sha256(encoded).hexdigest()}"


def _asset_ref(asset_key: str) -> str:
    digest = hashlib.sha256(asset_key.encode()).hexdigest()
    return f"s003:unit:sha256:{digest}"
