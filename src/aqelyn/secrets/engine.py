"""Secrets and cryptographic-asset engine (EA-0032 W2)."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.conventions import ActorRef, require_tenant_id
from aqelyn.conventions.errors import CryptoConfigInvalid, StoreUnavailable
from aqelyn.evidence import EvidenceStore
from aqelyn.inventory import DiscoverySource
from aqelyn.objects import ObjectStore
from aqelyn.secrets.ingest import (
    CryptoInventoryOwner,
    PreparedDescriptor,
    TrustAssessor,
    asset_observed_at,
    crypto_asset_kind,
    crypto_object,
    ensure_crypto_object_types,
    inventory_report,
    new_asset,
    prepare_descriptor,
    reconcile_asset,
    with_owner_identity,
)
from aqelyn.secrets.models import (
    CertificateDescriptor,
    CryptoAsset,
    CryptoAssetKind,
    CryptoConfig,
    CryptographicKeyDescriptor,
    CryptoQuery,
    SecretAsset,
    SecretScanDescriptor,
)
from aqelyn.secrets.store import CryptoStore

_SECRETS_ACTOR = ActorRef(actor_type="system", actor_id="secrets_engine")


class SecretsIntelligenceEngine:
    def __init__(
        self,
        store: CryptoStore,
        *,
        object_store: ObjectStore,
        inventory: CryptoInventoryOwner,
        evidence_store: EvidenceStore,
        trust: TrustAssessor,
        config: CryptoConfig | None = None,
        actor: ActorRef | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.inventory = inventory
        self.evidence_store = evidence_store
        self.trust = trust
        self.config = config or CryptoConfig()
        self.actor = actor or _SECRETS_ACTOR
        ensure_crypto_object_types(object_store)

    async def ingest_secrets(
        self,
        descriptors: Sequence[SecretScanDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[SecretAsset]:
        selected_tenant = require_tenant_id(tenant_id)
        prepared = await self._prepare_all(descriptors, tenant_id=selected_tenant)
        stored: list[SecretAsset] = []
        for item in prepared:
            asset = await self._persist(item, tenant_id=selected_tenant)
            if not isinstance(asset, SecretAsset):
                raise StoreUnavailable("secret ingest produced a non-secret asset")
            stored.append(asset)
        return [item.model_copy(deep=True) for item in stored]

    async def ingest_crypto_assets(
        self,
        keys: Sequence[CryptographicKeyDescriptor],
        certificates: Sequence[CertificateDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[CryptoAsset]:
        selected_tenant = require_tenant_id(tenant_id)
        descriptors: list[CryptographicKeyDescriptor | CertificateDescriptor] = [
            *keys,
            *certificates,
        ]
        prepared = await self._prepare_all(descriptors, tenant_id=selected_tenant)
        stored = [await self._persist(item, tenant_id=selected_tenant) for item in prepared]
        return [item.model_copy(deep=True) for item in stored]

    async def _prepare_all(
        self,
        descriptors: Sequence[
            SecretScanDescriptor | CryptographicKeyDescriptor | CertificateDescriptor
        ],
        *,
        tenant_id: str | None,
    ) -> list[PreparedDescriptor]:
        if len(descriptors) > self.config.batch_size:
            raise CryptoConfigInvalid(
                "crypto descriptor count exceeds batch_size; partial acceptance is forbidden"
            )
        prepared: list[PreparedDescriptor] = []
        for descriptor in descriptors:
            prepared.append(
                await prepare_descriptor(
                    descriptor,
                    evidence_store=self.evidence_store,
                    trust=self.trust,
                    actor=self.actor,
                    tenant_id=tenant_id,
                )
            )
        return prepared

    async def _persist(
        self,
        prepared: PreparedDescriptor,
        *,
        tenant_id: str | None,
    ) -> CryptoAsset:
        incoming = new_asset(prepared)
        kind = crypto_asset_kind(incoming)
        existing = await self.store.get_asset_by_fingerprint(
            kind,
            incoming.fingerprint,
            tenant_id=tenant_id,
        )
        selected = incoming if existing is None else reconcile_asset(existing, incoming)
        saved_object = await self.object_store.upsert(crypto_object(selected, actor=self.actor))
        if existing is not None and saved_object.id != existing.object_id:
            raise StoreUnavailable("EA-0002 crypto identity changed across ingest")
        selected = with_owner_identity(selected, saved_object.id)
        inventory_rows = await self.inventory.ingest(
            reports=[inventory_report(selected)],
            source=DiscoverySource(
                source_id=selected.source_id,
                reliability=selected.claim_confidence,
                health="ok",
                as_of=asset_observed_at(selected),
            ),
            tenant_id=tenant_id,
        )
        if len(inventory_rows) != 1 or inventory_rows[0].id != selected.inventory_ref:
            raise StoreUnavailable("EA-0025 inventory did not accept the crypto asset")
        return await self.store.put_asset(selected)

    async def _bounded_assets(
        self,
        *,
        tenant_id: str | None,
        kind: CryptoAssetKind | None = None,
    ) -> tuple[list[CryptoAsset], bool]:
        """Page under max_work; the boolean says the result was truncated."""
        selected_tenant = require_tenant_id(tenant_id)
        remaining = self.config.max_work
        cursor: str | None = None
        seen_cursors: set[str] = set()
        assets: list[CryptoAsset] = []
        while True:
            rows, next_cursor = await self.store.query_assets(
                CryptoQuery(
                    tenant_id=selected_tenant,
                    kind=kind,
                    limit=min(self.config.batch_size, remaining),
                    cursor=cursor,
                )
            )
            if len(rows) > remaining:
                raise StoreUnavailable("CryptoStore exceeded the requested work budget")
            assets.extend(rows)
            remaining -= len(rows)
            if next_cursor is None:
                return [item.model_copy(deep=True) for item in assets], False
            if next_cursor in seen_cursors:
                raise StoreUnavailable("CryptoStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            if remaining == 0:
                return [item.model_copy(deep=True) for item in assets], True
            cursor = next_cursor
