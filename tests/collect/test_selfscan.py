"""ECR-0113: the downloadable self-scan is the shipped collector, and it stays that way.

The customer download (aqelyn.com/scan) was built ad-hoc once; a collector change could rot
it silently. These witnesses assert the runner produces a valid collection + report, and that
the zipapp build produces a runnable artifact — so breakage fails a test instead of a customer.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from tools.build_selfscan_pyz import build

from aqelyn.collect.host import CommandRunner
from aqelyn.collect.selfscan import main, order_key, render_report, run


def _runner(table: dict[str, tuple[int, str]]) -> CommandRunner:
    def r(argv: Sequence[str]) -> tuple[int, str] | None:
        return table.get(argv[0])

    return r


def _fake(tmp_path: Path) -> CommandRunner:
    return _runner(
        {
            "hostname": (0, "test-host\n"),
            "uname": (0, "6.0.0\n"),
            "ss": (0, "LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*\n"),  # one public listener
        }
    )


# --- the runner produces a valid collection + report ---------------------------------------


def test_run_writes_a_valid_posture_document(tmp_path: Path) -> None:
    from aqelyn.reporting.posture import validate_posture_shape

    obs = run(tmp_path, runner=_fake(tmp_path))
    doc = json.loads((tmp_path / "posture.json").read_text(encoding="utf-8"))
    # The uploaded/produced document must satisfy the platform's own validator.
    assert validate_posture_shape(doc)
    assert any(o["check"] == "listening_sockets_public" for o in obs)


def test_run_writes_a_report_containing_the_findings(tmp_path: Path) -> None:
    obs = run(tmp_path, runner=_fake(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<!doctype html>" in html
    import html as _h
    for o in obs:
        assert _h.escape(o["what_happened"]) in html


def test_findings_are_ordered_by_severity() -> None:
    rows = [{"severity": "info"}, {"severity": "high"}, {"severity": "medium"}]
    assert [r["severity"] for r in sorted(rows, key=order_key)] == ["high", "medium", "info"]


def test_the_report_escapes_observation_text() -> None:
    """Observation text describes a real machine; it must never inject markup."""
    html = render_report(
        "host", "OS", [{"severity": "high", "what_happened": "<script>x</script>"}], "now"
    )
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_an_empty_scan_reports_nothing_flagged() -> None:
    html = render_report("host", "OS", [], "now")
    assert "Nothing was flagged." in html


def test_main_runs_and_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # main() scans the real host read-only; we only assert it completes and writes output.
    assert main([]) == 0
    assert (tmp_path / "aqelyn-scan" / "posture.json").is_file()
    assert (tmp_path / "aqelyn-scan" / "report.html").is_file()


# --- the zipapp build produces a runnable artifact -----------------------------------------


def test_build_produces_a_runnable_zipapp(tmp_path: Path) -> None:
    pyz = build(tmp_path / "aqelyn-selfscan.pyz")
    assert pyz.is_file()
    assert pyz.stat().st_size > 0
    # Run it in a fresh process from a scratch cwd; it must scan and write a valid collection.
    workdir = tmp_path / "run"
    workdir.mkdir()
    result = subprocess.run(
        [sys.executable, str(pyz)], cwd=workdir, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    doc = json.loads((workdir / "aqelyn-scan" / "posture.json").read_text(encoding="utf-8"))
    assert "observations" in doc
