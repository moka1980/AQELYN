"""In-memory CryptoStore implementation (EA-0032 W2)."""

from __future__ import annotations

from aqelyn.conventions.errors import (
    CrossTenantReference,
    CryptoConfigInvalid,
    OptimisticConcurrencyConflict,
)
from aqelyn.secrets.models import (
    CredentialGovernanceScore,
    CryptoAssessment,
    CryptoAsset,
    CryptoAssetKind,
    CryptoQuery,
)
from aqelyn.secrets.store import (
    asset_kind,
    validate_assessment,
    validate_assessment_id,
    validate_asset,
    validate_asset_id,
    validate_fingerprint,
    validate_kind,
    validate_query,
    validate_score,
    validate_score_id,
    validate_tenant_scope,
    validate_write_tenant,
)


class InMemoryCryptoStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._asset_history: dict[str, list[CryptoAsset]] = {}
        self._identities: dict[tuple[str | None, CryptoAssetKind, str], str] = {}
        self._assessments: dict[str, CryptoAssessment] = {}
        self._scores: dict[str, CredentialGovernanceScore] = {}

    async def put_asset(self, asset: CryptoAsset) -> CryptoAsset:
        stored = validate_asset(asset)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        kind = asset_kind(stored)
        identity = (stored.tenant_id, kind, stored.fingerprint)
        identity_id = self._identities.get(identity)
        if identity_id is not None and identity_id != stored.id:
            raise CryptoConfigInvalid("crypto fingerprint identity cannot change asset id")
        history = self._asset_history.get(stored.id)
        if history:
            current = history[-1]
            if current.tenant_id != stored.tenant_id:
                raise CrossTenantReference("crypto asset tenant_id cannot change")
            if asset_kind(current) != kind or current.fingerprint != stored.fingerprint:
                raise CryptoConfigInvalid("crypto asset id cannot change kind or fingerprint")
            if current.model_dump(mode="json") == stored.model_dump(mode="json"):
                return current.model_copy(deep=True)
        self._identities[identity] = stored.id
        self._asset_history.setdefault(stored.id, []).append(stored.model_copy(deep=True))
        return stored.model_copy(deep=True)

    async def get_asset(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset | None:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        history = self._asset_history.get(selected_id)
        if not history or not self._visible(history[-1].tenant_id, selected_tenant):
            return None
        return history[-1].model_copy(deep=True)

    async def get_asset_by_fingerprint(
        self,
        kind: CryptoAssetKind,
        fingerprint: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset | None:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        identity = (
            selected_tenant,
            validate_kind(kind),
            validate_fingerprint(fingerprint),
        )
        asset_id = self._identities.get(identity)
        if asset_id is None:
            return None
        history = self._asset_history[asset_id]
        return history[-1].model_copy(deep=True)

    async def query_assets(
        self,
        query: CryptoQuery,
    ) -> tuple[list[CryptoAsset], str | None]:
        selected = validate_query(query, mode=self.mode)
        rows = sorted(
            (
                history[-1]
                for history in self._asset_history.values()
                if self._visible(history[-1].tenant_id, selected.tenant_id)
                and (selected.kind is None or asset_kind(history[-1]) == selected.kind)
                and (selected.cursor is None or history[-1].id > selected.cursor)
            ),
            key=lambda item: item.id,
        )
        page = rows[: selected.limit]
        next_cursor = page[-1].id if len(rows) > selected.limit else None
        return [item.model_copy(deep=True) for item in page], next_cursor

    async def put_assessment(self, assessment: CryptoAssessment) -> CryptoAssessment:
        stored = validate_assessment(assessment)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        existing = self._assessments.get(stored.id)
        if existing is not None:
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("crypto assessment tenant_id cannot change")
            raise OptimisticConcurrencyConflict("crypto assessments are append-only")
        self._assessments[stored.id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def get_assessment(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptoAssessment | None:
        selected_id = validate_assessment_id(assessment_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        record = self._assessments.get(selected_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return record.model_copy(deep=True)

    async def put_score(
        self,
        score: CredentialGovernanceScore,
    ) -> CredentialGovernanceScore:
        stored = validate_score(score)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        current = self._scores.get(stored.id)
        if current is not None:
            if current.tenant_id != stored.tenant_id:
                raise CrossTenantReference("credential governance score tenant_id cannot change")
            if current.model_dump(mode="json") != stored.model_dump(mode="json"):
                raise OptimisticConcurrencyConflict("credential governance scores are append-only")
            return validate_score(current)
        self._scores[stored.id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def get_score(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> CredentialGovernanceScore | None:
        selected_id = validate_score_id(score_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        record = self._scores.get(selected_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return validate_score(record)

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local":
            return row_tenant_id is None and requested_tenant_id is None
        return row_tenant_id == requested_tenant_id
