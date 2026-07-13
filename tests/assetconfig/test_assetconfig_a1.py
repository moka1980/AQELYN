"""A1 acceptance tests for Asset & Configuration Governance types and comparators."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import aqelyn.assetconfig.comparators as comparators
from aqelyn.assetconfig import (
    MAX_REGEX_PATTERN_LENGTH,
    MISSING,
    ACGConfig,
    Baseline,
    Check,
    compare,
)
from aqelyn.conventions import ALL_ERROR_CODES, ActorRef
from aqelyn.conventions.errors import (
    BaselineConfigInvalid,
    BaselineNotFound,
    DriftSnapshotNotFound,
)

SYS = ActorRef(actor_type="system", actor_id="assetconfig-a1-test")


def _check(**overrides: object) -> Check:
    data: dict[str, object] = {
        "id": "ssh-root-login",
        "key": "ssh.permit_root_login",
        "expected": "no",
        "comparator": "eq",
        "severity": "high",
        "rationale": "Root SSH login should be disabled.",
        "framework_refs": [{"framework": "CIS", "requirement": "5.2.8"}],
    }
    data.update(overrides)
    return Check.model_validate(data)


def _baseline(*checks: Check) -> Baseline:
    return Baseline(
        id="cis-linux-server",
        name="CIS Linux Server",
        asset_class="linux_server",
        version=1,
        checks=list(checks) or [_check()],
        tenant_id=None,
        set_by=SYS,
        set_at=datetime.now(UTC),
    )


def test_acg_comparators() -> None:
    assert compare("eq", "no", "no")
    assert compare("ne", "yes", "no")
    assert compare("in", "prod", ["prod", "pci"])
    assert compare("nin", "dev", ["prod", "pci"])
    assert compare("gte", 5, 4)
    assert compare("lte", 4, 4)
    assert compare("exists", None, True)
    assert compare("absent", MISSING, True)
    assert compare("regex", "Ubuntu 22.04 LTS", r"^Ubuntu \d+\.\d+")

    assert not compare("eq", MISSING, "no")
    assert not compare("in", "prod", "production")
    assert not compare("gte", "5", 4)
    assert not compare("regex", "Debian 12", r"^Ubuntu")

    source = Path(comparators.__file__).read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source

    with pytest.raises(BaselineConfigInvalid):
        compare("regex", "aaaaaaaa", "(a+)+$")
    with pytest.raises(BaselineConfigInvalid):
        compare("regex", "aaaaaaaa", "a" * (MAX_REGEX_PATTERN_LENGTH + 1))
    with pytest.raises(BaselineConfigInvalid):
        compare("regex", "aaaaaaaa", "[")


def test_acg_config_invalid() -> None:
    _baseline()
    assert "BaselineConfigInvalid" in ALL_ERROR_CODES
    assert BaselineNotFound.code in ALL_ERROR_CODES
    assert DriftSnapshotNotFound.code in ALL_ERROR_CODES

    with pytest.raises(BaselineConfigInvalid):
        ACGConfig(batch_size=0)
    with pytest.raises(BaselineConfigInvalid):
        ACGConfig(batch_size=True)
    with pytest.raises(BaselineConfigInvalid):
        _check(comparator="matches")
    with pytest.raises(BaselineConfigInvalid):
        Check.model_validate(
            {
                "id": "missing-key",
                "expected": "no",
                "comparator": "eq",
                "severity": "high",
                "rationale": "Missing key should be rejected.",
            }
        )
    with pytest.raises(BaselineConfigInvalid):
        Check.model_validate(
            {
                "id": "missing-expected",
                "key": "ssh.permit_root_login",
                "comparator": "eq",
                "severity": "high",
                "rationale": "Missing expected should be rejected.",
            }
        )
    with pytest.raises(BaselineConfigInvalid):
        _baseline(_check(id="duplicate"), _check(id="duplicate"))
    with pytest.raises(BaselineConfigInvalid):
        _check(comparator="regex", expected="(a+)+$")
