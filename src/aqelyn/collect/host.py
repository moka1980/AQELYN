"""ECR-0102: read-only facts about the machine the operator is sitting at.

Two rules shape this module.

**Nothing here decides anything.** It gathers facts and records, per fact, whether the
gather succeeded. Judgement lives in `checks.py`, which is pure and therefore testable
without a host.

**A fact that could not be read is `None`, never a default.** A firewall whose state could
not be determined must not become "no firewall" — the platform's whole claim is that
unmeasured is its own state, and a collector that quietly substitutes a default is where
that claim would first be broken.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# A command runner returns (exit_code, stdout) or None when the command is unavailable.
CommandRunner = Callable[[Sequence[str]], tuple[int, str] | None]

_TIMEOUT_SECONDS = 20


def run_command(argv: Sequence[str]) -> tuple[int, str] | None:
    """Run a read-only command. Returns None when it is not installed or misbehaves."""

    if shutil.which(argv[0]) is None:
        return None
    try:
        # Fixed argv, no shell, no user input; the command list is a module constant.
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.returncode, completed.stdout


@dataclass(frozen=True)
class Listener:
    port: int
    bind: str

    @property
    def is_public(self) -> bool:
        """Reachable from off this machine.

        The whole 127.0.0.0/8 range is loopback, not just 127.0.0.1 — systemd-resolved
        binds 127.0.0.53. Treating only the canonical address as local reported resolver
        DNS as internet-facing, which is a false positive in the direction that costs
        trust. An address that cannot be parsed is called public: over-reporting an
        unknown beats silently clearing it.
        """
        if self.bind == "localhost":
            return False
        try:
            address = ipaddress.ip_address(self.bind)
        except ValueError:
            return True
        # A wildcard bind (0.0.0.0 / ::) needs no special case: it is not loopback, so the
        # test below already calls it public. An explicit `is_unspecified` branch was here
        # and removed — mutating it away changed no verdict, which made it dead code in a
        # security check, and dead code in a security check is a liability.
        return not address.is_loopback


@dataclass(frozen=True)
class HostFacts:
    """Every field is optional. `None` means the fact could not be read."""

    hostname: str | None = None
    os_name: str | None = None
    kernel: str | None = None
    listeners: tuple[Listener, ...] | None = None
    firewall_tool: str | None = None
    firewall_active: bool | None = None
    pending_updates: int | None = None
    ssh_password_auth: bool | None = None
    unreadable: tuple[str, ...] = field(default_factory=tuple)


_ADDR = re.compile(r"^(?P<bind>.*):(?P<port>\d+)$")


def parse_listeners(ss_output: str) -> tuple[Listener, ...]:
    """Parse `ss -tlnH` local-address column into listeners.

    Pure so the shapes that matter - IPv6 brackets, wildcard binds, interface suffixes -
    can be tested without a host.
    """

    listeners: list[Listener] = []
    for line in ss_output.splitlines():
        columns = line.split()
        if len(columns) < 4:
            continue
        match = _ADDR.match(columns[3])
        if match is None:
            continue
        bind = match.group("bind").strip()
        if bind.startswith("[") and bind.endswith("]"):
            bind = bind[1:-1]
        bind = bind.split("%", 1)[0]  # drop the %lo scope suffix
        if bind in {"*", "0.0.0.0", "::"}:
            bind = "0.0.0.0"
        listeners.append(Listener(port=int(match.group("port")), bind=bind))
    return tuple(sorted(set(listeners), key=lambda item: (item.port, item.bind)))


def parse_pending_updates(apt_simulate_output: str) -> int:
    """Count upgradable packages from `apt-get -s upgrade`."""

    return sum(1 for line in apt_simulate_output.splitlines() if line.startswith("Inst "))


def parse_ssh_password_auth(sshd_config: str) -> bool | None:
    """Return whether password auth is enabled, or None when the file does not say.

    An sshd_config that never mentions the directive is not evidence of either setting -
    the effective value comes from the build default - so it reads as unmeasured.
    """

    result: bool | None = None
    for raw in sshd_config.splitlines():
        line = raw.strip()
        # The `#` test is defensive, not load-bearing: a commented directive already fails
        # the token comparison below. Mutating it away changes no verdict. Kept because it
        # states the intent, and recorded as unwitnessed rather than left looking proven.
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == "passwordauthentication":
            result = parts[1].lower() == "yes"
    return result


def read_host_facts(
    runner: CommandRunner = run_command,
    *,
    os_release: Path = Path("/etc/os-release"),
    sshd_config: Path = Path("/etc/ssh/sshd_config"),
) -> HostFacts:
    """Gather what this machine will say about itself. Read-only throughout."""

    unreadable: list[str] = []

    hostname = None
    result = runner(["hostname"])
    if result is not None and result[0] == 0:
        hostname = result[1].strip() or None
    if hostname is None:
        unreadable.append("hostname")

    os_name = None
    with contextlib.suppress(OSError):
        for line in os_release.read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip().strip('"') or None
    if os_name is None:
        unreadable.append("os_name")

    kernel = None
    result = runner(["uname", "-r"])
    if result is not None and result[0] == 0:
        kernel = result[1].strip() or None
    if kernel is None:
        unreadable.append("kernel")

    listeners: tuple[Listener, ...] | None = None
    result = runner(["ss", "-tlnH"])
    if result is not None and result[0] == 0:
        listeners = parse_listeners(result[1])
    else:
        unreadable.append("listeners")

    firewall_tool: str | None = None
    firewall_active: bool | None = None
    for tool, argv, marker in (
        ("ufw", ["ufw", "status"], "status: active"),
        ("firewalld", ["firewall-cmd", "--state"], "running"),
    ):
        result = runner(argv)
        if result is None:
            continue
        firewall_tool = tool
        firewall_active = marker in result[1].lower()
        break
    if firewall_tool is None:
        unreadable.append("firewall")

    pending_updates: int | None = None
    result = runner(["apt-get", "-s", "upgrade"])
    if result is not None and result[0] == 0:
        pending_updates = parse_pending_updates(result[1])
    else:
        unreadable.append("pending_updates")

    ssh_password_auth: bool | None = None
    with contextlib.suppress(OSError):
        ssh_password_auth = parse_ssh_password_auth(sshd_config.read_text(encoding="utf-8"))
    if ssh_password_auth is None:
        unreadable.append("ssh_password_auth")

    return HostFacts(
        hostname=hostname,
        os_name=os_name,
        kernel=kernel,
        listeners=listeners,
        firewall_tool=firewall_tool,
        firewall_active=firewall_active,
        pending_updates=pending_updates,
        ssh_password_auth=ssh_password_auth,
        unreadable=tuple(unreadable),
    )
