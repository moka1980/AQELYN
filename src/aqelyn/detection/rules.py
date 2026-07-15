"""Declarative threat detection rule matching (EA-0017 D1)."""

from __future__ import annotations

from typing import Any

from aqelyn.conventions.errors import DetectionConfigInvalid
from aqelyn.detection.models import DetectionRule
from aqelyn.policy import condition_matches


def rule_matches(
    rule: DetectionRule,
    signal: dict[str, Any],
    *,
    scope: dict[str, Any] | None = None,
) -> bool:
    data: dict[str, object] = {
        "signal": signal,
        "scope": {} if scope is None else scope,
        "subject_type": rule.subject_type,
        "rule": {
            "id": rule.id,
            "kind": rule.kind,
            "version": rule.version,
            "technique_ids": list(rule.technique_ids),
            "severity": rule.severity,
        },
    }
    try:
        return condition_matches(rule.condition, data)
    except ValueError as exc:
        raise DetectionConfigInvalid(str(exc)) from exc
