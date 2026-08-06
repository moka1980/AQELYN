"""ECR-0104: Charter v2 Principle 5 — progressive disclosure, and UX-008 modes.

The Charter specifies a six-level Progressive Detail Model and four communication modes.
Both are stated in §9 as *mandatory architectural requirements*, not styling, so they live
here as data a renderer consumes rather than as markup decisions scattered through one.

| Level | Name | Question it answers |
|---|---|---|
| 1 | Summary | What is the problem? |
| 2 | Explanation | Why does it matter? |
| 3 | Evidence | What data proves it? |
| 4 | Technical Detail | What exact configuration caused it? |
| 5 | Remediation | What should be done? |
| 6 | Audit Trail | What changed and when? |

Two rules the Charter imposes that are easy to violate by accident:

**Levels add, they never repeat.** Principle 5 says a simplified finding is a starting
point, not a duplicate — "the user interface supports multiple information levels without
duplicating data". A level that restates the one above it is a bug, and there is a witness.

**A mode narrows what is shown; it never softens what is true.** Principle 8 forbids
alarmist language, but nothing permits telling a home user a smaller truth. Every mode
shows the same severity and the same facts; they differ in how much technical surface is
offered by default.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from aqelyn.findings.models import Finding


class Mode(StrEnum):
    """Charter UX-008. The audience, not the truth, changes."""

    HOME = "home"
    SMB = "smb"
    ENTERPRISE = "enterprise"
    EXPERT = "expert"


# How many levels each mode opens by default. Every level remains reachable in every mode -
# Principle 5 calls the simplified view "a starting point, not a ceiling" - so this governs
# what is expanded on arrival, never what exists.
_DEFAULT_OPEN: dict[Mode, int] = {
    Mode.HOME: 2,
    Mode.SMB: 3,
    Mode.ENTERPRISE: 5,
    Mode.EXPERT: 6,
}


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    question: str
    body: str
    open_by_default: bool


def _evidence_body(finding: Finding) -> str:
    if not finding.evidence_ids:
        # Never render "no evidence" as though it were reassuring: UX-006 requires the link,
        # so its absence is a defect in the finding and should read as one.
        return "No evidence record is linked to this finding, which the platform requires."
    joined = ", ".join(finding.evidence_ids)
    return f"Determined by: {finding.how_determined} Evidence: {joined}"


def _technical_body(finding: Finding) -> str:
    details = finding.expert_details or {}
    if not details:
        return "No technical expansion was recorded for this finding."
    parts = [
        f"{key}: {value}"
        for key, value in sorted(details.items())
        if value not in (None, {}, [], "")
    ]
    return "; ".join(parts) if parts else "No technical expansion was recorded."


def _audit_body(finding: Finding) -> str:
    if not finding.audit:
        return (
            f"Raised {finding.first_detected_at.isoformat()}; "
            f"last seen {finding.last_detected_at.isoformat()}; status {finding.status}."
        )
    return "; ".join(f"{entry.at.isoformat()} {entry.action}" for entry in finding.audit)


def levels(finding: Finding, *, mode: Mode = Mode.ENTERPRISE) -> Sequence[Level]:
    """The Charter's six levels for one finding, in order."""

    remediation = finding.remediation
    open_through = _DEFAULT_OPEN[mode]
    specified = (
        (1, "Summary", "What is the problem?", finding.title),
        (2, "Explanation", "Why does it matter?", finding.why_it_matters),
        (3, "Evidence", "What data proves it?", _evidence_body(finding)),
        (4, "Technical Detail", "What exact configuration caused it?", _technical_body(finding)),
        (
            5,
            "Remediation",
            "What should be done?",
            f"{remediation.summary} Effort: {remediation.difficulty}. "
            f"Expected outcome: {remediation.expected_outcome}",
        ),
        (6, "Audit Trail", "What changed and when?", _audit_body(finding)),
    )
    return tuple(
        Level(
            number=number,
            name=name,
            question=question,
            body=body,
            open_by_default=number <= open_through,
        )
        for number, name, question, body in specified
    )
