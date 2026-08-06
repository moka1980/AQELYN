"""Self-contained self-scan runner — the customer-facing Linux entry point.

`aqelyn collect` writes a collection directory for the pipeline; this wraps the same
collector in a friendly one-shot: it scans the host, writes ``posture.json`` and a
self-contained ``report.html`` a person can open, and prints a plain summary. It is what the
downloadable ``aqelyn-selfscan.pyz`` runs (built by ``tools/build_selfscan_pyz.py``), so the
shipped download is exactly this code — no hand-copied second implementation to drift.

Stdlib only, like the rest of ``aqelyn.collect``, so the zipapp needs no dependencies.
"""

from __future__ import annotations

import html as _html
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqelyn.collect.checks import observations_for
from aqelyn.collect.host import CommandRunner, read_host_facts

_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_COLOR = {
    "critical": "#c62828",
    "high": "#e08a00",
    "medium": "#0b6fc4",
    "low": "#657790",
    "info": "#657790",
}

_STYLE = """
 body{margin:0;background:#060b15;color:#e7eef8;
      font:15px/1.6 system-ui,-apple-system,Segoe UI,Arial,sans-serif}
 .top{background:linear-gradient(160deg,#0b2440,#04182e);padding:26px 22px;
      border-bottom:2px solid #0b8ce0}
 .top h1{margin:0;font-size:22px;letter-spacing:-.02em}
 .top p{margin:4px 0 0;color:#8fb2d2;font-size:13px}
 main{max-width:820px;margin:0 auto;padding:22px}
 .f{display:grid;grid-template-columns:96px 1fr;gap:14px;padding:16px;
    border:1px solid #1e2f49;border-radius:10px;background:#0d1626;margin-bottom:12px}
 .sv{font:700 10px/1.7 ui-monospace,monospace;letter-spacing:.08em;color:var(--c);
     align-self:start;border:1px solid var(--c);border-radius:100px;text-align:center;padding:2px 0}
 h3{margin:0 0 5px;font-size:15.5px} .w{margin:0 0 6px;color:#aab9d0;font-size:13.5px}
 .d{margin:0;color:#7e8fa8;font-size:12px;font-family:ui-monospace,monospace}
 .fix{margin:8px 0 0;color:#3fc169;font-size:13px}
 footer{max-width:820px;margin:0 auto;padding:0 22px 30px;color:#7e8fa8;font-size:12.5px}
"""


def order_key(observation: Mapping[str, Any]) -> int:
    """Severity rank; unknown severities sort last."""

    return _ORDER.get(str(observation.get("severity", "info")), 9)


def _card(observation: Mapping[str, Any]) -> str:
    sev = str(observation.get("severity", "info"))
    color = _COLOR.get(sev, "#657790")
    fix = str((observation.get("remediation") or {}).get("summary", ""))
    fix_html = f'<p class="fix">Fix: {_html.escape(fix)}</p>' if fix else ""
    what = _html.escape(str(observation.get("what_happened", "")))
    why = _html.escape(str(observation.get("why_it_matters", "")))
    how = _html.escape(str(observation.get("how_determined", "")))
    return (
        f'<article class="f"><div class="sv" style="--c:{color}">{_html.escape(sev.upper())}</div>'
        f'<div><h3>{what}</h3><p class="w">{why}</p>'
        f'<p class="d">Determined by: {how}</p>{fix_html}</div></article>'
    )


def render_report(
    subject: str,
    os_name: str | None,
    observations: Sequence[Mapping[str, Any]],
    when: str,
) -> str:
    """A self-contained dark report a person can open with no network access.

    Every value is HTML-escaped: the observations describe a real machine and must never be
    able to inject markup into the page that shows them.
    """

    body = "\n".join(_card(o) for o in observations) or "<p>Nothing was flagged.</p>"
    header = (
        f"{_html.escape(os_name or 'unknown OS')} · {len(observations)} observations · "
        f"{_html.escape(when)} · read-only, nothing left this machine"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>AQELYN self-scan — {_html.escape(subject)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f'<div class="top"><h1>AQELYN self-scan · {_html.escape(subject)}</h1>'
        f"<p>{header}</p></div><main>{body}</main>"
        "<footer>Produced by the AQELYN host collector. Run again with <code>sudo</code> to let "
        "the firewall and SSH checks read the true values. This report was generated entirely on "
        "your machine.</footer></body></html>"
    )


def run(output_dir: Path, *, runner: CommandRunner | None = None) -> list[dict[str, Any]]:
    """Scan the host, write ``posture.json`` + ``report.html`` into ``output_dir``, return findings.

    ``runner`` is injectable so tests can drive a fake host without touching the real machine.
    """

    facts = read_host_facts() if runner is None else read_host_facts(runner)
    subject = facts.hostname or "this-machine"
    observations = sorted(observations_for(facts, subject_ref=subject), key=order_key)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "posture.json").write_text(
        json.dumps({"observations": observations}, indent=2), encoding="utf-8"
    )
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    (output_dir / "report.html").write_text(
        render_report(subject, facts.os_name, observations, when), encoding="utf-8"
    )
    return list(observations)


def main(argv: Sequence[str] | None = None) -> int:
    out = Path("aqelyn-scan")
    observations = run(out)
    subject = next(
        (str((o.get("subject") or {}).get("ref", "")) for o in observations if o.get("subject")),
        "this-machine",
    )
    print(f"\n  AQELYN self-scan — {subject}\n  " + "=" * 44)
    for observation in observations:
        sev = str(observation.get("severity", "info")).upper()
        print(f"  [{sev:8}] {observation.get('what_happened', '')}")
    print("\n  Read-only. Nothing was sent anywhere.")
    print(f"  Findings : {out / 'posture.json'}")
    print(f"  Report   : open {out / 'report.html'} in your browser\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
