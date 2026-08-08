"""S-004 baseline resolution through fresh captures and existing owners."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from aqelyn.conventions import require_typed_id
from aqelyn.conventions.errors import AQError, CertificateNotFound
from aqelyn.objects import ObjectStore
from aqelyn.secrets import CertificateAsset
from tools.s003_baseline import (
    BaselineAssessment,
    BaselineDefinition,
    ClaimObservation,
    ResolvedObservation,
    UnresolvedObservation,
    _assess_baseline_observations,
)
from tools.s003_surface import attribute_listener_observations, classify_bind
from tools.s004_handin import HandedInCaptureSet


class CertificateLifecycleOwner(Protocol):
    async def assess_certificate(
        self,
        certificate_id: str,
        *,
        tenant_id: str | None,
    ) -> CertificateAsset: ...


class CertificatePathBinding(BaseModel):
    """Private owner mapping from one config reference to its EA-0032 asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_ref: str
    certificate_id: str

    @field_validator("certificate_ref")
    @classmethod
    def _certificate_ref(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("certificate_ref must not be empty")
        return value

    @field_validator("certificate_id")
    @classmethod
    def _certificate_id(cls, value: str) -> str:
        return require_typed_id(value, "x509", field="certificate_id")


async def assess_s004_baseline(
    object_store: ObjectStore,
    captures: HandedInCaptureSet,
    *,
    definition: BaselineDefinition,
    tenant_id: str | None,
    observed_at: datetime,
    source_id: str,
    certificate_owner: CertificateLifecycleOwner | None = None,
    certificate_bindings: Sequence[CertificatePathBinding] = (),
) -> BaselineAssessment:
    """Resolve C1/C4 from W1 and C5 only through EA-0032."""

    selected = HandedInCaptureSet.model_validate(captures.model_dump(mode="python"))
    listeners = attribute_listener_observations(
        selected.privileged_sockets.listeners,
        selected.inventory,
    )
    externally_bound = [
        observation for observation in listeners if classify_bind(observation.address) == "external"
    ]
    c1: ClaimObservation = (
        ResolvedObservation(claim_id="C1", value=True)
        if all(observation.asset_key is not None for observation in externally_bound)
        else UnresolvedObservation(
            claim_id="C1",
            unknown_class="collection_scope",
        )
    )
    c4: ClaimObservation = ResolvedObservation(
        claim_id="C4",
        value=bool(listeners),
    )
    c5 = await _certificate_observation(
        selected,
        tenant_id=tenant_id,
        certificate_owner=certificate_owner,
        certificate_bindings=certificate_bindings,
    )
    return await _assess_baseline_observations(
        object_store,
        definition=definition,
        observations=[
            c1,
            UnresolvedObservation(claim_id="C2", unknown_class="collection_scope"),
            UnresolvedObservation(claim_id="C3", unknown_class="collection_scope"),
            c4,
            c5,
        ],
        tenant_id=tenant_id,
        observed_at=observed_at,
        source_id=source_id,
    )


async def _certificate_observation(
    captures: HandedInCaptureSet,
    *,
    tenant_id: str | None,
    certificate_owner: CertificateLifecycleOwner | None,
    certificate_bindings: Sequence[CertificatePathBinding],
) -> ClaimObservation:
    certificate_refs = {
        directive.arguments[0]
        for directive in captures.proxy_configuration.directives
        if directive.kind == "ssl_certificate"
    }
    bindings = {binding.certificate_ref: binding.certificate_id for binding in certificate_bindings}
    if len(bindings) != len(certificate_bindings):
        raise ValueError("certificate path bindings must be unique")
    if set(bindings) - certificate_refs:
        raise ValueError("certificate path binding is not present in the proxy capture")
    if not certificate_refs or set(bindings) != certificate_refs or certificate_owner is None:
        return UnresolvedObservation(
            claim_id="C5",
            unknown_class="certificate_lifecycle",
        )

    lifecycle_states: list[str] = []
    for certificate_ref in sorted(certificate_refs):
        certificate_id = bindings[certificate_ref]
        try:
            assessed = await certificate_owner.assess_certificate(
                certificate_id,
                tenant_id=tenant_id,
            )
        except CertificateNotFound:
            return UnresolvedObservation(
                claim_id="C5",
                unknown_class="certificate_lifecycle",
            )
        except AQError as exc:
            if not exc.retriable:
                raise
            return UnresolvedObservation(
                claim_id="C5",
                unknown_class="certificate_lifecycle",
            )
        if assessed.id != certificate_id or assessed.tenant_id != tenant_id:
            raise ValueError("EA-0032 certificate assessment does not match its binding")
        lifecycle_states.extend(
            (
                assessed.expiry.status,
                assessed.chain.status,
                assessed.revocation.status,
            )
        )
    if "invalid" in lifecycle_states:
        return ResolvedObservation(claim_id="C5", value=False)
    if lifecycle_states and set(lifecycle_states) == {"valid"}:
        return ResolvedObservation(claim_id="C5", value=True)
    return UnresolvedObservation(
        claim_id="C5",
        unknown_class="certificate_lifecycle",
    )
