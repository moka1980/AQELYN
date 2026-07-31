"""GC-004 persisted-field census and inspectable classification.

The guard reports a census, not a clearance. It can discover writes and source-level
readers, but it cannot prove that a shipped path can produce the state a reader needs.
Dormancy is therefore declared and review-owned; undeclared dormancy remains a named
limit of this module.

The population is write-defined. SQL INSERT/UPDATE columns describe Postgres writes,
while field-level store operations describe in-memory writes. A DDL column describes
capacity and is deliberately not enough to enter the census.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from guarantees.discovery import (
    GuaranteeViolation,
    aqelyn_source_root,
    source_python_files,
)

Backend = Literal["memory", "postgres"]
FieldState = Literal["consumed", "dormant", "exempt", "unconsumed"]


DORMANT_FIELDS = {
    "findings.current_severity_score": (
        "The only divergence point is re-emission in findings/memory.py, while the "
        "shipped reporting path constructs a fresh store for each run."
    )
}

_EXEMPTION_GROUPS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "assetconfig",
        (
            "coverage_by_object_type",
            "coverage_complete",
            "coverage_incomplete_reason",
            "objects_assessed",
            "objects_in_scope",
            "unassessed_object_ids",
        ),
        "EA-0012 keeps baseline coverage accounting inside its owner for audit and replay; "
        "the shipped cross-package contract exposes the resulting drift, not these fields.",
    ),
    (
        "cspm",
        ("unreported_facts",),
        "EA-0028 keeps unreported normalization facts inside its owner and exposes derived "
        "posture records across package boundaries.",
    ),
    (
        "decision",
        ("action_hint", "tenant_key"),
        "EA-0021 persists model-selection bookkeeping inside its owner; callers consume the "
        "validated recommendation contract.",
    ),
    (
        "detection",
        ("insufficient_data", "subject_type", "technique_ids"),
        "EA-0006 keeps profile and rule bookkeeping inside its owner; external consumers use "
        "the resulting detections.",
    ),
    (
        "dspm",
        ("classification_status", "store_id", "store_type", "tenant_key"),
        "EA-0031 keeps normalized store identity and classification bookkeeping inside its "
        "owner; external consumers use posture and exposure outputs.",
    ),
    (
        "evidence",
        ("anchor", "manifest_hash", "package_hash"),
        "EA-0002 keeps integrity-chain material inside the evidence owner; callers consume "
        "verification outcomes rather than recomputing these fields.",
    ),
    (
        "executive",
        (
            "approval_status",
            "combinator",
            "exceptions",
            "issued_by",
            "kpi_key",
            "period",
            "sections",
            "unit",
        ),
        "EA-0022 keeps report-definition and issuance bookkeeping inside its owner; external "
        "consumers receive the assembled report.",
    ),
    (
        "exposure",
        ("validated_at",),
        "EA-0023 retains validation provenance inside its owner; consumers use the scored "
        "exposure record.",
    ),
    (
        "findings",
        ("resolved_at",),
        "EA-0003 owns lifecycle timestamps; cross-package consumers use the finding status "
        "and store APIs rather than this persistence field directly.",
    ),
    (
        "forecast",
        ("resolves_at", "tenant_key"),
        "EA-0020 keeps forecast resolution and model-key bookkeeping inside its owner; "
        "callers consume validated forecasts.",
    ),
    (
        "forensics",
        ("acquisition_id", "artifact_type", "linked_asset_ids"),
        "EA-0015 keeps artifact acquisition and linkage bookkeeping inside its owner; callers "
        "consume validated artifact records.",
    ),
    (
        "governance",
        ("framework_scores",),
        "EA-0010 retains framework component scores inside its owner; external consumers use "
        "the composed compliance snapshot.",
    ),
    (
        "idthreat",
        (
            "corroboration",
            "detection_type",
            "entitlement_refs",
            "profile_ref",
            "reviewed_by",
        ),
        "EA-0027 keeps detection corroboration and review bookkeeping inside its owner; "
        "external consumers use findings and review outcomes.",
    ),
    (
        "inventory",
        ("discovery_source", "unreported_since"),
        "EA-0025 owns discovery and reconciliation bookkeeping; consumers use reconciled "
        "assets and ownership results.",
    ),
    (
        "lake",
        (
            "archived_at",
            "classifications",
            "dataset",
            "indexed_fields",
            "ingested_at",
            "legal_hold",
            "raw_ref",
            "record_count",
            "retention_policy_id",
            "retention_state",
            "schema",
        ),
        "EA-0019 keeps dataset, retention, and archive bookkeeping inside the lake owner; "
        "external consumers use query and retention operations.",
    ),
    (
        "objects",
        ("changed_by", "merged_into"),
        "EA-0005 owns object history and merge bookkeeping; consumers use current objects and "
        "relationships.",
    ),
    (
        "policy",
        ("standard",),
        "EA-0009 keeps policy-standard metadata inside its owner; callers consume authorization "
        "decisions.",
    ),
    (
        "response",
        ("max_effect",),
        "EA-0018 owns bounded-effect campaign metadata; callers consume gated campaign and "
        "workflow outcomes.",
    ),
    (
        "risk",
        (
            "band_counts",
            "overall_exposure",
            "top_risks",
            "treated_by",
            "treatment",
            "treatment_note",
        ),
        "EA-0013 keeps snapshot composition and treatment bookkeeping inside its owner; "
        "external consumers use scored risk records and findings.",
    ),
    (
        "soc",
        ("alert_ids", "assignee", "timeline"),
        "EA-0017 owns incident assembly and assignment bookkeeping; callers consume SOC alerts "
        "and incidents through its service boundary.",
    ),
    (
        "sspm",
        (
            "grantor_kind",
            "grantor_ref",
            "integration_id",
            "known_surface_ref",
            "over_scoped",
            "provider_tenant",
            "reach_status",
            "reachable_object_ids",
            "scopes",
            "third_party_app",
            "third_party_external",
        ),
        "EA-0029 keeps SaaS normalization and reachability bookkeeping inside its owner; "
        "external consumers use posture and exposure outputs.",
    ),
    (
        "supplychain",
        (
            "assessment_status",
            "component_type",
            "components",
            "doc_id",
            "licenses",
            "locations",
            "provenance_status",
            "supplier",
            "transitive",
            "unverified_provenance",
            "vulnerable_components",
        ),
        "EA-0030 keeps SBOM document and component provenance inside its owner; external "
        "consumers use vulnerability prioritization and findings.",
    ),
    (
        "threat",
        ("meta",),
        "EA-0016 keeps source metadata inside its owner; consumers use normalized threat "
        "signals and factor-provider outputs.",
    ),
    (
        "vuln",
        ("cvss", "disposition", "epss"),
        "EA-0024 keeps raw prioritization inputs and disposition inside its owner; external "
        "consumers use the resulting priority and coverage.",
    ),
    (
        "workflow",
        ("approvals",),
        "EA-0008 owns approval history and evaluates it internally before any action; external "
        "consumers use workflow state and outcomes.",
    ),
)

EXEMPT_FIELDS = {
    f"{owner}.{field}": reason for owner, fields, reason in _EXEMPTION_GROUPS for field in fields
}


@dataclass(frozen=True, order=True)
class WriteSite:
    backend: Backend
    path: Path
    line: int


@dataclass(frozen=True)
class PersistedField:
    owner: str
    name: str
    backends: frozenset[Backend]
    sites: tuple[WriteSite, ...]

    @property
    def key(self) -> str:
        return f"{self.owner}.{self.name}"


@dataclass(frozen=True)
class FieldClassification:
    field: PersistedField
    state: FieldState
    readers: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True)
class _SourceModule:
    name: str
    package: str
    path: Path
    tree: ast.Module


_INSERT_RE = re.compile(
    r"\bINSERT\s+INTO\s+[^\s(]+\s*\((.*?)\)\s*VALUES\b",
    re.IGNORECASE | re.DOTALL,
)
_UPDATE_RE = re.compile(
    r"(?:\bUPDATE\s+[^\s]+\s+SET|\bDO\s+UPDATE\s+SET)\s+(.*?)"
    r"(?=\bWHERE\b|\bRETURNING\b|\bON\s+CONFLICT\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_SQL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def discover_persisted_fields(aqelyn_root: Path | None = None) -> tuple[PersistedField, ...]:
    root = aqelyn_root or aqelyn_source_root()
    modules = _source_modules(root)
    writes: dict[tuple[str, str], set[WriteSite]] = defaultdict(set)

    for module in modules.values():
        if module.path.name == "postgres.py":
            for name, line in _postgres_written_fields(module):
                writes[(module.package, name)].add(WriteSite("postgres", module.path, line))
        for name, line in _memory_written_fields(module):
            writes[(module.package, name)].add(WriteSite("memory", module.path, line))

    return tuple(
        PersistedField(
            owner=owner,
            name=name,
            backends=frozenset(site.backend for site in sites),
            sites=tuple(sorted(sites)),
        )
        for (owner, name), sites in sorted(writes.items())
    )


def classify_persisted_fields(
    aqelyn_root: Path | None = None,
    *,
    dormant_fields: Mapping[str, str] = DORMANT_FIELDS,
    exempt_fields: Mapping[str, str] = EXEMPT_FIELDS,
) -> dict[str, FieldClassification]:
    root = aqelyn_root or aqelyn_source_root()
    population = discover_persisted_fields(root)
    _validate_registries(population, dormant_fields=dormant_fields, exempt_fields=exempt_fields)
    reads = _external_readers(root)
    classified: dict[str, FieldClassification] = {}

    for field in population:
        readers = tuple(sorted(reads.get(field.name, set()) - {field.owner}))
        if field.key in dormant_fields:
            if not readers:
                raise GuaranteeViolation(
                    f"dormant field has no discovered external reader: {field.key}"
                )
            state: FieldState = "dormant"
            reason = dormant_fields[field.key]
        elif field.key in exempt_fields:
            if readers:
                raise GuaranteeViolation(
                    f"exempt field has discovered external readers: {field.key} -> {readers}"
                )
            state = "exempt"
            reason = exempt_fields[field.key]
        elif readers:
            state = "consumed"
            reason = None
        else:
            state = "unconsumed"
            reason = None
        classified[field.key] = FieldClassification(field, state, readers, reason)
    return classified


def assert_persisted_fields_consumed(
    aqelyn_root: Path | None = None,
    *,
    dormant_fields: Mapping[str, str] = DORMANT_FIELDS,
    exempt_fields: Mapping[str, str] = EXEMPT_FIELDS,
) -> dict[str, FieldClassification]:
    classified = classify_persisted_fields(
        aqelyn_root,
        dormant_fields=dormant_fields,
        exempt_fields=exempt_fields,
    )
    missing = sorted(key for key, value in classified.items() if value.state == "unconsumed")
    if missing:
        raise GuaranteeViolation(f"persisted fields have no external consumer: {missing}")
    return classified


def _validate_registries(
    population: Sequence[PersistedField],
    *,
    dormant_fields: Mapping[str, str],
    exempt_fields: Mapping[str, str],
) -> None:
    blank = sorted(
        key
        for registry in (dormant_fields, exempt_fields)
        for key, reason in registry.items()
        if not reason.strip()
    )
    if blank:
        raise GuaranteeViolation(f"persisted-field registry entries require reasons: {blank}")
    overlap = sorted(frozenset(dormant_fields) & frozenset(exempt_fields))
    if overlap:
        raise GuaranteeViolation(f"persisted fields cannot be dormant and exempt: {overlap}")
    population_keys = frozenset(field.key for field in population)
    stale = sorted((frozenset(dormant_fields) | frozenset(exempt_fields)) - population_keys)
    if stale:
        raise GuaranteeViolation(f"persisted-field registry contains unknown entries: {stale}")


def _source_modules(root: Path) -> dict[str, _SourceModule]:
    modules: dict[str, _SourceModule] = {}
    for path in source_python_files(root):
        relative = path.relative_to(root).with_suffix("")
        parts = relative.parts
        module_name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        tree = _parse(path)
        modules[module_name] = _SourceModule(
            name=module_name,
            package=parts[0],
            path=path,
            tree=tree,
        )
    return modules


def _memory_written_fields(module: _SourceModule) -> tuple[tuple[str, int], ...]:
    written: set[tuple[str, int]] = set()
    for node in module.tree.body:
        if not (
            isinstance(node, ast.ClassDef)
            and node.name.startswith("InMemory")
            and node.name.endswith(("Store", "Registry"))
        ):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for selected in ast.walk(item):
                if isinstance(selected, ast.Assign):
                    for target in selected.targets:
                        _record_memory_target(target, selected.value, selected.lineno, written)
                elif isinstance(selected, ast.AnnAssign) and selected.value is not None:
                    _record_memory_target(
                        selected.target,
                        selected.value,
                        selected.lineno,
                        written,
                    )
                elif isinstance(selected, ast.AugAssign):
                    _record_memory_attribute(selected.target, selected.lineno, written)
                elif isinstance(selected, ast.Call):
                    _record_memory_call(selected, written)
    return tuple(sorted(written))


def _record_memory_target(
    target: ast.expr,
    value: ast.expr,
    line: int,
    written: set[tuple[str, int]],
) -> None:
    _record_memory_attribute(target, line, written)
    if isinstance(target, ast.Subscript) and _is_self_storage(target.value):
        for key in _dict_keys(value):
            written.add((key, line))


def _record_memory_attribute(
    target: ast.expr,
    line: int,
    written: set[tuple[str, int]],
) -> None:
    if (
        isinstance(target, ast.Attribute)
        and not (isinstance(target.value, ast.Name) and target.value.id == "self")
        and not target.attr.startswith("_")
    ):
        written.add((target.attr, line))


def _record_memory_call(
    node: ast.Call,
    written: set[tuple[str, int]],
) -> None:
    if isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "extend", "insert"}:
        _record_memory_attribute(node.func.value, node.lineno, written)
    if isinstance(node.func, ast.Attribute) and node.func.attr == "model_copy":
        for keyword in node.keywords:
            if keyword.arg == "update":
                for key in _dict_keys(keyword.value):
                    written.add((key, node.lineno))
    if isinstance(node.func, ast.Name) and node.func.id == "replace":
        written.update(
            (keyword.arg, node.lineno) for keyword in node.keywords if keyword.arg is not None
        )


def _dict_keys(node: ast.expr) -> tuple[str, ...]:
    if not isinstance(node, ast.Dict):
        return ()
    return tuple(
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    )


def _is_self_storage(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr.startswith("_")
    )


def _postgres_written_fields(module: _SourceModule) -> tuple[tuple[str, int], ...]:
    values = _module_static_values(module.tree)
    written: set[tuple[str, int]] = set()
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Constant | ast.JoinedStr | ast.BinOp | ast.Call | ast.Name):
            continue
        rendered = _static_value(node, values)
        if not isinstance(rendered, str):
            continue
        upper = rendered.upper()
        if "INSERT" not in upper and "UPDATE" not in upper:
            continue
        for match in _INSERT_RE.finditer(rendered):
            for column in _split_sql_items(match.group(1)):
                selected = _sql_name(column)
                if selected is not None:
                    written.add((selected, node.lineno))
        for match in _UPDATE_RE.finditer(rendered):
            for assignment in _split_sql_items(match.group(1)):
                selected = _sql_name(assignment.split("=", 1)[0])
                if selected is not None:
                    written.add((selected, node.lineno))
    return tuple(sorted(written))


def _external_readers(root: Path) -> dict[str, set[str]]:
    readers: dict[str, set[str]] = defaultdict(set)
    for path in source_python_files(root):
        package = path.relative_to(root).parts[0]
        tree = _parse(path)
        for node in ast.walk(tree):
            identifier = _source_identifier(node)
            if identifier is not None:
                readers[identifier].add(package)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                key = _string_constant(node.slice)
                if key is not None:
                    readers[key].add(package)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _SQL_NAME_RE.fullmatch(node.value):
                    readers[node.value].add(package)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
            ):
                key = _string_constant(node.args[1])
                if key is not None:
                    readers[key].add(package)
    return readers


def _module_static_values(tree: ast.Module) -> dict[str, object]:
    assignments: list[tuple[str, ast.expr]] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            assignments.append((node.targets[0].id, node.value))
    values: dict[str, object] = {}
    for _ in range(len(assignments) + 1):
        changed = False
        for name, expression in assignments:
            value = _static_value(expression, values)
            if value is not None and values.get(name) != value:
                values[name] = value
                changed = True
        if not changed:
            break
    return values


def _static_value(node: ast.expr, values: Mapping[str, object]) -> object | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str | int | float | bool):
        return node.value
    if isinstance(node, ast.Name):
        return values.get(node.id)
    if isinstance(node, ast.Tuple | ast.List):
        items = tuple(_static_value(item, values) for item in node.elts)
        return items if all(item is not None for item in items) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_value(node.left, values)
        right = _static_value(node.right, values)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                value = _static_value(part.value, values)
                parts.append(value if isinstance(value, str) else f"{{{ast.unparse(part.value)}}}")
            else:
                return None
        return "".join(parts)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
    ):
        separator = _static_value(node.func.value, values)
        joined_items = _static_value(node.args[0], values)
        if (
            isinstance(separator, str)
            and isinstance(joined_items, tuple)
            and all(isinstance(item, str) for item in joined_items)
        ):
            return separator.join(item for item in joined_items if isinstance(item, str))
    return None


def _split_sql_items(value: str) -> tuple[str, ...]:
    items: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            items.append(value[start:index].strip())
            start = index + 1
    items.append(value[start:].strip())
    return tuple(item for item in items if item)


def _sql_name(value: str) -> str | None:
    selected = value.strip().strip('"').split(".")[-1]
    return selected if _SQL_NAME_RE.fullmatch(selected) else None


def _string_constant(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _source_identifier(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.arg):
        return node.arg
    if isinstance(node, ast.keyword):
        return node.arg
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _parse(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise GuaranteeViolation(f"cannot classify source file {path}: {exc}") from exc
