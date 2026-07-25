"""C-038/R1: an impossible duration is unknown, never zero.

The EA-0018 flake was a negative duration. It was **diagnosed rather than clamped**:
clamping presents an impossible reading as a legitimate instantaneous measurement,
which is the empty-means-safe family (ECR-0013, ECR-0040) arriving in a metric, and it
makes the cause permanently invisible.

**Diagnosed cause: mixed time bases in the fixture.** The campaign's timestamps came
from the wall clock while the incident's came from a fixed `NOW` literal, so the sign
of MTTD depended on the machine's clock relative to that literal. Not a wall-clock
regression in production (these are differences between *stored* timestamps from
different records, so a monotonic source cannot help -- the ordering has to be checked,
not guaranteed) and not an ordering defect in the campaign path.

A production clamp existed too: `_mttd_seconds` returned `max(0.0, ...)`, so a campaign
that responded to an incident *before that incident occurred* was reported as
**instantaneous detection** -- the most favourable possible reading of impossible
input. That is the part that would have hidden a real ordering defect if one ever
appeared, so it is removed here whether or not it was the cause of this flake.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from aqelyn.conventions import utc_now
from aqelyn.response.metrics import _elapsed_seconds


def test_response_duration_never_negative() -> None:
    """An end before its start yields unknown, not a duration."""
    now = utc_now()
    assert _elapsed_seconds(now, now - timedelta(minutes=20)) == 1200.0
    assert _elapsed_seconds(now, now) == 0.0
    # The impossible pair. Zero would say "detected instantly"; None says "unusable".
    assert _elapsed_seconds(now, now + timedelta(minutes=20)) is None


def test_response_duration_zero_is_reserved_for_real_simultaneity() -> None:
    """Zero must keep meaning *measured as instantaneous*, not *impossible*.

    If impossible pairs were clamped to zero, a genuine zero and an unusable reading
    would be indistinguishable in the output -- and the mean would be dragged toward
    zero by values that should never have entered it.
    """
    now = utc_now()
    genuine = _elapsed_seconds(now, now)
    impossible = _elapsed_seconds(now, now + timedelta(seconds=1))

    assert genuine == 0.0
    assert impossible is None
    assert genuine != impossible


@pytest.mark.parametrize("skew_seconds", [1, 60, 1200, 86_400])
def test_response_duration_refuses_at_every_scale(skew_seconds: int) -> None:
    """The refusal does not depend on how far the ordering is inverted."""
    now = utc_now()
    assert _elapsed_seconds(now, now + timedelta(seconds=skew_seconds)) is None
