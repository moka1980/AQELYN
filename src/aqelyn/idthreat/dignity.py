"""Non-negotiable identity-detection dignity gate (EA-0027 I2)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from aqelyn.idthreat.models import (
    IdThreatConfig,
    SignalRef,
    assert_dignity_floors,
    independent_signal_count,
)


def dignity_gate(
    corroboration: Sequence[SignalRef],
    confidence: float,
    config: IdThreatConfig,
) -> bool:
    """Return whether independent corroboration and confidence clear both floors.

    Raises `IdThreatConfigInvalid` if the config itself sits below a floor: the
    guarantee holds at the point of use, not only at construction (EA-0027 §11).
    """
    assert_dignity_floors(config)
    if independent_signal_count(list(corroboration)) < config.min_corroboration:
        return False
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return False
    selected = float(confidence)
    return math.isfinite(selected) and 0.0 <= selected <= 1.0 and selected > config.min_confidence
