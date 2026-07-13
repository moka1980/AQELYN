"""Policy Engine decision core (EA-0009 P2)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from aqelyn.conventions.errors import PolicyConfigInvalid
from aqelyn.policy.interpreter import condition_matches
from aqelyn.policy.models import (
    ComplianceResult,
    ComplianceViolation,
    Decision,
    DecisionEffect,
    DecisionRequest,
    Obligation,
    Policy,
    Rule,
    Target,
)

_EFFECT_RANK: dict[str, int] = {"permit": 0, "require_approval": 1, "deny": 2}


class PolicyEngine:
    def __init__(self, policies: Sequence[Policy] = ()) -> None:
        self._policies = tuple(policy.model_copy(deep=True) for policy in policies)

    async def authorize(self, request: DecisionRequest) -> Decision:
        payload = _request_payload(request)
        matches = [
            (policy, rule)
            for policy in self._applicable_policies(request.resource.tenant_id)
            for rule in _sorted_rules(policy)
            if rule.kind == "authorization"
            and _target_matches(rule.target, request.action, request.resource.type)
            and _condition_true(rule, payload)
        ]
        matched_rules = [_rule_ref(policy, rule) for policy, rule in matches]
        obligations = _dedupe_obligations(
            obligation
            for _, rule in matches
            if rule.effect != "deny"
            for obligation in _rule_obligations(rule)
        )

        if not matches:
            return Decision(
                effect="deny",
                matched_rules=[],
                obligations=[],
                reason="Denied by default: no applicable permit rule matched.",
            )
        if any(rule.effect == "deny" for _, rule in matches):
            return Decision(
                effect="deny",
                matched_rules=matched_rules,
                obligations=obligations,
                reason=f"Denied because deny rule(s) matched: {', '.join(matched_rules)}.",
            )
        if any(_requires_approval(rule) for _, rule in matches):
            return Decision(
                effect="require_approval",
                matched_rules=matched_rules,
                obligations=obligations,
                reason=(
                    "Approval required because matching policy rule(s) require it: "
                    f"{', '.join(matched_rules)}."
                ),
            )
        return Decision(
            effect="permit",
            matched_rules=matched_rules,
            obligations=obligations,
            reason=f"Permitted by matching policy rule(s): {', '.join(matched_rules)}.",
        )

    async def evaluate_compliance(
        self, resource: dict[str, Any], *, tenant_id: str | None
    ) -> ComplianceResult:
        resource_type = _resource_type(resource)
        subject_ref = str(resource.get("id") or resource_type or "resource")
        payload: dict[str, object] = {"resource": resource}
        violations: list[ComplianceViolation] = []
        evaluated = 0
        for policy in self._applicable_policies(tenant_id):
            for rule in _sorted_rules(policy):
                if rule.kind != "compliance":
                    continue
                if not _target_matches(rule.target, None, resource_type):
                    continue
                evaluated += 1
                if _condition_true(rule, payload):
                    continue
                violations.append(
                    ComplianceViolation(
                        policy_id=policy.id,
                        rule_id=rule.id,
                        subject_ref=subject_ref,
                        requirement=rule.description,
                        reason=f"Required condition for rule {rule.id!r} did not hold.",
                    )
                )
        return ComplianceResult(
            compliant=not violations,
            violations=violations,
            evaluated=evaluated,
        )

    def explain(self, decision: Decision) -> dict[str, object]:
        return {
            "effect": decision.effect,
            "matched_rules": list(decision.matched_rules),
            "obligations": [
                obligation.model_dump(mode="json") for obligation in decision.obligations
            ],
            "reason": decision.reason,
        }

    def _applicable_policies(self, tenant_id: str | None) -> tuple[Policy, ...]:
        return tuple(
            sorted(
                (
                    policy
                    for policy in self._policies
                    if policy.tenant_id is None or policy.tenant_id == tenant_id
                ),
                key=lambda policy: (
                    policy.tenant_id is not None,
                    policy.tenant_id or "",
                    policy.id,
                ),
            )
        )


def more_restrictive_effect(*effects: DecisionEffect) -> DecisionEffect:
    if not effects:
        raise PolicyConfigInvalid("at least one effect is required")
    try:
        effect = max(effects, key=lambda value: _EFFECT_RANK[value])
    except KeyError as exc:
        raise PolicyConfigInvalid(f"unknown decision effect: {exc.args[0]!r}") from exc
    return effect


def _request_payload(request: DecisionRequest) -> dict[str, object]:
    return {
        "subject": request.subject.model_dump(mode="json"),
        "action": request.action,
        "resource": request.resource.model_dump(mode="json"),
        "context": request.context,
    }


def _sorted_rules(policy: Policy) -> list[Rule]:
    return sorted(policy.rules, key=lambda rule: (-rule.priority, rule.id))


def _target_matches(target: Target, action: str | None, resource_type: str | None) -> bool:
    if action is not None and target.actions is not None and action not in target.actions:
        return False
    return not (
        target.resource_types is not None
        and (resource_type is None or resource_type not in target.resource_types)
    )


def _condition_true(rule: Rule, payload: dict[str, object]) -> bool:
    if rule.condition is None:
        return True
    return condition_matches(rule.condition, payload)


def _rule_ref(policy: Policy, rule: Rule) -> str:
    return f"{policy.id}:{rule.id}"


def _rule_obligations(rule: Rule) -> list[Obligation]:
    obligations = list(rule.obligations)
    if rule.effect == "require_approval" and not any(
        obligation.type == "require_approval" for obligation in obligations
    ):
        obligations.append(Obligation(type="require_approval"))
    return obligations


def _requires_approval(rule: Rule) -> bool:
    if rule.effect == "require_approval":
        return True
    return any(obligation.type == "require_approval" for obligation in rule.obligations)


def _dedupe_obligations(obligations: Iterable[Obligation]) -> list[Obligation]:
    seen: set[str] = set()
    out: list[Obligation] = []
    for obligation in obligations:
        key = json.dumps(obligation.model_dump(mode="json"), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(obligation)
    return out


def _resource_type(resource: dict[str, Any]) -> str | None:
    value = resource.get("type", resource.get("object_type"))
    if value is None:
        return None
    return str(value)
