"""ECR-0104 witnesses for Charter v2 Principle 5 and UX-008.

The Charter states these are mandatory architectural requirements, so the two properties
that are easy to break by accident get explicit witnesses: levels must not duplicate each
other, and a communication mode must not change what is true.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aqelyn.conventions import new_id
from aqelyn.findings import Finding
from aqelyn.reporting.disclosure import Mode, levels
from aqelyn.reporting.posture import observation_to_finding

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "observation_id": "obs-ports",
        "subject": {"kind": "host", "ref": "203.0.113.10"},
        "check": "listening_sockets_public",
        "severity": "high",
        "severity_score": 70.0,
        "observed": {"public_ports": [8080, 8081]},
        "what_happened": "Two ports are reachable from beyond this machine.",
        "why_it_matters": "They sit beside the reverse proxy rather than behind it.",
        "how_determined": "Parsed ss -tlnH on the host.",
        "risk_of_inaction": "Services intended for local use are exposed.",
        "remediation": {
            "summary": "Bind them to loopback.",
            "difficulty": "low",
            "expected_outcome": "Only intended ports stay reachable.",
        },
    }
    base.update(overrides)
    return base


def _finding(observation: dict[str, Any] | None = None) -> Finding:
    return observation_to_finding(
        observation or _observation(),
        finding_id=new_id("fnd"),
        evidence_id=new_id("evd"),
        observed_at=NOW,
    )


# --- the six levels exist, in order ---------------------------------------------------


def test_all_six_charter_levels_are_present_in_order() -> None:
    produced = levels(_finding())
    assert [level.number for level in produced] == [1, 2, 3, 4, 5, 6]
    assert [level.name for level in produced] == [
        "Summary",
        "Explanation",
        "Evidence",
        "Technical Detail",
        "Remediation",
        "Audit Trail",
    ]


def test_every_level_carries_the_question_it_answers() -> None:
    """The Charter specifies the question per level, not only the name."""
    questions = {level.number: level.question for level in levels(_finding())}
    assert questions[1] == "What is the problem?"
    assert questions[4] == "What exact configuration caused it?"
    assert questions[6] == "What changed and when?"


def test_no_level_is_empty() -> None:
    assert all(level.body.strip() for level in levels(_finding()))


# --- Principle 5: levels add, they never repeat ---------------------------------------


def test_levels_do_not_duplicate_one_another() -> None:
    """ "...supports multiple information levels without duplicating data"."""
    bodies = [level.body.strip() for level in levels(_finding())]
    assert len(set(bodies)) == len(bodies)


def test_the_explanation_is_not_the_summary_again() -> None:
    produced = {level.number: level.body for level in levels(_finding())}
    assert produced[1] != produced[2]


def test_technical_detail_carries_the_raw_measurement_the_summary_omits() -> None:
    produced = {level.number: level.body for level in levels(_finding())}
    assert "public_ports" in produced[4]
    assert "public_ports" not in produced[1]


def test_evidence_level_names_the_evidence_record() -> None:
    finding = _finding()
    produced = {level.number: level.body for level in levels(finding)}
    assert finding.evidence_ids[0] in produced[3]


def test_missing_evidence_reads_as_a_defect_not_as_reassurance() -> None:
    finding = _finding().model_copy(update={"evidence_ids": []})
    body = next(level.body for level in levels(finding) if level.number == 3)
    assert "requires" in body
    assert "no issues" not in body.lower()


# --- UX-008: a mode changes what is opened, never what is true ------------------------


def test_every_mode_produces_all_six_levels() -> None:
    """A simplified view is a starting point, not a ceiling: nothing is removed."""
    for mode in Mode:
        assert len(levels(_finding(), mode=mode)) == 6


def test_home_mode_opens_less_than_expert_mode() -> None:
    home = sum(level.open_by_default for level in levels(_finding(), mode=Mode.HOME))
    expert = sum(level.open_by_default for level in levels(_finding(), mode=Mode.EXPERT))
    assert home < expert


def test_expert_mode_opens_everything() -> None:
    assert all(level.open_by_default for level in levels(_finding(), mode=Mode.EXPERT))


def test_the_summary_is_open_in_every_mode() -> None:
    for mode in Mode:
        first = next(level for level in levels(_finding(), mode=mode) if level.number == 1)
        assert first.open_by_default


def test_a_mode_never_changes_the_content_of_a_level() -> None:
    """UX-008 selects register, not truth. Same finding, same words, whoever is reading."""
    # One finding, read four ways. Building a fresh one per mode would compare different
    # findings and pass for the wrong reason - the evidence id alone would differ.
    finding = _finding()
    reference = {level.number: level.body for level in levels(finding, mode=Mode.EXPERT)}
    for mode in Mode:
        produced = {level.number: level.body for level in levels(finding, mode=mode)}
        assert produced == reference


def test_severity_is_not_softened_for_a_home_reader() -> None:
    finding = _finding()
    home = levels(finding, mode=Mode.HOME)
    assert finding.severity == "high"
    assert home[0].body == finding.title
