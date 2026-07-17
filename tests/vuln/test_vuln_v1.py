"""V1 acceptance tests for vulnerability models and no-scan surface."""

from __future__ import annotations

import inspect
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import NoReturn

import pytest

import aqelyn.vuln as vuln
from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, is_valid, new_id
from aqelyn.conventions.actors import ActorRef
from aqelyn.conventions.errors import (
    CoverageUnavailable,
    VulnBasisMissing,
    VulnConfigInvalid,
    VulnNotFound,
    VulnNotReplayable,
)
from aqelyn.exposure import AssetRef
from aqelyn.vuln import (
    CarriedScore,
    CoverageReport,
    Disposition,
    RemediationPlan,
    VulnBasis,
    VulnConfig,
    VulnerabilityAssessment,
    VulnerabilityRecord,
    VulnPriority,
)

NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000240001"


def _asset_ref() -> AssetRef:
    return AssetRef(kind="asset", ref_id="obj:web-1", evidence_id=new_id("evd"))


def _basis(kind: str = "scanner") -> VulnBasis:
    return VulnBasis(
        kind=kind,
        ref="scanner:nessus:run-42",
        as_of=NOW,
        evidence_id=new_id("evd"),
    )


def _cvss(value: float = 9.8) -> CarriedScore:
    return CarriedScore(
        source="nvd:cve-2026-4242",
        value=value,
        vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        as_of=NOW,
    )


def _epss(value: float = 0.73) -> CarriedScore:
    return CarriedScore(source="first:epss:2026-07-17", value=value, as_of=NOW)


def _record(**overrides: object) -> VulnerabilityRecord:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "cve_id": "CVE-2026-4242",
        "scanner": "nessus",
        "asset_ref": _asset_ref(),
        "severity": "low",
        "cvss": _cvss(),
        "epss": _epss(),
        "confidence": 0.84,
        "basis": [_basis()],
        "discovered_at": NOW,
    }
    data.update(overrides)
    return VulnerabilityRecord(**data)


def test_vuln_scanner_basis_required() -> None:
    with pytest.raises(VulnConfigInvalid, match="must not be empty"):
        _record(scanner=" ")

    with pytest.raises(VulnBasisMissing):
        _record(basis=[])

    with pytest.raises(VulnConfigInvalid):
        VulnBasis(kind="feed", ref="nvd", as_of=NOW)


def test_vuln_cvss_carried_not_recomputed() -> None:
    cvss = _cvss(value=9.9)
    epss = _epss(value=0.91)
    record = _record(severity="low", cvss=cvss, epss=epss)

    assert record.cvss == cvss
    assert record.epss == epss
    assert record.cvss.value == 9.9
    assert record.epss.value == 0.91
    assert record.severity == "low"


def test_vuln_no_scan_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"scan", "patch", "execute"}

    public_callables = {
        name
        for name, value in inspect.getmembers(vuln)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & forbidden)

    for model in (
        CarriedScore,
        CoverageReport,
        Disposition,
        RemediationPlan,
        VulnBasis,
        VulnConfig,
        VulnPriority,
        VulnerabilityAssessment,
        VulnerabilityRecord,
    ):
        model_methods = {
            name
            for name, value in inspect.getmembers(model)
            if not name.startswith("_") and callable(value)
        }
        assert not (model_methods & forbidden)

    attempts: list[str] = []

    def blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("socket")
        raise AssertionError("socket use is not permitted in vulnerability V1")

    def blocked_create_connection(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("create_connection")
        raise AssertionError("network connection is not permitted in vulnerability V1")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    monkeypatch.setattr(socket, "create_connection", blocked_create_connection)

    record = _record()

    assert record.scanner == "nessus"
    assert attempts == []


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CarriedScore(source="", value=1.0, as_of=NOW),
        lambda: CarriedScore(source="nvd", value=-1.0, as_of=NOW),
        lambda: CarriedScore(source="nvd", value=float("nan"), as_of=NOW),
        lambda: VulnerabilityRecord(
            tenant_id=TENANT,
            cve_id="CVE-2026-4242",
            scanner="nessus",
            asset_ref=_asset_ref(),
            severity="urgent",
            cvss=_cvss(),
            confidence=0.84,
            basis=[_basis()],
            discovered_at=NOW,
        ),
        lambda: _record(confidence=1.1),
        lambda: _record(status="suppressed"),
        lambda: Disposition(
            actor=ActorRef(actor_type="user", actor_id="analyst@example.com"),
            kind="waived",
            reason="accepted by owner",
            at=NOW,
        ),
        lambda: Disposition(
            actor=ActorRef(actor_type="user", actor_id="analyst@example.com"),
            kind="false_positive",
            reason="",
            at=NOW,
        ),
        lambda: CoverageReport(
            scanned=["asset:1", "asset:1"],
            unscanned=[],
            stale=[],
            computed_at=NOW,
        ),
        lambda: VulnerabilityAssessment(
            tenant_id=TENANT,
            coverage=CoverageReport(scanned=[], unscanned=[], stale=[], computed_at=NOW),
            suppressed_count=-1,
            generated_at=NOW,
        ),
        lambda: RemediationPlan(
            tenant_id=TENANT,
            vulnerability_id=new_id("vln"),
            priority="high",
            proposed_campaign={},
            rationale="Patch during maintenance.",
        ),
        lambda: RemediationPlan(
            tenant_id=TENANT,
            vulnerability_id=new_id("vln"),
            priority="urgent",
            proposed_campaign={"phase": "remediate"},
            rationale="Patch during maintenance.",
        ),
        lambda: VulnConfig(max_priorities=0),
        lambda: VulnConfig(stale_after_days=0),
        lambda: VulnConfig(score_weights={}),
        lambda: VulnConfig(score_weights={"cvss": -0.1}),
    ],
)
def test_vuln_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(VulnConfigInvalid):
        factory()


def test_vuln_v1_model_shapes_and_taxonomy() -> None:
    disposition = Disposition(
        actor=ActorRef(actor_type="user", actor_id="analyst@example.com"),
        kind="false_positive",
        reason="Scanner plugin matched a patched package name.",
        at=NOW,
    )
    record = _record(disposition=disposition)
    coverage = CoverageReport(
        scanned=["asset:web-1"],
        unscanned=["asset:db-1"],
        stale=[],
        computed_at=NOW,
    )
    assessment = VulnerabilityAssessment(
        tenant_id=TENANT,
        priorities=[],
        coverage=coverage,
        suppressed_count=1,
        generated_at=NOW,
    )
    plan = RemediationPlan(
        tenant_id=TENANT,
        vulnerability_id=record.id,
        priority="medium",
        proposed_campaign={"phases": ["remediate", "verify"]},
        owner="platform",
        rationale="Propose a gated response campaign; do not execute.",
    )
    config = VulnConfig()

    assert is_valid(record.id, "vln")
    assert is_valid(assessment.id, "vas")
    assert is_valid(plan.id, "rem")
    assert record.basis[0].kind == "scanner"
    assert record.disposition == disposition
    assert assessment.coverage.unscanned == ["asset:db-1"]
    assert config.score_weights["cvss"] == 0.20

    assert PREFIXES["vln"] == "vulnerability_record"
    assert PREFIXES["vpr"] == "vuln_priority"
    assert PREFIXES["vas"] == "vuln_assessment"
    assert PREFIXES["rem"] == "remediation_plan"
    assert "VulnConfigInvalid" in ALL_ERROR_CODES
    assert "VulnBasisMissing" in ALL_ERROR_CODES
    assert "CoverageUnavailable" in ALL_ERROR_CODES
    assert "VulnNotFound" in ALL_ERROR_CODES
    assert "VulnNotReplayable" in ALL_ERROR_CODES

    for error in (
        VulnConfigInvalid,
        VulnBasisMissing,
        CoverageUnavailable,
        VulnNotFound,
        VulnNotReplayable,
    ):
        assert error.code in ALL_ERROR_CODES
