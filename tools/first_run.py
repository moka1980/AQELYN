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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hashlib

from aqelyn.conventions import ActorRef, new_id
from aqelyn.events import Subject
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.supplychain import SBOMDocument
from aqelyn.supplychain.parse import parse_sbom
from aqelyn.vuln import PostgresVulnerabilityStore, VulnerabilityIntelligenceEngine
from aqelyn.vuln.parse import parse_grype

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
    engine = VulnerabilityIntelligenceEngine(store)
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


def density_report(report: RunReport) -> None:
    """Per-factor known/unknown with reasons — the roadmap this run produces."""
    print("\n" + "=" * 74)
    print("UNKNOWN-DENSITY REPORT")
    print("=" * 74)

    print(
        f"\n-- mapper boundary ({len(report.vuln_rejected)} refused of {report.grype_matches}) --"
    )
    for reason, count in Counter(r[2] for r in report.vuln_rejected).most_common():
        print(f"  {count:5d}  {reason}")

    factors: Counter[str] = Counter()
    reasons: dict[str, Counter[str]] = {}
    errors: Counter[str] = Counter()
    for item in report.findings:
        if isinstance(item, Exception):
            errors[f"{type(item).__name__}: {item}"[:100]] += 1
            continue
        for name, factor in getattr(item, "factors", {}).items():
            known = getattr(factor, "value", None) not in (None, 0.0)
            factors[f"{name}:{'known' if known else 'unknown'}"] += 1
            if not known:
                reasons.setdefault(name, Counter())[getattr(factor, "reason", "?")[:70]] += 1

    if factors:
        print("\n-- priority factors --")
        names = sorted({k.rsplit(":", 1)[0] for k in factors})
        for name in names:
            known = factors.get(f"{name}:known", 0)
            unknown = factors.get(f"{name}:unknown", 0)
            pct = unknown / (known + unknown or 1) * 100
            print(f"  {name:22s} known={known:4d} unknown={unknown:4d} ({pct:3.0f}%)")
            for reason, count in reasons.get(name, Counter()).most_common(2):
                print(f"      {count:4d}x {reason}")
    if errors:
        print("\n-- prioritization errors --")
        for message, count in errors.most_common(5):
            print(f"  {count:5d}  {message}")


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
