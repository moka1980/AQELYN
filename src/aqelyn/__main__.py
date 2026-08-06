"""Installed AQELYN entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from aqelyn.collect.cli import main as collect_main
from aqelyn.reporting.cli import main as reporting_main
from aqelyn.surface.cli import main as surface_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the collector, the local report command, or the loopback operator surface."""
    selected = list(sys.argv[1:] if argv is None else argv)
    if selected[:1] == ["surface"]:
        return surface_main(selected[1:])
    if selected[:1] == ["collect"]:
        return collect_main(selected[1:])
    return reporting_main(selected)


if __name__ == "__main__":
    raise SystemExit(main())
