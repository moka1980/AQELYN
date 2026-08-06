"""ECR-0106: a posture subject becomes an object the store can resolve.

ECR-0100 refused to mint an `obj_` id for a posture subject because it would have been a
reference to nothing, and recorded the link as owed. This is that link. The property that
matters is not "the field is populated" - it is "the id resolves, and the same asset
observed twice is one asset".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime
from aqelyn.objects.memory import InMemoryObjectStore
from aqelyn.objects.models import ObjectQuery
from aqelyn.reporting.analyze import ingest_posture_into
from aqelyn.reporting.html import render_findings_report
from aqelyn.reporting.posture import (
    POSTURE_SUBJECT_OBJECT_TYPE,
    PostureDocumentError,
    subject_natural_key,
)

_VULNS: dict[str, Any] = {
    "descriptor": {"name": "grype", "timestamp": "2026-08-06T09:00:00Z"},
    "matches": [],
}


def _observation(index: int, ref: str, kind: str = "host") -> dict[str, Any]:
    return {
        "observation_id": f"obs-{index}",
        "subject": {"kind": kind, "ref": ref},
        "check": f"check-{index}",
        "severity": "high",
        "severity_score": 70.0,
        "observed": {"public_ports": [8080]},
        "what_happened": "One port is reachable from beyond this machine.",
        "why_it_matters": "It sits beside the reverse proxy rather than behind it.",
        "how_determined": "Parsed ss -tlnH on the host.",
        "risk_of_inaction": "A local-only service is exposed.",
        "remediation": {
            "summary": "Bind it to loopback.",
            "difficulty": "low",
            "expected_outcome": "Only intended ports stay reachable.",
        },
    }


def _collection(tmp_path: Path, observations: list[dict[str, Any]]) -> Path:
    (tmp_path / "vulns.json").write_text(json.dumps(_VULNS), encoding="utf-8")
    (tmp_path / "posture.json").write_text(
        json.dumps({"observations": observations}), encoding="utf-8"
    )
    return tmp_path


def _runtime() -> Runtime:
    return create_inmemory_runtime(AQELYNConfig(tenant_mode="local"))


# --- the id is real ------------------------------------------------------------------


async def test_every_posture_finding_names_an_affected_asset(tmp_path: Path) -> None:
    runtime = _runtime()
    findings = await ingest_posture_into(
        runtime, _collection(tmp_path, [_observation(1, "203.0.113.10")])
    )
    assert findings[0].affected_object_ids


async def test_the_affected_object_id_resolves_in_the_store(tmp_path: Path) -> None:
    """The whole reason ECR-0100 refused to mint one. A link that dangles is worse
    than an empty field, so this is the witness that matters most in the file."""
    runtime = _runtime()
    findings = await ingest_posture_into(
        runtime, _collection(tmp_path, [_observation(1, "203.0.113.10")])
    )
    resolved = await runtime.object_store.get(findings[0].affected_object_ids[0])
    assert resolved is not None
    assert resolved.display_name == "203.0.113.10"


async def test_the_object_carries_the_subject_as_a_natural_key(tmp_path: Path) -> None:
    runtime = _runtime()
    findings = await ingest_posture_into(
        runtime, _collection(tmp_path, [_observation(1, "203.0.113.10")])
    )
    resolved = await runtime.object_store.get(findings[0].affected_object_ids[0])
    assert resolved is not None
    assert [(key.namespace, key.value) for key in resolved.natural_keys] == [
        ("posture:host", "203.0.113.10")
    ]


# --- identity, not accumulation --------------------------------------------------------


async def test_two_observations_of_one_host_share_one_asset(tmp_path: Path) -> None:
    runtime = _runtime()
    findings = await ingest_posture_into(
        runtime,
        _collection(tmp_path, [_observation(1, "203.0.113.10"), _observation(2, "203.0.113.10")]),
    )
    assert len({item.affected_object_ids[0] for item in findings}) == 1


async def test_different_hosts_do_not_collapse_into_one_asset(tmp_path: Path) -> None:
    runtime = _runtime()
    findings = await ingest_posture_into(
        runtime,
        _collection(tmp_path, [_observation(1, "203.0.113.10"), _observation(2, "wcagvakt.no")]),
    )
    assert len({item.affected_object_ids[0] for item in findings}) == 2


async def test_the_same_ref_under_a_different_kind_is_a_different_asset(tmp_path: Path) -> None:
    """A host named `x` and a domain named `x` are not the same thing."""
    runtime = _runtime()
    findings = await ingest_posture_into(
        runtime,
        _collection(
            tmp_path,
            [_observation(1, "wcagvakt.no", kind="host"), _observation(2, "wcagvakt.no", "domain")],
        ),
    )
    assert len({item.affected_object_ids[0] for item in findings}) == 2


async def test_reingesting_the_same_collection_does_not_duplicate_the_asset(
    tmp_path: Path,
) -> None:
    """A second run of the same collector must update the asset, not clone it."""
    runtime = _runtime()
    collection = _collection(tmp_path, [_observation(1, "203.0.113.10")])
    await ingest_posture_into(runtime, collection)
    await ingest_posture_into(runtime, collection)
    found, _ = await runtime.object_store.query(
        ObjectQuery(tenant_id=None, object_type=POSTURE_SUBJECT_OBJECT_TYPE, limit=100)
    )
    assert len(found) == 1


async def test_the_object_type_is_registered_by_ingestion_itself(tmp_path: Path) -> None:
    """Ingestion must not depend on some other module having registered the type first."""
    runtime = _runtime()
    store = runtime.object_store
    assert isinstance(store, InMemoryObjectStore)
    assert not store.registry.is_registered(POSTURE_SUBJECT_OBJECT_TYPE)
    await ingest_posture_into(runtime, _collection(tmp_path, [_observation(1, "203.0.113.10")]))
    assert store.registry.is_registered(POSTURE_SUBJECT_OBJECT_TYPE)


# --- the natural key itself -------------------------------------------------------------


def test_a_subject_with_no_ref_is_refused_rather_than_given_a_placeholder() -> None:
    with pytest.raises(PostureDocumentError):
        subject_natural_key({"subject": {"kind": "host", "ref": "   "}})


def test_a_subject_with_no_kind_still_resolves_to_a_stable_key() -> None:
    key = subject_natural_key({"subject": {"ref": "203.0.113.10"}})
    assert key == subject_natural_key({"subject": {"kind": "", "ref": "203.0.113.10"}})


# --- it reaches the page ------------------------------------------------------------------


async def test_the_affected_asset_is_rendered_for_the_reader(tmp_path: Path) -> None:
    """An id nothing displays is the same dead data this ECR exists to remove."""
    from aqelyn.reporting.analyze import analyze_collection

    analysis = await analyze_collection(_collection(tmp_path, [_observation(1, "203.0.113.10")]))
    rendered = render_findings_report(analysis)
    assert "Affected asset:" in rendered
    assert "203.0.113.10" in rendered
    assert analysis.posture_findings[0].affected_object_ids[0] in rendered


async def test_an_unlinked_asset_reads_as_incomplete_not_as_clean(tmp_path: Path) -> None:
    from aqelyn.reporting.analyze import analyze_collection
    from aqelyn.reporting.html import _affected_assets

    analysis = await analyze_collection(_collection(tmp_path, [_observation(1, "203.0.113.10")]))
    stripped = analysis.posture_findings[0].model_copy(update={"affected_object_ids": []})
    rendered = _affected_assets(stripped)
    assert "not linked to an object" in rendered
    assert "none" not in rendered.lower().split("class=")[0]
