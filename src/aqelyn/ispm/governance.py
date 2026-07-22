"""Thin delegation to the EA-0011 governance owner (EA-0033 G3)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import ActorRef
from aqelyn.iag import AccessPath, AccessRiskReport, Certification
from aqelyn.objects import ObjectQuery


class IdentityGovernanceOwner(Protocol):
    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]: ...

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport: ...

    async def open_certification(
        self,
        *,
        tenant_id: str | None,
        name: str,
        scope: ObjectQuery,
        by: ActorRef,
        due_days: int | None = None,
    ) -> Certification: ...

    async def decide_item(
        self,
        cert_id: str,
        item_id: str,
        *,
        decision: str,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Certification: ...

    async def complete_certification(
        self,
        cert_id: str,
        *,
        by: ActorRef,
        raise_findings: bool = True,
    ) -> list[str]: ...

    async def risks_to_findings(
        self,
        report: AccessRiskReport,
        *,
        by: ActorRef,
        prioritize: bool = True,
        tenant_id: str | None = None,
    ) -> list[str]: ...


async def governance_context(
    owner: IdentityGovernanceOwner,
    *,
    tenant_id: str | None,
    scope: ObjectQuery,
) -> AccessRiskReport:
    return await owner.analyze_risk(tenant_id=tenant_id, scope=scope)


async def identity_access_paths(
    owner: IdentityGovernanceOwner,
    identity_id: str,
    *,
    tenant_id: str | None,
) -> list[AccessPath]:
    return await owner.access_paths(identity_id, tenant_id=tenant_id)


async def open_certification(
    owner: IdentityGovernanceOwner,
    *,
    tenant_id: str | None,
    name: str,
    scope: ObjectQuery,
    by: ActorRef,
    due_days: int | None = None,
) -> Certification:
    return await owner.open_certification(
        tenant_id=tenant_id,
        name=name,
        scope=scope,
        by=by,
        due_days=due_days,
    )


async def decide_certification_item(
    owner: IdentityGovernanceOwner,
    cert_id: str,
    item_id: str,
    *,
    decision: str,
    by: ActorRef,
    note: str | None,
    expected_version: int,
) -> Certification:
    return await owner.decide_item(
        cert_id,
        item_id,
        decision=decision,
        by=by,
        note=note,
        expected_version=expected_version,
    )


async def complete_certification(
    owner: IdentityGovernanceOwner,
    cert_id: str,
    *,
    by: ActorRef,
    raise_findings: bool = True,
) -> list[str]:
    return await owner.complete_certification(
        cert_id,
        by=by,
        raise_findings=raise_findings,
    )


async def risks_to_findings(
    owner: IdentityGovernanceOwner,
    report: AccessRiskReport,
    *,
    by: ActorRef,
    prioritize: bool = True,
    tenant_id: str | None = None,
) -> list[str]:
    if tenant_id is None:
        return await owner.risks_to_findings(report, by=by, prioritize=prioritize)
    return await owner.risks_to_findings(
        report,
        by=by,
        prioritize=prioritize,
        tenant_id=tenant_id,
    )
