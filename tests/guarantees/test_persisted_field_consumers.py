"""GC-004: every written field is consumed, dormant, exempt, or fails."""

from __future__ import annotations

from pathlib import Path

import pytest

from guarantees.discovery import GuaranteeViolation, aqelyn_source_root
from guarantees.persisted_fields import (
    DORMANT_FIELDS,
    EXEMPT_FIELDS,
    FieldClassification,
    assert_persisted_fields_consumed,
    classify_persisted_fields,
    discover_persisted_fields,
    discover_whole_record_writers,
)

CONTROL_ROOT = Path(__file__).resolve().parent / "controls" / "persisted_fields"
CONTROL_DORMANT = {
    "writer.dormant_probe": (
        "The synthetic external reader exists, but the control declares that no shipped path "
        "can produce its state."
    )
}
CONTROL_EXEMPT = {
    "writer.alias_left": "Synthetic union-alias field has no external reader by design.",
    "writer.alias_right": "Synthetic union-alias field has no external reader by design.",
    "writer.bare_only": "Synthetic bare whole-record writer has no external reader by design.",
    "writer.conforming_only": (
        "Synthetic convention-named whole-record writer has no external reader by design."
    ),
    "writer.direct_only": "Synthetic direct memory mutation has no external reader by design.",
    "writer.id": "Synthetic Postgres identity is internal to the control store.",
    "writer.memory_only": "Synthetic memory-only field has no external reader by design.",
    "writer.owner_only": "Synthetic field is deliberately read only by its owning package.",
    "writer.postgres_only": "Synthetic Postgres-only field has no external reader by design.",
}


def test_gc004_population_is_write_defined() -> None:
    population = {field.key: field for field in discover_persisted_fields(CONTROL_ROOT)}

    assert "writer.capacity_only" not in population
    assert "writer.ddl_only" not in population
    assert population["writer.alias_left"].backends == frozenset({"memory"})
    assert population["writer.alias_right"].backends == frozenset({"memory"})
    assert population["writer.bare_only"].backends == frozenset({"memory"})
    assert population["writer.conforming_only"].backends == frozenset({"memory"})
    assert population["writer.direct_only"].backends == frozenset({"memory"})
    assert population["writer.memory_only"].backends == frozenset({"memory"})
    assert population["writer.postgres_only"].backends == frozenset({"postgres"})
    assert {
        "writer.AliasLog",
        "writer.InMemoryControlStore",
        "writer.InMemoryWholeRecordStore",
        "writer.ProbeLog",
    } <= discover_whole_record_writers(CONTROL_ROOT)


def test_gc004_backend_write_divergence_surfaces() -> None:
    population = {field.key: field for field in discover_persisted_fields(CONTROL_ROOT)}

    assert population["writer.dormant_probe"].backends == frozenset({"memory"})
    assert population["writer.id"].backends == frozenset({"postgres"})
    assert population["writer.memory_only"].backends != population["writer.postgres_only"].backends


def test_gc004_reader_outside_owning_package_detected() -> None:
    classified = classify_persisted_fields(
        CONTROL_ROOT,
        dormant_fields=CONTROL_DORMANT,
        exempt_fields=_control_exempt(include_unconsumed=True),
    )

    assert classified["writer.dormant_probe"].readers == ("reader",)


def test_gc004_reader_inside_owning_package_does_not_count() -> None:
    classified = classify_persisted_fields(
        CONTROL_ROOT,
        dormant_fields=CONTROL_DORMANT,
        exempt_fields=_control_exempt(include_unconsumed=True),
    )

    owner_only = classified["writer.owner_only"]
    assert owner_only.readers == ()
    assert owner_only.state == "exempt"


def test_gc004_dormant_registry_pinned() -> None:
    assert DORMANT_FIELDS == {
        "findings.current_severity_score": (
            "The only divergence point is re-emission in findings/memory.py, while the "
            "shipped reporting path constructs a fresh store for each run."
        )
    }


def test_gc004_exempt_registry_pinned() -> None:
    assert _expected_exempt_fields() == EXEMPT_FIELDS


@pytest.mark.parametrize("selected_registry", ["dormant", "exempt"])
def test_gc004_registry_entry_without_reason_rejected(selected_registry: str) -> None:
    dormant = dict(CONTROL_DORMANT)
    exempt = dict(CONTROL_EXEMPT)
    if selected_registry == "dormant":
        dormant["writer.dormant_probe"] = ""
    else:
        exempt["writer.owner_only"] = ""

    with pytest.raises(GuaranteeViolation, match="registry entries require reasons"):
        classify_persisted_fields(
            CONTROL_ROOT,
            dormant_fields=dormant,
            exempt_fields=exempt,
        )


def test_gc004_dormant_entry_without_external_reader_rejected() -> None:
    dormant = {**CONTROL_DORMANT, "writer.owner_only": "Synthetic invalid dormant entry."}
    exempt = {key: value for key, value in CONTROL_EXEMPT.items() if key != "writer.owner_only"}

    with pytest.raises(GuaranteeViolation, match="dormant field has no discovered external reader"):
        classify_persisted_fields(
            CONTROL_ROOT,
            dormant_fields=dormant,
            exempt_fields=exempt,
        )


def test_gc004_exempt_entry_with_external_reader_rejected() -> None:
    exempt = {**CONTROL_EXEMPT, "writer.dormant_probe": "Synthetic invalid exemption."}

    with pytest.raises(GuaranteeViolation, match="exempt field has discovered external readers"):
        classify_persisted_fields(
            CONTROL_ROOT,
            dormant_fields={},
            exempt_fields=exempt,
        )


def test_gc004_classification_is_returned_not_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    classified = classify_persisted_fields(
        CONTROL_ROOT,
        dormant_fields=CONTROL_DORMANT,
        exempt_fields=_control_exempt(include_unconsumed=True),
    )

    assert isinstance(classified, dict)
    assert all(isinstance(value, FieldClassification) for value in classified.values())
    assert capsys.readouterr() == ("", "")


def test_gc004_control_no_reader_fails() -> None:
    with pytest.raises(GuaranteeViolation, match=r"writer\.unconsumed_probe"):
        assert_persisted_fields_consumed(
            CONTROL_ROOT,
            dormant_fields=CONTROL_DORMANT,
            exempt_fields=CONTROL_EXEMPT,
        )


def test_gc004_control_declared_dormant_passes() -> None:
    classified = assert_persisted_fields_consumed(
        CONTROL_ROOT,
        dormant_fields=CONTROL_DORMANT,
        exempt_fields=_control_exempt(include_unconsumed=True),
    )

    assert all(item.state != "unconsumed" for item in classified.values())


def test_gc004_control_dormant_classified_dormant_not_consumed() -> None:
    classified = assert_persisted_fields_consumed(
        CONTROL_ROOT,
        dormant_fields=CONTROL_DORMANT,
        exempt_fields=_control_exempt(include_unconsumed=True),
    )

    assert classified["writer.dormant_probe"].state == "dormant"


def test_gc004_all_production_fields_classified() -> None:
    classified = assert_persisted_fields_consumed()

    assert classified
    assert classified["findings.current_severity_score"].state == "dormant"
    assert classified["findings.current_severity_score"].readers == ("reporting",)
    assert all(item.state != "unconsumed" for item in classified.values())


def test_gc004_has_no_runtime_surface() -> None:
    assert not (aqelyn_source_root() / "guarantees").exists()
    assert Path(__file__).resolve().parent.name == "guarantees"


def _control_exempt(*, include_unconsumed: bool) -> dict[str, str]:
    selected = dict(CONTROL_EXEMPT)
    if include_unconsumed:
        selected["writer.unconsumed_probe"] = (
            "Synthetic no-reader field is exempt only for controls that exercise other states."
        )
    return selected


def _expected_exempt_fields() -> dict[str, str]:
    groups: tuple[tuple[str, tuple[str, ...], str], ...] = (
        (
            "assetconfig",
            (
                "coverage_by_object_type",
                "coverage_complete",
                "coverage_incomplete_reason",
                "objects_assessed",
                "objects_in_scope",
                "unassessed_object_ids",
            ),
            "EA-0012 keeps baseline coverage accounting inside its owner for audit and replay; "
            "the shipped cross-package contract exposes the resulting drift, not these fields.",
        ),
        (
            "cspm",
            ("unreported_facts",),
            "EA-0028 keeps unreported normalization facts inside its owner and exposes derived "
            "posture records across package boundaries.",
        ),
        (
            "decision",
            (
                "action_hint",
                "applied",
                "feedback",
                "proposed_change",
                "recommendation_id",
                "tenant_key",
            ),
            "EA-0021 persists model-selection bookkeeping inside its owner; callers consume "
            "the validated recommendation contract.",
        ),
        (
            "detection",
            ("insufficient_data", "subject_type", "technique_ids"),
            "EA-0006 keeps profile and rule bookkeeping inside its owner; external consumers "
            "use the resulting detections.",
        ),
        (
            "dspm",
            (
                "access_claims",
                "access_evidence_ids",
                "classification_status",
                "classified_fields",
                "coverage_reason",
                "coverage_status",
                "data_asset_id",
                "exposure_ref",
                "field_classifications",
                "gap_ids",
                "max_known_sensitivity",
                "reachability_claim",
                "store_id",
                "store_type",
                "stores_evaluated",
                "tenant_key",
                "unknown_fields",
            ),
            "EA-0031 keeps normalized store identity and classification bookkeeping inside "
            "its owner; external consumers use posture and exposure outputs.",
        ),
        (
            "evidence",
            ("anchor", "manifest_hash", "package_hash"),
            "EA-0002 keeps integrity-chain material inside the evidence owner; callers consume "
            "verification outcomes rather than recomputing these fields.",
        ),
        (
            "events",
            ("attempts", "causation_id", "consumer", "trace_id"),
            "EA-0003 keeps delivery-attempt and trace bookkeeping inside the event owner; "
            "external consumers receive validated Event envelopes through the bus contract.",
        ),
        (
            "executive",
            (
                "approval_status",
                "combinator",
                "exceptions",
                "issued_by",
                "kpi_key",
                "period",
                "sections",
                "unit",
            ),
            "EA-0022 keeps report-definition and issuance bookkeeping inside its owner; "
            "external consumers receive the assembled report.",
        ),
        (
            "exposure",
            ("validated_at",),
            "EA-0023 retains validation provenance inside its owner; consumers use the scored "
            "exposure record.",
        ),
        (
            "findings",
            ("resolved_at",),
            "EA-0003 owns lifecycle timestamps; cross-package consumers use the finding status "
            "and store APIs rather than this persistence field directly.",
        ),
        (
            "forecast",
            ("resolves_at", "tenant_key"),
            "EA-0020 keeps forecast resolution and model-key bookkeeping inside its owner; "
            "callers consume validated forecasts.",
        ),
        (
            "forensics",
            ("acquisition_id", "artifact_type", "linked_asset_ids"),
            "EA-0015 keeps artifact acquisition and linkage bookkeeping inside its owner; "
            "callers consume validated artifact records.",
        ),
        (
            "governance",
            ("framework_scores",),
            "EA-0010 retains framework component scores inside its owner; external consumers "
            "use the composed compliance snapshot.",
        ),
        (
            "idthreat",
            (
                "corroboration",
                "detection_type",
                "entitlement_refs",
                "profile_ref",
                "reviewed_by",
            ),
            "EA-0027 keeps detection corroboration and review bookkeeping inside its owner; "
            "external consumers use findings and review outcomes.",
        ),
        (
            "inventory",
            ("discovery_source", "unreported_since"),
            "EA-0025 owns discovery and reconciliation bookkeeping; consumers use reconciled "
            "assets and ownership results.",
        ),
        (
            "ispm",
            (
                "account_object_ids",
                "approved_at",
                "approved_by",
                "drift_snapshot_id",
                "iag_risks",
                "identities_evaluated",
                "inventory_complete",
                "inventory_note",
                "relationship_ids",
                "score_ids",
                "unknown_controls",
            ),
            "EA-0033 keeps normalized relationship, assessment, and approval bookkeeping "
            "inside its owner; external consumers use posture scores, drift, and delegated "
            "IAG outputs.",
        ),
        (
            "lake",
            (
                "archived_at",
                "classifications",
                "dataset",
                "indexed_fields",
                "ingested_at",
                "legal_hold",
                "raw_ref",
                "record_count",
                "retention_policy_id",
                "retention_state",
                "schema",
                "schema_",
            ),
            "EA-0019 keeps dataset, retention, and archive bookkeeping inside the lake owner; "
            "external consumers use query and retention operations.",
        ),
        (
            "objects",
            ("changed_by", "merged_into"),
            "EA-0005 owns object history and merge bookkeeping; consumers use current objects "
            "and relationships.",
        ),
        (
            "policy",
            ("standard",),
            "EA-0009 keeps policy-standard metadata inside its owner; callers consume "
            "authorization decisions.",
        ),
        (
            "response",
            ("escalate_to", "max_effect", "requested_at", "sla_seconds"),
            "EA-0018 owns bounded-effect campaign metadata; callers consume gated campaign "
            "and workflow outcomes.",
        ),
        (
            "risk",
            (
                "band_counts",
                "overall_exposure",
                "top_risks",
                "treated_by",
                "treatment",
                "treatment_note",
            ),
            "EA-0013 keeps snapshot composition and treatment bookkeeping inside its owner; "
            "external consumers use scored risk records and findings.",
        ),
        (
            "secrets",
            (
                "active_critical_exposure_ids",
                "assets_evaluated",
                "certificates",
                "expiry",
                "expiring_soon",
                "external_key_ref",
                "governance_incomplete_reason",
                "governance_score_ids",
                "governance_scoring_status",
                "issuer",
                "key_size",
                "last_rotated_at",
                "not_after",
                "revocation",
                "rotation",
                "serial",
                "secrets",
                "strength",
                "unknown_lifecycle",
                "usages",
            ),
            "EA-0032 keeps lifecycle inventory and governance-assessment bookkeeping inside "
            "its owner; external consumers use value-free crypto assets, scores, and proposals.",
        ),
        (
            "soc",
            ("alert_ids", "assignee", "timeline"),
            "EA-0017 owns incident assembly and assignment bookkeeping; callers consume SOC "
            "alerts and incidents through its service boundary.",
        ),
        (
            "sspm",
            (
                "grantor_kind",
                "grantor_ref",
                "integration_id",
                "known_surface_ref",
                "over_scoped",
                "provider_tenant",
                "reach_status",
                "reachable_object_ids",
                "scopes",
                "third_party_app",
                "third_party_external",
            ),
            "EA-0029 keeps SaaS normalization and reachability bookkeeping inside its owner; "
            "external consumers use posture and exposure outputs.",
        ),
        (
            "supplychain",
            (
                "assessment_status",
                "component_type",
                "components",
                "doc_id",
                "licenses",
                "locations",
                "provenance_status",
                "supplier",
                "transitive",
                "unverified_provenance",
                "vulnerable_components",
            ),
            "EA-0030 keeps SBOM document and component provenance inside its owner; external "
            "consumers use vulnerability prioritization and findings.",
        ),
        (
            "threat",
            ("meta",),
            "EA-0016 keeps source metadata inside its owner; consumers use normalized threat "
            "signals and factor-provider outputs.",
        ),
        (
            "vuln",
            ("cvss", "disposition", "epss"),
            "EA-0024 keeps raw prioritization inputs and disposition inside its owner; external "
            "consumers use the resulting priority and coverage.",
        ),
        (
            "workflow",
            ("approvals",),
            "EA-0008 owns approval history and evaluates it internally before any action; "
            "external consumers use workflow state and outcomes.",
        ),
        (
            "identity",
            ("email", "redeemed_by"),
            "ECR-0116 keeps the login address and single-use invite bookkeeping inside the "
            "identity owner: callers authenticate through the store methods (get_by_email / "
            "authenticate) rather than reading the email field, and redeemed_by is read only "
            "within the invite store to refuse reuse. No external consumer references either.",
        ),
        (
            "consent",
            ("actor_account_id", "revoked_at", "text_version"),
            "ECR-0117 keeps consent lifecycle and audit-actor bookkeeping inside its owner: "
            "external consumers receive ConsentRecord / AuditEvent envelopes through the "
            "store's active() and list() methods rather than reading revoked_at, text_version "
            "or the acting-account field directly.",
        ),
    )
    return {f"{owner}.{field}": reason for owner, fields, reason in groups for field in fields}
