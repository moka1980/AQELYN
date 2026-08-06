"""ECR-0102 witnesses for the self-scan collector.

The collector's one dangerous failure mode is reporting a machine as clean because a check
did not run. Most of what follows exists to make that impossible to do quietly.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqelyn.collect.checks import observations_for
from aqelyn.collect.cli import build_documents, write_collection
from aqelyn.collect.host import (
    HostFacts,
    Listener,
    parse_listeners,
    parse_pending_updates,
    parse_ssh_password_auth,
    read_host_facts,
)
from aqelyn.reporting.posture import validate_posture_shape

NOW = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)


# --- parsing ---------------------------------------------------------------------------


def test_wildcard_binds_normalise_to_all_interfaces() -> None:
    listeners = parse_listeners(
        "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 128 *:80 *:*\nLISTEN 0 128 [::]:443 [::]:*\n"
    )
    assert {item.bind for item in listeners} == {"0.0.0.0"}
    assert {item.port for item in listeners} == {22, 80, 443}


def test_loopback_binds_are_not_public() -> None:
    listeners = parse_listeners("LISTEN 0 128 127.0.0.1:8082 0.0.0.0:*\n")
    assert [item.is_public for item in listeners] == [False]


def test_ipv6_loopback_is_not_public() -> None:
    listeners = parse_listeners("LISTEN 0 128 [::1]:9000 [::]:*\n")
    assert [item.is_public for item in listeners] == [False]


def test_interface_scope_suffix_is_stripped() -> None:
    """`127.0.0.53%lo:53` is loopback; failing to strip the scope would call it public."""
    listeners = parse_listeners("LISTEN 0 128 127.0.0.53%lo:53 0.0.0.0:*\n")
    assert [item.is_public for item in listeners] == [False]


def test_pending_updates_counts_only_install_lines() -> None:
    output = "Inst libc6 [1.0]\nConf libc6 [1.1]\nInst openssl [3.0]\nReading state...\n"
    assert parse_pending_updates(output) == 2


def test_ssh_password_auth_reads_the_first_effective_directive() -> None:
    """ECR-0110 corrected this. It asserted LAST-wins, which is not what sshd does:
    "unless noted otherwise, for each keyword, the first obtained value will be used".
    Proven against a real sshd with `sshd -T -f` on two-line configs in both orders, after
    the live VPS turned up two drop-ins that disagree."""
    assert (
        parse_ssh_password_auth("PasswordAuthentication yes\nPasswordAuthentication no\n") is True
    )


def test_ssh_commented_directive_is_not_evidence() -> None:
    """A commented line leaves the build default in force, which we have not read."""
    assert parse_ssh_password_auth("#PasswordAuthentication yes\n") is None


def test_ssh_absent_directive_is_unmeasured_not_false() -> None:
    assert parse_ssh_password_auth("Port 22\n") is None


# --- facts: unreadable is recorded, never defaulted --------------------------------------


def _runner(responses: dict[str, tuple[int, str]]) -> Any:
    def run(argv: Sequence[str]) -> tuple[int, str] | None:
        return responses.get(argv[0])

    return run


def test_a_host_that_answers_nothing_reports_every_fact_unreadable(tmp_path: Path) -> None:
    facts = read_host_facts(
        _runner({}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
    )
    assert facts.listeners is None
    assert facts.firewall_active is None
    assert facts.pending_updates is None
    for fact in ("hostname", "kernel", "listeners", "firewall", "pending_updates"):
        assert fact in facts.unreadable


def test_an_absent_firewall_is_unreadable_not_inactive(tmp_path: Path) -> None:
    """The difference between 'no firewall' and 'we could not look' is the whole point."""
    facts = read_host_facts(
        _runner({"hostname": (0, "box\n")}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
    )
    assert facts.firewall_active is None
    assert "firewall" in facts.unreadable


def test_an_installed_inactive_firewall_is_read_as_inactive(tmp_path: Path) -> None:
    facts = read_host_facts(
        _runner({"hostname": (0, "box\n"), "ufw": (0, "Status: inactive\n")}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
    )
    assert facts.firewall_active is False
    assert "firewall" not in facts.unreadable


# --- checks ------------------------------------------------------------------------------


def test_unreadable_listeners_produce_an_unmeasured_observation() -> None:
    observations = observations_for(HostFacts(listeners=None), subject_ref="box")
    unmeasured = [item for item in observations if item["observed"].get("unmeasured")]
    assert any(item["observed"]["fact"] == "listeners" for item in unmeasured)


def test_every_unreadable_fact_produces_its_own_unmeasured_observation() -> None:
    """Counting only the unmeasured observations that exist cannot catch a missing one."""
    observations = observations_for(HostFacts(), subject_ref="box")
    facts_reported = {
        item["observed"]["fact"] for item in observations if item["observed"].get("unmeasured")
    }
    # ECR-0107 added two facts and this equality is what forced the list to be updated
    # rather than quietly under-reporting. That is the whole point of asserting the set.
    assert facts_reported == {
        "listeners",
        "firewall",
        "pending_updates",
        "unattended_upgrades",
        "disk_encryption",
        "ssh_password_auth",
    }


def test_an_unparsable_bind_address_is_treated_as_public() -> None:
    """Over-reporting an address we cannot classify beats silently clearing it."""
    assert Listener(port=9000, bind="not-an-address").is_public is True


def test_wildcard_bind_is_public() -> None:
    assert Listener(port=80, bind="0.0.0.0").is_public is True
    assert Listener(port=80, bind="::").is_public is True


def test_an_unmeasured_observation_never_claims_a_pass() -> None:
    observations = observations_for(HostFacts(), subject_ref="box")
    for observation in observations:
        if observation["observed"].get("unmeasured"):
            assert "neither passing nor failing" in observation["why_it_matters"]


def test_only_loopback_listeners_produce_no_finding() -> None:
    facts = HostFacts(listeners=(Listener(port=8082, bind="127.0.0.1"),))
    assert [
        item
        for item in observations_for(facts, subject_ref="box")
        if item["check"] == "listening_sockets_public"
    ] == []


def test_many_public_ports_outrank_few() -> None:
    few = HostFacts(listeners=tuple(Listener(port=p, bind="0.0.0.0") for p in (80, 443)))
    many = HostFacts(listeners=tuple(Listener(port=p, bind="0.0.0.0") for p in range(8000, 8006)))

    def score(facts: HostFacts) -> float:
        return float(
            next(
                item["severity_score"]
                for item in observations_for(facts, subject_ref="box")
                if item["check"] == "listening_sockets_public"
            )
        )

    assert score(many) > score(few)


def test_an_active_firewall_produces_no_finding() -> None:
    facts = HostFacts(firewall_tool="ufw", firewall_active=True)
    assert [
        item
        for item in observations_for(facts, subject_ref="box")
        if item["check"] == "host_firewall_active"
    ] == []


def test_zero_pending_updates_produces_no_finding() -> None:
    facts = HostFacts(pending_updates=0)
    assert [
        item
        for item in observations_for(facts, subject_ref="box")
        if item["check"] == "pending_package_updates"
    ] == []


def test_ssh_password_auth_enabled_is_high() -> None:
    facts = HostFacts(ssh_password_paths={"password_authentication": True})
    finding = next(
        item
        for item in observations_for(facts, subject_ref="box")
        if item["check"] == "ssh_password_authentication"
    )
    assert finding["severity"] == "high"


def test_observations_are_ordered_by_score() -> None:
    facts = HostFacts(
        listeners=tuple(Listener(port=p, bind="0.0.0.0") for p in range(8000, 8006)),
        pending_updates=30,
        firewall_tool="ufw",
        firewall_active=False,
    )
    scores = [item["severity_score"] for item in observations_for(facts, subject_ref="box")]
    assert scores == sorted(scores, reverse=True)


# --- documents -----------------------------------------------------------------------------


def _facts() -> HostFacts:
    return HostFacts(
        hostname="box",
        os_name="Ubuntu 24.04",
        kernel="6.8.0",
        listeners=(Listener(port=22, bind="0.0.0.0"), Listener(port=8082, bind="127.0.0.1")),
        pending_updates=5,
        unreadable=("firewall",),
    )


def test_generated_posture_document_passes_the_platform_validator() -> None:
    """The collector's output must be something the ingestion path actually accepts."""
    documents = build_documents(_facts(), collected_at=NOW)
    observations = validate_posture_shape(documents["posture.json"])
    assert len(observations) >= 1


def test_manifest_records_what_was_not_measured() -> None:
    manifest = build_documents(_facts(), collected_at=NOW)["collection-manifest.json"]
    assert manifest["unmeasured"] == ["firewall"]
    assert manifest["results_summary"]["facts_unreadable"] == 1


def test_manifest_states_the_exclusions_explicitly() -> None:
    manifest = build_documents(_facts(), collected_at=NOW)["collection-manifest.json"]
    excluded = " ".join(manifest["scope"]["excluded"]).lower()
    assert "scanning" in excluded
    assert "mobile" in excluded


def test_vulns_document_is_present_and_honestly_empty() -> None:
    """The collection contract requires vulns.json; this collector does no CVE matching."""
    vulns = build_documents(_facts(), collected_at=NOW)["vulns.json"]
    assert vulns["matches"] == []
    assert vulns["descriptor"]["name"] == "aqelyn-collect"


def test_written_documents_are_owner_only(tmp_path: Path) -> None:
    written = write_collection(tmp_path, build_documents(_facts(), collected_at=NOW))
    assert written
    for path in written:
        assert path.stat().st_mode & 0o077 == 0


def test_written_documents_are_valid_json(tmp_path: Path) -> None:
    write_collection(tmp_path, build_documents(_facts(), collected_at=NOW))
    for name in ("posture.json", "collection-manifest.json", "vulns.json"):
        json.loads((tmp_path / name).read_text(encoding="utf-8"))
