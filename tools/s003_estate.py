"""S-003 read-only collection for a real, owner-declared estate.

This module deliberately lives outside ``src/aqelyn``. It invokes host tools and
hands their documents to the platform; no analytical engine learns how to collect
from a host.

Asset identity is a deployable service boundary:

* a systemd unit is a ``systemd_unit`` asset;
* an nginx virtual host is an ``nginx_vhost`` asset;
* a listener or port is an observation attached to an asset, never an asset itself.

That distinction lets a virtual host without a dedicated unit carry its own owner
declaration while keeping transient listener details out of object identity.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_OUTPUT_BYTES = 128 * 1024 * 1024

EstateAssetKind = Literal["systemd_unit", "nginx_vhost"]
CommandName = Literal["syft", "systemctl", "ss", "nft", "nginx"]


class S003CollectionError(RuntimeError):
    """The collector could not produce an honest handed-in document."""


class EstateAsset(BaseModel):
    """A stable deployment boundary, not a listener."""

    model_config = ConfigDict(extra="forbid")

    asset_key: str
    kind: EstateAssetKind
    native_id: str
    display_name: str

    @field_validator("asset_key", "native_id", "display_name")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("estate asset fields must not be empty")
        return value


class UnitRecord(EstateAsset):
    kind: Literal["systemd_unit"] = "systemd_unit"
    load_state: str
    active_state: str
    sub_state: str
    main_pid: int | None = None
    exec_start: str | None = None
    fragment_path: str | None = None
    user: str | None = None
    group: str | None = None


class NginxVHost(EstateAsset):
    kind: Literal["nginx_vhost"] = "nginx_vhost"
    source_file: str | None = None
    server_names: list[str] = Field(default_factory=list)
    upstream_targets: list[str] = Field(default_factory=list)


class ListenerObservation(BaseModel):
    """Host-local configuration observed for an asset.

    ``asset_key=None`` means the listener was observed but could not be joined to
    a registered service. That is intentionally distinct from a registered service
    for which no surface could be derived.
    """

    model_config = ConfigDict(extra="forbid")

    asset_key: str | None = None
    protocol: Literal["tcp", "udp"]
    address: str
    port: int
    process_ids: list[int] = Field(default_factory=list)
    process_names: list[str] = Field(default_factory=list)

    @field_validator("address")
    @classmethod
    def _address(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("listener address must not be empty")
        return value

    @field_validator("port")
    @classmethod
    def _port(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1 or value > 65_535:
            raise ValueError("listener port must be in [1,65535]")
        return value


class UnitInventoryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collected_at: datetime
    units: list[UnitRecord]
    unavailable_details: dict[str, str] = Field(default_factory=dict)


class ServiceSurfaceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collected_at: datetime
    listeners_raw: str | None
    firewall_raw: dict[str, Any] | None
    nginx_config: str | None
    listeners: list[ListenerObservation] = Field(default_factory=list)
    vhosts: list[NginxVHost] = Field(default_factory=list)
    unavailable_details: dict[str, str] = Field(default_factory=dict)


class CollectionManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CommandName
    argv: list[str]
    required: bool
    returncode: int
    stdout_bytes: int
    stderr: str | None = None


class CollectionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collected_at: datetime
    commands: list[CollectionManifestEntry]
    documents: list[str]


@dataclass(frozen=True)
class CommandTemplate:
    name: CommandName
    argv: tuple[str, ...]
    purpose: str
    required: bool
    timeout_seconds: int
    output_name: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    """Execute an allow-listed command without a shell or privilege escalation."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> CommandResult:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                env=_bounded_environment(),
            )
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if (
                    os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size
                    > max_output_bytes
                ):
                    process.kill()
                    process.wait()
                    raise S003CollectionError(
                        f"{Path(argv[0]).name} output exceeds the collection size bound"
                    )
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait()
                    raise subprocess.TimeoutExpired(list(argv), timeout_seconds)
                time.sleep(0.05)
            returncode = process.wait()
            if (
                os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size
                > max_output_bytes
            ):
                raise S003CollectionError(
                    f"{Path(argv[0]).name} output exceeds the collection size bound"
                )
            stdout.seek(0)
            stderr.seek(0)
            return CommandResult(
                returncode=returncode,
                stdout=stdout.read(max_output_bytes + 1),
                stderr=stderr.read(max_output_bytes + 1),
            )


COMMAND_TEMPLATES: tuple[CommandTemplate, ...] = (
    CommandTemplate(
        name="syft",
        argv=("syft", "dir:/", "-o", "cyclonedx-json"),
        purpose="Produce a package inventory of the local filesystem.",
        required=True,
        timeout_seconds=300,
        output_name="sbom.json",
    ),
    CommandTemplate(
        name="systemctl",
        argv=(
            "systemctl",
            "list-units",
            "--type=service",
            "--state=running",
            "--no-legend",
            "--no-pager",
            "--plain",
        ),
        purpose="List running service units without changing their state.",
        required=True,
        timeout_seconds=20,
        output_name="systemctl-list-units.txt",
    ),
    CommandTemplate(
        name="ss",
        argv=(
            "ss",
            "--no-header",
            "--oneline",
            "--listening",
            "--tcp",
            "--udp",
            "--numeric",
            "--processes",
        ),
        purpose="Read local listening sockets; no connection is attempted.",
        required=False,
        timeout_seconds=20,
        output_name="ss-listeners.txt",
    ),
    CommandTemplate(
        name="nft",
        argv=("nft", "--json", "list", "ruleset"),
        purpose="Read the local firewall ruleset.",
        required=False,
        timeout_seconds=20,
        output_name="nft-ruleset.json",
    ),
    CommandTemplate(
        name="nginx",
        argv=("nginx", "-T"),
        purpose="Read and validate the effective reverse-proxy configuration.",
        required=False,
        timeout_seconds=20,
        output_name="nginx-config.txt",
    ),
)


def unit_detail_command(unit_name: str) -> CommandTemplate:
    selected = _unit_name(unit_name)
    return CommandTemplate(
        name="systemctl",
        argv=(
            "systemctl",
            "show",
            selected,
            "--no-pager",
            "--property=Id,Description,LoadState,ActiveState,SubState,MainPID,"
            "ExecStart,FragmentPath,User,Group",
        ),
        purpose="Read one discovered unit's identity and execution metadata.",
        required=True,
        timeout_seconds=10,
        output_name=f"unit-{_safe_filename(selected)}.txt",
    )


def collection_command_templates() -> tuple[CommandTemplate, ...]:
    """The complete static command vocabulary used by the collector."""

    return (
        *COMMAND_TEMPLATES,
        CommandTemplate(
            name="systemctl",
            argv=(
                "systemctl",
                "show",
                "{discovered-unit}",
                "--no-pager",
                "--property=Id,Description,LoadState,ActiveState,SubState,MainPID,"
                "ExecStart,FragmentPath,User,Group",
            ),
            purpose="Read each discovered unit's identity and execution metadata.",
            required=True,
            timeout_seconds=10,
            output_name="unit-{discovered-unit}.txt",
        ),
    )


def canonical_asset_key(kind: EstateAssetKind, native_id: str) -> str:
    selected = native_id.strip()
    if not selected:
        raise S003CollectionError("asset native id must not be empty")
    return f"{kind}:{selected}"


def validate_read_only_command(argv: Sequence[str]) -> None:
    """Fail closed unless ``argv`` is one of S-003's enumerated read paths."""

    selected = tuple(argv)
    if not selected:
        raise S003CollectionError("empty command is not allowed")
    executable = Path(selected[0]).name
    if executable == "syft" and selected == COMMAND_TEMPLATES[0].argv:
        return
    if executable == "systemctl":
        if selected == COMMAND_TEMPLATES[1].argv:
            return
        if (
            len(selected) == 5
            and selected[1] == "show"
            and selected[3] == "--no-pager"
            and selected[4].startswith("--property=")
        ):
            _unit_name(selected[2])
            return
    if executable == "ss" and selected == COMMAND_TEMPLATES[2].argv:
        return
    if executable == "nft" and selected == COMMAND_TEMPLATES[3].argv:
        return
    if executable == "nginx" and selected == COMMAND_TEMPLATES[4].argv:
        return
    raise S003CollectionError(f"command is outside the S-003 read-only allowlist: {selected!r}")


def ensure_private_workdir(workdir: Path, *, repository_root: Path = REPOSITORY_ROOT) -> Path:
    """Refuse collection into any Git working tree path."""

    selected = workdir.expanduser().resolve()
    root = repository_root.resolve()
    ancestors = (selected, *selected.parents)
    if (
        selected == root
        or root in selected.parents
        or any((ancestor / ".git").exists() for ancestor in ancestors)
    ):
        raise S003CollectionError(
            "S-003 collection documents must be written outside the repository"
        )
    selected.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(OSError):
        os.chmod(selected, 0o700)
    return selected


def parse_unit_list(document: str) -> list[UnitRecord]:
    units: list[UnitRecord] = []
    for raw_line in document.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        columns = line.split(maxsplit=4)
        if len(columns) < 4:
            raise S003CollectionError("systemctl unit list contains an incomplete row")
        native_id, load_state, active_state, sub_state = columns[:4]
        description = columns[4] if len(columns) == 5 else native_id
        units.append(
            UnitRecord(
                asset_key=canonical_asset_key("systemd_unit", native_id),
                native_id=native_id,
                display_name=description,
                load_state=load_state,
                active_state=active_state,
                sub_state=sub_state,
            )
        )
    units.sort(key=lambda item: item.asset_key)
    return units


def parse_unit_details(document: str, discovered: UnitRecord) -> UnitRecord:
    values: dict[str, str] = {}
    for line in document.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    native_id = values.get("Id") or discovered.native_id
    if native_id != discovered.native_id:
        raise S003CollectionError("systemctl show returned details for a different unit")
    return discovered.model_copy(
        update={
            "display_name": values.get("Description") or discovered.display_name,
            "load_state": values.get("LoadState") or discovered.load_state,
            "active_state": values.get("ActiveState") or discovered.active_state,
            "sub_state": values.get("SubState") or discovered.sub_state,
            "main_pid": _optional_pid(values.get("MainPID")),
            "exec_start": values.get("ExecStart") or None,
            "fragment_path": values.get("FragmentPath") or None,
            "user": values.get("User") or None,
            "group": values.get("Group") or None,
        },
        deep=True,
    )


class EstateCollector:
    def __init__(
        self,
        runner: CommandRunner,
        *,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        if max_output_bytes < 1:
            raise S003CollectionError("max_output_bytes must be positive")
        self.runner = runner
        self.max_output_bytes = max_output_bytes

    def collect(self, workdir: Path, *, reuse: bool = False) -> CollectionManifest:
        selected_workdir = ensure_private_workdir(workdir)
        collected_at = datetime.now(UTC)
        entries: list[CollectionManifestEntry] = []

        outputs: dict[str, bytes] = {}
        for command in COMMAND_TEMPLATES:
            result = self._execute(command, selected_workdir, reuse=reuse)
            entries.append(result[0])
            outputs[command.output_name] = result[1]

        units = parse_unit_list(outputs["systemctl-list-units.txt"].decode("utf-8"))
        detailed_units: list[UnitRecord] = []
        unavailable: dict[str, str] = {}
        for unit in units:
            command = unit_detail_command(unit.native_id)
            entry, output = self._execute(command, selected_workdir, reuse=reuse)
            entries.append(entry)
            if entry.returncode != 0:
                unavailable[unit.asset_key] = entry.stderr or "systemctl show failed"
                continue
            detailed_units.append(parse_unit_details(output.decode("utf-8"), unit))

        unit_document = UnitInventoryDocument(
            collected_at=collected_at,
            units=detailed_units,
            unavailable_details=unavailable,
        )
        _write_private_json(selected_workdir / "unit-inventory.json", unit_document)

        surface_unavailable: dict[str, str] = {}
        listeners_raw = _optional_text_output(
            entries,
            outputs,
            output_name="ss-listeners.txt",
            command_name="ss",
            unavailable=surface_unavailable,
        )
        firewall_raw = _optional_json_output(
            entries,
            outputs,
            output_name="nft-ruleset.json",
            command_name="nft",
            unavailable=surface_unavailable,
        )
        nginx_entry = next(entry for entry in entries if entry.name == "nginx")
        nginx_config = (
            outputs["nginx-config.txt"].decode("utf-8") if nginx_entry.returncode == 0 else None
        )
        if nginx_entry.returncode != 0:
            surface_unavailable["nginx"] = nginx_entry.stderr or "nginx config unavailable"
        surface_document = ServiceSurfaceDocument(
            collected_at=collected_at,
            listeners_raw=listeners_raw,
            firewall_raw=firewall_raw,
            nginx_config=nginx_config,
            unavailable_details=surface_unavailable,
        )
        _write_private_json(selected_workdir / "service-surface.json", surface_document)

        manifest = CollectionManifest(
            collected_at=collected_at,
            commands=entries,
            documents=["sbom.json", "unit-inventory.json", "service-surface.json"],
        )
        _write_private_json(selected_workdir / "collection-manifest.json", manifest)
        return manifest

    def _execute(
        self,
        command: CommandTemplate,
        workdir: Path,
        *,
        reuse: bool,
    ) -> tuple[CollectionManifestEntry, bytes]:
        validate_read_only_command(command.argv)
        path = workdir / command.output_name
        if reuse and path.exists():
            output = path.read_bytes()
            if len(output) > self.max_output_bytes:
                raise S003CollectionError(f"cached {command.name} output exceeds the size bound")
            return (
                CollectionManifestEntry(
                    name=command.name,
                    argv=list(command.argv),
                    required=command.required,
                    returncode=0,
                    stdout_bytes=len(output),
                ),
                output,
            )
        try:
            result = self.runner.run(
                command.argv,
                timeout_seconds=command.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except subprocess.TimeoutExpired as exc:
            raise S003CollectionError(
                f"{command.name} exceeded its {command.timeout_seconds}s collection bound"
            ) from exc
        if len(result.stdout) > self.max_output_bytes:
            raise S003CollectionError(f"{command.name} output exceeds the size bound")
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode != 0 and command.required:
            raise S003CollectionError(
                f"required command {command.name} failed: {stderr or 'no detail'}"
            )
        output = result.stdout
        if command.name == "nginx" and not output and result.returncode == 0:
            output = result.stderr
            stderr = ""
        if result.returncode == 0:
            path.write_bytes(output)
        return (
            CollectionManifestEntry(
                name=command.name,
                argv=list(command.argv),
                required=command.required,
                returncode=result.returncode,
                stdout_bytes=len(output),
                stderr=stderr or None,
            ),
            output,
        )


def _optional_json_output(
    entries: Sequence[CollectionManifestEntry],
    outputs: Mapping[str, bytes],
    *,
    output_name: str,
    command_name: CommandName,
    unavailable: dict[str, str],
) -> dict[str, Any] | None:
    entry = next(item for item in entries if item.name == command_name)
    if entry.returncode != 0:
        unavailable[command_name] = entry.stderr or f"{command_name} unavailable"
        return None
    try:
        loaded = json.loads(outputs[output_name])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise S003CollectionError(f"{command_name} returned malformed JSON") from exc
    if not isinstance(loaded, dict):
        raise S003CollectionError(f"{command_name} JSON must be an object")
    return loaded


def _optional_text_output(
    entries: Sequence[CollectionManifestEntry],
    outputs: Mapping[str, bytes],
    *,
    output_name: str,
    command_name: CommandName,
    unavailable: dict[str, str],
) -> str | None:
    entry = next(item for item in entries if item.name == command_name)
    if entry.returncode != 0:
        unavailable[command_name] = entry.stderr or f"{command_name} unavailable"
        return None
    try:
        return outputs[output_name].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise S003CollectionError(f"{command_name} returned non-UTF-8 output") from exc


def _write_private_json(path: Path, model: BaseModel) -> None:
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    with suppress(OSError):
        os.chmod(path, 0o600)


def _bounded_environment() -> dict[str, str]:
    selected = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "LANG", "LC_ALL", "PATH", "SYSTEMD_PAGER"}
    }
    selected["SYSTEMD_PAGER"] = ""
    selected["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
    return selected


def _unit_name(value: str) -> str:
    selected = value.strip()
    if (
        not selected.endswith(".service")
        or "/" in selected
        or "\\" in selected
        or selected.startswith("-")
        or any(character.isspace() for character in selected)
    ):
        raise S003CollectionError(f"invalid discovered systemd unit name: {value!r}")
    return selected


def _safe_filename(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._-" else "_" for character in value
    )


def _optional_pid(value: str | None) -> int | None:
    if value is None or not value.strip() or value == "0":
        return None
    try:
        selected = int(value)
    except ValueError as exc:
        raise S003CollectionError("systemctl MainPID is not an integer") from exc
    if selected < 1:
        raise S003CollectionError("systemctl MainPID must be positive")
    return selected


def _plan() -> None:
    for command in collection_command_templates():
        print(json.dumps({"argv": list(command.argv), "purpose": command.purpose}))


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect S-003 host-local documents")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="Print every command shape without running it")
    collect_parser = subparsers.add_parser("collect", help="Collect the three private documents")
    collect_parser.add_argument("--workdir", type=Path, required=True)
    collect_parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        _plan()
        return 0
    collector = EstateCollector(SubprocessCommandRunner())
    manifest = collector.collect(args.workdir, reuse=bool(args.reuse))
    print(
        json.dumps(
            {
                "commands_executed": len(manifest.commands),
                "documents_written": len(manifest.documents),
                "detail": "Per-asset collection remains in the private workdir.",
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
