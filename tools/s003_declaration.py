"""S-003 private criticality declaration and EA-0007 handoff.

The declaration is generated from a collected ``UnitInventoryDocument`` and is
bound to that exact discovered roster. It stays outside the repository under
ECR-0069. Only owner-declared tiers materialize mission objects; an undeclared
row creates no EA-0007 signal and remains an explicit, closable unknown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from tools.first_run import FactorReading
from tools.s003_estate import UnitInventoryDocument, ensure_private_workdir

from aqelyn.conventions import ActorRef, require_typed_id
from aqelyn.mission import MISSION_OBJECT_TYPE, MissionImpactResult, MissionView
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    NaturalKey,
    ObjectQuery,
    ObjectStore,
    SourceRef,
)
from aqelyn.vuln import FactorUnknownCause

DECLARATION_FILENAME = "criticality-declaration.json"
DECLARATION_NATURAL_KEY = "s003:criticality"
ESTATE_ASSET_KEY_LABEL = "s003_asset_key"
ESTATE_ASSET_NATURAL_KEY = "s003:estate_asset"
CRITICALITY_NOT_DECLARED = "criticality not declared"
ASSET_NOT_REGISTERED = "estate asset not registered"

CriticalityTier = Literal[1, 2, 3, "undeclared"]
DeclarationStatus = Literal["known", "unknown"]


class S003DeclarationError(RuntimeError):
    """The private declaration cannot be applied honestly."""


class CriticalityDeclarationEntry(BaseModel):
    """One discovered unit and the owner's decision, if one exists."""

    model_config = ConfigDict(extra="forbid")

    asset_key: str
    display_name: str
    criticality_tier: CriticalityTier = "undeclared"
    rationale: str | None = None

    @field_validator("asset_key", "display_name")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("declaration identity fields must not be empty")
        return value

    @field_validator("criticality_tier", mode="before")
    @classmethod
    def _tier_is_semantic(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("criticality_tier must be 1, 2, 3, or undeclared")
        return value

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("rationale must be non-empty when supplied")
        return value


class CriticalityDeclarationDocument(BaseModel):
    """Owner-editable declaration bound to a discovered unit roster."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    discovered_assets_sha256: str
    entries: list[CriticalityDeclarationEntry] = Field(default_factory=list)

    @field_validator("discovered_assets_sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        selected = value.strip().lower()
        if len(selected) != 64 or any(char not in "0123456789abcdef" for char in selected):
            raise ValueError("discovered_assets_sha256 must be a SHA-256 hex digest")
        return selected

    @model_validator(mode="after")
    def _entries_are_unique(self) -> CriticalityDeclarationDocument:
        keys = [entry.asset_key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("declaration entries must have unique asset_key values")
        return self


class MissionDeclarationOutcome(BaseModel):
    """Local per-asset result. This type must never feed the aggregate emitter."""

    model_config = ConfigDict(extra="forbid")

    factor: Literal["mission"] = "mission"
    asset_key: str
    asset_id: str | None
    status: DeclarationStatus
    criticality_tier: int | None = None
    mission_id: str | None = None
    unknown_cause: FactorUnknownCause | None = None
    reason: str

    @field_validator("asset_id", "mission_id")
    @classmethod
    def _object_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="declaration object reference")

    @field_validator("criticality_tier")
    @classmethod
    def _known_tier(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value not in (1, 2, 3)):
            raise ValueError("criticality_tier must be 1, 2, or 3")
        return value

    @field_validator("asset_key", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("declaration outcome text must not be empty")
        return value

    @model_validator(mode="after")
    def _state_is_total(self) -> MissionDeclarationOutcome:
        if self.status == "known":
            if self.asset_id is None or self.criticality_tier is None or self.mission_id is None:
                raise ValueError("known declaration requires asset, tier, and mission")
            if self.unknown_cause is not None:
                raise ValueError("known declaration cannot carry an unknown cause")
            if self.reason == CRITICALITY_NOT_DECLARED:
                raise ValueError("known declaration cannot use the undeclared reason")
        else:
            if self.criticality_tier is not None or self.mission_id is not None:
                raise ValueError("unknown declaration cannot carry a tier or mission")
            if self.unknown_cause != "input_missing":
                raise ValueError("unknown declaration requires the closable input_missing cause")
        return self


class MissionDeclarationApplication(BaseModel):
    """Local outcomes plus aggregate counts safe for operational reporting."""

    model_config = ConfigDict(extra="forbid")

    outcomes: list[MissionDeclarationOutcome]
    joined: int
    declared: int
    undeclared: int
    unregistered: int

    @model_validator(mode="after")
    def _counts_match_outcomes(self) -> MissionDeclarationApplication:
        expected = {
            "joined": sum(outcome.asset_id is not None for outcome in self.outcomes),
            "declared": sum(outcome.status == "known" for outcome in self.outcomes),
            "undeclared": sum(
                outcome.reason == CRITICALITY_NOT_DECLARED for outcome in self.outcomes
            ),
            "unregistered": sum(
                outcome.reason == ASSET_NOT_REGISTERED for outcome in self.outcomes
            ),
        }
        actual = {
            "joined": self.joined,
            "declared": self.declared,
            "undeclared": self.undeclared,
            "unregistered": self.unregistered,
        }
        if actual != expected:
            raise ValueError("declaration aggregate counts do not match outcomes")
        return self

    def aggregate(self) -> dict[str, int]:
        """Return counts only; per-asset declaration detail cannot cross this API."""

        return {
            "joined": self.joined,
            "declared": self.declared,
            "undeclared": self.undeclared,
            "unregistered": self.unregistered,
        }


def mission_factor_readings(
    application: MissionDeclarationApplication,
) -> list[FactorReading]:
    """Translate U2 outcomes to the shared count-only factor vocabulary."""

    return [
        FactorReading(
            name="mission",
            status=outcome.status,
            reason=("owner criticality declared" if outcome.status == "known" else outcome.reason),
            source=(
                "s003:mission:declared" if outcome.status == "known" else "s003:mission:missing"
            ),
            unknown_cause=outcome.unknown_cause,
        )
        for outcome in application.outcomes
    ]


class MissionOwner(Protocol):
    async def criticality_of(self, mission_id: str) -> MissionView: ...

    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


def discovered_roster_sha256(inventory: UnitInventoryDocument) -> str:
    """Hash the discovered identities, excluding mutable runtime observations."""

    roster = [
        {
            "asset_key": unit.asset_key,
            "kind": unit.kind,
            "native_id": unit.native_id,
        }
        for unit in sorted(inventory.units, key=lambda item: item.asset_key)
    ]
    encoded = json.dumps(roster, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def prepare_declaration(
    inventory: UnitInventoryDocument,
    *,
    generated_at: datetime | None = None,
) -> CriticalityDeclarationDocument:
    """Build the owner-editable declaration only after unit discovery."""

    keys = [unit.asset_key for unit in inventory.units]
    if len(keys) != len(set(keys)):
        raise S003DeclarationError("discovered unit inventory contains duplicate asset keys")
    return CriticalityDeclarationDocument(
        generated_at=generated_at or datetime.now(UTC),
        discovered_assets_sha256=discovered_roster_sha256(inventory),
        entries=[
            CriticalityDeclarationEntry(
                asset_key=unit.asset_key,
                display_name=unit.display_name,
            )
            for unit in sorted(inventory.units, key=lambda item: item.asset_key)
        ],
    )


def validate_declaration(
    declaration: CriticalityDeclarationDocument,
    inventory: UnitInventoryDocument,
) -> None:
    """Refuse a declaration that was not made against this discovered roster."""

    if declaration.discovered_assets_sha256 != discovered_roster_sha256(inventory):
        raise S003DeclarationError("declaration was not made against this discovered unit roster")
    discovered = {unit.asset_key for unit in inventory.units}
    declared = {entry.asset_key for entry in declaration.entries}
    if declared != discovered:
        raise S003DeclarationError(
            "declaration roster differs from discovery "
            f"(missing={len(discovered - declared)}, extra={len(declared - discovered)})"
        )


def write_declaration_template(
    inventory_path: Path,
    output_path: Path,
) -> CriticalityDeclarationDocument:
    """Write one private owner-editable template without overwriting a decision."""

    selected_inventory = inventory_path.expanduser().resolve()
    selected_output = output_path.expanduser().resolve()
    ensure_private_workdir(selected_inventory.parent)
    ensure_private_workdir(selected_output.parent)
    if selected_output.exists():
        raise S003DeclarationError("criticality declaration already exists; refusing overwrite")
    inventory = UnitInventoryDocument.model_validate_json(
        selected_inventory.read_text(encoding="utf-8")
    )
    declaration = prepare_declaration(inventory)
    with selected_output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(declaration.model_dump_json(indent=2))
        handle.write("\n")
    with suppress(OSError):
        os.chmod(selected_output, 0o600)
    return declaration


def load_declaration(
    inventory_path: Path,
    declaration_path: Path,
) -> tuple[UnitInventoryDocument, CriticalityDeclarationDocument]:
    ensure_private_workdir(inventory_path.expanduser().resolve().parent)
    ensure_private_workdir(declaration_path.expanduser().resolve().parent)
    inventory = UnitInventoryDocument.model_validate_json(
        inventory_path.expanduser().resolve().read_text(encoding="utf-8")
    )
    declaration = CriticalityDeclarationDocument.model_validate_json(
        declaration_path.expanduser().resolve().read_text(encoding="utf-8")
    )
    validate_declaration(declaration, inventory)
    return inventory, declaration


async def apply_declaration(
    declaration: CriticalityDeclarationDocument,
    inventory: UnitInventoryDocument,
    *,
    asset_ids_by_key: Mapping[str, str],
    object_store: ObjectStore,
    mission_owner: MissionOwner,
    tenant_id: str | None,
    source_id: str,
    actor: ActorRef,
) -> MissionDeclarationApplication:
    """Bind declared assets to the real EA-0007 owner.

    The declaration-to-asset join is checked before any write. Undeclared assets
    create no mission object. A previously materialized declaration cannot be
    silently changed back to undeclared while its relationship remains active;
    that transition refuses until an owner-controlled lifecycle path exists.
    """

    validate_declaration(declaration, inventory)
    bindings = await _preflight_bindings(
        declaration,
        asset_ids_by_key=asset_ids_by_key,
        object_store=object_store,
        tenant_id=tenant_id,
    )
    source = SourceRef(
        source_id=source_id,
        observed_at=declaration.generated_at,
        method="S-003 owner criticality declaration",
    )
    outcomes: list[MissionDeclarationOutcome] = []
    for entry in declaration.entries:
        binding = bindings[entry.asset_key]
        if binding is None:
            outcomes.append(
                MissionDeclarationOutcome(
                    asset_key=entry.asset_key,
                    asset_id=None,
                    status="unknown",
                    unknown_cause="input_missing",
                    reason=ASSET_NOT_REGISTERED,
                )
            )
            continue
        asset, existing_mission = binding
        if entry.criticality_tier == "undeclared":
            outcomes.append(
                MissionDeclarationOutcome(
                    asset_key=entry.asset_key,
                    asset_id=asset.id,
                    status="unknown",
                    unknown_cause="input_missing",
                    reason=CRITICALITY_NOT_DECLARED,
                )
            )
            continue

        mission = await object_store.upsert(
            _mission_object(
                entry,
                tenant_id=tenant_id,
                source=source,
                actor=actor,
                existing_id=None if existing_mission is None else existing_mission.id,
            )
        )
        await _ensure_dependency(
            object_store,
            mission=mission,
            asset=asset,
            source=source,
            actor=actor,
        )
        view = await mission_owner.criticality_of(mission.id)
        impact = await mission_owner.mission_impact(asset.id)
        if (
            view.used_default_tier
            or view.criticality_tier != entry.criticality_tier
            or not any(item.mission.id == mission.id for item in impact.impacts)
        ):
            raise S003DeclarationError("EA-0007 did not return the declared criticality")
        outcomes.append(
            MissionDeclarationOutcome(
                asset_key=entry.asset_key,
                asset_id=asset.id,
                status="known",
                criticality_tier=entry.criticality_tier,
                mission_id=mission.id,
                reason=view.reason,
            )
        )

    return MissionDeclarationApplication(
        outcomes=outcomes,
        joined=sum(outcome.asset_id is not None for outcome in outcomes),
        declared=sum(outcome.status == "known" for outcome in outcomes),
        undeclared=sum(outcome.reason == CRITICALITY_NOT_DECLARED for outcome in outcomes),
        unregistered=sum(outcome.reason == ASSET_NOT_REGISTERED for outcome in outcomes),
    )


async def _preflight_bindings(
    declaration: CriticalityDeclarationDocument,
    *,
    asset_ids_by_key: Mapping[str, str],
    object_store: ObjectStore,
    tenant_id: str | None,
) -> dict[str, tuple[AQObject, AQObject | None] | None]:
    bindings: dict[str, tuple[AQObject, AQObject | None] | None] = {}
    for entry in declaration.entries:
        existing_mission = await _mission_for_asset(
            object_store,
            asset_key=entry.asset_key,
            tenant_id=tenant_id,
        )
        raw_asset_id = asset_ids_by_key.get(entry.asset_key)
        if raw_asset_id is None:
            if existing_mission is not None:
                raise S003DeclarationError(
                    "a prior mission exists for an asset missing from the current join"
                )
            bindings[entry.asset_key] = None
            continue
        try:
            asset_id = require_typed_id(raw_asset_id, "obj", field="estate asset id")
        except Exception as exc:
            raise S003DeclarationError("declaration join contains an invalid asset id") from exc
        asset = await object_store.get(asset_id, resolve_merged=False)
        if asset is None:
            if existing_mission is not None:
                raise S003DeclarationError(
                    "a prior mission exists for an asset missing from the object store"
                )
            bindings[entry.asset_key] = None
            continue
        if asset.tenant_id != tenant_id:
            raise S003DeclarationError("declaration join crosses a tenant boundary")
        if not _asset_carries_key(asset, entry.asset_key):
            raise S003DeclarationError("declaration join does not bind to the named estate asset")
        if existing_mission is not None:
            dependencies = await object_store.relationships(
                existing_mission.id,
                direction="out",
                relation_type="depends_on",
            )
            if any(relation.to_id != asset.id for relation in dependencies):
                raise S003DeclarationError("prior declaration is bound to a different estate asset")
            if entry.criticality_tier == "undeclared":
                raise S003DeclarationError(
                    "declared criticality cannot become undeclared while its mission is active"
                )
        bindings[entry.asset_key] = (asset, existing_mission)
    return bindings


async def _mission_for_asset(
    object_store: ObjectStore,
    *,
    asset_key: str,
    tenant_id: str | None,
) -> AQObject | None:
    rows, cursor = await object_store.query(
        ObjectQuery(
            tenant_id=tenant_id,
            object_type=MISSION_OBJECT_TYPE,
            natural_key=NaturalKey(namespace=DECLARATION_NATURAL_KEY, value=asset_key),
            limit=1,
        )
    )
    if cursor is not None or len(rows) > 1:
        raise S003DeclarationError("criticality natural key resolved ambiguously")
    return rows[0] if rows else None


def _asset_carries_key(asset: AQObject, asset_key: str) -> bool:
    if asset.labels.get(ESTATE_ASSET_KEY_LABEL) == asset_key:
        return True
    return any(
        natural_key.namespace == ESTATE_ASSET_NATURAL_KEY and natural_key.value == asset_key
        for natural_key in asset.natural_keys
    )


def _mission_object(
    entry: CriticalityDeclarationEntry,
    *,
    tenant_id: str | None,
    source: SourceRef,
    actor: ActorRef,
    existing_id: str | None,
) -> AQObject:
    if entry.criticality_tier == "undeclared":
        raise S003DeclarationError("undeclared criticality cannot materialize a mission")
    now = source.observed_at
    return AQObject(
        id=existing_id or "",
        object_type=MISSION_OBJECT_TYPE,
        schema_version=1,
        tenant_id=tenant_id,
        display_name=f"Owner-declared continuity: {entry.display_name}",
        attributes={
            "criticality_tier": entry.criticality_tier,
            "declared_asset_key": entry.asset_key,
            **({"rationale": entry.rationale} if entry.rationale is not None else {}),
        },
        labels={ESTATE_ASSET_KEY_LABEL: entry.asset_key, "module": "S-003"},
        natural_keys=[NaturalKey(namespace=DECLARATION_NATURAL_KEY, value=entry.asset_key)],
        sources=[source],
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
    )


async def _ensure_dependency(
    object_store: ObjectStore,
    *,
    mission: AQObject,
    asset: AQObject,
    source: SourceRef,
    actor: ActorRef,
) -> None:
    existing = await object_store.relationships(
        mission.id,
        direction="out",
        relation_type="depends_on",
    )
    if any(relation.to_id == asset.id for relation in existing):
        return
    await object_store.relate(
        AQRelationship(
            id="",
            tenant_id=mission.tenant_id,
            from_id=mission.id,
            to_id=asset.id,
            relation_type="depends_on",
            attributes={"basis": "owner_criticality_declaration"},
            sources=[source],
            created_at=source.observed_at,
            updated_at=source.observed_at,
            created_by=actor,
            updated_by=actor,
        )
    )


def _aggregate_declaration(declaration: CriticalityDeclarationDocument) -> dict[str, int]:
    declared = sum(entry.criticality_tier != "undeclared" for entry in declaration.entries)
    return {
        "assets": len(declaration.entries),
        "declared": declared,
        "undeclared": len(declaration.entries) - declared,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or validate an S-003 declaration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare",
        help="Generate an owner-editable declaration from a private unit inventory",
    )
    prepare.add_argument("--unit-inventory", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser(
        "validate",
        help="Validate a private declaration and print aggregate counts only",
    )
    validate.add_argument("--unit-inventory", type=Path, required=True)
    validate.add_argument("--declaration", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "prepare":
        declaration = write_declaration_template(args.unit_inventory, args.output)
    else:
        _, declaration = load_declaration(args.unit_inventory, args.declaration)
    print(json.dumps(_aggregate_declaration(declaration), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
