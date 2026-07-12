"""Kernel (T6). Implements EA-0001-kernel.spec.md:
AQService, AQKernel, lifecycle, health, wiring; ends in the C-001 skeleton (T7)."""

from aqelyn.kernel.config import AQELYNConfig
from aqelyn.kernel.factory import Runtime, create_inmemory_runtime
from aqelyn.kernel.kernel import AQKernel
from aqelyn.kernel.service import AQService, HealthStatus, KernelState
from aqelyn.kernel.wiring import BusObjectEventSink

__all__ = [
    "AQELYNConfig",
    "AQKernel",
    "AQService",
    "BusObjectEventSink",
    "HealthStatus",
    "KernelState",
    "Runtime",
    "create_inmemory_runtime",
]
