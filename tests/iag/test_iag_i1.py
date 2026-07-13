"""I1 acceptance tests for Identity & Access Governance models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, ActorRef, new_id
from aqelyn.conventions.errors import IAGConfigInvalid, SchemaValidationError
from aqelyn.graph import Path
from aqelyn.iag import (
    AccessPath,
    AccessRisk,
    AccessRiskReport,
    Certification,
    IAGConfig,
    ReviewItem,
)

SYS = ActorRef(actor_type="system", actor_id="iag-i1-test")


def _now() -> datetime:
    return datetime.now(UTC)


def _path(*node_ids: str) -> Path:
    return Path(node_ids=list(node_ids), edges=[], length=max(0, len(node_ids) - 1))


def test_iag_config_invalid() -> None:
    assert "IAGConfigInvalid" in ALL_ERROR_CODES
    assert "CertificationNotFound" in ALL_ERROR_CODES
    assert "ReviewItemNotFound" in ALL_ERROR_CODES
    assert PREFIXES["cert"] == "iag_certification"
    assert PREFIXES["rvi"] == "iag_review_item"

    config = IAGConfig.model_validate(
        {
            "dormant_days": 45,
            "privileged_roles": ["role-admin"],
            "peer_baseline": "engineering",
            "review_default_due_days": 14,
        },
        context={"known_privileged_roles": {"role-admin"}},
    )
    assert config.dormant_days == 45
    assert config.privileged_roles == ["role-admin"]

    with pytest.raises(IAGConfigInvalid, match="days"):
        IAGConfig(dormant_days=0)

    with pytest.raises(IAGConfigInvalid, match="days"):
        IAGConfig(review_default_due_days=0)

    with pytest.raises(IAGConfigInvalid, match="duplicates"):
        IAGConfig(privileged_roles=["role-admin", "role-admin"])

    with pytest.raises(IAGConfigInvalid, match="unknown privileged_roles"):
        IAGConfig.model_validate(
            {"privileged_roles": ["role-root"]},
            context={"known_privileged_roles": {"role-admin"}},
        )

    with pytest.raises(IAGConfigInvalid, match="peer_baseline"):
        IAGConfig(peer_baseline=" ")

    identity_id = new_id("obj")
    account_id = new_id("obj")
    entitlement_id = new_id("obj")
    evidence_id = new_id("evd")
    access_path = AccessPath(
        identity_id=identity_id,
        account_id=account_id,
        entitlement_ids=[entitlement_id],
        via=_path(identity_id, account_id, entitlement_id),
    )
    risk = AccessRisk(
        kind="sod_conflict",
        subject_id=identity_id,
        detail={"entitlement_ids": [entitlement_id]},
        severity="high",
        evidence_path=access_path.via,
        reason="Identity holds mutually exclusive entitlements.",
    )
    report = AccessRiskReport(risks=[risk], evaluated=1, truncated=False)
    assert report.risks == [risk]

    pending = ReviewItem(
        id=new_id("rvi"),
        identity_id=identity_id,
        account_id=account_id,
        entitlement_id=entitlement_id,
        current_state={"granted": True},
        recommendation="review",
    )
    assert pending.decision == "pending"

    with pytest.raises(IAGConfigInvalid, match="pending"):
        ReviewItem(
            id=new_id("rvi"),
            identity_id=identity_id,
            current_state={},
            recommendation="review",
            decided_by=SYS,
        )

    with pytest.raises(IAGConfigInvalid, match="require actor"):
        ReviewItem(
            id=new_id("rvi"),
            identity_id=identity_id,
            current_state={},
            recommendation="review",
            decision="revoked",
        )

    decided = ReviewItem(
        id=new_id("rvi"),
        identity_id=identity_id,
        account_id=account_id,
        entitlement_id=entitlement_id,
        current_state={"granted": True},
        recommendation="revoke",
        decision="revoked",
        decided_by=SYS,
        decided_at=_now(),
        evidence_id=evidence_id,
        note="Access no longer needed.",
    )
    assert decided.evidence_id == evidence_id

    created = _now()
    cert = Certification(
        id=new_id("cert"),
        tenant_id=None,
        name="Q3 privileged access review",
        scope={"object_type": "identity"},
        status="open",
        items=[pending],
        created_by=SYS,
        created_at=created,
        due_at=created + timedelta(days=14),
    )
    assert cert.items == [pending]
    assert cert.version == 1

    with pytest.raises(IAGConfigInvalid, match="due_at"):
        Certification(
            id=new_id("cert"),
            name="expired before start",
            scope={},
            items=[],
            created_by=SYS,
            created_at=created,
            due_at=created,
        )

    with pytest.raises(SchemaValidationError, match="cert_"):
        Certification(
            id=new_id("rvi"),
            name="wrong prefix",
            scope={},
            items=[],
            created_by=SYS,
            created_at=created,
        )
