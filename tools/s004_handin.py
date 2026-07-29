"""Pure S-004 hand-in parsing and cross-document freshness enforcement.

The owner captures these documents outside AQELYN. This module accepts their
contents and capture times as values; it performs no I/O, starts no process, and
knows no host or privilege boundary.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator, model_validator
from tools.s003_estate import (
    CommandTemplate,
    ListenerObservation,
    ServiceSurfaceDocument,
    UnitInventoryDocument,
    collection_command_templates,
)
from tools.s003_surface import S003SurfaceError, parse_listener_rows

CaptureKind = Literal[
    "unit_inventory",
    "service_surface",
    "privileged_socket_table",
    "proxy_configuration",
    "firewall_ruleset",
]
OwnerCaptureKind = Literal[
    "privileged_socket_table",
    "proxy_configuration",
    "firewall_ruleset",
]
ProxyDirectiveKind = Literal["listen", "server_name", "proxy_pass", "ssl_certificate"]
HandInFailureReason = Literal[
    "capture_time_missing_or_naive",
    "capture_document_malformed",
    "capture_time_skew_exceeded",
]

_PROXY_DIRECTIVES = frozenset(("listen", "server_name", "proxy_pass", "ssl_certificate"))
_OWNER_CAPTURE_COMMANDS: tuple[tuple[OwnerCaptureKind, str], ...] = (
    ("privileged_socket_table", "ss"),
    ("firewall_ruleset", "nft"),
    ("proxy_configuration", "nginx"),
)


class S004HandInError(RuntimeError):
    """A handed-in capture cannot be consumed honestly."""

    def __init__(self, reason: HandInFailureReason, detail: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class OwnerCaptureCommand:
    """One inert owner command derived from the shipped collector vocabulary."""

    kind: OwnerCaptureKind
    source: CommandTemplate
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        expected_name = dict(_OWNER_CAPTURE_COMMANDS)[self.kind]
        if self.source.name != expected_name:
            raise ValueError("owner capture kind does not match its source command")
        if (
            len(self.argv) != len(self.source.argv) + 1
            or not self.argv[0].strip()
            or self.argv[1:] != self.source.argv
        ):
            raise ValueError(
                "owner capture command must add only one privilege executable "
                "to the shipped command"
            )


class CaptureRef(BaseModel):
    """Content-and-time address for one private capture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CaptureKind
    capture_id: str
    captured_at: AwareDatetime

    @model_validator(mode="after")
    def _id_matches_kind(self) -> CaptureRef:
        prefix = f"s004:{self.kind}:sha256:"
        digest = self.capture_id.removeprefix(prefix)
        if (
            not self.capture_id.startswith(prefix)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("capture_id must be a SHA-256 reference for its capture kind")
        return self


class PrivilegedSocketCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capture: CaptureRef
    listeners: list[ListenerObservation]

    @model_validator(mode="after")
    def _kind_and_join_state(self) -> PrivilegedSocketCapture:
        if self.capture.kind != "privileged_socket_table":
            raise ValueError("privileged socket capture has the wrong capture kind")
        if any(listener.asset_key is not None for listener in self.listeners):
            raise ValueError("socket parsing cannot claim an asset before the inventory join")
        return self


class ProxyDirective(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ProxyDirectiveKind
    arguments: tuple[str, ...]

    @field_validator("arguments")
    @classmethod
    def _arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("proxy directive arguments must not be empty")
        return value


class ProxyConfigurationCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capture: CaptureRef
    directives: list[ProxyDirective]

    @model_validator(mode="after")
    def _kind_and_content(self) -> ProxyConfigurationCapture:
        if self.capture.kind != "proxy_configuration":
            raise ValueError("proxy configuration capture has the wrong capture kind")
        if not self.directives:
            raise ValueError("proxy configuration contains no supported directives")
        return self


class FirewallRulesetCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capture: CaptureRef
    entries: list[dict[str, object]]

    @model_validator(mode="after")
    def _kind(self) -> FirewallRulesetCapture:
        if self.capture.kind != "firewall_ruleset":
            raise ValueError("firewall ruleset capture has the wrong capture kind")
        return self


class CaptureJoinBasis(BaseModel):
    """Replayable proof that every input was named and within the owner policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capture_refs: list[CaptureRef]
    captured_from: AwareDatetime
    captured_through: AwareDatetime
    observed_skew: timedelta
    max_skew: timedelta

    @model_validator(mode="after")
    def _basis_is_complete_and_fresh(self) -> CaptureJoinBasis:
        if len(self.capture_refs) < 2:
            raise ValueError("capture join basis requires at least two captures")
        ids = [capture.capture_id for capture in self.capture_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("capture join basis cannot cite a capture twice")
        if self.max_skew < timedelta(0):
            raise ValueError("capture join maximum skew must be non-negative")
        captured_from = min(capture.captured_at for capture in self.capture_refs)
        captured_through = max(capture.captured_at for capture in self.capture_refs)
        if self.captured_from != captured_from or self.captured_through != captured_through:
            raise ValueError("capture join bounds contradict the cited captures")
        if self.observed_skew != captured_through - captured_from:
            raise ValueError("capture join skew contradicts the cited captures")
        if self.observed_skew > self.max_skew:
            raise ValueError("stale capture join cannot be represented as fresh")
        return self


class HandedInCaptureSet(BaseModel):
    """Inputs W4+ may consume only after W3 has accepted their freshness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory: UnitInventoryDocument
    prior_surface: ServiceSurfaceDocument
    privileged_sockets: PrivilegedSocketCapture
    proxy_configuration: ProxyConfigurationCapture
    firewall_ruleset: FirewallRulesetCapture
    basis: CaptureJoinBasis

    @model_validator(mode="after")
    def _basis_cites_every_document(self) -> HandedInCaptureSet:
        expected = {
            capture_ref_for_document(self.inventory).capture_id,
            capture_ref_for_document(self.prior_surface).capture_id,
            self.privileged_sockets.capture.capture_id,
            self.proxy_configuration.capture.capture_id,
            self.firewall_ruleset.capture.capture_id,
        }
        actual = {capture.capture_id for capture in self.basis.capture_refs}
        if actual != expected or len(self.basis.capture_refs) != len(expected):
            raise ValueError("capture set basis must cite every consumed document exactly once")
        return self


def owner_capture_command_plan(
    *,
    privilege_executable: str,
) -> tuple[OwnerCaptureCommand, ...]:
    """Describe the owner's manual captures without executing any command."""

    if not privilege_executable.strip():
        raise ValueError("owner privilege executable must not be empty")
    templates = collection_command_templates()
    plan: list[OwnerCaptureCommand] = []
    for kind, command_name in _OWNER_CAPTURE_COMMANDS:
        matches = [template for template in templates if template.name == command_name]
        if len(matches) != 1:
            raise RuntimeError(
                f"shipped command registry must contain exactly one {command_name} template"
            )
        source = matches[0]
        plan.append(
            OwnerCaptureCommand(
                kind=kind,
                source=source,
                argv=(privilege_executable, *source.argv),
            )
        )
    return tuple(plan)


def parse_privileged_socket_capture(
    raw: str,
    *,
    captured_at: datetime,
) -> PrivilegedSocketCapture:
    """Parse a handed-in privileged socket table without joining it to inventory."""

    selected = _capture_text(raw)
    try:
        listeners = parse_listener_rows(selected)
    except S003SurfaceError as exc:
        raise S004HandInError("capture_document_malformed", str(exc)) from exc
    return PrivilegedSocketCapture(
        capture=_capture_ref("privileged_socket_table", selected, captured_at),
        listeners=listeners,
    )


def parse_proxy_configuration_capture(
    raw: str,
    *,
    captured_at: datetime,
) -> ProxyConfigurationCapture:
    """Extract only the proxy directives later S-004 milestones are allowed to use."""

    selected = _capture_text(raw)
    directives: list[ProxyDirective] = []
    try:
        statements = _semicolon_statements(selected)
        for statement in statements:
            candidate = statement.rsplit("{", maxsplit=1)[-1].rsplit("}", maxsplit=1)[-1].strip()
            if not candidate:
                continue
            tokens = shlex.split(candidate, comments=False, posix=True)
            if not tokens or tokens[0] not in _PROXY_DIRECTIVES:
                continue
            directives.append(
                ProxyDirective(
                    kind=cast(ProxyDirectiveKind, tokens[0]),
                    arguments=tuple(tokens[1:]),
                )
            )
    except (ValueError, S004HandInError) as exc:
        if isinstance(exc, S004HandInError):
            raise
        raise S004HandInError(
            "capture_document_malformed", "proxy configuration is invalid"
        ) from exc
    if not directives:
        raise S004HandInError(
            "capture_document_malformed",
            "proxy configuration contains no supported directives",
        )
    return ProxyConfigurationCapture(
        capture=_capture_ref("proxy_configuration", selected, captured_at),
        directives=directives,
    )


def parse_firewall_ruleset_capture(
    raw: str,
    *,
    captured_at: datetime,
) -> FirewallRulesetCapture:
    """Parse the handed-in structured firewall ruleset."""

    selected = _capture_text(raw)
    try:
        payload = json.loads(selected)
    except json.JSONDecodeError as exc:
        raise S004HandInError(
            "capture_document_malformed",
            "firewall ruleset is not valid JSON",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"nftables"}:
        raise S004HandInError(
            "capture_document_malformed",
            "firewall ruleset must contain only the nftables root",
        )
    entries = payload["nftables"]
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise S004HandInError(
            "capture_document_malformed",
            "firewall nftables entries must be objects",
        )
    return FirewallRulesetCapture(
        capture=_capture_ref("firewall_ruleset", selected, captured_at),
        entries=cast(list[dict[str, object]], entries),
    )


def capture_ref_for_document(
    document: UnitInventoryDocument | ServiceSurfaceDocument,
) -> CaptureRef:
    """Content-address an existing U1 document without retaining another copy."""

    if isinstance(document, UnitInventoryDocument):
        kind: CaptureKind = "unit_inventory"
    elif isinstance(document, ServiceSurfaceDocument):
        kind = "service_surface"
    else:
        raise TypeError("unsupported U1 document type")
    encoded = json.dumps(
        document.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _capture_ref(kind, encoded, document.collected_at)


def prepare_handed_in_capture_set(
    inventory: UnitInventoryDocument,
    prior_surface: ServiceSurfaceDocument,
    *,
    privileged_sockets: PrivilegedSocketCapture,
    proxy_configuration: ProxyConfigurationCapture,
    firewall_ruleset: FirewallRulesetCapture,
    max_skew: timedelta,
) -> HandedInCaptureSet:
    """Refuse stale U1/W1 inputs before any attribution or topology join can run."""

    refs = [
        capture_ref_for_document(inventory),
        capture_ref_for_document(prior_surface),
        privileged_sockets.capture,
        proxy_configuration.capture,
        firewall_ruleset.capture,
    ]
    basis = require_fresh_capture_join(refs, max_skew=max_skew)
    return HandedInCaptureSet(
        inventory=inventory,
        prior_surface=prior_surface,
        privileged_sockets=privileged_sockets,
        proxy_configuration=proxy_configuration,
        firewall_ruleset=firewall_ruleset,
        basis=basis,
    )


def require_fresh_capture_join(
    capture_refs: Sequence[CaptureRef],
    *,
    max_skew: timedelta,
) -> CaptureJoinBasis:
    """Return a replayable basis or refuse with the named stale-join reason."""

    if len(capture_refs) < 2:
        raise S004HandInError(
            "capture_document_malformed",
            "cross-document freshness requires at least two captures",
        )
    if max_skew < timedelta(0):
        raise S004HandInError(
            "capture_document_malformed",
            "capture freshness tolerance must be non-negative",
        )
    captured_from = min(capture.captured_at for capture in capture_refs)
    captured_through = max(capture.captured_at for capture in capture_refs)
    observed_skew = captured_through - captured_from
    if observed_skew > max_skew:
        raise S004HandInError(
            "capture_time_skew_exceeded",
            "stale cross-document join exceeds the owner-selected freshness tolerance",
        )
    return CaptureJoinBasis(
        capture_refs=list(capture_refs),
        captured_from=captured_from,
        captured_through=captured_through,
        observed_skew=observed_skew,
        max_skew=max_skew,
    )


def _capture_ref(kind: CaptureKind, raw: str, captured_at: datetime) -> CaptureRef:
    timestamp = _capture_time(captured_at)
    digest = hashlib.sha256(
        f"{kind}\0{timestamp.isoformat()}\0{raw}".encode(),
    ).hexdigest()
    return CaptureRef(
        kind=kind,
        capture_id=f"s004:{kind}:sha256:{digest}",
        captured_at=timestamp,
    )


def _capture_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise S004HandInError(
            "capture_time_missing_or_naive",
            "capture time must include a timezone",
        )
    return value.astimezone(UTC)


def _capture_text(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip() or "\0" in raw:
        raise S004HandInError(
            "capture_document_malformed",
            "capture text must be non-empty and contain no NUL bytes",
        )
    return raw


def _semicolon_statements(raw: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    comment = False
    for character in raw:
        if comment:
            if character == "\n":
                comment = False
                current.append(character)
            continue
        if quote is not None:
            current.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character == "#":
            comment = True
            continue
        if character in ('"', "'"):
            quote = character
            current.append(character)
            continue
        if character == ";":
            statements.append("".join(current))
            current.clear()
            continue
        current.append(character)
    if quote is not None:
        raise S004HandInError(
            "capture_document_malformed",
            "proxy configuration contains an unterminated quote",
        )
    return statements
