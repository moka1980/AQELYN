"""N1 acceptance tests for inventory models and no-scan surface."""

from __future__ import annotations

import inspect
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import NoReturn

import pytest

import aqelyn.inventory as inventory
from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, is_valid, new_id
from aqelyn.conventions.errors import (
    AssetBasisMissing,
    AssetNotFound,
    DecommissionRequiresEvidence,
    InventoryConfigInvalid,
    InventoryUnavailable,
    SourceHealthUnknown,
)
from aqelyn.inventory import (
    AssetBasis,
    AssetRecord,
    AssetRelationship,
    ConflictCandidate,
    DiscoverySource,
    FieldConflict,
    InventoryConfig,
    InventoryReport,
    Ownership,
)

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000250001"


def _basis(kind: str = "discovery") -> AssetBasis:
    return AssetBasis(
        kind=kind,
        ref="discovery:cmdb:asset-1",
        as_of=NOW,
        evidence_id=new_id("evd"),
    )


def _asset(**overrides: object) -> AssetRecord:
    data: dict[str, object] = {
        "tenant_id": TENANT,
        "asset_type": "server",
        "discovery_source": "src:cmdb",
        "classification": "server",
        "owner": Ownership(
            business_owner="payments",
            technical_owner="platform",
            custodian="sre",
            rationale="CMDB owner fields were reconciled.",
            source_id="src:cmdb",
        ),
        "lifecycle_state": "active",
        "confidence": 0.91,
        "basis": [_basis()],
        "first_seen_at": NOW,
        "last_reported_at": NOW,
    }
    data.update(overrides)
    return AssetRecord(**data)


def test_inv_source_basis_required() -> None:
    with pytest.raises(InventoryConfigInvalid, match="must not be empty"):
        _asset(discovery_source="")

    with pytest.raises(AssetBasisMissing):
        _asset(basis=[])

    with pytest.raises(InventoryConfigInvalid):
        AssetBasis(kind="scan", ref="scanner:asset-1", as_of=NOW)


def test_inv_no_scan_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"scan", "probe", "connect"}

    public_callables = {
        name
        for name, value in inspect.getmembers(inventory)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & forbidden)

    for model in (
        AssetBasis,
        AssetRecord,
        AssetRelationship,
        ConflictCandidate,
        DiscoverySource,
        FieldConflict,
        InventoryConfig,
        InventoryReport,
        Ownership,
    ):
        model_methods = {
            name
            for name, value in inspect.getmembers(model)
            if not name.startswith("_") and callable(value)
        }
        assert not (model_methods & forbidden)

    attempts: list[str] = []

    def blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("socket")
        raise AssertionError("socket use is not permitted in inventory N1")

    def blocked_create_connection(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("create_connection")
        raise AssertionError("network connection is not permitted in inventory N1")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    monkeypatch.setattr(socket, "create_connection", blocked_create_connection)

    asset = _asset()
    source = DiscoverySource(
        source_id="src:cmdb",
        reliability=0.8,
        health="ok",
        as_of=NOW,
    )

    assert asset.discovery_source == "src:cmdb"
    assert source.health == "ok"
    assert attempts == []


@pytest.mark.parametrize(
    "factory",
    [
        lambda: DiscoverySource(source_id="", reliability=0.8, health="ok", as_of=NOW),
        lambda: DiscoverySource(source_id="src:cmdb", reliability=1.1, health="ok", as_of=NOW),
        lambda: DiscoverySource(source_id="src:cmdb", reliability=0.8, health="offline", as_of=NOW),
        lambda: AssetBasis(kind="discovery", ref="", as_of=NOW),
        lambda: _asset(confidence=1.1),
        lambda: _asset(lifecycle_state="missing"),
        lambda: _asset(classification=""),
        lambda: ConflictCandidate(value="server", source_id="", reliability=0.5),
        lambda: ConflictCandidate(value="server", source_id="src:cmdb", reliability=-0.1),
        lambda: FieldConflict(field="", candidates=[], unresolved=True),
        lambda: FieldConflict(
            field="hostname",
            candidates=[ConflictCandidate(value="a", source_id="src:cmdb", reliability=0.5)],
            unresolved=True,
            resolved_by="src:cmdb",
        ),
        lambda: FieldConflict(
            field="hostname",
            candidates=[ConflictCandidate(value="a", source_id="src:cmdb", reliability=0.5)],
            unresolved=False,
        ),
        lambda: Ownership(rationale="", source_id="src:cmdb"),
        lambda: Ownership(rationale="CMDB owner.", source_id=""),
        lambda: AssetRelationship(
            tenant_id=TENANT,
            source_asset="",
            target_asset="ast:db-1",
            relationship_type="depends_on",
            confidence=0.7,
            inferred_from="graph",
        ),
        lambda: AssetRelationship(
            tenant_id=TENANT,
            source_asset="ast:web-1",
            target_asset="ast:db-1",
            relationship_type="depends_on",
            confidence=1.1,
            inferred_from="graph",
        ),
        lambda: InventoryReport(
            assets=["ast:web-1", "ast:web-1"],
            total=2,
            as_of=NOW,
            source_freshness={"src:cmdb": NOW},
        ),
        lambda: InventoryReport(assets=[], total=-1, as_of=NOW, source_freshness={}),
        lambda: InventoryReport(assets=[], total=0, as_of=NOW, source_freshness={"": NOW}),
        lambda: InventoryConfig(stale_after_days=0),
        lambda: InventoryConfig(max_relationship_work=0),
        lambda: InventoryConfig(min_source_health="unknown"),
    ],
)
def test_inv_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(InventoryConfigInvalid):
        factory()


def test_inv_n1_model_shapes_and_taxonomy() -> None:
    source = DiscoverySource(source_id="src:cmdb", reliability=0.9, health="ok", as_of=NOW)
    conflict = FieldConflict(
        field="hostname",
        candidates=[
            ConflictCandidate(value="web-1", source_id="src:cmdb", reliability=0.9),
            ConflictCandidate(value="web-01", source_id="src:edr", reliability=0.7),
        ],
        resolved_by="src:cmdb",
    )
    asset = _asset(conflicts=[conflict])
    relationship = AssetRelationship(
        tenant_id=TENANT,
        source_asset=asset.id,
        target_asset="ast:database-1",
        relationship_type="depends_on",
        confidence=0.7,
        inferred_from="graph:shared_subnet",
        evidence_id=new_id("evd"),
    )
    report = InventoryReport(
        assets=[asset.id],
        total=1,
        as_of=NOW,
        source_freshness={source.source_id: source.as_of},
    )
    config = InventoryConfig()

    assert is_valid(asset.id, "ast")
    assert is_valid(relationship.id, "arl")
    assert asset.lifecycle_state == "active"
    assert asset.basis[0].kind == "discovery"
    assert asset.conflicts[0].resolved_by == "src:cmdb"
    assert relationship.confidence == 0.7
    assert report.total == 1
    assert report.degraded is False
    assert config.min_source_health == "ok"

    assert PREFIXES["ast"] == "asset_record"
    assert PREFIXES["arl"] == "asset_relationship"
    assert "InventoryConfigInvalid" in ALL_ERROR_CODES
    assert "AssetBasisMissing" in ALL_ERROR_CODES
    assert "AssetNotFound" in ALL_ERROR_CODES
    assert "InventoryUnavailable" in ALL_ERROR_CODES
    assert "SourceHealthUnknown" in ALL_ERROR_CODES
    assert "DecommissionRequiresEvidence" in ALL_ERROR_CODES

    for error in (
        InventoryConfigInvalid,
        AssetBasisMissing,
        AssetNotFound,
        InventoryUnavailable,
        SourceHealthUnknown,
        DecommissionRequiresEvidence,
    ):
        assert error.code in ALL_ERROR_CODES
