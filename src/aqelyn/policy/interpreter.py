"""Structured condition checker for Policy Engine P1."""

DEFAULT_MAX_DEPTH = 32
_MISSING = object()


def condition_matches(
    condition: object,
    data: dict[str, object],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> bool:
    if max_depth < 1:
        raise ValueError("max_depth must be >= 1")
    return _matches(condition, data, depth=1, max_depth=max_depth)


def _matches(
    condition: object,
    data: dict[str, object],
    *,
    depth: int,
    max_depth: int,
) -> bool:
    if depth > max_depth:
        raise ValueError("condition depth exceeds max_depth")
    op = getattr(condition, "op", None)
    attr = getattr(condition, "attr", None)
    if op is not None and attr is not None:
        return _leaf(str(op), str(attr), getattr(condition, "value", None), data)

    all_items = getattr(condition, "all", None)
    if all_items is not None:
        return all(_matches(item, data, depth=depth + 1, max_depth=max_depth) for item in all_items)

    any_items = getattr(condition, "any", None)
    if any_items is not None:
        return any(_matches(item, data, depth=depth + 1, max_depth=max_depth) for item in any_items)

    not_item = getattr(condition, "not_", None)
    if not_item is not None:
        return not _matches(not_item, data, depth=depth + 1, max_depth=max_depth)

    raise ValueError("malformed condition")


def _leaf(op: str, attr: str, expected: object, data: dict[str, object]) -> bool:
    actual = _lookup(data, attr)
    exists = actual is not _MISSING
    if op == "exists":
        want_exists = True if expected is None else bool(expected)
        return exists is want_exists
    if not exists:
        return op in ("ne", "nin")
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return _contains(expected, actual)
    if op == "nin":
        return not _contains(expected, actual)
    if op == "contains":
        return _contains(actual, expected)
    if op in ("gt", "gte", "lt", "lte"):
        return _compare(op, actual, expected)
    raise ValueError(f"unknown condition op: {op}")


def _lookup(data: dict[str, object], path: str) -> object:
    current: object = data
    for part in path.split("."):
        if not part:
            return _MISSING
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        else:
            current = getattr(current, part, _MISSING)
        if current is _MISSING:
            return _MISSING
    return current


def _contains(container: object, item: object) -> bool:
    try:
        if isinstance(container, dict):
            return item in container
        if isinstance(container, str):
            return isinstance(item, str) and item in container
        if isinstance(container, list | tuple | set | frozenset):
            return item in container
    except TypeError:
        return False
    return False


def _compare(op: str, actual: object, expected: object) -> bool:
    try:
        if op == "gt":
            result = actual > expected  # type: ignore[operator]
        elif op == "gte":
            result = actual >= expected  # type: ignore[operator]
        elif op == "lt":
            result = actual < expected  # type: ignore[operator]
        else:
            result = actual <= expected  # type: ignore[operator]
    except TypeError:
        return False
    return bool(result)
