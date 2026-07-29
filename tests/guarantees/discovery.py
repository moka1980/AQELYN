"""Discovery and explicit-failure helpers for GC-001."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from types import ModuleType
from typing import Literal

from pydantic import BaseModel, ValidationError

from aqelyn.conventions.errors import AQError
from aqelyn.workflow import InMemoryActionRegistry

EXECUTION_SCAN_EXCLUSIONS = {
    "workflow": (
        "EA-0008 is the canonical execution owner; its handler dispatch is the "
        "behavior every other package must route through."
    )
}


class GuaranteeViolation(AssertionError):
    """A central guarantee is not enforced by the discovered surface."""


@dataclass(frozen=True)
class SourcePackage:
    name: str
    path: Path


@dataclass(frozen=True)
class DirectInvocation:
    path: Path
    line: int
    expression: str


ScoreOrientation = Literal["higher_is_favourable", "lower_is_favourable"]
_VULNERABILITY_FACTOR_METHODS = frozenset(
    ("exploitation_factor", "reachability_factor", "blocking_factor", "scanner_trust")
)


@dataclass(frozen=True)
class ScorerObservation:
    name: str
    known_good: float
    unknown: float
    orientation: ScoreOrientation


def aqelyn_source_root() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "aqelyn"


def discover_packages(aqelyn_root: Path | None = None) -> tuple[SourcePackage, ...]:
    root = aqelyn_root or aqelyn_source_root()
    if not root.is_dir():
        raise GuaranteeViolation(f"AQELYN source root does not exist: {root}")
    packages = tuple(
        SourcePackage(path.name, path)
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.is_dir() and (path / "__init__.py").is_file()
    )
    if not packages:
        raise GuaranteeViolation(f"no AQELYN packages discovered under {root}")
    return packages


def source_python_files(aqelyn_root: Path | None = None) -> tuple[Path, ...]:
    files: list[Path] = []
    for package in discover_packages(aqelyn_root):
        files.extend(sorted(package.path.rglob("*.py")))
    return tuple(files)


def find_direct_handler_invocations(paths: Iterable[Path]) -> tuple[DirectInvocation, ...]:
    violations: list[DirectInvocation] = []
    for path in sorted(paths):
        tree = _parse(path)
        handler_names = _assigned_handler_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"execute", "rollback"}:
                continue
            receiver = node.func.value
            if not (
                _is_registry_get(receiver)
                or _receiver_is_handler(receiver, handler_names=handler_names)
            ):
                continue
            violations.append(
                DirectInvocation(
                    path=path,
                    line=node.lineno,
                    expression=ast.unparse(node.func),
                )
            )
    return tuple(violations)


def assert_no_direct_handler_invocations(aqelyn_root: Path | None = None) -> None:
    root = aqelyn_root or aqelyn_source_root()
    paths = [
        path
        for path in source_python_files(root)
        if path.relative_to(root).parts[0] not in EXECUTION_SCAN_EXCLUSIONS
    ]
    _raise_for_direct_invocations(find_direct_handler_invocations(paths))


def assert_no_direct_handler_invocations_in(paths: Iterable[Path]) -> None:
    _raise_for_direct_invocations(find_direct_handler_invocations(paths))


def assert_runtime_action_authority(
    runtime: object,
    *,
    additional_roots: Sequence[object] = (),
) -> None:
    workflow_registry = getattr(runtime, "workflow_action_registry", None)
    workflow_engine = getattr(runtime, "workflow_engine", None)
    if not isinstance(workflow_registry, InMemoryActionRegistry):
        raise GuaranteeViolation("constructed runtime has no canonical workflow ActionRegistry")
    if getattr(workflow_engine, "_registry", None) is not workflow_registry:
        raise GuaranteeViolation("WorkflowEngine is not wired to the canonical ActionRegistry")

    found = _action_registries((runtime, *additional_roots))
    alternate = [(path, registry) for path, registry in found if registry is not workflow_registry]
    if alternate:
        locations = ", ".join(path for path, _ in alternate)
        raise GuaranteeViolation(
            f"alternate ActionRegistry discovered outside EA-0008: {locations}"
        )


def assert_runtime_rejects_kind(
    model_type: type[BaseModel],
    payload: Mapping[str, object],
) -> None:
    try:
        model_type.model_validate(dict(payload))
    except (ValidationError, AQError):
        return
    raise GuaranteeViolation(
        f"{model_type.__module__}.{model_type.__name__} accepted an unregistered signal kind"
    )


def discover_composition_scorer_packages(
    aqelyn_root: Path | None = None,
) -> frozenset[str]:
    candidates: set[str] = set()
    for package in discover_packages(aqelyn_root):
        trees = [_parse(path) for path in sorted(package.path.rglob("*.py"))]
        aliases = _known_unknown_aliases(trees)
        has_factor = any(_tree_has_known_unknown_factor(tree, aliases=aliases) for tree in trees)
        if has_factor:
            candidates.add(package.name)
    return frozenset(candidates)


def assert_scorer_registry_complete(
    registered: Mapping[str, object],
    *,
    aqelyn_root: Path | None = None,
) -> None:
    discovered = discover_composition_scorer_packages(aqelyn_root)
    selected = frozenset(registered)
    missing = sorted(discovered - selected)
    extra = sorted(selected - discovered)
    if missing or extra:
        raise GuaranteeViolation(
            f"composition scorer registry mismatch: missing={missing}, extra={extra}"
        )


def discover_vulnerability_factor_providers(
    aqelyn_root: Path | None = None,
) -> frozenset[str]:
    """Discover concrete EA-0024 factor-provider implementations.

    A provider is a concrete class that implements one of EA-0024's factor-returning
    protocol methods and either annotates or constructs a ``PriorityFactor``. The
    structural signature catches the shipped KEV adapter even though its public
    boundary deliberately uses ``Any`` to avoid a threat -> vuln import cycle.
    """

    root = aqelyn_root or aqelyn_source_root()
    providers: set[str] = set()
    for path in source_python_files(root):
        tree = _parse(path)
        relative = path.relative_to(root).with_suffix("")
        module = ".".join(("aqelyn", *relative.parts))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or _class_is_protocol(node):
                continue
            for item in node.body:
                if (
                    isinstance(item, ast.AsyncFunctionDef)
                    and item.name in _VULNERABILITY_FACTOR_METHODS
                    and _returns_priority_factor(item)
                ):
                    providers.add(f"{module}.{node.name}.{item.name}")
    return frozenset(providers)


def assert_vulnerability_factor_provider_registry_complete(
    registered: Mapping[str, object],
    *,
    aqelyn_root: Path | None = None,
) -> None:
    discovered = discover_vulnerability_factor_providers(aqelyn_root)
    selected = frozenset(registered)
    missing = sorted(discovered - selected)
    extra = sorted(selected - discovered)
    if missing or extra:
        raise GuaranteeViolation(
            f"vulnerability factor-provider registry mismatch: missing={missing}, extra={extra}"
        )


def discover_mission_score_paths(
    aqelyn_root: Path | None = None,
) -> frozenset[str]:
    """Discover every production path that can turn mission input into an output.

    Discovery deliberately starts wider than scorers. A mission owner call may feed a
    score, priority, correlation, health probe, or another owner adapter, and a new
    path must be classified before the central guarantee accepts it. The registry
    therefore records behavioral cases and reasoned exclusions; omission is never an
    implicit exclusion.
    """

    root = aqelyn_root or aqelyn_source_root()
    paths: set[str] = set()
    for path in source_python_files(root):
        tree = _parse(path)
        relative = path.relative_to(root).with_suffix("")
        module = ".".join(("aqelyn", *relative.parts))
        for qualified_name, node in _qualified_functions(tree):
            if (
                _calls_attribute(node, "mission_impact")
                or _calls_name(node, "mission_context_from_results")
                or _accepts_optional_risk_mission_context(node)
            ):
                paths.add(f"{module}.{qualified_name}")
    return frozenset(paths)


def assert_mission_score_path_registry_complete(
    registered: Mapping[str, object],
    exclusions: Mapping[str, str],
    *,
    aqelyn_root: Path | None = None,
) -> None:
    blank_reasons = sorted(path for path, reason in exclusions.items() if not reason.strip())
    if blank_reasons:
        raise GuaranteeViolation(f"mission score-path exclusions require reasons: {blank_reasons}")
    overlap = sorted(frozenset(registered) & frozenset(exclusions))
    if overlap:
        raise GuaranteeViolation(
            f"mission score-path registry has cases also marked excluded: {overlap}"
        )
    discovered = discover_mission_score_paths(aqelyn_root)
    selected = frozenset(registered) | frozenset(exclusions)
    missing = sorted(discovered - selected)
    extra = sorted(selected - discovered)
    if missing or extra:
        raise GuaranteeViolation(
            f"mission score-path registry mismatch: missing={missing}, extra={extra}"
        )


def assert_unknown_less_favourable(observations: Sequence[ScorerObservation]) -> None:
    if not observations:
        raise GuaranteeViolation("no composition scorer observations were supplied")
    for observation in observations:
        if observation.orientation == "higher_is_favourable":
            valid = observation.unknown < observation.known_good
        else:
            valid = observation.unknown > observation.known_good
        if not valid:
            raise GuaranteeViolation(
                f"{observation.name} maps unknown to a favourable known result: "
                f"known_good={observation.known_good}, unknown={observation.unknown}"
            )


def _parse(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise GuaranteeViolation(f"cannot classify source file {path}: {exc}") from exc


def _assigned_handler_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_registry_get(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_registry_get(node.value)
            and isinstance(node.target, ast.Name)
        ):
            names.add(node.target.id)
        elif isinstance(node, ast.arg) and _annotation_tail(node.annotation) == "ActionHandler":
            names.add(node.arg)
    return names


def _is_registry_get(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    return node.func.attr == "get" and "registry" in _expression_tail(node.func.value).lower()


def _receiver_is_handler(receiver: ast.expr, *, handler_names: set[str]) -> bool:
    if isinstance(receiver, ast.Name):
        return receiver.id in handler_names or "handler" in receiver.id.lower()
    if isinstance(receiver, ast.Attribute):
        return "handler" in receiver.attr.lower()
    return False


def _expression_tail(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _annotation_tail(annotation: ast.expr | None) -> str:
    if annotation is None:
        return ""
    return _expression_tail(annotation)


def _raise_for_direct_invocations(violations: Sequence[DirectInvocation]) -> None:
    if not violations:
        return
    detail = ", ".join(
        f"{violation.path}:{violation.line} ({violation.expression})" for violation in violations
    )
    raise GuaranteeViolation(f"direct ActionHandler invocation outside EA-0008: {detail}")


def _action_registries(roots: Sequence[object]) -> tuple[tuple[str, object], ...]:
    found: list[tuple[str, object]] = []
    seen: set[int] = set()
    stack = [(root, f"root[{index}]", 0) for index, root in enumerate(roots)]
    while stack:
        value, path, depth = stack.pop()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        if _looks_like_action_registry(value):
            found.append((path, value))
            continue
        if depth >= 4 or _is_leaf(value):
            continue
        if isinstance(value, Mapping):
            stack.extend((item, f"{path}[{key!r}]", depth + 1) for key, item in value.items())
        elif isinstance(value, list | tuple | set | frozenset):
            stack.extend((item, f"{path}[{index}]", depth + 1) for index, item in enumerate(value))
        elif is_dataclass(value) and not isinstance(value, type):
            stack.extend(
                (getattr(value, field.name), f"{path}.{field.name}", depth + 1)
                for field in fields(value)
            )
        elif hasattr(value, "__dict__") and _traversable_object(value):
            stack.extend((item, f"{path}.{name}", depth + 1) for name, item in vars(value).items())
    return tuple(found)


def _looks_like_action_registry(value: object) -> bool:
    if isinstance(value, InMemoryActionRegistry):
        return True
    return (
        value.__class__.__name__.endswith("ActionRegistry")
        and callable(getattr(value, "register", None))
        and callable(getattr(value, "get", None))
    )


def _is_leaf(value: object) -> bool:
    return isinstance(
        value,
        (str, bytes, bytearray, int, float, complex, bool, type(None), Path, ModuleType, type),
    )


def _traversable_object(value: object) -> bool:
    module = value.__class__.__module__
    return module.startswith(("aqelyn.", "guarantees."))


def _known_unknown_aliases(trees: Sequence[ast.Module]) -> set[str]:
    aliases: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and _literal_values(node.value) == {"known", "unknown"}
            ):
                aliases.add(node.targets[0].id)
    return aliases


def _tree_has_known_unknown_factor(tree: ast.Module, *, aliases: set[str]) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or "Factor" not in node.name:
            continue
        for item in node.body:
            if (
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.target.id == "status"
                and (
                    _annotation_tail(item.annotation) in aliases
                    or _literal_values(item.annotation) == {"known", "unknown"}
                )
            ):
                return True
    return False


def _class_is_protocol(node: ast.ClassDef) -> bool:
    return any(_expression_tail(base) == "Protocol" for base in node.bases)


def _returns_priority_factor(node: ast.AsyncFunctionDef) -> bool:
    if _annotation_tail(node.returns) == "PriorityFactor":
        return True
    return any(
        isinstance(item, ast.Call) and _expression_tail(item.func) == "PriorityFactor"
        for item in ast.walk(node)
    )


def _qualified_functions(
    tree: ast.Module,
) -> tuple[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef], ...]:
    functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            functions.extend(
                (f"{node.name}.{item.name}", item)
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            )
    return tuple(functions)


def _calls_attribute(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    attribute: str,
) -> bool:
    return any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == attribute
        for item in ast.walk(node)
    )


def _calls_name(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    name: str,
) -> bool:
    return any(
        isinstance(item, ast.Call) and _expression_tail(item.func) == name
        for item in ast.walk(node)
    )


def _accepts_optional_risk_mission_context(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
        annotation = argument.annotation
        if not isinstance(annotation, ast.BinOp) or not isinstance(annotation.op, ast.BitOr):
            continue
        members = {
            (
                "None"
                if isinstance(member, ast.Constant) and member.value is None
                else _annotation_tail(member)
            )
            for member in (annotation.left, annotation.right)
        }
        if members == {"RiskMissionContext", "None"}:
            return True
    return False


def _literal_values(node: ast.expr) -> set[str]:
    if not isinstance(node, ast.Subscript) or _expression_tail(node.value) != "Literal":
        return set()
    return {
        item.value
        for item in ast.walk(node.slice)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }
