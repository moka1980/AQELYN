"""P-001: one private collection directory to one honest local findings report."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

import pytest

from aqelyn.findings.memory import InMemoryFindingStore
from aqelyn.findings.service import FindingReadService
from aqelyn.reporting.analyze import (
    ReportFinding,
    ReportInputError,
    _read_all_findings,
    analyze_collection,
)
from aqelyn.reporting.cli import main
from aqelyn.reporting.html import render_findings_report
from aqelyn.vuln.service import VulnerabilityIntelligenceService

_PRE_ECR0089_SEMANTIC_GOLDEN: dict[str, Any] = {
    "scanner_matches": 3,
    "represented_records": 2,
    "rejected": 1,
    "unknown_factor_count": 9,
    "findings": [
        {
            "cve": "CVE-2026-1000",
            "asset": "pkg:pypi/web@1",
            "score": 63.35,
            "priority": "medium",
            "severity": "medium",
            "unknowns": [
                (
                    "baseline",
                    "provider_unconfigured",
                    "EA-0012 blocking factor 0.000 reduces priority; "
                    "No EA-0012 blocking provider supplied.",
                ),
                (
                    "exposure",
                    "provider_unconfigured",
                    "No EA-0023 exposure provider supplied.",
                ),
                (
                    "mission",
                    "provider_unconfigured",
                    "No EA-0007 mission provider supplied.",
                ),
            ],
        },
        {
            "cve": "CVE-2026-2000",
            "asset": "pkg:pypi/worker@2",
            "score": 28.25,
            "priority": "low",
            "severity": "low",
            "unknowns": [
                (
                    "baseline",
                    "provider_unconfigured",
                    "EA-0012 blocking factor 0.000 reduces priority; "
                    "No EA-0012 blocking provider supplied.",
                ),
                (
                    "cvss",
                    "input_missing",
                    "No CVSS was supplied by the source; severity is undetermined, not zero.",
                ),
                (
                    "epss",
                    "input_missing",
                    "No EPSS carried score was supplied by the source.",
                ),
                (
                    "exposure",
                    "provider_unconfigured",
                    "No EA-0023 exposure provider supplied.",
                ),
                (
                    "mission",
                    "provider_unconfigured",
                    "No EA-0007 mission provider supplied.",
                ),
                (
                    "threat",
                    "source_cannot_assert",
                    "CISA KEV does not list this CVE. KEV is a positive-only catalog of "
                    "known-exploited vulnerabilities, so absence is not evidence that the "
                    "vulnerability is unexploited -- the source cannot assert for this record.",
                ),
            ],
        },
    ],
}


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


class _EscalationAnnotationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.annotations: list[tuple[str, tuple[str, ...]]] = []
        self._depth = 0
        self._text: list[str] = []
        self._current_values: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self._depth == 0:
            if tag == "aside" and "severity-escalation" in classes:
                self._depth = 1
                self._text = []
                self._current_values = []
            return
        self._depth += 1
        current = attributes.get("data-current-severity")
        if current is not None:
            self._current_values.append(current)

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        self._depth -= 1
        if self._depth == 0:
            text = " ".join("".join(self._text).split())
            self.annotations.append((text, tuple(self._current_values)))


async def _reemitted_at(
    item: ReportFinding,
    *,
    current_severity_score: float,
) -> ReportFinding:
    store = InMemoryFindingStore(mode="local")
    first_emission = item.finding.model_copy(
        update={"id": "", "current_severity_score": None},
        deep=True,
    )
    created = await store.raise_finding(first_emission)
    updated = await store.raise_finding(
        first_emission.model_copy(
            update={"severity_score": current_severity_score},
            deep=True,
        )
    )
    assert updated.id == created.id
    assert updated.severity_score == created.severity_score
    assert updated.current_severity_score == current_severity_score
    return replace(item, finding=updated)


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
async def test_ecr0089_report_uses_registered_publish_and_read_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_collection(tmp_path)
    calls = {"ingest": 0, "read": 0}
    original_ingest = VulnerabilityIntelligenceService.ingest
    original_query = FindingReadService.query

    async def observed_ingest(
        self: VulnerabilityIntelligenceService,
        *,
        records: list[Any],
        tenant_id: str | None,
    ) -> list[Any]:
        calls["ingest"] += 1
        return await original_ingest(self, records=records, tenant_id=tenant_id)

    async def observed_query(
        self: FindingReadService,
        *,
        tenant_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Any], str | None]:
        calls["read"] += 1
        return await original_query(
            self,
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
        )

    monkeypatch.setattr(VulnerabilityIntelligenceService, "ingest", observed_ingest)
    monkeypatch.setattr(FindingReadService, "query", observed_query)

    analysis = await analyze_collection(tmp_path)

    assert len(analysis.findings) == 2
    assert calls == {"ingest": 1, "read": 1}


@pytest.mark.asyncio
async def test_ecr0089_runtime_path_matches_the_pre_unification_semantic_golden(
    tmp_path: Path,
) -> None:
    _write_collection(tmp_path)

    analysis = await analyze_collection(tmp_path)
    semantic = {
        "scanner_matches": analysis.scanner_matches,
        "represented_records": analysis.represented_records,
        "rejected": len(analysis.rejected_matches),
        "unknown_factor_count": analysis.unknown_factor_count,
        "findings": [
            {
                "cve": item.vulnerability.cve_id,
                "asset": item.vulnerability.asset_ref.ref_id,
                "score": item.priority.score,
                "priority": item.priority.priority,
                "severity": item.finding.severity,
                "unknowns": sorted(
                    (
                        name,
                        factor.get("unknown_cause"),
                        factor.get("reason"),
                    )
                    for name, factor in item.priority.factors.items()
                    if factor.get("status") == "unknown"
                ),
            }
            for item in analysis.findings
        ],
    }

    assert semantic == _PRE_ECR0089_SEMANTIC_GOLDEN


async def test_ecr0089_finding_read_is_single_pass_at_acceptance_scale() -> None:
    expected_count = 10_173

    class _Reader:
        def __init__(self) -> None:
            self.calls: list[tuple[str | None, int, str | None]] = []

        async def query(
            self,
            *,
            tenant_id: str | None,
            limit: int,
            cursor: str | None,
        ) -> tuple[list[Any], str | None]:
            self.calls.append((tenant_id, limit, cursor))
            return [object()] * expected_count, None

    reader = _Reader()

    findings = await _read_all_findings(cast(Any, reader), expected_count=expected_count)

    assert len(findings) == expected_count
    assert reader.calls == [(None, expected_count, None)]


@pytest.mark.asyncio
async def test_p002_divergent_renders_current_and_disclosure(tmp_path: Path) -> None:
    """The branch is test-reachable via re-emission but dormant in fresh aqelyn-report runs."""

    _write_collection(tmp_path, include_rejected=False)
    analysis = await analyze_collection(tmp_path)
    item = await _reemitted_at(
        analysis.findings[0],
        current_severity_score=0.876,
    )

    rendered = render_findings_report(replace(analysis, findings=(item,)))
    parser = _EscalationAnnotationParser()
    parser.feed(rendered)

    assert len(parser.annotations) == 1
    annotation_text, current_values = parser.annotations[0]
    assert current_values == ("87.6",)
    assert annotation_text.count("87.6") == 1
    assert "This priority is the severity recorded when the finding was first raised." in (
        annotation_text
    )
    assert "does not change the priority or its position in this list." in annotation_text


@pytest.mark.asyncio
async def test_p002_equal_renders_neither(tmp_path: Path) -> None:
    _write_collection(tmp_path, include_rejected=False)
    analysis = await analyze_collection(tmp_path)
    assert all(
        item.finding.current_severity_score == item.finding.severity_score
        for item in analysis.findings
    )

    parser = _EscalationAnnotationParser()
    parser.feed(render_findings_report(analysis))

    assert parser.annotations == []


@pytest.mark.asyncio
async def test_p002_sub_display_precision_difference_renders_neither(tmp_path: Path) -> None:
    _write_collection(tmp_path, include_rejected=False)
    analysis = await analyze_collection(tmp_path)
    first_seen = analysis.findings[0].finding.severity_score
    first_seen_text = f"{first_seen * 100.0:.1f}"
    current = next(
        candidate
        for candidate in (
            first_seen - 0.0004,
            first_seen + 0.0004,
        )
        if 0.0 <= candidate <= 1.0 and f"{candidate * 100.0:.1f}" == first_seen_text
    )
    assert current != first_seen
    assert not math.isclose(current, first_seen)
    assert f"{current * 100.0:.1f}" == first_seen_text
    item = await _reemitted_at(
        analysis.findings[0],
        current_severity_score=current,
    )

    parser = _EscalationAnnotationParser()
    parser.feed(render_findings_report(replace(analysis, findings=(item,))))

    assert parser.annotations == []


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
