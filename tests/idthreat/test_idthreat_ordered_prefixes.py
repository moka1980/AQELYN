"""ECR-0098 ordered-prefix witnesses for identity detection reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.decision import Derivation, DerivationStep
from aqelyn.idthreat import (
    IdentityBasis,
    IdentityDetection,
    IdentityDetectionStore,
    IdThreatConfig,
    InMemoryIdentityDetectionStore,
    PostgresIdentityDetectionStore,
    SignalRef,
)
from aqelyn.idthreat.store import (
    claims_for_sources,
    detection_result,
    identity_engine_version,
    identity_result_operation,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
ROW_COUNT = 6
CONFIG = IdThreatConfig(min_corroboration=2, min_confidence=0.75, platform_default=0.5)


def _detection(*, detection_id: str, detected_at: datetime) -> IdentityDetection:
    signals = [
        SignalRef(
            kind="authentication",
            ref=f"auth:{detection_id}",
            as_of=detected_at,
            evidence_id=new_id("evd"),
        ),
        SignalRef(
            kind="session",
            ref=f"session:{detection_id}",
            as_of=detected_at,
            evidence_id=new_id("evd"),
        ),
    ]
    profile_ref = new_id("prf")
    basis = [
        IdentityBasis(
            kind="profile",
            ref=f"{profile_ref}:v1",
            as_of=detected_at,
            evidence_id=new_id("evd"),
        ),
        IdentityBasis(
            kind="event",
            ref="rule:ecr0098-rule:v1",
            as_of=detected_at,
            evidence_id=new_id("evd"),
        ),
    ]
    result = detection_result(
        subject_ref=f"acct:{detection_id}",
        detection_type="impossible_travel",
        statement="Two independent observations indicate impossible travel.",
        corroboration=signals,
        confidence=0.9,
        basis=basis,
        profile_ref=profile_ref,
        entitlement_refs=[],
        detected_at=detected_at.isoformat(),
    )
    claims = claims_for_sources(signals, basis)
    refs = [claim.ref_id for claim in claims]
    return IdentityDetection(
        id=detection_id,
        subject_ref=f"acct:{detection_id}",
        detection_type="impossible_travel",
        statement="Two independent observations indicate impossible travel.",
        corroboration=signals,
        confidence=0.9,
        basis=basis,
        derivation=Derivation(
            inputs=claims,
            steps=[
                DerivationStep(
                    seq=1,
                    op=identity_result_operation(),
                    input_refs=refs,
                    params={
                        "source_refs": refs,
                        "result": result,
                        "profile_version": 1,
                        "rule_ref": "ecr0098-rule",
                        "rule_version": 1,
                    },
                    output=result,
                    note="Return the pinned identity detection.",
                )
            ],
            result=result,
            model_version=1,
            engine_version=identity_engine_version(),
        ),
        profile_ref=profile_ref,
        detected_at=detected_at,
    )


async def _stores(kind: str) -> AsyncIterator[IdentityDetectionStore]:
    if kind == "inmemory":
        yield InMemoryIdentityDetectionStore(config=CONFIG)
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresIdentityDetectionStore.connect(PG_URL, config=CONFIG)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_identity_review, aq_identity_detection")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: IdentityDetectionStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "identity detection fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_identity_detection_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    expected = sorted(new_id("idt") for _ in range(ROW_COUNT))
    records = [
        _detection(detection_id=row_id, detected_at=BASE + timedelta(minutes=index))
        for index, row_id in enumerate(expected)
    ]
    async for store in _stores(kind):
        for record in reversed(records):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
