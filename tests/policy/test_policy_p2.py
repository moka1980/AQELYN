"""P2 acceptance tests for Policy Engine decision core."""

from __future__ import annotations

from datetime import UTC, datetime

from aqelyn.conventions import ActorRef
from aqelyn.policy import (
    Condition,
    DecisionRequest,
    DecisionResource,
    Obligation,
    Policy,
    PolicyEngine,
    Rule,
    Target,
    more_restrictive_effect,
)

SYS = ActorRef(actor_type="system", actor_id="policy-p2-test")


def _condition(payload: dict[str, object]) -> Condition:
    return Condition.model_validate(payload)


def _rule(
    rule_id: str,
    effect: str,
    *,
    kind: str = "authorization",
    condition: dict[str, object] | None = None,
    actions: list[str] | None = None,
    resource_types: list[str] | None = None,
    obligations: list[Obligation] | None = None,
    priority: int = 0,
) -> Rule:
    return Rule(
        id=rule_id,
        kind=kind,
        description=f"{kind} {effect} rule {rule_id}",
        target=Target(
            actions=["workflow.read"] if actions is None else actions,
            resource_types=["device"] if resource_types is None else resource_types,
        ),
        condition=_condition(condition) if condition is not None else None,
        effect=effect,
        obligations=obligations or [],
        priority=priority,
    )


def _policy(*rules: Rule, policy_id: str = "policy-p2", tenant_id: str | None = None) -> Policy:
    return Policy(
        id=policy_id,
        version=1,
        name=f"Policy {policy_id}",
        description="P2 decision policy",
        tenant_id=tenant_id,
        rules=list(rules),
        standard=None,
        set_by=SYS,
        set_at=datetime.now(UTC),
    )


def _request(
    *,
    action: str = "workflow.read",
    resource_type: str | None = "device",
    attrs: dict[str, object] | None = None,
    tenant_id: str | None = None,
) -> DecisionRequest:
    return DecisionRequest(
        subject=SYS,
        action=action,
        resource=DecisionResource(
            id="obj-test",
            type=resource_type,
            attributes=attrs or {},
            tenant_id=tenant_id,
        ),
        context={"risk": 0.2},
    )


async def test_policy_deny_by_default() -> None:
    decision = await PolicyEngine().authorize(_request())

    assert decision.effect == "deny"
    assert decision.matched_rules == []
    assert decision.obligations == []
    assert "default" in decision.reason


async def test_policy_deny_overrides() -> None:
    engine = PolicyEngine(
        [
            _policy(
                _rule("permit-read", "permit", priority=1),
                _rule("deny-prod", "deny", priority=2),
            )
        ]
    )

    decision = await engine.authorize(_request())

    assert decision.effect == "deny"
    assert decision.matched_rules == ["policy-p2:deny-prod", "policy-p2:permit-read"]
    assert "deny" in decision.reason.lower()


async def test_policy_require_approval() -> None:
    engine = PolicyEngine(
        [
            _policy(
                _rule(
                    "permit-with-approval",
                    "permit",
                    obligations=[Obligation(type="require_approval")],
                    priority=2,
                ),
                _rule("explicit-approval", "require_approval", priority=1),
            )
        ]
    )

    decision = await engine.authorize(_request())

    assert decision.effect == "require_approval"
    assert decision.matched_rules == [
        "policy-p2:permit-with-approval",
        "policy-p2:explicit-approval",
    ]
    assert [obligation.type for obligation in decision.obligations] == ["require_approval"]


async def test_policy_explainable() -> None:
    engine = PolicyEngine([_policy(_rule("permit-read", "permit"))])
    request = _request(attrs={"mfa_enabled": True})

    first = await engine.authorize(request)
    second = await engine.authorize(request)
    explanation = engine.explain(first)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.effect == "permit"
    assert first.matched_rules == ["policy-p2:permit-read"]
    assert explanation["matched_rules"] == ["policy-p2:permit-read"]
    assert explanation["reason"] == first.reason


def test_policy_tighten_only() -> None:
    assert more_restrictive_effect("permit", "require_approval") == "require_approval"
    assert more_restrictive_effect("permit", "deny") == "deny"
    assert more_restrictive_effect("require_approval", "deny") == "deny"


async def test_policy_compliance_violations() -> None:
    engine = PolicyEngine(
        [
            _policy(
                _rule(
                    "require-mfa",
                    "require",
                    kind="compliance",
                    actions=None,
                    condition={
                        "op": "eq",
                        "attr": "resource.attributes.mfa_enabled",
                        "value": True,
                    },
                )
            )
        ]
    )

    result = await engine.evaluate_compliance(
        {
            "id": "obj-device",
            "type": "device",
            "attributes": {"mfa_enabled": False},
        },
        tenant_id=None,
    )

    assert result.compliant is False
    assert result.evaluated == 1
    assert len(result.violations) == 1
    assert result.violations[0].policy_id == "policy-p2"
    assert result.violations[0].rule_id == "require-mfa"
    assert "did not hold" in result.violations[0].reason


async def test_policy_no_side_effects() -> None:
    policy = _policy(
        _rule(
            "permit-prod",
            "permit",
            condition={"op": "contains", "attr": "resource.attributes.tags", "value": "prod"},
        )
    )
    request = _request(attrs={"tags": ["prod"]})
    resource = {"id": "obj-device", "type": "device", "attributes": {"mfa_enabled": True}}
    policy_before = policy.model_dump_json()
    request_before = request.model_dump_json()
    resource_before = dict(resource)
    engine = PolicyEngine([policy])

    await engine.authorize(request)
    await engine.evaluate_compliance(resource, tenant_id=None)

    assert policy.model_dump_json() == policy_before
    assert request.model_dump_json() == request_before
    assert resource == resource_before
