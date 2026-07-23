"""A deliberately alternate action path for the AC-1 negative control."""

from __future__ import annotations

from typing import Any

from aqelyn.workflow import ActionSpec, InMemoryActionRegistry


class RogueHandler:
    def __init__(self) -> None:
        self.spec = ActionSpec(
            action_type="rogue.customer_mutation",
            capability="rogue.mutate",
            effect="reversible",
            reversible=True,
            description="Deliberately bypass the workflow owner in a negative control.",
        )
        self.executions = 0

    async def simulate(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
    ) -> dict[str, Any]:
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executions += 1
        return {
            "inputs": dict(inputs),
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
        }

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        _ = rollback_ref, tenant_id


class RogueEngine:
    def __init__(self) -> None:
        self.registry = InMemoryActionRegistry()
        self.handler = RogueHandler()
        self.registry.register(self.handler)

    async def execute_outside_workflow(self) -> dict[str, Any]:
        handler = self.registry.get(self.handler.spec.action_type)
        return await handler.execute(
            {"target": "customer-asset"},
            tenant_id=None,
            idempotency_key="rogue-control",
        )
