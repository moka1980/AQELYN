"""ECR-0108: Charter v2 Principle 2 (Simplicity First) without rewriting the finding.

ECR-0104 recorded UX-008 as half-served and ECR-0105 recorded it again: a mode changed how
much was shown, never the words. A home reader still met "listening socket" and "loopback".

The obvious fix is to rewrite each finding per audience. This module deliberately does not
do that, because a second rendering of the same fact is exactly where a "simplified"
version drifts from a true one - and there would be no witness for the drift, since both
sentences would be things we wrote.

Instead the plain language is **additive**. The finding's own sentence is never altered in
any mode; the technical terms it happens to contain are annotated. One rendering of the
fact, one source of truth, and Principle 2 served by explaining the vocabulary rather than
by replacing it.

Terms are matched on word boundaries and case-insensitively, so "key" does not match inside
"monkey" and "Loopback" at the start of a sentence is still found.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# Written for someone who has never administered a machine. Each definition says what the
# thing *is* in terms of what it does, not what it is called in another jargon.
#
# Only vocabulary the shipped checks can actually emit. Four web- and mail-intelligence
# terms were drafted here and removed: EA-0054 is a recorded decision NOT to build that
# capability, and its absence guard caught them. Glossing words no AQELYN finding can
# produce would be a glossary describing a product we do not have. The guard is a text
# census, so naming the four terms even in this comment trips it - which is the guard
# working, and why they are described rather than listed.
GLOSSARY: dict[str, str] = {
    "loopback": "only reachable from this machine itself, not from the network",
    "listening socket": "a program sitting and waiting for network connections",
    "listening sockets": "programs sitting and waiting for network connections",
    "port": "a numbered door on this machine that a program can accept connections through",
    "ports": "numbered doors on this machine that programs accept connections through",
    "reverse proxy": "a front-door program that receives requests and passes them on",
    "firewall": "the part of the system that decides which connections are allowed in",
    "ssh": "the standard way of logging into a machine remotely over the network",
    "key": "a long secret file used instead of a password, far too long to guess",
    "cve": "a public catalogue number for one specific published software flaw",
    "full-disk encryption": (
        "scrambling everything on the drive so it is unreadable without the key"
    ),
    "encryption": "scrambling data so it is unreadable without the key",
    "unattended-upgrades": "the service that installs security updates without being asked",
    "package": "one installable piece of software, updated as a unit",
    "packages": "installable pieces of software, each updated as a unit",
    "evidence record": "the stored proof of what was seen, when, and by what method",
    "posture": "how a machine is configured, as opposed to what flaws its software has",
    "severity": "how serious this is, on a fixed scale, not an opinion about your situation",
}


@dataclass(frozen=True)
class Gloss:
    term: str
    plain: str


# Longest first, so "listening socket" wins over "socket" and "full-disk encryption" over
# "encryption". Without this the shorter term matches first and the better explanation is
# never offered.
_ORDERED_TERMS = sorted(GLOSSARY, key=len, reverse=True)
_PATTERNS = {term: re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE) for term in GLOSSARY}


def glosses_for(text: str) -> Sequence[Gloss]:
    """Every glossary term the text actually uses, longest match first, no duplicates.

    A term already covered by a longer one that matched is skipped: a reader shown
    "full-disk encryption" does not also need "encryption" explained on the same line.
    """

    found: list[Gloss] = []
    claimed: list[str] = []
    for term in _ORDERED_TERMS:
        if not _PATTERNS[term].search(text):
            continue
        if any(term in longer for longer in claimed):
            continue
        claimed.append(term)
        found.append(Gloss(term=term, plain=GLOSSARY[term]))
    return tuple(found)
