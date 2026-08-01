"""ECR-0086 absence guards for the three genuine capability gaps."""

from __future__ import annotations

from pathlib import Path

import pytest

from .absence_guard import CapabilityAbsenceSpec, discover_capability_signals

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "aqelyn"

DISPOSITION_B_SPECS = (
    CapabilityAbsenceSpec(
        ea_number="EA-0052",
        label="Endpoint Intelligence",
        raw_terms=(
            "endpoint_telemetry",
            "agent_enrolment",
            "agent_enrollment",
            "process_inventory",
            "process_list",
            "running_process",
            "endpoint_inventory",
            "endpoint_agent",
        ),
        token_sets=(
            frozenset(("endpoint", "intelligence")),
            frozenset(("endpoint", "telemetry")),
            frozenset(("endpoint", "agent")),
            frozenset(("agent", "enrolment")),
            frozenset(("agent", "enrollment")),
            frozenset(("process", "inventory")),
        ),
    ),
    CapabilityAbsenceSpec(
        ea_number="EA-0053",
        label="Endpoint Security Assessment",
        raw_terms=(
            "endpoint_security_assessment",
            "endpoint_posture",
            "endpoint_misconfiguration",
            "endpoint_remediation",
        ),
        token_sets=(
            frozenset(("endpoint", "security", "assessment")),
            frozenset(("endpoint", "posture")),
            frozenset(("endpoint", "misconfiguration")),
            frozenset(("endpoint", "remediation")),
        ),
    ),
    CapabilityAbsenceSpec(
        ea_number="EA-0054",
        label="Web Intelligence",
        raw_terms=(
            "web_intelligence",
            "website_scanning",
            "domain_scanning",
            "tls_handshake",
            "http_headers",
            "csp_header",
            "hsts",
            "dkim",
            "dmarc",
        ),
        token_sets=(
            frozenset(("web", "intelligence")),
            frozenset(("website", "scanning")),
            frozenset(("domain", "scanning")),
            frozenset(("tls", "handshake")),
            frozenset(("http", "headers")),
            frozenset(("csp", "header")),
            frozenset(("hsts",)),
            frozenset(("dkim",)),
            frozenset(("dmarc",)),
        ),
    ),
)
SPEC_IDS = tuple(spec.ea_number.lower().replace("-", "") for spec in DISPOSITION_B_SPECS)

RAW_WITNESSES = {
    "EA-0052": ('capability = "endpoint_telemetry"\n', "endpoint_telemetry"),
    "EA-0053": ('capability = "endpoint_posture"\n', "endpoint_posture"),
    "EA-0054": ('capability = "tls_handshake"\n', "tls_handshake"),
}
TOKEN_WITNESSES = {
    "EA-0052": "EndpointIntelligenceEngine",
    "EA-0053": "EndpointSecurityAssessmentEngine",
    "EA-0054": "WebIntelligenceEngine",
}


def test_batch_disposition_b_guard_roster_pinned() -> None:
    """Deleting a whole parametrized guard row is itself a detectable failure."""

    assert tuple(spec.ea_number for spec in DISPOSITION_B_SPECS) == (
        "EA-0052",
        "EA-0053",
        "EA-0054",
    )


@pytest.mark.parametrize("spec", DISPOSITION_B_SPECS, ids=SPEC_IDS)
def test_batch_disposition_b_capability_has_no_owner(spec: CapabilityAbsenceSpec) -> None:
    """Recorded gaps stay absent under all three bounded discovery branches."""

    signals = discover_capability_signals(SRC, spec)
    assert signals.declared_owners == (), (
        f"{spec.ea_number} {spec.label} now has declared owners: "
        f"{[path.relative_to(ROOT) for path in signals.declared_owners]}. Reclassify the row."
    )
    assert signals.raw_hits == (), (
        f"{spec.ea_number} {spec.label} now has raw vocabulary hits: {signals.raw_hits}. "
        "Reclassify the row."
    )
    assert signals.identifier_hits == (), (
        f"{spec.ea_number} {spec.label} now has normalized identifier hits: "
        f"{signals.identifier_hits}. Reclassify the row."
    )


@pytest.mark.parametrize("spec", DISPOSITION_B_SPECS, ids=SPEC_IDS)
def test_batch_absence_declaration_branch_has_unique_witness(
    tmp_path: Path,
    spec: CapabilityAbsenceSpec,
) -> None:
    """An exact EA declaration fires without either vocabulary branch."""

    package_init = _write_witness(
        tmp_path,
        spec,
        f'"""Opaque capability ({spec.ea_number})."""\n',
    )
    signals = discover_capability_signals(tmp_path, spec)
    assert signals.declared_owners == (package_init,)
    assert signals.raw_hits == ()
    assert signals.identifier_hits == ()


@pytest.mark.parametrize("spec", DISPOSITION_B_SPECS, ids=SPEC_IDS)
def test_batch_absence_raw_keyword_branch_has_unique_witness(
    tmp_path: Path,
    spec: CapabilityAbsenceSpec,
) -> None:
    """A string literal fires the raw net without declaration or identifier help."""

    source, expected_indicator = RAW_WITNESSES[spec.ea_number]
    package_init = _write_witness(tmp_path, spec, source)
    location = package_init.relative_to(tmp_path).as_posix()
    signals = discover_capability_signals(tmp_path, spec)
    assert signals.declared_owners == ()
    assert signals.raw_hits == (f"{location}: {expected_indicator}",)
    assert signals.identifier_hits == ()


@pytest.mark.parametrize("spec", DISPOSITION_B_SPECS, ids=SPEC_IDS)
def test_batch_absence_normalized_identifier_branch_has_unique_witness(
    tmp_path: Path,
    spec: CapabilityAbsenceSpec,
) -> None:
    """CamelCase capability names fire token matching without raw-term help."""

    class_name = TOKEN_WITNESSES[spec.ea_number]
    package_init = _write_witness(tmp_path, spec, f"class {class_name}:\n    pass\n")
    location = package_init.relative_to(tmp_path).as_posix()
    signals = discover_capability_signals(tmp_path, spec)
    assert signals.declared_owners == ()
    assert signals.raw_hits == ()
    assert signals.identifier_hits == (f"{location}: {class_name}",)


def _write_witness(tmp_path: Path, spec: CapabilityAbsenceSpec, source: str) -> Path:
    package = tmp_path / f"witness_{spec.ea_number.lower().replace('-', '')}"
    package.mkdir()
    package_init = package / "__init__.py"
    package_init.write_text(source, encoding="utf-8")
    return package_init
