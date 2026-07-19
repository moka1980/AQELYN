"""Z1 acceptance tests for SSPM types, config, and structural boundaries."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

import aqelyn.sspm as sspm
from aqelyn.conventions import ALL_ERROR_CODES, new_id
from aqelyn.conventions.errors import SaaSConfigInvalid, SchemaValidationError
from aqelyn.sspm import (
    MAX_INTEGRATION_NODES,
    BlastRadius,
    IntegrationDescriptor,
    NormalizedSaaSObject,
    SaaSAppDescriptor,
    SaaSConfig,
    SaaSIntegration,
    SaaSRoutingResult,
)

NOW = datetime(2026, 7, 19, 13, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000290001"


def _config_payload() -> dict[str, Any]:
    return {
        "type_map": {
            "google_workspace:application": "saas_app",
            "microsoft_365:oauth_grant": "saas_integration",
        },
        "baseline_ids": ["cis-google-workspace-v1"],
        "sensitive_scopes": ["read_all_files", "directory.readwrite.all"],
        "batch_size": 100,
        "integration_max_nodes": 10_000,
    }


def _config(payload: dict[str, Any] | None = None) -> SaaSConfig:
    return SaaSConfig.model_validate(
        payload or _config_payload(),
        context={
            "known_object_types": {"saas_app", "saas_integration"},
            "known_baseline_ids": {"cis-google-workspace-v1"},
        },
    )


def _normalized_payload() -> dict[str, Any]:
    return {
        "object_id": new_id("obj"),
        "tenant_id": TENANT,
        "object_type": "saas_app",
        "provider": "google_workspace",
        "tenant": "example.com",
        "native_facts": {
            "mfa_enabled": True,
            "allowed_domains": ["example.com"],
        },
        "field_provenance": {
            "mfa_enabled": "$.security.mfaEnabled",
            "allowed_domains": "$.sharing.allowedDomains",
        },
        "conflicts": [],
        "evidence_id": new_id("evd"),
        "flagged": False,
    }


def _integration_payload(*, status: object = "over_scoped") -> dict[str, Any]:
    object_id = new_id("obj")
    return {
        "object_id": object_id,
        "tenant_id": TENANT,
        "integration_id": "google:oauth:calendar-helper",
        "grantor_ref": new_id("obj"),
        "grantor_kind": "identity",
        "third_party_app": new_id("obj"),
        "third_party_external": True,
        "scopes": ["read_all_files"],
        "over_scoped": status,
        "reachable_object_ids": [new_id("obj")],
        "reachable_truncated": False,
        "known_surface_ref": object_id if status == "over_scoped" else None,
        "claim_confidence": 0.88,
        "evidence_id": new_id("evd"),
        "observed_at": NOW,
        "reason": "External grant carries a sensitive scope.",
    }


def test_sspm_config_invalid() -> None:
    config = _config()
    assert config.integration_max_nodes == 10_000
    assert {
        "SaaSConfigInvalid",
        "SaaSObjectNotFound",
        "IntegrationNotFound",
        "UnmappedSaaSType",
    } <= ALL_ERROR_CODES

    unknown_type = _config_payload()
    unknown_type["type_map"] = {"provider:app": "unknown_type"}
    with pytest.raises(SaaSConfigInvalid, match="unknown object type"):
        _config(unknown_type)

    unknown_baseline = _config_payload()
    unknown_baseline["baseline_ids"] = ["missing-baseline"]
    with pytest.raises(SaaSConfigInvalid, match="unknown baseline_id"):
        _config(unknown_baseline)

    for field, values in (
        ("batch_size", (0, -1, True)),
        ("integration_max_nodes", (0, -1, True, MAX_INTEGRATION_NODES + 1)),
    ):
        for invalid in values:
            payload = _config_payload()
            payload[field] = invalid
            with pytest.raises(SaaSConfigInvalid, match=field):
                _config(payload)

    for field in ("baseline_ids", "sensitive_scopes"):
        duplicate = _config_payload()
        duplicate[field] = [duplicate[field][0], duplicate[field][0]]
        with pytest.raises(SaaSConfigInvalid, match="duplicates"):
            _config(duplicate)

    no_sensitive_scopes = _config_payload()
    no_sensitive_scopes["sensitive_scopes"] = []
    assert _config(no_sensitive_scopes).sensitive_scopes == []

    extra = _config_payload()
    extra["vendor_reputation_weight"] = 0.5
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _config(extra)


def test_sspm_scope_status() -> None:
    integration = SaaSIntegration.model_validate(_integration_payload())
    assert integration.over_scoped == "over_scoped"
    assert integration.known_surface_ref == integration.object_id

    unknown_payload = _integration_payload(status="unknown")
    unknown_payload["scopes"] = []
    unknown = SaaSIntegration.model_validate(unknown_payload)
    assert unknown.over_scoped == "unknown"
    assert unknown.known_surface_ref is None

    within = SaaSIntegration.model_validate(_integration_payload(status="within_scope"))
    assert within.over_scoped == "within_scope"
    assert within.known_surface_ref is None

    for ambiguous in ("true", "false", True, False):
        with pytest.raises(ValidationError):
            SaaSIntegration.model_validate(_integration_payload(status=ambiguous))

    missing_surface = _integration_payload()
    missing_surface["known_surface_ref"] = None
    with pytest.raises(SaaSConfigInvalid, match="known_surface_ref == object_id"):
        SaaSIntegration.model_validate(missing_surface)

    internal = _integration_payload()
    internal["third_party_external"] = False
    with pytest.raises(SaaSConfigInvalid, match="must be external"):
        SaaSIntegration.model_validate(internal)

    unexpected_surface = _integration_payload(status="within_scope")
    unexpected_surface["known_surface_ref"] = unexpected_surface["object_id"]
    with pytest.raises(SaaSConfigInvalid, match="only for an over_scoped"):
        SaaSIntegration.model_validate(unexpected_surface)


def test_sspm_no_verdict_field() -> None:
    forbidden = {
        "severity",
        "score",
        "risk_score",
        "compliance_status",
        "finding",
        "action",
        "vendor_score",
        "vendor_trust",
        "vendor_verdict",
        "confidence",
        "reputation",
        "trust",
        "verdict",
    }
    assert not (set(NormalizedSaaSObject.model_fields) & forbidden)

    public_callables = {
        name
        for name, value in inspect.getmembers(sspm)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & {"assess", "score", "detect", "enumerate"})

    for field in forbidden:
        payload = _normalized_payload()
        payload[field] = "forbidden"
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            NormalizedSaaSObject.model_validate(payload)

    for container in ("native_facts", "field_provenance", "conflicts"):
        payload = _normalized_payload()
        if container == "native_facts":
            payload[container] = {"VendorScore": 0.1}
            payload["field_provenance"] = {"VendorScore": "$.vendor.score"}
        elif container == "field_provenance":
            payload["native_facts"] = {"vendor_trust": "trusted"}
            payload[container] = {"vendor_trust": "$.vendor.trust"}
        else:
            payload[container] = [{"resolution": {"VENDOR_VERDICT": "safe"}}]
        with pytest.raises(SaaSConfigInvalid, match="reserved verdict key"):
            NormalizedSaaSObject.model_validate(payload)

    descriptor = SaaSAppDescriptor(
        provider="google_workspace",
        tenant="example.com",
        app_id="calendar-helper",
        app_name="Calendar Helper",
        resource_type="google_workspace:application",
        raw={"vendorScore": 98, "severity": "HIGH"},
        observed_at=NOW,
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
    )
    assert descriptor.raw["severity"] == "HIGH"


def test_sspm_no_vendor_verdict() -> None:
    fields = set(SaaSIntegration.model_fields)
    assert "claim_confidence" in fields
    assert not fields & {
        "confidence",
        "vendor_score",
        "vendor_trust",
        "vendor_verdict",
        "reputation",
    }

    for field in ("confidence", "vendor_score", "vendor_trust", "vendor_verdict"):
        payload = _integration_payload()
        payload[field] = 0.9
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            SaaSIntegration.model_validate(payload)


def test_sspm_claim_confidence_not_vendor_score() -> None:
    for accepted in (0, 0.5, 1):
        payload = _integration_payload()
        payload["claim_confidence"] = accepted
        assert SaaSIntegration.model_validate(payload).claim_confidence == float(accepted)

    for rejected in (-0.01, 1.01, float("nan"), float("inf"), True):
        payload = _integration_payload()
        payload["claim_confidence"] = rejected
        with pytest.raises(SaaSConfigInvalid, match="claim_confidence"):
            SaaSIntegration.model_validate(payload)


def test_sspm_tenant_and_reference_guards() -> None:
    normalized = NormalizedSaaSObject.model_validate(_normalized_payload())
    integration = SaaSIntegration.model_validate(_integration_payload())
    assert normalized.tenant_id == TENANT
    assert integration.tenant_id == TENANT

    for payload_factory, model in (
        (_normalized_payload, NormalizedSaaSObject),
        (_integration_payload, SaaSIntegration),
    ):
        payload = payload_factory()
        payload["tenant_id"] = "provider-tenant"
        with pytest.raises(SchemaValidationError, match="tenant_id must be a UUID"):
            model.model_validate(payload)

    descriptor = IntegrationDescriptor(
        integration_id="m365:oauth:calendar-helper",
        grantor_ref=new_id("obj"),
        grantor_kind="api",
        third_party_app=new_id("obj"),
        third_party_external=True,
        scopes=[],
        observed_at=NOW,
        raw={},
        source_id=new_id("src"),
    )
    assert descriptor.scopes == []


def test_sspm_provenance_blast_radius_and_routing_guards() -> None:
    normalized = NormalizedSaaSObject.model_validate(_normalized_payload())
    assert set(normalized.native_facts) == set(normalized.field_provenance)

    missing_provenance = _normalized_payload()
    missing_provenance["field_provenance"] = {"mfa_enabled": "$.security.mfaEnabled"}
    with pytest.raises(SaaSConfigInvalid, match="missing provenance"):
        NormalizedSaaSObject.model_validate(missing_provenance)

    object_ids = [new_id("obj"), new_id("obj")]
    radius = BlastRadius(object_ids=object_ids, truncated=True)
    assert radius.object_ids == object_ids
    assert radius.truncated is True

    with pytest.raises(SaaSConfigInvalid, match="duplicates"):
        BlastRadius(object_ids=[object_ids[0], object_ids[0]], truncated=False)

    result = SaaSRoutingResult(
        object_id=new_id("obj"),
        routed_to=["inventory", "assetconfig"],
        routing_pending=["exposure"],
        inventory_ref=new_id("obj"),
        known_surface_refs=[new_id("obj")],
    )
    assert result.routing_pending == ["exposure"]

    with pytest.raises(SaaSConfigInvalid, match="overlap"):
        SaaSRoutingResult(
            object_id=new_id("obj"),
            routed_to=["inventory"],
            routing_pending=["inventory"],
        )
