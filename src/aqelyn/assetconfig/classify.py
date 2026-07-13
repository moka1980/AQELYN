"""Declarative asset classification for Asset & Configuration Governance (A2)."""

from __future__ import annotations

from typing import Any

from aqelyn.conventions.errors import BaselineConfigInvalid
from aqelyn.objects import AQObject
from aqelyn.policy import Condition, condition_matches

UNCLASSIFIED = "unclassified"


def classify(asset: AQObject, rules: list[dict[str, Any]]) -> str:
    for rule in rules:
        asset_class = _asset_class(rule)
        condition = _condition(rule)
        if condition_matches(condition, _classification_data(asset)):
            return asset_class
    return UNCLASSIFIED


def _asset_class(rule: dict[str, Any]) -> str:
    raw = rule.get("asset_class", rule.get("class"))
    if not isinstance(raw, str) or not raw.strip():
        raise BaselineConfigInvalid("classification rule requires asset_class")
    return raw


def _condition(rule: dict[str, Any]) -> Condition:
    raw = rule.get("condition", rule.get("match"))
    if raw is None:
        raw = {
            key: value
            for key, value in rule.items()
            if key not in ("asset_class", "class", "description")
        }
    if not isinstance(raw, dict):
        raise BaselineConfigInvalid("classification rule condition must be an object")
    try:
        return Condition.model_validate(raw)
    except Exception as exc:
        raise BaselineConfigInvalid(f"invalid classification rule: {exc}") from exc


def _classification_data(asset: AQObject) -> dict[str, object]:
    return {
        "id": asset.id,
        "object_type": asset.object_type,
        "display_name": asset.display_name,
        "tenant_id": asset.tenant_id,
        "attributes": asset.attributes,
        "labels": asset.labels,
    }
