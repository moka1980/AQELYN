"""Cloud Security Posture Management normalization layer (EA-0028)."""

from aqelyn.cspm.engine import CloudPostureEngine
from aqelyn.cspm.memory import InMemoryCloudNormalizationStore
from aqelyn.cspm.models import (
    RESERVED_VERDICT_KEYS,
    ROUTE_OWNERS,
    CloudChangeKind,
    CloudNormalizationConfig,
    CloudResourceDescriptor,
    CloudRouteEnvelope,
    CloudRoutingResult,
    CloudRoutingStatus,
    NormalizedCloudObject,
    OwnerRouteOutcome,
    OwnerRouteStatus,
    Provider,
    RouteOwner,
    UnreportedCloudFact,
)
from aqelyn.cspm.normalize import CLOUD_UNKNOWN_OBJECT_TYPE
from aqelyn.cspm.postgres import PostgresCloudNormalizationStore
from aqelyn.cspm.route import (
    CloudBaselineRouter,
    CloudOwnerRouter,
    InventoryCloudOwnerRouter,
    cloud_asset_id,
)
from aqelyn.cspm.store import CloudNormalizationStore

__all__ = [
    "CLOUD_UNKNOWN_OBJECT_TYPE",
    "RESERVED_VERDICT_KEYS",
    "ROUTE_OWNERS",
    "CloudBaselineRouter",
    "CloudChangeKind",
    "CloudNormalizationConfig",
    "CloudNormalizationStore",
    "CloudOwnerRouter",
    "CloudPostureEngine",
    "CloudResourceDescriptor",
    "CloudRouteEnvelope",
    "CloudRoutingResult",
    "CloudRoutingStatus",
    "InMemoryCloudNormalizationStore",
    "InventoryCloudOwnerRouter",
    "NormalizedCloudObject",
    "OwnerRouteOutcome",
    "OwnerRouteStatus",
    "PostgresCloudNormalizationStore",
    "Provider",
    "RouteOwner",
    "UnreportedCloudFact",
    "cloud_asset_id",
]
