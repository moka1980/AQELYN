"""S-004 W7 convergence over fresh captures and existing owner engines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from tools.first_run import RunReport, coverage_factor_readings, measure_kev_join
from tools.s003_baseline import (
    BaselineAssessment,
    BaselineDefinition,
    baseline_factor_readings,
)
from tools.s003_declaration import (
    MissionDeclarationApplication,
    mission_factor_readings,
)
from tools.s003_estate import EstateAsset
from tools.s003_surface import (
    InventorySurfaceOwner,
    surface_factor_readings,
)
from tools.s004_baseline import (
    CertificateLifecycleOwner,
    CertificatePathBinding,
    assess_s004_baseline,
)
from tools.s004_handin import HandedInCaptureSet
from tools.s004_route import (
    S004TopologyDerivation,
    derive_s004_topology,
    topology_factor_readings,
)

from aqelyn.exposure import ExposureConfig, ExposureStore
from aqelyn.inventory import DiscoverySource
from aqelyn.objects import ObjectStore
from aqelyn.vuln import CoverageReport


async def assemble_s004_report(
    base_report: RunReport,
    *,
    catalog: Any,
    vulnerability_document: dict[str, Any],
    coverage: CoverageReport,
    captures: HandedInCaptureSet,
    mission_application: MissionDeclarationApplication,
    baseline_definition: BaselineDefinition,
    object_store: ObjectStore,
    inventory_owner: InventorySurfaceOwner,
    exposure_store: ExposureStore,
    discovery_source: DiscoverySource,
    tenant_id: str | None,
    observed_at: datetime,
    source_id: str,
    asset_ids_by_key: Mapping[str, str] | None = None,
    unregistered_assets: Sequence[EstateAsset] = (),
    exposure_config: ExposureConfig | None = None,
    certificate_owner: CertificateLifecycleOwner | None = None,
    certificate_bindings: Sequence[CertificatePathBinding] = (),
) -> tuple[RunReport, BaselineAssessment, S004TopologyDerivation]:
    """Run W4-W6 and emit only counts, reasons, and shared owner decisions."""

    derivation = await derive_s004_topology(
        captures,
        inventory_owner=inventory_owner,
        exposure_store=exposure_store,
        source=discovery_source,
        tenant_id=tenant_id,
        asset_ids_by_key=asset_ids_by_key,
        unregistered_assets=unregistered_assets,
        exposure_config=exposure_config,
    )
    baseline = await assess_s004_baseline(
        object_store,
        captures,
        definition=baseline_definition,
        tenant_id=tenant_id,
        observed_at=observed_at,
        source_id=source_id,
        certificate_owner=certificate_owner,
        certificate_bindings=certificate_bindings,
    )
    factor_readings = [
        *coverage_factor_readings(coverage),
        *surface_factor_readings(derivation.surface_application.aggregate()),
        *topology_factor_readings(derivation.topology_application),
        *baseline_factor_readings(baseline),
        *mission_factor_readings(mission_application),
    ]
    return (
        replace(
            base_report,
            coverage_factors=factor_readings,
            roadmap_dependencies=list(baseline.roadmap_dependencies),
            kev_join=measure_kev_join(catalog, vulnerability_document),
        ),
        baseline,
        derivation,
    )
