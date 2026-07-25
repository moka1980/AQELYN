"""ECR-0064: the grype mapper, and the distinction real data made load-bearing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aqelyn.vuln.parse import parse_grype

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def _document(**vulnerability: Any) -> dict[str, Any]:
    base = {
        "id": "CVE-2026-0001",
        "severity": "high",
        "cvss": [{"source": "nvd", "metrics": {"baseScore": 7.5}, "vector": "CVSS:3.1/AV:N"}],
    }
    base.update(vulnerability)
    return {"matches": [{"vulnerability": base, "artifact": {"purl": "pkg:deb/x@1"}}]}


def _one(**vulnerability: Any) -> Any:
    parsed = parse_grype(
        _document(**vulnerability), scanner="grype", confidence=0.9, observed_at=NOW
    )
    assert not parsed.rejected, parsed.rejected
    return parsed.records[0]


def test_vuln_parse_grype_document() -> None:
    record = _one()

    assert record.cve_id == "CVE-2026-0001"
    assert record.severity == "high"
    assert record.cvss is not None
    assert record.cvss.value == 7.5


def test_vuln_parse_absent_cvss_is_none_not_zero() -> None:
    """Absence is representable and is never a zero.

    A zero would claim the vulnerability scores nothing -- the most favourable
    reading of an absence. `None` reaches the engine as an unknown factor instead.
    """
    record = _one(cvss=[])

    assert record.cvss is None


def test_vuln_parse_none_and_unknown_are_distinct() -> None:
    """ECR-0064 amendment: `none` and `unknown` SHALL be provably distinct.

    `none` means the source stated there is no severity -- a positive claim of
    absence of risk. `unknown` means the source did not say. Once `none` exists in
    the vocabulary it is a target that type-checks and reads as reasonable, so
    conflating them is the platform's founding error wearing a valid enum member.

    **A test exercising only `Unknown` would pass against a mapper that routes it to
    `none`.** This drives both, and asserts they differ.
    """
    stated_none = _one(severity="None")
    stated_unknown = _one(severity="Unknown")

    assert stated_none.severity == "none"
    assert stated_unknown.severity == "unknown"
    assert stated_none.severity != stated_unknown.severity


def test_vuln_parse_negligible_is_carried_verbatim() -> None:
    """Not folded into `low` (which inflates) or `none` (which the scanner did not say)."""
    assert _one(severity="Negligible").severity == "negligible"


def test_vuln_parse_cvss_not_priority() -> None:
    """The mapper carries CVSS as an input; it computes and ranks nothing."""
    record = _one()

    assert not hasattr(record, "priority")
    assert record.disposition is None
    assert record.cvss is not None
    assert record.cvss.value == 7.5  # verbatim, not normalized or scored


def test_vuln_parse_unrepresentable_severity_refused_with_reason() -> None:
    parsed = parse_grype(
        _document(severity="Catastrophic"), scanner="grype", confidence=0.9, observed_at=NOW
    )

    assert not parsed.records
    assert len(parsed.rejected) == 1
    assert "VALID_SEVERITIES" in parsed.rejected[0].reason
