"""Command-line entry point for the local operator surface."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from aqelyn.kernel import AQELYNConfig, create_runtime
from aqelyn.surface.app import SurfaceApplication
from aqelyn.surface.server import LOOPBACK_HOST, SurfaceServer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aqelyn surface")
    parser.add_argument("--port", type=int, default=8765)
    return parser


async def run_surface(*, port: int) -> None:
    config = AQELYNConfig.load()
    runtime = await create_runtime(config)
    server = SurfaceServer(SurfaceApplication(runtime), port=port)
    await runtime.kernel.start()
    try:
        await server.start()
        print(f"AQELYN surface: http://{LOOPBACK_HOST}:{server.port}")
        await server.serve_forever()
    finally:
        await server.close()
        await runtime.kernel.stop(reason="surface_shutdown")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65_535:
        _parser().error("--port must be between 1 and 65535")
    try:
        asyncio.run(run_surface(port=args.port))
    except KeyboardInterrupt:
        return 130
    return 0
