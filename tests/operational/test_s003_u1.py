from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError
from tools.s003_estate import (
    COMMAND_TEMPLATES,
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
    ensure_private_workdir,
    parse_unit_list,
    unit_detail_command,
    validate_read_only_command,
)


class _CollectionRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> CommandResult:
        assert timeout_seconds > 0
        assert max_output_bytes > 0
        selected = tuple(argv)
        self.commands.append(selected)
        if selected == COMMAND_TEMPLATES[0].argv:
            return _ok(b'{"bomFormat":"CycloneDX","components":[]}')
        if selected == COMMAND_TEMPLATES[1].argv:
            return _ok(
                b"alpha.service loaded active running Alpha service\n"
                b"beta.service loaded active running Beta service\n"
            )
        if selected == COMMAND_TEMPLATES[2].argv:
            return _ok(b'tcp LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:* users:(("alpha",pid=41))\n')
        if selected == COMMAND_TEMPLATES[3].argv:
            return _ok(b'{"nftables":[]}')
        if selected == COMMAND_TEMPLATES[4].argv:
            return CommandResult(
                returncode=0,
                stdout=b"",
                stderr=b"server { listen 443 ssl; }\n",
            )
        if selected == unit_detail_command("alpha.service").argv:
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
        if selected == unit_detail_command("beta.service").argv:
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


def test_s003_no_host_reference_in_src() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    references = [
        path for path in src.rglob("*.py") if "s003_estate" in path.read_text(encoding="utf-8")
    ]
    assert references == []


def test_s003_collection_commands_enumerated() -> None:
    templates = collection_command_templates()
    assert {item.name for item in templates} == {"syft", "systemctl", "ss", "nft", "nginx"}
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
    manifest = EstateCollector(runner).collect(tmp_path / "private")

    assert manifest.documents == ["sbom.json", "unit-inventory.json", "service-surface.json"]
    assert len(manifest.commands) == len(COMMAND_TEMPLATES) + 2
    assert runner.commands == [
        *(template.argv for template in COMMAND_TEMPLATES),
        unit_detail_command("alpha.service").argv,
        unit_detail_command("beta.service").argv,
    ]

    stored_manifest = CollectionManifest.model_validate_json(
        (tmp_path / "private" / "collection-manifest.json").read_text(encoding="utf-8")
    )
    units = UnitInventoryDocument.model_validate_json(
        (tmp_path / "private" / "unit-inventory.json").read_text(encoding="utf-8")
    )
    surface = ServiceSurfaceDocument.model_validate_json(
        (tmp_path / "private" / "service-surface.json").read_text(encoding="utf-8")
    )
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
    assert sbom["bomFormat"] == "CycloneDX"


def test_s003_unit_inventory_rejects_malformed_discovery() -> None:
    with pytest.raises(S003CollectionError, match="incomplete row"):
        parse_unit_list("alpha.service loaded active")


def test_s003_discovered_unit_cannot_inject_a_command() -> None:
    with pytest.raises(S003CollectionError, match="invalid discovered"):
        unit_detail_command("alpha.service --property=Environment")


def test_s003_collection_output_is_bounded(tmp_path: Path) -> None:
    with pytest.raises(S003CollectionError, match="size bound"):
        EstateCollector(_CollectionRunner(), max_output_bytes=4).collect(tmp_path / "private")
