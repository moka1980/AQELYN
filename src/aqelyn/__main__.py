"""Installed AQELYN entry point."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.reporting.cli import main as reporting_main


def main(argv: Sequence[str] | None = None) -> int:
    """Write one local findings report from handed-in collection documents."""
    return reporting_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
