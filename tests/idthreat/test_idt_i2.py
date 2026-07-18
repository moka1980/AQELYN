"""I2 acceptance tests for the non-negotiable dignity gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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


def test_idt_config_floors_immutable() -> None:
    """A constructed config cannot be lowered afterwards (S3/§11 — not knobs)."""
    config = _config()

    with pytest.raises(ValidationError):
        config.min_corroboration = 1
    with pytest.raises(ValidationError):
        config.min_confidence = 0.0

    assert config.min_corroboration == 2
    assert config.min_confidence == 0.75


@pytest.mark.parametrize(
    "update",
    [
        {"min_corroboration": 1},
        {"min_confidence": 0.0},
        {"min_confidence": 0.5},
    ],
)
def test_idt_laundered_config_refused_at_use(update: dict[str, int | float]) -> None:
    """A config minted through a validation-skipping API cannot run the gate.

    `model_copy(update=...)` and `model_construct` bypass validators by design,
    so construction-time enforcement alone leaves the floors reachable. The gate
    re-asserts them at the point of use.
    """
    laundered = _config().model_copy(update=update)
    signals = [_signal("authentication", "auth:oslo"), _signal("session", "session:sao-paulo")]

    with pytest.raises(IdThreatConfigInvalid):
        dignity_gate(signals, 0.01, laundered)

    constructed = IdThreatConfig.model_construct(
        min_corroboration=1, min_confidence=0.0, platform_default=0.5
    )
    with pytest.raises(IdThreatConfigInvalid):
        dignity_gate([_signal("authentication", "auth:oslo")], 0.01, constructed)
