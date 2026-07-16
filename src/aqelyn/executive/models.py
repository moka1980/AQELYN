"""Executive Intelligence & Strategic Reporting models (EA-0022 X1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ExecutiveConfigInvalid, FigureProvenanceMissing
from aqelyn.decision import Derivation

SourceKind = Literal[
    "risk",
    "compliance",
    "forecast",
    "mission",
    "finding",
    "recommendation",
    "evidence",
]
ApprovalStatus = Literal["draft", "pending", "approved", "published"]

VALID_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    (
        "risk",
        "compliance",
        "forecast",
        "mission",
        "finding",
        "recommendation",
        "evidence",
    )
)
VALID_INPUT_METRICS: Final[dict[str, frozenset[str]]] = {
    "compliance": frozenset(
        (
            "coverage",
            "posture_score",
            "control_result",
            "framework_score",
            "gap_count",
            "trend",
        )
    ),
    "risk": frozenset(("score", "exposure", "band", "trend", "top_risk_score", "risk_count")),
    "forecast": frozenset(
        (
            "point",
            "interval",
            "interval_low",
            "interval_high",
            "accuracy",
            "trend",
        )
    ),
    "mission": frozenset(("criticality", "mission_impact", "degraded_count")),
}
VALID_COMBINATORS: Final[frozenset[str]] = frozenset(
    ("identity", "sum", "average", "weighted_average", "min", "max", "delta", "ratio")
)
VALID_REPORT_SECTIONS: Final[frozenset[str]] = frozenset(
    ("kpis", "risk", "compliance", "forecast", "mission", "briefing")
)
VALID_BANDS: Final[frozenset[str]] = frozenset(("green", "amber", "red", "unknown"))


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ExecutiveConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExecutiveConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutiveConfigInvalid(f"{field} must be >= 0")
    return value


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExecutiveConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise ExecutiveConfigInvalid(f"{field} must be a finite number")
    return selected


def _unit(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0 or selected > 1.0:
        raise ExecutiveConfigInvalid(f"{field} must be in [0,1]")
    return selected


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref_id: str
    as_of: datetime
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_SOURCE_KINDS:
            raise ExecutiveConfigInvalid(f"unknown source kind: {value!r}")
        return value

    @field_validator("ref_id")
    @classmethod
    def _ref_id(cls, value: str) -> str:
        return _nonempty(value, field="source ref_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class Figure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | str
    unit: str
    source_refs: list[SourceRef]
    confidence: float | None = None
    as_of: datetime

    @field_validator("value")
    @classmethod
    def _value(cls, value: float | str) -> float | str:
        if isinstance(value, str):
            return _nonempty(value, field="figure value")
        return _finite(value, field="figure value")

    @field_validator("unit")
    @classmethod
    def _unit_name(cls, value: str) -> str:
        return _nonempty(value, field="figure unit")

    @field_validator("source_refs")
    @classmethod
    def _source_refs(cls, values: list[SourceRef]) -> list[SourceRef]:
        if not values:
            raise FigureProvenanceMissing("figure requires source_refs")
        return values

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _unit(value, field="figure confidence")


class KPIInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_engine: str
    metric: str
    selector: dict[str, Any] = Field(default_factory=dict)
    weight: float | None = None

    @field_validator("source_engine")
    @classmethod
    def _source_engine(cls, value: str) -> str:
        selected = _nonempty(value, field="source_engine")
        if selected not in VALID_INPUT_METRICS:
            raise ExecutiveConfigInvalid(f"unknown source engine: {selected!r}")
        return selected

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str, info: ValidationInfo) -> str:
        selected = _nonempty(value, field="metric")
        source_engine = info.data.get("source_engine")
        if isinstance(source_engine, str) and selected not in VALID_INPUT_METRICS[source_engine]:
            raise ExecutiveConfigInvalid(f"unknown metric for {source_engine!r}: {selected!r}")
        return selected

    @field_validator("selector")
    @classmethod
    def _selector(cls, value: dict[str, Any]) -> dict[str, Any]:
        return dict(value)

    @field_validator("weight")
    @classmethod
    def _weight(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _unit(value, field="input weight")


class KPIDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("kdf"))
    key: str
    version: int = 1
    title: str
    inputs: list[KPIInput]
    combinator: str
    unit: str
    thresholds: dict[str, float]
    promoted_by: ActorRef | None = None
    promoted_at: datetime | None = None
    active: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "kdf", field="id", allow_empty=True)

    @field_validator("key", "title", "unit")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="kpi definition field")

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="definition version")

    @field_validator("inputs")
    @classmethod
    def _inputs(cls, values: list[KPIInput]) -> list[KPIInput]:
        if not values:
            raise ExecutiveConfigInvalid("kpi definition inputs must not be empty")
        return values

    @field_validator("combinator")
    @classmethod
    def _combinator(cls, value: str) -> str:
        selected = _nonempty(value, field="combinator")
        if selected not in VALID_COMBINATORS:
            raise ExecutiveConfigInvalid(f"unknown combinator: {selected!r}")
        return selected

    @field_validator("thresholds")
    @classmethod
    def _thresholds(cls, values: dict[str, float]) -> dict[str, float]:
        if not values:
            raise ExecutiveConfigInvalid("thresholds must not be empty")
        out: dict[str, float] = {}
        previous: float | None = None
        for band, raw_value in values.items():
            selected_band = _nonempty(band, field="threshold band")
            value = _finite(raw_value, field=f"thresholds[{selected_band!r}]")
            if previous is not None and value >= previous:
                raise ExecutiveConfigInvalid("thresholds must be ordered high-to-low")
            out[selected_band] = value
            previous = value
        return out

    @model_validator(mode="after")
    def _promotion_integrity(self) -> KPIDefinition:
        promoted = self.promoted_by is not None or self.promoted_at is not None
        if self.active and (self.promoted_by is None or self.promoted_at is None):
            raise ExecutiveConfigInvalid("active kpi definitions require promotion metadata")
        if promoted and (self.promoted_by is None or self.promoted_at is None):
            raise ExecutiveConfigInvalid("kpi definition promotion metadata must be complete")
        return self


class KPIRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("kpi"))
    tenant_id: str | None = None
    kpi_key: str
    definition_version: int
    figure: Figure
    reporting_period: str
    band: str
    derivation: Derivation | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "kpi", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("kpi_key", "reporting_period")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="kpi record field")

    @field_validator("definition_version", mode="before")
    @classmethod
    def _definition_version(cls, value: object) -> int:
        return _positive_int(value, field="definition_version")

    @field_validator("band")
    @classmethod
    def _band(cls, value: str) -> str:
        selected = _nonempty(value, field="band")
        if selected not in VALID_BANDS:
            raise ExecutiveConfigInvalid(f"unknown kpi band: {selected!r}")
        return selected


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    figures: list[Figure] = Field(default_factory=list)
    narrative: str | None = None
    template_version: int | None = None

    @field_validator("key", "title")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="report section field")

    @field_validator("narrative")
    @classmethod
    def _narrative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="narrative")

    @field_validator("template_version", mode="before")
    @classmethod
    def _template_version(cls, value: object) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field="template_version")


class ExceptionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    figure: Figure

    @field_validator("key", "title")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="exception item field")


class ReportExclude(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    reason: str

    @field_validator("key", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="report exclude field")


class ExecutiveReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("rpt"))
    tenant_id: str | None = None
    title: str
    version: int = 1
    period: str
    sections: list[ReportSection]
    exceptions: list[Figure]
    approval_status: str = "draft"
    issued_at: datetime | None = None
    issued_by: ActorRef | None = None
    content_hash: str | None = None
    frozen: bool = False
    scope: dict[str, Any] = Field(default_factory=dict)
    excludes: list[ReportExclude] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rpt", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("title", "period")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="executive report field")

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="report version")

    @field_validator("sections")
    @classmethod
    def _sections(cls, values: list[ReportSection]) -> list[ReportSection]:
        if not values:
            raise ExecutiveConfigInvalid("executive report sections must not be empty")
        return values

    @field_validator("exceptions")
    @classmethod
    def _exceptions(cls, values: list[Figure]) -> list[Figure]:
        return values

    @field_validator("approval_status")
    @classmethod
    def _approval_status(cls, value: str) -> str:
        if value not in ("draft", "pending", "approved", "published"):
            raise ExecutiveConfigInvalid(f"unknown approval_status: {value!r}")
        return value

    @field_validator("content_hash")
    @classmethod
    def _content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="content_hash")

    @model_validator(mode="after")
    def _issued_integrity(self) -> ExecutiveReport:
        if self.frozen and (
            self.issued_at is None or self.issued_by is None or self.content_hash is None
        ):
            raise ExecutiveConfigInvalid(
                "frozen reports require issued_at, issued_by, content_hash"
            )
        return self


class Dashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("dsh"))
    tenant_id: str | None = None
    owner: ActorRef
    widgets: list[Figure]
    refresh_interval: int

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "dsh", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("widgets")
    @classmethod
    def _widgets(cls, values: list[Figure]) -> list[Figure]:
        if not values:
            raise ExecutiveConfigInvalid("dashboard widgets must not be empty")
        return values

    @field_validator("refresh_interval", mode="before")
    @classmethod
    def _refresh_interval(cls, value: object) -> int:
        return _positive_int(value, field="refresh_interval")


class ExecutiveBriefing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("brf"))
    tenant_id: str | None = None
    audience: str
    template_version: int
    sections: list[ReportSection]
    recommendations: list[SourceRef] = Field(default_factory=list)
    generated_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "brf", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("audience")
    @classmethod
    def _audience(cls, value: str) -> str:
        return _nonempty(value, field="audience")

    @field_validator("template_version", mode="before")
    @classmethod
    def _template_version(cls, value: object) -> int:
        return _positive_int(value, field="template_version")

    @field_validator("sections")
    @classmethod
    def _sections(cls, values: list[ReportSection]) -> list[ReportSection]:
        if not values:
            raise ExecutiveConfigInvalid("briefing sections must not be empty")
        return values


class ReportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[str]
    period: str
    audience: str

    @field_validator("sections")
    @classmethod
    def _sections(cls, values: list[str]) -> list[str]:
        if not values:
            raise ExecutiveConfigInvalid("sections must not be empty")
        out: list[str] = []
        for value in values:
            selected = _nonempty(value, field="section")
            if selected == "exceptions":
                raise ExecutiveConfigInvalid("exceptions are engine-assembled, not configurable")
            if selected not in VALID_REPORT_SECTIONS:
                raise ExecutiveConfigInvalid(f"unknown report section: {selected!r}")
            out.append(selected)
        if len(out) != len(set(out)):
            raise ExecutiveConfigInvalid("sections must not contain duplicates")
        return out

    @field_validator("period", "audience")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="report config field")


class ExecutiveConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_kpis: int = 50
    max_sections: int = 20

    @field_validator("max_kpis", "max_sections", mode="before")
    @classmethod
    def _positive(cls, value: object, info: ValidationInfo) -> int:
        return _positive_int(value, field=info.field_name or "executive config integer")


def validate_limit(value: int) -> int:
    return _positive_int(value, field="limit")


def validate_version(value: int) -> int:
    return _positive_int(value, field="version")


def validate_nonnegative_version(value: int) -> int:
    return _nonnegative_int(value, field="version")
