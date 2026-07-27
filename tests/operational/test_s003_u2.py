"""S-003 U2 acceptance tests for the private criticality declaration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError
from tools.s003_declaration import (
    ASSET_NOT_REGISTERED,
    CRITICALITY_NOT_DECLARED,
    DECLARATION_NATURAL_KEY,
    ESTATE_ASSET_KEY_LABEL,
    ESTATE_ASSET_NATURAL_KEY,
    CriticalityDeclarationDocument,
    MissionDeclarationApplication,
    MissionDeclarationOutcome,
    S003DeclarationError,
    _main,
    apply_declaration,
    discovered_roster_sha256,
    prepare_declaration,
    validate_declaration,
    write_declaration_template,
)
from tools.s003_estate import (
    S003CollectionError,
    UnitInventoryDocument,
    UnitRecord,
    canonical_asset_key,
)

from aqelyn.conventions import ActorRef, new_id
from aqelyn.graph import InMemoryKnowledgeGraph, PostgresKnowledgeGraph
from aqelyn.mission import MISSION_OBJECT_TYPE, MissionEngine
from aqelyn.objects import (
    AQObject,
    InMemoryObjectStore,
    NaturalKey,
    ObjectQuery,
    ObjectStore,
    SourceRef,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000003003"
NOW = datetime(2026, 7, 27, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="s003-owner")

MATRIX = [
    pytest.param("memory", "local", id="memory-local"),
    pytest.param("memory", "enterprise", id="memory-enterprise"),
    pytest.param("postgres", "local", id="postgres-local"),
    pytest.param("postgres", "enterprise", id="postgres-enterprise"),
]


class _Harness:
    def __init__(
        self,
        store: ObjectStore,
        mission: MissionEngine,
        *,
        tenant_id: str | None,
    ) -> None:
        self.store = store
        self.mission = mission
        self.tenant_id = tenant_id


@asynccontextmanager
async def _harness(backend: str, tenant_mode: str) -> AsyncIterator[_Harness]:
    tenant_id = None if tenant_mode == "local" else TENANT
    if backend == "memory":
        memory = InMemoryObjectStore(mode=tenant_mode)
        memory.registry.register(MISSION_OBJECT_TYPE, 1, None)
        yield _Harness(
            memory,
            MissionEngine(memory, InMemoryKnowledgeGraph(memory)),
            tenant_id=tenant_id,
        )
        return

    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.objects.postgres import PostgresObjectStore

    postgres = await PostgresObjectStore.connect(PG_URL, mode=tenant_mode)
    async with postgres._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    postgres.registry.register(MISSION_OBJECT_TYPE, 1, None)
    try:
        yield _Harness(
            postgres,
            MissionEngine(postgres, PostgresKnowledgeGraph(postgres._pool)),
            tenant_id=tenant_id,
        )
    finally:
        await postgres.close()


def _unit(native_id: str, display_name: str) -> UnitRecord:
    return UnitRecord(
        asset_key=canonical_asset_key("systemd_unit", native_id),
        native_id=native_id,
        display_name=display_name,
        load_state="loaded",
        active_state="active",
        sub_state="running",
    )


def _inventory(*units: UnitRecord) -> UnitInventoryDocument:
    return UnitInventoryDocument(collected_at=NOW, units=list(units))


def _with_tier(
    declaration: CriticalityDeclarationDocument,
    *,
    asset_key: str,
    tier: int | str,
    rationale: str | None = None,
) -> CriticalityDeclarationDocument:
    payload = declaration.model_dump(mode="json")
    for entry in cast(list[dict[str, Any]], payload["entries"]):
        if entry["asset_key"] == asset_key:
            entry["criticality_tier"] = tier
            entry["rationale"] = rationale
    return CriticalityDeclarationDocument.model_validate(payload)


def _source() -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        observed_at=NOW,
        method="S-003 U2 acceptance",
    )


async def _asset(
    harness: _Harness,
    unit: UnitRecord,
    *,
    carry_key: bool = True,
) -> AQObject:
    labels = {ESTATE_ASSET_KEY_LABEL: unit.asset_key} if carry_key else {}
    natural_keys = (
        [NaturalKey(namespace=ESTATE_ASSET_NATURAL_KEY, value=unit.asset_key)] if carry_key else []
    )
    return await harness.store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            tenant_id=harness.tenant_id,
            display_name=unit.display_name,
            labels=labels,
            natural_keys=natural_keys,
            sources=[_source()],
            first_seen_at=NOW,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            created_by=ACTOR,
            updated_by=ACTOR,
        )
    )


async def _mission_rows(harness: _Harness) -> list[AQObject]:
    rows, cursor = await harness.store.query(
        ObjectQuery(
            tenant_id=harness.tenant_id,
            object_type=MISSION_OBJECT_TYPE,
            limit=100,
        )
    )
    assert cursor is None
    return rows


async def test_s003_undeclared_is_unknown() -> None:
    unit = _unit("alpha.service", "Alpha service")
    inventory = _inventory(unit)
    declaration = prepare_declaration(inventory, generated_at=NOW)
    assert declaration.entries[0].criticality_tier == "undeclared"

    async with _harness("memory", "local") as harness:
        asset = await _asset(harness, unit)
        result = await apply_declaration(
            declaration,
            inventory,
            asset_ids_by_key={unit.asset_key: asset.id},
            object_store=harness.store,
            mission_owner=harness.mission,
            tenant_id=harness.tenant_id,
            source_id=new_id("src"),
            actor=ACTOR,
        )

        outcome = result.outcomes[0]
        assert outcome.status == "unknown"
        assert outcome.factor == "mission"
        assert outcome.unknown_cause == "input_missing"
        assert outcome.reason == CRITICALITY_NOT_DECLARED
        assert outcome.criticality_tier is None
        assert outcome.mission_id is None
        assert result.aggregate() == {
            "joined": 1,
            "declared": 0,
            "undeclared": 1,
            "unregistered": 0,
        }
        assert await _mission_rows(harness) == []
        assert (await harness.mission.mission_impact(asset.id)).impacts == []


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_s003_partial_declaration_honest(backend: str, tenant_mode: str) -> None:
    alpha = _unit("alpha.service", "Alpha service")
    beta = _unit("beta.service", "Beta service")
    inventory = _inventory(alpha, beta)
    declaration = _with_tier(
        prepare_declaration(inventory, generated_at=NOW),
        asset_key=alpha.asset_key,
        tier=1,
        rationale="Owner-verified material service.",
    )

    async with _harness(backend, tenant_mode) as harness:
        alpha_asset = await _asset(harness, alpha)
        beta_asset = await _asset(harness, beta)
        result = await apply_declaration(
            declaration,
            inventory,
            asset_ids_by_key={
                alpha.asset_key: alpha_asset.id,
                beta.asset_key: beta_asset.id,
            },
            object_store=harness.store,
            mission_owner=harness.mission,
            tenant_id=harness.tenant_id,
            source_id=new_id("src"),
            actor=ACTOR,
        )

        assert result.aggregate() == {
            "joined": 2,
            "declared": 1,
            "undeclared": 1,
            "unregistered": 0,
        }
        declared = next(item for item in result.outcomes if item.asset_key == alpha.asset_key)
        undecided = next(item for item in result.outcomes if item.asset_key == beta.asset_key)
        assert declared.status == "known"
        assert declared.criticality_tier == 1
        assert declared.mission_id is not None
        assert undecided.status == "unknown"
        assert undecided.reason == CRITICALITY_NOT_DECLARED

        alpha_impact = await harness.mission.mission_impact(alpha_asset.id)
        beta_impact = await harness.mission.mission_impact(beta_asset.id)
        assert len(alpha_impact.impacts) == 1
        assert alpha_impact.impacts[0].mission.id == declared.mission_id
        assert alpha_impact.impacts[0].mission.criticality_tier == 1
        assert alpha_impact.impacts[0].mission.used_default_tier is False
        assert beta_impact.impacts == []


async def test_s003_declaration_never_defaults_favourably() -> None:
    unit = _unit("alpha.service", "Alpha service")
    inventory = _inventory(unit)
    payload = prepare_declaration(inventory, generated_at=NOW).model_dump(mode="json")
    cast(list[dict[str, Any]], payload["entries"])[0].pop("criticality_tier")
    omitted = CriticalityDeclarationDocument.model_validate(payload)
    assert omitted.entries[0].criticality_tier == "undeclared"

    for invalid in (None, True, False, 0, 4, "1", "safe"):
        bad = omitted.model_dump(mode="json")
        cast(list[dict[str, Any]], bad["entries"])[0]["criticality_tier"] = invalid
        with pytest.raises(ValidationError):
            CriticalityDeclarationDocument.model_validate(bad)

    with pytest.raises(ValidationError):
        MissionDeclarationOutcome(
            asset_key=unit.asset_key,
            asset_id=None,
            status="known",
            reason="looks known",
        )
    with pytest.raises(ValidationError):
        MissionDeclarationOutcome(
            asset_key=unit.asset_key,
            asset_id=None,
            status="unknown",
            criticality_tier=3,
            unknown_cause="input_missing",
            reason=CRITICALITY_NOT_DECLARED,
        )


async def test_s003_declaration_join_is_explicit_and_checked_before_writes() -> None:
    unit = _unit("alpha.service", "Alpha service")
    inventory = _inventory(unit)
    declaration = _with_tier(
        prepare_declaration(inventory, generated_at=NOW),
        asset_key=unit.asset_key,
        tier=2,
    )
    async with _harness("memory", "local") as harness:
        unregistered = await apply_declaration(
            declaration,
            inventory,
            asset_ids_by_key={},
            object_store=harness.store,
            mission_owner=harness.mission,
            tenant_id=None,
            source_id=new_id("src"),
            actor=ACTOR,
        )
        assert unregistered.outcomes[0].reason == ASSET_NOT_REGISTERED
        assert unregistered.aggregate()["unregistered"] == 1
        assert await _mission_rows(harness) == []

        wrong_asset = await _asset(harness, unit, carry_key=False)
        with pytest.raises(S003DeclarationError, match="does not bind"):
            await apply_declaration(
                declaration,
                inventory,
                asset_ids_by_key={unit.asset_key: wrong_asset.id},
                object_store=harness.store,
                mission_owner=harness.mission,
                tenant_id=None,
                source_id=new_id("src"),
                actor=ACTOR,
            )
        assert await _mission_rows(harness) == []


async def test_s003_declared_handoff_is_idempotent_and_cannot_decay_to_unknown() -> None:
    unit = _unit("alpha.service", "Alpha service")
    inventory = _inventory(unit)
    declaration = _with_tier(
        prepare_declaration(inventory, generated_at=NOW),
        asset_key=unit.asset_key,
        tier=2,
    )
    async with _harness("memory", "local") as harness:
        asset = await _asset(harness, unit)

        async def apply(
            selected: CriticalityDeclarationDocument,
        ) -> MissionDeclarationApplication:
            return await apply_declaration(
                selected,
                inventory,
                asset_ids_by_key={unit.asset_key: asset.id},
                object_store=harness.store,
                mission_owner=harness.mission,
                tenant_id=None,
                source_id=new_id("src"),
                actor=ACTOR,
            )

        first = await apply(declaration)
        second = await apply(declaration)
        assert first.outcomes[0].mission_id == second.outcomes[0].mission_id
        missions = await _mission_rows(harness)
        assert len(missions) == 1
        relationships = await harness.store.relationships(
            missions[0].id,
            direction="out",
            relation_type="depends_on",
        )
        assert len(relationships) == 1

        cleared = prepare_declaration(inventory, generated_at=NOW)
        with pytest.raises(S003DeclarationError, match="cannot become undeclared"):
            await apply(cleared)


def test_s003_declaration_is_bound_to_discovery() -> None:
    alpha = _unit("alpha.service", "Alpha service")
    beta = _unit("beta.service", "Beta service")
    alpha_inventory = _inventory(alpha)
    declaration = prepare_declaration(alpha_inventory, generated_at=NOW)
    assert declaration.discovered_assets_sha256 == discovered_roster_sha256(alpha_inventory)

    with pytest.raises(S003DeclarationError, match="not made against"):
        validate_declaration(declaration, _inventory(alpha, beta))

    missing = declaration.model_dump(mode="json")
    missing["entries"] = []
    with pytest.raises(S003DeclarationError, match=r"missing=1, extra=0"):
        validate_declaration(
            CriticalityDeclarationDocument.model_validate(missing),
            alpha_inventory,
        )


def test_s003_declaration_digest_binds_native_identity() -> None:
    alpha = _unit("alpha.service", "Alpha service")
    inventory = _inventory(alpha)
    declaration = prepare_declaration(inventory, generated_at=NOW)
    relabelled_native_id = alpha.model_copy(update={"native_id": "renamed.service"})
    with pytest.raises(S003DeclarationError, match="not made against"):
        validate_declaration(declaration, _inventory(relabelled_native_id))


def test_s003_private_template_and_cli_emit_counts_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    inventory_path = private / "unit-inventory.json"
    declaration_path = private / "criticality-declaration.json"
    inventory = _inventory(_unit("alpha.service", "Confidential service name"))
    inventory_path.write_text(inventory.model_dump_json(indent=2), encoding="utf-8")

    written = write_declaration_template(inventory_path, declaration_path)
    assert written.entries[0].criticality_tier == "undeclared"
    with pytest.raises(S003DeclarationError, match="refusing overwrite"):
        write_declaration_template(inventory_path, declaration_path)

    assert (
        _main(
            [
                "validate",
                "--unit-inventory",
                str(inventory_path),
                "--declaration",
                str(declaration_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out.strip()
    assert json.loads(output) == {"assets": 1, "declared": 0, "undeclared": 1}
    assert "Confidential" not in output
    assert "alpha.service" not in output


def test_s003_declaration_refuses_repository_input(tmp_path: Path) -> None:
    with pytest.raises(S003CollectionError, match="outside the repository"):
        write_declaration_template(
            ROOT / "pyproject.toml",
            tmp_path / "private" / "criticality-declaration.json",
        )


def test_s003_declaration_guards_survive_python_o() -> None:
    script = """
from datetime import UTC, datetime
from pydantic import ValidationError
from tools.s003_declaration import (
    CRITICALITY_NOT_DECLARED,
    CriticalityDeclarationDocument,
    MissionDeclarationOutcome,
    prepare_declaration,
)
from tools.s003_estate import UnitInventoryDocument, UnitRecord, canonical_asset_key

now = datetime(2026, 7, 27, tzinfo=UTC)
unit = UnitRecord(
    asset_key=canonical_asset_key("systemd_unit", "alpha.service"),
    native_id="alpha.service",
    display_name="Alpha",
    load_state="loaded",
    active_state="active",
    sub_state="running",
)
document = prepare_declaration(
    UnitInventoryDocument(collected_at=now, units=[unit]),
    generated_at=now,
)
if document.entries[0].criticality_tier != "undeclared":
    raise SystemExit("omitted declaration defaulted favourably")
try:
    MissionDeclarationOutcome(
        asset_key=unit.asset_key,
        asset_id=None,
        status="unknown",
        criticality_tier=3,
        unknown_cause="input_missing",
        reason=CRITICALITY_NOT_DECLARED,
    )
except ValidationError:
    pass
else:
    raise SystemExit("unknown declaration carried a favourable tier")
payload = document.model_dump(mode="json")
payload["entries"][0]["criticality_tier"] = True
try:
    CriticalityDeclarationDocument.model_validate(payload)
except ValidationError:
    pass
else:
    raise SystemExit("boolean declaration tier was accepted")
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_s003_declaration_natural_key_is_not_an_asset_identity() -> None:
    assert DECLARATION_NATURAL_KEY != ESTATE_ASSET_NATURAL_KEY
