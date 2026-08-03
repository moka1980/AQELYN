"""ECR-0094 witnesses for every component of the findings keyset read."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from aqelyn.conventions import new_id
from aqelyn.findings import Automation, Finding, FindingQuery, Remediation
from aqelyn.findings.postgres import PostgresFindingStore
from aqelyn.findings.store import FindingStore

_ROW_COUNT = 5


def _finding(
    *,
    finding_id: str,
    dedup_key: str,
    severity_score: float,
) -> Finding:
    now = datetime.now(UTC)
    return Finding(
        id=finding_id,
        finding_type="aqelyn.finding.device.open_port",
        schema_version=1,
        dedup_key=dedup_key,
        title="SSH exposed to the internet",
        severity="high",
        severity_score=severity_score,
        what_happened="Port 22 is reachable from any address.",
        why_it_matters="Attackers can attempt to brute-force SSH.",
        how_determined="A handed-in descriptor reports an externally reachable listener.",
        risk_of_inaction="Unauthorized access is likely over time.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=[new_id("obj")],
        remediation=Remediation(
            summary="Restrict SSH to trusted networks.",
            steps=["Add a firewall rule", "Verify access"],
            difficulty="easy",
            expected_outcome="Port 22 is no longer publicly reachable.",
        ),
        automation=Automation(eligibility="assisted"),
        source_engine="ecr-0094-witness",
        first_detected_at=now,
        last_detected_at=now,
    )


async def _assert_store_holds_rows(store: FindingStore, expected: list[str]) -> None:
    rows, _cursor = await store.query(FindingQuery(limit=len(expected)))
    assert len(rows) == len(expected)
    assert {row.id for row in rows} == set(expected)


async def _assert_keyset_walk(store: FindingStore, expected: list[str]) -> None:
    for limit in range(1, len(expected) + 1):
        cursor: str | None = None
        seen: list[str] = []
        for _page_number in range(len(expected) + 2):
            page, cursor = await store.query(FindingQuery(limit=limit, cursor=cursor))
            seen.extend(finding.id for finding in page)
            if cursor is None:
                break
        else:
            raise AssertionError("findings keyset walk did not terminate")

        assert seen == expected
        assert len(seen) == len(set(seen))


async def _assert_under_store_plan(
    store: FindingStore,
    expected: list[str],
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    if isinstance(store, PostgresFindingStore):
        async with forced_keyset_plan(store):
            await _assert_keyset_walk(store, expected)
        return
    await _assert_keyset_walk(store, expected)


async def test_finding_keyset_tiebreak_witness(
    finding_store: FindingStore,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("fnd") for _ in range(_ROW_COUNT))
    for index, finding_id in enumerate(reversed(ids)):
        saved = await finding_store.raise_finding(
            _finding(
                finding_id=finding_id,
                dedup_key=f"ecr0094:tiebreak:{index}",
                severity_score=80.0,
            )
        )
        assert saved.severity_score == 80.0

    await _assert_store_holds_rows(finding_store, ids)
    await _assert_under_store_plan(finding_store, ids, forced_keyset_plan)


async def test_finding_keyset_leading_key_witness(
    finding_store: FindingStore,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("fnd") for _ in range(_ROW_COUNT))
    scores = [float(20 * (index + 1)) for index in range(_ROW_COUNT)]
    for index, (finding_id, severity_score) in enumerate(zip(ids, scores, strict=True)):
        saved = await finding_store.raise_finding(
            _finding(
                finding_id=finding_id,
                dedup_key=f"ecr0094:leading:{index}",
                severity_score=severity_score,
            )
        )
        assert saved.severity_score == severity_score

    expected = list(reversed(ids))
    id_only = sorted(ids)
    assert id_only != expected
    await _assert_store_holds_rows(finding_store, expected)
    await _assert_under_store_plan(finding_store, expected, forced_keyset_plan)
