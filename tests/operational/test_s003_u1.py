from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import tools.s003_estate as s003_estate
from pydantic import ValidationError
from tools.s003_estate import (
    COMMAND_TEMPLATES,
    SURFACE_NOT_DERIVED_REASONS,
    SYFT_EXCLUDE_PATTERNS,
    CollectionManifest,
    CommandResult,
    EstateAsset,
    EstateCollector,
    ListenerObservation,
    S003CollectionError,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
    canonical_asset_key,
    collection_command_templates,
    command_with_executable,
    ensure_private_workdir,
    parse_unit_list,
    unit_detail_command,
    validate_read_only_command,
)
from tools.s004_handin import (
    S004HandInError,
    parse_firewall_ruleset_capture,
    parse_privileged_socket_capture,
    parse_proxy_configuration_capture,
    prepare_handed_in_capture_set,
)


class _CollectionRunner:
    def __init__(
        self,
        *,
        fail_syft: bool = False,
        interrupt_syft: bool = False,
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[Mapping[str, str] | None] = []
        self.fail_syft = fail_syft
        self.interrupt_syft = interrupt_syft

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        max_output_bytes: int,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        assert timeout_seconds > 0
        assert max_output_bytes > 0
        selected = tuple(argv)
        self.commands.append(selected)
        self.environments.append(environment)
        if selected[1:] == COMMAND_TEMPLATES[0].argv[1:]:
            if self.interrupt_syft:
                raise KeyboardInterrupt
            if self.fail_syft:
                return CommandResult(returncode=1, stdout=b"", stderr=b"syft failed")
            return _ok(b'{"bomFormat":"CycloneDX","components":[]}')
        if selected[1:] == COMMAND_TEMPLATES[1].argv[1:]:
            return _ok(
                b"alpha.service loaded active running Alpha service\n"
                b"beta.service loaded active running Beta service\n"
            )
        if selected[1:] == COMMAND_TEMPLATES[2].argv[1:]:
            return _ok(b'tcp LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:* users:(("alpha",pid=41))\n')
        if selected[1:] == COMMAND_TEMPLATES[3].argv[1:]:
            return _ok(b'{"nftables":[]}')
        if selected[1:] == COMMAND_TEMPLATES[4].argv[1:]:
            return CommandResult(
                returncode=0,
                stdout=b"",
                stderr=b"server { listen 443 ssl; }\n",
            )
        if selected[1:] == unit_detail_command("alpha.service").argv[1:]:
            return _ok(
                b"Id=alpha.service\n"
                b"Description=Alpha service\n"
                b"LoadState=loaded\n"
                b"ActiveState=active\n"
                b"SubState=running\n"
                b"MainPID=41\n"
                b"ExecStart={ path=/usr/bin/alpha ; argv[]=/usr/bin/alpha ; }\n"
                b"FragmentPath=/etc/systemd/system/alpha.service\n"
                b"User=svc-alpha\n"
                b"Group=svc-alpha\n"
            )
        if selected[1:] == unit_detail_command("beta.service").argv[1:]:
            return _ok(
                b"Id=beta.service\n"
                b"Description=Beta service\n"
                b"LoadState=loaded\n"
                b"ActiveState=active\n"
                b"SubState=running\n"
                b"MainPID=0\n"
                b"ExecStart=\n"
                b"FragmentPath=/lib/systemd/system/beta.service\n"
                b"User=\n"
                b"Group=\n"
            )
        raise AssertionError(f"unexpected command: {selected!r}")


def _ok(stdout: bytes) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr=b"")


def _tool_lookup(name: str) -> str | None:
    return f"/usr/bin/{name}"


def test_s003_no_host_reference_in_src() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    references = [
        path for path in src.rglob("*.py") if "s003_estate" in path.read_text(encoding="utf-8")
    ]
    assert references == []


def test_s003_collection_commands_enumerated() -> None:
    templates = collection_command_templates()
    assert {item.name for item in templates} == {"syft", "systemctl", "ss", "nft", "nginx"}
    syft = templates[0]
    assert syft.argv.count("--exclude") == len(SYFT_EXCLUDE_PATTERNS)
    assert all(pattern in syft.argv for pattern in SYFT_EXCLUDE_PATTERNS)
    assert all("venv" not in pattern for pattern in SYFT_EXCLUDE_PATTERNS)
    for template in templates:
        if "{discovered-unit}" not in template.argv:
            validate_read_only_command(template.argv)
        assert template.timeout_seconds > 0
        assert template.purpose
        assert "sudo" not in template.argv

    for forbidden in (
        ("systemctl", "restart", "alpha.service"),
        ("systemctl", "enable", "alpha.service"),
        ("nft", "add", "rule"),
        ("curl", "https://example.invalid"),
        ("nmap", "127.0.0.1"),
        ("sudo", "systemctl", "show", "alpha.service"),
    ):
        with pytest.raises(S003CollectionError):
            validate_read_only_command(forbidden)


def test_s003_asset_is_service_boundary_not_port() -> None:
    unit = EstateAsset(
        asset_key=canonical_asset_key("systemd_unit", "alpha.service"),
        kind="systemd_unit",
        native_id="alpha.service",
        display_name="Alpha",
    )
    vhost = EstateAsset(
        asset_key=canonical_asset_key("nginx_vhost", "example.test"),
        kind="nginx_vhost",
        native_id="example.test",
        display_name="Example",
    )
    listener = ListenerObservation(
        asset_key=vhost.asset_key,
        protocol="tcp",
        address="0.0.0.0",
        port=443,
    )

    assert unit.kind == "systemd_unit"
    assert vhost.kind == "nginx_vhost"
    assert listener.port == 443
    with pytest.raises(ValidationError):
        EstateAsset.model_validate(
            {
                "asset_key": "port:443",
                "kind": "port",
                "native_id": "443",
                "display_name": "HTTPS",
            }
        )


def test_s003_collection_documents_stay_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    with pytest.raises(S003CollectionError, match="outside the repository"):
        ensure_private_workdir(repository / "private", repository_root=repository)

    selected = ensure_private_workdir(
        tmp_path / "elsewhere" / "private", repository_root=repository
    )
    assert selected == (tmp_path / "elsewhere" / "private").resolve()


def test_s003_collects_three_private_documents(tmp_path: Path) -> None:
    runner = _CollectionRunner()
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    manifest = EstateCollector(runner, tool_lookup=_tool_lookup).collect(
        tmp_path / "private",
        transient_root=transient_root,
    )

    assert manifest.documents == ["sbom.json", "unit-inventory.json", "service-surface.json"]
    assert len(manifest.commands) == len(COMMAND_TEMPLATES) + 2
    assert runner.commands == [
        *(
            command_with_executable(template, f"/usr/bin/{template.name}").argv
            for template in COMMAND_TEMPLATES
        ),
        command_with_executable(unit_detail_command("alpha.service"), "/usr/bin/systemctl").argv,
        command_with_executable(unit_detail_command("beta.service"), "/usr/bin/systemctl").argv,
    ]
    syft_environment = runner.environments[0]
    assert syft_environment is not None
    runtime_root = Path(syft_environment["HOME"]).parent
    assert runtime_root.parent == transient_root.resolve()
    assert runtime_root.name.startswith("aqelyn-s003-syft-")
    assert syft_environment["GOMAXPROCS"] == "2"
    assert syft_environment["SYFT_PARALLELISM"] == "2"

    stored_manifest = CollectionManifest.model_validate_json(
        (tmp_path / "private" / "collection-manifest.json").read_text(encoding="utf-8")
    )
    units = UnitInventoryDocument.model_validate_json(
        (tmp_path / "private" / "unit-inventory.json").read_text(encoding="utf-8")
    )
    surface_payload = json.loads(
        (tmp_path / "private" / "service-surface.json").read_text(encoding="utf-8")
    )
    surface = ServiceSurfaceDocument.model_validate(surface_payload)
    sbom = json.loads((tmp_path / "private" / "sbom.json").read_text(encoding="utf-8"))

    assert len(stored_manifest.commands) == 7
    assert [unit.native_id for unit in units.units] == ["alpha.service", "beta.service"]
    assert units.units[0].main_pid == 41
    assert units.units[1].main_pid is None
    assert surface.listeners_raw == (
        'tcp LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:* users:(("alpha",pid=41))\n'
    )
    assert surface.firewall_raw == {"nftables": []}
    assert surface.nginx_config == "server { listen 443 ssl; }\n"
    assert surface_payload["listeners"] is None
    assert surface_payload["vhosts"] is None
    assert surface.listeners is None
    assert surface.vhosts is None
    assert surface.unavailable_details["listeners"] == (SURFACE_NOT_DERIVED_REASONS["listeners"])
    assert surface.unavailable_details["vhosts"] == (SURFACE_NOT_DERIVED_REASONS["vhosts"])
    assert sbom["bomFormat"] == "CycloneDX"
    assert not runtime_root.exists()
    assert list(transient_root.iterdir()) == []


def test_s003_reuse_preserves_observation_time_for_freshness_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = datetime(2026, 7, 27, tzinfo=UTC)
    new = datetime(2026, 7, 29, tzinfo=UTC)

    class _Clock:
        current = old

        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            return cls.current

    monkeypatch.setattr(s003_estate, "datetime", _Clock)
    runner = _CollectionRunner()
    workdir = tmp_path / "private"
    collector = EstateCollector(runner, tool_lookup=_tool_lookup)
    initial = collector.collect(
        workdir,
        transient_root=tmp_path / "transient",
    )
    command_count = len(runner.commands)

    _Clock.current = new
    reused = collector.collect(workdir, reuse=True)
    inventory = UnitInventoryDocument.model_validate_json(
        (workdir / "unit-inventory.json").read_text(encoding="utf-8")
    )
    surface = ServiceSurfaceDocument.model_validate_json(
        (workdir / "service-surface.json").read_text(encoding="utf-8")
    )

    assert len(runner.commands) == command_count
    for model in (CollectionManifest, UnitInventoryDocument, ServiceSurfaceDocument):
        description = model.model_json_schema()["properties"]["collected_at"]["description"]
        assert "content described by this document was observed to be true" in description

    privileged = parse_privileged_socket_capture(
        'tcp LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:* users:(("alpha",pid=41))\n',
        captured_at=new,
    )
    proxy = parse_proxy_configuration_capture(
        """
        server {
            listen endpoint-reference;
            proxy_pass upstream-reference;
        }
        """,
        captured_at=new,
    )
    firewall = parse_firewall_ruleset_capture('{"nftables":[]}', captured_at=new)
    with pytest.raises(S004HandInError) as stale:
        prepare_handed_in_capture_set(
            inventory,
            surface,
            privileged_sockets=privileged,
            proxy_configuration=proxy,
            firewall_ruleset=firewall,
            max_skew=timedelta(hours=1),
        )
    assert stale.value.reason == "capture_time_skew_exceeded"
    assert initial.collected_at == old
    assert reused.collected_at == old
    assert inventory.collected_at == old
    assert surface.collected_at == old


def test_s003_structured_surface_not_derived_is_explicit() -> None:
    document = {
        "collected_at": "2026-07-27T00:00:00Z",
        "listeners_raw": "socket output",
        "firewall_raw": None,
        "nginx_config": "nginx output",
    }

    with pytest.raises(ValidationError, match="listeners=None requires"):
        ServiceSurfaceDocument.model_validate(document)

    derived_empty = ServiceSurfaceDocument.model_validate(
        {
            **document,
            "listeners": [],
            "vhosts": [],
            "unavailable_details": {},
        }
    )
    assert derived_empty.listeners == []
    assert derived_empty.vhosts == []

    with pytest.raises(ValidationError, match="cannot be both derived and unavailable"):
        ServiceSurfaceDocument.model_validate(
            {
                **document,
                "listeners": [],
                "vhosts": [],
                "unavailable_details": SURFACE_NOT_DERIVED_REASONS,
            }
        )


@pytest.mark.parametrize("fail_syft", [False, True])
def test_s003_transient_syft_is_verified_and_removed(
    tmp_path: Path,
    fail_syft: bool,
) -> None:
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    artifact = transient_root / "syft"
    artifact.write_bytes(b"owner-approved-syft")
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    runner = _CollectionRunner(fail_syft=fail_syft)

    def lookup(name: str) -> str | None:
        return None if name == "syft" else f"/usr/bin/{name}"

    def collect() -> CollectionManifest:
        return EstateCollector(runner, tool_lookup=lookup).collect(
            tmp_path / "private",
            transient_syft=artifact,
            syft_sha256=checksum,
            transient_root=transient_root,
        )

    if fail_syft:
        with pytest.raises(S003CollectionError, match="required command syft failed"):
            collect()
    else:
        collect()

    syft_environment = runner.environments[0]
    assert syft_environment is not None
    runtime_root = Path(syft_environment["HOME"]).parent
    assert runner.commands[0][0] == str(runtime_root / "syft")
    assert not artifact.exists()
    assert not runtime_root.exists()
    assert list(transient_root.iterdir()) == []


def test_s003_interrupted_run_removes_transient_syft(tmp_path: Path) -> None:
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    artifact = transient_root / "syft"
    artifact.write_bytes(b"owner-approved-syft")
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    runner = _CollectionRunner(interrupt_syft=True)

    def lookup(name: str) -> str | None:
        return None if name == "syft" else f"/usr/bin/{name}"

    with pytest.raises(KeyboardInterrupt):
        EstateCollector(runner, tool_lookup=lookup).collect(
            tmp_path / "private",
            transient_syft=artifact,
            syft_sha256=checksum,
            transient_root=transient_root,
        )

    syft_environment = runner.environments[0]
    assert syft_environment is not None
    assert not artifact.exists()
    assert not Path(syft_environment["HOME"]).parent.exists()
    assert list(transient_root.iterdir()) == []


def test_s003_transient_syft_checksum_mismatch_runs_nothing(tmp_path: Path) -> None:
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    artifact = transient_root / "syft"
    artifact.write_bytes(b"unexpected")
    runner = _CollectionRunner()

    with pytest.raises(S003CollectionError, match="checksum does not match"):
        EstateCollector(runner, tool_lookup=_tool_lookup).collect(
            tmp_path / "private",
            transient_syft=artifact,
            syft_sha256="0" * 64,
            transient_root=transient_root,
        )

    assert runner.commands == []
    assert not artifact.exists()


@pytest.mark.parametrize("checksum", [None, "not-a-digest"])
def test_s003_invalid_transient_digest_still_removes_artifact(
    tmp_path: Path,
    checksum: str | None,
) -> None:
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    artifact = transient_root / "syft"
    artifact.write_bytes(b"owner-approved-syft")
    runner = _CollectionRunner()

    with pytest.raises(S003CollectionError, match="syft-sha256"):
        EstateCollector(runner, tool_lookup=_tool_lookup).collect(
            tmp_path / "private",
            transient_syft=artifact,
            syft_sha256=checksum,
            transient_root=transient_root,
        )

    assert runner.commands == []
    assert not artifact.exists()


def test_s003_missing_syft_refuses_cleanly_before_commands(tmp_path: Path) -> None:
    runner = _CollectionRunner()

    def lookup(name: str) -> str | None:
        return None if name == "syft" else f"/usr/bin/{name}"

    with pytest.raises(S003CollectionError, match="required tool syft is not in PATH"):
        EstateCollector(runner, tool_lookup=lookup).collect(
            tmp_path / "private",
            transient_root=tmp_path,
        )

    assert runner.commands == []


def test_s003_missing_optional_tools_are_recorded_not_run(tmp_path: Path) -> None:
    runner = _CollectionRunner()

    def lookup(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"syft", "systemctl"} else None

    manifest = EstateCollector(runner, tool_lookup=lookup).collect(
        tmp_path / "private",
        transient_root=tmp_path,
    )
    missing = {
        entry.name: entry for entry in manifest.commands if entry.name in {"ss", "nft", "nginx"}
    }
    surface = ServiceSurfaceDocument.model_validate_json(
        (tmp_path / "private" / "service-surface.json").read_text(encoding="utf-8")
    )

    assert set(missing) == {"ss", "nft", "nginx"}
    assert all(entry.returncode == 127 for entry in missing.values())
    assert all("not in PATH" in (entry.stderr or "") for entry in missing.values())
    assert set(surface.unavailable_details) == {
        "ss",
        "nft",
        "nginx",
        "listeners",
        "vhosts",
    }
    assert all(Path(command[0]).name not in missing for command in runner.commands)


def test_s003_transient_runtime_cannot_use_repository(tmp_path: Path) -> None:
    runner = _CollectionRunner()

    with pytest.raises(S003CollectionError, match="transient root"):
        EstateCollector(runner, tool_lookup=_tool_lookup).collect(
            tmp_path / "private",
            transient_root=Path.cwd(),
        )

    assert runner.commands == []


def test_s003_missing_systemctl_removes_transient_before_refusal(tmp_path: Path) -> None:
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    artifact = transient_root / "syft"
    artifact.write_bytes(b"owner-approved-syft")
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    runner = _CollectionRunner()

    def lookup(name: str) -> str | None:
        return None if name in {"syft", "systemctl"} else f"/usr/bin/{name}"

    with pytest.raises(S003CollectionError, match="required tool systemctl"):
        EstateCollector(runner, tool_lookup=lookup).collect(
            tmp_path / "private",
            transient_syft=artifact,
            syft_sha256=checksum,
            transient_root=transient_root,
        )

    assert runner.commands == []
    assert not artifact.exists()
    assert list(transient_root.iterdir()) == []


def test_s003_runtime_setup_failure_still_removes_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    artifact = transient_root / "syft"
    artifact.write_bytes(b"owner-approved-syft")
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    runner = _CollectionRunner()

    def fail_setup(*_args: object, **_kwargs: object) -> str:
        raise OSError("temporary storage unavailable")

    monkeypatch.setattr("tools.s003_estate.tempfile.mkdtemp", fail_setup)
    with pytest.raises(S003CollectionError, match="S-003 runtime setup failed"):
        EstateCollector(runner, tool_lookup=_tool_lookup).collect(
            tmp_path / "private",
            transient_syft=artifact,
            syft_sha256=checksum,
            transient_root=transient_root,
        )

    assert runner.commands == []
    assert not artifact.exists()


def test_s003_cleanup_is_verified_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transient_root = tmp_path / "transient"
    transient_root.mkdir()
    runner = _CollectionRunner()
    real_rmtree = shutil.rmtree
    monkeypatch.setattr("tools.s003_estate.shutil.rmtree", lambda _path: None)

    with pytest.raises(S003CollectionError, match="isolated Syft runtime remains"):
        EstateCollector(runner, tool_lookup=_tool_lookup).collect(
            tmp_path / "private",
            transient_root=transient_root,
        )

    syft_environment = runner.environments[0]
    assert syft_environment is not None
    runtime_root = Path(syft_environment["HOME"]).parent
    assert runtime_root.exists()
    real_rmtree(runtime_root)


def test_s003_unit_inventory_rejects_malformed_discovery() -> None:
    with pytest.raises(S003CollectionError, match="incomplete row"):
        parse_unit_list("alpha.service loaded active")


def test_s003_discovered_unit_cannot_inject_a_command() -> None:
    with pytest.raises(S003CollectionError, match="invalid discovered"):
        unit_detail_command("alpha.service --property=Environment")


def test_s003_collection_output_is_bounded(tmp_path: Path) -> None:
    with pytest.raises(S003CollectionError, match="size bound"):
        EstateCollector(
            _CollectionRunner(),
            max_output_bytes=4,
            tool_lookup=_tool_lookup,
        ).collect(
            tmp_path / "private",
            transient_root=tmp_path,
        )
