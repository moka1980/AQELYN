"""S-track unknown-cause taxonomy and roadmap classification."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.first_run import (
    FactorReading,
    RunReport,
    UnreadableFactor,
    coverage_factor_readings,
    density_report,
    read_factors,
)

from aqelyn.vuln import CoverageGap, CoverageReport


def test_unknown_roadmap_uses_typed_cause_not_source_suffix() -> None:
    structural = FactorReading(
        name="threat",
        status="unknown",
        reason="The positive-only source cannot assert for this CVE.",
        source="kev:2026.07.25:unavailable",
        unknown_cause="source_cannot_assert",
    )
    closable = FactorReading(
        name="exposure",
        status="unknown",
        reason="No provider is configured.",
        source="exposure:no-provider",
        unknown_cause="provider_unconfigured",
    )

    assert structural.closable is False
    assert closable.closable is True


def test_unknown_roadmap_keeps_carried_input_absence_consistent() -> None:
    priority = SimpleNamespace(
        factors={
            "cvss": {
                "status": "unknown",
                "reason": "No CVSS was supplied.",
                "source": "cvss:unavailable",
                "unknown_cause": "input_missing",
            },
            "epss": {
                "status": "unknown",
                "reason": "No EPSS was supplied.",
                "source": "epss:missing",
                "unknown_cause": "input_missing",
            },
        }
    )

    readings = read_factors(priority)

    assert {reading.name: reading.closable for reading in readings} == {
        "cvss": True,
        "epss": True,
    }


def test_vuln_cpe_only_appears_closable_in_density(
    capsys: pytest.CaptureFixture[str],
) -> None:
    coverage = CoverageReport(
        scanned=[],
        unscanned=[],
        stale=[],
        unassessable=[
            CoverageGap(
                asset_ref="ast_019f0000000070008000000000000072",
                reason="no provider matches identity_kind=cpe",
                unknown_cause="provider_unconfigured",
            )
        ],
        computed_at=datetime(2026, 7, 27, 15, 0, tzinfo=UTC),
    )

    [reading] = coverage_factor_readings(coverage)

    assert reading.name == "vulnerability_coverage"
    assert reading.closable is True
    assert "ast_" not in repr(reading)

    density_report(
        RunReport(
            target="private-estate",
            tenant_mode="enterprise",
            sbom_components=1,
            sbom_parsed=1,
            grype_matches=0,
            vuln_records=0,
            vuln_rejected=[],
            join_total=0,
            join_matched=0,
            stored=0,
            findings=[],
            coverage_factors=[reading],
        )
    )
    rendered = capsys.readouterr().out
    assert "vulnerability_coverage" in rendered
    assert "no provider matches identity_kind=cpe" in rendered
    assert "ast_" not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "unknown",
            "reason": "Cause omitted.",
            "source": "factor:unknown",
        },
        {
            "status": "known",
            "reason": "Known factor.",
            "source": "factor:known",
            "unknown_cause": "input_missing",
        },
    ],
    ids=["unknown-without-cause", "known-with-cause"],
)
def test_unknown_roadmap_refuses_inconsistent_factor_payload(
    payload: dict[str, object],
) -> None:
    priority = SimpleNamespace(factors={"factor": payload})

    with pytest.raises(UnreadableFactor):
        read_factors(priority)
