"""Knowledge Graph result and query models (EA-0005 §5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.objects.models import SourceRef

Direction = Literal["out", "in", "both"]


class NodeView(BaseModel):
    id: str
    object_type: str
    display_name: str
    tenant_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)


class EdgeView(BaseModel):
    id: str
    from_id: str
    to_id: str
    relation_type: str
    confidence: float = 1.0
    sources: list[SourceRef] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rel", field="id")

    @field_validator("from_id", "to_id")
    @classmethod
    def _object_ref(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="edge endpoint")


class Subgraph(BaseModel):
    nodes: list[NodeView] = Field(default_factory=list)
    edges: list[EdgeView] = Field(default_factory=list)
    truncated: bool = False


class Path(BaseModel):
    node_ids: list[str]
    edges: list[EdgeView] = Field(default_factory=list)
    length: int

    @field_validator("node_ids")
    @classmethod
    def _node_ids(cls, values: list[str]) -> list[str]:
        return [require_typed_id(value, "obj", field="node_ids") for value in values]


class ImpactHit(BaseModel):
    node: NodeView
    via: Path


class ImpactResult(BaseModel):
    hits: list[ImpactHit] = Field(default_factory=list)
    truncated: bool = False


class TraversalLimits(BaseModel):
    max_depth: int = 6
    max_nodes: int = 10_000
