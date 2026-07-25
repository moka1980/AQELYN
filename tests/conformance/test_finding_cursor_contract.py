"""C-037 cursor contract for `FindingStore` (ECR-0062).

`FindingStore.query` had a pagination-shaped signature that never paginated:
`FindingQuery.cursor` was accepted and validated, neither backend read it, and both
returned `…, None` unconditionally while truncating at `limit`. Since a null
`next_cursor` means *exhausted*, a caller paging until it was `None` got one page and
believed the read complete.

This is store-level only. `FindingStore.query` promises **a page**, not completeness,
so there is deliberately no engine paging loop, no work budget and no `degraded` flag
here -- that apparatus belongs to `inventory()`, which promises a complete answer. The
default `limit=100` is unchanged: this does not change the page size, it makes the page
size truthful.

**The tie-spanning test is the one that matters.** Findings are ordered by
`severity_score DESC, id`, so a cursor keyed on `id` alone is incoherent -- a row with a
larger id sorts *before* the cursor row when its severity is higher. A proof whose
severity scores are all distinct passes against that wrong implementation, so without
ties straddling a page boundary the suite would green-light exactly the bug this ticket
exists to prevent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import SchemaValidationError
from aqelyn.findings import (
    Automation,
    Finding,
    FindingQuery,
    InMemoryFindingStore,
    Remediation,
)
from aqelyn.findings.models import decode_finding_cursor, encode_finding_cursor
from aqelyn.findings.postgres import PostgresFindingStore
from aqelyn.findings.store import FindingStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000370100"
_ACTOR = ActorRef(actor_type="user", actor_id="c037-reviewer")

MATRIX = [
    pytest.param("memory", "local", id="memory-local"),
    pytest.param("memory", "enterprise", id="memory-enterprise"),
    pytest.param("postgres", "local", id="postgres-local"),
    pytest.param("postgres", "enterprise", id="postgres-enterprise"),
]


def _finding(
    *,
    tenant_id: str | None,
    index: int,
    severity_score: float,
    finding_id: str | None = None,
) -> Finding:
    now = datetime.now(UTC)
    return Finding(
        id=finding_id or "",
        tenant_id=tenant_id,
        finding_type="aqelyn.finding.device.open_port",
        schema_version=1,
        dedup_key=f"c037:{index}",
        title="SSH exposed to the internet",
        severity="high",
        severity_score=severity_score,
        what_happened="Port 22 is reachable from any address.",
        why_it_matters="Attackers can attempt to brute-force SSH.",
        how_determined="A TCP connect scan observed an open port 22.",
        risk_of_inaction="Unauthorized access is likely over time.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=[new_id("obj")],
        remediation=Remediation(
            summary="Restrict SSH to trusted networks.",
            steps=["Add a firewall rule", "Verify access"],
            difficulty="easy",
            expected_outcome="Port 22 no longer reachable publicly.",
        ),
        automation=Automation(eligibility="assisted"),
        source_engine="c037-conformance",
        first_detected_at=now,
        last_detected_at=now,
    )


@asynccontextmanager
async def _store(backend: str, tenant_mode: str) -> AsyncIterator[tuple[FindingStore, str | None]]:
    tenant_id = None if tenant_mode == "local" else TENANT
    if backend == "memory":
        yield InMemoryFindingStore(mode=tenant_mode), tenant_id
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    pg = await PostgresFindingStore.connect(PG_URL, mode=tenant_mode)
    async with pg._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_finding, aq_finding_evidence, aq_finding_asset, "
            "aq_finding_audit RESTART IDENTITY CASCADE"
        )
    try:
        yield pg, tenant_id
    finally:
        await pg.close()


async def _page_everything(store: FindingStore, *, tenant_id: str | None, limit: int) -> list[str]:
    """Page to exhaustion the way a caller is meant to, collecting ids in order."""
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(100):  # loop guard: the suite never needs this many pages
        page, cursor = await store.query(
            FindingQuery(tenant_id=tenant_id, limit=limit, cursor=cursor)
        )
        seen.extend(f.id for f in page)
        if cursor is None:
            return seen
    raise AssertionError("pagination did not terminate")


# --- Q1/Q3: the contract ---------------------------------------------------------


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_finding_cursor_no_skip_no_duplicate(backend: str, tenant_mode: str) -> None:
    """Paging through more rows than `limit` returns every row exactly once."""
    async with _store(backend, tenant_mode) as (store, tenant_id):
        # Ascending severity, so ids (monotonic) run OPPOSITE to sort position. If ids
        # agreed with the ordering, an id-only cursor would coincidentally work and the
        # suite would prove nothing.
        written = [
            (await store.raise_finding(_finding(tenant_id=tenant_id, index=i, severity_score=s))).id
            for i, s in enumerate([30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0])
        ]

        seen = await _page_everything(store, tenant_id=tenant_id, limit=2)

        assert sorted(seen) == sorted(written)
        assert len(seen) == len(set(seen)), "a finding was returned on more than one page"
        # Highest severity first, which is the reverse of creation/id order.
        assert seen == list(reversed(written))


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_finding_cursor_ties_span_page_boundary(backend: str, tenant_mode: str) -> None:
    """THE critical case: equal severity scores straddling a page boundary.

    With `limit=2` and scores [90, 90, 90, 50, 50], every page boundary falls inside a
    run of equal scores. An `id`-only cursor skips and duplicates here, while passing a
    suite whose scores are all distinct -- which is why this test exists separately from
    the round-trip above.
    """
    async with _store(backend, tenant_mode) as (store, tenant_id):
        # The low-severity rows are written FIRST so they carry the SMALLER ids, while
        # sorting LAST. That anti-correlation is what makes the id-only cursor fail:
        # under `id > cursor` the trailing 50s are excluded outright, because their ids
        # are smaller than the tie member the first page ended on.
        # Ids are pre-generated and the rows inserted in REVERSE id order within each
        # severity group, so insertion order mirrors neither the id order nor the sort
        # order. A store returning insertion order, or one tie-breaking on arrival,
        # fails here; with fixtures inserted in id order it would not.
        low_ids = sorted(new_id("fnd") for _ in range(2))
        high_ids = sorted(new_id("fnd") for _ in range(3))
        for index, finding_id in enumerate(reversed(low_ids)):
            await store.raise_finding(
                _finding(
                    tenant_id=tenant_id,
                    index=index,
                    severity_score=50.0,
                    finding_id=finding_id,
                )
            )
        for index, finding_id in enumerate(reversed(high_ids)):
            await store.raise_finding(
                _finding(
                    tenant_id=tenant_id,
                    index=10 + index,
                    severity_score=90.0,
                    finding_id=finding_id,
                )
            )
        low, high = low_ids, high_ids
        written = [*low, *high]

        seen = await _page_everything(store, tenant_id=tenant_id, limit=2)

        assert len(seen) == len(written), f"expected {len(written)} rows, paged {len(seen)}"
        assert sorted(seen) == sorted(written)
        assert len(seen) == len(set(seen))
        # Ordering holds across the boundary: every 90 precedes every 50, even though
        # the 50s were created first and sort by a smaller id.
        assert set(seen[:3]) == set(high), "a tie member leaked across the page boundary"
        assert set(seen[3:]) == set(low)
        # Within a tie the order is by id -- the sort key -- not by arrival.
        assert seen[:3] == high_ids
        assert seen[3:] == low_ids


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_finding_cursor_d8_semantics(backend: str, tenant_mode: str) -> None:
    """`next_cursor` is non-null exactly when another matching row exists."""
    async with _store(backend, tenant_mode) as (store, tenant_id):
        for index, score in enumerate([90.0, 80.0, 70.0]):
            await store.raise_finding(
                _finding(tenant_id=tenant_id, index=index, severity_score=score)
            )

        exhausted, exhausted_cursor = await store.query(FindingQuery(tenant_id=tenant_id, limit=3))
        assert len(exhausted) == 3
        assert exhausted_cursor is None, "a full-but-exhausted page must not offer a cursor"

        partial, partial_cursor = await store.query(FindingQuery(tenant_id=tenant_id, limit=2))
        assert len(partial) == 2
        assert partial_cursor is not None

        # The cursor is exclusive: the next page starts after it, with no overlap.
        rest, rest_cursor = await store.query(
            FindingQuery(tenant_id=tenant_id, limit=2, cursor=partial_cursor)
        )
        assert rest_cursor is None
        assert {f.id for f in rest}.isdisjoint({f.id for f in partial})


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_finding_cursor_applies_filters_before_limit(backend: str, tenant_mode: str) -> None:
    """Filters apply before the page, so paging a filtered set stays within it."""
    async with _store(backend, tenant_mode) as (store, tenant_id):
        for index, score in enumerate([90.0, 80.0, 70.0, 60.0]):
            await store.raise_finding(
                _finding(tenant_id=tenant_id, index=index, severity_score=score)
            )
        target = await store.raise_finding(
            _finding(tenant_id=tenant_id, index=99, severity_score=10.0)
        )
        await store.transition(
            target.id,
            "acknowledged",
            by=_ACTOR,
            note=None,
            expected_version=target.version,
        )

        seen: list[str] = []
        cursor: str | None = None
        while True:
            page, cursor = await store.query(
                FindingQuery(tenant_id=tenant_id, status=("open",), limit=2, cursor=cursor)
            )
            seen.extend(f.id for f in page)
            if cursor is None:
                break

        assert target.id not in seen
        assert len(seen) == 4


# --- cursor codec ----------------------------------------------------------------


def test_finding_cursor_encodes_the_complete_sort_key() -> None:
    """The cursor carries `(severity_score, id)`, and round-trips exactly."""
    finding_id = new_id("fnd")
    cursor = encode_finding_cursor(severity_score=73.125, finding_id=finding_id)

    assert decode_finding_cursor(cursor) == (73.125, finding_id)
    # `repr` round-trips floats exactly, so the resume point is the stored value and
    # not a rounded approximation that could straddle a tie.
    awkward = 0.1 + 0.2
    assert decode_finding_cursor(
        encode_finding_cursor(severity_score=awkward, finding_id=finding_id)
    ) == (awkward, finding_id)


def test_finding_cursor_rejects_malformed_input() -> None:
    """A cursor is validated at the query boundary, not trusted into SQL."""
    for bad in ("", "nonsense", "90.0", "90.0|not-an-id", "notafloat|fnd_0", "nan|fnd_0"):
        with pytest.raises(SchemaValidationError):
            FindingQuery(cursor=bad)


# --- Q2: implementers and the health probes --------------------------------------


async def test_finding_health_probes_unaffected() -> None:
    """The three `limit=1` probes discard the result; they only assert liveness.

    `ispm/service.py:303`, `secrets/service.py:335` and `dspm/service.py:270` call
    `finding_store.query(...)` and throw the result away. Checked rather than silently
    skipped: discarding is safe under the new contract, since the cursor changes what is
    *returned*, never whether the call succeeds.
    """
    store = InMemoryFindingStore(mode="enterprise")
    await store.raise_finding(_finding(tenant_id=TENANT, index=0, severity_score=90.0))

    page, cursor = await store.query(FindingQuery(tenant_id=TENANT, limit=1))

    assert len(page) == 1
    assert cursor is None, "one finding is an exhausted read, so no cursor is owed"


def test_finding_store_has_only_the_two_real_implementers() -> None:
    """Q2's inverted rule-18 case does not materialise here -- there are no doubles.

    A double that faithfully models broken behaviour becomes a broken double the moment
    the behaviour is fixed, and `mypy` cannot see it because no type changed. That
    hazard is real, but this codebase has no `FindingStore` double at all: every test
    uses a real store. Enumerated by breaking the Protocol signature and reading what
    `mypy --strict` named (rule 22 -- grep proposes, the type system disposes).

    This asserts the property that made the hazard vacuous, so that adding a double
    later is a deliberate act rather than a silent one.
    """
    import importlib
    import pkgutil

    import aqelyn

    implementers: set[str] = set()
    for module in pkgutil.walk_packages(aqelyn.__path__, "aqelyn."):
        loaded = importlib.import_module(module.name)
        for name, obj in vars(loaded).items():
            if not isinstance(obj, type) or obj.__module__ != module.name:
                continue
            query = getattr(obj, "query", None)
            if query is None or not callable(query):
                continue
            annotations = getattr(query, "__annotations__", {})
            if "FindingQuery" not in str(annotations.get("q", "")):
                continue
            # The Protocol itself is not an implementer.
            if getattr(obj, "_is_protocol", False):
                continue
            implementers.add(name)
    assert implementers == {"InMemoryFindingStore", "PostgresFindingStore"}


def test_finding_cursor_optimized_python() -> None:
    """The contract is not assert-statements that `python -O` strips away."""
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-m",
            "pytest",
            str(Path(__file__).resolve()),
            "-q",
            "-p",
            "no:cacheprovider",
            "-k",
            "ties_span or no_skip or d8_semantics",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
