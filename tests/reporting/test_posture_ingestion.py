"""ECR-0100 witnesses for posture ingestion.

The fixtures are the point. A posture document that is merely well-formed proves nothing:
every check below is written so that removing the guard it names turns it red.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import new_id
from aqelyn.findings import Finding
from aqelyn.reporting.posture import (
    POSTURE_FINDING_TYPE,
    PostureDocumentError,
    observation_to_finding,
    posture_dedup_key,
    validate_posture_shape,
)

NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "observation_id": "obs-hsts-absent",
        "subject": {"kind": "site", "ref": "https://example.test"},
        "check": "response_header_present",
        "severity": "medium",
        "severity_score": 48.0,
        "what_happened": "The site redirects to https but sends no Strict-Transport-Security.",
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


def _document(*observations: dict[str, Any]) -> dict[str, Any]:
    return {"schema": "aqelyn.posture.collection/v0", "observations": list(observations)}


# --- shape ---------------------------------------------------------------------------


def test_valid_document_is_accepted() -> None:
    observations = validate_posture_shape(_document(_observation()))
    assert len(observations) == 1


@pytest.mark.parametrize(
    "field", ["what_happened", "why_it_matters", "how_determined", "risk_of_inaction"]
)
def test_each_narrative_field_is_required(field: str) -> None:
    """A collector that cannot say why it matters has not collected enough."""
    document = _document(_observation(**{field: ""}))
    with pytest.raises(PostureDocumentError, match=field):
        validate_posture_shape(document)


def test_missing_narrative_key_is_refused_not_defaulted() -> None:
    observation = _observation()
    del observation["risk_of_inaction"]
    with pytest.raises(PostureDocumentError, match="risk_of_inaction"):
        validate_posture_shape(_document(observation))


def test_repeated_observation_id_is_refused() -> None:
    """Two observations sharing an id would collapse to one finding, silently."""
    with pytest.raises(PostureDocumentError, match="repeats observation_id"):
        validate_posture_shape(_document(_observation(), _observation()))


def test_observations_must_be_a_list() -> None:
    with pytest.raises(PostureDocumentError, match="must be a list"):
        validate_posture_shape({"observations": {"not": "a list"}})


def test_empty_observation_list_is_refused() -> None:
    with pytest.raises(PostureDocumentError, match="must not be empty"):
        validate_posture_shape(_document())


def test_unknown_severity_is_refused() -> None:
    with pytest.raises(PostureDocumentError, match="severity must be one of"):
        validate_posture_shape(_document(_observation(severity="catastrophic")))


@pytest.mark.parametrize("score", [-1.0, 100.1, "48", True, None])
def test_severity_score_must_be_a_number_in_range(score: object) -> None:
    with pytest.raises(PostureDocumentError, match="severity_score"):
        validate_posture_shape(_document(_observation(severity_score=score)))


def test_remediation_difficulty_is_constrained() -> None:
    observation = _observation()
    observation["remediation"] = dict(observation["remediation"], difficulty="trivial")
    with pytest.raises(PostureDocumentError, match="difficulty must be one of"):
        validate_posture_shape(_document(observation))


def test_subject_ref_is_required() -> None:
    with pytest.raises(PostureDocumentError, match="subject ref"):
        validate_posture_shape(_document(_observation(subject={"kind": "site"})))


# --- dedup key -----------------------------------------------------------------------


def test_dedup_key_is_stable_across_runs() -> None:
    """A re-run of the same collection must not raise a second copy of every finding."""
    first = posture_dedup_key(_observation())
    second = posture_dedup_key(copy.deepcopy(_observation()))
    assert first == second


def test_dedup_key_separates_two_checks_on_one_subject() -> None:
    a = posture_dedup_key(_observation(observation_id="obs-a", check="header_present"))
    b = posture_dedup_key(_observation(observation_id="obs-b", check="banner_disclosure"))
    assert a != b


def test_dedup_key_separates_one_check_across_subjects() -> None:
    a = posture_dedup_key(_observation(subject={"kind": "site", "ref": "https://a.test"}))
    b = posture_dedup_key(_observation(subject={"kind": "site", "ref": "https://b.test"}))
    assert a != b


def test_every_observation_in_a_document_gets_a_distinct_key() -> None:
    observations = [
        _observation(observation_id=f"obs-{index}", check=f"check-{index}") for index in range(6)
    ]
    keys = {posture_dedup_key(observation) for observation in observations}
    assert len(keys) == len(observations)


# --- finding construction ------------------------------------------------------------


def _finding(observation: dict[str, Any] | None = None) -> Finding:
    return observation_to_finding(
        observation or _observation(),
        finding_id=new_id("fnd"),
        evidence_id=new_id("evd"),
        observed_at=NOW,
    )


def test_finding_carries_the_narrative_verbatim() -> None:
    observation = _observation()
    finding = _finding(observation)
    assert finding.what_happened == observation["what_happened"]
    assert finding.why_it_matters == observation["why_it_matters"]
    assert finding.how_determined == observation["how_determined"]
    assert finding.risk_of_inaction == observation["risk_of_inaction"]


def test_finding_carries_the_observed_score_unchanged() -> None:
    """ECR-0063 keeps severity_score fixed so the keyset cursor stays stable."""
    finding = _finding(_observation(severity_score=63.5))
    assert finding.severity_score == 63.5


def test_finding_links_its_evidence() -> None:
    evidence_id = new_id("evd")
    finding = observation_to_finding(
        _observation(), finding_id=new_id("fnd"), evidence_id=evidence_id, observed_at=NOW
    )
    assert finding.evidence_ids == [evidence_id]


def test_finding_is_typed_as_posture_not_vulnerability() -> None:
    assert _finding().finding_type == POSTURE_FINDING_TYPE


def test_finding_remediation_is_carried() -> None:
    finding = _finding()
    assert finding.remediation.summary.startswith("Add Strict-Transport-Security")
    assert finding.remediation.difficulty == "low"
    assert finding.remediation.expected_outcome


def test_posture_findings_are_not_automation_eligible_by_default() -> None:
    """Nothing observed passively should be actioned without a human deciding."""
    assert _finding().automation.eligibility == "not_eligible"


def test_detection_times_come_from_the_observation_not_the_clock() -> None:
    finding = _finding()
    assert finding.first_detected_at == NOW
    assert finding.last_detected_at == NOW


def test_two_observations_produce_findings_with_different_dedup_keys() -> None:
    one = _finding(_observation(observation_id="obs-a", check="check-a"))
    two = _finding(_observation(observation_id="obs-b", check="check-b"))
    assert one.dedup_key != two.dedup_key
