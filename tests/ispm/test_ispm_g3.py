"""C-030 G3 acceptance tests for delegation to EA-0011."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.iag import AccessPath, AccessRisk, AccessRiskReport, Certification
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.ispm import InMemoryISPMStore, ISPMEngine, NormalizedIdentity
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine

TENANT = "018f0000-0000-7000-8000-000000330301"
ACTOR = ActorRef(actor_type="user", actor_id="ispm-g3-reviewer")
NOW = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)


class _GovernanceOwnerSpy:
    def __init__(self, *, identity_id: str) -> None:
        self.report = AccessRiskReport(
            risks=[
                AccessRisk(
                    kind="dormant",
                    subject_id=identity_id,
                    severity="medium",
                    reason="Owner-produced risk.",
                )
            ],
            evaluated=17,
            truncated=True,
        )
        self.paths: list[AccessPath] = []
        self.certification = Certification(
            id=new_id("cert"),
            tenant_id=TENANT,
            name="Quarterly access review",
            created_by=ACTOR,
            created_at=NOW,
        )
        self.access_path_calls: list[tuple[str, str | None]] = []
        self.analyze_calls: list[tuple[str | None, ObjectQuery | None]] = []
        self.open_calls: list[tuple[str | None, str, ObjectQuery, ActorRef, int | None]] = []
        self.decision_calls: list[tuple[str, str, str, ActorRef, str | None, int]] = []
        self.complete_calls: list[tuple[str, ActorRef, bool]] = []
        self.finding_calls: list[tuple[AccessRiskReport, ActorRef, bool, str | None]] = []

    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]:
        self.access_path_calls.append((identity_id, tenant_id))
        return self.paths

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        self.analyze_calls.append((tenant_id, scope))
        return self.report

    async def open_certification(
        self,
        *,
        tenant_id: str | None,
        name: str,
        scope: ObjectQuery,
        by: ActorRef,
        due_days: int | None = None,
    ) -> Certification:
        self.open_calls.append((tenant_id, name, scope, by, due_days))
        return self.certification

    async def decide_item(
        self,
        cert_id: str,
        item_id: str,
        *,
        decision: str,
        by: ActorRef,
        note: str | None,
        expected_version: int,
    ) -> Certification:
        self.decision_calls.append((cert_id, item_id, decision, by, note, expected_version))
        return self.certification

    async def complete_certification(
        self,
        cert_id: str,
        *,
        by: ActorRef,
        raise_findings: bool = True,
    ) -> list[str]:
        self.complete_calls.append((cert_id, by, raise_findings))
        return ["run-owner"]

    async def risks_to_findings(
        self,
        report: AccessRiskReport,
        *,
        by: ActorRef,
        prioritize: bool = True,
        tenant_id: str | None = None,
    ) -> list[str]:
        self.finding_calls.append((report, by, prioritize, tenant_id))
        return ["fnd-owner"]


async def _engine() -> tuple[ISPMEngine, _GovernanceOwnerSpy, str]:
    identity_id = new_id("obj")
    owner = _GovernanceOwnerSpy(identity_id=identity_id)
    store = InMemoryISPMStore(mode="enterprise")
    await store.upsert_identity(
        NormalizedIdentity(
            object_id=identity_id,
            tenant_id=TENANT,
            external_id="identity:governed",
            provider="entra",
            identity_kind="human",
            field_provenance={"identity_kind": "provider:/kind"},
            evidence_id=new_id("evd"),
        )
    )
    engine = ISPMEngine(
        store,
        object_store=InMemoryObjectStore(mode="enterprise"),
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise")),
        evidence_store=InMemoryEvidenceStore(mode="enterprise"),
        trust=TrustEngine(registry=InMemorySourceReliabilityRegistry()),
        governance_owner=owner,
    )
    return engine, owner, identity_id


async def test_ispm_iag_not_reimplemented() -> None:
    engine, owner, identity_id = await _engine()

    report = await engine.governance_context(identity_id, tenant_id=TENANT)
    paths = await engine.access_paths(identity_id, tenant_id=TENANT)

    assert report is owner.report
    assert paths is owner.paths
    assert len(owner.analyze_calls) == 1
    tenant_id, scope = owner.analyze_calls[0]
    assert tenant_id == TENANT
    assert isinstance(scope, ObjectQuery)
    assert scope.tenant_id == TENANT
    assert scope.limit == engine.config.page_budget
    assert owner.access_path_calls == [(identity_id, TENANT)]

    engine.governance_owner = None
    with pytest.raises(StoreUnavailable, match="EA-0011 governance owner"):
        await engine.governance_context(identity_id, tenant_id=TENANT)


async def test_ispm_certification_delegates() -> None:
    engine, owner, _ = await _engine()
    scope = ObjectQuery(tenant_id=TENANT, object_type="identity", limit=37)
    item_id = new_id("rvi")

    opened = await engine.open_certification(
        tenant_id=TENANT,
        name="Quarterly access review",
        scope=scope,
        by=ACTOR,
        due_days=14,
    )
    decided = await engine.decide_certification_item(
        owner.certification.id,
        item_id,
        decision="approved",
        by=ACTOR,
        note="Owner decision.",
        expected_version=1,
    )
    runs = await engine.complete_certification(
        owner.certification.id,
        by=ACTOR,
        raise_findings=False,
    )

    assert opened is owner.certification
    assert decided is owner.certification
    assert runs == ["run-owner"]
    assert owner.open_calls == [(TENANT, "Quarterly access review", scope, ACTOR, 14)]
    assert owner.decision_calls == [
        (
            owner.certification.id,
            item_id,
            "approved",
            ACTOR,
            "Owner decision.",
            1,
        )
    ]
    assert owner.complete_calls == [(owner.certification.id, ACTOR, False)]


async def test_ispm_findings_path() -> None:
    engine, owner, _ = await _engine()

    finding_ids = await engine.risks_to_findings(owner.report, by=ACTOR, tenant_id=TENANT)

    assert finding_ids == ["fnd-owner"]
    assert owner.finding_calls == [(owner.report, ACTOR, True, TENANT)]
