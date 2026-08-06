"""ECR-0105: the disclosure model reaches the rendered report.

ECR-0104 built the levels and nothing consumed them, which is the dead-code criticism
this project keeps making of itself. These witnesses exist so that stays fixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aqelyn.reporting.analyze import analyze_collection
from aqelyn.reporting.cli import _parser, main
from aqelyn.reporting.disclosure import Mode
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
        "severity_score": 70.0,
        "observed": {"public_ports": [8080]},
        "what_happened": "One port is reachable from beyond this machine.",
        "why_it_matters": "It sits beside the reverse proxy rather than behind it.",
        "how_determined": "Parsed ss -tlnH on the host.",
        "risk_of_inaction": "A local-only service is exposed.",
        "remediation": {
            "summary": "Bind it to loopback.",
            "difficulty": "low",
            "expected_outcome": "Only intended ports stay reachable.",
        },
    }
    base.update(overrides)
    return base


def _collection(tmp_path: Path, count: int = 1) -> Path:
    (tmp_path / "vulns.json").write_text(json.dumps(_VULNS), encoding="utf-8")
    observations = [
        _observation(observation_id=f"obs-{index}", check=f"check-{index}")
        for index in range(count)
    ]
    (tmp_path / "posture.json").write_text(
        json.dumps({"observations": observations}), encoding="utf-8"
    )
    return tmp_path


async def _render(tmp_path: Path, mode: Mode, count: int = 1) -> str:
    analysis = await analyze_collection(_collection(tmp_path, count))
    return render_findings_report(analysis, mode=mode)


async def test_all_six_levels_reach_the_html(tmp_path: Path) -> None:
    rendered = await _render(tmp_path, Mode.ENTERPRISE)
    assert rendered.count('class="level"') == 6


async def test_each_level_renders_its_charter_question(tmp_path: Path) -> None:
    rendered = await _render(tmp_path, Mode.EXPERT)
    for question in (
        "What is the problem?",
        "Why does it matter?",
        "What data proves it?",
        "What exact configuration caused it?",
        "What should be done?",
        "What changed and when?",
    ):
        assert question in rendered


async def test_each_level_renders_its_charter_name(tmp_path: Path) -> None:
    """Found GREEN by ECR-0105/M7: the names were rendered and nothing witnessed them."""
    rendered = await _render(tmp_path, Mode.EXPERT)
    for name in (
        "Summary",
        "Explanation",
        "Evidence",
        "Technical Detail",
        "Remediation",
        "Audit Trail",
    ):
        assert f">{name}<" in rendered


async def test_home_mode_opens_fewer_levels_than_enterprise(tmp_path: Path) -> None:
    home = (await _render(tmp_path, Mode.HOME)).count('class="level" open')
    enterprise = (await _render(tmp_path, Mode.ENTERPRISE)).count('class="level" open')
    assert home < enterprise


async def test_every_mode_still_renders_every_level(tmp_path: Path) -> None:
    """UX-008 changes what opens, never what exists. Collapsed is not removed."""
    for mode in Mode:
        rendered = await _render(tmp_path, mode)
        assert rendered.count('class="level"') == 6


async def test_levels_use_details_so_depth_survives_without_script(tmp_path: Path) -> None:
    """Principle 5's expert depth must not depend on JavaScript being enabled."""
    rendered = await _render(tmp_path, Mode.HOME)
    assert "<details" in rendered
    assert rendered.count("<details") >= 6


async def test_the_mode_is_stated_in_the_report(tmp_path: Path) -> None:
    """A reader should know which register they are being shown.

    Asserted on the rendered element, not on the bare word: "home" appears in plenty of
    prose, so a substring check would pass for the wrong reason.
    """
    for mode in Mode:
        rendered = await _render(tmp_path, mode)
        assert f"<strong>{mode.value}</strong> mode" in rendered


async def test_levels_scale_with_findings(tmp_path: Path) -> None:
    rendered = await _render(tmp_path, Mode.ENTERPRISE, count=3)
    assert rendered.count('class="level"') == 18


async def test_no_posture_document_renders_no_levels(tmp_path: Path) -> None:
    (tmp_path / "vulns.json").write_text(json.dumps(_VULNS), encoding="utf-8")
    rendered = render_findings_report(await analyze_collection(tmp_path))
    assert 'class="level"' not in rendered


async def test_the_technical_body_reaches_the_html_not_only_the_heading(
    tmp_path: Path,
) -> None:
    """A rendered level that shows its question but not its answer is a heading, not a level."""
    rendered = await _render(tmp_path, Mode.EXPERT)
    assert "public_ports" in rendered
    assert "Bind it to loopback." in rendered
    assert "Parsed ss -tlnH on the host." in rendered


def test_the_cli_actually_passes_the_mode_through(tmp_path: Path) -> None:
    """The flag has to reach the renderer, not merely parse."""
    collection = _collection(tmp_path)
    output = tmp_path / "report.html"
    counts = {}
    for mode in (Mode.HOME, Mode.ENTERPRISE):
        assert main([str(collection), "--mode", mode.value, "--output", str(output)]) == 0
        counts[mode] = output.read_text(encoding="utf-8").count('class="level" open')
    assert counts[Mode.HOME] < counts[Mode.ENTERPRISE]


def test_cli_offers_every_charter_mode() -> None:
    for mode in Mode:
        assert _parser().parse_args(["dir", "--mode", mode.value]).mode == mode.value


def test_cli_defaults_to_enterprise() -> None:
    assert _parser().parse_args(["dir"]).mode == Mode.ENTERPRISE.value
