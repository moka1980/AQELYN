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
    ASSET_OBJECT_TYPE,
    AssetConfigAnalyzer,
    assess_asset,
    classify_asset,
    explain,
)
from aqelyn.assetconfig.models import (
    ACGConfig,
    AssetDrift,
    Baseline,
    Check,
    DriftItem,
    DriftSnapshot,
    DriftStatus,
    FrameworkRef,
)

__all__ = [
    "ASSET_OBJECT_TYPE",
    "MAX_REGEX_GROUPS",
    "MAX_REGEX_PATTERN_LENGTH",
    "MISSING",
    "VALID_COMPARATORS",
    "ACGConfig",
    "AssetConfigAnalyzer",
    "AssetDrift",
    "Baseline",
    "Check",
    "Comparator",
    "DriftItem",
    "DriftSnapshot",
    "DriftStatus",
    "FrameworkRef",
    "assess_asset",
    "classify_asset",
    "compare",
    "explain",
    "validate_comparator",
    "validate_regex_pattern",
]
