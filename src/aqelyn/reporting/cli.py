"""Installed P-001 command: one collection directory to one local HTML report."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections.abc import Sequence
from pathlib import Path

from aqelyn.reporting.analyze import (
    ReportInputError,
    analyze_collection,
    load_collection_documents,
)
from aqelyn.reporting.disclosure import Mode
from aqelyn.reporting.html import render_findings_report

_DEFAULT_REPORT = "aqelyn-findings.html"
_FINGERPRINT_PATTERN = re.compile(
    r'<meta name="aqelyn-input-fingerprint" content="([0-9a-f]{64})">'
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    collection_dir = Path(args.collection_dir).expanduser().resolve()
    output = _output_path(collection_dir, args.output)
    try:
        _validate_local_boundary(collection_dir, output)
        if args.reuse and output.is_file():
            current_fingerprint = load_collection_documents(collection_dir)[-1]
            if _stored_fingerprint(output) == current_fingerprint:
                print(f"Reused local findings report: {output}")
                return 0
        analysis = asyncio.run(analyze_collection(collection_dir))
        rendered = render_findings_report(analysis, mode=Mode(args.mode))
        _write_private_report(output, rendered)
    except ReportInputError as exc:
        parser.exit(2, f"aqelyn: {exc}\n")
    # ECR-0100: posture observations are counted separately. Folding them into the
    # findings total would let a collection with no representable vulnerability record
    # report a non-zero count, which is the opposite of what that zero is for.
    posture_note = (
        f"; {len(analysis.posture_findings):,} posture observations"
        if analysis.posture_findings
        else ""
    )
    print(
        f"Wrote {len(analysis.findings):,} local findings to {output} "
        f"({analysis.unknown_factor_count:,} unknown factors remain visible)"
        f"{posture_note}"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aqelyn",
        description=(
            "Turn handed-in collection documents into one local, offline findings report."
        ),
    )
    parser.add_argument("collection_dir", help="private directory containing vulns.json")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in Mode],
        default=Mode.ENTERPRISE.value,
        help=(
            "Charter UX-008 communication mode. Governs how many disclosure levels open "
            "by default; every level is present for every mode (default: enterprise)"
        ),
    )
    parser.add_argument(
        "--output",
        help=f"HTML path inside the collection directory (default: {_DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="reuse an existing report only when every consumed input is unchanged",
    )
    return parser


def _output_path(collection_dir: Path, requested: str | None) -> Path:
    if requested is None:
        return collection_dir / _DEFAULT_REPORT
    selected = Path(requested).expanduser()
    if not selected.is_absolute():
        selected = collection_dir / selected
    return selected.resolve()


def _validate_local_boundary(collection_dir: Path, output: Path) -> None:
    if not collection_dir.is_dir():
        raise ReportInputError(f"collection directory does not exist: {collection_dir}")
    if _git_ancestor(collection_dir) is not None:
        raise ReportInputError("collection documents must stay outside every Git worktree")
    try:
        output.relative_to(collection_dir)
    except ValueError as exc:
        raise ReportInputError(
            "the findings report must stay inside the collection directory"
        ) from exc
    if output.suffix.lower() != ".html":
        raise ReportInputError("the findings report output must use the .html suffix")
    if _git_ancestor(output.parent) is not None:
        raise ReportInputError("the findings report must stay outside every Git worktree")


def _git_ancestor(path: Path) -> Path | None:
    selected = path.resolve()
    candidates = (selected, *selected.parents)
    return next((candidate for candidate in candidates if (candidate / ".git").exists()), None)


def _stored_fingerprint(path: Path) -> str | None:
    try:
        prefix = path.read_text(encoding="utf-8")[:4096]
    except (OSError, UnicodeDecodeError):
        return None
    match = _FINGERPRINT_PATTERN.search(prefix)
    return match.group(1) if match is not None else None


def _write_private_report(path: Path, rendered: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError as exc:
        raise ReportInputError(f"cannot write local findings report: {path}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
