"""Object-type registry (EA-0002 §7)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqelyn.conventions.errors import SchemaValidationError, UnknownObjectType

AttrValidator = Callable[[dict[str, Any]], None]


class ObjectTypeRegistry:
    """Registers object types and validates object attributes against them."""

    def __init__(self) -> None:
        self._types: dict[str, tuple[int, AttrValidator | None]] = {}
        # Foundation ships exactly one built-in type: `generic` (freeform).
        self.register("generic", 1, None)

    def register(
        self, key: str, schema_version: int, validator: AttrValidator | None = None
    ) -> None:
        self._types[key] = (schema_version, validator)

    def is_registered(self, key: str) -> bool:
        return key in self._types

    def validate(self, object_type: str, attributes: dict[str, Any]) -> None:
        if object_type not in self._types:
            raise UnknownObjectType(f"object_type not registered: {object_type!r}")
        _, validator = self._types[object_type]
        if validator is not None:
            try:
                validator(attributes)
            except SchemaValidationError:
                raise
            except Exception as exc:  # normalize any validator error to a typed error
                raise SchemaValidationError(str(exc)) from exc
