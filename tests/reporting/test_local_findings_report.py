"""P-001: one private collection directory to one honest local findings report."""

from __future__ import annotations

import json
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from aqelyn.reporting.analyze import ReportInputError, analyze_collection
from aqelyn.reporting.cli import main
from aqelyn.reporting.html import render_findings_report


class _RenderedArithmeticParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.score_headings: list[Decimal] = []
        self.arithmetic: list[list[Decimal]] = []
        self.contribution_columns: list[list[Decimal]] = []
        self._current_arithmetic: list[Decimal] | None = None
        self._current_contributions: list[Decimal] | None = None
        self._capture: str | None = None
        self._capture_text: list[str] = []
        self._next_score_strong = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "div" and "score-block" in classes:
            self._next_score_strong = True
        elif tag == "article" and "finding" in classes:
            self._current_contributions = []
        elif tag == "p" and "calculation-total" in classes:
            self._current_arithmetic = []
        elif (
            tag == "td"
            and dict(attrs).get("data-label") == "Contribution"
            and self._current_contributions is not None
        ):
            self._capture = "contribution"
            self._capture_text = []
        elif tag == "strong":
            if self._next_score_strong:
                self._capture = "score"
                self._next_score_strong = False
                self._capture_text = []
            elif self._current_arithmetic is not None:
                self._capture = "arithmetic"
                self._capture_text = []

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "strong" and self._capture is not None:
            value = Decimal("".join(self._capture_text).strip())
            if self._capture == "score":
                self.score_headings.append(value)
            elif self._current_arithmetic is not None:
                self._current_arithmetic.append(value)
            self._capture = None
            self._capture_text = []
        elif tag == "td" and self._capture == "contribution":
            value = Decimal("".join(self._capture_text).strip().removesuffix(" points"))
            if self._current_contributions is not None:
                self._current_contributions.append(value)
            self._capture = None
            self._capture_text = []
        elif tag == "p" and self._current_arithmetic is not None:
            self.arithmetic.append(self._current_arithmetic)
            self._current_arithmetic = None
        elif tag == "article" and self._current_contributions is not None:
            self.contribution_columns.append(self._current_contributions)
            self._current_contributions = None


def _match(
    *,
    cve_id: str,
    severity: str,
    purl: str,
    cvss: float | None,
    epss: float | None = None,
) -> dict[str, Any]:
    vulnerability: dict[str, Any] = {
        "id": cve_id,
        "severity": severity,
        "cvss": (
            [{"source": "nvd", "metrics": {"baseScore": cvss}, "vector": "CVSS:3.1/AV:N"}]
            if cvss is not None
            else []
        ),
    }
    if epss is not None:
        vulnerability["epss"] = [{"epss": epss}]
    return {
        "vulnerability": vulnerability,
        "artifact": {"purl": purl},
    }


def _write_collection(
    directory: Path,
    *,
    include_kev: bool = True,
    malicious_asset: bool = False,
    include_rejected: bool = True,
) -> None:
    purl = "pkg:pypi/web<script>@1" if malicious_asset else "pkg:pypi/web@1"
    matches = [
        _match(
            cve_id="CVE-2026-1000",
            severity="Critical",
            purl=purl,
            cvss=9.8,
            epss=0.8,
        ),
        _match(
            cve_id="CVE-2026-2000",
            severity="High",
            purl="pkg:pypi/worker@2",
            cvss=None,
        ),
    ]
    if include_rejected:
        matches.append(
            _match(
                cve_id="CVE-2026-3000",
                severity="Catastrophic",
                purl="pkg:pypi/other@3",
                cvss=7.0,
            )
        )
    (directory / "vulns.json").write_text(
        json.dumps(
            {
                "descriptor": {"timestamp": "2026-07-29T12:48:30Z"},
                "matches": matches,
            }
        ),
        encoding="utf-8",
    )
    if include_kev:
        (directory / "kev.json").write_text(
            json.dumps(
                {
                    "catalogVersion": "2026.07.29",
                    "dateReleased": "2026-07-29",
                    "vulnerabilities": [
                        {
                            "cveID": "CVE-2026-1000",
                            "vendorProject": "Example",
                            "product": "Web",
                            "dateAdded": "2026-07-28",
                            "knownRansomwareCampaignUse": "Unknown",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )


@pytest.mark.asyncio
async def test_report_drives_real_owners_and_keeps_unknowns_beside_findings(
    tmp_path: Path,
) -> None:
    _write_collection(tmp_path)

    analysis = await analyze_collection(tmp_path)
    rendered = render_findings_report(analysis)

    assert len(analysis.findings) == 2
    assert analysis.findings[0].vulnerability.cve_id == "CVE-2026-1000"
    assert analysis.findings[0].has_known_exploitation
    assert analysis.findings[1].priority.factors["threat"]["status"] == "unknown"
    assert (
        analysis.findings[1].priority.factors["threat"]["unknown_cause"] == "source_cannot_assert"
    )
    second_priority = analysis.findings[1].priority
    known_points = sum(
        float(factor["contribution"]) * 100.0
        for factor in second_priority.factors.values()
        if factor["status"] == "known"
    )
    assert known_points + second_priority.uncertainty_surcharge.contribution == pytest.approx(
        second_priority.score
    )

    first_article, second_article = rendered.split('<article class="finding"', maxsplit=2)[1:]
    assert "CVE-2026-1000" in first_article
    assert "What we do not know" in first_article
    assert "Excluded" in first_article
    assert "CISA KEV does not list this CVE" in second_article
    assert "Cause: source cannot assert" in second_article
    assert "View derivation" in second_article
    assert "Compose factors and uncertainty" in second_article
    assert "Unknown factors receive no factor weight" in second_article
    assert "Uncertainty surcharge" in second_article
    assert "u = 0.25" in second_article
    assert "known-factor points" in second_article
    assert "uncertainty points" in second_article
    assert "No action was taken." in second_article
    assert "Human approval is required" in second_article

    arithmetic = _RenderedArithmeticParser()
    arithmetic.feed(rendered)
    assert len(arithmetic.score_headings) == len(analysis.findings)
    assert len(arithmetic.arithmetic) == len(analysis.findings)
    assert len(arithmetic.contribution_columns) == len(analysis.findings)
    for heading, terms, contributions in zip(
        arithmetic.score_headings,
        arithmetic.arithmetic,
        arithmetic.contribution_columns,
        strict=True,
    ):
        assert len(terms) == 3
        rendered_known_points, uncertainty_points, total_points = terms
        assert rendered_known_points + uncertainty_points == total_points
        assert total_points == heading
        assert sum(contributions[:-1], start=Decimal()) == rendered_known_points
        assert contributions[-1] == uncertainty_points
        assert sum(contributions, start=Decimal()) == total_points


@pytest.mark.asyncio
async def test_report_refuses_input_without_turning_it_into_a_clean_result(tmp_path: Path) -> None:
    _write_collection(tmp_path)

    analysis = await analyze_collection(tmp_path)
    rendered = render_findings_report(analysis)

    assert len(analysis.rejected_matches) == 1
    assert "1 scanner matches were refused" in rendered
    assert "were not treated as clean" in rendered
    assert "outside VALID_SEVERITIES" in rendered


@pytest.mark.asyncio
async def test_report_without_kev_keeps_threat_provider_unconfigured(tmp_path: Path) -> None:
    _write_collection(tmp_path, include_kev=False, include_rejected=False)

    analysis = await analyze_collection(tmp_path)

    for finding in analysis.findings:
        threat = finding.priority.factors["threat"]
        assert threat["status"] == "unknown"
        assert threat["unknown_cause"] == "provider_unconfigured"
        assert threat["weight"] == 0.0


@pytest.mark.asyncio
async def test_report_escapes_handed_in_component_text_and_blocks_network(
    tmp_path: Path,
) -> None:
    _write_collection(tmp_path, malicious_asset=True, include_rejected=False)

    rendered = render_findings_report(await analyze_collection(tmp_path))

    assert "pkg:pypi/web&lt;script&gt;@1" in rendered
    assert "pkg:pypi/web<script>@1" not in rendered
    assert "connect-src 'none'" in rendered
    assert "default-src 'none'" in rendered
    assert "http://" not in rendered
    assert "https://" not in rendered


def test_cli_writes_and_reuses_only_an_unchanged_private_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_collection(tmp_path, include_rejected=False)

    assert main([str(tmp_path)]) == 0
    report = tmp_path / "aqelyn-findings.html"
    original = report.read_bytes()
    original_stat = report.stat().st_mtime_ns

    assert main([str(tmp_path), "--reuse"]) == 0
    assert report.read_bytes() == original
    assert report.stat().st_mtime_ns == original_stat
    assert "Reused local findings report" in capsys.readouterr().out

    vulnerability_path = tmp_path / "vulns.json"
    document = json.loads(vulnerability_path.read_text(encoding="utf-8"))
    document["matches"].append(
        _match(
            cve_id="CVE-2026-4000",
            severity="Medium",
            purl="pkg:pypi/new@4",
            cvss=5.0,
        )
    )
    vulnerability_path.write_text(json.dumps(document), encoding="utf-8")

    assert main([str(tmp_path), "--reuse"]) == 0
    assert report.read_bytes() != original
    assert "CVE-2026-4000" in report.read_text(encoding="utf-8")


def test_cli_refuses_to_write_outside_the_private_collection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collection = tmp_path / "collection"
    collection.mkdir()
    _write_collection(collection, include_rejected=False)

    with pytest.raises(SystemExit, match="2"):
        main([str(collection), "--output", str(tmp_path / "elsewhere.html")])

    assert "must stay inside the collection directory" in capsys.readouterr().err


def test_cli_refuses_collection_documents_inside_git(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".git").mkdir()
    collection = tmp_path / "collection"
    collection.mkdir()
    _write_collection(collection, include_rejected=False)

    with pytest.raises(SystemExit, match="2"):
        main([str(collection)])

    assert "outside every Git worktree" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_analysis_refuses_to_invent_an_observation_time(tmp_path: Path) -> None:
    (tmp_path / "vulns.json").write_text(json.dumps({"matches": []}), encoding="utf-8")

    with pytest.raises(ReportInputError, match="no content observation time"):
        await analyze_collection(tmp_path)


@pytest.mark.asyncio
async def test_analysis_refuses_a_malformed_match_as_input_not_as_a_traceback(
    tmp_path: Path,
) -> None:
    (tmp_path / "vulns.json").write_text(
        json.dumps(
            {
                "descriptor": {"timestamp": "2026-07-29T12:48:30Z"},
                "matches": [None],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReportInputError, match="match 0 must be an object"):
        await analyze_collection(tmp_path)
