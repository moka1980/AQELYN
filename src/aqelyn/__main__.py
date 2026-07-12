"""Placeholder entry point (T0 scaffold).

Prints version and the backing-service URLs it can see, then exits. Real
runtime behaviour (Kernel start -> walking skeleton) arrives with T6/T7; see
the C-001 task bundle. This exists only to prove the package is installed and
env wiring works.
"""

from __future__ import annotations

import os

from aqelyn import __version__


def main() -> None:
    """Print scaffold banner and observed configuration."""
    print(f"AQELYN {__version__} — C-001 scaffold (no runtime yet)")
    print(f"  env       : {os.getenv('AQELYN_ENV', 'unset')}")
    print(f"  tenant    : {os.getenv('AQELYN_TENANT_MODE', 'unset')}")
    print(f"  database  : {os.getenv('AQELYN_DATABASE_URL', 'unset')}")
    print(f"  redis     : {os.getenv('AQELYN_REDIS_URL', 'unset')}")


if __name__ == "__main__":
    main()
