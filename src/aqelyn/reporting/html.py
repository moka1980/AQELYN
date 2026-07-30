"""Self-contained, offline HTML renderer for P-001."""

from __future__ import annotations

import html
from collections.abc import Mapping
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from aqelyn.reporting.analyze import CollectionAnalysis, ReportFinding


def render_findings_report(analysis: CollectionAnalysis) -> str:
    """Render an operator report without external assets or network capability."""

    finding_html = "\n".join(_finding(item, index) for index, item in enumerate(analysis.findings))
    rejected_html = _rejected_matches(analysis)
    source_names = ", ".join(source.name for source in analysis.sources)
    high_attention = sum(
        item.priority.priority in {"immediate", "high"} for item in analysis.findings
    )
    exploited = sum(item.has_known_exploitation for item in analysis.findings)
    empty_state = (
        ""
        if analysis.findings
        else """
        <section class="empty-state">
          <h2>No representable findings</h2>
          <p>The handed-in scan produced no vulnerability record the platform could
          represent. Review the refused-input section; this is not a clean result.</p>
        </section>
        """
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="aqelyn-input-fingerprint" content="{analysis.input_fingerprint}">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';
                 img-src data:; connect-src 'none'; font-src 'none'; object-src 'none';
                 base-uri 'none'; form-action 'none'">
  <title>AQELYN findings report</title>
  <style>{_STYLES}</style>
</head>
<body>
  <header class="report-header">
    <div class="header-inner">
      <div>
        <p class="product-name">AQELYN</p>
        <h1>Findings report</h1>
        <p class="report-scope">
          Local operator report. Per-asset detail must stay on this machine.
        </p>
      </div>
      <dl class="report-meta">
        <div><dt>Observed</dt><dd>{_e(analysis.observed_at.isoformat())}</dd></div>
        <div><dt>Generated</dt><dd>{_e(analysis.generated_at.isoformat())}</dd></div>
        <div><dt>Inputs</dt><dd>{_e(source_names)}</dd></div>
      </dl>
    </div>
  </header>
  <main>
    <section class="summary-band" aria-label="Report summary">
      <div class="summary-stat">
        <span class="summary-value">{len(analysis.findings):,}</span>
        <span class="summary-label">Findings</span>
      </div>
      <div class="summary-stat attention">
        <span class="summary-value">{high_attention:,}</span>
        <span class="summary-label">High attention</span>
      </div>
      <div class="summary-stat exploited">
        <span class="summary-value">{exploited:,}</span>
        <span class="summary-label">Known exploited</span>
      </div>
      <div class="summary-stat unknown">
        <span class="summary-value">{analysis.unknown_factor_count:,}</span>
        <span class="summary-label">Unknown factors</span>
      </div>
      <div class="summary-stat refused">
        <span class="summary-value">{len(analysis.rejected_matches):,}</span>
        <span class="summary-label">Refused inputs</span>
      </div>
    </section>

    <section class="boundary-note">
      <strong>This report did not scan, patch, approve, or execute anything.</strong>
      It presents owner findings and advisory proposals from handed-in documents.
      Unknowns are excluded from scoring and remain visible beside each finding.
    </section>

    <section class="toolbar" aria-label="Finding controls">
      <label class="search-control">
        <span>Search</span>
        <input id="finding-search" type="search" placeholder="CVE, component, or reason">
      </label>
      <label>
        <span>Priority</span>
        <select id="priority-filter">
          <option value="all">All priorities</option>
          <option value="immediate">Immediate</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="deferred">Deferred</option>
        </select>
      </label>
      <label>
        <span>Knowledge</span>
        <select id="knowledge-filter">
          <option value="all">All findings</option>
          <option value="unknown">Has unknowns</option>
          <option value="complete">No unknowns</option>
        </select>
      </label>
      <button id="expand-all" type="button">Expand derivations</button>
      <p id="visible-count" class="visible-count" aria-live="polite">
        Showing {len(analysis.findings):,} of {len(analysis.findings):,}
      </p>
    </section>

    {empty_state}
    <section id="findings" class="findings" aria-label="Findings">
      {finding_html}
    </section>
    {rejected_html}
  </main>
  <footer>
    <p>Generated from {analysis.scanner_matches:,} handed-in scanner matches;
       {analysis.represented_records:,} unique records were representable.</p>
    <p>This is the local findings boundary. It is not the shareable density report.</p>
  </footer>
  <script>{_SCRIPT}</script>
</body>
</html>
"""


def _finding(item: ReportFinding, index: int) -> str:
    finding = item.finding
    priority = item.priority
    vulnerability = item.vulnerability
    unknowns = [
        (name, factor)
        for name, factor in priority.factors.items()
        if isinstance(factor, Mapping) and factor.get("status") == "unknown"
    ]
    knowns = [
        (name, factor)
        for name, factor in priority.factors.items()
        if isinstance(factor, Mapping) and factor.get("status") == "known"
    ]
    search_text = " ".join(
        [
            finding.title,
            vulnerability.cve_id,
            vulnerability.asset_ref.ref_id,
            *(str(factor.get("reason", "")) for _, factor in unknowns),
        ]
    ).lower()
    unknown_html = (
        "\n".join(
            f"""
            <li>
              <strong>{_e(_label(name))}</strong>
              <span>{_e(str(factor.get("reason", "No reason recorded.")))}</span>
              <small>{_e(_cause_label(factor.get("unknown_cause")))}</small>
            </li>
            """
            for name, factor in unknowns
        )
        if unknowns
        else '<li class="known-complete">No scoring factor is unknown for this finding.</li>'
    )
    surcharge = priority.uncertainty_surcharge
    (
        factor_contribution_text,
        known_points_text,
        surcharge_points_text,
        total_points_text,
    ) = _display_score_arithmetic(
        factors=priority.factors,
        total_points=priority.score,
        uncertainty_points=surcharge.contribution,
    )
    factor_rows = "\n".join(
        _factor_row(
            name,
            factor,
            contribution_text=factor_contribution_text.get(name),
        )
        for name, factor in priority.factors.items()
        if isinstance(factor, Mapping)
    )
    surcharge_row = _uncertainty_surcharge_row(
        rate=surcharge.rate,
        unknown_weight=surcharge.unknown_weight,
        contribution_text=surcharge_points_text,
    )
    derivation_steps = "\n".join(
        f"""
        <li>
          <div class="step-heading">
            <span>Step {step.seq}</span>
            <strong>{_e(_operation_label(step.op))}</strong>
          </div>
          <p>{_e(step.note)}</p>
          <small>Inputs: {_e(", ".join(step.input_refs))}</small>
        </li>
        """
        for step in priority.derivation.steps
    )
    known_names = ", ".join(_label(name) for name, _ in knowns) or "none"
    excluded_names = ", ".join(_label(name) for name, _ in unknowns) or "none"
    remediation_steps = "\n".join(f"<li>{_e(step)}</li>" for step in finding.remediation.steps)
    priority_class = _priority_class(priority.priority)
    score_width = max(0.0, min(100.0, priority.score))
    escalation_html = _escalation_annotation(
        first_seen=finding.severity_score,
        current=finding.current_severity_score,
    )
    knowledge = "unknown" if unknowns else "complete"
    exploited = "yes" if item.has_known_exploitation else "no"
    return f"""
    <article class="finding" data-finding data-priority="{_e(priority.priority)}"
             data-knowledge="{knowledge}" data-exploited="{exploited}"
             data-search="{_e(search_text)}">
      <div class="finding-lead">
        <div class="finding-title">
          <div class="finding-kicker">
            <span class="priority {priority_class}">{_e(priority.priority.title())}</span>
            <span class="finding-number">Finding {index + 1}</span>
          </div>
          <h2>{_e(finding.title)}</h2>
          <p class="asset-ref">{_e(vulnerability.asset_ref.ref_id)}</p>
        </div>
        <div class="finding-score">
          <div class="score-block" aria-label="Priority score {total_points_text} out of 100">
            <strong>{total_points_text}</strong>
            <span>of 100</span>
            <div class="score-track"><span style="width:{score_width:.3f}%"></span></div>
          </div>
          {escalation_html}
        </div>
      </div>

      <div class="finding-body">
        <section class="claim-section">
          <h3>What is the problem?</h3>
          <p>{_e(finding.what_happened)}</p>
          <p>{_e(finding.why_it_matters)}</p>
        </section>

        <section class="unknown-section">
          <div class="section-heading">
            <h3>What we do not know</h3>
            <span>{len(unknowns)} excluded</span>
          </div>
          <ul>{unknown_html}</ul>
        </section>

        <section class="factor-section">
          <h3>Why this priority?</h3>
          <p class="calculation-summary">
            Known factors keep their configured share:
            <strong>{_e(known_names)}</strong>. Unknown factors receive no factor weight:
            <strong>{_e(excluded_names)}</strong>; their raw weight informs the separate
            uncertainty surcharge.
          </p>
          <p class="calculation-total">
            <strong>{known_points_text}</strong> known-factor points +
            <strong>{surcharge_points_text}</strong> uncertainty points =
            <strong>{total_points_text}</strong> total points.
          </p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Factor</th><th>Status</th><th>Signal</th><th>Weight</th>
                  <th>Contribution</th><th>Reason</th>
                </tr>
              </thead>
              <tbody>{factor_rows}{surcharge_row}</tbody>
            </table>
          </div>
          <details class="derivation">
            <summary>View derivation</summary>
            <p class="derivation-intro">
              Engine {_e(priority.derivation.engine_version)}, model
              {priority.derivation.model_version}. The steps below replay to
              {total_points_text}/100.
            </p>
            <ol>{derivation_steps}</ol>
          </details>
        </section>

        <section class="proposal-section">
          <h3>Proposed next steps</h3>
          <p class="action-boundary">
            <strong>No action was taken.</strong> Human approval is required before any
            response workflow can execute.
          </p>
          <p>{_e(finding.remediation.summary)}</p>
          <ol>{remediation_steps}</ol>
          <p><strong>Expected outcome:</strong> {_e(finding.remediation.expected_outcome)}</p>
        </section>
      </div>
    </article>
    """


def _escalation_annotation(*, first_seen: float, current: float | None) -> str:
    # P-002 dormancy: aqelyn-report uses a fresh store per run, so shipped reports cannot
    # reach this branch until findings persist. Tests exercise the real re-emission path.
    if current is None or current == first_seen:
        return ""
    current_text = f"{current * 100.0:.1f}"
    return f"""
    <aside class="severity-escalation" data-severity-escalation>
      <p>
        This priority is the severity recorded when the finding was first raised.
        Its current severity is
        <strong data-current-severity="{current_text}">{current_text}</strong>, which does
        not change the priority or its position in this list.
      </p>
    </aside>
    """


def _factor_row(
    name: str,
    factor: Mapping[str, Any],
    *,
    contribution_text: str | None,
) -> str:
    status = str(factor.get("status", "unknown"))
    reason = str(factor.get("reason", "No reason recorded."))
    source = str(factor.get("source", "No source recorded."))
    if status == "unknown":
        signal = "Not scored"
        weight = "Excluded"
        contribution = "0 points"
        row_class = "factor-unknown"
    else:
        if contribution_text is None:
            raise ValueError(f"known factor {name!r} has no displayed contribution")
        signal = f"{_number(factor.get('value')) * 100:.1f}/100"
        weight = f"{_number(factor.get('weight')) * 100:.1f}%"
        contribution = f"{contribution_text} points"
        row_class = "factor-known"
    return f"""
    <tr class="{row_class}">
      <th scope="row">
        <span>{_e(_label(name))}</span>
        <small>{_e(source)}</small>
      </th>
      <td data-label="Status"><span class="status {status}">{_e(status.title())}</span></td>
      <td data-label="Signal">{signal}</td>
      <td data-label="Weight">{weight}</td>
      <td data-label="Contribution">{contribution}</td>
      <td data-label="Reason">{_e(reason)}</td>
    </tr>
    """


def _uncertainty_surcharge_row(
    *,
    rate: float,
    unknown_weight: float,
    contribution_text: str,
) -> str:
    status = "Applied" if unknown_weight > 0.0 else "Not applied"
    return f"""
    <tr class="factor-surcharge">
      <th scope="row">
        <span>Uncertainty surcharge</span>
        <small>EA-0024 typed unknown policy</small>
      </th>
      <td data-label="Status"><span class="status">{status}</span></td>
      <td data-label="Signal">u = {rate:.2f}</td>
      <td data-label="Weight">{unknown_weight * 100.0:.1f}% unknown</td>
      <td data-label="Contribution">{contribution_text} points</td>
      <td data-label="Reason">
        Unknown factors remain excluded individually; their retained raw weight contributes
        only through this separate surcharge.
      </td>
    </tr>
    """


def _display_score_arithmetic(
    *,
    factors: Mapping[str, Any],
    total_points: float,
    uncertainty_points: float,
) -> tuple[dict[str, str], str, str, str]:
    """Round displayed terms as one reconciled largest-remainder allocation."""

    total = Decimal(f"{total_points:.1f}")
    uncertainty = Decimal(f"{uncertainty_points:.1f}")
    known = total - uncertainty
    if known < 0:
        raise ValueError("displayed uncertainty exceeds the displayed score")

    raw_contributions = [
        (
            name,
            Decimal(str(_number(factor.get("contribution")))) * Decimal(100),
        )
        for name, factor in factors.items()
        if isinstance(factor, Mapping) and factor.get("status") == "known"
    ]
    target_tenths = int(known * 10)
    raw_total = sum((value for _, value in raw_contributions), start=Decimal())
    if raw_total == 0:
        if target_tenths != 0:
            raise ValueError("nonzero displayed known subtotal has no factor contributions")
        allocations = [0 for _ in raw_contributions]
    else:
        exact_tenths = [
            value * Decimal(target_tenths) / raw_total for _, value in raw_contributions
        ]
        allocations = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact_tenths]
        remaining = target_tenths - sum(allocations)
        if not 0 <= remaining < len(allocations):
            raise ValueError("displayed factor contributions cannot be reconciled")
        by_largest_remainder = sorted(
            range(len(exact_tenths)),
            key=lambda index: (
                -(exact_tenths[index] - Decimal(allocations[index])),
                index,
            ),
        )
        for index in by_largest_remainder[:remaining]:
            allocations[index] += 1

    displayed_factors = {
        name: f"{Decimal(tenths) / Decimal(10):.1f}"
        for (name, _), tenths in zip(raw_contributions, allocations, strict=True)
    }
    return (
        displayed_factors,
        f"{known:.1f}",
        f"{uncertainty:.1f}",
        f"{total:.1f}",
    )


def _rejected_matches(analysis: CollectionAnalysis) -> str:
    if not analysis.rejected_matches:
        return ""
    reason_counts: dict[str, int] = {}
    for rejected in analysis.rejected_matches:
        reason_counts[rejected.reason] = reason_counts.get(rejected.reason, 0) + 1
    rows = "\n".join(
        f"<tr><td>{count:,}</td><td>{_e(reason)}</td></tr>"
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return f"""
    <section class="refused-section">
      <div>
        <p class="eyebrow">Input coverage</p>
        <h2>{len(analysis.rejected_matches):,} scanner matches were refused</h2>
        <p>These inputs are not findings and were not treated as clean. The shipped model
        could not represent them without guessing.</p>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Count</th><th>Reason</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    """


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _cause_label(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "Cause not classified"
    return f"Cause: {value.replace('_', ' ')}"


def _operation_label(value: str) -> str:
    labels = {
        "select_claims": "Select cited owner records",
        "weigh": "Compose available factors",
        "mission_weight": "Emit the replayable score",
        "vulnerability_priority_score": "Compose factors and uncertainty",
    }
    return labels.get(value, _label(value))


def _priority_class(value: str) -> str:
    return value if value in {"immediate", "high", "medium", "low", "deferred"} else "deferred"


_STYLES = """
:root {
  color-scheme: light;
  --ink: #18201d;
  --muted: #5c6862;
  --line: #d7dfdb;
  --paper: #ffffff;
  --canvas: #f2f5f3;
  --teal: #087f72;
  --teal-dark: #075e55;
  --amber: #a86400;
  --red: #b42318;
  --blue: #2457a7;
  --charcoal: #202825;
  --soft-amber: #fff7e8;
  --soft-teal: #eaf8f5;
  --soft-blue: #eef4ff;
}
* { box-sizing: border-box; }
html { background: var(--canvas); }
body {
  margin: 0;
  color: var(--ink);
  background: var(--canvas);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
    sans-serif;
  font-size: 15px;
  line-height: 1.55;
  letter-spacing: 0;
}
button, input, select { font: inherit; letter-spacing: 0; }
.report-header {
  color: #fff;
  background: var(--charcoal);
  border-bottom: 4px solid var(--teal);
}
.header-inner {
  width: min(1440px, calc(100% - 40px));
  margin: 0 auto;
  padding: 30px 0 28px;
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 36px;
}
.product-name, .eyebrow {
  margin: 0 0 4px;
  color: #70d4c7;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: 30px; line-height: 1.15; }
.report-scope { margin: 8px 0 0; color: #d4dfda; }
.report-meta {
  margin: 0;
  display: grid;
  gap: 5px;
  min-width: min(100%, 480px);
}
.report-meta div {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr);
  gap: 12px;
}
.report-meta dt { color: #9fb0a8; }
.report-meta dd { margin: 0; overflow-wrap: anywhere; }
main, footer {
  width: min(1440px, calc(100% - 40px));
  margin: 0 auto;
}
.summary-band {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  background: var(--paper);
  border: 1px solid var(--line);
  border-top: 0;
}
.summary-stat {
  min-height: 94px;
  padding: 18px 20px;
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.summary-stat:last-child { border-right: 0; }
.summary-value { font-size: 27px; font-weight: 800; line-height: 1; }
.summary-label { margin-top: 7px; color: var(--muted); font-size: 13px; }
.summary-stat.attention { border-top: 3px solid var(--amber); }
.summary-stat.exploited { border-top: 3px solid var(--red); }
.summary-stat.unknown { border-top: 3px solid var(--blue); }
.summary-stat.refused { border-top: 3px solid #73510d; }
.boundary-note {
  margin: 22px 0 0;
  padding: 14px 18px;
  background: var(--soft-teal);
  border-left: 4px solid var(--teal);
}
.toolbar {
  margin: 22px 0 18px;
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 180px 180px auto auto;
  gap: 12px;
  align-items: end;
}
.toolbar label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; }
.toolbar input, .toolbar select, .toolbar button {
  min-height: 42px;
  border: 1px solid #b9c5bf;
  border-radius: 4px;
  background: var(--paper);
  color: var(--ink);
  padding: 8px 11px;
}
.toolbar input:focus, .toolbar select:focus, .toolbar button:focus {
  outline: 3px solid #aadbd4;
  outline-offset: 1px;
}
.toolbar button { cursor: pointer; font-weight: 700; }
.visible-count { margin: 0 0 10px; color: var(--muted); text-align: right; }
.findings { display: grid; gap: 18px; }
.finding {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}
.finding[hidden] { display: none; }
.finding-lead {
  padding: 22px 24px 20px;
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 24px;
  border-bottom: 1px solid var(--line);
}
.finding-kicker { display: flex; align-items: center; gap: 10px; }
.finding-number { color: var(--muted); font-size: 12px; }
.priority, .status {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 800;
}
.priority.immediate { color: #fff; background: var(--red); }
.priority.high { color: #fff; background: #8a4200; }
.priority.medium { color: #5b3900; background: #ffd785; }
.priority.low { color: #17447e; background: #dceaff; }
.priority.deferred { color: #46524c; background: #e5ebe8; }
.finding h2 { margin: 9px 0 4px; font-size: 21px; line-height: 1.25; }
.asset-ref {
  max-width: 900px;
  margin: 0;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.finding-score {
  flex: 0 1 auto;
  min-width: 118px;
  display: flex;
  justify-content: flex-end;
  align-items: start;
  gap: 18px;
}
.score-block { flex: 0 0 118px; text-align: right; }
.score-block strong { display: block; font-size: 29px; line-height: 1; }
.score-block > span { color: var(--muted); font-size: 12px; }
.score-track {
  width: 118px;
  height: 6px;
  margin-top: 8px;
  background: #e6ece9;
  overflow: hidden;
}
.score-track span { display: block; height: 100%; background: var(--teal); }
.severity-escalation {
  width: min(280px, 30vw);
  padding: 10px 12px;
  color: #5b3900;
  background: var(--soft-amber);
  border-left: 3px solid var(--amber);
  text-align: left;
  font-size: 12px;
  line-height: 1.45;
}
.severity-escalation p { margin: 0; }
.severity-escalation strong { color: var(--red); }
.finding-body { padding: 0 24px 24px; }
.finding-body > section { padding: 20px 0; border-bottom: 1px solid var(--line); }
.finding-body > section:last-child { border-bottom: 0; padding-bottom: 0; }
h3 { margin: 0 0 8px; font-size: 16px; }
.finding-body p { margin: 7px 0; }
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 16px;
}
.section-heading span { color: var(--blue); font-size: 12px; font-weight: 800; }
.unknown-section { background: var(--soft-blue); margin: 0 -24px; padding: 20px 24px !important; }
.unknown-section ul { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 10px; }
.unknown-section li {
  display: grid;
  grid-template-columns: 140px 1fr auto;
  gap: 12px;
  align-items: start;
}
.unknown-section li strong { color: #173f77; }
.unknown-section li small { color: var(--muted); }
.unknown-section .known-complete { display: block; color: var(--teal-dark); }
.calculation-summary { color: var(--muted); }
.calculation-total { color: var(--ink); }
.table-wrap { width: 100%; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td {
  padding: 10px 9px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
thead th { color: var(--muted); font-size: 11px; text-transform: uppercase; }
tbody th { white-space: nowrap; }
tbody th span, tbody th small { display: block; }
tbody th small {
  margin-top: 3px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-weight: 400;
  white-space: normal;
  overflow-wrap: anywhere;
}
.status.known { color: var(--teal-dark); background: var(--soft-teal); }
.status.unknown { color: #17447e; background: #dceaff; }
.factor-unknown td:last-child { color: #244b7a; }
.factor-surcharge { background: var(--soft-teal); }
.factor-surcharge td:last-child { color: var(--teal-dark); }
.derivation { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 14px; }
.derivation summary { cursor: pointer; font-weight: 800; color: var(--teal-dark); }
.derivation-intro { color: var(--muted); }
.derivation ol { list-style: none; margin: 16px 0 0; padding: 0; }
.derivation li {
  position: relative;
  margin-left: 16px;
  padding: 0 0 18px 22px;
  border-left: 2px solid #b7d9d3;
}
.derivation li:last-child { padding-bottom: 0; }
.derivation li::before {
  content: "";
  position: absolute;
  width: 10px;
  height: 10px;
  left: -6px;
  top: 5px;
  border-radius: 50%;
  background: var(--teal);
}
.step-heading { display: flex; gap: 10px; align-items: baseline; }
.step-heading span { color: var(--muted); font-size: 12px; }
.derivation li p { margin: 4px 0; }
.derivation li small {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  overflow-wrap: anywhere;
}
.action-boundary {
  padding: 11px 13px;
  background: var(--soft-amber);
  border-left: 4px solid var(--amber);
}
.proposal-section ol { margin: 10px 0; padding-left: 22px; }
.refused-section {
  margin: 28px 0 0;
  padding: 24px;
  display: grid;
  grid-template-columns: minmax(260px, 0.8fr) minmax(0, 1.2fr);
  gap: 36px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 6px;
}
.refused-section .eyebrow { color: #73510d; }
.refused-section h2 { margin: 0; font-size: 21px; }
.empty-state { padding: 42px 24px; background: var(--paper); border: 1px solid var(--line); }
footer {
  margin-top: 28px;
  padding: 20px 0 36px;
  color: var(--muted);
  font-size: 12px;
  border-top: 1px solid var(--line);
}
footer p { margin: 4px 0; }
@media (max-width: 900px) {
  .header-inner { align-items: start; flex-direction: column; }
  .report-meta { width: 100%; }
  .summary-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-stat { border-bottom: 1px solid var(--line); }
  .toolbar { grid-template-columns: 1fr 1fr; }
  .search-control { grid-column: 1 / -1; }
  .visible-count { text-align: left; }
  .unknown-section li { grid-template-columns: 120px 1fr; }
  .unknown-section li small { grid-column: 2; }
  .refused-section { grid-template-columns: 1fr; }
}
@media (max-width: 700px) {
  .factor-section .table-wrap { overflow-x: visible; }
  .factor-section table,
  .factor-section tbody,
  .factor-section tr,
  .factor-section th,
  .factor-section td { display: block; width: 100%; }
  .factor-section thead { display: none; }
  .factor-section tr { padding: 14px 0; border-bottom: 1px solid var(--line); }
  .factor-section th,
  .factor-section td { border: 0; padding: 4px 0; white-space: normal; }
  .factor-section th { margin-bottom: 5px; }
  .factor-section td {
    display: grid;
    grid-template-columns: 108px minmax(0, 1fr);
    gap: 10px;
  }
  .factor-section td::before {
    content: attr(data-label);
    color: var(--muted);
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }
}
@media (max-width: 560px) {
  .header-inner, main, footer { width: min(calc(100% - 24px), 1440px); }
  .header-inner { padding: 22px 0; }
  h1 { font-size: 25px; }
  .report-meta div { grid-template-columns: 74px minmax(0, 1fr); }
  .summary-band { grid-template-columns: 1fr 1fr; }
  .summary-stat:last-child { grid-column: 1 / -1; }
  .summary-stat { min-height: 82px; padding: 14px; }
  .summary-value { font-size: 23px; }
  .toolbar { grid-template-columns: 1fr; }
  .search-control { grid-column: auto; }
  .finding-lead { padding: 18px; flex-direction: column; }
  .finding-score { width: 100%; flex-direction: column; align-items: stretch; }
  .score-block { width: 100%; flex-basis: auto; text-align: left; }
  .score-track { width: 100%; }
  .severity-escalation { width: 100%; }
  .finding-body { padding: 0 18px 18px; }
  .unknown-section { margin: 0 -18px; padding: 18px !important; }
  .unknown-section li { grid-template-columns: 1fr; }
  .unknown-section li small { grid-column: auto; }
  .refused-section { padding: 18px; }
}
@media print {
  body { background: #fff; font-size: 11px; }
  .report-header { color: #000; background: #fff; border-bottom: 2px solid #000; }
  .report-scope, .report-meta dt, .report-meta dd { color: #333; }
  .toolbar { display: none; }
  .finding { break-inside: avoid; }
  .derivation[open] { break-inside: avoid; }
  main, footer, .header-inner { width: 100%; }
}
"""


_SCRIPT = """
(() => {
  const cards = [...document.querySelectorAll('[data-finding]')];
  const search = document.getElementById('finding-search');
  const priority = document.getElementById('priority-filter');
  const knowledge = document.getElementById('knowledge-filter');
  const count = document.getElementById('visible-count');
  const expand = document.getElementById('expand-all');
  let expanded = false;

  const apply = () => {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      const matchesSearch = !query || card.dataset.search.includes(query);
      const matchesPriority = priority.value === 'all' ||
        card.dataset.priority === priority.value;
      const matchesKnowledge = knowledge.value === 'all' ||
        card.dataset.knowledge === knowledge.value;
      card.hidden = !(matchesSearch && matchesPriority && matchesKnowledge);
      if (!card.hidden) visible += 1;
    });
    count.textContent = `Showing ${visible.toLocaleString()} of ${cards.length.toLocaleString()}`;
  };

  [search, priority, knowledge].forEach((control) => {
    control.addEventListener('input', apply);
    control.addEventListener('change', apply);
  });
  expand.addEventListener('click', () => {
    expanded = !expanded;
    document.querySelectorAll('.derivation').forEach((detail) => {
      detail.open = expanded;
    });
    expand.textContent = expanded ? 'Collapse derivations' : 'Expand derivations';
  });
})();
"""
