"""ECR-0101: the surface can start holding a collection.

Before this, a freshly started surface served eight routes over an empty kernel. The
operator had a working shell and nothing in it, and no shipped path put anything there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime
from aqelyn.reporting.analyze import ReportInputError, ingest_posture_into
from aqelyn.surface.cli import _parser

_VULNS: dict[str, Any] = {
    "descriptor": {"name": "grype", "timestamp": "2026-08-06T09:00:00Z"},
    "matches": [],
}


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "observation_id": "obs-ports",
        "subject": {"kind": "host", "ref": "203.0.113.10"},
        "check": "listening_sockets_public",
        "severity": "high",
        "severity_score": 72.0,
        "what_happened": "Four application ports are reachable from the internet.",
        "why_it_matters": "They sit beside the reverse proxy rather than behind it.",
        "how_determined": "ss -tlnp on the host over an existing session.",
        "risk_of_inaction": "Listeners are exposed without the proxy's controls.",
        "remediation": {
            "summary": "Bind each application to loopback and publish through the proxy.",
            "difficulty": "low",
            "expected_outcome": "Only 22, 80 and 443 remain reachable.",
        },
    }
    base.update(overrides)
    return base


def _collection(tmp_path: Path, posture: dict[str, Any] | None) -> Path:
    (tmp_path / "vulns.json").write_text(json.dumps(_VULNS), encoding="utf-8")
    if posture is not None:
        (tmp_path / "posture.json").write_text(json.dumps(posture), encoding="utf-8")
    return tmp_path


def _runtime() -> Runtime:
    return create_inmemory_runtime(AQELYNConfig(tenant_mode="local"))


# --- the argument ---------------------------------------------------------------------


def test_collection_argument_defaults_to_none() -> None:
    """An unseeded surface stays the default; this feature is opt-in."""
    assert _parser().parse_args(["--port", "8765"]).collection is None


def test_collection_argument_is_parsed_as_a_path() -> None:
    parsed = _parser().parse_args(["--collection", "/tmp/somewhere"])
    assert parsed.collection == Path("/tmp/somewhere")


# --- seeding a live runtime -----------------------------------------------------------


async def test_seeding_puts_findings_in_the_kernel_the_surface_reads(tmp_path: Path) -> None:
    """The surface serves whatever `finding_read` returns, so that is what must be seeded."""
    runtime = _runtime()
    raised = await ingest_posture_into(
        runtime, _collection(tmp_path, {"observations": [_observation()]})
    )
    assert len(raised) == 1

    reader = cast(Any, runtime.kernel.get_service("finding_read"))
    findings, _ = await reader.query(tenant_id=None, limit=10, cursor=None)
    assert [finding.id for finding in findings] == [raised[0].id]


async def test_a_collection_without_posture_seeds_nothing_and_does_not_fail(tmp_path: Path) -> None:
    runtime = _runtime()
    assert await ingest_posture_into(runtime, _collection(tmp_path, None)) == ()


async def test_a_refused_collection_raises_rather_than_seeding_partially(tmp_path: Path) -> None:
    """Serving an empty page after rejecting the input would read as 'nothing found'."""
    runtime = _runtime()
    broken = {"observations": [_observation(), _observation()]}  # repeated observation_id
    with pytest.raises(ReportInputError, match="posture document was refused"):
        await ingest_posture_into(runtime, _collection(tmp_path, broken))

    reader = cast(Any, runtime.kernel.get_service("finding_read"))
    findings, _ = await reader.query(tenant_id=None, limit=10, cursor=None)
    assert findings == []


async def test_seeding_is_ordered_by_severity(tmp_path: Path) -> None:
    observations = [
        _observation(observation_id="o-low", check="c-low", severity="low", severity_score=10.0),
        _observation(observation_id="o-high", check="c-high", severity="high", severity_score=90.0),
    ]
    runtime = _runtime()
    raised = await ingest_posture_into(
        runtime, _collection(tmp_path, {"observations": observations})
    )
    assert [finding.severity_score for finding in raised] == [90.0, 10.0]


async def test_seeding_twice_is_idempotent(tmp_path: Path) -> None:
    """A restart against the same collection must not double every finding."""
    directory = _collection(tmp_path, {"observations": [_observation()]})
    runtime = _runtime()
    await ingest_posture_into(runtime, directory)
    await ingest_posture_into(runtime, directory)

    reader = cast(Any, runtime.kernel.get_service("finding_read"))
    findings, _ = await reader.query(tenant_id=None, limit=50, cursor=None)
    assert len(findings) == 1
