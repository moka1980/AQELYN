"""Error taxonomy (CONVENTIONS §9). Every raised error is an ``AQError``."""

from __future__ import annotations

from typing import Any


class AQError(Exception):
    """Base error. Subclasses set a stable ``code`` and ``retriable`` flag."""

    code: str = "AQError"
    retriable: bool = False

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}


# --- EA-0002 ---
class ObjectNotFound(AQError):
    code = "ObjectNotFound"


class UnknownObjectType(AQError):
    code = "UnknownObjectType"


class SchemaValidationError(AQError):
    code = "SchemaValidationError"


class MissingProvenance(AQError):
    code = "MissingProvenance"


class OptimisticConcurrencyConflict(AQError):
    code = "OptimisticConcurrencyConflict"
    retriable = True


class TenantScopeRequired(AQError):
    code = "TenantScopeRequired"


class CrossTenantReference(AQError):
    code = "CrossTenantReference"


class StoreUnavailable(AQError):
    code = "StoreUnavailable"
    retriable = True


# --- EA-0003 ---
class UnknownEventType(AQError):
    code = "UnknownEventType"


class EventSchemaValidationError(AQError):
    code = "EventSchemaValidationError"


class BusBackpressure(AQError):
    code = "BusBackpressure"
    retriable = True


class CrossTenantEvent(AQError):
    code = "CrossTenantEvent"


class SubscriptionClosed(AQError):
    code = "SubscriptionClosed"


class BusUnavailable(AQError):
    code = "BusUnavailable"
    retriable = True


# --- EA-0004 ---
class EvidenceNotFound(AQError):
    code = "EvidenceNotFound"


class EvidenceTampered(AQError):
    code = "EvidenceTampered"


class ChainBroken(AQError):
    code = "ChainBroken"


class EvidenceImmutable(AQError):
    code = "EvidenceImmutable"


# --- Finding ---
class FindingNotFound(AQError):
    code = "FindingNotFound"


class InvalidFindingTransition(AQError):
    code = "InvalidFindingTransition"


class EvidenceRequired(AQError):
    code = "EvidenceRequired"


# --- EA-0005 ---
class GraphQueryInvalid(AQError):
    code = "GraphQueryInvalid"


# --- EA-0006 ---
class TrustConfigInvalid(AQError):
    code = "TrustConfigInvalid"


# --- EA-0007 ---
class MissionConfigInvalid(AQError):
    code = "MissionConfigInvalid"


# --- EA-0008 ---
class UnknownAction(AQError):
    code = "UnknownAction"


class UnauthorizedAction(AQError):
    code = "UnauthorizedAction"


class ApprovalRequired(AQError):
    code = "ApprovalRequired"


class ConfirmationRequired(AQError):
    code = "ConfirmationRequired"


class ActionFailed(AQError):
    code = "ActionFailed"


class RunNotFound(AQError):
    code = "RunNotFound"


# --- EA-0009 ---
class PolicyConfigInvalid(AQError):
    code = "PolicyConfigInvalid"


class PolicyNotFound(AQError):
    code = "PolicyNotFound"


# --- EA-0010 ---
class GovernanceConfigInvalid(AQError):
    code = "GovernanceConfigInvalid"


class SnapshotNotFound(AQError):
    code = "SnapshotNotFound"


# --- EA-0011 ---
class IAGConfigInvalid(AQError):
    code = "IAGConfigInvalid"


class CertificationNotFound(AQError):
    code = "CertificationNotFound"


class ReviewItemNotFound(AQError):
    code = "ReviewItemNotFound"


# --- EA-0012 ---
class BaselineConfigInvalid(AQError):
    code = "BaselineConfigInvalid"


class BaselineNotFound(AQError):
    code = "BaselineNotFound"


class DriftSnapshotNotFound(AQError):
    code = "DriftSnapshotNotFound"


# --- EA-0013 ---
class RiskConfigInvalid(AQError):
    code = "RiskConfigInvalid"


class RiskNotFound(AQError):
    code = "RiskNotFound"


class RiskSnapshotNotFound(AQError):
    code = "RiskSnapshotNotFound"


# --- EA-0014 ---
class ThreatConfigInvalid(AQError):
    code = "ThreatConfigInvalid"


class ThreatSourceNotFound(AQError):
    code = "ThreatSourceNotFound"


class MalformedFeedRecord(AQError):
    code = "MalformedFeedRecord"


# --- EA-0015 ---
class SOCConfigInvalid(AQError):
    code = "SOCConfigInvalid"


class IncidentNotFound(AQError):
    code = "IncidentNotFound"


class AlertNotFound(AQError):
    code = "AlertNotFound"


# --- EA-0016 ---
class ForensicsConfigInvalid(AQError):
    code = "ForensicsConfigInvalid"


class ArtifactIntegrityError(AQError):
    code = "ArtifactIntegrityError"


class ArtifactNotFound(AQError):
    code = "ArtifactNotFound"


# --- EA-0017 ---
class DetectionConfigInvalid(AQError):
    code = "DetectionConfigInvalid"


class DetectionRuleNotFound(AQError):
    code = "DetectionRuleNotFound"


class ProfileNotFound(AQError):
    code = "ProfileNotFound"


# --- EA-0018 ---
class ResponseConfigInvalid(AQError):
    code = "ResponseConfigInvalid"


class CampaignNotFound(AQError):
    code = "CampaignNotFound"


class TriggerNotFound(AQError):
    code = "TriggerNotFound"


class PhaseBlocked(AQError):
    code = "PhaseBlocked"


# --- EA-0019 ---
class LakeConfigInvalid(AQError):
    code = "LakeConfigInvalid"


class DatasetNotFound(AQError):
    code = "DatasetNotFound"


class RecordNotFound(AQError):
    code = "RecordNotFound"


class ArchiveIntegrityError(AQError):
    code = "ArchiveIntegrityError"


class RetentionBlocked(AQError):
    code = "RetentionBlocked"


# --- EA-0020 ---
class DecisionConfigInvalid(AQError):
    code = "DecisionConfigInvalid"


class DerivationNotReplayable(AQError):
    code = "DerivationNotReplayable"


class UnknownOperation(AQError):
    code = "UnknownOperation"


class RecommendationNotFound(AQError):
    code = "RecommendationNotFound"


class ModelVersionNotFound(AQError):
    code = "ModelVersionNotFound"


# --- EA-0021 ---
class ForecastConfigInvalid(AQError):
    code = "ForecastConfigInvalid"


class UnknownMethod(AQError):
    code = "UnknownMethod"


class InsufficientHistory(AQError):
    code = "InsufficientHistory"


class ForecastNotFound(AQError):
    code = "ForecastNotFound"


class ForecastNotReplayable(AQError):
    code = "ForecastNotReplayable"


# --- EA-0022 ---
class ExecutiveConfigInvalid(AQError):
    code = "ExecutiveConfigInvalid"


class FigureProvenanceMissing(AQError):
    code = "FigureProvenanceMissing"


class FrozenReportMutation(AQError):
    code = "FrozenReportMutation"


class ExceptionsUnavailable(AQError):
    code = "ExceptionsUnavailable"


class KPIDefinitionNotFound(AQError):
    code = "KPIDefinitionNotFound"


class ReportNotFound(AQError):
    code = "ReportNotFound"


# --- EA-0023 ---
class ExposureConfigInvalid(AQError):
    code = "ExposureConfigInvalid"


class ExposureBasisMissing(AQError):
    code = "ExposureBasisMissing"


class ExposureNotFound(AQError):
    code = "ExposureNotFound"


class ExposureNotReplayable(AQError):
    code = "ExposureNotReplayable"


class ScanNotPermitted(AQError):
    code = "ScanNotPermitted"


# --- EA-0024 ---
class VulnConfigInvalid(AQError):
    code = "VulnConfigInvalid"


class VulnBasisMissing(AQError):
    code = "VulnBasisMissing"


class CoverageUnavailable(AQError):
    code = "CoverageUnavailable"


class VulnNotFound(AQError):
    code = "VulnNotFound"


class VulnNotReplayable(AQError):
    code = "VulnNotReplayable"


# --- EA-0001 ---
class ServiceStartFailed(AQError):
    code = "ServiceStartFailed"


class DependencyUnavailable(AQError):
    code = "DependencyUnavailable"
    retriable = True


class ConfigError(AQError):
    code = "ConfigError"


def _all_error_classes() -> list[type[AQError]]:
    seen: set[type[AQError]] = set()
    stack: list[type[AQError]] = [AQError]
    out: list[type[AQError]] = []
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                out.append(sub)
                stack.append(sub)
    return out


ALL_ERROR_CODES: frozenset[str] = frozenset(c.code for c in _all_error_classes())
