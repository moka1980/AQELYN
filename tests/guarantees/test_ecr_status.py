"""ECR index/body status consistency."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import pytest

ECR_LOG = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "modules" / "ECR-LOG.md"
BODY_STATUS_EXCLUSIONS = {
    61: (
        "ECR-0061's legacy Status line describes the inherited ECR-0034 discharge; "
        "its own Accepted state is recorded in the index."
    )
}
_INDEX_ROW = re.compile(
    r"^\| ECR-(?P<number>\d{4}) \| [^|]+ \| (?P<status>[^|]+) \|",
    re.MULTILINE,
)
_BODY_HEADING = re.compile(r"^## ECR-(?P<number>\d{4})\b", re.MULTILINE)
_BODY_STATUS = re.compile(r"^\*\*Status:\*\*\s*(?P<status>[^\n]+)", re.MULTILINE)
_CANONICAL_STATUS = re.compile(
    r"^(?:Fully\s+)?(?P<status>Proposed|Accepted|Rejected|Resolved)\b",
    re.IGNORECASE,
)


class ECRStatusMismatch(AssertionError):
    """The ECR index and narrative body disagree mechanically."""


def test_ecr_index_and_body_statuses_match() -> None:
    assert_ecr_statuses_match(
        ECR_LOG.read_text(encoding="utf-8"),
        exclusions=BODY_STATUS_EXCLUSIONS,
    )


def test_ecr_status_guard_rejects_mismatch() -> None:
    text = "\n".join(
        (
            "| ECR-0001 | owner | Accepted | summary |",
            "",
            "## ECR-0001 - negative control",
            "",
            "**Status:** Proposed.",
            "",
        )
    )

    with pytest.raises(ECRStatusMismatch, match="index=Accepted, body=Proposed"):
        assert_ecr_statuses_match(text)


def assert_ecr_statuses_match(
    text: str,
    *,
    exclusions: Mapping[int, str] | None = None,
) -> None:
    selected_exclusions = dict(exclusions or {})
    blank_reasons = sorted(
        number for number, reason in selected_exclusions.items() if not reason.strip()
    )
    if blank_reasons:
        raise ECRStatusMismatch(f"ECR status exclusions require reasons: {blank_reasons}")

    index = {
        int(match.group("number")): _canonical_status(match.group("status"))
        for match in _INDEX_ROW.finditer(text)
    }
    sections = _body_sections(text)
    if not index:
        raise ECRStatusMismatch("ECR index has no rows")
    expected_numbers = set(range(1, max(index) + 1))
    if set(index) != expected_numbers:
        raise ECRStatusMismatch(
            f"ECR index is not contiguous: expected={sorted(expected_numbers)}, "
            f"actual={sorted(index)}"
        )
    if set(sections) != set(index):
        raise ECRStatusMismatch(
            "ECR index/body membership differs: "
            f"missing_bodies={sorted(set(index) - set(sections))}, "
            f"extra_bodies={sorted(set(sections) - set(index))}"
        )

    mismatches: list[str] = []
    unclassified: set[int] = set()
    for number, body in sections.items():
        status_match = _BODY_STATUS.search(body)
        if status_match is None:
            continue
        body_status = _canonical_status(status_match.group("status"))
        if body_status is None:
            unclassified.add(number)
            continue
        index_status = index[number]
        if index_status is None:
            mismatches.append(f"ECR-{number:04d}: index status is not canonical")
        elif index_status != body_status:
            mismatches.append(f"ECR-{number:04d}: index={index_status}, body={body_status}")

    expected_unclassified = set(selected_exclusions)
    if unclassified != expected_unclassified:
        mismatches.append(
            "unclassified body statuses differ from the reasoned exclusions: "
            f"expected={sorted(expected_unclassified)}, actual={sorted(unclassified)}"
        )
    if mismatches:
        raise ECRStatusMismatch("; ".join(mismatches))


def _body_sections(text: str) -> dict[int, str]:
    headings = list(_BODY_HEADING.finditer(text))
    return {
        int(match.group("number")): text[
            match.end() : headings[index + 1].start() if index + 1 < len(headings) else len(text)
        ]
        for index, match in enumerate(headings)
    }


def _canonical_status(value: str) -> str | None:
    cleaned = re.sub(r"[*_`]", "", value).strip()
    match = _CANONICAL_STATUS.match(cleaned)
    return match.group("status").capitalize() if match is not None else None
