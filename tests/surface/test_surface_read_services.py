"""ECR-0089 owner read contracts and composite keyset controls."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from aqelyn.conventions.errors import SchemaValidationError
from aqelyn.conventions.ids import new_id
from aqelyn.exposure import AssetRef, ExposureBasis, ExposureRecord
from aqelyn.exposure.read import ExposureReadService
from aqelyn.ispm.read import ISPMReadService
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime
from aqelyn.secrets import SecretAsset, SecretLocation
from aqelyn.secrets.read import SecretsReadService
from aqelyn.supplychain import SoftwareComponent
from aqelyn.supplychain.read import SupplyChainReadService

NOW = datetime(2026, 8, 2, tzinfo=UTC)


@dataclass(frozen=True)
class _Record:
    id: str


class _Engine:
    def explain(self, record: _Record) -> dict[str, object]:
        return {"record_id": record.id, "reason": "owner derivation"}


class _ISPMStore:
    def __init__(self) -> None:
        self.afters: list[tuple[str, str] | None] = []
        self.record = _Record("ips_019fa1f100007a119000000000000001")

    async def query_scores_for_read(
        self, *, tenant_id: str | None, after: tuple[str, str] | None = None, limit: int = 100
    ) -> tuple[list[_Record], tuple[str, str] | None]:
        assert tenant_id is None
        assert limit > 0
        self.afters.append(after)
        return [self.record], (
            "obj_019fa1f100007a119000000000000001",
            self.record.id,
        )

    async def get_score(self, score_id: str, *, tenant_id: str | None) -> _Record | None:
        return self.record if score_id == self.record.id and tenant_id is None else None


class _ExposureStore:
    def __init__(self) -> None:
        self.afters: list[tuple[datetime, str] | None] = []
        self.record = _Record("exp_019fa1f100007a119000000000000001")

    async def query_for_read(
        self,
        *,
        tenant_id: str | None,
        after: tuple[datetime, str] | None = None,
        limit: int = 100,
    ) -> tuple[list[_Record], tuple[datetime, str] | None]:
        assert tenant_id is None
        assert limit > 0
        self.afters.append(after)
        return [self.record], (NOW, self.record.id)

    async def get(self, exposure_id: str, *, tenant_id: str | None) -> _Record | None:
        return self.record if exposure_id == self.record.id and tenant_id is None else None


class _SecretsStore:
    def __init__(self) -> None:
        self.afters: list[tuple[str, str] | None] = []
        self.record = _Record("sct_019fa1f100007a119000000000000001")

    async def query_assets_for_read(
        self, *, tenant_id: str | None, after: tuple[str, str] | None = None, limit: int = 100
    ) -> tuple[list[_Record], tuple[str, str] | None]:
        assert tenant_id is None
        assert limit > 0
        self.afters.append(after)
        return [self.record], ("secret", self.record.id)

    async def get_asset(self, asset_id: str, *, tenant_id: str | None) -> _Record | None:
        return self.record if asset_id == self.record.id and tenant_id is None else None


class _SupplyChainStore:
    def __init__(self) -> None:
        self.afters: list[tuple[str, str] | None] = []
        self.record = _Record("obj_019fa1f100007a119000000000000002")

    async def query_components_for_read(
        self, *, tenant_id: str | None, after: tuple[str, str] | None = None, limit: int = 100
    ) -> tuple[list[_Record], tuple[str, str] | None]:
        assert tenant_id is None
        assert limit > 0
        self.afters.append(after)
        return [self.record], ("verified", self.record.id)

    async def get_component_by_object_id(
        self, object_id: str, *, tenant_id: str | None
    ) -> _Record | None:
        return self.record if object_id == self.record.id and tenant_id is None else None


@pytest.mark.parametrize(
    ("service_type", "allowed_reads"),
    [
        (ISPMReadService, {"list_postures", "get_posture"}),
        (ExposureReadService, {"list_exposures", "get_exposure"}),
        (SecretsReadService, {"list_assets", "get_asset"}),
        (SupplyChainReadService, {"list_components", "get_component"}),
    ],
)
def test_owner_read_services_expose_only_lifecycle_and_enumerated_reads(
    service_type: type[object],
    allowed_reads: set[str],
) -> None:
    public_methods = {
        name
        for name, member in inspect.getmembers(service_type, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {"start", "stop", "health"} | allowed_reads
    forbidden = ("ingest", "raise", "propose", "decommission", "transition", "assign", "treat")
    assert not [name for name in public_methods if any(word in name for word in forbidden)]


async def test_each_owner_cursor_round_trips_its_complete_composite_key() -> None:
    ispm_store = _ISPMStore()
    exposure_store = _ExposureStore()
    secrets_store = _SecretsStore()
    supplychain_store = _SupplyChainStore()
    engine = _Engine()
    services = [
        (
            ISPMReadService(cast(Any, ispm_store), cast(Any, engine), tenant_mode="local"),
            "list_postures",
            ispm_store,
        ),
        (
            ExposureReadService(cast(Any, exposure_store), tenant_mode="local"),
            "list_exposures",
            exposure_store,
        ),
        (
            SecretsReadService(cast(Any, secrets_store), cast(Any, engine), tenant_mode="local"),
            "list_assets",
            secrets_store,
        ),
        (
            SupplyChainReadService(cast(Any, supplychain_store), tenant_mode="local"),
            "list_components",
            supplychain_store,
        ),
    ]

    for service, method_name, store in services:
        method = cast(Any, getattr(service, method_name))
        first = await method(tenant_id=None, limit=1, cursor=None)
        await method(tenant_id=None, limit=1, cursor=first.next_cursor)
        afters = cast(Any, store).afters
        assert afters[0] is None
        assert afters[1] is not None
        assert len(afters[1]) == 2


async def test_composite_cursor_is_owner_scoped() -> None:
    ispm = ISPMReadService(cast(Any, _ISPMStore()), cast(Any, _Engine()), tenant_mode="local")
    exposure = ExposureReadService(cast(Any, _ExposureStore()), tenant_mode="local")
    page = await ispm.list_postures(tenant_id=None, limit=1, cursor=None)

    with pytest.raises(SchemaValidationError, match="does not belong"):
        await exposure.list_exposures(tenant_id=None, limit=1, cursor=page.next_cursor)


async def test_composite_cursor_is_tenant_scoped() -> None:
    local = ISPMReadService(cast(Any, _ISPMStore()), cast(Any, _Engine()), tenant_mode="local")
    enterprise = ISPMReadService(
        cast(Any, _ISPMStore()),
        cast(Any, _Engine()),
        tenant_mode="enterprise",
    )
    page = await local.list_postures(tenant_id=None, limit=1, cursor=None)

    with pytest.raises(SchemaValidationError, match="does not belong"):
        await enterprise.list_postures(
            tenant_id="00000000-0000-0000-0000-000000000001",
            limit=1,
            cursor=page.next_cursor,
        )


def test_factory_registers_all_four_read_services_in_both_tenant_modes() -> None:
    local = create_inmemory_runtime(AQELYNConfig(tenant_mode="local"))
    enterprise = create_inmemory_runtime(AQELYNConfig(tenant_mode="enterprise"))
    expected = {"ispm_read", "exposure_read", "secrets_read", "supplychain_read"}

    assert expected <= set(local.kernel._services)
    assert set(local.kernel._services) == set(enterprise.kernel._services)
    assert local.ispm_read_service is local.kernel.get_service("ispm_read")
    assert local.exposure_read_service is local.kernel.get_service("exposure_read")
    assert local.secrets_read_service is local.kernel.get_service("secrets_read")
    assert local.supplychain_read_service is local.kernel.get_service("supplychain_read")


async def test_real_owner_stores_page_without_skip_or_duplicate_and_detail_round_trips() -> None:
    runtime = create_inmemory_runtime(AQELYNConfig(tenant_mode="local"))
    exposure_ids: list[str] = []
    secret_ids: list[str] = []
    component_ids: list[str] = []
    component_keys: list[tuple[str, str]] = []
    for index in range(2):
        exposure = _exposure(index)
        secret = _secret(index)
        component = _component(index)
        exposure_ids.append((await runtime.exposure_store.put(exposure)).id)
        secret_ids.append((await runtime.secrets_store.put_asset(secret)).id)
        stored_component = await runtime.supplychain_store.put_component(component)
        component_ids.append(stored_component.object_id)
        component_keys.append((stored_component.provenance_status, stored_component.object_id))

    async def collect(
        service: object,
        method_name: str,
        *,
        identifier: str = "id",
    ) -> list[str]:
        cursor: str | None = None
        seen: list[str] = []
        while True:
            page = await cast(Any, getattr(service, method_name))(
                tenant_id=None,
                limit=1,
                cursor=cursor,
            )
            record = page.items[0].record
            seen.append(cast(str, getattr(record, identifier)))
            cursor = page.next_cursor
            if cursor is None:
                return seen

    assert await collect(runtime.exposure_read_service, "list_exposures") == exposure_ids
    assert await collect(runtime.secrets_read_service, "list_assets") == sorted(secret_ids)
    assert await collect(
        runtime.supplychain_read_service,
        "list_components",
        identifier="object_id",
    ) == [object_id for _provenance, object_id in sorted(component_keys)]
    assert (
        await runtime.exposure_read_service.get_exposure(exposure_ids[0], tenant_id=None)
    ) is not None
    assert await runtime.secrets_read_service.get_asset(secret_ids[0], tenant_id=None) is not None
    assert (
        await runtime.supplychain_read_service.get_component(component_ids[0], tenant_id=None)
    ) is not None


def _exposure(index: int) -> ExposureRecord:
    return ExposureRecord(
        tenant_id=None,
        asset_ref=AssetRef(kind="asset", ref_id=new_id("ast"), evidence_id=new_id("evd")),
        exposure_type="reachable_service",
        reachability="unknown",
        basis=[
            ExposureBasis(
                kind="inventory",
                ref=f"inventory:record-{index}",
                as_of=NOW + timedelta(seconds=index),
                evidence_id=new_id("evd"),
            )
        ],
        confidence=0.7,
        rationale="Reachability is derived from handed-in inventory.",
        flagged=True,
        discovered_at=NOW + timedelta(seconds=index),
    )


def _secret(index: int) -> SecretAsset:
    return SecretAsset(
        tenant_id=None,
        object_id=new_id("obj"),
        inventory_ref=new_id("ast"),
        kind="api_key",
        fingerprint=f"hmac-sha256:{index + 1:064x}",
        location=SecretLocation(kind="configuration", resource_ref=f"app://service-{index}"),
        rotation={"reason": "Not assessed."},
        claim_confidence=0.5,
        source_id=new_id("src"),
        detected_at=NOW,
        evidence_id=new_id("evd"),
    )


def _component(index: int) -> SoftwareComponent:
    return SoftwareComponent(
        object_id=new_id("obj"),
        tenant_id=None,
        identity_kind="purl",
        purl=f"pkg:pypi/component-{index}@1.0.{index}",
        name=f"component-{index}",
        version=f"1.0.{index}",
        component_type="library",
        provenance_status="unverified" if index == 0 else "verified",
        direct=True,
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )
