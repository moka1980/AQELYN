"""Shared three-branch capability-absence discovery for batch conformance."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CapabilityAbsenceSpec:
    """Vocabulary and exact declaration for one recorded capability gap."""

    ea_number: str
    label: str
    raw_terms: tuple[str, ...]
    token_sets: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class CapabilityAbsenceSignals:
    """Inspectable results from the three independent discovery branches."""

    declared_owners: tuple[Path, ...]
    raw_hits: tuple[str, ...]
    identifier_hits: tuple[str, ...]

    @property
    def vocabulary_hits(self) -> tuple[str, ...]:
        """Return the union used by legacy guards without hiding branch results."""

        return tuple(sorted({*self.raw_hits, *self.identifier_hits}))


def discover_capability_signals(
    root: Path,
    spec: CapabilityAbsenceSpec,
) -> CapabilityAbsenceSignals:
    """Discover exact declarations, raw terms, and normalized identifiers."""

    declared_owners: list[Path] = []
    raw_hits: set[str] = set()
    identifier_hits: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        relative_path = path.relative_to(root)
        location = relative_path.as_posix()

        if path.name == "__init__.py":
            docstring = ast.get_docstring(tree, clean=False) or ""
            declarations = set(re.findall(r"\bEA-\d{4}\b", docstring))
            if spec.ea_number in declarations:
                declared_owners.append(path)

        lowered_source = source.lower()
        for term in spec.raw_terms:
            if term.lower() in lowered_source:
                raw_hits.add(f"{location}: {term}")

        identifiers = {path.stem, *relative_path.parts}
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                identifiers.add(node.name)
            elif isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.alias):
                identifiers.add(node.asname or node.name.rsplit(".", 1)[-1])
        for identifier in sorted(identifiers):
            tokens = identifier_tokens(identifier)
            if any(required <= tokens for required in spec.token_sets):
                identifier_hits.add(f"{location}: {identifier}")

    return CapabilityAbsenceSignals(
        declared_owners=tuple(declared_owners),
        raw_hits=tuple(sorted(raw_hits)),
        identifier_hits=tuple(sorted(identifier_hits)),
    )


def identifier_tokens(identifier: str) -> frozenset[str]:
    """Normalize snake_case and CamelCase without substring false positives."""

    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", separated)
    return frozenset(part.lower() for part in re.findall(r"[A-Za-z0-9]+", separated))
