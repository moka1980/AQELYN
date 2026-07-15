"""Digital Forensics artifact store protocol and validation helpers (EA-0016 F2)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.forensics.models import Artifact


class ArtifactStore(Protocol):
    async def put(self, artifact: Artifact) -> Artifact: ...

    async def get(self, artifact_id: str) -> Artifact | None: ...

    async def list(
        self, *, tenant_id: str | None, case_id: str | None = None
    ) -> list[Artifact]: ...


def materialize_artifact_id(artifact: Artifact) -> Artifact:
    if artifact.id:
        return artifact
    return artifact.model_copy(update={"id": new_id("art")}, deep=True)


def validate_artifact(artifact: Artifact) -> Artifact:
    return Artifact.model_validate(artifact.model_dump(mode="json"))


def validate_artifact_id(value: str, *, field: str = "artifact_id") -> str:
    return require_typed_id(value, "art", field=field)


def validate_case_id(value: str | None, *, field: str = "case_id") -> str | None:
    if value is None:
        return None
    return require_typed_id(value, "inc", field=field)


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)
