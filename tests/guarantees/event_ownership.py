"""GC-002 event-namespace discovery, golden set, and derived ownership map.

Helpers live in ``tests/`` (never ``conventions``); GC-002 adds no runtime
surface. Enumeration is *discovery* — read from a constructed runtime's
``EventTypeRegistry`` — while the golden set and the ownership allow-list are the
frozen *review points*. The ownership map is **derived from evidence**: for every
registered event literal, the owning package is the one whose source registers
that literal (or the registry seed itself, for ``CORE_EVENTS``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from aqelyn.events.registry import CORE_EVENTS, EventTypeRegistry
from guarantees.discovery import GuaranteeViolation, aqelyn_source_root


def registry_of(runtime: object) -> EventTypeRegistry:
    """Return the wired ``EventTypeRegistry`` from a constructed runtime.

    The registry exposes no public enumeration API, so — exactly as GC-001
    inspects internal runtime attributes — GC-002 reads the wired registry off
    the runtime's event bus.
    """
    bus = getattr(runtime, "event_bus", None)
    registry = getattr(bus, "registry", None)
    if not isinstance(registry, EventTypeRegistry):
        raise GuaranteeViolation("constructed runtime exposes no EventTypeRegistry on its bus")
    return registry


def registered_event_types(runtime: object) -> frozenset[str]:
    """Discover every registered event type from the wired runtime registry."""
    registry = registry_of(runtime)
    return frozenset(registry._types)


def prefix_of(event_type: str) -> str:
    """``aqelyn.<owner>.<event_name>`` -> ``<owner>``."""
    parts = event_type.split(".")
    if len(parts) < 3 or parts[0] != "aqelyn":
        raise GuaranteeViolation(f"event type is not aqelyn.<owner>.<name>: {event_type!r}")
    return parts[1]


def registered_prefixes(runtime: object) -> frozenset[str]:
    return frozenset(prefix_of(event_type) for event_type in registered_event_types(runtime))


# --- AC-1: frozen golden set, grouped by owner (§3) ----------------------------
# Grouping is a requirement, not formatting: at 100+ event types a one-line
# addition to a flat list is invisible in review. Grouped, a diff reads
# "exposure gained an event" and keeps the reviewable question in front of the
# reviewer. Adding an event here is the deliberate, reviewed edit; silent
# widening in src/ fails until it lands here.
GOLDEN_EVENT_TYPES: Mapping[str, frozenset[str]] = {
    "cloud": frozenset(
        {
            "aqelyn.cloud.resource_normalized",
            "aqelyn.cloud.resource_unclassified",
        }
    ),
    "compliance": frozenset(
        {
            "aqelyn.compliance.assessment_completed",
            "aqelyn.compliance.posture_changed",
        }
    ),
    "config": frozenset(
        {
            "aqelyn.config.assessment_completed",
            "aqelyn.config.drift_detected",
        }
    ),
    "crypto": frozenset(
        {
            "aqelyn.crypto.certificate_expiring",
            "aqelyn.crypto.governance_scored",
            "aqelyn.crypto.lifecycle_unknown",
            "aqelyn.crypto.secret_detected",
            "aqelyn.crypto.weak_key_detected",
        }
    ),
    "data": frozenset(
        {
            "aqelyn.data.classification_conflict",
            "aqelyn.data.exposure_detected",
            "aqelyn.data.store_classified",
        }
    ),
    "decision": frozenset(
        {
            "aqelyn.decision.decision_recorded",
            "aqelyn.decision.model_promoted",
            "aqelyn.decision.recommendation_generated",
        }
    ),
    "detection": frozenset(
        {
            "aqelyn.detection.anomaly_detected",
            "aqelyn.detection.profile_updated",
            "aqelyn.detection.threat_detected",
        }
    ),
    "evidence": frozenset(
        {
            "aqelyn.evidence.recorded",
        }
    ),
    "executive": frozenset(
        {
            "aqelyn.executive.briefing_completed",
            "aqelyn.executive.dashboard_updated",
            "aqelyn.executive.kpi_calculated",
            "aqelyn.executive.report_issued",
            "aqelyn.executive.summary_generated",
        }
    ),
    "exposure": frozenset(
        {
            "aqelyn.exposure.asset_discovered",
            "aqelyn.exposure.attack_surface_updated",
            "aqelyn.exposure.closed",
            "aqelyn.exposure.detected",
            "aqelyn.exposure.score_updated",
        }
    ),
    "finding": frozenset(
        {
            "aqelyn.finding.raised",
            "aqelyn.finding.regressed",
            "aqelyn.finding.status_changed",
        }
    ),
    "forecast": frozenset(
        {
            "aqelyn.forecast.generated",
            "aqelyn.forecast.scored",
            "aqelyn.forecast.trend_detected",
        }
    ),
    "forensics": frozenset(
        {
            "aqelyn.forensics.artifact_cataloged",
            "aqelyn.forensics.case_packaged",
            "aqelyn.forensics.evidence_verified",
        }
    ),
    "iag": frozenset(
        {
            "aqelyn.iag.certification_completed",
            "aqelyn.iag.certification_opened",
            "aqelyn.iag.item_decided",
            "aqelyn.iag.risk_detected",
        }
    ),
    "idthreat": frozenset(
        {
            "aqelyn.idthreat.credential_anomaly",
            "aqelyn.idthreat.detected",
            "aqelyn.idthreat.privilege_use",
            "aqelyn.idthreat.reviewed",
        }
    ),
    "inventory": frozenset(
        {
            "aqelyn.inventory.asset_discovered",
            "aqelyn.inventory.asset_reconciled",
            "aqelyn.inventory.asset_unreported",
            "aqelyn.inventory.lifecycle_changed",
            "aqelyn.inventory.relationship_updated",
        }
    ),
    "ispm": frozenset(
        {
            "aqelyn.ispm.controls_unknown",
            "aqelyn.ispm.identity_normalized",
            "aqelyn.ispm.posture_drift_detected",
            "aqelyn.ispm.posture_scored",
        }
    ),
    "kernel": frozenset(
        {
            "aqelyn.kernel.runtime_started",
            "aqelyn.kernel.runtime_stopped",
        }
    ),
    "lake": frozenset(
        {
            "aqelyn.lake.archived",
            "aqelyn.lake.retention_applied",
        }
    ),
    "object": frozenset(
        {
            "aqelyn.object.created",
            "aqelyn.object.merged",
            "aqelyn.object.state_changed",
            "aqelyn.object.updated",
        }
    ),
    "policy": frozenset(
        {
            "aqelyn.policy.decision_denied",
            "aqelyn.policy.updated",
        }
    ),
    "relationship": frozenset(
        {
            "aqelyn.relationship.created",
        }
    ),
    "response": frozenset(
        {
            "aqelyn.response.approval_routed",
            "aqelyn.response.campaign_completed",
            "aqelyn.response.campaign_planned",
            "aqelyn.response.phase_completed",
            "aqelyn.response.started",
        }
    ),
    "risk": frozenset(
        {
            "aqelyn.risk.identified",
            "aqelyn.risk.score_changed",
            "aqelyn.risk.treated",
        }
    ),
    "saas": frozenset(
        {
            "aqelyn.saas.app_normalized",
            "aqelyn.saas.app_unclassified",
            "aqelyn.saas.integration_detected",
        }
    ),
    "soc": frozenset(
        {
            "aqelyn.soc.alert_raised",
            "aqelyn.soc.incident_created",
            "aqelyn.soc.incident_status_changed",
            "aqelyn.soc.response_proposed",
        }
    ),
    "supplychain": frozenset(
        {
            "aqelyn.supplychain.dependency_risk_detected",
            "aqelyn.supplychain.provenance_failed",
            "aqelyn.supplychain.sbom_ingested",
        }
    ),
    "telemetry": frozenset(
        {
            "aqelyn.telemetry.ingested",
            "aqelyn.telemetry.quarantined",
        }
    ),
    "threat": frozenset(
        {
            "aqelyn.threat.indicator_ingested",
            "aqelyn.threat.match_detected",
            "aqelyn.threat.updated",
        }
    ),
    "vuln": frozenset(
        {
            "aqelyn.vuln.discovered",
            "aqelyn.vuln.exploit_correlated",
            "aqelyn.vuln.prioritized",
            "aqelyn.vuln.reassessed",
            "aqelyn.vuln.remediation_recommended",
        }
    ),
    "workflow": frozenset(
        {
            "aqelyn.workflow.approval_granted",
            "aqelyn.workflow.run_completed",
            "aqelyn.workflow.run_failed",
            "aqelyn.workflow.run_halted",
            "aqelyn.workflow.run_proposed",
            "aqelyn.workflow.run_simulated",
            "aqelyn.workflow.step_executed",
        }
    ),
}


def golden_event_types() -> frozenset[str]:
    """Flatten the grouped golden set into the full frozen event-type set."""
    flat: set[str] = set()
    for group in GOLDEN_EVENT_TYPES.values():
        flat |= group
    return frozenset(flat)


# --- AC-2: derived, reasoned prefix -> package ownership (§4) -------------------
@dataclass(frozen=True)
class OwnershipEntry:
    """One reasoned allow-list entry, mirroring GC-001's ``EXECUTION_SCAN_EXCLUSIONS``.

    ``package`` is a real shipped directory under ``src/aqelyn/``. ``reason``
    records *why* this prefix belongs to that package — carried because adding to
    an allow-list is a visible reviewable act while omission from a registry is
    silent. ``core_seeded`` marks the ``CORE_EVENTS`` prefixes: they are seeded by
    the registry itself, not by a ``register_*_events`` owner — a different
    ownership shape, not an exception to the rule.
    """

    package: str
    reason: str
    core_seeded: bool = False


# Derived from evidence (the package whose source registers each literal), NOT
# from the brief's table. Non-1:1 naming, many-to-one ownership (lake owns both
# `lake` and `telemetry`; objects owns both `object` and `relationship`), and
# CORE_EVENTS seeding are all present in shipped code and all represented here.
PREFIX_OWNERSHIP: Mapping[str, OwnershipEntry] = {
    "cloud": OwnershipEntry(
        "cspm", "EA-0021 CSPM normalizes cloud resources (register_cspm_events)."
    ),
    "compliance": OwnershipEntry(
        "governance", "EA-0010 governance emits compliance posture (register_compliance_events)."
    ),
    "config": OwnershipEntry(
        "assetconfig", "EA-0020 asset-config governance owns config drift (register_acg_events)."
    ),
    "crypto": OwnershipEntry(
        "secrets", "EA-0032 secrets/cryptographic-asset engine (register_crypto_events)."
    ),
    "data": OwnershipEntry("dspm", "EA-0031 DSPM classifies data stores (register_dspm_events)."),
    "decision": OwnershipEntry(
        "decision", "Decision-intelligence package registers its own events."
    ),
    "detection": OwnershipEntry("detection", "Detection package registers its own events."),
    "evidence": OwnershipEntry("evidence", "Evidence package registers its own event."),
    "executive": OwnershipEntry("executive", "Executive package registers its own events."),
    "exposure": OwnershipEntry("exposure", "EA-0037 exposure package registers its own events."),
    "finding": OwnershipEntry(
        "findings", "Findings package owns the `finding` prefix (register_finding_events)."
    ),
    "forecast": OwnershipEntry("forecast", "Forecast package registers its own events."),
    "forensics": OwnershipEntry("forensics", "Forensics package registers its own events."),
    "iag": OwnershipEntry("iag", "Identity-analytics-governance package registers its own events."),
    "idthreat": OwnershipEntry("idthreat", "Identity-threat package registers its own events."),
    "inventory": OwnershipEntry("inventory", "Inventory package registers its own events."),
    "ispm": OwnershipEntry("ispm", "EA-0033 ISPM package registers its own events."),
    "kernel": OwnershipEntry(
        "kernel",
        "CORE_EVENTS seeded by events/registry.py; runtime lifecycle owned by kernel.",
        core_seeded=True,
    ),
    "lake": OwnershipEntry("lake", "EA-0019 data lake owns `lake` (register_lake_events)."),
    "object": OwnershipEntry(
        "objects",
        "CORE_EVENTS seeded by events/registry.py; object lifecycle owned by objects.",
        core_seeded=True,
    ),
    "policy": OwnershipEntry("policy", "Policy package registers its own events."),
    "relationship": OwnershipEntry(
        "objects",
        "CORE_EVENTS seeded by events/registry.py; relationships owned by objects.",
        core_seeded=True,
    ),
    "response": OwnershipEntry("response", "Response package registers its own events."),
    "risk": OwnershipEntry("risk", "Risk package registers its own events."),
    "saas": OwnershipEntry("sspm", "EA SSPM normalizes SaaS apps (register_sspm_events)."),
    "soc": OwnershipEntry("soc", "SOC package registers its own events."),
    "supplychain": OwnershipEntry("supplychain", "Supply-chain package registers its own events."),
    "telemetry": OwnershipEntry(
        "lake", "EA-0019 data lake also owns `telemetry` (many-to-one with `lake`)."
    ),
    "threat": OwnershipEntry("threat", "Threat-intel package registers its own events."),
    "vuln": OwnershipEntry("vuln", "Vulnerability package registers its own events."),
    "workflow": OwnershipEntry("workflow", "EA-0008 workflow engine (register_workflow_events)."),
}


def package_registers_prefix(package: str, prefix: str, *, core_seeded: bool) -> bool:
    """Evidence check: does ``package``'s shipped source actually own ``prefix``?

    For a ``register_*_events`` owner, the package's source must contain a literal
    ``"aqelyn.<prefix>."``. For a ``CORE_EVENTS``-seeded prefix, the evidence is
    the registry seed itself — the prefix appears in ``CORE_EVENTS``. This keeps
    the allow-list honest: an entry naming a package that does not register the
    prefix is a guess, and fails.
    """
    if core_seeded:
        return any(prefix_of(event_type) == prefix for event_type in CORE_EVENTS)
    package_root = aqelyn_source_root() / package
    if not package_root.is_dir():
        return False
    needle = f"aqelyn.{prefix}."
    return any(needle in path.read_text(encoding="utf-8") for path in package_root.rglob("*.py"))


def assert_event_types_frozen(observed: frozenset[str]) -> None:
    """AC-1 closure: the discovered set must equal the frozen golden set.

    Raised explicitly (never via bare ``assert``) so an assertion-stripped
    ``python -O`` build still refuses. The message names the offending event type
    and its prefix, so the reviewable question is immediate.
    """
    golden = golden_event_types()
    unexpected = observed - golden
    missing = golden - observed
    if unexpected:
        offender = sorted(unexpected)[0]
        raise GuaranteeViolation(
            "event type registered outside the frozen golden set: "
            f"{offender!r} (prefix {prefix_of(offender)!r}); "
            f"all unexpected={sorted(unexpected)}"
        )
    if missing:
        raise GuaranteeViolation(f"golden event types no longer registered: {sorted(missing)}")


def assert_prefix_ownership(prefixes: frozenset[str]) -> None:
    """AC-2 ownership: every registered prefix maps to a real shipped package.

    A prefix with no allow-list entry fails (the `aqelyn.cyber.*` case). An entry
    naming a package that does not exist, or does not register the prefix, fails
    as a guess. Raised explicitly to survive ``python -O``.
    """
    for prefix in sorted(prefixes):
        entry = PREFIX_OWNERSHIP.get(prefix)
        if entry is None:
            raise GuaranteeViolation(
                f"event prefix aqelyn.{prefix}.* has no owning package in PREFIX_OWNERSHIP; "
                "a new prefix for an existing capability is a parallel namespace"
            )
        if not (aqelyn_source_root() / entry.package).is_dir():
            raise GuaranteeViolation(
                f"prefix aqelyn.{prefix}.* names package {entry.package!r}, "
                "which is not a shipped package"
            )
        if not package_registers_prefix(entry.package, prefix, core_seeded=entry.core_seeded):
            raise GuaranteeViolation(
                f"prefix aqelyn.{prefix}.* is allow-listed to {entry.package!r}, but that package "
                "does not register the prefix — the ownership entry is a guess, not evidence"
            )
        if not entry.reason.strip():
            raise GuaranteeViolation(f"ownership entry for aqelyn.{prefix}.* carries no reason")


def source_root_has_no_guarantee_surface() -> bool:
    """AC-4: GC-002 added nothing under ``src/aqelyn/``."""
    root = aqelyn_source_root()
    return not (root / "guarantees").exists() and not (root / "gc002").exists()


def this_helper_is_under_tests() -> bool:
    return Path(__file__).resolve().parent.parent.name == "tests"
