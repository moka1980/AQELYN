"""E1 acceptance tests for Exposure models and the no-scan boundary."""

from __future__ import annotations

import inspect
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import NoReturn

import pytest

import aqelyn.exposure as exposure
from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, is_valid, new_id
from aqelyn.conventions.errors import (
    ExposureBasisMissing,
    ExposureConfigInvalid,
    ScanNotPermitted,
)
from aqelyn.exposure import (
    ACTIVE_SCAN_CAPABILITY,
    AssetRef,
    AttackSurfaceAsset,
    ExposureBasis,
    ExposureConfig,
    ExposureRecord,
    ReachablePath,
    active_reachability_action_spec,
    refuse_active_reachability_collection,
)
from aqelyn.workflow import ActionSpec

NOW = datetime(2026, 7, 16, 20, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000230001"


def _asset_ref(kind: str = "asset") -> AssetRef:
    return AssetRef(kind=kind, ref_id=f"{kind}:asset-1", evidence_id=new_id("evd"))


def _basis(kind: str = "inventory") -> ExposureBasis:
    return ExposureBasis(
        kind=kind,
        ref=f"{kind}:known-record",
        as_of=NOW,
        evidence_id=new_id("evd"),
    )


def _exposure(*, reachability: str = "unknown", flagged: bool = True) -> ExposureRecord:
    return ExposureRecord(
        tenant_id=TENANT,
        asset_ref=_asset_ref(),
        exposure_type="reachable_service",
        reachability=reachability,
        basis=[_basis()],
        confidence=0.7,
        rationale="Reachability is derived from known inventory, not probing.",
        flagged=flagged,
        discovered_at=NOW,
    )


def test_exp_no_scan_surface() -> None:
    forbidden = {"scan", "probe", "connect"}

    public_callables = {
        name
        for name, value in inspect.getmembers(exposure)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & forbidden)

    for model in (AssetRef, ExposureBasis, ExposureRecord, AttackSurfaceAsset, ReachablePath):
        model_methods = {
            name
            for name, value in inspect.getmembers(model)
            if not name.startswith("_") and callable(value)
        }
        assert not (model_methods & forbidden)


def test_exp_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def blocked_socket(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("socket")
        raise AssertionError("socket use is not permitted in exposure E1")

    def blocked_create_connection(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("create_connection")
        raise AssertionError("network connection is not permitted in exposure E1")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    monkeypatch.setattr(socket, "create_connection", blocked_create_connection)

    record = _exposure()
    surface_asset = AttackSurfaceAsset(
        tenant_id=TENANT,
        asset_ref=record.asset_ref,
        classification="known_service",
        exposure_level="unknown",
        discovered_at=NOW,
        basis=record.basis,
    )
    action = active_reachability_action_spec()

    assert record.reachability == "unknown"
    assert surface_asset.exposure_level == "unknown"
    assert action.capability == ACTIVE_SCAN_CAPABILITY
    assert attempts == []


def test_exp_unknown_not_internal() -> None:
    record = _exposure()

    assert record.reachability == "unknown"
    assert record.flagged is True
    assert record.reachability != "internal"

    with pytest.raises(ExposureConfigInvalid, match="unknown reachability"):
        _exposure(reachability="unknown", flagged=False)


def test_exp_basis_required() -> None:
    with pytest.raises(ExposureBasisMissing):
        ExposureRecord(
            tenant_id=TENANT,
            asset_ref=_asset_ref(),
            exposure_type="reachable_service",
            reachability="external",
            basis=[],
            rationale="Invalid because the record cites no basis.",
            flagged=False,
            discovered_at=NOW,
        )

    with pytest.raises(ExposureBasisMissing):
        AttackSurfaceAsset(
            tenant_id=TENANT,
            asset_ref=_asset_ref(),
            classification="known_service",
            exposure_level="unknown",
            discovered_at=NOW,
            basis=[],
        )


async def test_exp_active_scan_is_actionspec() -> None:
    action = active_reachability_action_spec()

    assert isinstance(action, ActionSpec)
    assert action.capability == "scan.active"
    assert action.effect == "reversible"
    assert action.reversible is True

    with pytest.raises(ScanNotPermitted):
        await refuse_active_reachability_collection()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AssetRef(kind="host", ref_id="asset:1"),
        lambda: AssetRef(kind="asset", ref_id=""),
        lambda: ExposureBasis(kind="scan", ref="asset:1", as_of=NOW),
        lambda: ExposureBasis(kind="inventory", ref="", as_of=NOW),
        lambda: _exposure(reachability="safe", flagged=False),
        lambda: ExposureRecord(
            tenant_id=TENANT,
            asset_ref=_asset_ref(),
            exposure_type="reachable_service",
            reachability="external",
            basis=[_basis()],
            score=101.0,
            rationale="Invalid score.",
            flagged=False,
            discovered_at=NOW,
        ),
        lambda: ExposureRecord(
            tenant_id=TENANT,
            asset_ref=_asset_ref(),
            exposure_type="reachable_service",
            reachability="external",
            basis=[_basis()],
            confidence=1.1,
            rationale="Invalid confidence.",
            flagged=False,
            discovered_at=NOW,
        ),
        lambda: AttackSurfaceAsset(
            tenant_id=TENANT,
            asset_ref=_asset_ref(),
            classification="known_service",
            exposure_level="safe",
            discovered_at=NOW,
            basis=[_basis()],
        ),
        lambda: ReachablePath(target_ref="asset:1", path=[], max_work=50_000),
        lambda: ReachablePath(target_ref="asset:1", path=["asset:1"], via="scanner", max_work=1),
        lambda: ExposureConfig(max_paths=0),
        lambda: ExposureConfig(max_work=0),
        lambda: ExposureConfig(default_level="safe"),
        lambda: ExposureConfig(score_weights={}),
        lambda: ExposureConfig(score_weights={"mission": -1.0}),
    ],
)
def test_exp_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(ExposureConfigInvalid):
        factory()


def test_exp_e1_model_shapes_and_taxonomy() -> None:
    record = _exposure()
    surface_asset = AttackSurfaceAsset(
        tenant_id=TENANT,
        asset_ref=record.asset_ref,
        classification="known_service",
        exposure_level="unknown",
        discovered_at=NOW,
        basis=record.basis,
    )
    path = ReachablePath(target_ref="asset:1", path=["mission:1", "asset:1"], max_work=50_000)
    config = ExposureConfig()

    assert is_valid(record.id, "exp")
    assert is_valid(surface_asset.id, "asa")
    assert record.basis[0].kind == "inventory"
    assert record.status == "open"
    assert path.via == "graph"
    assert config.default_level == "unknown"
    assert PREFIXES["exp"] == "exposure_record"
    assert PREFIXES["asa"] == "attack_surface_asset"
    assert "ExposureConfigInvalid" in ALL_ERROR_CODES
    assert "ExposureBasisMissing" in ALL_ERROR_CODES
    assert "ExposureNotFound" in ALL_ERROR_CODES
    assert "ExposureNotReplayable" in ALL_ERROR_CODES
    assert "ScanNotPermitted" in ALL_ERROR_CODES
