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
    import html as _h

    obs = run(tmp_path, runner=_fake(tmp_path))
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<!doctype html>" in report
    findings = [o for o in obs if not (o.get("observed") or {}).get("unmeasured")]
    assert findings
    for o in findings:
        # a finding's raw text lives in the collapsed technical detail, HTML-escaped
        assert _h.escape(o["what_happened"]) in report


def test_findings_are_ordered_by_severity() -> None:
    rows = [{"severity": "info"}, {"severity": "high"}, {"severity": "medium"}]
    assert [r["severity"] for r in sorted(rows, key=order_key)] == ["high", "medium", "info"]


def test_the_report_escapes_observation_text() -> None:
    """Observation text describes a real machine; it must never inject markup."""
    html = render_report(
        "host",
        "OS",
        [{"severity": "high", "check": "x", "what_happened": "<script>x</script>"}],
        "now",
    )
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_an_empty_scan_has_no_worth_a_look_section() -> None:
    html = render_report("host", "OS", [], "now")
    assert "<h2>Worth a look</h2>" not in html
    assert "0 worth a look" in html


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


# --- ECR-0114: plain-language report + check/plain sync -------------------------------------


def test_every_emitted_check_has_plain_language(tmp_path: Path) -> None:
    """A new check without a plain-language entry would show the fallback — fail instead."""
    from aqelyn.collect.plain import PLAIN

    obs = run(tmp_path, runner=_fake(tmp_path))
    for o in obs:
        assert o["check"] in PLAIN, f"no plain-language entry for {o['check']}"


def test_linux_check_ids_all_have_plain_entries() -> None:
    from aqelyn.collect.plain import LINUX_CHECK_IDS, PLAIN

    for cid in LINUX_CHECK_IDS:
        assert cid in PLAIN


def test_report_shows_plain_headline_not_raw_jargon(tmp_path: Path) -> None:
    run(tmp_path, runner=_fake(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    # the plain headline is primary; the raw ss command only appears in the collapsed detail
    assert "can be reached over the network" in html
    assert "What to do:" in html
    assert "Show the technical detail" in html


def test_report_shows_a_looking_good_section(tmp_path: Path) -> None:
    """Charter Principle 2: show what is good, not only problems."""
    html = (
        (tmp_path / "report.html").read_text(encoding="utf-8")
        if (tmp_path / "report.html").exists()
        else ""
    )
    run(tmp_path, runner=_fake(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Looking good" in html
    assert "✓" in html


# --- ECR-0114 (i18n): the report speaks the reader's language -------------------------------------


def test_norwegian_locale_selects_norwegian() -> None:
    from aqelyn.collect.plain import pick_language

    assert pick_language("nb_NO.UTF-8") == "nb"
    assert pick_language("nn_NO") == "nb"
    assert pick_language("en_US") == "en"
    assert pick_language(None) == "en"


def test_report_renders_in_norwegian() -> None:
    obs = [
        {
            "severity": "high",
            "check": "listening_sockets_public",
            "what_happened": "x",
            "how_determined": "y",
        }
    ]
    html = render_report("host", "OS", obs, "now", passed=["host_firewall_active"], lang="nb")
    assert '<html lang="nb"' in html
    assert "Verdt å se på" in html  # section title
    assert "Hva du bør gjøre:" in html  # action label
    assert "Brannmuren er på" in html  # a passed check, in Norwegian


def test_every_check_has_norwegian_text() -> None:
    """A check with English but no Norwegian plain text would fall back silently — catch it."""
    from aqelyn.collect.plain import PLAIN, PLAIN_NB

    for cid in PLAIN:
        assert cid in PLAIN_NB, f"no Norwegian plain-language for {cid}"


def test_english_is_still_the_default(tmp_path: Path) -> None:
    obs = [
        {
            "severity": "high",
            "check": "listening_sockets_public",
            "what_happened": "x",
            "how_determined": "y",
        }
    ]
    html = render_report("host", "OS", obs, "now", lang="en")
    assert '<html lang="en"' in html
    assert "What to do:" in html
