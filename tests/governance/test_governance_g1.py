"""G1 acceptance tests for Compliance & Governance Engine models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import PREFIXES, new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, GovernanceConfigInvalid
from aqelyn.governance import (
    ComplianceSnapshot,
    ControlResult,
    FrameworkCoverage,
    GovernanceConfig,
)


def _valid_config_payload() -> dict[str, Any]:
    return {
        "controls": [
            {
                "id": "control-access-review",
                "name": "Access review",
                "description": "Quarterly access reviews are complete.",
                "policy_ids": ["policy-access-review"],
                "framework_refs": [{"framework": "ISO27001", "requirement": "A.9.2"}],
                "severity": "high",
            }
        ],
        "frameworks": {"ISO27001": ["A.9.2", "A.12.6"]},
        "batch_size": 50,
        "min_confidence": 0.2,
    }


def _valid_config() -> GovernanceConfig:
    return GovernanceConfig.model_validate(
        _valid_config_payload(), context={"known_policy_ids": {"policy-access-review"}}
    )


def test_gov_config_invalid() -> None:
    config = _valid_config()
    assert config.controls[0].id == "control-access-review"
    assert "GovernanceConfigInvalid" in ALL_ERROR_CODES
    assert "SnapshotNotFound" in ALL_ERROR_CODES
    assert PREFIXES["snap"] == "compliance_snapshot"

    unknown_policy = _valid_config_payload()
    with pytest.raises(GovernanceConfigInvalid, match="unknown policy"):
        GovernanceConfig.model_validate(
            unknown_policy,
            context={"known_policy_ids": {"policy-endpoint-hardening"}},
        )

    unknown_framework = _valid_config_payload()
    unknown_framework["frameworks"] = {}
    with pytest.raises(GovernanceConfigInvalid, match="unknown framework"):
        GovernanceConfig.model_validate(
            unknown_framework,
            context={"known_policy_ids": {"policy-access-review"}},
        )

    unknown_requirement = _valid_config_payload()
    unknown_requirement["frameworks"] = {"ISO27001": ["A.12.6"]}
    with pytest.raises(GovernanceConfigInvalid, match="unknown requirement"):
        GovernanceConfig.model_validate(
            unknown_requirement,
            context={"known_policy_ids": {"policy-access-review"}},
        )

    duplicate_controls = _valid_config_payload()
    duplicate_controls["controls"] = [
        *_valid_config_payload()["controls"],
        *_valid_config_payload()["controls"],
    ]
    with pytest.raises(GovernanceConfigInvalid, match="unique"):
        GovernanceConfig.model_validate(
            duplicate_controls,
            context={"known_policy_ids": {"policy-access-review"}},
        )

    batch_size_zero = _valid_config_payload()
    batch_size_zero["batch_size"] = 0
    with pytest.raises(GovernanceConfigInvalid, match="batch_size"):
        GovernanceConfig.model_validate(
            batch_size_zero,
            context={"known_policy_ids": {"policy-access-review"}},
        )

    confidence_out_of_range = _valid_config_payload()
    confidence_out_of_range["min_confidence"] = 1.01
    with pytest.raises(GovernanceConfigInvalid, match="min_confidence"):
        GovernanceConfig.model_validate(
            confidence_out_of_range,
            context={"known_policy_ids": {"policy-access-review"}},
        )

    with pytest.raises(GovernanceConfigInvalid, match="passed \\+ failed"):
        ControlResult(
            control_id="control-access-review",
            evaluated=2,
            passed=2,
            failed=1,
            failing_subject_ids=[new_id("obj")],
            score=0.5,
            reason="inconsistent counts",
        )

    with pytest.raises(GovernanceConfigInvalid, match="covered"):
        FrameworkCoverage(
            framework="ISO27001",
            requirements=1,
            covered=2,
            coverage=1.0,
            score=1.0,
        )

    result = ControlResult(
        control_id="control-access-review",
        evaluated=2,
        passed=1,
        failed=1,
        failing_subject_ids=[new_id("obj")],
        score=0.5,
        reason="one subject failed",
    )
    snapshot = ComplianceSnapshot(
        id=new_id("snap"),
        tenant_id="00000000-0000-4000-8000-000000000001",
        run_at=datetime.now(UTC),
        scope={"object_type": "device"},
        overall_score=0.5,
        control_results=[result],
        framework_scores={"ISO27001": 0.5},
        evidence_id=new_id("evd"),
    )
    assert snapshot.control_results == [result]
