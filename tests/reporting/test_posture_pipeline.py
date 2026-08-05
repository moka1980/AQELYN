"""ECR-0100 integration: posture.json through analyze_collection and the renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aqelyn.reporting.analyze import ReportInputError, analyze_collection, load_collection_documents
from aqelyn.reporting.html import render_findings_report

_VULNS: dict[str, Any] = {
    "descriptor": {"name": "grype", "timestamp": "2026-08-06T09:00:00Z"},
    "matches": [],
}


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "observation_id": "obs-ports",
        "subject": {"kind": "host", "ref": "203.0.113.10"},
        "check": "listening_sockets_public",
        "severity": "high",
        "severity_score": 72.0,
        "what_happened": "Four application ports are reachable from the internet.",
        "why_it_matters": "They sit beside the reverse proxy rather than behind it.",
        "how_determined": "ss -tlnp on the host over an existing session.",
        "risk_of_inaction": "Listeners are exposed without the proxy's controls.",
        "remediation": {
            "summary": "Bind each application to loopback and publish through the proxy.",
            "difficulty": "low",
            "expected_outcome": "Only 22, 80 and 443 remain reachable.",
        },
    }
    base.update(overrides)
    return base


def _collection(tmp_path: Path, posture: dict[str, Any] | None) -> Path:
    (tmp_path / "vulns.json").write_text(json.dumps(_VULNS), encoding="utf-8")
    if posture is not None:
        (tmp_path / "posture.json").write_text(json.dumps(posture), encoding="utf-8")
    return tmp_path


async def test_posture_document_is_optional(tmp_path: Path) -> None:
    """Most collections will not have one; its absence is not an error."""
    analysis = await analyze_collection(_collection(tmp_path, None))
    assert analysis.posture_findings == ()


async def test_observations_become_findings(tmp_path: Path) -> None:
    directory = _collection(tmp_path, {"observations": [_observation()]})
    analysis = await analyze_collection(directory)
    assert len(analysis.posture_findings) == 1
    finding = analysis.posture_findings[0]
    assert finding.what_happened.startswith("Four application ports")
    assert finding.severity == "high"


async def test_findings_are_raised_through_the_store_not_constructed(tmp_path: Path) -> None:
    """A store-issued finding has a real id and version; a hand-built one would not."""
    directory = _collection(tmp_path, {"observations": [_observation()]})
    analysis = await analyze_collection(directory)
    finding = analysis.posture_findings[0]
    assert finding.id.startswith("fnd_")
    assert finding.status
    assert finding.version >= 1


async def test_each_finding_links_a_distinct_evidence_record(tmp_path: Path) -> None:
    observations = [
        _observation(observation_id=f"obs-{index}", check=f"check-{index}") for index in range(3)
    ]
    analysis = await analyze_collection(_collection(tmp_path, {"observations": observations}))
    evidence_ids = [finding.evidence_ids[0] for finding in analysis.posture_findings]
    assert len(analysis.posture_findings) == 3
    assert all(evidence_id.startswith("evd_") for evidence_id in evidence_ids)
    assert len(set(evidence_ids)) == 3


async def test_posture_findings_are_ordered_by_score(tmp_path: Path) -> None:
    observations = [
        _observation(observation_id="obs-low", check="c-low", severity="low", severity_score=10.0),
        _observation(observation_id="obs-hi", check="c-hi", severity="high", severity_score=90.0),
        _observation(
            observation_id="obs-mid", check="c-mid", severity="medium", severity_score=50.0
        ),
    ]
    analysis = await analyze_collection(_collection(tmp_path, {"observations": observations}))
    scores = [finding.severity_score for finding in analysis.posture_findings]
    assert scores == sorted(scores, reverse=True)


async def test_a_refused_posture_document_fails_the_run(tmp_path: Path) -> None:
    """Silently skipping a malformed document would report a clean collection."""
    broken = {"observations": [_observation(what_happened="")]}
    with pytest.raises(ReportInputError, match="posture document was refused"):
        await analyze_collection(_collection(tmp_path, broken))


async def test_posture_document_is_fingerprinted_as_a_source(tmp_path: Path) -> None:
    directory = _collection(tmp_path, {"observations": [_observation()]})
    _, _, posture_document, _, sources, _ = load_collection_documents(directory)
    assert posture_document is not None
    names = [source.name for source in sources]
    assert "posture.json" in names
    digest = next(source.sha256 for source in sources if source.name == "posture.json")
    assert len(digest) == 64


async def test_fingerprint_changes_when_the_posture_document_changes(tmp_path: Path) -> None:
    directory = _collection(tmp_path, {"observations": [_observation()]})
    _, _, _, _, _, first = load_collection_documents(directory)
    (directory / "posture.json").write_text(
        json.dumps({"observations": [_observation(severity_score=71.0)]}), encoding="utf-8"
    )
    _, _, _, _, _, second = load_collection_documents(directory)
    assert first != second


async def test_report_renders_the_posture_section(tmp_path: Path) -> None:
    directory = _collection(tmp_path, {"observations": [_observation()]})
    rendered = render_findings_report(await analyze_collection(directory))
    assert "Posture observations (1)" in rendered
    assert "Four application ports are reachable" in rendered
    assert "ss -tlnp on the host" in rendered


async def test_report_omits_the_section_when_no_posture_was_handed_in(tmp_path: Path) -> None:
    """An empty section would imply posture was checked and found clean."""
    rendered = render_findings_report(await analyze_collection(_collection(tmp_path, None)))
    assert "Posture observations" not in rendered


async def test_posture_findings_do_not_inflate_the_vulnerability_count(tmp_path: Path) -> None:
    """The zero in '0 findings' means no representable vulnerability record. Keep it."""
    directory = _collection(tmp_path, {"observations": [_observation()]})
    analysis = await analyze_collection(directory)
    assert analysis.findings == ()
    assert analysis.scanner_matches == 0
    assert len(analysis.posture_findings) == 1
