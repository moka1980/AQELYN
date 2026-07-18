"""Non-negotiable identity-detection dignity gate (EA-0027 I2)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from aqelyn.idthreat.models import IdThreatConfig, SignalRef


def dignity_gate(
    corroboration: Sequence[SignalRef],
    confidence: float,
    config: IdThreatConfig,
) -> bool:
    """Return whether independent corroboration and confidence clear both floors."""
    independent = {(signal.kind, signal.ref) for signal in corroboration}
    if len(independent) < config.min_corroboration:
        return False
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return False
    selected = float(confidence)
    return math.isfinite(selected) and 0.0 <= selected <= 1.0 and selected > config.min_confidence
