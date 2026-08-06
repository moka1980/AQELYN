"""ECR-0102: turn host facts into posture observations.

Pure. Facts in, observations out - no I/O, no subprocess, no network - so every judgement
below can be tested without a host, and the same facts always produce the same document.

Each check returns an observation or `None`. `None` means the check did not apply. A fact
that could not be *read* is different: it produces an `unmeasured` observation, because the
one thing this platform must never do is report a machine as clean when nothing looked at it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from aqelyn.collect.host import UPSTREAM_DEFAULT_OPEN, HostFacts

SUBJECT_KIND = "host"


def _observation(
    *,
    observation_id: str,
    subject_ref: str,
    check: str,
    severity: str,
    severity_score: float,
    what_happened: str,
    why_it_matters: str,
    how_determined: str,
    risk_of_inaction: str,
    summary: str,
    difficulty: str,
    expected_outcome: str,
    observed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "subject": {"kind": SUBJECT_KIND, "ref": subject_ref},
        "check": check,
        "severity": severity,
        "severity_score": severity_score,
        "observed": observed or {},
        "what_happened": what_happened,
        "why_it_matters": why_it_matters,
        "how_determined": how_determined,
        "risk_of_inaction": risk_of_inaction,
        "remediation": {
            "summary": summary,
            "difficulty": difficulty,
            "expected_outcome": expected_outcome,
        },
    }


def _unmeasured(subject_ref: str, fact: str, check: str) -> dict[str, Any]:
    return _observation(
        observation_id=f"obs-unmeasured-{fact}",
        subject_ref=subject_ref,
        check=check,
        severity="info",
        severity_score=0.0,
        what_happened=f"This machine's {fact.replace('_', ' ')} could not be read.",
        why_it_matters=(
            "The check did not run, so this machine is neither passing nor failing it. "
            "Recorded so the gap is visible rather than mistaken for a clean result."
        ),
        how_determined=(
            f"The collector attempted to read {fact} and the command or file was "
            "unavailable on this system."
        ),
        risk_of_inaction=(
            "A real problem here would be invisible. Nothing can be concluded either way."
        ),
        summary=f"Run the collector where {fact.replace('_', ' ')} can be read, or supply it.",
        difficulty="low",
        expected_outcome="The check reports a real result instead of an absence.",
        observed={"unmeasured": True, "fact": fact},
    )


def check_public_listeners(facts: HostFacts, subject_ref: str) -> dict[str, Any] | None:
    if facts.listeners is None:
        return _unmeasured(subject_ref, "listeners", "listening_sockets_public")
    public = [item for item in facts.listeners if item.is_public]
    if not public:
        return None
    ports = sorted({item.port for item in public})
    wildcard = sorted({item.port for item in public if item.bind == "0.0.0.0"})
    specific = sorted({item.port for item in public if item.bind != "0.0.0.0"})
    severity, score = ("high", 70.0) if len(ports) > 3 else ("medium", 45.0)

    # "All interfaces" is only true of a wildcard bind. A service on one routable address
    # is still reachable off this machine, but saying it listens everywhere would be wrong,
    # and a security report that overstates once is discounted thereafter.
    detail = []
    if wildcard:
        detail.append(f"on every interface: {', '.join(str(port) for port in wildcard)}")
    if specific:
        detail.append(
            f"on a specific routable address: {', '.join(str(port) for port in specific)}"
        )
    return _observation(
        observation_id="obs-public-listeners",
        subject_ref=subject_ref,
        check="listening_sockets_public",
        severity=severity,
        severity_score=score,
        what_happened=(
            f"{len(ports)} port(s) are reachable from beyond this machine — "
            + "; ".join(detail)
            + "."
        ),
        why_it_matters=(
            "Anything not bound to loopback is reachable from the network this machine is "
            "on, not only from the machine itself."
        ),
        how_determined=(
            "Parsed the local address column of `ss -tlnH` on this host; loopback addresses "
            "(the whole 127.0.0.0/8 range and ::1) were excluded."
        ),
        risk_of_inaction=(
            "Services intended for local use are exposed to everything that can route here."
        ),
        summary="Bind local-only services to 127.0.0.1, and put the rest behind a proxy.",
        difficulty="low",
        expected_outcome="Only ports meant to be reachable stay reachable.",
        observed={
            "public_ports": ports,
            "all_interfaces": wildcard,
            "specific_address": specific,
        },
    )


def check_firewall(facts: HostFacts, subject_ref: str) -> dict[str, Any] | None:
    if facts.firewall_active is None:
        return _unmeasured(subject_ref, "firewall", "host_firewall_active")
    if facts.firewall_active:
        return None
    return _observation(
        observation_id="obs-firewall-inactive",
        subject_ref=subject_ref,
        check="host_firewall_active",
        severity="medium",
        severity_score=42.0,
        what_happened=f"A host firewall ({facts.firewall_tool}) is installed but not active.",
        why_it_matters=(
            "Every listening service is reachable from the local network, whether or not "
            "it was meant to be."
        ),
        how_determined=f"Queried {facts.firewall_tool} for its own state on this host.",
        risk_of_inaction="A service opened by accident is immediately reachable.",
        summary="Enable the firewall with a default-deny inbound policy.",
        difficulty="low",
        expected_outcome="Inbound traffic is denied unless a rule allows it.",
        observed={"tool": facts.firewall_tool, "active": False},
    )


def check_pending_updates(facts: HostFacts, subject_ref: str) -> dict[str, Any] | None:
    if facts.pending_updates is None:
        return _unmeasured(subject_ref, "pending_updates", "pending_package_updates")
    if facts.pending_updates == 0:
        return None
    count = facts.pending_updates
    severity, score = ("medium", 50.0) if count >= 20 else ("low", 25.0)
    return _observation(
        observation_id="obs-pending-updates",
        subject_ref=subject_ref,
        check="pending_package_updates",
        severity=severity,
        severity_score=score,
        what_happened=f"{count} package update(s) are pending on this machine.",
        why_it_matters=(
            "Published updates describe the flaws they fix, so an unpatched machine is "
            "documented as vulnerable."
        ),
        how_determined="Counted `Inst` lines from `apt-get -s upgrade`, which changes nothing.",
        risk_of_inaction="Known, published flaws stay open on this machine.",
        summary="Apply the pending updates and enable unattended security upgrades.",
        difficulty="low",
        expected_outcome="The machine tracks published fixes without manual work.",
        observed={"pending": count},
    )


_PATH_LABELS = {
    "password_authentication": "password login",
    "keyboard_interactive_authentication": (
        "keyboard-interactive login, which with PAM is a password prompt under another name"
    ),
    "empty_passwords": "accounts with an empty password",
}


def check_ssh_password_auth(facts: HostFacts, subject_ref: str) -> dict[str, Any] | None:
    open_paths = sorted(fact for fact, value in (facts.ssh_password_paths or {}).items() if value)
    conditional = sorted(facts.ssh_password_match_scoped)
    # Nothing global and nothing conditional means the config named none of these directives,
    # which ECR-0111 records as unmeasured rather than clean.
    if facts.ssh_password_paths is None and not conditional:
        return _unmeasured(subject_ref, "ssh_password_auth", "ssh_password_authentication")
    if not open_paths and not conditional:
        return None

    described = "; ".join(_PATH_LABELS.get(fact, fact) for fact in open_paths)
    # ECR-0112: a Match block decides the value for some connections and we cannot read
    # which without `sshd -T -C`. Reported as conditional rather than folded into the global
    # yes/no, so a Match-hidden opening is never mistaken for an all-clear.
    conditional_clause = ""
    if conditional:
        names = "; ".join(_PATH_LABELS.get(fact, fact) for fact in conditional)
        conditional_clause = (
            f" A Match block sets {names} for some connections, so the effective answer "
            "depends on who is connecting; this was not fully measured."
        )
    if open_paths:
        opener = (
            f"The SSH server accepts {len(open_paths)} authentication "
            f"{'paths' if len(open_paths) > 1 else 'path'} that a person can type: {described}."
        )
    else:
        opener = (
            "The SSH server's password authentication is decided by a Match block, not globally."
        )
    return _observation(
        observation_id="obs-ssh-password-auth",
        subject_ref=subject_ref,
        check="ssh_password_authentication",
        severity="high",
        severity_score=68.0,
        what_happened=opener + conditional_clause,
        why_it_matters=(
            "A password can be guessed at whatever rate the network allows; a key cannot. "
            "Each of these is a separate door, and closing only the obvious one leaves the "
            "others open."
        ),
        how_determined=(
            "Read the effective sshd directives, following Include files in the order sshd "
            "reads them and taking the first value of each keyword in unconditional scope. "
            "Match blocks are reported as conditional, not evaluated."
        ),
        risk_of_inaction="Remote access is exposed to credential guessing.",
        summary=(
            "Set PasswordAuthentication no, KbdInteractiveAuthentication no and "
            "PermitEmptyPasswords no, and use keys. Confirm a key works in a second session "
            "before closing the first."
        ),
        difficulty="medium",
        expected_outcome="Only key holders can open a session.",
        observed={
            "open_paths": open_paths,
            "paths": dict(facts.ssh_password_paths or {}),
            "match_scoped": conditional,
            # Directives the config never sets, where the upstream default leaves the door
            # open. Reported so the reader sees them; not counted as findings, because the
            # default belongs to how this sshd was built and we have not read that.
            "unset_and_open_by_default": sorted(
                UPSTREAM_DEFAULT_OPEN - set(facts.ssh_password_paths or {})
            ),
        },
    )


def check_disk_encryption(facts: HostFacts, subject_ref: str) -> dict[str, Any] | None:
    if facts.disk_encrypted is None:
        return _unmeasured(subject_ref, "disk_encryption", "disk_encryption_at_rest")
    if facts.disk_encrypted:
        return None
    return _observation(
        observation_id="obs-disk-encryption",
        subject_ref=subject_ref,
        check="disk_encryption_at_rest",
        severity="medium",
        severity_score=55.0,
        what_happened="No encrypted volume was found on this machine.",
        why_it_matters=(
            "Every access control on this machine is enforced by the running system. A "
            "disk read on another machine - a stolen laptop, a returned drive, a disposed "
            "server - is not subject to any of them."
        ),
        how_determined=(
            "Listed block device types with `lsblk -rno TYPE` and found no `crypt` "
            "mapping. This reads the device table and changes nothing."
        ),
        risk_of_inaction=(
            "Anyone who obtains the physical drive reads everything on it, including "
            "credentials cached by the software installed here."
        ),
        summary=(
            "Enable full-disk encryption. On an existing installation this usually means "
            "a reinstall, so plan it rather than attempting it in place."
        ),
        difficulty="high",
        expected_outcome="A drive removed from this machine is unreadable without the key.",
        observed={"encrypted_volumes": 0},
    )


def check_unattended_upgrades(facts: HostFacts, subject_ref: str) -> dict[str, Any] | None:
    if facts.unattended_upgrades is None:
        return _unmeasured(subject_ref, "unattended_upgrades", "automatic_security_updates")
    if facts.unattended_upgrades:
        return None
    return _observation(
        observation_id="obs-unattended-upgrades",
        subject_ref=subject_ref,
        check="automatic_security_updates",
        severity="medium",
        severity_score=45.0,
        what_happened="This machine does not install security updates on its own.",
        why_it_matters=(
            "Patching that depends on someone remembering is patching that stops when "
            "they are busy. The gap between a fix being published and being installed is "
            "the window an attacker works in, and it is measured in days here."
        ),
        how_determined=(
            "Read APT::Periodic::Unattended-Upgrade from /etc/apt/apt.conf.d/20auto-upgrades."
        ),
        risk_of_inaction=(
            "Published fixes stay uninstalled for as long as nobody runs the update."
        ),
        summary="Install unattended-upgrades and enable it for the security pocket.",
        difficulty="low",
        expected_outcome="Security updates install without anyone remembering to.",
        observed={"unattended_upgrade": False},
    )


CHECKS = (
    check_public_listeners,
    check_firewall,
    check_pending_updates,
    check_unattended_upgrades,
    check_disk_encryption,
    check_ssh_password_auth,
)


def observations_for(facts: HostFacts, *, subject_ref: str) -> Sequence[dict[str, Any]]:
    """Run every check. Order is severity-descending so the document reads top-down."""

    produced = [
        observation
        for observation in (check(facts, subject_ref) for check in CHECKS)
        if observation is not None
    ]
    produced.sort(key=lambda item: (-float(item["severity_score"]), str(item["observation_id"])))
    return produced
