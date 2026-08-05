"""Command-line entry point for the local operator surface."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from aqelyn.kernel import AQELYNConfig, create_runtime
from aqelyn.reporting.analyze import ReportInputError, ingest_posture_into
from aqelyn.surface.app import SurfaceApplication
from aqelyn.surface.server import LOOPBACK_HOST, SurfaceServer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aqelyn surface")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--collection",
        type=Path,
        default=None,
        help=(
            "collection directory to seed the kernel from before serving; "
            "read once at startup, never re-read"
        ),
    )
    return parser


async def run_surface(*, port: int, collection: Path | None = None) -> None:
    config = AQELYNConfig.load()
    runtime = await create_runtime(config)
    server = SurfaceServer(SurfaceApplication(runtime), port=port)
    await runtime.kernel.start()
    try:
        seeded = 0
        if collection is not None:
            # Refusals surface here rather than at first request: an operator should learn
            # the collection was rejected when they start the surface, not from an empty page.
            seeded = len(await ingest_posture_into(runtime, collection))
        await server.start()
        print(f"AQELYN surface: http://{LOOPBACK_HOST}:{server.port}")
        if collection is not None:
            print(f"Seeded {seeded:,} posture findings from {collection}")
        await server.serve_forever()
    finally:
        await server.close()
        await runtime.kernel.stop(reason="surface_shutdown")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65_535:
        _parser().error("--port must be between 1 and 65535")
    if args.collection is not None and not args.collection.is_dir():
        _parser().error(f"--collection is not a directory: {args.collection}")
    try:
        asyncio.run(run_surface(port=args.port, collection=args.collection))
    except ReportInputError as exc:
        # A refused collection must stop the surface. Serving an empty page after
        # rejecting the input would read as "nothing found".
        print(f"aqelyn surface: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130
    return 0
