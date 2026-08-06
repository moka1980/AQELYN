"""Self-contained self-scan runner — the customer-facing Linux entry point.

`aqelyn collect` writes a collection directory for the pipeline; this wraps the same
collector in a friendly one-shot: it scans the host, writes ``posture.json`` (the technical
record, for the platform) and a plain-language ``report.html`` a non-technical person can
read in their own language, and prints a summary. It is what the downloadable
``aqelyn-selfscan.pyz`` runs (built by ``tools/build_selfscan_pyz.py``).

The report follows Charter Principle 2: it shows what is good as well as what needs a look,
in words anyone understands, in the reader's language (auto-selected from the computer's
locale; English fallback), with the technical detail available but not first. Stdlib only.
"""

from __future__ import annotations

import html as _html
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqelyn.collect.checks import observations_for
from aqelyn.collect.host import CommandRunner, read_host_facts
from aqelyn.collect.plain import LINUX_CHECK_IDS, UI, pick_language, plain_for_lang

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
 .top h1{margin:0;font-size:23px;letter-spacing:-.02em}
 .top p{margin:6px 0 0;color:#8fb2d2;font-size:13.5px}
 .sum{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
 .sum span{font-size:12.5px;font-weight:700;padding:5px 12px;border-radius:100px}
 .sum .g{background:#0d2a1a;color:#3fc169} .sum .a{background:#2c2410;color:#eeae4a}
 .sum .u{background:#131f34;color:#8fb2d2}
 main{max-width:780px;margin:0 auto;padding:22px}
 h2{font-size:14px;letter-spacing:.04em;color:#8fb2d2;text-transform:uppercase;
    margin:26px 0 12px;font-weight:700}
 .card{border:1px solid #1e2f49;border-radius:12px;background:#0d1626;
        padding:18px;margin-bottom:12px}
 .card.good{display:flex;gap:11px;align-items:flex-start;padding:14px 16px}
 .tick{color:#3fc169;font-weight:800;font-size:16px;line-height:1.3}
 .chip{font:700 10.5px/1.7 system-ui;letter-spacing:.05em;text-transform:uppercase;
       padding:2px 10px;border-radius:100px;color:var(--c);border:1px solid var(--c)}
 .hl{font-size:16.5px;font-weight:700;margin:10px 0 6px}
 .mean{color:#c7d4e6;margin:0 0 10px}
 .act{color:#e7eef8;margin:0} .act b{color:#3fc169}
 details{margin-top:12px;border-top:1px solid #1e2f49;padding-top:10px}
 summary{cursor:pointer;color:#7e8fa8;font-size:12.5px}
 .tech{color:#7e8fa8;font-size:12px;font-family:ui-monospace,monospace;
        margin:8px 0 0;white-space:pre-wrap}
 .good .g2{font-weight:600} .good .g3{color:#9fb0c6;font-size:13px}
 footer{max-width:780px;margin:0 auto;padding:6px 22px 30px;color:#7e8fa8;font-size:12.5px}
"""


def order_key(observation: Mapping[str, Any]) -> int:
    """Severity rank; unknown severities sort last."""

    return _ORDER.get(str(observation.get("severity", "info")), 9)


def _is_unmeasured(observation: Mapping[str, Any]) -> bool:
    observed = observation.get("observed")
    return bool(isinstance(observed, Mapping) and observed.get("unmeasured"))


def _finding_card(observation: Mapping[str, Any], lang: str) -> str:
    sev = str(observation.get("severity", "info"))
    ui = UI[lang]
    plain = plain_for_lang(str(observation.get("check", "")), lang)
    color = _COLOR.get(sev, "#657790")
    tech = "\n".join(
        s
        for s in (
            str(observation.get("what_happened", "")),
            "Determined by: " + str(observation.get("how_determined", "")),
        )
        if s.strip()
    )
    sev_word = ui["severity"].get(sev, sev)
    return (
        '<article class="card">'
        f'<span class="chip" style="--c:{color}">{_html.escape(sev_word)}</span>'
        f'<p class="hl">{_html.escape(plain["headline"])}</p>'
        f'<p class="mean">{_html.escape(plain["meaning"])}</p>'
        f'<p class="act"><b>{_html.escape(ui["action"])}</b> {_html.escape(plain["action"])}</p>'
        f"<details><summary>{_html.escape(ui['detail'])}</summary>"
        f'<p class="tech">{_html.escape(tech)}</p></details></article>'
    )


def _good_card(check: str, lang: str) -> str:
    plain = plain_for_lang(check, lang)
    return (
        '<article class="card good"><span class="tick">✓</span>'
        f'<span><span class="g2">{_html.escape(plain["good"])}</span></span></article>'
    )


def _unknown_card(observation: Mapping[str, Any], lang: str) -> str:
    ui = UI[lang]
    plain = plain_for_lang(str(observation.get("check", "")), lang)
    return (
        '<article class="card good"><span class="g3">•</span>'
        f'<span class="g3">{_html.escape(ui["cannot"])}: '
        f"{_html.escape(plain['headline'].lower())}. "
        f"{_html.escape(ui['runadmin'])}</span></article>"
    )


def render_report(
    subject: str,
    os_name: str | None,
    observations: Sequence[Mapping[str, Any]],
    when: str,
    passed: Sequence[str] = (),
    lang: str = "en",
) -> str:
    """Plain-language report in the reader's language: needs a look / good / could not read."""

    ui = UI[lang]
    findings = [o for o in observations if not _is_unmeasured(o)]
    unknown = [o for o in observations if _is_unmeasured(o)]
    findings.sort(key=order_key)

    parts = []
    if findings:
        parts.append(f"<h2>{_html.escape(ui['worth'])}</h2>")
        parts.extend(_finding_card(o, lang) for o in findings)
    if passed:
        parts.append(f"<h2>{_html.escape(ui['good'])}</h2>")
        parts.extend(_good_card(c, lang) for c in passed)
    if unknown:
        parts.append(f"<h2>{_html.escape(ui['unknown'])}</h2>")
        parts.extend(_unknown_card(o, lang) for o in unknown)
    body = "\n".join(parts) or "<p>—</p>"

    summary = (
        f'<div class="sum"><span class="g">{len(passed)} {_html.escape(ui["s_good"])}</span>'
        f'<span class="a">{len(findings)} {_html.escape(ui["s_worth"])}</span>'
        + (
            f'<span class="u">{len(unknown)} {_html.escape(ui["s_unknown"])}</span>'
            if unknown
            else ""
        )
        + "</div>"
    )
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>AQELYN — {_html.escape(ui['title'])} — {_html.escape(subject)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f'<div class="top"><h1>{_html.escape(ui["title"])} · {_html.escape(subject)}</h1>'
        f"<p>{_html.escape(os_name or 'this computer')} · {_html.escape(when)} · "
        f"{_html.escape(ui['readonly'])}</p>{summary}</div>"
        f"<main>{body}</main>"
        f"<footer>{_html.escape(ui['footer'])}</footer>"
        "</body></html>"
    )


def _detect_lang() -> str:
    return pick_language(os.environ.get("LC_ALL") or os.environ.get("LANG"))


def run(
    output_dir: Path, *, runner: CommandRunner | None = None, lang: str | None = None
) -> list[dict[str, Any]]:
    """Scan the host, write ``posture.json`` + a plain ``report.html``, return the findings."""

    facts = read_host_facts() if runner is None else read_host_facts(runner)
    language = lang or _detect_lang()
    subject = facts.hostname or "this-computer"
    observations = sorted(observations_for(facts, subject_ref=subject), key=order_key)
    seen = {str(o.get("check", "")) for o in observations}
    passed = [cid for cid in LINUX_CHECK_IDS if cid not in seen]

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "posture.json").write_text(
        json.dumps({"observations": observations}, indent=2), encoding="utf-8"
    )
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    (output_dir / "report.html").write_text(
        render_report(subject, facts.os_name, observations, when, passed, language),
        encoding="utf-8",
    )
    return list(observations)


def main(argv: Sequence[str] | None = None) -> int:
    lang = _detect_lang()
    ui = UI[lang]
    out = Path("aqelyn-scan")
    observations = run(out, lang=lang)
    findings = [o for o in observations if not _is_unmeasured(o)]
    subject = next(
        (str((o.get("subject") or {}).get("ref", "")) for o in observations if o.get("subject")),
        "this-computer",
    )
    print(f"\n  {ui['console_title']} — {subject}\n  " + "=" * 44)
    if not findings:
        print(f"  {ui['console_clean']}")
    for observation in findings:
        plain = plain_for_lang(str(observation.get("check", "")), lang)
        word = ui["severity"].get(str(observation.get("severity", "info")), "")
        print(f"  [{word:18}] {plain['headline']}")
    print(f"\n  {ui['readonly'].capitalize()}.")
    print(f"  open {out / 'report.html'}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
