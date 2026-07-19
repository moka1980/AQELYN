"""SaaS Security Posture Management public API (EA-0029)."""

from aqelyn.sspm.engine import SaaSPostureEngine
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
from aqelyn.sspm.normalize import SAAS_UNKNOWN_OBJECT_TYPE
from aqelyn.sspm.postgres import PostgresSaaSNormalizationStore
from aqelyn.sspm.route import SaaSOwnerRouter
from aqelyn.sspm.store import SaaSNormalizationStore

__all__ = [
    "MAX_INTEGRATION_NODES",
    "RESERVED_VERDICT_KEYS",
    "SAAS_UNKNOWN_OBJECT_TYPE",
    "VALID_GRANTOR_KINDS",
    "VALID_OVER_SCOPED_STATUSES",
    "VALID_ROUTE_OWNERS",
    "BlastRadius",
    "GrantorKind",
    "InMemorySaaSNormalizationStore",
    "IntegrationDescriptor",
    "NormalizedSaaSObject",
    "OverScopedStatus",
    "PostgresSaaSNormalizationStore",
    "ReachStatus",
    "SaaSAppDescriptor",
    "SaaSConfig",
    "SaaSIntegration",
    "SaaSNormalizationStore",
    "SaaSOwnerRouter",
    "SaaSPostureEngine",
    "SaaSRouteOwner",
    "SaaSRoutingResult",
]
