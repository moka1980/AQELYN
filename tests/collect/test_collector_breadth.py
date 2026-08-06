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
    check_firewall,
    check_pending_updates,
    check_ssh_password_auth,
    check_unattended_upgrades,
    observations_for,
)
from aqelyn.collect.host import (
    CommandRunner,
    HostFacts,
    _filesystem_include_resolver,
    flatten_sshd_config,
    parse_disk_encryption,
    parse_dnf_updates,
    parse_pacman_updates,
    parse_ssh_password_auth,
    parse_ssh_password_paths,
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


# --- ECR-0109: the firewall reader, found wrong by running it on the live VPS ------------


def _facts(tmp_path: Path, table: dict[str, tuple[int, str]]) -> HostFacts:
    absent = tmp_path / "absent"
    return read_host_facts(
        _runner(table), os_release=absent, sshd_config=absent, auto_upgrades=absent
    )


def test_ufw_reporting_active_is_read_as_active(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"ufw": (0, "Status: active\nTo  Action  From\n22/tcp  ALLOW IN")})
    assert facts.firewall_active is True
    assert "firewall" not in facts.unreadable


def test_ufw_reporting_inactive_is_read_as_inactive(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"ufw": (0, "Status: inactive")})
    assert facts.firewall_active is False
    assert "firewall" not in facts.unreadable


def test_ufw_refusing_without_root_is_unreadable_not_inactive(tmp_path: Path) -> None:
    """Measured on the live VPS: `ufw status` needs root, and the collector was telling the
    owner to enable a firewall that was already running. A false positive in the direction
    that costs trust - the same class the `is_public` fix addressed."""
    facts = _facts(tmp_path, {"ufw": (1, "ERROR: You need to be root to run this script")})
    assert facts.firewall_active is None
    assert facts.firewall_tool == "ufw"
    assert "firewall" in facts.unreadable


def test_a_stopped_firewalld_is_not_read_as_running(tmp_path: Path) -> None:
    """`firewall-cmd --state` prints "not running", which contains "running". The old
    substring test called a stopped firewall active - the same defect in the direction
    that hides a real problem."""
    facts = _facts(tmp_path, {"firewall-cmd": (252, "not running")})
    assert facts.firewall_active is False


def test_a_running_firewalld_is_read_as_running(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"firewall-cmd": (0, "running")})
    assert facts.firewall_active is True


def test_an_unreadable_firewall_produces_an_unmeasured_observation(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"ufw": (1, "ERROR: You need to be root to run this script")})
    observation = check_firewall(facts, "host-1")
    assert observation is not None
    assert observation["severity"] == "info"
    assert "not active" not in observation["what_happened"]


# --- ECR-0110: sshd Include and first-wins, found on the live VPS -------------------------

_MAIN = """# main config
Include /etc/ssh/sshd_config.d/*.conf
#PasswordAuthentication yes
PermitRootLogin prohibit-password
"""


def test_a_drop_in_is_read_at_all(tmp_path: Path) -> None:
    """The main file's directive is commented out, so a parser that ignores Include reads
    a config that says nothing. Measured on the live VPS."""
    flat = flatten_sshd_config(_MAIN, resolve=lambda _: ["PasswordAuthentication no\n"])
    assert parse_ssh_password_auth(flat) is False


def test_two_drop_ins_that_disagree_resolve_the_way_sshd_resolves_them() -> None:
    """The live VPS has exactly this: 50-cloud-init says yes, 60-cloudimg says no. sshd
    takes the FIRST value, 50 sorts before 60, and `sshd -T` reports yes."""
    flat = flatten_sshd_config(
        _MAIN,
        resolve=lambda _: ["PasswordAuthentication yes\n", "PasswordAuthentication no\n"],
    )
    assert parse_ssh_password_auth(flat) is True


def test_the_first_value_wins_not_the_last() -> None:
    assert (
        parse_ssh_password_auth("PasswordAuthentication no\nPasswordAuthentication yes\n") is False
    )


def test_a_directive_in_the_main_file_before_the_include_wins() -> None:
    """Position matters, not which file it came from."""
    text = "PasswordAuthentication yes\nInclude drop.conf\n"
    flat = flatten_sshd_config(text, resolve=lambda _: ["PasswordAuthentication no\n"])
    assert parse_ssh_password_auth(flat) is True


def test_a_commented_include_is_not_followed() -> None:
    flat = flatten_sshd_config(
        "#Include /etc/ssh/sshd_config.d/*.conf\n",
        resolve=lambda _: ["PasswordAuthentication no\n"],
    )
    assert parse_ssh_password_auth(flat) is None


def test_a_self_including_config_terminates() -> None:
    """A config that includes itself must not hang a collector."""
    flat = flatten_sshd_config("Include self\n", resolve=lambda _: ["Include self\n"])
    assert isinstance(flat, str)


def test_the_disk_resolver_returns_drop_ins_in_sorted_name_order(tmp_path: Path) -> None:
    """Asserted on the resolver's own output order, not on a value derived from it.

    ECR-0110/M3 first ran GREEN: `sorted()` swapped for `list()` changed nothing, because
    the filesystem happened to hand back the files in the order the test wanted. A witness
    whose verdict depends on directory iteration order is not a witness."""
    conf_d = tmp_path / "sshd_config.d"
    conf_d.mkdir()
    for name in ("90-z.conf", "10-a.conf", "50-m.conf"):
        (conf_d / name).write_text(f"# {name}\n", encoding="utf-8")
    resolve = _filesystem_include_resolver(tmp_path)
    assert [text.strip() for text in resolve("sshd_config.d/*.conf")] == [
        "# 10-a.conf",
        "# 50-m.conf",
        "# 90-z.conf",
    ]


def test_includes_are_read_off_disk_in_sorted_order(tmp_path: Path) -> None:
    """The real resolver end to end: sorted glob order decides which drop-in wins."""
    conf_d = tmp_path / "sshd_config.d"
    conf_d.mkdir()
    (conf_d / "60-second.conf").write_text("PasswordAuthentication no\n", encoding="utf-8")
    (conf_d / "50-first.conf").write_text("PasswordAuthentication yes\n", encoding="utf-8")
    main = tmp_path / "sshd_config"
    main.write_text("Include sshd_config.d/*.conf\n", encoding="utf-8")
    facts = read_host_facts(
        _runner({}),
        os_release=tmp_path / "absent",
        sshd_config=main,
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.ssh_password_auth is True
    assert "ssh_password_auth" not in facts.unreadable


def test_an_unreadable_drop_in_does_not_crash_the_collector(tmp_path: Path) -> None:
    conf_d = tmp_path / "sshd_config.d"
    conf_d.mkdir()
    main = tmp_path / "sshd_config"
    main.write_text("Include sshd_config.d/*.conf\nPasswordAuthentication yes\n", encoding="utf-8")
    facts = read_host_facts(
        _runner({}),
        os_release=tmp_path / "absent",
        sshd_config=main,
        auto_upgrades=tmp_path / "absent",
    )
    assert facts.ssh_password_auth is True


# --- ECR-0111: every password-capable path, not just the obvious one ----------------------


def test_keyboard_interactive_is_reported_as_a_password_path() -> None:
    """With PAM this is a password prompt under another name. ECR-0110 read only
    PasswordAuthentication and said so; on the live VPS the others are safe by luck."""
    paths = parse_ssh_password_paths(
        "PasswordAuthentication no\nKbdInteractiveAuthentication yes\n"
    )
    assert paths == {
        "password_authentication": False,
        "keyboard_interactive_authentication": True,
    }


def test_empty_passwords_is_reported_as_a_password_path() -> None:
    paths = parse_ssh_password_paths("PermitEmptyPasswords yes\n")
    assert paths == {"empty_passwords": True}


def test_a_directive_the_config_never_sets_is_omitted_not_defaulted() -> None:
    """Two of the three upstream defaults are OPEN, measured with `sshd -T -f` on a config
    containing only `Port 22`. Synthesising a value here would either invent a finding or
    hide one, so the absence is carried through instead."""
    assert parse_ssh_password_paths("PasswordAuthentication no\n") == {
        "password_authentication": False
    }


def test_a_config_that_sets_none_of_them_is_unmeasured() -> None:
    assert parse_ssh_password_paths("Port 22\n") is None


def test_the_check_names_which_path_is_open() -> None:
    facts = HostFacts(
        ssh_password_paths={
            "password_authentication": False,
            "keyboard_interactive_authentication": True,
        }
    )
    observation = check_ssh_password_auth(facts, "host-1")
    assert observation is not None
    assert "keyboard-interactive" in observation["what_happened"]
    assert "password login" not in observation["what_happened"]


def test_the_check_stays_silent_when_every_path_is_closed() -> None:
    facts = HostFacts(
        ssh_password_paths={
            "password_authentication": False,
            "keyboard_interactive_authentication": False,
            "empty_passwords": False,
        }
    )
    assert check_ssh_password_auth(facts, "host-1") is None


def test_the_check_reports_unset_paths_the_upstream_default_leaves_open() -> None:
    facts = HostFacts(ssh_password_paths={"password_authentication": True})
    observation = check_ssh_password_auth(facts, "host-1")
    assert observation is not None
    assert observation["observed"]["unset_and_open_by_default"] == [
        "keyboard_interactive_authentication"
    ]


def test_password_auth_is_derived_from_the_path_set_not_stored_twice() -> None:
    """Two records of one fact are two records that can disagree."""
    assert HostFacts(ssh_password_paths={"password_authentication": True}).ssh_password_auth
    assert HostFacts().ssh_password_auth is None
    assert HostFacts(ssh_password_paths={"empty_passwords": True}).ssh_password_auth is None
