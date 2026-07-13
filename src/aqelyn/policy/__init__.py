"""Policy Engine (EA-0009)."""

from aqelyn.policy.engine import PolicyEngine, more_restrictive_effect
from aqelyn.policy.interpreter import DEFAULT_MAX_DEPTH, condition_matches
from aqelyn.policy.models import (
    ComplianceResult,
    ComplianceViolation,
    Condition,
    Decision,
    DecisionEffect,
    DecisionRequest,
    DecisionResource,
    Obligation,
    Op,
    Policy,
    Rule,
    RuleEffect,
    RuleKind,
    Target,
    condition_depth,
)

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "ComplianceResult",
    "ComplianceViolation",
    "Condition",
    "Decision",
    "DecisionEffect",
    "DecisionRequest",
    "DecisionResource",
    "Obligation",
    "Op",
    "Policy",
    "PolicyEngine",
    "Rule",
    "RuleEffect",
    "RuleKind",
    "Target",
    "condition_depth",
    "condition_matches",
    "more_restrictive_effect",
]
