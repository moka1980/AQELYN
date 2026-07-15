"""In-memory Digital Forensics artifact store (EA-0016 F2)."""

from __future__ import annotations

import copy

from aqelyn.conventions.errors import CrossTenantReference
from aqelyn.forensics.models import Artifact
from aqelyn.forensics.store import (
    materialize_artifact_id,
    validate_artifact,
    validate_artifact_id,
    validate_case_id,
    validate_tenant,
)


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._artifacts: dict[str, Artifact] = {}

    async def put(self, artifact: Artifact) -> Artifact:
        stored = validate_artifact(materialize_artifact_id(artifact))
        existing = self._artifacts.get(stored.id)
        if existing is not None and existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("artifact tenant_id cannot change")
        self._artifacts[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, artifact_id: str) -> Artifact | None:
        validate_artifact_id(artifact_id)
        artifact = self._artifacts.get(artifact_id)
        return None if artifact is None else copy.deepcopy(artifact)

    async def list(self, *, tenant_id: str | None, case_id: str | None = None) -> list[Artifact]:
        tenant_id = validate_tenant(tenant_id)
        case_id = validate_case_id(case_id)
        rows = [
            copy.deepcopy(artifact)
            for artifact in self._artifacts.values()
            if artifact.tenant_id == tenant_id and (case_id is None or artifact.case_id == case_id)
        ]
        rows.sort(key=lambda artifact: (artifact.first_seen_at, artifact.id))
        return rows
