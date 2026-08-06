"""ECR-0103: Charter v2 compliance for posture findings.

The Charter calls its UX requirements mandatory architectural requirements, not styling,
so they get witnesses like any other contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aqelyn.conventions import new_id
from aqelyn.findings import Finding
from aqelyn.reporting.posture import expert_details, observation_to_finding, plain_title

NOW = datetime(2026, 8, 6, 11, 0, tzinfo=UTC)


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "observation_id": "obs-hsts",
        "subject": {"kind": "site", "ref": "https://example.test"},
        "check": "response_header_present",
        "severity": "medium",
        "severity_score": 48.0,
        "observed": {"strict_transport_security": None},
        "what_happened": "The site redirects to https but sends no HSTS header. More detail here.",
        "why_it_matters": "The first request of each visit is still downgradeable.",
        "how_determined": "curl -D - https://example.test ; header absent.",
        "risk_of_inaction": "The redirect can be stripped on an untrusted network.",
        "remediation": {
            "summary": "Add Strict-Transport-Security to the TLS server block.",
            "difficulty": "low",
            "expected_outcome": "Browsers refuse cleartext after the first visit.",
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


# --- UX-001: a non-technical summary -------------------------------------------------


def test_title_is_a_sentence_not_a_machine_identifier() -> None:
    title = _finding().title
    assert "response_header_present" not in title
    assert "https://example.test" not in title
    assert title.startswith("The site redirects")


def test_title_takes_the_first_sentence_only() -> None:
    """A title is a summary. The rest stays in what_happened."""
    assert _finding().title == "The site redirects to https but sends no HSTS header"


def test_an_explicit_title_is_respected() -> None:
    assert _finding(_observation(title="Your website does not enforce HTTPS")).title == (
        "Your website does not enforce HTTPS"
    )


def test_title_never_falls_through_to_empty() -> None:
    assert plain_title({"what_happened": ""}) == "Security observation"


def test_title_is_not_the_check_name_even_when_what_happened_is_terse() -> None:
    observation = _observation(what_happened="Firewall is off.")
    assert _finding(observation).title == "Firewall is off"


# --- UX-002: an expert-detail expansion ----------------------------------------------


def test_expert_details_carry_the_machine_identifiers() -> None:
    details = _finding().expert_details or {}
    assert details["check"] == "response_header_present"
    assert details["observation_id"] == "obs-hsts"
    assert details["subject"]["ref"] == "https://example.test"


def test_expert_details_carry_the_raw_measurement() -> None:
    """Progressive Detail level 4: the exact configuration that caused the finding."""
    details = _finding().expert_details or {}
    assert details["observed"] == {"strict_transport_security": None}


def test_expert_details_are_present_on_every_finding() -> None:
    assert _finding().expert_details is not None


def test_nothing_is_lost_when_the_title_is_simplified() -> None:
    """The identifiers removed from the title must still be reachable."""
    observation = _observation()
    finding = _finding(observation)
    details = finding.expert_details or {}
    assert observation["check"] not in finding.title
    assert details["check"] == observation["check"]
    assert details["subject"] == observation["subject"]


def test_expert_details_do_not_duplicate_the_narrative() -> None:
    """Principle 5: deeper levels add detail, they do not repeat the summary."""
    details = expert_details(_observation())
    assert "what_happened" not in details
    assert "why_it_matters" not in details


# --- the Charter's required fields, end to end ----------------------------------------


def test_every_charter_required_field_is_populated() -> None:
    """Charter section 5: eleven required fields on a user-facing finding."""
    finding = _finding()
    assert finding.title
    assert finding.severity
    assert finding.what_happened
    assert finding.why_it_matters
    assert finding.evidence_ids
    assert finding.remediation.summary
    assert finding.remediation.difficulty
    assert finding.remediation.expected_outcome
    assert finding.automation.eligibility
    assert finding.expert_details
    assert finding.risk_of_inaction


def test_ux007_no_fear_based_language_in_generated_text() -> None:
    """UX-007. Checks the words this codebase generates, not the operator's own prose."""
    banned = ("catastrophic", "disaster", "hacked", "urgent!", "immediately!!")
    finding = _finding()
    text = " ".join(
        [finding.title, finding.what_happened, finding.why_it_matters, finding.risk_of_inaction]
    ).lower()
    for word in banned:
        assert word not in text
