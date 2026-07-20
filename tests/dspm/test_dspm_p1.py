"""C-028 P1 acceptance tests for DSPM types and config."""

from __future__ import annotations

import inspect
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import aqelyn.dspm as dspm
from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, is_valid, new_id
from aqelyn.conventions.errors import (
    ClassificationUnavailable,
    DataAssetNotFound,
    DataExposureNotFound,
    DSPMConfigInvalid,
    SchemaValidationError,
)
from aqelyn.decision.models import ClaimRef, Derivation, DerivationStep
from aqelyn.dspm import (
    ClassificationCandidate,
    ClassificationConflict,
    ClassificationSignal,
    ClassifierRule,
    DataAccessClaim,
    DataAccessContext,
    DataAsset,
    DataExposure,
    DataFieldDescriptor,
    DataPostureAssessment,
    DataStoreDescriptor,
    DataStoreLocation,
    DSPMConfig,
    DSPMScope,
    FieldClassification,
    ReachabilityClaim,
)
from aqelyn.lake.models import VALID_CLASSIFICATIONS as LAKE_CLASSIFICATIONS
from aqelyn.lake.models import Classification as LakeClassification
from aqelyn.lake.models import SchemaType as LakeSchemaType
from aqelyn.policy import Condition

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000310001"


def _location(**overrides: object) -> DataStoreLocation:
    data: dict[str, object] = {
        "provider": "aws",
        "account_ref": "account-123",
        "region": "eu-north-1",
        "resource_ref": "arn:aws:s3:::billing-records",
    }
    data.update(overrides)
    return DataStoreLocation.model_validate(data)


def _signal(**overrides: object) -> ClassificationSignal:
    data: dict[str, object] = {
        "id": "detector:email-address:v1",
        "kind": "detector_match",
        "detector_ref": "detector:email-address:v1",
        "match_count": 4,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return ClassificationSignal.model_validate(data)


def _field(**overrides: object) -> DataFieldDescriptor:
    data: dict[str, object] = {
        "name": "customer_email",
        "data_type": "string",
        "signals": [_signal()],
        "existing_classification": None,
    }
    data.update(overrides)
    return DataFieldDescriptor.model_validate(data)


def _descriptor(**overrides: object) -> DataStoreDescriptor:
    data: dict[str, object] = {
        "store_id": "aws:s3:billing-records",
        "tenant_id": TENANT,
        "store_type": "bucket",
        "location": _location(),
        "fields": [_field()],
        "access_claims": [],
        "reachability_claim": None,
        "source_id": new_id("src"),
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return DataStoreDescriptor.model_validate(data)


def _classification(**overrides: object) -> FieldClassification:
    data: dict[str, object] = {
        "field": "customer_email",
        "classification": "pii",
        "status": "known",
        "flagged": False,
        "rule_refs": ["rule:email-is-pii:v1"],
        "confidence": 0.92,
        "evidence_ids": [new_id("evd")],
        "reason": "The detector found email-shaped metadata.",
    }
    data.update(overrides)
    return FieldClassification.model_validate(data)


def _asset(**overrides: object) -> DataAsset:
    data: dict[str, object] = {
        "object_id": new_id("obj"),
        "inventory_ref": new_id("ast"),
        "tenant_id": TENANT,
        "store_id": "aws:s3:billing-records",
        "store_type": "bucket",
        "location": _location(),
        "field_classifications": [_classification()],
        "max_known_sensitivity": "pii",
        "classification_status": "complete",
        "flagged": False,
        "conflicts": [],
        "access_claims": [],
        "reachability_claim": None,
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
        "version": 1,
    }
    data.update(overrides)
    return DataAsset.model_validate(data)


def _derivation(*, score: float = 81.0) -> Derivation:
    evidence_id = new_id("evd")
    return Derivation(
        inputs=[ClaimRef(kind="finding", ref_id="data-exposure:billing", evidence_id=evidence_id)],
        steps=[
            DerivationStep(
                seq=1,
                op="weighted_sum",
                input_refs=["data-exposure:billing"],
                params={"weights": [1.0]},
                output={"score": score},
                note="EA-0023 composed the exposure score.",
            )
        ],
        result={"score": score},
        model_version=1,
        engine_version="exposure:1",
    )


def _exposure(**overrides: object) -> DataExposure:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "data_asset_id": new_id("dsa"),
        "object_id": new_id("obj"),
        "exposure_ref": new_id("exp"),
        "sensitivity": "unknown",
        "reachability": "external",
        "state": "classification_gap",
        "flagged": True,
        "score": None,
        "derivation": None,
        "access_evidence_ids": [],
        "reason": "The store is reachable but classification is incomplete.",
        "evidence_ids": [new_id("evd")],
        "detected_at": NOW,
    }
    data.update(overrides)
    return DataExposure.model_validate(data)


def _assessment(**overrides: object) -> DataPostureAssessment:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "run_at": NOW,
        "scope": DSPMScope(store_types=["bucket"]),
        "coverage_status": "pending",
        "coverage_reason": "Classification evidence is unavailable.",
    }
    data.update(overrides)
    return DataPostureAssessment.model_validate(data)


def _rule(*, rule_id: str = "rule:email-is-pii:v1") -> ClassifierRule:
    return ClassifierRule(
        id=rule_id,
        condition=Condition(op="eq", attr="field.data_type", value="string"),
        classification="pii",
        reason="Email metadata is personal data.",
    )


def _config(**overrides: object) -> DSPMConfig:
    data: dict[str, object] = {
        "classifier_rules": [_rule()],
        "sensitivity_factors": {
            "public": 0.0,
            "internal": 0.25,
            "pii": 0.8,
            "secret": 1.0,
        },
    }
    data.update(overrides)
    return DSPMConfig.model_validate(data)


def test_dspm_no_collection_or_bulk_read(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def _socket(*args: object, **kwargs: object) -> None:
        del args, kwargs
        attempts.append("socket")

    def _read(*args: object, **kwargs: object) -> bytes:
        del args, kwargs
        attempts.append("read")
        return b""

    monkeypatch.setattr(socket, "socket", _socket)
    monkeypatch.setattr(Path, "read_bytes", _read)
    descriptor = _descriptor()

    public_callables = {
        name
        for name, value in inspect.getmembers(dspm)
        if not name.startswith("_") and callable(value)
    }
    assert not (
        public_callables & {"scan", "probe", "connect", "collect", "sample", "read", "read_content"}
    )
    assert descriptor.store_id == "aws:s3:billing-records"
    assert attempts == []


@pytest.mark.parametrize(
    "forbidden",
    ["raw_value", "sample", "content", "rows", "document", "blob", "credential", "token"],
)
def test_dspm_no_raw_sensitive_shape(forbidden: str) -> None:
    descriptor = _descriptor().model_dump()
    descriptor[forbidden] = "must-not-fit"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DataStoreDescriptor.model_validate(descriptor)

    asset = _asset().model_dump()
    asset[forbidden] = "must-not-fit"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DataAsset.model_validate(asset)

    field = _field().model_dump()
    field[forbidden] = "must-not-fit"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DataFieldDescriptor.model_validate(field)


@pytest.mark.parametrize(
    "resource_ref",
    [
        "https://reader:password@example.test/store",
        "https://example.test/store?token=secret",
        "https://example.test/store?X-Amz-Signature=abc",
    ],
)
def test_dspm_resource_ref_rejects_credentials(resource_ref: str) -> None:
    with pytest.raises(DSPMConfigInvalid, match="credential"):
        _location(resource_ref=resource_ref)


def test_dspm_taxonomy_reused() -> None:
    assert dspm.Classification is LakeClassification
    assert dspm.SchemaType is LakeSchemaType
    assert dspm.VALID_CLASSIFICATIONS is LAKE_CLASSIFICATIONS
    assert {"public", "internal", "pii", "secret"} == dspm.VALID_CLASSIFICATIONS
    assert {"public", "internal", "pii", "secret", "unknown"} == dspm.VALID_SENSITIVITIES
    assert {"bucket", "database", "fileshare", "warehouse", "other"} == dspm.VALID_STORE_TYPES

    with pytest.raises(ValidationError):
        _field(data_type="binary")
    with pytest.raises(ValidationError):
        _field(existing_classification="unknown")


@pytest.mark.parametrize(
    "overrides",
    [
        {"classification": "unknown", "status": "known"},
        {"classification": "public", "status": "unknown", "flagged": True},
        {"classification": "unknown", "status": "unknown", "flagged": False},
        {"classification": "unknown", "status": "conflict", "flagged": False},
    ],
)
def test_dspm_unknown_not_public(overrides: dict[str, object]) -> None:
    with pytest.raises(DSPMConfigInvalid):
        _classification(**overrides)

    unknown = _classification(
        classification="unknown",
        status="unknown",
        flagged=True,
        confidence=0.0,
    )
    asset = _asset(
        field_classifications=[unknown],
        max_known_sensitivity=None,
        classification_status="unknown",
        flagged=True,
    )
    assert asset.max_known_sensitivity is None
    assert asset.flagged is True

    with pytest.raises(DSPMConfigInvalid, match="unknown asset must be flagged"):
        _asset(
            field_classifications=[unknown],
            max_known_sensitivity=None,
            classification_status="unknown",
            flagged=False,
        )


def test_dspm_classification_evidence() -> None:
    classification = _classification()
    assert classification.evidence_ids
    assert classification.confidence == pytest.approx(0.92)

    with pytest.raises(DSPMConfigInvalid, match="evidence_ids must not be empty"):
        _classification(evidence_ids=[])
    with pytest.raises(SchemaValidationError, match="use evd_ prefix"):
        _classification(evidence_ids=[new_id("src")])
    with pytest.raises(DSPMConfigInvalid, match="max_known_sensitivity"):
        _asset(max_known_sensitivity="secret")


def test_dspm_conflicts_are_structural() -> None:
    candidates = [
        ClassificationCandidate(
            classification="pii",
            source_ref="source:a",
            reliability=0.8,
            evidence_id=new_id("evd"),
        ),
        ClassificationCandidate(
            classification="secret",
            source_ref="source:b",
            reliability=0.8,
            evidence_id=new_id("evd"),
        ),
    ]
    conflict = ClassificationConflict(
        field="customer_email",
        candidates=candidates,
        unresolved=True,
    )
    field = _classification(
        classification="unknown",
        status="conflict",
        flagged=True,
    )
    asset = _asset(
        field_classifications=[field],
        max_known_sensitivity=None,
        classification_status="conflict",
        flagged=True,
        conflicts=[conflict],
    )
    assert asset.classification_status == "conflict"

    with pytest.raises(DSPMConfigInvalid, match="cannot name resolved_by"):
        ClassificationConflict(
            field="customer_email",
            candidates=candidates,
            unresolved=True,
            resolved_by="source:a",
        )


def test_dspm_exposure_states() -> None:
    gap = _exposure()
    pending = _exposure(
        sensitivity="pii",
        reachability="unknown",
        state="reachability_pending",
        reason="Reachability has not been computed.",
    )
    confirmed = _exposure(
        sensitivity="secret",
        reachability="external",
        state="confirmed",
        score=81.0,
        derivation=_derivation(),
        reason="A secret store is externally reachable.",
    )
    assert gap.score is None
    assert pending.reachability == "unknown"
    assert confirmed.score == pytest.approx(81.0)

    invalid: list[dict[str, object]] = [
        {"state": "classification_gap", "sensitivity": "public"},
        {"state": "classification_gap", "flagged": False},
        {"state": "reachability_pending", "reachability": "internal"},
        {"state": "reachability_pending", "score": 1.0, "derivation": _derivation(score=1.0)},
        {
            "state": "confirmed",
            "sensitivity": "internal",
            "score": 1.0,
            "derivation": _derivation(score=1.0),
        },
        {"state": "confirmed", "sensitivity": "pii", "score": 1.0},
    ]
    for overrides in invalid:
        with pytest.raises(DSPMConfigInvalid):
            _exposure(**overrides)


def test_dspm_assessment_coverage_is_honest() -> None:
    pending = _assessment()
    complete = _assessment(
        coverage_status="complete",
        coverage_reason=None,
        stores_evaluated=1,
        classified_fields=1,
        evidence_id=new_id("evd"),
    )
    truncated = _assessment(
        coverage_status="truncated",
        coverage_reason="max_work exhausted",
        next_cursor="cursor-100",
        stores_evaluated=100,
        classified_fields=80,
        unknown_fields=20,
        evidence_id=new_id("evd"),
    )
    assert pending.coverage_status == "pending"
    assert complete.coverage_status == "complete"
    assert truncated.next_cursor == "cursor-100"

    for overrides in (
        {"stores_evaluated": 1},
        {"exposure_ids": [new_id("dxe")]},
        {"evidence_id": new_id("evd")},
        {"coverage_reason": None},
    ):
        with pytest.raises(DSPMConfigInvalid, match="pending assessment"):
            _assessment(**overrides)

    with pytest.raises(DSPMConfigInvalid, match="truncated assessment"):
        _assessment(coverage_status="truncated", coverage_reason="max_work exhausted")
    with pytest.raises(DSPMConfigInvalid, match="complete assessment"):
        _assessment(coverage_status="complete", coverage_reason=None, next_cursor="cursor")


def test_dspm_access_context_pending_not_known_empty() -> None:
    asset_id = new_id("dsa")
    claim = DataAccessClaim(
        identity_id=new_id("obj"),
        claim_kind="observed",
        evidence_id=new_id("evd"),
    )
    pending = DataAccessContext(
        data_asset_id=asset_id,
        status="pending",
        claims=[claim],
        reason="IAG owner is unavailable.",
    )
    known = DataAccessContext(
        data_asset_id=asset_id,
        status="known",
        claims=[claim],
        reason="The evidenced claim was checked.",
    )
    assert pending.status == "pending"
    assert known.status == "known"

    with pytest.raises(DSPMConfigInvalid, match="requires evidenced claims"):
        DataAccessContext(
            data_asset_id=asset_id,
            status="known",
            reason="An empty result must not imply nobody has access.",
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: DSPMScope(limit=0),
        lambda: _signal(match_count=-1),
        lambda: _descriptor(fields=[_field(), _field()]),
        lambda: _config(sensitivity_factors={"public": 0.0}),
        lambda: _config(
            sensitivity_factors={
                "public": 0.0,
                "internal": 0.8,
                "pii": 0.4,
                "secret": 1.0,
            }
        ),
        lambda: _config(batch_size=0),
        lambda: _config(max_work=True),
        lambda: _config(classifier_rules=[_rule(), _rule()]),
    ],
)
def test_dspm_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(DSPMConfigInvalid):
        factory()


def test_dspm_ids_errors_and_model_defaults() -> None:
    asset = _asset()
    exposure = _exposure()
    assessment = _assessment()
    config = _config()
    descriptor = _descriptor(
        reachability_claim=ReachabilityClaim(
            reachability="external",
            evidence_id=new_id("evd"),
            reason="A gateway policy exposes the store.",
        )
    )

    assert is_valid(asset.id, "dsa")
    assert is_valid(exposure.id, "dxe")
    assert is_valid(assessment.id, "dpa")
    assert PREFIXES["dsa"] == "data_asset"
    assert PREFIXES["dxe"] == "data_exposure"
    assert PREFIXES["dpa"] == "data_posture_assessment"
    assert descriptor.reachability_claim is not None
    assert config.batch_size == 100
    assert config.max_work == 5_000
    assert config.max_fields_per_store == 1_000
    assert config.max_signals_per_field == 100

    for error in (
        DSPMConfigInvalid,
        DataAssetNotFound,
        DataExposureNotFound,
        ClassificationUnavailable,
    ):
        assert error.code in ALL_ERROR_CODES


def test_dspm_extra_config_is_rejected() -> None:
    payload: dict[str, Any] = _config().model_dump()
    payload["default_unknown_to_public"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DSPMConfig.model_validate(payload)
