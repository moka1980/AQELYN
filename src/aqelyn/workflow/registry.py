"""Workflow action registry (EA-0008 W1)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from aqelyn.conventions.errors import ActionFailed, SchemaValidationError, UnknownAction
from aqelyn.workflow.models import ActionSpec


@runtime_checkable
class ActionHandler(Protocol):
    spec: ActionSpec

    async def simulate(
        self, inputs: dict[str, Any], *, tenant_id: str | None
    ) -> dict[str, Any]: ...

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None: ...


@runtime_checkable
class ActionRegistry(Protocol):
    def register(self, handler: ActionHandler) -> None: ...
    def get(self, action_type: str) -> ActionHandler: ...


class InMemoryActionRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, handler: ActionHandler) -> None:
        action_type = handler.spec.action_type
        if action_type in self._handlers:
            raise SchemaValidationError(f"action already registered: {action_type!r}")
        self._handlers[action_type] = handler

    def get(self, action_type: str) -> ActionHandler:
        try:
            return self._handlers[action_type]
        except KeyError as exc:
            raise UnknownAction(f"unknown action_type: {action_type!r}") from exc

    def list(self) -> list[ActionSpec]:
        return [self._handlers[key].spec for key in sorted(self._handlers)]


class ReadOnlyEchoHandler:
    """Built-in read-only test handler; W1 does not wire any execute path."""

    def __init__(
        self,
        *,
        action_type: str = "workflow.echo",
        capability: str = "workflow.read",
        description: str = "Echo inputs for workflow safety tests",
    ) -> None:
        self.spec = ActionSpec(
            action_type=action_type,
            capability=capability,
            effect="read_only",
            reversible=False,
            description=description,
        )
        self.simulation_count = 0

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        self.simulation_count += 1
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        raise ActionFailed("workflow execution is not implemented in W1")

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        raise ActionFailed("read_only workflow actions do not have rollback_ref")
