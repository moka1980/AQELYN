"""I2 acceptance tests for the non-negotiable dignity gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions.errors import IdThreatConfigInvalid
from aqelyn.idthreat import IdThreatConfig, SignalRef, dignity_gate

NOW = datetime(2026, 7, 18, 11, 0, tzinfo=UTC)


def _signal(kind: str, ref: str) -> SignalRef:
    return SignalRef(kind=kind, ref=ref, as_of=NOW)


def _config() -> IdThreatConfig:
    return IdThreatConfig(
        min_corroboration=2,
        min_confidence=0.75,
        platform_default=0.5,
    )


@pytest.mark.parametrize(
    "values",
    [
        {"min_corroboration": 1, "min_confidence": 0.75, "platform_default": 0.5},
        {"min_corroboration": 2, "min_confidence": 0.5, "platform_default": 0.5},
        {"min_corroboration": 2, "min_confidence": 0.49, "platform_default": 0.5},
    ],
)
def test_idt_config_dignity_nonnegotiable(values: dict[str, int | float]) -> None:
    with pytest.raises(IdThreatConfigInvalid):
        IdThreatConfig(**values)


def test_idt_dignity_gate_drops() -> None:
    first = _signal("authentication", "auth:oslo")
    second = _signal("session", "session:sao-paulo")
    config = _config()

    assert dignity_gate([first, second], 0.76, config) is True
    assert dignity_gate([first], 0.99, config) is False
    assert dignity_gate([first, first], 0.99, config) is False
    assert dignity_gate([first, second], 0.75, config) is False
    assert dignity_gate([first, second], 0.74, config) is False
    assert dignity_gate([first, second], float("nan"), config) is False

    detection = "candidate" if dignity_gate([first], 0.99, config) else None
    assert detection is None
