"""A deliberately unsafe scorer for the AC-3 negative control."""

from typing import Literal


def unsafe_status_score(status: Literal["known_good", "unknown"]) -> float:
    _ = status
    return 100.0
