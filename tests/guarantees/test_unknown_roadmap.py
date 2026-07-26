"""S-track unknown-cause taxonomy and roadmap classification."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.first_run import FactorReading, UnreadableFactor, read_factors


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
