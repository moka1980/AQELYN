"""SaaS Security Posture Management public API (EA-0029)."""

from aqelyn.sspm.baselines import AssetConfigSaaSBaselineRouter
from aqelyn.sspm.engine import SaaSPostureEngine
from aqelyn.sspm.integration import IntegrationGraph, IntegrationTrustProvider
from aqelyn.sspm.memory import InMemorySaaSNormalizationStore
from aqelyn.sspm.models import (
    MAX_INTEGRATION_NODES,
    RESERVED_VERDICT_KEYS,
    VALID_GRANTOR_KINDS,
    VALID_OVER_SCOPED_STATUSES,
    VALID_ROUTE_OWNERS,
    BlastRadius,
    GrantorKind,
    IntegrationDescriptor,
    NormalizedSaaSObject,
    OverScopedStatus,
    ReachStatus,
    SaaSAppDescriptor,
    SaaSConfig,
    SaaSIntegration,
    SaaSRouteOwner,
    SaaSRoutingResult,
)
from aqelyn.sspm.normalize import SAAS_INTEGRATION_OBJECT_TYPE, SAAS_UNKNOWN_OBJECT_TYPE
from aqelyn.sspm.postgres import PostgresSaaSNormalizationStore
from aqelyn.sspm.route import (
    InventorySaaSOwnerRouter,
    SaaSAbsenceRouter,
    SaaSBaselineRouter,
    SaaSOwnerRouter,
    SharedObjectSaaSOwnerRouter,
    saas_asset_id,
)
from aqelyn.sspm.store import SaaSNormalizationStore
from aqelyn.sspm.surface import SaaSIntegrationKnownSurfaceSource

__all__ = [
    "MAX_INTEGRATION_NODES",
    "RESERVED_VERDICT_KEYS",
    "SAAS_INTEGRATION_OBJECT_TYPE",
    "SAAS_UNKNOWN_OBJECT_TYPE",
    "VALID_GRANTOR_KINDS",
    "VALID_OVER_SCOPED_STATUSES",
    "VALID_ROUTE_OWNERS",
    "AssetConfigSaaSBaselineRouter",
    "BlastRadius",
    "GrantorKind",
    "InMemorySaaSNormalizationStore",
    "IntegrationDescriptor",
    "IntegrationGraph",
    "IntegrationTrustProvider",
    "InventorySaaSOwnerRouter",
    "NormalizedSaaSObject",
    "OverScopedStatus",
    "PostgresSaaSNormalizationStore",
    "ReachStatus",
    "SaaSAbsenceRouter",
    "SaaSAppDescriptor",
    "SaaSBaselineRouter",
    "SaaSConfig",
    "SaaSIntegration",
    "SaaSIntegrationKnownSurfaceSource",
    "SaaSNormalizationStore",
    "SaaSOwnerRouter",
    "SaaSPostureEngine",
    "SaaSRouteOwner",
    "SaaSRoutingResult",
    "SharedObjectSaaSOwnerRouter",
    "saas_asset_id",
]
