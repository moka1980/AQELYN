"""Safe structured comparators for Asset & Configuration Governance (EA-0012 A1)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Literal

from aqelyn.conventions.errors import BaselineConfigInvalid

Comparator = Literal["eq", "ne", "in", "nin", "gte", "lte", "exists", "absent", "regex"]
VALID_COMPARATORS: Final[frozenset[str]] = frozenset(
    ("eq", "ne", "in", "nin", "gte", "lte", "exists", "absent", "regex")
)
MAX_REGEX_PATTERN_LENGTH: Final[int] = 256
MAX_REGEX_GROUPS: Final[int] = 12
MISSING: Final = object()

_NESTED_QUANTIFIER = re.compile(
    r"\((?:[^()\\]|\\.)*(?:[+*]|\{\d+(?:,\d*)?\})(?:[^()\\]|\\.)*\)"
    r"(?:[+*?]|\{\d+(?:,\d*)?\})"
)
_BACKREFERENCE = re.compile(r"(?<!\\)\\[1-9]")
_FORBIDDEN_REGEX_TOKENS: Final[tuple[str, ...]] = (
    "(?=",
    "(?!",
    "(?<=",
    "(?<!",
    "(?P",
    "(?#",
    "(?(",
)


def validate_comparator(value: str) -> str:
    if value not in VALID_COMPARATORS:
        raise BaselineConfigInvalid(f"unknown comparator: {value!r}")
    return value


def validate_regex_pattern(pattern: object) -> str:
    if not isinstance(pattern, str):
        raise BaselineConfigInvalid("regex expected value must be a string")
    if not pattern:
        raise BaselineConfigInvalid("regex pattern must not be empty")
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise BaselineConfigInvalid(f"regex pattern length must be <= {MAX_REGEX_PATTERN_LENGTH}")
    if pattern.count("(") > MAX_REGEX_GROUPS:
        raise BaselineConfigInvalid(f"regex group count must be <= {MAX_REGEX_GROUPS}")
    if any(token in pattern for token in _FORBIDDEN_REGEX_TOKENS):
        raise BaselineConfigInvalid("regex pattern uses unsupported advanced constructs")
    if _BACKREFERENCE.search(pattern):
        raise BaselineConfigInvalid("regex pattern must not use backreferences")
    if _NESTED_QUANTIFIER.search(pattern):
        raise BaselineConfigInvalid("regex pattern must not use nested quantifiers")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise BaselineConfigInvalid(f"invalid regex pattern: {exc}") from exc
    return pattern


def compare(comparator: str, observed: object, expected: object) -> bool:
    selected = validate_comparator(comparator)
    if selected == "exists":
        return observed is not MISSING
    if selected == "absent":
        return observed is MISSING
    if observed is MISSING:
        return False
    if selected == "eq":
        return observed == expected
    if selected == "ne":
        return observed != expected
    if selected == "in":
        return _contains(expected, observed)
    if selected == "nin":
        return not _contains(expected, observed)
    if selected == "gte":
        return _ordered("gte", observed, expected)
    if selected == "lte":
        return _ordered("lte", observed, expected)
    if selected == "regex":
        pattern = validate_regex_pattern(expected)
        return isinstance(observed, str) and re.search(pattern, observed) is not None
    raise BaselineConfigInvalid(f"unknown comparator: {selected!r}")


def _contains(container: object, item: object) -> bool:
    try:
        if isinstance(container, Mapping):
            return item in container
        if isinstance(container, list | tuple | set | frozenset):
            return item in container
    except TypeError:
        return False
    return False


def _ordered(op: str, observed: object, expected: object) -> bool:
    try:
        if op == "gte":
            return bool(observed >= expected)  # type: ignore[operator]
        return bool(observed <= expected)  # type: ignore[operator]
    except TypeError:
        return False
