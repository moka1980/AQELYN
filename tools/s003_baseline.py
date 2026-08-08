"""S-003 owner baseline evaluation through EA-0012.

Owner claim text and estate values remain in the private workdir under ECR-0069.
This adapter accepts only the stable C1-C5 handles, sends resolved values through
the real EA-0012 analyzer, and returns a value-free assessment with explicit pass,
fail, and unknown buckets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.assetconfig import ACGConfig, AssetConfigAnalyzer, Baseline, Check, Comparator
from aqelyn.conventions import ActorRef
from aqelyn.objects import AQObject, NaturalKey, ObjectQuery, ObjectStore, SourceRef
from aqelyn.vuln import FactorUnknownCause
from tools.first_run import FactorReading, RoadmapDependency
from tools.s003_estate import ServiceSurfaceDocument, UnitInventoryDocument
from tools.s003_surface import classify_bind, parse_listener_observations

ClaimId = Literal["C1", "C2", "C3", "C4", "C5"]
UnknownClass = Literal["privileged_read", "collection_scope", "certificate_lifecycle"]
OutcomeStatus = Literal["pass", "fail", "unknown"]

CLAIM_IDS = frozenset(("C1", "C2", "C3", "C4", "C5"))
NO_BASELINE_DECLARED = "no approved baseline declared"
PRIVILEGED_READ_REQUIRED = "privileged read decision pending"
COLLECTION_SCOPE_INCOMPLETE = "collection scope does not provide required evidence"
CERTIFICATE_LIFECYCLE_UNKNOWN = "certificate lifecycle owner could not establish validity"

_ACTOR = ActorRef(actor_type="user", actor_id="s003-owner")
_BASELINE_TARGET_NATURAL_KEY = NaturalKey(
    namespace="s003:baseline-target",
    value="owner-declared-host",
)
_UNKNOWN_REASONS: Mapping[UnknownClass, str] = {
    "privileged_read": PRIVILEGED_READ_REQUIRED,
    "collection_scope": COLLECTION_SCOPE_INCOMPLETE,
    "certificate_lifecycle": CERTIFICATE_LIFECYCLE_UNKNOWN,
}


class S003BaselineError(RuntimeError):
    """The private baseline cannot be evaluated honestly."""


class BaselineClaim(BaseModel):
    """One private claim's comparison shape; no statement text crosses this API."""

    model_config = ConfigDict(extra="forbid")

    claim_id: ClaimId
    comparator: Comparator
    expected: Any


class BaselineDefinition(BaseModel):
    """The complete owner-approved C1-C5 baseline."""

    model_config = ConfigDict(extra="forbid")

    claims: list[BaselineClaim]

    @model_validator(mode="after")
    def _complete_claim_set(self) -> BaselineDefinition:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("baseline claim ids must be unique")
        if frozenset(claim_ids) != CLAIM_IDS:
            raise ValueError("baseline definition must contain exactly C1-C5")
        return self


class ResolvedObservation(BaseModel):
    """A value that may reach EA-0012's comparator."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["resolved"] = "resolved"
    claim_id: ClaimId
    value: Any


class UnresolvedObservation(BaseModel):
    """An explicit unknown that can never reach EA-0012's comparator."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["unresolved"] = "unresolved"
    claim_id: ClaimId
    unknown_class: UnknownClass


ClaimObservation = Annotated[
    ResolvedObservation | UnresolvedObservation,
    Field(discriminator="state"),
]


class BaselineOutcome(BaseModel):
    """One local, value-free claim result."""

    model_config = ConfigDict(extra="forbid")

    claim_id: ClaimId
    status: OutcomeStatus
    unknown_class: UnknownClass | None = None
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("baseline outcome reason must not be empty")
        return value

    @model_validator(mode="after")
    def _state_is_total(self) -> BaselineOutcome:
        if self.status == "unknown":
            if self.unknown_class is None:
                raise ValueError("unknown baseline outcome requires a cause class")
            if self.reason != _UNKNOWN_REASONS[self.unknown_class]:
                raise ValueError("unknown baseline reason contradicts its cause class")
        elif self.unknown_class is not None:
            raise ValueError("evaluated baseline outcome cannot carry an unknown class")
        return self


class BaselineAssessment(BaseModel):
    """Count-complete U4 result safe to aggregate outside the estate."""

    model_config = ConfigDict(extra="forbid")

    baseline_declared: bool
    passed: int = 0
    failed: int = 0
    unknown: int = 0
    outcomes: list[BaselineOutcome] = Field(default_factory=list)
    reason: str | None = None
    roadmap_dependencies: list[RoadmapDependency] = Field(default_factory=list)

    @field_validator("passed", "failed", "unknown", mode="before")
    @classmethod
    def _counts(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("baseline bucket counts must be non-negative integers")
        return value

    @model_validator(mode="after")
    def _counts_and_state_are_total(self) -> BaselineAssessment:
        if not self.baseline_declared:
            if self.outcomes or self.passed or self.failed or self.unknown:
                raise ValueError("undeclared baseline cannot carry evaluated claims")
            if self.reason != NO_BASELINE_DECLARED:
                raise ValueError("undeclared baseline requires the exact reason")
            if self.roadmap_dependencies:
                raise ValueError("undeclared baseline cannot carry claim dependencies")
            return self
        if self.reason is not None:
            raise ValueError("declared baseline cannot carry a declaration reason")
        expected = {
            "pass": sum(outcome.status == "pass" for outcome in self.outcomes),
            "fail": sum(outcome.status == "fail" for outcome in self.outcomes),
            "unknown": sum(outcome.status == "unknown" for outcome in self.outcomes),
        }
        actual = {
            "pass": self.passed,
            "fail": self.failed,
            "unknown": self.unknown,
        }
        if actual != expected:
            raise ValueError("baseline bucket counts do not match outcomes")
        if self.passed + self.failed + self.unknown != len(self.outcomes):
            raise ValueError("baseline buckets must cover every outcome exactly once")
        return self

    def aggregate(self) -> dict[str, int]:
        """Return the three visible buckets, with no claim or estate detail."""

        return {
            "passed": self.passed,
            "failed": self.failed,
            "unknown": self.unknown,
        }


def s003_acg_config() -> ACGConfig:
    """State the estate override instead of inheriting EA-0012's general default."""

    return ACGConfig(
        assessable_object_types=["asset"],
        classification_rules=[
            {
                "asset_class": "s003_owner_baseline",
                "condition": {
                    "op": "eq",
                    "attr": "attributes.s003_baseline_target",
                    "value": True,
                },
            }
        ],
        unknown_is_fail=False,
    )


async def assess_s003_baseline(
    object_store: ObjectStore,
    *,
    definition: BaselineDefinition | None,
    inventory: UnitInventoryDocument | None,
    surface: ServiceSurfaceDocument | None,
    tenant_id: str | None,
    observed_at: datetime,
    source_id: str,
) -> BaselineAssessment:
    """Derive from U1 documents, then compare only resolved values.

    The public call accepts no observation list. That makes stepping around the
    resolution gate with hand-written values impossible.
    """

    if definition is None:
        return BaselineAssessment(
            baseline_declared=False,
            reason=NO_BASELINE_DECLARED,
        )
    if inventory is None or surface is None:
        raise S003BaselineError("a declared baseline requires the U1 documents")

    observations = derive_baseline_observations(inventory, surface)
    return await _assess_baseline_observations(
        object_store,
        definition=definition,
        observations=observations,
        tenant_id=tenant_id,
        observed_at=observed_at,
        source_id=source_id,
    )


async def _assess_baseline_observations(
    object_store: ObjectStore,
    *,
    definition: BaselineDefinition,
    observations: Sequence[ClaimObservation],
    tenant_id: str | None,
    observed_at: datetime,
    source_id: str,
) -> BaselineAssessment:
    """Compare only a complete set of already-gated claim observations."""

    resolutions = _resolution_map(definition, observations)
    observed_state: dict[str, object] = {
        claim_id: resolution.value
        for claim_id, resolution in resolutions.items()
        if isinstance(resolution, ResolvedObservation)
    }
    target = await _upsert_target(
        object_store,
        observed_state=observed_state,
        tenant_id=tenant_id,
        observed_at=observed_at,
        source_id=source_id,
    )
    owner_baseline = Baseline(
        id="s003-owner-baseline",
        name="S-003 owner baseline",
        asset_class="s003_owner_baseline",
        version=1,
        checks=[
            Check(
                id=claim.claim_id,
                key=claim.claim_id,
                expected=claim.expected,
                comparator=claim.comparator,
                severity="medium",
                rationale=f"{claim.claim_id} is owner-declared.",
                framework_refs=[],
            )
            for claim in definition.claims
        ],
        tenant_id=tenant_id,
        set_by=_ACTOR,
        set_at=observed_at,
    )
    analyzer = AssetConfigAnalyzer(
        object_store,
        [owner_baseline],
        config=s003_acg_config(),
    )
    [drift] = await analyzer.assess_asset(target.id, tenant_id=tenant_id)
    by_claim = {item.check_id: item for item in drift.items}
    if frozenset(by_claim) != CLAIM_IDS:
        raise S003BaselineError("EA-0012 did not return the complete C1-C5 result")

    outcomes: list[BaselineOutcome] = []
    for claim in sorted(definition.claims, key=lambda item: item.claim_id):
        resolution = resolutions[claim.claim_id]
        owner_item = by_claim[claim.claim_id]
        if isinstance(resolution, UnresolvedObservation):
            if owner_item.status != "unknown":
                raise S003BaselineError(f"{claim.claim_id} unresolved observation was evaluated")
            outcomes.append(
                BaselineOutcome(
                    claim_id=claim.claim_id,
                    status="unknown",
                    unknown_class=resolution.unknown_class,
                    reason=_UNKNOWN_REASONS[resolution.unknown_class],
                )
            )
            continue
        if owner_item.status not in ("pass", "fail"):
            raise S003BaselineError(f"{claim.claim_id} resolved observation was not evaluated")
        outcomes.append(
            BaselineOutcome(
                claim_id=claim.claim_id,
                status=owner_item.status,
                reason=(
                    f"{claim.claim_id} matches the approved baseline."
                    if owner_item.status == "pass"
                    else f"{claim.claim_id} differs from the approved baseline."
                ),
            )
        )

    passed = sum(outcome.status == "pass" for outcome in outcomes)
    failed = sum(outcome.status == "fail" for outcome in outcomes)
    unknown = sum(outcome.status == "unknown" for outcome in outcomes)
    if drift.passed != passed or drift.failed != failed:
        raise S003BaselineError("EA-0012 aggregate contradicts the three-bucket result")
    roadmap = [
        RoadmapDependency(
            decision="privileged_read",
            dependent=f"baseline:{outcome.claim_id}",
        )
        for outcome in outcomes
        if outcome.unknown_class == "privileged_read"
    ]
    return BaselineAssessment(
        baseline_declared=True,
        passed=passed,
        failed=failed,
        unknown=unknown,
        outcomes=outcomes,
        roadmap_dependencies=roadmap,
    )


def derive_baseline_observations(
    inventory: UnitInventoryDocument,
    surface: ServiceSurfaceDocument,
) -> list[ClaimObservation]:
    """Resolve the C1-C5 handles from handed-in U1 documents.

    Claim text remains private. The stable handles carry only which collected
    evidence class can answer each claim. U1 has no evidence for C2/C3, while C1
    and C5 share the owner-gated privileged read. C4 is the one claim whose value is
    mechanically observable from the handed-in socket table.
    """

    if surface.listeners_raw is None:
        c1: ClaimObservation = UnresolvedObservation(
            claim_id="C1",
            unknown_class="privileged_read",
        )
        c4: ClaimObservation = UnresolvedObservation(
            claim_id="C4",
            unknown_class="collection_scope",
        )
    else:
        listeners = parse_listener_observations(surface, inventory)
        externally_bound = [
            observation
            for observation in listeners
            if classify_bind(observation.address) == "external"
        ]
        c1 = (
            ResolvedObservation(claim_id="C1", value=True)
            if all(observation.asset_key is not None for observation in externally_bound)
            else UnresolvedObservation(
                claim_id="C1",
                unknown_class="privileged_read",
            )
        )
        c4 = ResolvedObservation(
            claim_id="C4",
            value=bool(listeners),
        )
    c5: ClaimObservation = (
        ResolvedObservation(claim_id="C5", value=True)
        if surface.nginx_config is not None
        else UnresolvedObservation(
            claim_id="C5",
            unknown_class="privileged_read",
        )
    )
    return [
        c1,
        UnresolvedObservation(claim_id="C2", unknown_class="collection_scope"),
        UnresolvedObservation(claim_id="C3", unknown_class="collection_scope"),
        c4,
        c5,
    ]


def baseline_factor_readings(assessment: BaselineAssessment) -> list[FactorReading]:
    """Translate U4 into value-free density facts; claim ids never cross this API."""

    if not assessment.baseline_declared:
        return [
            FactorReading(
                name="baseline",
                status="unknown",
                reason=NO_BASELINE_DECLARED,
                source="s003:baseline:not-declared",
                unknown_cause="input_missing",
            )
        ]
    readings: list[FactorReading] = []
    for outcome in assessment.outcomes:
        if outcome.status == "unknown":
            cause: FactorUnknownCause = (
                "provider_unconfigured"
                if outcome.unknown_class == "certificate_lifecycle"
                else "input_missing"
            )
            readings.append(
                FactorReading(
                    name="baseline",
                    status="unknown",
                    reason=outcome.reason,
                    source=f"s003:baseline:{outcome.unknown_class}",
                    unknown_cause=cause,
                )
            )
        else:
            readings.append(
                FactorReading(
                    name="baseline",
                    status="known",
                    reason="owner baseline claim evaluated",
                    source="s003:baseline:evaluated",
                    unknown_cause=None,
                )
            )
    return readings


def _resolution_map(
    definition: BaselineDefinition,
    observations: Sequence[ClaimObservation],
) -> dict[ClaimId, ResolvedObservation | UnresolvedObservation]:
    by_claim: dict[ClaimId, ResolvedObservation | UnresolvedObservation] = {}
    for observation in observations:
        if observation.claim_id in by_claim:
            raise S003BaselineError("baseline observations must name each claim once")
        by_claim[observation.claim_id] = observation
    expected = {claim.claim_id for claim in definition.claims}
    if set(by_claim) != expected:
        raise S003BaselineError("baseline observations must cover exactly C1-C5")
    return by_claim


async def _upsert_target(
    object_store: ObjectStore,
    *,
    observed_state: Mapping[str, object],
    tenant_id: str | None,
    observed_at: datetime,
    source_id: str,
) -> AQObject:
    rows, _ = await object_store.query(
        ObjectQuery(
            tenant_id=tenant_id,
            object_type="asset",
            natural_key=_BASELINE_TARGET_NATURAL_KEY,
            limit=2,
        )
    )
    if len(rows) > 1:
        raise S003BaselineError("baseline target natural key is not unique")
    source = SourceRef(
        source_id=source_id,
        observed_at=observed_at,
        method="s003:baseline-resolution",
    )
    attributes = {
        "s003_baseline_target": True,
        "observed_state": dict(observed_state),
    }
    if rows:
        current = rows[0]
        updated = current.model_copy(
            update={
                "attributes": attributes,
                "sources": [*current.sources, source],
                "last_seen_at": observed_at,
                "updated_at": observed_at,
                "updated_by": _ACTOR,
            }
        )
        return await object_store.update(updated, expected_version=current.version)
    return await object_store.upsert(
        AQObject(
            id="",
            object_type="asset",
            schema_version=1,
            tenant_id=tenant_id,
            display_name="S-003 baseline target",
            attributes=attributes,
            natural_keys=[_BASELINE_TARGET_NATURAL_KEY],
            sources=[source],
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            created_at=observed_at,
            updated_at=observed_at,
            created_by=_ACTOR,
            updated_by=_ACTOR,
        )
    )
