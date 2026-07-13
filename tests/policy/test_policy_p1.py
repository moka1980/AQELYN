"""P1 acceptance tests for Policy Engine models and condition interpreter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

import aqelyn.policy.interpreter as interpreter
from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import PolicyConfigInvalid
from aqelyn.policy import Condition, Policy, Rule, Target, condition_matches

SYS = ActorRef(actor_type="system", actor_id="policy-p1-test")


def _condition(payload: dict[str, object]) -> Condition:
    return Condition.model_validate(payload)


def _rule(
    *,
    rule_id: str = "rule-1",
    kind: str = "authorization",
    effect: str = "permit",
    condition: dict[str, object] | None = None,
) -> Rule:
    return Rule(
        id=rule_id,
        kind=kind,
        description=f"{kind} rule {rule_id}",
        target=Target(actions=["workflow.read"], resource_types=["device"]),
        condition=_condition(condition) if condition is not None else None,
        effect=effect,
        obligations=[],
        priority=10,
    )


def _policy(*rules: Rule) -> Policy:
    return Policy(
        id="policy-p1",
        version=1,
        name="P1 policy",
        description="P1 validation policy",
        tenant_id=None,
        rules=list(rules),
        standard=None,
        set_by=SYS,
        set_at=datetime.now(UTC),
    )


def test_policy_condition_interpreter() -> None:
    data: dict[str, object] = {
        "subject": {"actor_type": "user", "actor_id": "alice"},
        "action": "workflow.read",
        "resource": {
            "type": "device",
            "attributes": {
                "tier": 1,
                "tags": ["prod", "pci"],
                "mfa_enabled": True,
                "owner": "security",
            },
        },
        "context": {"risk": 0.2},
    }

    condition = _condition(
        {
            "all": [
                {"op": "eq", "attr": "resource.type", "value": "device"},
                {"op": "in", "attr": "action", "value": ["workflow.read", "workflow.scan"]},
                {"op": "gt", "attr": "resource.attributes.tier", "value": 0},
                {"op": "exists", "attr": "resource.attributes.mfa_enabled"},
                {
                    "any": [
                        {
                            "op": "contains",
                            "attr": "resource.attributes.tags",
                            "value": "prod",
                        },
                        {"op": "eq", "attr": "resource.attributes.owner", "value": "ops"},
                    ]
                },
                {"not": {"op": "eq", "attr": "context.risk", "value": 1.0}},
            ]
        }
    )

    assert condition_matches(condition, data) is True
    assert condition_matches(
        _condition({"op": "nin", "attr": "action", "value": ["workflow.write"]}),
        data,
    )
    assert not condition_matches(
        _condition({"op": "lte", "attr": "resource.attributes.tier", "value": 0}),
        data,
    )


def test_policy_no_code_eval() -> None:
    source = Path(interpreter.__file__).read_text(encoding="utf-8")

    for forbidden in ("eval", "exec", "compile", "import"):
        assert forbidden not in source


def test_policy_lookup_dunder_path_no_match() -> None:
    condition = _condition(
        {
            "op": "eq",
            "attr": "resource.attributes.__class__",
            "value": "secret",
        }
    )
    data: dict[str, object] = {
        "resource": {"attributes": {"__class__": "secret", "owner": "security"}}
    }

    assert condition_matches(condition, data) is False
    assert (
        condition_matches(
            _condition({"op": "exists", "attr": "resource.attributes.__class__"}),
            data,
        )
        is False
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"op": "matches", "attr": "resource.type", "value": "device"},
        {"op": "eq", "value": "device"},
        {"all": []},
        {"any": []},
        {"op": "eq", "attr": "resource.type", "value": "device", "any": []},
        {"script": "return true"},
    ],
)
def test_policy_config_invalid_condition(payload: dict[str, object]) -> None:
    with pytest.raises(PolicyConfigInvalid):
        _condition(payload)


@pytest.mark.parametrize(
    "rule",
    [
        lambda: _rule(kind="workflow", effect="permit"),
        lambda: _rule(kind="authorization", effect="allow"),
        lambda: _rule(kind="authorization", effect="require"),
        lambda: _rule(kind="compliance", effect="permit"),
        lambda: Rule(
            id="bad-priority",
            kind="authorization",
            description="bad priority",
            target=Target(actions=["workflow.read"], resource_types=["device"]),
            condition=None,
            effect="permit",
            obligations=[],
            priority=True,
        ),
    ],
)
def test_policy_config_invalid_rule(rule: Callable[[], object]) -> None:
    with pytest.raises(PolicyConfigInvalid):
        rule()


def test_policy_config_invalid_policy() -> None:
    with pytest.raises(PolicyConfigInvalid):
        _policy()
    with pytest.raises(PolicyConfigInvalid):
        _policy(_rule(rule_id="duplicate"), _rule(rule_id="duplicate"))
    with pytest.raises(PolicyConfigInvalid):
        Policy(
            id="policy-p1",
            version=0,
            name="P1 policy",
            description="Invalid version",
            tenant_id=None,
            rules=[_rule()],
            set_by=SYS,
            set_at=datetime.now(UTC),
        )


def test_policy_depth_cap() -> None:
    payload: dict[str, object] = {"op": "eq", "attr": "resource.type", "value": "device"}
    for _ in range(32):
        payload = {"not": payload}

    with pytest.raises(PolicyConfigInvalid):
        _condition(payload)

    allowed: dict[str, object] = {"op": "eq", "attr": "resource.type", "value": "device"}
    for _ in range(31):
        allowed = {"not": allowed}

    condition = _condition(allowed)
    assert condition_matches(condition, {"resource": {"type": "service"}}) is True
