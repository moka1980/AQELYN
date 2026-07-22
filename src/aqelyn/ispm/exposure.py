"""Expose normalized identity accounts through EA-0023's owner seam."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import (
    CrossTenantReference,
    EvidenceTampered,
    ISPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.evidence import EvidenceStore
from aqelyn.exposure import (
    AssetRef,
    ExposureBasis,
    ExposureImpactContext,
    ExposureRecord,
    KnownSurfaceRecord,
    KnownSurfaceSource,
)
from aqelyn.ispm.models import IdentityPostureScore
from aqelyn.ispm.normalize import inventory_ref
from aqelyn.ispm.store import ISPMStore

_PAGE_SIZE = 1_000
_ACTOR = ActorRef(actor_type="system", actor_id="ispm_engine")


class IdentityExposureOwner(Protocol):
    async def analyze_scored_exposure(
        self,
        *,
        asset_ref: AssetRef,
        impact_context: ExposureImpactContext,
        tenant_id: str | None,
    ) -> ExposureRecord: ...


class IdentityKnownSurfaceSource:
    """Overlay identity metadata while preserving the upstream reachability claim."""

    def __init__(
        self,
        upstream: KnownSurfaceSource,
        store: ISPMStore,
        evidence_store: EvidenceStore,
    ) -> None:
        self.upstream = upstream
        self.store = store
        self.evidence_store = evidence_store

    async def list_known_surface(
        self,
        *,
        tenant_id: str | None,
    ) -> Sequence[KnownSurfaceRecord]:
        upstream_rows = list(await self.upstream.list_known_surface(tenant_id=tenant_id))
        identities = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page, next_cursor = await self.store.query_identities(
                tenant_id=tenant_id,
                cursor=cursor,
                limit=_PAGE_SIZE,
            )
            identities.extend(page)
            if next_cursor is None:
                break
            if not page:
                raise StoreUnavailable("ISPMStore returned an empty page with a cursor")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise StoreUnavailable("ISPMStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        by_ref = {row.asset_ref.ref_id: row.model_copy(deep=True) for row in upstream_rows}
        claimed_accounts: set[str] = set()
        for identity in identities:
            evidence = await self.evidence_store.get(identity.evidence_id, actor=_ACTOR)
            if evidence.tenant_id != tenant_id:
                raise CrossTenantReference("ISPM surface evidence belongs to another tenant")
            verification = await self.evidence_store.verify(identity.evidence_id)
            if not verification.ok:
                raise EvidenceTampered(
                    verification.detail or "ISPM surface evidence failed verification"
                )
            for account_id in identity.account_object_ids:
                if account_id in claimed_accounts:
                    raise ISPMConfigInvalid(
                        "one account object cannot belong to multiple normalized identities"
                    )
                claimed_accounts.add(account_id)
                surface_ref = inventory_ref(account_id)
                upstream = by_ref.get(surface_ref)
                identity_basis = ExposureBasis(
                    kind="access",
                    ref=f"ispm:identity:{identity.object_id}:account:{account_id}",
                    as_of=evidence.collected_at,
                    evidence_id=identity.evidence_id,
                )
                if upstream is None:
                    basis = [identity_basis]
                    reachability = None
                    observed_at = evidence.collected_at
                    rationale = (
                        "EA-0033 normalized an identity account; reachability remains "
                        "unknown until an evidence-backed source establishes it."
                    )
                else:
                    basis = _merge_basis(upstream.basis, identity_basis)
                    reachability = upstream.reachability
                    upstream_as_of = upstream.observed_at or min(
                        item.as_of for item in upstream.basis
                    )
                    observed_at = min(evidence.collected_at, upstream_as_of)
                    rationale = (
                        "EA-0033 overlaid identity control metadata while preserving the "
                        f"upstream reachability claim: "
                        f"{upstream.rationale or 'no upstream rationale'}"
                    )
                by_ref[surface_ref] = KnownSurfaceRecord(
                    asset_ref=AssetRef(
                        kind="identity",
                        ref_id=surface_ref,
                        object_id=account_id,
                        evidence_id=identity.evidence_id,
                    ),
                    classification=f"identity_{identity.identity_kind}",
                    exposure_type="identity_account_surface",
                    reachability=reachability,
                    basis=basis,
                    observed_at=observed_at,
                    rationale=rationale,
                )
        return [by_ref[key] for key in sorted(by_ref)]


def identity_impact_context(score: IdentityPostureScore) -> ExposureImpactContext:
    factor = round(1.0 - (score.score / 100.0), 6)
    return ExposureImpactContext(
        kind="identity_sensitivity",
        status="known",
        factor=factor,
        source_ref=score.id,
        evidence_id=score.evidence_id,
        reason=(
            f"EA-0033 measured the account control posture at {score.score:.3f}/100; "
            "lower control posture increases identity exposure impact."
        ),
    )


def identity_asset_ref(score: IdentityPostureScore) -> AssetRef:
    return AssetRef(
        kind="identity",
        ref_id=inventory_ref(score.subject_ref),
        object_id=score.subject_ref,
        evidence_id=score.evidence_id,
    )


def validate_identity_exposure(
    exposure: ExposureRecord,
    *,
    score: IdentityPostureScore,
    context: ExposureImpactContext,
) -> ExposureRecord:
    if exposure.tenant_id != score.tenant_id:
        raise CrossTenantReference("EA-0023 exposure belongs to another tenant")
    if exposure.asset_ref != identity_asset_ref(score):
        raise ISPMConfigInvalid("EA-0023 exposure is bound to a different identity account")
    if exposure.reachability == "unknown":
        if exposure.impact_context is not None or exposure.score is not None:
            raise ISPMConfigInvalid("unknown identity reachability cannot carry a score")
        return exposure
    if exposure.impact_context != context:
        raise ISPMConfigInvalid("EA-0023 exposure lost the identity impact context")
    if exposure.score is None or exposure.derivation is None:
        raise ISPMConfigInvalid("reachable identity exposure must be replayably scored")
    return exposure


def _merge_basis(
    upstream: Sequence[ExposureBasis],
    identity_basis: ExposureBasis,
) -> list[ExposureBasis]:
    selected = {
        (item.kind, item.ref, item.evidence_id): item.model_copy(deep=True) for item in upstream
    }
    selected[(identity_basis.kind, identity_basis.ref, identity_basis.evidence_id)] = identity_basis
    return [selected[key] for key in sorted(selected, key=repr)]
