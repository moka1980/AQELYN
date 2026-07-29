"""Pure S-004 hand-in parsing and cross-document freshness enforcement.

The owner captures these documents outside AQELYN. This module accepts their
contents and capture times as values; it performs no I/O, starts no process, and
knows no host or privilege boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
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


class ProxyRouteDeclaration(BaseModel):
    """One explicit front-end-to-upstream route inside a single server block."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frontend_ref: str
    upstream_ref: str
    server_names: tuple[str, ...] = ()
    certificate_refs: tuple[str, ...] = ()

    @field_validator("frontend_ref", "upstream_ref")
    @classmethod
    def _endpoint_ref(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("proxy route endpoint references must not be empty")
        return value

    @field_validator("server_names", "certificate_refs")
    @classmethod
    def _optional_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("proxy route references must not be empty")
        if len(values) != len(set(values)):
            raise ValueError("proxy route references must not contain duplicates")
        return values


class ProxyConfigurationCapture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capture: CaptureRef
    directives: list[ProxyDirective]
    routes: list[ProxyRouteDeclaration] = Field(default_factory=list)

    @model_validator(mode="after")
    def _kind_and_content(self) -> ProxyConfigurationCapture:
        if self.capture.kind != "proxy_configuration":
            raise ValueError("proxy configuration capture has the wrong capture kind")
        if not self.directives:
            raise ValueError("proxy configuration contains no supported directives")
        route_keys = [
            (route.frontend_ref, route.upstream_ref, route.server_names, route.certificate_refs)
            for route in self.routes
        ]
        if len(route_keys) != len(set(route_keys)):
            raise ValueError("proxy configuration routes must not contain duplicates")
        listens = {
            directive.arguments[0] for directive in self.directives if directive.kind == "listen"
        }
        upstreams = {
            directive.arguments[0]
            for directive in self.directives
            if directive.kind == "proxy_pass"
        }
        if any(
            route.frontend_ref not in listens or route.upstream_ref not in upstreams
            for route in self.routes
        ):
            raise ValueError("proxy routes must cite retained configuration directives")
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
    try:
        directives, routes = _proxy_configuration(selected)
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
        routes=routes,
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


def _proxy_configuration(
    raw: str,
) -> tuple[list[ProxyDirective], list[ProxyRouteDeclaration]]:
    directives: list[ProxyDirective] = []
    server_directives: list[list[ProxyDirective]] = []
    stack: list[tuple[str, int | None]] = []
    current: list[str] = []

    for token in _nginx_tokens(raw):
        if token == "{":
            if not current:
                raise S004HandInError(
                    "capture_document_malformed",
                    "proxy configuration contains a block without a name",
                )
            inherited_server = stack[-1][1] if stack else None
            if current[0] == "server":
                inherited_server = len(server_directives)
                server_directives.append([])
            stack.append((current[0], inherited_server))
            current.clear()
            continue
        if token == ";":
            if not current:
                continue
            directive = _supported_proxy_directive(current)
            if directive is not None:
                directives.append(directive)
                active_server = stack[-1][1] if stack else None
                if active_server is not None:
                    server_directives[active_server].append(directive)
            current.clear()
            continue
        if token == "}":
            if current or not stack:
                raise S004HandInError(
                    "capture_document_malformed",
                    "proxy configuration contains an invalid block boundary",
                )
            stack.pop()
            continue
        current.append(token)

    if current or stack:
        raise S004HandInError(
            "capture_document_malformed",
            "proxy configuration contains an unterminated directive or block",
        )

    routes: list[ProxyRouteDeclaration] = []
    seen: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()
    for selected in server_directives:
        frontends = _first_arguments(selected, "listen")
        upstreams = _first_arguments(selected, "proxy_pass")
        server_names = _first_arguments(selected, "server_name")
        certificate_refs = _first_arguments(selected, "ssl_certificate")
        for frontend_ref in frontends:
            for upstream_ref in upstreams:
                key = (frontend_ref, upstream_ref, server_names, certificate_refs)
                if key in seen:
                    continue
                seen.add(key)
                routes.append(
                    ProxyRouteDeclaration(
                        frontend_ref=frontend_ref,
                        upstream_ref=upstream_ref,
                        server_names=server_names,
                        certificate_refs=certificate_refs,
                    )
                )
    return directives, routes


def _supported_proxy_directive(tokens: Sequence[str]) -> ProxyDirective | None:
    if not tokens or tokens[0] not in _PROXY_DIRECTIVES:
        return None
    return ProxyDirective(
        kind=cast(ProxyDirectiveKind, tokens[0]),
        arguments=tuple(tokens[1:]),
    )


def _first_arguments(
    directives: Sequence[ProxyDirective],
    kind: ProxyDirectiveKind,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(directive.arguments[0] for directive in directives if directive.kind == kind)
    )


def _nginx_tokens(raw: str) -> list[str]:
    """Tokenize nginx configuration without assigning meaning to unsupported syntax."""

    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    comment = False
    variable_braces = 0

    def flush() -> None:
        if current:
            tokens.append("".join(current))
            current.clear()

    for character in raw:
        if comment:
            if character == "\n":
                comment = False
            continue
        if variable_braces:
            current.append(character)
            if character == "{":
                variable_braces += 1
            elif character == "}":
                variable_braces -= 1
            continue
        if quote is not None:
            if escaped:
                current.append(character)
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            else:
                current.append(character)
            continue
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "#":
            flush()
            comment = True
            continue
        if character in ('"', "'"):
            quote = character
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "{" and current and current[-1] == "$":
            current.append(character)
            variable_braces = 1
            continue
        if character.isspace():
            flush()
            continue
        if character in "{};":
            flush()
            tokens.append(character)
            continue
        current.append(character)

    if quote is not None or escaped or variable_braces:
        raise S004HandInError(
            "capture_document_malformed",
            "proxy configuration contains an unterminated quote or escape",
        )
    flush()
    return tokens
