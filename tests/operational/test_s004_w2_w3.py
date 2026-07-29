from __future__ import annotations

import ast
import builtins
import ipaddress
import os
import socket
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from tools.s003_estate import (
    SURFACE_NOT_DERIVED_REASONS,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
    UnitRecord,
    canonical_asset_key,
    collection_command_templates,
)
from tools.s004_handin import (
    FirewallRulesetCapture,
    HandedInCaptureSet,
    PrivilegedSocketCapture,
    ProxyConfigurationCapture,
    S004HandInError,
    capture_ref_for_document,
    parse_firewall_ruleset_capture,
    parse_privileged_socket_capture,
    parse_proxy_configuration_capture,
    prepare_handed_in_capture_set,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 29, tzinfo=UTC)


def _inventory(captured_at: datetime) -> UnitInventoryDocument:
    native_id = f"unit-{1:03d}.service"
    return UnitInventoryDocument(
        collected_at=captured_at,
        units=[
            UnitRecord(
                asset_key=canonical_asset_key("systemd_unit", native_id),
                native_id=native_id,
                display_name=f"Unit {1:03d}",
                load_state="loaded",
                active_state="active",
                sub_state="running",
                main_pid=101,
            )
        ],
    )


def _prior_surface(captured_at: datetime) -> ServiceSurfaceDocument:
    return ServiceSurfaceDocument(
        collected_at=captured_at,
        listeners_raw=_socket_table(pid=None),
        firewall_raw={"nftables": []},
        nginx_config="events {}",
        unavailable_details=dict(SURFACE_NOT_DERIVED_REASONS),
    )


def _socket_table(*, pid: int | None) -> str:
    process = "" if pid is None else " " + "users:" + "((" + f'"process",pid={pid},fd=1' + "))"
    address = str(ipaddress.ip_address(0))
    port = 10_000 * 2
    return f"tcp LISTEN 0 128 {address}:{port} *:*{process}\n"


def _w1_captures(
    captured_at: datetime,
) -> tuple[PrivilegedSocketCapture, ProxyConfigurationCapture, FirewallRulesetCapture]:
    return (
        parse_privileged_socket_capture(_socket_table(pid=101), captured_at=captured_at),
        parse_proxy_configuration_capture(
            """
            server {
                listen endpoint-reference;
                server_name host-reference;
                proxy_pass upstream-reference;
                ssl_certificate certificate-reference;
            }
            """,
            captured_at=captured_at,
        ),
        parse_firewall_ruleset_capture('{"nftables":[]}', captured_at=captured_at),
    )


def _capture_set(
    u1_at: datetime,
    w1_at: datetime,
    *,
    max_skew: timedelta,
) -> HandedInCaptureSet:
    sockets, proxy, firewall = _w1_captures(w1_at)
    return prepare_handed_in_capture_set(
        _inventory(u1_at),
        _prior_surface(u1_at),
        privileged_sockets=sockets,
        proxy_configuration=proxy,
        firewall_ruleset=firewall,
        max_skew=max_skew,
    )


def test_s004_no_privileged_path_in_src() -> None:
    src = ROOT / "src" / "aqelyn"
    references = [
        path for path in src.rglob("*.py") if "s004_handin" in path.read_text(encoding="utf-8")
    ]
    assert references == []

    module = ROOT / "tools" / "s004_handin.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert imported_roots.isdisjoint(
        {"asyncio", "http", "pathlib", "requests", "socket", "subprocess", "urllib"}
    )

    templates = collection_command_templates()
    assert {template.name for template in templates} == {
        "syft",
        "systemctl",
        "ss",
        "nft",
        "nginx",
    }
    assert all("sudo" not in template.argv for template in templates)


def test_s004_parsers_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("pure hand-in parser attempted external I/O")

    monkeypatch.setattr(builtins, "open", refused)
    monkeypatch.setattr(socket, "socket", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(subprocess, "run", refused)
    monkeypatch.setattr(subprocess, "Popen", refused)

    sockets, proxy, firewall = _w1_captures(NOW)

    assert len(sockets.listeners) == 1
    assert sockets.listeners[0].asset_key is None
    assert {directive.kind for directive in proxy.directives} == {
        "listen",
        "server_name",
        "proxy_pass",
        "ssl_certificate",
    }
    assert firewall.entries == []


def test_s004_derivation_cites_capture() -> None:
    capture_set = _capture_set(
        NOW,
        NOW + timedelta(seconds=5),
        max_skew=timedelta(seconds=10),
    )
    expected = {
        capture_ref_for_document(capture_set.inventory).capture_id,
        capture_ref_for_document(capture_set.prior_surface).capture_id,
        capture_set.privileged_sockets.capture.capture_id,
        capture_set.proxy_configuration.capture.capture_id,
        capture_set.firewall_ruleset.capture.capture_id,
    }
    assert {capture.capture_id for capture in capture_set.basis.capture_refs} == expected
    assert len(capture_set.basis.capture_refs) == len(expected)

    incomplete = capture_set.model_dump(mode="python")
    incomplete["basis"]["capture_refs"] = incomplete["basis"]["capture_refs"][:-1]
    with pytest.raises(ValidationError, match="cite every consumed document"):
        HandedInCaptureSet.model_validate(incomplete)


def test_s004_stale_join_refuses() -> None:
    with pytest.raises(S004HandInError) as stale:
        _capture_set(
            NOW,
            NOW + timedelta(days=2),
            max_skew=timedelta(minutes=1),
        )

    assert stale.value.reason == "capture_time_skew_exceeded"


def test_s004_join_reason_names_the_staleness() -> None:
    with pytest.raises(
        S004HandInError,
        match="capture_time_skew_exceeded: stale cross-document join",
    ):
        _capture_set(
            NOW,
            NOW + timedelta(hours=1),
            max_skew=timedelta(seconds=30),
        )


def test_s004_capture_time_and_content_are_pinned() -> None:
    first = parse_firewall_ruleset_capture('{"nftables":[]}', captured_at=NOW)
    later = parse_firewall_ruleset_capture(
        '{"nftables":[]}',
        captured_at=NOW + timedelta(seconds=1),
    )
    changed = parse_firewall_ruleset_capture(
        '{"nftables":[{"metainfo":{}}]}',
        captured_at=NOW,
    )

    assert (
        len({first.capture.capture_id, later.capture.capture_id, changed.capture.capture_id}) == 3
    )
    with pytest.raises(S004HandInError) as naive:
        parse_firewall_ruleset_capture(
            '{"nftables":[]}',
            captured_at=datetime(2026, 7, 29),
        )
    assert naive.value.reason == "capture_time_missing_or_naive"


@pytest.mark.parametrize(
    ("parser", "raw"),
    [
        (parse_privileged_socket_capture, "not a socket table"),
        (parse_proxy_configuration_capture, "events {}"),
        (parse_firewall_ruleset_capture, '{"not_nftables":[]}'),
    ],
)
def test_s004_malformed_capture_refuses(
    parser: Callable[..., object],
    raw: str,
) -> None:
    with pytest.raises(S004HandInError) as malformed:
        parser(raw, captured_at=NOW)
    assert malformed.value.reason == "capture_document_malformed"


def test_s004_guards_hold_under_optimized_python() -> None:
    script = """
import ipaddress
from datetime import UTC, datetime, timedelta
from tools.s003_estate import (
    SURFACE_NOT_DERIVED_REASONS,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
)
from tools.s004_handin import (
    S004HandInError,
    parse_firewall_ruleset_capture,
    parse_privileged_socket_capture,
    parse_proxy_configuration_capture,
    prepare_handed_in_capture_set,
)

old = datetime(2026, 7, 27, tzinfo=UTC)
new = datetime(2026, 7, 29, tzinfo=UTC)
inventory = UnitInventoryDocument(collected_at=old, units=[])
surface = ServiceSurfaceDocument(
    collected_at=old,
    listeners_raw="",
    firewall_raw={"nftables": []},
    nginx_config="events {}",
    unavailable_details=dict(SURFACE_NOT_DERIVED_REASONS),
)
sockets = parse_privileged_socket_capture(
    (
        "tcp LISTEN 0 128 "
        f"{ipaddress.ip_address(0)}:{10_000 * 2} *:* "
        + "users:"
        + "(("
        + '"process",pid=101,fd=1'
        + "))"
    ),
    captured_at=new,
)
proxy = parse_proxy_configuration_capture(
    "server { listen endpoint-reference; proxy_pass upstream-reference; }",
    captured_at=new,
)
firewall = parse_firewall_ruleset_capture('{"nftables":[]}', captured_at=new)
try:
    prepare_handed_in_capture_set(
        inventory,
        surface,
        privileged_sockets=sockets,
        proxy_configuration=proxy,
        firewall_ruleset=firewall,
        max_skew=timedelta(minutes=1),
    )
except S004HandInError as exc:
    if exc.reason != "capture_time_skew_exceeded":
        raise SystemExit(f"wrong refusal: {exc.reason}")
else:
    raise SystemExit("stale cross-document join was accepted")
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
