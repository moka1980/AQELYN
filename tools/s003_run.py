"""S-003 U5 convergence over the four shipped factor outputs.

Private U1 documents and per-asset owner results enter this module, but only the
existing count-only ``FactorReading`` and ``RoadmapDependency`` shapes leave it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.first_run import (
    RunReport,
    coverage_factor_readings,
    measure_kev_join,
)
from tools.s003_baseline import (
    BaselineAssessment,
    BaselineDefinition,
    assess_s003_baseline,
    baseline_factor_readings,
)
from tools.s003_declaration import (
    MissionDeclarationApplication,
    mission_factor_readings,
)
from tools.s003_estate import (
    ServiceSurfaceDocument,
    UnitInventoryDocument,
    ensure_private_workdir,
)
from tools.s003_surface import (
    SurfaceApplication,
    surface_factor_readings,
    surface_roadmap_dependencies,
)

from aqelyn.objects import ObjectStore
from aqelyn.vuln import CoverageReport


class S003RunError(RuntimeError):
    """The private run cannot be assembled into an honest count-only report."""


def load_u1_documents(
    workdir: Path,
) -> tuple[UnitInventoryDocument, ServiceSurfaceDocument]:
    """Load the two U1 documents used by U3 and U4 from a private workdir."""

    selected = ensure_private_workdir(workdir)
    try:
        inventory_raw = (selected / "unit-inventory.json").read_text(encoding="utf-8")
        surface_raw = (selected / "service-surface.json").read_text(encoding="utf-8")
    except OSError as exc:
        raise S003RunError("the required U1 documents are unavailable") from exc
    return (
        UnitInventoryDocument.model_validate_json(inventory_raw),
        ServiceSurfaceDocument.model_validate_json(surface_raw),
    )


async def assemble_s003_report(
    base_report: RunReport,
    *,
    catalog: Any,
    vulnerability_document: dict[str, Any],
    coverage: CoverageReport,
    inventory: UnitInventoryDocument,
    surface: ServiceSurfaceDocument,
    surface_application: SurfaceApplication,
    mission_application: MissionDeclarationApplication,
    baseline_definition: BaselineDefinition | None,
    object_store: ObjectStore,
    tenant_id: str | None,
    observed_at: datetime,
    source_id: str,
) -> tuple[RunReport, BaselineAssessment]:
    """Assemble U1-U4 without accepting pre-resolved baseline observations."""

    baseline = await assess_s003_baseline(
        object_store,
        definition=baseline_definition,
        inventory=inventory,
        surface=surface,
        tenant_id=tenant_id,
        observed_at=observed_at,
        source_id=source_id,
    )
    surface_summary = surface_application.aggregate()
    factor_readings = [
        *coverage_factor_readings(coverage),
        *surface_factor_readings(surface_summary),
        *baseline_factor_readings(baseline),
        *mission_factor_readings(mission_application),
    ]
    roadmap_dependencies = [
        *surface_roadmap_dependencies(surface, surface_summary),
        *baseline.roadmap_dependencies,
    ]
    return (
        replace(
            base_report,
            coverage_factors=factor_readings,
            roadmap_dependencies=roadmap_dependencies,
            kev_join=measure_kev_join(catalog, vulnerability_document),
        ),
        baseline,
    )
