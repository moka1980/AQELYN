"""C-035 batch conformance record for EA-0038 - EA-0050 (ECR-0060).

Thirteen archive masters from the same generator, resolved by one decision rather
than thirteen conformance passes. The batch replaces the *analyses*, not the
capability map: EA-0048 is the row where the same-generator heuristic gives the
wrong answer, and skipping the map would have certified that AI security is already
owned.

Three dispositions:

* **A — conformant via shipped owners** (eleven rows below).
* **B — open capability gap, not scheduled**: EA-0048.
* **C — non-capability**: EA-0050, alongside EA-0051.

These tests are deliberately light. The eleven rows restate owners already certified
by their own milestones, and GC-001/GC-002 are the mechanical backstop for the
capability claims. What they do *not* pin is the batch's own row-to-owner mapping,
which is what rots silently if a package is renamed or an EA renumbered. That is
what this file holds.
"""

from __future__ import annotations

import ast
import re
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "aqelyn"

# Disposition A. Each row: archive master -> the shipped package(s) that realize it,
# with the EA number each package declares in its own docstring. Verified against
# shipped code, not inferred from titles alone.
DISPOSITION_A: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "EA-0038 Vulnerability Intelligence Correlation": (
        "VulnerabilityIntelligenceEngine",
        (("vuln", "EA-0024"),),
    ),
    # Verbatim title match, and the engine is named for the fusion itself.
    "EA-0039 Threat Intelligence Fusion": (
        "ThreatFusionEngine",
        (("threat", "EA-0014"),),
    ),
    # This is IS-037's chain, certified by C-034.
    "EA-0040 Attack Path & Exposure Graph": (
        "KnownDataExposureEngine",
        (("exposure", "EA-0023"), ("graph", "EA-0005")),
    ),
    # Near-verbatim: the shipped package is "Security Data Lake & Telemetry Platform",
    # and it already owns both the lake and telemetry event prefixes (GC-002).
    "EA-0041 Security Data Lake & Telemetry Fabric": (
        "DataLakeService",
        (("lake", "EA-0019"),),
    ),
    "EA-0042 Detection Engineering & Analytics": (
        "ThreatDetectionEngine",
        (("detection", "EA-0017"),),
    ),
    "EA-0043 Incident Command & Case Management": (
        "SecurityOperationsEngine",
        (("soc", "EA-0015"), ("response", "EA-0018")),
    ),
    "EA-0044 Forensic Evidence Preservation": (
        "DigitalForensicsService",
        (("forensics", "EA-0016"), ("evidence", "EA-0004")),
    ),
    "EA-0045 Cyber Risk Quantification": (
        "RiskIntelligenceEngine",
        (("risk", "EA-0013"),),
    ),
    # Control validation and continuous assurance: Control / ControlResult /
    # FrameworkCoverage / ComplianceSnapshot all ship here.
    "EA-0046 Control Validation & Continuous Assurance": (
        "ComplianceEngine",
        (("governance", "EA-0010"),),
    ),
    "EA-0047 Supply Chain Security Governance": (
        "SupplyChainEngine",
        (("supplychain", "EA-0030"),),
    ),
    "EA-0049 Privacy, Data Protection & Sovereignty": (
        "DSPMEngine",
        (("dspm", "EA-0031"), ("governance", "EA-0010")),
    ),
}


def _package_docstring(package: str) -> str:
    source = (SRC / package / "__init__.py").read_text(encoding="utf-8")
    return ast.get_docstring(ast.parse(source), clean=False) or ""


def _declared_owners(root: Path, ea_number: str) -> list[Path]:
    """Discover owner declarations semantically, independent of package vocabulary."""
    owners: list[Path] = []
    for package_init in root.rglob("__init__.py"):
        source = package_init.read_text(encoding="utf-8")
        docstring = ast.get_docstring(ast.parse(source), clean=False) or ""
        declarations = set(re.findall(r"\bEA-\d{4}\b", docstring))
        if ea_number in declarations:
            owners.append(package_init)
    return sorted(owners)


def test_batch_disposition_a_owners_present() -> None:
    """Every Disposition-A row points at a package that declares the claimed EA.

    A row is confirmed by pointing at shipped code. This asserts the pointing still
    lands: if a package is renamed, removed, or renumbered, the batch record stops
    being true and this fails rather than rotting quietly.
    """
    for archive_master, (engine, owners) in DISPOSITION_A.items():
        for package, ea_number in owners:
            package_init = SRC / package / "__init__.py"
            assert package_init.is_file(), f"{archive_master}: no package {package!r}"
            assert ea_number in _package_docstring(package), (
                f"{archive_master}: package {package!r} no longer declares {ea_number}"
            )
        # The named engine/service is the API that realizes the archive capability.
        owning_package = owners[0][0]
        package_api = import_module(f"aqelyn.{owning_package}")
        exported = getattr(package_api, engine, None)
        assert exported is not None, (
            f"{archive_master}: {owning_package!r} no longer exports {engine!r} as an API"
        )
        assert getattr(exported, "__name__", None) == engine
        assert engine in getattr(package_api, "__all__", ()), (
            f"{archive_master}: {engine!r} is not in {owning_package!r}.__all__"
        )


def test_batch_ea0048_no_owner() -> None:
    """EA-0048 (AI Security & Model Governance) has no shipped owner.

    Disposition B rests entirely on this absence, so it is asserted rather than
    assumed. If someone builds AI/model governance, this fails and EA-0048 must be
    reclassified from "open gap" to an owned capability -- the record must not
    silently go stale in the direction that matters.

    EA-0020 `decision` ("AI Decision Intelligence Engine") is deliberately not the
    owner and is excluded below: it is AI used *by* AQELYN to produce replayable
    decisions over cases and claims. EA-0048 would be governance *of* customer AI/ML
    systems. Opposite directions; the question was asked and answered.
    """
    owners = _declared_owners(SRC, "EA-0048")
    assert owners == [], (
        "EA-0048 is recorded as an open capability gap, but packages now declare "
        f"ownership: {[path.relative_to(ROOT) for path in owners]}. Reclassify the row."
    )


def test_batch_ea0048_owner_discovery_is_name_independent(tmp_path: Path) -> None:
    """An owner under vocabulary the old keyword roster never anticipated is found."""
    package = tmp_path / "opaque_assurance"
    package.mkdir()
    (package / "__init__.py").write_text(
        '"""Opaque assurance capability (EA-0048)."""\n',
        encoding="utf-8",
    )

    assert _declared_owners(tmp_path, "EA-0048") == [package / "__init__.py"]


def test_batch_ea0020_is_not_the_ea0048_owner() -> None:
    """The false friend is guarded explicitly, so the rejection stays on the record.

    EA-0020 ships and is about AQELYN's own decision-making. Asserting what it *is*
    keeps a future reader from resolving EA-0048 to it on the strength of "AI" in
    both titles.
    """
    decision_init = _package_docstring("decision")
    assert "AI Decision Intelligence Engine (EA-0020)" in decision_init
    assert "EA-0048" not in set(re.findall(r"\bEA-\d{4}\b", decision_init))
