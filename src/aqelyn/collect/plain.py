"""Plain-language layer for the customer self-scan report.

Charter Principle 2 (Simplicity First): the output must be understandable by everyone,
non-technical included. The collector's observation text is written for an operator; this
maps each check to words a person with no security background can act on, and gives a
reassuring line for the checks that passed. The technical detail is kept — it just stops
being the first thing a customer reads.

Keyed by the ``check`` id each collector emits, so Linux and Windows share the wording.
"""

from __future__ import annotations

# Friendly, non-alarmist severity words (Charter Principle 8: no scare language).
_SEVERITY_WORD = {
    "critical": "Fix this soon",
    "high": "Worth attention",
    "medium": "Worth improving",
    "low": "Minor",
    "info": "For information",
}


def severity_word(severity: str) -> str:
    return _SEVERITY_WORD.get(severity, "Note")


# For each check id: a plain headline + what it means + what to do (shown when it is a
# finding), and a short reassurance (shown when the check passed). Written for a person, not
# an admin. `good` is what a customer sees in the "Looking good" section.
PLAIN: dict[str, dict[str, str]] = {
    "listening_sockets_public": {
        "headline": "Some services on this computer can be reached over the network",
        "meaning": (
            "Programs on this computer are waiting for connections from other devices on the "
            "same network — not only from the computer itself. That is normal for things like "
            "file and printer sharing, but anything you do not actually use is safer turned off."
        ),
        "action": (
            "On a network you do not fully trust (a café, airport, or shared office), set that "
            "network to 'Public' in your settings. If you do not share files or printers from "
            "this computer, turn that sharing off."
        ),
        "good": "Nothing on this computer is needlessly open to the network.",
    },
    "host_firewall_active": {
        "headline": "The firewall is switched off",
        "meaning": (
            "A firewall turns away connections you did not ask for. With it off, other devices "
            "can reach services on this computer more freely."
        ),
        "action": "Switch the firewall on for every network type.",
        "good": "The firewall is on — it turns away connections you did not ask for.",
    },
    "disk_encryption_at_rest": {
        "headline": "The disk is not encrypted",
        "meaning": (
            "If this computer is lost or stolen, someone could take the drive out and read "
            "everything on it, because the files are not scrambled."
        ),
        "action": "Turn on disk encryption (BitLocker on Windows, or your system's encryption).",
        "good": (
            "The disk is encrypted — if the computer is lost or stolen, the files cannot be read."
        ),
    },
    "pending_package_updates": {
        "headline": "Some updates are waiting to be installed",
        "meaning": (
            "Updates fix flaws that are already public knowledge. Until they are installed, "
            "those flaws stay open on this computer."
        ),
        "action": "Install the pending updates.",
        "good": "The software is up to date.",
    },
    "automatic_security_updates": {
        "headline": "Security updates do not install by themselves",
        "meaning": (
            "If updates wait for someone to remember, they are often late. That gap is the time "
            "an attacker has to use a flaw that already has a fix."
        ),
        "action": "Turn on automatic security updates.",
        "good": "Security updates install themselves automatically.",
    },
    "ssh_password_authentication": {
        "headline": "This computer allows remote login with a password",
        "meaning": (
            "A password can be guessed at whatever speed the network allows; a key file cannot. "
            "Allowing password login over the network is a common way in for attackers."
        ),
        "action": "Use key files for remote login, and turn password login off.",
        "good": "Remote login does not accept guessable passwords.",
    },
    "antivirus_protection": {
        "headline": "Antivirus or real-time protection is off",
        "meaning": (
            "With real-time protection off, harmful files are not checked as they arrive, so "
            "malware can run without being caught."
        ),
        "action": (
            "Turn Microsoft Defender real-time protection on, or confirm another antivirus "
            "is active."
        ),
        "good": "Antivirus is on and watching for harmful files.",
    },
    "antivirus_signatures_current": {
        "headline": "Antivirus is out of date",
        "meaning": "Old antivirus data misses threats discovered since it was last updated.",
        "action": "Update your antivirus (check for updates in Windows Security).",
        "good": "Antivirus data is up to date.",
    },
    "remote_desktop_exposed": {
        "headline": "Remote Desktop is switched on",
        "meaning": (
            "Remote Desktop lets someone log in to this computer over the network. Left open, "
            "it is a constant target for people guessing passwords."
        ),
        "action": (
            "Turn Remote Desktop off if you do not use it; if you need it, do not expose it to "
            "the internet."
        ),
        "good": "Remote Desktop is off — nobody can log in to this computer over the network.",
    },
}

_FALLBACK = {
    "headline": "Something needs a look",
    "meaning": "A security check reported something worth reviewing.",
    "action": "Review this item.",
    "good": "This check passed.",
}


def plain_for(check: str) -> dict[str, str]:
    return PLAIN.get(check, _FALLBACK)


# The check ids the Linux collector can emit (used to compute which checks passed — a check
# that produced no observation passed). Kept in sync with checks.py by test_selfscan.
LINUX_CHECK_IDS: tuple[str, ...] = (
    "listening_sockets_public",
    "host_firewall_active",
    "pending_package_updates",
    "automatic_security_updates",
    "disk_encryption_at_rest",
    "ssh_password_authentication",
)
