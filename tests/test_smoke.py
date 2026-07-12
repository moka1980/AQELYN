"""T0 smoke test: the package imports and exposes its version."""

import importlib

import aqelyn

SUBPACKAGES = [
    "aqelyn.conventions",
    "aqelyn.objects",
    "aqelyn.events",
    "aqelyn.evidence",
    "aqelyn.findings",
    "aqelyn.kernel",
]


def test_package_version() -> None:
    assert aqelyn.__version__ == "0.1.0"


def test_subpackages_import() -> None:
    for name in SUBPACKAGES:
        assert importlib.import_module(name) is not None
