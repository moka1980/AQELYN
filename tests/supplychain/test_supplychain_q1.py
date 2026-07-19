"""C-027 Q1 acceptance tests for supply-chain types and config."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, is_valid, new_id
from aqelyn.conventions.errors import (
    ComponentNotFound,
    ProvenanceUnverifiable,
    SBOMParseError,
    SupplyChainConfigInvalid,
)
from aqelyn.supplychain import (
    VALID_ASSESSMENT_STATUSES,
    VALID_DEPENDENCY_SCOPES,
    VALID_PROVENANCE_KINDS,
    VALID_PROVENANCE_STATUSES,
    VALID_REACHABILITY_STATUSES,
    VALID_SBOM_FORMATS,
    DependencyRelationship,
    ProvenanceAttestation,
    ProvenanceResult,
    ReachabilitySignal,
    SBOMDocument,
    SoftwareComponent,
    SupplyChainAssessment,
    SupplyChainConfig,
)

NOW = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000300001"
PURL = "pkg:pypi/urllib3@2.5.0"


def _document(**overrides: object) -> SBOMDocument:
    data: dict[str, object] = {
        "format": "cyclonedx",
        "subject_ref": "artifact:billing-api:2026.07.19",
        "raw": {"bomFormat": "CycloneDX", "specVersion": "1.6"},
        "source_id": new_id("src"),
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return SBOMDocument.model_validate(data)


def _component(**overrides: object) -> SoftwareComponent:
    data: dict[str, object] = {
        "object_id": new_id("obj"),
        "tenant_id": TENANT,
        "purl": PURL,
        "name": "urllib3",
        "version": "2.5.0",
        "component_type": "library",
        "licenses": ["MIT"],
        "supplier": "Python Packaging Authority",
        "hashes": {"sha256": "a" * 64},
        "direct": False,
        "source_id": new_id("src"),
        "observed_at": NOW,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return SoftwareComponent.model_validate(data)


def _assessment(**overrides: object) -> SupplyChainAssessment:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "run_at": NOW,
        "subject_ref": "artifact:billing-api:2026.07.19",
        "components": 0,
        "direct": 0,
        "transitive": 0,
        "unverified_provenance": 0,
        "vulnerable_components": 0,
        "evidence_id": new_id("evd"),
    }
    data.update(overrides)
    return SupplyChainAssessment.model_validate(data)


def test_sc_reachability_unknown_not_safe() -> None:
    unknown = ReachabilitySignal(
        component_purl=PURL,
        cve_id="CVE-2026-3000",
        reason="Dependency traversal has not run.",
    )
    unreachable = ReachabilitySignal(
        component_purl=PURL,
        cve_id="CVE-2026-3000",
        reachable="unreachable",
        reason="A complete traversal found no path.",
    )

    assert unknown.reachable == "unknown"
    assert unreachable.reachable == "unreachable"
    assert unknown.model_dump() != unreachable.model_dump()

    with pytest.raises(SupplyChainConfigInvalid, match="cannot carry depth"):
        ReachabilitySignal(
            component_purl=PURL,
            cve_id="CVE-2026-3000",
            depth=1,
            reason="Stale path data must not make unknown reach look computed.",
        )


def test_sc_assessment_status_not_clean() -> None:
    pending = _assessment()
    complete = _assessment(
        assessment_status="complete",
        components=900,
        direct=100,
        transitive=800,
        unverified_provenance=20,
        vulnerable_components=3,
    )
    truncated = _assessment(
        assessment_status="truncated",
        components=25,
        direct=4,
        transitive=20,
        unverified_provenance=2,
        vulnerable_components=1,
    )

    assert pending.assessment_status == "pending"
    assert complete.assessment_status == "complete"
    assert truncated.assessment_status == "truncated"
    assert (
        len({pending.assessment_status, complete.assessment_status, truncated.assessment_status})
        == 3
    )

    legacy = pending.model_dump(mode="json")
    legacy.pop("assessment_status")
    legacy["truncated"] = False
    with pytest.raises(ValidationError, match="truncated"):
        SupplyChainAssessment.model_validate(legacy)

    with pytest.raises(SupplyChainConfigInvalid, match="pending assessment"):
        _assessment(
            components=900,
            direct=100,
            transitive=800,
            vulnerable_components=0,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"components": 1, "direct": 1, "transitive": 1}, "direct plus transitive"),
        ({"components": 1, "vulnerable_components": 2}, "vulnerable_components"),
        ({"components": 1, "unverified_provenance": 2}, "unverified_provenance"),
    ],
)
def test_sc_assessment_counts_are_coherent(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(SupplyChainConfigInvalid, match=message):
        _assessment(assessment_status="complete", **overrides)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _document(format="swid"),
        lambda: _document(subject_ref=" "),
        lambda: _component(purl=""),
        lambda: _component(licenses=["MIT", "MIT"]),
        lambda: _component(hashes={"sha256": ""}),
        lambda: DependencyRelationship(
            from_purl=PURL,
            to_purl="pkg:pypi/idna@3.10",
            scope="runtime",
            version_constraint=" ",
        ),
        lambda: ReachabilitySignal(
            component_purl=PURL,
            cve_id="CVE-2026-3000",
            reachable="direct",
            reason="Direct dependency.",
        ),
        lambda: ReachabilitySignal(
            component_purl=PURL,
            cve_id="CVE-2026-3000",
            reachable="transitive",
            depth=2,
            reason="Missing path reference.",
        ),
        lambda: _assessment(components=-1),
        lambda: SupplyChainConfig(max_depth=0),
        lambda: SupplyChainConfig(batch_size=0),
        lambda: SupplyChainConfig(license_policy_id=" "),
        lambda: SupplyChainConfig(sensitive_scopes=["runtime", "runtime"]),
    ],
)
def test_sc_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(SupplyChainConfigInvalid):
        factory()


def test_sc_q1_model_shapes_and_taxonomy() -> None:
    document = _document()
    component = _component()
    relationship = DependencyRelationship(
        from_purl="pkg:pypi/requests@2.32.4",
        to_purl=PURL,
        version_constraint=">=2.0,<3",
        scope="runtime",
        edge_id=new_id("rel"),
    )
    direct = ReachabilitySignal(
        component_purl=PURL,
        cve_id="CVE-2026-3000",
        reachable="direct",
        depth=0,
        reason="The application directly imports this component.",
    )
    attestation = ProvenanceAttestation(
        component_purl=PURL,
        kind="slsa",
        raw={"predicateType": "https://slsa.dev/provenance/v1"},
        evidence_id=new_id("evd"),
    )
    result = ProvenanceResult(
        component_purl=PURL,
        status="unverified",
        detail="No trusted verification result exists yet.",
        evidence_id=new_id("evd"),
    )
    assessment = _assessment()
    config = SupplyChainConfig(
        license_policy_id="policy:licenses:v1",
        sensitive_scopes=["runtime"],
    )

    assert is_valid(document.doc_id, "sbm")
    assert is_valid(assessment.id, "sca")
    assert component.provenance_status == "unverified"
    assert relationship.scope == "runtime"
    assert direct.depth == 0
    assert attestation.kind == "slsa"
    assert result.status == "unverified"
    assert config.max_depth == 6
    assert config.batch_size == 100

    assert {"spdx", "cyclonedx"} == VALID_SBOM_FORMATS
    assert {"direct", "transitive", "unreachable", "unknown"} == VALID_REACHABILITY_STATUSES
    assert {"complete", "truncated", "pending"} == VALID_ASSESSMENT_STATUSES
    assert {"runtime", "dev", "optional"} == VALID_DEPENDENCY_SCOPES
    assert {"verified", "unverified", "failed"} == VALID_PROVENANCE_STATUSES
    assert {"slsa", "sigstore", "signature"} == VALID_PROVENANCE_KINDS

    assert PREFIXES["sbm"] == "sbom_document"
    assert PREFIXES["sca"] == "supply_chain_assessment"
    for error in (
        SupplyChainConfigInvalid,
        SBOMParseError,
        ComponentNotFound,
        ProvenanceUnverifiable,
    ):
        assert error.code in ALL_ERROR_CODES
