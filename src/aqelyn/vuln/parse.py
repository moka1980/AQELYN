"""Pure parser for handed-in vulnerability scan documents (EA-0024, S-001).

Mirrors `supplychain/parse.py`: a document goes in as already-decoded JSON and
records come out. **No I/O, no subprocess, no network** — nothing here knows that a
scanner exists, which is the boundary S-001 was built to respect. Whoever runs the
scanner hands the result in.

Two disciplines this mapping holds, both of which real data immediately tested:

1. **Absent source data becomes a refusal with a reason, never a default.** Grype
   omits CVSS for 46% of matches against a real Debian image. `VulnerabilityRecord`
   requires `cvss`, and `CarriedScore.value` is a required non-negative float, so
   there is no way to represent "no CVSS" — and inventing `0.0` would assert *no
   severity*, the most favourable possible reading of missing data (the ECR-0040
   shape). So such matches are **rejected with a stated reason** and counted, rather
   than fabricated. See ECR-0064.

2. **CVSS must not become priority.** Grype supplies both a severity string and,
   sometimes, CVSS. Both are carried as *inputs* for EA-0024's factor composition.
   This module computes no score, ranks nothing, and never writes `disposition`.

A rejected match is not a dropped one: `ParsedVulnerabilities.rejected` carries every
one with the reason it could not be represented, so a caller can report the shortfall
instead of silently under-reporting risk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aqelyn.exposure import AssetRef
from aqelyn.vuln.models import (
    VALID_SEVERITIES,
    CarriedScore,
    VulnBasis,
    VulnerabilityRecord,
)


@dataclass(frozen=True)
class RejectedMatch:
    """A scanner match the shipped model cannot represent honestly."""

    cve_id: str
    component: str
    reason: str


@dataclass(frozen=True)
class ParsedVulnerabilities:
    records: tuple[VulnerabilityRecord, ...]
    rejected: tuple[RejectedMatch, ...]


def parse_grype(
    document: Mapping[str, Any],
    *,
    scanner: str,
    confidence: float,
    observed_at: datetime,
    tenant_id: str | None = None,
) -> ParsedVulnerabilities:
    """Map a grype JSON document to records, refusing what it cannot represent.

    `confidence` is a **required argument with no default**: it is confidence that
    the reported match exists as stated, which the scanner does not supply. The
    caller states it explicitly rather than letting this module invent one — the
    same shape as `DiscoverySource.reliability` on the SBOM path.
    """
    records: list[VulnerabilityRecord] = []
    rejected: list[RejectedMatch] = []

    for match in document.get("matches", []):
        vulnerability = match.get("vulnerability", {})
        artifact = match.get("artifact", {})
        cve_id = str(vulnerability.get("id", "")).strip()
        component = str(artifact.get("purl") or artifact.get("name") or "")

        if not cve_id:
            rejected.append(RejectedMatch("", component, "match carries no vulnerability id"))
            continue
        if not component:
            rejected.append(RejectedMatch(cve_id, "", "match carries no component reference"))
            continue

        severity = str(vulnerability.get("severity", "")).lower()
        if severity not in VALID_SEVERITIES:
            # Still refused rather than mapped to a neighbour. ECR-0064 added
            # `negligible` and `unknown`, so the common cases are now representable;
            # anything still outside the set is a value nobody has decided the
            # meaning of, and guessing would put a fabricated severity in the scorer.
            rejected.append(
                RejectedMatch(
                    cve_id,
                    component,
                    f"severity {vulnerability.get('severity')!r} is outside VALID_SEVERITIES",
                )
            )
            continue

        # ECR-0064 Gap 1: absence is representable now. `None` reaches the engine as
        # PriorityFactor(status="unknown"), which ECR-0040 excludes from the
        # denominator. It is never a zero -- a zero would claim the vulnerability
        # scores nothing, which is a stronger statement than the source supports.
        cvss = _carried_score(vulnerability.get("cvss"), observed_at=observed_at)

        records.append(
            VulnerabilityRecord(
                tenant_id=tenant_id,
                cve_id=cve_id,
                scanner=scanner,
                asset_ref=AssetRef(kind="asset", ref_id=component),
                severity=severity,
                cvss=cvss,
                epss=_epss_score(vulnerability.get("epss"), observed_at=observed_at),
                confidence=confidence,
                basis=[
                    VulnBasis(
                        kind="scanner",
                        ref=f"{scanner}:{cve_id}:{component}",
                        as_of=observed_at,
                    )
                ],
                discovered_at=observed_at,
            )
        )

    return ParsedVulnerabilities(records=tuple(records), rejected=tuple(rejected))


def _carried_score(entries: object, *, observed_at: datetime) -> CarriedScore | None:
    """Highest-versioned CVSS entry, or ``None`` when the scanner supplied none.

    ``None`` means *absent*, and the caller refuses on it. It is deliberately not a
    zero: a zero would claim the vulnerability scores nothing, which is a stronger
    and more favourable statement than the source supports.
    """
    if not isinstance(entries, Sequence) or isinstance(entries, str | bytes) or not entries:
        return None
    best: tuple[str, float, str | None] | None = None
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        metrics = entry.get("metrics")
        value = metrics.get("baseScore") if isinstance(metrics, Mapping) else None
        if not isinstance(value, int | float):
            continue
        source = str(entry.get("source") or entry.get("version") or "cvss")
        vector = entry.get("vector")
        candidate = (source, float(value), str(vector) if vector else None)
        if best is None or candidate[1] > best[1]:
            best = candidate
    if best is None:
        return None
    return CarriedScore(source=best[0], value=best[1], vector=best[2], as_of=observed_at)


def _epss_score(entries: object, *, observed_at: datetime) -> CarriedScore | None:
    """EPSS is optional on the record, so absence is representable and stays absent."""
    if not isinstance(entries, Sequence) or isinstance(entries, str | bytes) or not entries:
        return None
    first = entries[0]
    if not isinstance(first, Mapping):
        return None
    value = first.get("epss")
    if not isinstance(value, int | float):
        return None
    return CarriedScore(source="first:epss", value=float(value), as_of=observed_at)
