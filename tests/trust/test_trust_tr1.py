"""TR1 acceptance tests for Trust Engine config and registry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, TrustConfigInvalid
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    TrustConfig,
)

SYS = ActorRef(actor_type="system", actor_id="trust-test")


def _now() -> datetime:
    return datetime.now(UTC)


def test_trust_config_invalid() -> None:
    with pytest.raises(TrustConfigInvalid, match="type_weights"):
        TrustConfig(type_weights={"scanner": 1.1})
    with pytest.raises(TrustConfigInvalid, match="threshold"):
        TrustConfig(thresholds={"low": -0.1, "high": 0.67})
    with pytest.raises(TrustConfigInvalid, match=r"thresholds\.low"):
        TrustConfig(thresholds={"low": 0.8, "high": 0.7})
    with pytest.raises(TrustConfigInvalid, match="half_life_days"):
        TrustConfig(half_life_days=0)
    with pytest.raises(TrustConfigInvalid, match="default_reliability"):
        TrustConfig(default_reliability=1.5)
    with pytest.raises(TrustConfigInvalid, match="weight"):
        SourceReliability(
            key=new_id("src"),
            weight=-0.1,
            rationale="invalid",
            set_by=SYS,
            set_at=_now(),
        )

    assert "TrustConfigInvalid" in ALL_ERROR_CODES


async def test_trust_reliability_provenance() -> None:
    registry = InMemorySourceReliabilityRegistry()
    source_id = new_id("src")
    set_at = _now()
    source_entry = SourceReliability(
        key=source_id,
        weight=0.92,
        rationale="vendor API has signed responses",
        set_by=SYS,
        set_at=set_at,
        version=3,
    )
    method_entry = SourceReliability(
        key="method:heuristic_scan",
        weight=0.61,
        rationale="heuristic needs corroboration",
        set_by=SYS,
        set_at=set_at,
        version=2,
    )

    saved_source = await registry.set(source_entry)
    await registry.set(method_entry)
    by_source = await registry.get(source_id=source_id)
    by_method = await registry.get(method="heuristic_scan")
    listed = await registry.list()

    assert saved_source == source_entry
    assert by_source == source_entry
    assert by_method == method_entry
    assert by_source.set_by == SYS
    assert by_source.set_at == set_at
    assert by_source.rationale == "vendor API has signed responses"
    assert by_source.version == 3
    assert [entry.key for entry in listed] == sorted(entry.key for entry in listed)


async def test_trust_unknown_source_default() -> None:
    default = SourceReliability(
        key="*",
        weight=0.42,
        rationale="fallback for uncalibrated evidence",
        set_by=SYS,
        set_at=_now(),
        version=1,
    )
    registry = InMemorySourceReliabilityRegistry(default=default)
    method_entry = SourceReliability(
        key="method:scanner",
        weight=0.77,
        rationale="scanner method calibrated",
        set_by=SYS,
        set_at=_now(),
        version=4,
    )
    await registry.set(method_entry)

    unknown = await registry.get(source_id=new_id("src"), method="unknown")
    known_method = await registry.get(source_id=new_id("src"), method="scanner")
    listed = await registry.list()

    assert unknown == default
    assert unknown.key == "*"
    assert known_method == method_entry
    assert listed[0].key == "*"
