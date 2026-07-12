"""FindingStore protocol + validation helpers (Finding-model.spec.md §9)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import EvidenceRequired, SchemaValidationError
from aqelyn.findings.models import Finding, FindingQuery, Remediation

EvidenceExists = Callable[[str], Awaitable[bool]]


def validate_finding(f: Finding) -> None:
    """Enforce mandatory explanation + evidence (FR-1, FR-2)."""
    for field in ("title", "what_happened", "why_it_matters", "how_determined", "risk_of_inaction"):
        if not str(getattr(f, field)).strip():
            raise SchemaValidationError(f"finding.{field} must be non-empty")
    _validate_remediation(f.remediation)
    if not f.evidence_ids:
        raise EvidenceRequired("finding requires at least one evidence reference")


def _validate_remediation(r: Remediation) -> None:
    if not r.summary.strip():
        raise SchemaValidationError("remediation.summary must be non-empty")
    if not r.expected_outcome.strip():
        raise SchemaValidationError("remediation.expected_outcome must be non-empty")


class FindingStore(Protocol):
    async def raise_finding(self, f: Finding) -> Finding: ...
    async def get(self, finding_id: str) -> Finding | None: ...
    async def query(self, q: FindingQuery) -> tuple[list[Finding], str | None]: ...
    async def transition(
        self,
        finding_id: str,
        to_status: str,
        *,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Finding: ...
    async def add_evidence(
        self, finding_id: str, evidence_ids: list[str], *, by: ActorRef, expected_version: int
    ) -> Finding: ...
