"""S-001: drive the shipped engine chain against a real container image.

**This file lives outside `src/aqelyn/` for an architectural reason, not a mechanical
one.** GC-001's discovery test asserts a known set is a *subset* of actual, so a new
package would not fail it, and its no-execute AC forbids handler invocations that
bypass EA-0008 dispatch — not `subprocess`. The guard would stay green either way.

The real reason is that a scanner-invoking module inside `src/aqelyn/` **is live
collection**, the boundary every spec defers to a future EA-0008-gated connector.
Recording the correct justification matters: otherwise a later reader checks GC-001,
finds it green, and concludes the boundary was imaginary.

**The boundary, stated precisely:** this driver invokes tools and hands in files; the
engines never learn a scanner exists. Nothing under `src/aqelyn/` references `syft`,
`grype`, or a subprocess.

Usage:
    python tools/first_run.py postgres:16 --tenant-mode enterprise
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hashlib

from aqelyn.conventions import ActorRef, new_id
from aqelyn.events import Subject
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.supplychain import SBOMDocument
from aqelyn.supplychain.parse import parse_sbom
from aqelyn.threat.parse import KevExploitationProvider, parse_kev
from aqelyn.vuln import (
    VALID_FACTOR_UNKNOWN_CAUSES,
    CoverageReport,
    FactorUnknownCause,
    PostgresVulnerabilityStore,
    VulnerabilityIntelligenceEngine,
)
from aqelyn.vuln.parse import parse_grype

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
"""S-002/T3: the driver knows this URL. **Nothing under `src/aqelyn/` does** -- the
engine receives a document, exactly as it receives the SBOM. The boundary is
architectural (live collection is what every spec defers), not mechanical."""

SYFT_SOURCE_ID = "src_019f9a2008d17161979fdb07ebec82e3"
"""Stable registry id for the syft source. Fixed rather than minted per run, so the
same scanner is the same source across runs -- which is what dedup keys off."""

SCAN_CONFIDENCE = 0.9
"""Confidence that a reported match exists as stated. Stated by the operator, because
the scanner does not supply one — the parser refuses to invent it."""


@dataclass
class RunReport:
    target: str
    tenant_mode: str
    sbom_components: int
    sbom_parsed: int
    grype_matches: int
    vuln_records: int
    vuln_rejected: list[tuple[str, str, str]]
    join_total: int
    join_matched: int
    stored: int
    findings: list[Any]
    coverage_factors: list[FactorReading] = field(default_factory=list)


def _run(cmd: list[str], out: Path) -> None:
    print(f"  $ {' '.join(cmd)}")
    with out.open("wb") as handle:
        result = subprocess.run(cmd, stdout=handle, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{cmd[0]} failed: {result.stderr.decode()[:400]}")


def collect(target: str, workdir: Path, *, reuse: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Invoke the scanners. This is the only code that knows they exist."""
    sbom_path, vuln_path = workdir / "sbom.json", workdir / "vulns.json"
    if not (reuse and sbom_path.exists()):
        _run(["syft", target, "-o", "cyclonedx-json"], sbom_path)
    if not (reuse and vuln_path.exists()):
        _run(["grype", target, "-o", "json"], vuln_path)
    return json.loads(sbom_path.read_text()), json.loads(vuln_path.read_text())


def collect_kev(workdir: Path, *, reuse: bool) -> dict[str, Any]:
    """Fetch the KEV catalog once and cache it, exactly as the scans are cached."""
    path = workdir / "kev.json"
    if not (reuse and path.exists()):
        _run(["curl", "-sSfL", KEV_URL], path)
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def check_cve_join(catalog: Any, vulns: dict[str, Any]) -> tuple[int, int]:
    """Check the CVE join explicitly -- *because* it is easy.

    CVE->CVE is far simpler than S-001's purl join, which is exactly why it would be
    assumed rather than verified. A silent zero here is indistinguishable from a
    correct implementation finding nothing.
    """
    cves = {m.get("vulnerability", {}).get("id") for m in vulns.get("matches", [])}
    cves.discard(None)
    hits = sum(1 for cve in cves if catalog.lookup(str(cve)) is not None)
    return len(cves), hits


def check_purl_join(sbom: dict[str, Any], vulns: dict[str, Any]) -> tuple[int, int]:
    """Check the join explicitly. Inferring it from a finding count hides an orphan."""
    sbom_purls = {c.get("purl") for c in sbom.get("components", []) if c.get("purl")}
    match_purls = [m.get("artifact", {}).get("purl") for m in vulns.get("matches", [])]
    matched = sum(1 for p in match_purls if p in sbom_purls)
    return len(match_purls), matched


async def drive(target: str, tenant_mode: str, workdir: Path, *, reuse: bool) -> RunReport:
    tenant_id = "018f0000-0000-7000-8000-0000005e0001" if tenant_mode == "enterprise" else None
    now = datetime.now(UTC)

    print(f"[1/5] collecting from {target}")
    sbom_raw, vulns_raw = collect(target, workdir, reuse=reuse)

    print("[2/5] checking the purl join")
    join_total, join_matched = check_purl_join(sbom_raw, vulns_raw)
    print(f"      {join_matched}/{join_total} matches join the SBOM")
    if join_total and join_matched == 0:
        raise SystemExit("purl join is empty: every vulnerability orphaned")

    print("[3/5] parsing handed-in documents")
    catalog = parse_kev(collect_kev(workdir, reuse=reuse))
    cve_total, cve_hits = check_cve_join(catalog, vulns_raw)
    print(
        f"      KEV catalog            : {catalog.catalog_version} ({len(catalog.entries)} entries)"
    )
    print(f"      CVE join               : {cve_hits} of {cve_total} distinct CVEs listed in KEV")
    # The SBOM file itself is the evidence. Recorded properly rather than minting a
    # bare id: a fabricated evidence reference would be exactly the kind of plausible
    # fill this milestone exists to avoid.
    evidence_store = InMemoryEvidenceStore(mode=tenant_mode)
    raw_bytes = json.dumps(sbom_raw, sort_keys=True).encode()
    subject_id = new_id("obj")
    evidence = await evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="sbom.document",
            schema_version=1,
            subject=Subject(object_ids=[subject_id]),
            collected_at=now,
            recorded_at=now,
            collector=ActorRef(actor_type="system", actor_id="s001-driver"),
            source_id=SYFT_SOURCE_ID,
            method="handed-in file",
            content={"target": target, "tool": "syft"},
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            labels={"kind": "sbom", "target": target},
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    sbom_doc = SBOMDocument(
        format="cyclonedx",
        subject_ref=subject_id,
        raw=sbom_raw,
        source_id=SYFT_SOURCE_ID,
        observed_at=now,
        evidence_id=evidence.id,
    )
    parsed_sbom = parse_sbom(sbom_doc, tenant_id=tenant_id)
    parsed_vulns = parse_grype(
        vulns_raw,
        scanner="grype",
        confidence=SCAN_CONFIDENCE,
        observed_at=now,
        tenant_id=tenant_id,
    )
    print(f"      SBOM components parsed : {len(parsed_sbom.components)}")
    print(f"      vulnerability records  : {len(parsed_vulns.records)}")
    print(f"      REFUSED (unrepresentable): {len(parsed_vulns.rejected)}")

    print("[4/5] driving the real engine against real Postgres")
    store = await PostgresVulnerabilityStore.connect(
        "postgresql://aqelyn:aqelyn@localhost:5432/aqelyn", mode=tenant_mode
    )
    engine = VulnerabilityIntelligenceEngine(
        store, threat_provider=KevExploitationProvider(catalog=catalog)
    )
    stored = await engine.ingest(records=list(parsed_vulns.records), tenant_id=tenant_id)
    print(f"      stored: {len(stored)}")

    print("[5/5] prioritizing")
    findings: list[Any] = []
    for record in stored[:200]:
        try:
            findings.append(await engine.prioritize(record.id, tenant_id=tenant_id))
        except Exception as exc:
            findings.append(exc)
    await store.close()

    return RunReport(
        target=target,
        tenant_mode=tenant_mode,
        sbom_components=len(sbom_raw.get("components", [])),
        sbom_parsed=len(parsed_sbom.components),
        grype_matches=len(vulns_raw.get("matches", [])),
        vuln_records=len(parsed_vulns.records),
        vuln_rejected=[(r.cve_id, r.component, r.reason) for r in parsed_vulns.rejected],
        join_total=join_total,
        join_matched=join_matched,
        stored=len(stored),
        findings=findings,
    )


class UnreadableFactor(Exception):
    """The reporter could not read a factor's status -- distinct from the platform
    not knowing the factor's value."""


@dataclass(frozen=True)
class FactorReading:
    name: str
    status: str
    reason: str
    source: str
    unknown_cause: FactorUnknownCause | None

    @property
    def closable(self) -> bool:
        """Whether this unknown represents actionable roadmap work.

        S-002/§3, the third reason category. Two unknowns look identical in a count
        and mean opposite things:

        The engine carries a typed cause. The reporter owns the exhaustive mapping
        from that fact to roadmap treatment; it never interprets display-oriented
        `source` text.

        The density report ranks by unknown count on the premise that unknowns are
        closable. Without this distinction, a factor that is wired and working sits
        near the top of the roadmap forever, recommending work that cannot be done.
        """
        return (
            self.status == "unknown"
            and self.unknown_cause is not None
            and _UNKNOWN_ROADMAP_CLASS[self.unknown_cause] == "closable"
        )


_UNKNOWN_ROADMAP_CLASS: dict[FactorUnknownCause, Literal["closable", "structural"]] = {
    "provider_unconfigured": "closable",
    "input_missing": "closable",
    "assessment_incomplete": "closable",
    "source_cannot_assert": "structural",
}
if frozenset(_UNKNOWN_ROADMAP_CLASS) != VALID_FACTOR_UNKNOWN_CAUSES:
    raise RuntimeError("density report must classify every registered factor unknown cause")


def read_factors(finding: Any) -> list[FactorReading]:
    """Read one finding's factors, or raise naming exactly what could not be read.

    Three states exist, and only two of them belong in a report: `known` and
    `unknown` are the platform speaking; **undetermined is the tool speaking**, and
    the tool does not get a row in a table about the platform.
    """
    payload = getattr(finding, "factors", None)
    if not isinstance(payload, dict) or not payload:
        raise UnreadableFactor(
            f"factors payload is {type(payload).__name__}, expected a non-empty dict"
        )
    readings: list[FactorReading] = []
    for name, factor in sorted(payload.items()):
        if not isinstance(factor, dict):
            raise UnreadableFactor(f"factor {name!r} is {type(factor).__name__}, expected a dict")
        status = factor.get("status")
        if status not in ("known", "unknown"):
            raise UnreadableFactor(
                f"factor {name!r} has status {status!r}, expected 'known' or 'unknown'"
            )
        reason = str(factor.get("reason") or "")
        if status == "unknown" and not reason.strip():
            raise UnreadableFactor(f"factor {name!r} is unknown but carries no reason")
        raw_unknown_cause = factor.get("unknown_cause")
        if status == "unknown":
            if raw_unknown_cause not in VALID_FACTOR_UNKNOWN_CAUSES:
                raise UnreadableFactor(
                    f"factor {name!r} is unknown but carries unregistered "
                    f"unknown_cause {raw_unknown_cause!r}"
                )
            unknown_cause = cast(FactorUnknownCause, raw_unknown_cause)
        else:
            if raw_unknown_cause is not None:
                raise UnreadableFactor(
                    f"factor {name!r} is known but carries unknown_cause {raw_unknown_cause!r}"
                )
            unknown_cause = None
        readings.append(
            FactorReading(
                name=name,
                status=status,
                reason=reason,
                source=str(factor.get("source") or ""),
                unknown_cause=unknown_cause,
            )
        )
    return readings


def coverage_factor_readings(coverage: CoverageReport) -> list[FactorReading]:
    """Reduce EA-0024 coverage gaps to value-free roadmap facts.

    The returned shape has no subject identifier, so the density emitter cannot
    carry per-asset detail outside the local estate.
    """

    return [
        FactorReading(
            name="vulnerability_coverage",
            status=gap.status,
            reason=gap.reason,
            source="ea0024:coverage",
            unknown_cause=gap.unknown_cause,
        )
        for gap in coverage.unassessable
    ]


def density_report(report: RunReport) -> None:
    """Per-factor known/unknown with reasons -- or a refusal, never a partial table.

    **The reporter refuses rather than renders when it cannot read its input.** A
    broken reporter and a genuinely all-unknown platform produce identical output
    (`known=0`, reasons `?`), and given reachability, ownership and exposure are
    unwired, all-unknown is the plausible real answer -- so the camouflage is maximal
    exactly when the answer matters most. Distinct rendering is not enough: a reader
    scanning a column of non-`known` rows cannot parse which are the platform's
    answer and which are the tool's failure.

    Same discipline as EA-0030's SBOM quarantine and GC-001's unclassifiable => fail,
    do not skip. A partially-readable decision artifact is worse than none, because
    it presents as a basis for the decision it is corrupting.
    """
    print("\n" + "=" * 74)
    print("UNKNOWN-DENSITY REPORT")
    print("=" * 74)

    print(
        f"\n-- mapper boundary ({len(report.vuln_rejected)} refused of {report.grype_matches}) --"
    )
    for reason, count in Counter(r[2] for r in report.vuln_rejected).most_common():
        print(f"  {count:5d}  {reason}")
    if not report.vuln_rejected:
        print("  none -- every match was representable")

    errors = [item for item in report.findings if isinstance(item, Exception)]
    priorities = [item for item in report.findings if not isinstance(item, Exception)]

    if errors:
        print(f"\n-- prioritization errors ({len(errors)}) --")
        for message, count in Counter(f"{type(e).__name__}: {e}" for e in errors).most_common(5):
            print(f"  {count:5d}  {message[:96]}")

    # Refuse before reporting: read every factor on every finding first.
    unreadable: list[str] = []
    per_finding: list[list[FactorReading]] = []
    for index, priority in enumerate(priorities):
        try:
            per_finding.append(read_factors(priority))
        except UnreadableFactor as exc:
            identifier = getattr(priority, "vulnerability_id", f"#{index}")
            unreadable.append(f"{identifier}: {exc}")

    if unreadable:
        print("\n" + "!" * 74)
        print("NO DENSITY REPORT PRODUCED -- the reporter could not read its input.")
        print("!" * 74)
        print(
            "\nThis is a refusal, not an empty result. `known=0 / unknown=0` would be\n"
            "indistinguishable from a platform that genuinely knows nothing, and this\n"
            "report decides what S-002 connects. It is not emitted on unread input.\n"
        )
        print(f"unreadable factors on {len(unreadable)} of {len(priorities)} findings:")
        for line in unreadable[:10]:
            print(f"  {line}")
        if len(unreadable) > 10:
            print(f"  ... and {len(unreadable) - 10} more")
        raise SystemExit(2)

    if not per_finding and not report.coverage_factors:
        print("\nno findings were prioritized -- nothing to report on")
        return

    known: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    structural: Counter[str] = Counter()
    reasons: dict[str, Counter[str]] = {}
    for readings in per_finding:
        for reading in readings:
            if reading.status == "known":
                known[reading.name] += 1
            else:
                unknown[reading.name] += 1
                if not reading.closable:
                    structural[reading.name] += 1
                reasons.setdefault(reading.name, Counter())[reading.reason] += 1
    for reading in report.coverage_factors:
        unknown[reading.name] += 1
        if not reading.closable:
            structural[reading.name] += 1
        reasons.setdefault(reading.name, Counter())[reading.reason] += 1

    total_factors = sum(known.values()) + sum(unknown.values())
    print(
        f"\n-- priority factors ({len(per_finding)} findings, "
        f"{len(report.coverage_factors)} coverage gaps, {total_factors} factors) --"
    )
    # ECR-0066: with a tie at the top the ordering stops recommending anything, and
    # breaking it by sort stability would make an owner's decision invisibly. The
    # report states the tie and stops there; the tie-break -- cheapest-to-wire, or
    # largest effect on score usefulness -- is not the tool's to make.
    closable = Counter({n: unknown[n] - structural[n] for n in unknown})
    if any(closable.values()):
        top = max(closable.values())
        tied = sorted(name for name, count in closable.items() if count == top and count > 0)
        if top > 0 and len(tied) > 1:
            print(
                f"\n  ** {len(tied)}-WAY TIE at {top} closable unknown: {', '.join(tied)}\n"
                "     The ordering below does NOT rank these. Choosing between them\n"
                "     is an owner decision, not a property of the data.\n"
            )
    # Ordered by unknown density. The ordering IS the roadmap; no commentary is
    # added, because a recommendation would be the tool making the owner's decision
    # and would obscure the one property that makes the ordering trustworthy -- that
    # it is mechanical.
    # Ranked by CLOSABLE unknowns. A structural unknown is not a roadmap entry: the
    # factor is wired and working, and the source cannot speak to that record.
    for name in sorted(set(known) | set(unknown), key=lambda n: (-closable[n], n)):
        total = known[name] + unknown[name]
        pct = unknown[name] / total * 100 if total else 0.0
        mark = (
            f"  [{structural[name]} structural: wired, source cannot assert]"
            if structural[name]
            else ""
        )
        print(
            f"  {name:12s} known={known[name]:4d} unknown={unknown[name]:4d} "
            f"({pct:3.0f}% unknown){mark}"
        )
        for reason, count in reasons.get(name, Counter()).most_common(2):
            print(f"       {count:4d}x {reason[:78]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="S-001 first real run")
    parser.add_argument("target", nargs="?", default="postgres:16")
    parser.add_argument("--tenant-mode", default="local", choices=["local", "enterprise"])
    parser.add_argument("--workdir", default=str(Path.home() / "aqelyn_slice"))
    parser.add_argument("--reuse", action="store_true", help="reuse existing scan output")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(drive(args.target, args.tenant_mode, workdir, reuse=args.reuse))
    density_report(report)


if __name__ == "__main__":
    main()
