"""Asset & Configuration Governance Engine (EA-0012)."""

from aqelyn.assetconfig.comparators import (
    MAX_REGEX_GROUPS,
    MAX_REGEX_PATTERN_LENGTH,
    MISSING,
    VALID_COMPARATORS,
    Comparator,
    compare,
    validate_comparator,
    validate_regex_pattern,
)
from aqelyn.assetconfig.drift import (
    ACG_REMEDIATION_ACTION,
    ASSET_OBJECT_TYPE,
    AssetConfigAnalyzer,
    DriftTrendProvider,
    MissionPrioritizer,
    WorkflowProposer,
    assess_asset,
    classify_asset,
    explain,
)
from aqelyn.assetconfig.memory import InMemoryBaselineStore, InMemoryDriftSnapshotStore
from aqelyn.assetconfig.models import (
    ACGConfig,
    AssetDrift,
    Baseline,
    Check,
    DriftItem,
    DriftSnapshot,
    DriftStatus,
    FrameworkRef,
    ObjectTypeAssessmentCoverage,
)
from aqelyn.assetconfig.postgres import PostgresBaselineStore, PostgresDriftSnapshotStore
from aqelyn.assetconfig.service import (
    ACG_EVENTS,
    AssetConfigGovernanceService,
    register_acg_events,
)
from aqelyn.assetconfig.store import (
    BaselineStore,
    DriftSnapshotStore,
    new_drift_snapshot_id,
)

__all__ = [
    "ACG_EVENTS",
    "ACG_REMEDIATION_ACTION",
    "ASSET_OBJECT_TYPE",
    "MAX_REGEX_GROUPS",
    "MAX_REGEX_PATTERN_LENGTH",
    "MISSING",
    "VALID_COMPARATORS",
    "ACGConfig",
    "AssetConfigAnalyzer",
    "AssetConfigGovernanceService",
    "AssetDrift",
    "Baseline",
    "BaselineStore",
    "Check",
    "Comparator",
    "DriftItem",
    "DriftSnapshot",
    "DriftSnapshotStore",
    "DriftStatus",
    "DriftTrendProvider",
    "FrameworkRef",
    "InMemoryBaselineStore",
    "InMemoryDriftSnapshotStore",
    "MissionPrioritizer",
    "ObjectTypeAssessmentCoverage",
    "PostgresBaselineStore",
    "PostgresDriftSnapshotStore",
    "WorkflowProposer",
    "assess_asset",
    "classify_asset",
    "compare",
    "explain",
    "new_drift_snapshot_id",
    "register_acg_events",
    "validate_comparator",
    "validate_regex_pattern",
]
