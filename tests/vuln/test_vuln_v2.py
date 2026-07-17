"""V2 acceptance tests for VulnerabilityStore, ingest, and dispositions."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.exposure import AssetRef
from aqelyn.vuln import (
    CarriedScore,
    InMemoryVulnerabilityStore,
    PostgresVulnerabilityStore,
    VulnBasis,
    VulnerabilityIntelligenceEngine,
    VulnerabilityRecord,
    VulnerabilityStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 17, 14, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000240101"
OTHER_TENANT = "018f0000-0000-7000-8000-000000240102"
ACTOR = ActorRef(actor_type="user", actor_id="analyst@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class StoreHarness:
    kind: str
    store: VulnerabilityStore


async def _store(kind: str) -> AsyncIterator[StoreHarness]:
    if kind == "inmemory":
        yield StoreHarness(kind="inmemory", store=InMemoryVulnerabilityStore(mode="enterprise"))
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresVulnerabilityStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_vuln_history, aq_vuln_record")
    try:
        yield StoreHarness(kind="postgres", store=store)
    finally:
        await cast(_Closable, store).close()


def _asset_ref(ref_id: str = "asset:web-1") -> AssetRef:
    return AssetRef(kind="asset", ref_id=ref_id, evidence_id=new_id("evd"))


def _basis(ref: str = "scanner:nessus:run-42") -> VulnBasis:
    return VulnBasis(kind="scanner", ref=ref, as_of=NOW, evidence_id=new_id("evd"))


def _cvss(value: float = 9.8) -> CarriedScore:
    return CarriedScore(
        source="nvd:cve-2026-4242",
        value=value,
        vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        as_of=NOW,
    )


def _epss(value: float = 0.73) -> CarriedScore:
    return CarriedScore(source="first:epss:2026-07-17", value=value, as_of=NOW)


def _record(
    *,
    vulnerability_id: str | None = None,
    tenant_id: str | None = TENANT,
    cve_id: str = "CVE-2026-4242",
    scanner: str = "nessus",
    ref_id: str = "asset:web-1",
    cvss_value: float = 9.8,
    epss_value: float = 0.73,
    confidence: float = 0.84,
    discovered_at: datetime = NOW,
) -> VulnerabilityRecord:
    data: dict[str, object] = {
        "tenant_id": tenant_id,
        "cve_id": cve_id,
        "scanner": scanner,
        "asset_ref": _asset_ref(ref_id),
        "severity": "high",
        "cvss": _cvss(cvss_value),
        "epss": _epss(epss_value),
        "confidence": confidence,
        "basis": [_basis(f"scanner:{scanner}:{ref_id}")],
        "discovered_at": discovered_at,
    }
    if vulnerability_id is not None:
        data["id"] = vulnerability_id
    return VulnerabilityRecord.model_validate(data)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_store_contract(kind: str) -> None:
    async for harness in _store(kind):
        store = harness.store
        first = await store.put(_record())
        other = await store.put(
            _record(
                tenant_id=OTHER_TENANT,
                cve_id="CVE-2026-9999",
                ref_id="asset:other",
                discovered_at=NOW + timedelta(minutes=1),
            )
        )

        assert await store.get(first.id, tenant_id=TENANT) == first
        assert await store.get(first.id, tenant_id=OTHER_TENANT) is None
        assert [row.id for row in await store.query(tenant_id=TENANT, cve_id=first.cve_id)] == [
            first.id
        ]
        assert [row.id for row in await store.query(tenant_id=OTHER_TENANT)] == [other.id]

        changed = first.model_copy(
            update={"severity": "critical", "cvss": _cvss(10.0)},
            deep=True,
        )
        updated = await store.put(changed)
        assert updated.id == first.id
        assert updated.cvss.value == 10.0
        assert (await store.get(first.id, tenant_id=TENANT)) == updated

        history = await store.history(first.id)
        assert len(history) == 2
        assert history[0]["snapshot"]["cvss"]["value"] == 9.8
        assert history[1]["snapshot"]["cvss"]["value"] == 10.0

        if harness.kind == "postgres":
            pg = cast(PostgresVulnerabilityStore, store)
            async with pg._pool.acquire() as conn:
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        "UPDATE aq_vuln_history SET snapshot=snapshot WHERE vulnerability_id=$1",
                        first.id,
                    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_confidence_from_trust(kind: str) -> None:
    async for harness in _store(kind):
        engine = VulnerabilityIntelligenceEngine(harness.store)
        saved = (
            await engine.ingest(
                records=[
                    _record(
                        confidence=0.42,
                        cvss_value=8.6,
                        epss_value=0.12,
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        stored = await harness.store.get(saved.id, tenant_id=TENANT)

        assert saved.confidence == 0.42
        assert saved.cvss.value == 8.6
        assert saved.epss is not None
        assert saved.epss.value == 0.12
        assert stored == saved


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_disposition_attributed(kind: str) -> None:
    async for harness in _store(kind):
        engine = VulnerabilityIntelligenceEngine(harness.store)
        saved = (await engine.ingest(records=[_record()], tenant_id=TENANT))[0]

        updated = await engine.disposition(
            saved.id,
            kind="false_positive",
            by=ACTOR,
            reason="Package name matched a patched backport.",
            tenant_id=TENANT,
        )

        assert updated.disposition is not None
        assert updated.disposition.actor == ACTOR
        assert updated.disposition.kind == "false_positive"
        assert updated.disposition.reason == "Package name matched a patched backport."
        assert updated.disposition.reasserted_by_scanner is False
        assert [
            row.id
            for row in await harness.store.query(tenant_id=TENANT, disposition="false_positive")
        ] == [saved.id]
        assert len(await harness.store.history(saved.id)) == 2


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vuln_disposition_reasserted(kind: str) -> None:
    async for harness in _store(kind):
        engine = VulnerabilityIntelligenceEngine(harness.store)
        saved = (await engine.ingest(records=[_record(cvss_value=7.1)], tenant_id=TENANT))[0]
        await engine.disposition(
            saved.id,
            kind="accepted_risk",
            by=ACTOR,
            reason="Accepted until the next maintenance window.",
            tenant_id=TENANT,
        )

        reasserted = (
            await engine.ingest(
                records=[
                    _record(
                        vulnerability_id=new_id("vln"),
                        cvss_value=9.4,
                        epss_value=0.88,
                        confidence=0.67,
                        discovered_at=NOW + timedelta(days=1),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        counted = await harness.store.query(tenant_id=TENANT, disposition="accepted_risk")

        assert reasserted.id == saved.id
        assert reasserted.status == "reasserted"
        assert reasserted.cvss.value == 9.4
        assert reasserted.epss is not None
        assert reasserted.epss.value == 0.88
        assert reasserted.confidence == 0.67
        assert reasserted.disposition is not None
        assert reasserted.disposition.reasserted_by_scanner is True
        assert [row.id for row in counted] == [saved.id]
        assert len(await harness.store.history(saved.id)) == 3
