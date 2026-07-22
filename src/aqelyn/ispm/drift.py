"""Identity control drift on the EA-0012 comparator shape (EA-0033 G4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from aqelyn.assetconfig.comparators import compare
from aqelyn.conventions.errors import ISPMConfigInvalid
from aqelyn.ispm.models import (
    IdentityBaseline,
    IdentityDriftItem,
    IdentityDriftSnapshot,
    NormalizedIdentity,
)

_CONTROL_KEYS = ("mfa", "lifecycle", "last_activity")


def identity_drift_items(
    identity: NormalizedIdentity,
    baseline: IdentityBaseline,
    *,
    established_evidence: Mapping[str, bool],
) -> list[IdentityDriftItem]:
    items: list[IdentityDriftItem] = []
    for entry in baseline.entries:
        if entry.key not in _CONTROL_KEYS:
            items.append(
                IdentityDriftItem(
                    identity_id=identity.object_id,
                    key=entry.key,
                    expected=entry.expected,
                    observed=None,
                    status="unknown",
                    reason=f"Control {entry.key!r} is not represented by the normalized identity.",
                )
            )
            continue
        fact = getattr(identity.controls, entry.key)
        if fact.state == "unknown":
            items.append(
                IdentityDriftItem(
                    identity_id=identity.object_id,
                    key=entry.key,
                    expected=entry.expected,
                    observed=None,
                    status="unknown",
                    reason=fact.reason,
                )
            )
            continue
        if fact.evidence_id is None or not established_evidence.get(fact.evidence_id, False):
            items.append(
                IdentityDriftItem(
                    identity_id=identity.object_id,
                    key=entry.key,
                    expected=entry.expected,
                    observed=None,
                    status="unknown",
                    reason=f"Evidence for control {entry.key!r} could not be established.",
                )
            )
            continue
        passed = compare(entry.comparator, fact.state, entry.expected)
        items.append(
            IdentityDriftItem(
                identity_id=identity.object_id,
                key=entry.key,
                expected=entry.expected,
                observed=fact.state,
                status="pass" if passed else "fail",
                reason=(
                    f"EA-0012 comparator {entry.comparator!r} "
                    f"{'matched' if passed else 'did not match'} the observed control state."
                ),
            )
        )
    return items


def drift_snapshot(
    *,
    snapshot_id: str,
    tenant_id: str | None,
    baseline: IdentityBaseline,
    items: Sequence[IdentityDriftItem],
    run_at: datetime,
    evidence_id: str,
) -> IdentityDriftSnapshot:
    selected = sorted(
        (IdentityDriftItem.model_validate(item.model_dump(mode="json")) for item in items),
        key=lambda item: (item.identity_id, item.key),
    )
    return IdentityDriftSnapshot(
        id=snapshot_id,
        tenant_id=tenant_id,
        run_at=run_at,
        baseline_id=baseline.id,
        evaluated=len(selected),
        passed=sum(item.status == "pass" for item in selected),
        failed=sum(item.status == "fail" for item in selected),
        unknown=sum(item.status == "unknown" for item in selected),
        items=selected,
        evidence_id=evidence_id,
    )


def validate_drift_scope(scope: dict[str, object] | None) -> str | None:
    if scope is None:
        return None
    unknown = set(scope) - {"provider"}
    if unknown:
        raise ISPMConfigInvalid(f"unsupported identity drift scope fields: {sorted(unknown)}")
    provider = scope.get("provider")
    if provider is None:
        return None
    if not isinstance(provider, str) or not provider.strip():
        raise ISPMConfigInvalid("identity drift provider scope must be a non-empty string")
    return provider
