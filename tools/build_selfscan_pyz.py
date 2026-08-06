"""Build the downloadable ``aqelyn-selfscan.pyz`` from the shipped collector.

The public download at aqelyn.com/scan must be the exact code in ``src/aqelyn/collect`` — this
assembles it, so the artifact cannot drift from what the tests cover. Stdlib only.

    python -m tools.build_selfscan_pyz --output dist/aqelyn-selfscan.pyz
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
import zipapp
from pathlib import Path

_COLLECT = Path(__file__).resolve().parent.parent / "src" / "aqelyn" / "collect"
# Everything the self-scan runner touches. Kept explicit so a stray new module is a
# deliberate addition, not an accident that bloats the download.
_MODULES = ("__init__.py", "host.py", "checks.py", "cli.py", "selfscan.py")
_MAIN = "from aqelyn.collect.selfscan import main\n\nraise SystemExit(main())\n"


def build(output: Path) -> Path:
    """Assemble the zipapp at ``output`` and return the path."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "aqelyn" / "collect"
        pkg.mkdir(parents=True)
        (root / "aqelyn" / "__init__.py").write_text("", encoding="utf-8")
        for name in _MODULES:
            source = _COLLECT / name
            if not source.is_file():
                raise FileNotFoundError(f"collect module missing: {source}")
            shutil.copy2(source, pkg / name)
        (root / "__main__.py").write_text(_MAIN, encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(root, target=output, interpreter="/usr/bin/env python3")
    return output


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build aqelyn-selfscan.pyz")
    parser.add_argument("--output", type=Path, default=Path("dist/aqelyn-selfscan.pyz"))
    args = parser.parse_args(argv)
    out = build(args.output)
    print(f"built {out} ({out.stat().st_size} bytes)")
    print(f"sha256 {sha256(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
