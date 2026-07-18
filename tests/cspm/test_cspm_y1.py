"""Y1 acceptance tests for CSPM types, config, and structural boundaries."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

import aqelyn.cspm as cspm
from aqelyn.conventions import ALL_ERROR_CODES, new_id
from aqelyn.conventions.errors import CloudConfigInvalid, SchemaValidationError
from aqelyn.cspm import (
    CloudNormalizationConfig,
    CloudResourceDescriptor,
    CloudRoutingResult,
    NormalizedCloudObject,
    OwnerRouteOutcome,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000280001"


def _config_payload() -> dict[str, Any]:
    return {
        "type_map": {
            "aws:s3:bucket": "cloud_storage",
            "azure:network:security_group": "network_security_group",
        },
        "baseline_ids": ["cis-aws-s3-v1"],
        "batch_size": 100,
    }


def _config(payload: dict[str, Any] | None = None) -> CloudNormalizationConfig:
    return CloudNormalizationConfig.model_validate(
        payload or _config_payload(),
        context={
            "known_object_types": {"cloud_storage", "network_security_group"},
            "known_baseline_ids": {"cis-aws-s3-v1"},
        },
    )


def _normalized_payload() -> dict[str, Any]:
    return {
        "object_id": new_id("obj"),
        "object_type": "cloud_storage",
        "tenant_id": TENANT,
        "provider": "aws",
        "account": "123456789012",
        "region": "eu-north-1",
        "native_facts": {
            "encryption_enabled": True,
            "network": {"public": False, "ports": [443]},
        },
        "field_provenance": {
            "encryption_enabled": "$.properties.encryption.enabled",
            "network": "$.properties.network",
        },
        "conflicts": [],
        "evidence_id": new_id("evd"),
        "flagged": False,
    }


def test_cspm_config_invalid() -> None:
    config = _config()
    assert config.batch_size == 100
    assert {"CloudConfigInvalid", "CloudObjectNotFound"} <= ALL_ERROR_CODES

    unknown_type = _config_payload()
    unknown_type["type_map"] = {"aws:s3:bucket": "unknown_type"}
    with pytest.raises(CloudConfigInvalid, match="unknown object type"):
        _config(unknown_type)

    unknown_baseline = _config_payload()
    unknown_baseline["baseline_ids"] = ["missing-baseline"]
    with pytest.raises(CloudConfigInvalid, match="unknown baseline_id"):
        _config(unknown_baseline)

    for invalid_batch_size in (0, -1, True):
        payload = _config_payload()
        payload["batch_size"] = invalid_batch_size
        with pytest.raises(CloudConfigInvalid, match="batch_size"):
            _config(payload)

    duplicate_baseline = _config_payload()
    duplicate_baseline["baseline_ids"] = ["cis-aws-s3-v1", "cis-aws-s3-v1"]
    with pytest.raises(CloudConfigInvalid, match="duplicates"):
        _config(duplicate_baseline)

    with pytest.raises(CloudConfigInvalid, match="known_object_types"):
        CloudNormalizationConfig.model_validate(
            _config_payload(), context={"known_object_types": "cloud_storage"}
        )

    extra_field = _config_payload()
    extra_field["mode"] = "assessment"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _config(extra_field)


def test_cspm_verdict_fields_rejected() -> None:
    forbidden = {
        "severity",
        "score",
        "risk_score",
        "compliance_status",
        "finding",
        "action",
    }
    assert not (set(NormalizedCloudObject.model_fields) & forbidden)

    public_callables = {
        name
        for name, value in inspect.getmembers(cspm)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & {"assess", "score", "detect"})

    for field in forbidden:
        payload = _normalized_payload()
        payload[field] = "forbidden"
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            NormalizedCloudObject.model_validate(payload)

    for container in ("native_facts", "field_provenance", "conflicts"):
        payload = _normalized_payload()
        if container == "native_facts":
            payload[container] = {"network": {"SeVeRiTy": "high"}}
            payload["field_provenance"] = {"network": "$.network"}
        elif container == "field_provenance":
            payload["native_facts"] = {"Compliance_Status": "NON_COMPLIANT"}
            payload[container] = {"Compliance_Status": "$.complianceState"}
        else:
            payload[container] = [{"resolution": {"RISK_SCORE": 0.8}}]

        with pytest.raises(CloudConfigInvalid, match="reserved verdict key"):
            NormalizedCloudObject.model_validate(payload)

    descriptor = CloudResourceDescriptor(
        provider="aws",
        account="123456789012",
        region="eu-north-1",
        resource_type="aws:s3:bucket",
        resource_id="arn:aws:s3:::example",
        raw={"Severity": "HIGH", "ComplianceState": "NON_COMPLIANT"},
        observed_at=NOW,
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
    )
    assert descriptor.raw["Severity"] == "HIGH"


def test_cspm_native_facts_provenance_bound() -> None:
    normalized = NormalizedCloudObject.model_validate(_normalized_payload())
    assert set(normalized.native_facts) == set(normalized.field_provenance)

    missing_provenance = _normalized_payload()
    missing_provenance["field_provenance"] = {
        "encryption_enabled": "$.properties.encryption.enabled"
    }
    with pytest.raises(CloudConfigInvalid, match=r"missing provenance=.*network"):
        NormalizedCloudObject.model_validate(missing_provenance)

    orphaned_provenance = _normalized_payload()
    orphaned_provenance["field_provenance"] = {
        **orphaned_provenance["field_provenance"],
        "invented_posture": "$.does_not_exist",
    }
    with pytest.raises(CloudConfigInvalid, match=r"orphaned provenance=.*invented_posture"):
        NormalizedCloudObject.model_validate(orphaned_provenance)


def test_cspm_tenant_model_guard() -> None:
    normalized = NormalizedCloudObject.model_validate(_normalized_payload())
    assert normalized.tenant_id == TENANT

    local_payload = _normalized_payload()
    local_payload["tenant_id"] = None
    assert NormalizedCloudObject.model_validate(local_payload).tenant_id is None

    malformed_tenant = _normalized_payload()
    malformed_tenant["tenant_id"] = "tenant-one"
    with pytest.raises(SchemaValidationError, match="tenant_id must be a UUID"):
        NormalizedCloudObject.model_validate(malformed_tenant)

    for field, value, expected in (
        ("object_id", new_id("evd"), "obj_"),
        ("evidence_id", new_id("obj"), "evd_"),
    ):
        malformed_id = _normalized_payload()
        malformed_id[field] = value
        with pytest.raises(SchemaValidationError, match=expected):
            NormalizedCloudObject.model_validate(malformed_id)


def test_cspm_routing_result_consistency() -> None:
    accepted = OwnerRouteOutcome(owner="inventory", status="accepted", refs=[new_id("obj")])
    failed = OwnerRouteOutcome(
        owner="exposure", status="failed", refs=[], detail="owner unavailable"
    )

    partial = CloudRoutingResult(
        object_id=new_id("obj"), status="partial", outcomes=[accepted, failed]
    )
    assert partial.status == "partial"
    assert [outcome.status for outcome in partial.outcomes] == ["accepted", "failed"]

    with pytest.raises(CloudConfigInvalid, match="requires detail"):
        OwnerRouteOutcome(owner="risk", status="failed")

    with pytest.raises(CloudConfigInvalid, match="must be 'partial'"):
        CloudRoutingResult(object_id=new_id("obj"), status="complete", outcomes=[accepted, failed])

    with pytest.raises(CloudConfigInvalid, match="owners must be unique"):
        CloudRoutingResult(
            object_id=new_id("obj"),
            status="complete",
            outcomes=[accepted, accepted.model_copy()],
        )
