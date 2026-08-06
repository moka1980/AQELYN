"""ECR-0107: the collector stops assuming Debian, and looks at two more things.

ECR-0102 shipped four checks and named its own blind spots: disk encryption, automatic
updates, and package managers other than APT. A machine running Fedora reported
"pending_updates: unreadable" - which is honest, and useless.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from aqelyn.collect.checks import (
    check_disk_encryption,
    check_pending_updates,
    check_unattended_upgrades,
    observations_for,
)
from aqelyn.collect.host import (
    CommandRunner,
    HostFacts,
    parse_disk_encryption,
    parse_dnf_updates,
    parse_pacman_updates,
    parse_unattended_upgrades,
    parse_zypper_updates,
    read_host_facts,
)

_LSBLK_ENCRYPTED = "disk\npart\ncrypt\nlvm\n"
_LSBLK_PLAIN = "disk\npart\npart\nlvm\n"

_DNF = """Last metadata expiration check: 0:03:11 ago on Wed 06 Aug 2026.

kernel.x86_64                 6.9.7-200.fc40            updates
openssl.x86_64                3.2.2-3.fc40              updates
Obsoleting Packages
python3-foo.noarch            2.0-1.fc40                updates
"""

_ZYPPER = """S | Repository | Name    | Current | Available | Arch
--+------------+---------+---------+-----------+-----
v | repo-oss   | openssl | 3.1.4   | 3.1.5     | x86_64
v | repo-oss   | curl    | 8.0.1   | 8.6.0     | x86_64
"""


def _runner(table: dict[str, tuple[int, str]]) -> CommandRunner:
    """A host that answers only for the tools named in `table`; everything else is absent."""

    def run(argv: Sequence[str]) -> tuple[int, str] | None:
        return table.get(argv[0])

    return run


# --- non-Debian package managers ------------------------------------------------------


def test_dnf_updates_are_counted_without_the_header_or_the_obsoleting_trailer() -> None:
    assert parse_dnf_updates(_DNF) == 2


def test_zypper_updates_are_counted_from_the_table_rows() -> None:
    assert parse_zypper_updates(_ZYPPER) == 2


def test_pacman_updates_are_one_per_line() -> None:
    assert parse_pacman_updates("openssl 3.1.4-1 -> 3.1.5-1\ncurl 8.0.1-1 -> 8.6.0-1\n") == 2


def test_a_fedora_machine_reports_its_updates_instead_of_unreadable(tmp_path: Path) -> None:
    """The blind spot ECR-0102 named. `dnf check-update` exits 100 when updates exist."""
    facts = read_host_facts(
        _runner({"dnf": (100, _DNF)}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.update_tool == "dnf"
    assert facts.pending_updates == 2
    assert "pending_updates" not in facts.unreadable


def test_dnf_exit_zero_means_no_updates_not_a_failure(tmp_path: Path) -> None:
    facts = read_host_facts(
        _runner({"dnf": (0, "")}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.update_tool == "dnf"
    assert facts.pending_updates == 0


def test_apt_is_preferred_when_more_than_one_manager_is_present(tmp_path: Path) -> None:
    facts = read_host_facts(
        _runner({"apt-get": (0, "Inst libc6 [2.39]\n"), "dnf": (100, _DNF)}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.update_tool == "apt"
    assert facts.pending_updates == 1


def test_a_machine_with_no_known_package_manager_stays_unreadable(tmp_path: Path) -> None:
    """Not zero. Zero would be a claim that the machine is up to date."""
    facts = read_host_facts(
        _runner({}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.pending_updates is None
    assert "pending_updates" in facts.unreadable


# --- disk encryption --------------------------------------------------------------------


def test_a_crypt_mapping_is_recognised_as_encryption() -> None:
    assert parse_disk_encryption(_LSBLK_ENCRYPTED) is True


def test_no_crypt_mapping_is_a_real_answer_not_an_unknown() -> None:
    assert parse_disk_encryption(_LSBLK_PLAIN) is False


def test_an_unencrypted_machine_raises_an_observation() -> None:
    observation = check_disk_encryption(HostFacts(disk_encrypted=False), "host-1")
    assert observation is not None
    assert observation["check"] == "disk_encryption_at_rest"


def test_an_encrypted_machine_raises_nothing() -> None:
    assert check_disk_encryption(HostFacts(disk_encrypted=True), "host-1") is None


def test_an_unreadable_device_table_is_unmeasured_not_unencrypted() -> None:
    observation = check_disk_encryption(HostFacts(disk_encrypted=None), "host-1")
    assert observation is not None
    assert observation["severity"] == "info"
    assert "neither passing nor failing" in observation["what_happened"].lower() or (
        "could not be read" in observation["what_happened"].lower()
    )


def test_lsblk_failing_leaves_the_fact_unread(tmp_path: Path) -> None:
    facts = read_host_facts(
        _runner({}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.disk_encrypted is None
    assert "disk_encryption" in facts.unreadable


# --- unattended upgrades ------------------------------------------------------------------


def test_the_directive_set_to_one_reads_as_enabled() -> None:
    assert parse_unattended_upgrades('APT::Periodic::Unattended-Upgrade "1";\n') is True


def test_the_directive_set_to_zero_reads_as_disabled() -> None:
    assert parse_unattended_upgrades('APT::Periodic::Unattended-Upgrade "0";\n') is False


def test_a_commented_directive_does_not_count_as_enabled() -> None:
    assert parse_unattended_upgrades('// APT::Periodic::Unattended-Upgrade "1";\n') is False


def test_a_file_that_never_mentions_the_directive_reads_as_disabled() -> None:
    """Operationally identical to "0": nothing installs updates on its own."""
    assert parse_unattended_upgrades('APT::Periodic::Update-Package-Lists "1";\n') is False


def test_an_absent_config_file_is_unreadable_not_disabled(tmp_path: Path) -> None:
    """A machine with no APT is not a machine that declined automatic updates."""
    facts = read_host_facts(
        _runner({}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.unattended_upgrades is None
    assert "unattended_upgrades" in facts.unreadable


def test_a_present_config_file_is_read(tmp_path: Path) -> None:
    conf = tmp_path / "20auto-upgrades"
    conf.write_text('APT::Periodic::Unattended-Upgrade "1";\n', encoding="utf-8")
    facts = read_host_facts(
        _runner({}),
        os_release=tmp_path / "absent",
        sshd_config=tmp_path / "absent",
        auto_upgrades=conf,
    )
    assert facts.unattended_upgrades is True
    assert "unattended_upgrades" not in facts.unreadable


def test_disabled_automatic_updates_raise_an_observation() -> None:
    observation = check_unattended_upgrades(HostFacts(unattended_upgrades=False), "host-1")
    assert observation is not None
    assert observation["check"] == "automatic_security_updates"


def test_an_unreadable_config_is_unmeasured_at_the_check_level() -> None:
    """Symmetry with disk encryption. Found by ECR-0107/M8, whose only catcher was the
    ECR-0102 enumeration test - true, but indirect, and one witness deep."""
    observation = check_unattended_upgrades(HostFacts(unattended_upgrades=None), "host-1")
    assert observation is not None
    assert observation["severity"] == "info"
    assert observation["observed"]["fact"] == "unattended_upgrades"


def test_enabled_automatic_updates_raise_nothing() -> None:
    assert check_unattended_upgrades(HostFacts(unattended_upgrades=True), "host-1") is None


# --- the checks are wired in ----------------------------------------------------------------


def test_both_new_checks_run_in_the_real_check_list() -> None:
    """A check that exists and is never called is the dead code ECR-0105 removed."""
    produced = observations_for(
        HostFacts(disk_encrypted=False, unattended_upgrades=False), subject_ref="host-1"
    )
    checks = {str(item["check"]) for item in produced}
    assert "disk_encryption_at_rest" in checks
    assert "automatic_security_updates" in checks


def test_the_new_observations_carry_the_four_narrative_fields() -> None:
    for observation in (
        check_disk_encryption(HostFacts(disk_encrypted=False), "host-1"),
        check_unattended_upgrades(HostFacts(unattended_upgrades=False), "host-1"),
    ):
        assert observation is not None
        for field in ("what_happened", "why_it_matters", "how_determined", "risk_of_inaction"):
            assert str(observation[field]).strip()


def test_pending_updates_still_behaves_as_ecr_0102_left_it() -> None:
    assert check_pending_updates(HostFacts(pending_updates=0), "host-1") is None
    assert check_pending_updates(HostFacts(pending_updates=None), "host-1") is not None
