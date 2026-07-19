"""Software Supply Chain and SBOM models (EA-0030 Q1)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SupplyChainConfigInvalid
from aqelyn.graph.models import Path

SBOMFormat = Literal["spdx", "cyclonedx"]
ReachabilityStatus = Literal["direct", "transitive", "unreachable", "unknown"]
AssessmentStatus = Literal["complete", "truncated", "pending"]
DependencyScope = Literal["runtime", "dev", "optional"]
ProvenanceStatus = Literal["verified", "unverified", "failed"]
ProvenanceKind = Literal["slsa", "sigstore", "signature"]

VALID_SBOM_FORMATS: Final[frozenset[str]] = frozenset(("spdx", "cyclonedx"))
VALID_REACHABILITY_STATUSES: Final[frozenset[str]] = frozenset(
    ("direct", "transitive", "unreachable", "unknown")
)
VALID_ASSESSMENT_STATUSES: Final[frozenset[str]] = frozenset(("complete", "truncated", "pending"))
VALID_DEPENDENCY_SCOPES: Final[frozenset[str]] = frozenset(("runtime", "dev", "optional"))
VALID_PROVENANCE_STATUSES: Final[frozenset[str]] = frozenset(("verified", "unverified", "failed"))
VALID_PROVENANCE_KINDS: Final[frozenset[str]] = frozenset(("slsa", "sigstore", "signature"))


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise SupplyChainConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SupplyChainConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SupplyChainConfigInvalid(f"{field} must be >= 0")
    return value


def _unit(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SupplyChainConfigInvalid(f"{field} must be in [0,1]")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 1.0:
        raise SupplyChainConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise SupplyChainConfigInvalid(f"{field} must not contain duplicates")
    return list(values)


def _optional_nonempty(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field=field)


def _evidence_id(value: str | None) -> str | None:
    if value is None:
        return None
    return require_typed_id(value, "evd", field="evidence_id")


class SBOMDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(default_factory=lambda: new_id("sbm"))
    format: SBOMFormat
    subject_ref: str
    raw: dict[str, Any]
    source_id: str
    observed_at: datetime
    evidence_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _known_format(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("format") not in VALID_SBOM_FORMATS:
            raise SupplyChainConfigInvalid(f"unknown SBOM format: {data.get('format')!r}")
        return data

    @field_validator("doc_id")
    @classmethod
    def _doc_id(cls, value: str) -> str:
        return require_typed_id(value, "sbm", field="doc_id")

    @field_validator("subject_ref")
    @classmethod
    def _subject_ref(cls, value: str) -> str:
        return _nonempty(value, field="subject_ref")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        return _evidence_id(value)


class ComponentConflictCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    evidence_id: str
    observed_at: datetime
    reliability: float
    values: dict[str, Any]

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _candidate_evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("reliability", mode="before")
    @classmethod
    def _reliability(cls, value: object) -> float:
        return _unit(value, field="component conflict reliability")

    @field_validator("values")
    @classmethod
    def _values(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values:
            raise SupplyChainConfigInvalid("component conflict candidate requires values")
        return dict(values)


class ComponentConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[str]
    candidates: list[ComponentConflictCandidate]
    resolved_by: str | None = None
    resolved_evidence_id: str | None = None
    unresolved: bool
    reason: str

    @field_validator("fields")
    @classmethod
    def _fields(cls, values: list[str]) -> list[str]:
        if not values:
            raise SupplyChainConfigInvalid("component conflict requires fields")
        return _unique_nonempty(values, field="component conflict fields")

    @field_validator("candidates")
    @classmethod
    def _candidates(
        cls, values: list[ComponentConflictCandidate]
    ) -> list[ComponentConflictCandidate]:
        if len(values) < 2:
            raise SupplyChainConfigInvalid("component conflict requires at least two candidates")
        return values

    @field_validator("resolved_by")
    @classmethod
    def _resolved_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "src", field="resolved_by")

    @field_validator("resolved_evidence_id")
    @classmethod
    def _resolved_evidence_id(cls, value: str | None) -> str | None:
        return _evidence_id(value)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="component conflict reason")

    @model_validator(mode="after")
    def _resolution_consistency(self) -> ComponentConflict:
        if self.unresolved:
            if self.resolved_by is not None or self.resolved_evidence_id is not None:
                raise SupplyChainConfigInvalid(
                    "unresolved component conflicts cannot name a resolution"
                )
        elif self.resolved_by is None or self.resolved_evidence_id is None:
            raise SupplyChainConfigInvalid(
                "resolved component conflicts require source and evidence"
            )
        return self


class SoftwareComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = ""
    tenant_id: str | None = None
    purl: str
    name: str
    version: str
    component_type: str
    licenses: list[str] = Field(default_factory=list)
    supplier: str | None = None
    hashes: dict[str, str] = Field(default_factory=dict)
    provenance_status: ProvenanceStatus = "unverified"
    direct: bool
    source_id: str
    observed_at: datetime
    evidence_id: str
    conflicts: list[ComponentConflict] = Field(default_factory=list)

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("purl", "name", "version", "component_type")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="software component field")

    @field_validator("licenses")
    @classmethod
    def _licenses(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="licenses")

    @field_validator("supplier")
    @classmethod
    def _supplier(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="supplier")

    @field_validator("hashes")
    @classmethod
    def _hashes(cls, values: dict[str, str]) -> dict[str, str]:
        for algorithm, digest in values.items():
            _nonempty(algorithm, field="hash algorithm")
            _nonempty(digest, field=f"hashes[{algorithm!r}]")
        return dict(values)

    @field_validator("source_id")
    @classmethod
    def _component_source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _component_evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class QuarantinedSBOM(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    tenant_id: str | None = None
    source_id: str
    observed_at: datetime
    evidence_id: str | None = None
    raw: dict[str, Any]
    reason: str
    flagged: bool = True
    quarantined_at: datetime

    @field_validator("doc_id")
    @classmethod
    def _doc_id(cls, value: str) -> str:
        return require_typed_id(value, "sbm", field="doc_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("source_id")
    @classmethod
    def _quarantine_source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _quarantine_evidence_id(cls, value: str | None) -> str | None:
        return _evidence_id(value)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="quarantine reason")

    @model_validator(mode="after")
    def _must_be_flagged(self) -> QuarantinedSBOM:
        if not self.flagged:
            raise SupplyChainConfigInvalid("quarantined SBOM must remain flagged")
        return self


class DependencyRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_purl: str
    to_purl: str
    version_constraint: str | None = None
    scope: DependencyScope
    edge_id: str = ""

    @field_validator("from_purl", "to_purl")
    @classmethod
    def _purl(cls, value: str) -> str:
        return _nonempty(value, field="dependency purl")

    @field_validator("version_constraint")
    @classmethod
    def _version_constraint(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="version_constraint")

    @field_validator("edge_id")
    @classmethod
    def _edge_id(cls, value: str) -> str:
        return require_typed_id(value, "rel", field="edge_id", allow_empty=True)


def path_ref(path: Path) -> str:
    """Return a deterministic content address for an exact EA-0005 path."""

    payload = json.dumps(
        path.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class DependencyPathResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[Path] = Field(default_factory=list)
    truncated: bool = False


class ReachabilitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_purl: str
    cve_id: str
    reachable: ReachabilityStatus = "unknown"
    depth: int | None = None
    path_ref: str | None = None
    path: Path | None = None
    reason: str

    @field_validator("component_purl", "cve_id", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="reachability field")

    @field_validator("depth", mode="before")
    @classmethod
    def _depth(cls, value: object) -> int | None:
        if value is None:
            return None
        return _nonnegative_int(value, field="depth")

    @field_validator("path_ref")
    @classmethod
    def _path_ref(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="path_ref")

    @model_validator(mode="after")
    def _reachability_consistency(self) -> ReachabilitySignal:
        if self.reachable in {"unknown", "unreachable"}:
            if self.depth is not None or self.path_ref is not None or self.path is not None:
                raise SupplyChainConfigInvalid(
                    f"{self.reachable} reachability cannot carry depth or path"
                )
        elif self.reachable == "direct":
            if self.depth != 0 or self.path_ref is not None or self.path is not None:
                raise SupplyChainConfigInvalid(
                    "direct reachability requires depth == 0 and no graph path"
                )
        elif self.depth is None or self.depth < 1 or self.path_ref is None or self.path is None:
            raise SupplyChainConfigInvalid(
                "transitive reachability requires depth >= 1 and an EA-0005 path"
            )
        elif (
            self.path.length != len(self.path.edges)
            or len(self.path.node_ids) != self.path.length + 1
        ):
            raise SupplyChainConfigInvalid("EA-0005 path shape is inconsistent")
        elif self.depth != self.path.length:
            raise SupplyChainConfigInvalid("reachability depth must equal the EA-0005 path length")
        elif self.path_ref != path_ref(self.path):
            raise SupplyChainConfigInvalid(
                "path_ref must content-address the embedded EA-0005 path"
            )
        return self


class ProvenanceAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_purl: str
    kind: ProvenanceKind
    raw: dict[str, Any]
    evidence_id: str | None = None

    @field_validator("component_purl")
    @classmethod
    def _component_purl(cls, value: str) -> str:
        return _nonempty(value, field="component_purl")

    @field_validator("evidence_id")
    @classmethod
    def _attestation_evidence_id(cls, value: str | None) -> str | None:
        return _evidence_id(value)


class ProvenanceCheck(BaseModel):
    """Authenticity result from a kind-specific attestation verifier."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    detail: str

    @field_validator("detail")
    @classmethod
    def _detail(cls, value: str) -> str:
        return _nonempty(value, field="provenance check detail")


class ProvenanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_purl: str
    status: ProvenanceStatus
    detail: str
    evidence_id: str | None = None
    basis_evidence_id: str | None = None
    flagged: bool = True

    @field_validator("component_purl", "detail")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="provenance result field")

    @field_validator("evidence_id", "basis_evidence_id")
    @classmethod
    def _result_evidence_id(cls, value: str | None) -> str | None:
        return _evidence_id(value)

    @model_validator(mode="after")
    def _status_consistency(self) -> ProvenanceResult:
        if self.status == "verified":
            if self.evidence_id is None:
                raise SupplyChainConfigInvalid(
                    "verified provenance requires recorded result evidence"
                )
            if self.flagged:
                raise SupplyChainConfigInvalid("verified provenance cannot remain flagged")
        elif not self.flagged:
            raise SupplyChainConfigInvalid("unverified or failed provenance must remain flagged")
        return self


class SupplyChainAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("sca"))
    tenant_id: str | None = None
    run_at: datetime
    subject_ref: str
    components: int
    direct: int
    transitive: int
    unverified_provenance: int
    vulnerable_components: int
    assessment_status: AssessmentStatus = "pending"
    evidence_id: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "sca", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("subject_ref")
    @classmethod
    def _subject_ref(cls, value: str) -> str:
        return _nonempty(value, field="subject_ref")

    @field_validator(
        "components",
        "direct",
        "transitive",
        "unverified_provenance",
        "vulnerable_components",
        mode="before",
    )
    @classmethod
    def _count(cls, value: object) -> int:
        return _nonnegative_int(value, field="assessment count")

    @field_validator("evidence_id")
    @classmethod
    def _assessment_evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _status_and_count_consistency(self) -> SupplyChainAssessment:
        counts = (
            self.components,
            self.direct,
            self.transitive,
            self.unverified_provenance,
            self.vulnerable_components,
        )
        if self.assessment_status == "pending" and any(counts):
            raise SupplyChainConfigInvalid("pending assessment cannot carry computed counts")
        if self.direct + self.transitive > self.components:
            raise SupplyChainConfigInvalid(
                "direct plus transitive components cannot exceed total components"
            )
        if self.vulnerable_components > self.components:
            raise SupplyChainConfigInvalid("vulnerable_components cannot exceed total components")
        if self.unverified_provenance > self.components:
            raise SupplyChainConfigInvalid("unverified_provenance cannot exceed total components")
        return self


class SupplyChainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    license_policy_id: str | None = None
    sensitive_scopes: list[str] = Field(default_factory=list)
    max_depth: int = 6
    batch_size: int = 100

    @field_validator("license_policy_id")
    @classmethod
    def _license_policy_id(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="license_policy_id")

    @field_validator("sensitive_scopes")
    @classmethod
    def _sensitive_scopes(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="sensitive_scopes")

    @field_validator("max_depth", "batch_size", mode="before")
    @classmethod
    def _positive_limit(cls, value: object) -> int:
        return _positive_int(value, field="supply-chain config limit")
