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
    update_tool: str | None = None
    disk_encrypted: bool | None = None
    unattended_upgrades: bool | None = None
    ssh_password_paths: dict[str, bool] | None = None
    ssh_password_match_scoped: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ssh_password_auth(self) -> bool | None:
        """ECR-0111: derived, not stored.

        This was its own field alongside `ssh_password_paths`, which is two records of one
        fact and therefore two records that can disagree. Deriving it makes that
        impossible.
        """

        if self.ssh_password_paths is None:
            return None
        return self.ssh_password_paths.get("password_authentication")


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


# (tool, argv, the token that proves the command answered at all)
# The token is separate from the active test because a command can fail in a way that
# produces output: `ufw status` without root prints an error, and reading "active" out of
# its absence turns a permission problem into a security finding.
_FIREWALL_TOOLS: tuple[tuple[str, list[str], str], ...] = (
    ("ufw", ["ufw", "status"], "status:"),
    ("firewalld", ["firewall-cmd", "--state"], "running"),
)

# `firewall-cmd --state` prints "not running" when firewalld is stopped, and exits non-zero.
# A substring test for "running" matched that too, so a STOPPED firewall reported as active -
# the same defect as above in the direction that hides a real problem.
_FIREWALL_ACTIVE: dict[str, Callable[[str], bool]] = {
    "ufw": lambda output: "status: active" in output,
    "firewalld": lambda output: output.strip() == "running",
}


_UPDATE_TOOLS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    # (tool, argv, the exit code that means "the command answered")
    # `dnf check-update` exits 100 when updates exist and 0 when none do, so treating a
    # non-zero exit as failure would report a machine with pending updates as unreadable -
    # the one case the check exists for.
    ("apt", ("apt-get", "-s", "upgrade"), 0),
    ("dnf", ("dnf", "--quiet", "check-update"), 100),
    ("zypper", ("zypper", "--quiet", "list-updates"), 0),
    ("pacman", ("pacman", "-Qu"), 0),
)


def parse_dnf_updates(output: str) -> int:
    """Count upgradable packages from `dnf check-update`.

    dnf prints a blank-line-separated header and an `Obsoleting Packages` trailer; only
    the `name.arch version repo` rows are updates.
    """

    count = 0
    for raw in output.splitlines():
        line = raw.rstrip()
        # Everything after this marker is what the updates replace, not another update.
        # Counting it inflated the number by one per obsoleted package.
        if line.startswith("Obsoleting"):
            break
        if not line or line.startswith(" "):
            continue
        parts = line.split()
        if len(parts) >= 3 and "." in parts[0]:
            count += 1
    return count


def parse_zypper_updates(output: str) -> int:
    """Count rows of `zypper list-updates`, whose table rows begin with `v |`."""

    return sum(1 for line in output.splitlines() if line.strip().startswith("v |"))


def parse_pacman_updates(output: str) -> int:
    """Count lines of `pacman -Qu`; each line is one out-of-date package."""

    return sum(1 for line in output.splitlines() if line.strip())


_UPDATE_PARSERS = {
    "apt": parse_pending_updates,
    "dnf": parse_dnf_updates,
    "zypper": parse_zypper_updates,
    "pacman": parse_pacman_updates,
}


def parse_disk_encryption(lsblk_output: str) -> bool:
    """Whether any block device on this machine is an encrypted mapping.

    `lsblk -rno TYPE` names a LUKS/dm-crypt mapping `crypt`. Absence of one is a real
    answer, not an unknown: the command ran and listed every device.
    """

    return any(line.strip() == "crypt" for line in lsblk_output.splitlines())


def parse_unattended_upgrades(conf: str) -> bool:
    """Whether APT is configured to install updates on its own.

    A value of "0" and an absent directive both mean the same thing operationally, so both
    read False. The file's absence is handled by the caller as unreadable, not as False -
    a machine with no APT is not a machine that declined automatic updates.
    """

    for raw in conf.splitlines():
        line = raw.strip()
        if line.startswith("//") or not line:
            continue
        if "Unattended-Upgrade" not in line:
            continue
        quoted = line.split('"')
        # `APT::Periodic::Unattended-Upgrade "1";` splits into three parts, and the value
        # is the middle one. Reading index 3 looked plausible and matched nothing.
        if len(quoted) >= 2 and quoted[1].strip() not in {"0", ""}:
            return True
    return False


_MAX_INCLUDE_DEPTH = 8

IncludeResolver = Callable[[str], Sequence[str]]


def flatten_sshd_config(text: str, *, resolve: IncludeResolver, _depth: int = 0) -> str:
    """Inline `Include` directives where they appear, as sshd does.

    Modern Ubuntu ships `Include /etc/ssh/sshd_config.d/*.conf` near the top of the main
    file and puts the settings that matter in the drop-ins, so a parser that reads only the
    main file reads a file whose every auth directive is commented out. Measured on the
    live VPS: the effective setting lives in a drop-in, and the collector called the fact
    unmeasured.

    Depth is bounded: sshd permits nested includes, and a config that includes itself must
    not hang a collector.
    """

    if _depth >= _MAX_INCLUDE_DEPTH:
        return text
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        parts = line.split()
        # No `startswith("#")` guard here. A commented Include yields a first token of
        # "#Include" or "#", neither of which equals "include", so the guard could not
        # change a verdict - measured as GREEN by ECR-0110/M6. `is_public` set the
        # precedent: dead code in a security-relevant path is a liability, so it is gone
        # rather than left looking load-bearing. The witness for the behaviour stays.
        if len(parts) >= 2 and parts[0].lower() == "include":
            for pattern in parts[1:]:
                for included in resolve(pattern):
                    out.append(flatten_sshd_config(included, resolve=resolve, _depth=_depth + 1))
            continue
        out.append(raw)
    return "\n".join(out)


def sshd_directive(sshd_config: str, keyword: str) -> str | None:
    """The effective value of one sshd keyword, or None when the config never sets it.

    First match wins, per sshd_config(5). Comments are skipped. This is the general form of
    `parse_ssh_password_auth`, which stays because password auth is the finding everything
    else here exists to support.
    """

    return _directive_scopes(sshd_config, keyword)[0]


def _directive_scopes(sshd_config: str, keyword: str) -> tuple[str | None, bool]:
    """`(global_value, match_scoped)` for one keyword.

    `global_value` is the connection-independent value: the first occurrence in
    unconditional scope, which is what `sshd -T` (no `-C`) reports. `match_scoped` is True
    when the keyword also appears inside a `Match` block that is not `Match all`, meaning the
    effective value differs for some connections and a single global boolean would mislead.

    ECR-0112: reading a `Match`-scoped directive as if it were global under-reports a config
    like `PasswordAuthentication no` + `Match Address 0.0.0.0/0 { PasswordAuthentication
    yes }` - a false all-clear on the finding that matters most. `Match all` returns to
    unconditional scope, verified against a real `sshd -T`.
    """

    wanted = keyword.lower()
    global_value: str | None = None
    match_scoped = False
    conditional = False
    for raw in sshd_config.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        head = parts[0].lower()
        if head == "match":
            conditional = [token.lower() for token in parts[1:]] != ["all"]
            continue
        if len(parts) >= 2 and head == wanted:
            if conditional:
                match_scoped = True
            elif global_value is None:
                global_value = parts[1].lower()
    return global_value, match_scoped


def match_scoped_password_paths(sshd_config: str) -> tuple[str, ...]:
    """Password facts whose effective value is decided inside a `Match` block.

    These are conditional: `sshd -T -C addr=…` is the only way to know the value for a
    given connection, and this collector cannot run it. Reported as conditional rather than
    folded into a global yes/no, so a `Match`-hidden opening is never mistaken for an
    all-clear.
    """

    return tuple(
        fact
        for keyword, _enabled, fact in _PASSWORD_PATHS
        if _directive_scopes(sshd_config, keyword)[1]
    )


# Every way an sshd can end up accepting something a human typed rather than a key.
# `KbdInteractiveAuthentication` with PAM is a password prompt by another name, and
# `PermitEmptyPasswords` is worse than either. ECR-0110 read only the first of the three
# and said so; on the live VPS the other two happen to be safe, which is luck, not coverage.
#
# The third element is the upstream default, MEASURED by running `sshd -T -f` against a
# config containing nothing but `Port 22` on a real OpenSSH:
#
#     passwordauthentication yes    <- open
#     kbdinteractiveauthentication yes    <- open
#     permitemptypasswords no
#
# Two of the three default to OPEN, so an unset directive is not neutral. It is recorded
# rather than acted on: the default is a property of how a given sshd was built, and
# claiming it for every machine would be guessing with a citation. See ECR-0111 §5.
_PASSWORD_PATHS: tuple[tuple[str, str, str], ...] = (
    ("PasswordAuthentication", "yes", "password_authentication"),
    ("KbdInteractiveAuthentication", "yes", "keyboard_interactive_authentication"),
    ("PermitEmptyPasswords", "yes", "empty_passwords"),
)

# Measured, not assumed. Used only to say "unset, and upstream leaves this open" - never to
# synthesise a value the config did not state.
UPSTREAM_DEFAULT_OPEN: frozenset[str] = frozenset(
    {"password_authentication", "keyboard_interactive_authentication"}
)


def parse_ssh_password_paths(sshd_config: str) -> dict[str, bool] | None:
    """Which password-capable auth paths are open, or None when the config sets none of them.

    A path the config never mentions is omitted rather than defaulted: sshd's build default
    for `KbdInteractiveAuthentication` is `yes`, so guessing here would either invent a
    finding or hide one.
    """

    found = {
        fact: sshd_directive(sshd_config, keyword) == enabled_value
        for keyword, enabled_value, fact in _PASSWORD_PATHS
        if sshd_directive(sshd_config, keyword) is not None
    }
    return found or None


def parse_ssh_password_auth(sshd_config: str) -> bool | None:
    """Return whether password auth is enabled, or None when the config does not say.

    **The first value wins**, which is sshd's rule: "unless noted otherwise, for each
    keyword, the first obtained value will be used". This used to keep the last one. On the
    live VPS two drop-ins disagree - `50-cloud-init.conf` says yes and
    `60-cloudimg-settings.conf` says no - and taking the last would have reported the
    opposite of what `sshd -T` reports.

    A config that never mentions the directive is not evidence of either setting - the
    effective value comes from the build default - so it reads as unmeasured.
    """

    for raw in sshd_config.splitlines():
        line = raw.strip()
        # The `#` test is defensive, not load-bearing: a commented directive already fails
        # the token comparison below. Mutating it away changes no verdict. Kept because it
        # states the intent, and recorded as unwitnessed rather than left looking proven.
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() == "passwordauthentication":
            return parts[1].lower() == "yes"
    return None


def _filesystem_include_resolver(base: Path) -> IncludeResolver:
    """Read Include patterns off disk in the order sshd would: globbed, then sorted."""

    def resolve(pattern: str) -> Sequence[str]:
        target = Path(pattern)
        root, glob = (target.parent, target.name) if target.is_absolute() else (base, pattern)
        contents: list[str] = []
        try:
            matches = sorted(root.glob(glob))
        except (OSError, ValueError):
            return ()
        for path in matches:
            with contextlib.suppress(OSError):
                contents.append(path.read_text(encoding="utf-8"))
        return contents

    return resolve


def read_host_facts(
    runner: CommandRunner = run_command,
    *,
    os_release: Path = Path("/etc/os-release"),
    sshd_config: Path = Path("/etc/ssh/sshd_config"),
    auto_upgrades: Path = Path("/etc/apt/apt.conf.d/20auto-upgrades"),
    include_resolver: IncludeResolver | None = None,
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
    for tool, argv, readable_token in _FIREWALL_TOOLS:
        result = runner(argv)
        if result is None:
            continue
        firewall_tool = tool
        output = result[1].lower()
        if readable_token not in output:
            # ECR-0109: the tool is installed and did not answer - almost always because
            # `ufw status` needs root. That is not "no firewall". Measured on the live VPS,
            # where this reported an ACTIVE firewall as inactive and advised enabling it.
            unreadable.append("firewall")
            break
        firewall_active = _FIREWALL_ACTIVE[tool](output)
        break
    if firewall_tool is None:
        unreadable.append("firewall")

    # Try each package manager in turn rather than assuming Debian. The first one present
    # on the machine answers; the rest are not installed and return None from the runner.
    pending_updates: int | None = None
    update_tool: str | None = None
    for tool, command, ok_code in _UPDATE_TOOLS:
        result = runner(list(command))
        if result is None:
            continue
        if result[0] not in (0, ok_code):
            continue
        update_tool = tool
        pending_updates = _UPDATE_PARSERS[tool](result[1])
        break
    if update_tool is None:
        unreadable.append("pending_updates")

    disk_encrypted: bool | None = None
    result = runner(["lsblk", "-rno", "TYPE"])
    if result is not None and result[0] == 0:
        disk_encrypted = parse_disk_encryption(result[1])
    else:
        unreadable.append("disk_encryption")

    unattended_upgrades: bool | None = None
    with contextlib.suppress(OSError):
        unattended_upgrades = parse_unattended_upgrades(auto_upgrades.read_text(encoding="utf-8"))
    if unattended_upgrades is None:
        unreadable.append("unattended_upgrades")

    ssh_password_paths: dict[str, bool] | None = None
    ssh_password_match_scoped: tuple[str, ...] = ()
    with contextlib.suppress(OSError):
        flattened = flatten_sshd_config(
            sshd_config.read_text(encoding="utf-8"),
            resolve=include_resolver or _filesystem_include_resolver(sshd_config.parent),
        )
        ssh_password_paths = parse_ssh_password_paths(flattened)
        ssh_password_match_scoped = match_scoped_password_paths(flattened)
    if ssh_password_paths is None:
        unreadable.append("ssh_password_auth")

    return HostFacts(
        hostname=hostname,
        os_name=os_name,
        kernel=kernel,
        listeners=listeners,
        firewall_tool=firewall_tool,
        firewall_active=firewall_active,
        pending_updates=pending_updates,
        update_tool=update_tool,
        disk_encrypted=disk_encrypted,
        unattended_upgrades=unattended_upgrades,
        ssh_password_paths=ssh_password_paths,
        ssh_password_match_scoped=ssh_password_match_scoped,
        unreadable=tuple(unreadable),
    )
