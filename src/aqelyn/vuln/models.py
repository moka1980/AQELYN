"""Vulnerability Intelligence & Prioritization models (EA-0024 V1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    VulnBasisMissing,
    VulnConfigInvalid,
    VulnNotReplayable,
)
from aqelyn.decision import Derivation
from aqelyn.exposure.models import AssetRef

Severity = Literal["critical", "high", "medium", "low", "none"]
DispositionKind = Literal["accepted_risk", "false_positive", "mitigated"]
VulnBasisKind = Literal["scanner", "cve_feed", "advisory", "exposure", "threat"]
VulnStatus = Literal["open", "reasserted", "closed"]
PriorityLevel = Literal["immediate", "high", "medium", "low", "deferred"]
FactorUnknownCause = Literal[
    "provider_unconfigured",
    "input_missing",
    "assessment_incomplete",
    "source_cannot_assert",
]

VALID_SEVERITIES: Final[frozenset[str]] = frozenset(
    ("critical", "high", "medium", "low", "negligible", "none", "unknown")
)
"""ECR-0064 Gap 2. `negligible` and `unknown` were added because real scanner output
uses both and neither could be represented.

**`none` and `unknown` are not interchangeable.** `none` means *the source stated
there is no severity* -- a positive claim of absence of risk. `unknown` means *the
source did not say*. Mapping an undetermined severity onto `none` is the most
favourable possible reading of an absence, arriving through a value that type-checks.
`negligible` is carried verbatim rather than folded into `low` (which would inflate
it) or `none` (which would assert something the scanner did not say)."""
VALID_DISPOSITION_KINDS: Final[frozenset[str]] = frozenset(
    ("accepted_risk", "false_positive", "mitigated")
)
VALID_VULN_BASIS_KINDS: Final[frozenset[str]] = frozenset(
    ("scanner", "cve_feed", "advisory", "exposure", "threat")
)
VALID_VULN_STATUS: Final[frozenset[str]] = frozenset(("open", "reasserted", "closed"))
VALID_PRIORITY_LEVELS: Final[frozenset[str]] = frozenset(
    ("immediate", "high", "medium", "low", "deferred")
)
VALID_FACTOR_UNKNOWN_CAUSES: Final[frozenset[str]] = frozenset(
    ("provider_unconfigured", "input_missing", "assessment_incomplete", "source_cannot_assert")
)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise VulnConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VulnConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VulnConfigInvalid(f"{field} must be >= 0")
    return value


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise VulnConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise VulnConfigInvalid(f"{field} must be a finite number")
    return selected


def _unit(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0 or selected > 1.0:
        raise VulnConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _nonnegative(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0:
        raise VulnConfigInvalid(f"{field} must be non-negative")
    return selected


def _bounded_score(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0 or selected > 100.0:
        raise VulnConfigInvalid(f"{field} must be in [0,100]")
    return selected


def _refs(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise VulnConfigInvalid(f"{field} must not contain duplicates")
    return values


class VulnBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref: str
    as_of: datetime
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_VULN_BASIS_KINDS:
            raise VulnConfigInvalid(f"unknown vulnerability basis kind: {value!r}")
        return value

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _nonempty(value, field="vulnerability basis ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class CarriedScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    value: float
    vector: str | None = None
    as_of: datetime

    @field_validator("source")
    @classmethod
    def _source(cls, value: str) -> str:
        return _nonempty(value, field="score source")

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: object) -> float:
        return _nonnegative(value, field="score value")

    @field_validator("vector")
    @classmethod
    def _vector(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="score vector")


class Disposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: ActorRef
    kind: str
    reason: str
    at: datetime
    reasserted_by_scanner: bool = False

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_DISPOSITION_KINDS:
            raise VulnConfigInvalid(f"unknown disposition kind: {value!r}")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="disposition reason")


class VulnerabilityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("vln"))
    tenant_id: str | None = None
    cve_id: str
    scanner: str
    asset_ref: AssetRef
    severity: str
    # ECR-0064 Gap 1: optional because 46% of real scanner matches carry no CVSS.
    # Requiring it forced callers to invent a value, and `0.0` would have asserted
    # *no severity* -- the most favourable reading of an absence. Absence now
    # produces a `PriorityFactor(status="unknown")`, which ECR-0040 already excludes
    # from the denominator rather than scoring favourably.
    cvss: CarriedScore | None = None
    epss: CarriedScore | None = None
    confidence: float
    basis: list[VulnBasis]
    disposition: Disposition | None = None
    discovered_at: datetime
    status: str = "open"

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "vln", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("cve_id", "scanner")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="vulnerability record field")

    @field_validator("severity")
    @classmethod
    def _severity(cls, value: str) -> str:
        if value not in VALID_SEVERITIES:
            raise VulnConfigInvalid(f"unknown severity: {value!r}")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="confidence")

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[VulnBasis]) -> list[VulnBasis]:
        if not values:
            raise VulnBasisMissing("vulnerability record requires at least one basis")
        return values

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in VALID_VULN_STATUS:
            raise VulnConfigInvalid(f"unknown vulnerability status: {value!r}")
        return value


class VulnerabilityUncertaintySurcharge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: float
    unknown_weight: float
    contribution: float

    @field_validator("rate", mode="before")
    @classmethod
    def _rate(cls, value: object) -> float:
        selected = _unit(value, field="uncertainty surcharge rate")
        if selected <= 0.0 or selected >= 0.5:
            raise VulnConfigInvalid(
                "uncertainty surcharge rate must be greater than 0 and below 0.5"
            )
        return selected

    @field_validator("unknown_weight", mode="before")
    @classmethod
    def _unknown_weight(cls, value: object) -> float:
        return _unit(value, field="uncertainty surcharge unknown weight")

    @field_validator("contribution", mode="before")
    @classmethod
    def _contribution(cls, value: object) -> float:
        return _bounded_score(value, field="uncertainty surcharge contribution")

    @model_validator(mode="after")
    def _consistent(self) -> VulnerabilityUncertaintySurcharge:
        expected = round(self.rate * self.unknown_weight * 100.0, 6)
        if not math.isclose(self.contribution, expected, rel_tol=0.0, abs_tol=1e-6):
            raise VulnConfigInvalid(
                "uncertainty surcharge contribution does not match rate and unknown weight"
            )
        return self


class VulnPriority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("vpr"))
    tenant_id: str | None = None
    vulnerability_id: str
    score: float
    priority: str
    factors: dict[str, Any]
    uncertainty_surcharge: VulnerabilityUncertaintySurcharge
    confidence: float
    derivation: Derivation
    rationale: str

    @model_validator(mode="before")
    @classmethod
    def _requires_derivation(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("derivation") is None:
            raise VulnNotReplayable("vulnerability priority requires a replayable derivation")
        return data

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "vpr", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("vulnerability_id")
    @classmethod
    def _vulnerability_id(cls, value: str) -> str:
        return require_typed_id(value, "vln", field="vulnerability_id")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: object) -> float:
        return _bounded_score(value, field="priority score")

    @field_validator("priority")
    @classmethod
    def _priority(cls, value: str) -> str:
        if value not in VALID_PRIORITY_LEVELS:
            raise VulnConfigInvalid(f"unknown priority: {value!r}")
        return value

    @field_validator("factors")
    @classmethod
    def _factors(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise VulnConfigInvalid("priority factors must not be empty")
        for key in value:
            _nonempty(key, field="priority factor key")
        return dict(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _priority_confidence(cls, value: object) -> float:
        return _unit(value, field="priority confidence")

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, value: str) -> str:
        return _nonempty(value, field="priority rationale")


class CoverageGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ref: str
    reason: str
    status: Literal["unknown"] = "unknown"
    unknown_cause: FactorUnknownCause

    @field_validator("asset_ref")
    @classmethod
    def _asset_ref(cls, value: str) -> str:
        return _nonempty(value, field="coverage gap asset_ref")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="coverage gap reason")

    @field_validator("unknown_cause")
    @classmethod
    def _unknown_cause(cls, value: str) -> str:
        if value not in VALID_FACTOR_UNKNOWN_CAUSES:
            raise VulnConfigInvalid(f"unknown coverage gap cause: {value!r}")
        return value


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scanned: list[str]
    unscanned: list[str]
    stale: list[str]
    unassessable: list[CoverageGap] = Field(default_factory=list)
    computed_at: datetime

    @field_validator("scanned", "unscanned", "stale")
    @classmethod
    def _asset_refs(cls, values: list[str]) -> list[str]:
        return _refs(values, field="coverage asset ref")

    @field_validator("unassessable")
    @classmethod
    def _unassessable(cls, values: list[CoverageGap]) -> list[CoverageGap]:
        refs = [value.asset_ref for value in values]
        _refs(refs, field="unassessable coverage asset ref")
        return values

    @model_validator(mode="after")
    def _coverage_categories_do_not_overlap(self) -> CoverageReport:
        assessed = {*self.scanned, *self.unscanned, *self.stale}
        overlap = assessed & {gap.asset_ref for gap in self.unassessable}
        if overlap:
            raise VulnConfigInvalid(
                "unassessable coverage subjects cannot also be scanned, unscanned, or stale"
            )
        return self


class VulnerabilityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("vas"))
    tenant_id: str | None = None
    priorities: list[VulnPriority] = Field(default_factory=list)
    coverage: CoverageReport
    suppressed_count: int = 0
    degraded: bool = False
    unavailable: list[dict[str, str]] = Field(default_factory=list)
    generated_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "vas", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("suppressed_count", mode="before")
    @classmethod
    def _suppressed_count(cls, value: object) -> int:
        return _nonnegative_int(value, field="suppressed_count")

    @field_validator("unavailable")
    @classmethod
    def _unavailable(cls, values: list[dict[str, str]]) -> list[dict[str, str]]:
        for value in values:
            if not value:
                raise VulnConfigInvalid("unavailable entries must not be empty")
            for key, selected in value.items():
                _nonempty(key, field="unavailable key")
                _nonempty(selected, field="unavailable value")
        return [dict(value) for value in values]


class RemediationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("rem"))
    tenant_id: str | None = None
    vulnerability_id: str
    priority: str
    proposed_campaign: dict[str, Any]
    owner: str | None = None
    target_date: datetime | None = None
    rationale: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rem", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("vulnerability_id")
    @classmethod
    def _vulnerability_id(cls, value: str) -> str:
        return require_typed_id(value, "vln", field="vulnerability_id")

    @field_validator("priority")
    @classmethod
    def _priority(cls, value: str) -> str:
        if value not in VALID_PRIORITY_LEVELS:
            raise VulnConfigInvalid(f"unknown priority: {value!r}")
        return value

    @field_validator("proposed_campaign")
    @classmethod
    def _proposed_campaign(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise VulnConfigInvalid("proposed_campaign must not be empty")
        return dict(value)

    @field_validator("owner")
    @classmethod
    def _owner(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="remediation owner")

    @field_validator("rationale")
    @classmethod
    def _remediation_rationale(cls, value: str) -> str:
        return _nonempty(value, field="remediation rationale")


class VulnConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_priorities: int = 100
    stale_after_days: int = 30
    score_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "cvss": 0.20,
            "epss": 0.10,
            "threat": 0.20,
            "exposure": 0.20,
            "mission": 0.20,
            "baseline": 0.05,
            "trust": 0.05,
        }
    )

    @field_validator("max_priorities", "stale_after_days", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="vulnerability config limit")

    @field_validator("score_weights")
    @classmethod
    def _score_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise VulnConfigInvalid("score_weights must not be empty")
        out: dict[str, float] = {}
        for key, weight in value.items():
            selected_key = _nonempty(key, field="score weight key")
            selected = _finite(weight, field=f"score_weights[{selected_key!r}]")
            if selected < 0.0:
                raise VulnConfigInvalid("score weights must be non-negative")
            out[selected_key] = selected
        return out
