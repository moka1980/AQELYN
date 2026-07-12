# EA-0001 — AQELYN Kernel — Implementation Specification

**Realizes:** EA-0001 (supersedes the placeholder `archive/EA-0001/EA-0001_Master.md` for implementation)
**Depends on:** ADR-0001, EA-0002 (ObjectStore), EA-0003 (EventBus), EA-0004 (EvidenceStore), Finding model, CONVENTIONS
**Consumed by:** every engine (each is an `AQService` the Kernel supervises)
**Status:** Accepted
**Definition of Ready:** see §12
**Implementation order note:** although numbered EA-0001, it is built *after* its dependencies' contracts exist (EA-0002→0004 + Finding + Conventions), because the Kernel wires them. This matches the C-001 milestone.

---

## 1. Purpose

The Kernel is AQELYN's runtime spine: the single process that **constructs the
shared infrastructure** (object store, event bus, evidence store, config,
logging), **registers and supervises services** (every engine), **starts and
stops them in dependency order**, and **reports health** so operators always
know whether AQELYN is fully operational, degraded, blocked on a dependency, or
intentionally disabled. It is the entry point of the C-001 Foundation Runtime.

## 2. Scope

**In scope:** the `AQService` contract, the service registry, dependency-ordered
lifecycle, the health/readiness/degraded model, infrastructure wiring,
configuration + structured logging bootstrap, signal handling, graceful
shutdown, and the **C-001 walking-skeleton** definition that validates the whole
foundation.

**Out of scope:** the HTTP API surface (FastAPI wiring is thin and specified in
its own increment), specific engines, and scheduling/workflow (EA-0032).

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Service (`AQService`)** | Any long-lived subsystem the Kernel supervises (an engine, the bus adapter, etc.). `svc_…`. |
| **Registry** | The Kernel's set of registered services + their dependency edges. |
| **Health** | `healthy` \| `degraded` \| `unavailable`, per service and aggregate. |
| **Readiness** | Whether a service can accept work yet (vs merely started). |
| **Degraded mode** | Running with one or more non-critical dependencies impaired. |

## 4. Design decisions

- **D1 — Everything is an `AQService`.** Engines implement one small contract
  (`start`/`stop`/`health`, declared `name` + `dependencies`), so the Kernel
  treats all subsystems uniformly. (Matches the `EA-0051` interface sketch.)
- **D2 — Dependency-ordered lifecycle.** The Kernel topologically sorts services
  and starts in dependency order, stops in reverse. A cycle is a startup error.
- **D3 — Dependency injection, no globals.** The Kernel constructs
  `ObjectStore`, `EventBus`, `EvidenceStore`, `FindingStore`, config, and logger
  once and injects them. No module reaches for a global singleton.
- **D4 — Fail-fast on critical, degrade on non-critical.** A failed *critical*
  dependency aborts startup (`ServiceStartFailed`); a failed *non-critical* one
  puts the Kernel in `degraded` and is surfaced, not hidden.
- **D5 — Graceful, bounded shutdown.** On `SIGTERM`/`stop`, services stop in
  reverse order with per-service timeouts; the Kernel emits
  `aqelyn.kernel.runtime_stopped` and flushes logs.
- **D6 — Config is 12-factor** (ADR-0001 D9); logging is structured JSON
  (CONVENTIONS §10) initialized before any service starts.

## 5. The service contract

```python
from typing import Protocol, Sequence
from pydantic import BaseModel

class HealthStatus(BaseModel):
    status: str                      # "healthy" | "degraded" | "unavailable"
    ready: bool
    detail: str | None = None
    dependencies: dict[str, str] = {}   # dep name -> status

class AQService(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def dependencies(self) -> Sequence[str]: ...          # names of services it needs
    @property
    def critical(self) -> bool: ...                        # True => failure aborts startup
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> HealthStatus: ...
```

## 6. The Kernel

```python
from typing import Protocol
from pydantic import BaseModel

class KernelState(BaseModel):
    phase: str                       # created|starting|running|degraded|stopping|stopped
    services: dict[str, HealthStatus]

class AQKernel(Protocol):
    def register(self, service: AQService) -> None: ...
    async def start(self) -> None: ...          # DI wiring, topo-sort, ordered start, emit runtime_started
    async def stop(self, *, reason: str = "shutdown") -> None: ...  # reverse stop, emit runtime_stopped
    async def health(self) -> KernelState: ...  # aggregate health/readiness
    def get_service(self, name: str) -> AQService: ...
```

- Aggregate health: `unavailable` if any *critical* service is unavailable;
  `degraded` if any non-critical is degraded/unavailable; else `healthy`.
- Readiness (`/readyz`) is true only when all critical services report `ready`.

## 7. Startup & shutdown sequence

**Startup:** load config → init logging → construct infra (store, bus, evidence,
finding store) → register services → topo-sort (detect cycles) → start each in
order (await `ready`, honoring D4) → wire standard object→event emission
(EA-0002 ops → EA-0003 events) → emit `aqelyn.kernel.runtime_started` → phase
`running`/`degraded`.

**Shutdown:** phase `stopping` → emit `runtime_stopped` → stop services in
reverse order with per-service timeout → close bus/store connections → flush
logs → phase `stopped`. Handles `SIGTERM`/`SIGINT`.

## 8. Configuration & logging bootstrap

- Config via `pydantic-settings` from env (`AQELYN_*`). Missing/invalid required
  config → `ConfigError`, abort before any service starts.
- Logging: structured JSON (CONVENTIONS §10), correlation/trace ids propagated;
  initialized first so even early failures are logged structurally.

## 9. The C-001 walking skeleton (the design's proof)

The Kernel increment ships a minimal but **end-to-end** path that exercises
every foundation contract together. This is the acceptance that proves the
foundation design is complete and consistent (the reason we designed before
coding):

```
kernel.start()
  → create a `generic` object via ObjectStore            (EA-0002)
  → that emits aqelyn.object.created on the EventBus       (EA-0003)
  → a subscriber records an EvidenceRecord for it          (EA-0004)
  → a Finding is raised citing that evidence + object       (Finding model)
  → kernel.health() == healthy, ready == true
kernel.stop()  → runtime_stopped emitted, phase == stopped
```

If any contract can't participate in this 60-line path, that's a foundation gap
found now — cheaply — instead of after ten engines depend on it.

## 10. Requirements

### Functional

- **FR-1** The Kernel SHALL start registered services in dependency order and stop them in reverse (D2).
- **FR-2** A dependency cycle SHALL be detected at startup and raise `ConfigError`/`ServiceStartFailed` (no partial start).
- **FR-3** A failed **critical** service SHALL abort startup; a failed **non-critical** service SHALL yield `degraded` and be reported (D4).
- **FR-4** The Kernel SHALL inject shared infra into services; no service SHALL rely on a global (D3).
- **FR-5** `health()` SHALL aggregate per-service status into `healthy`/`degraded`/`unavailable` per §6.
- **FR-6** Readiness SHALL be true only when all critical services are `ready`.
- **FR-7** Startup SHALL emit `aqelyn.kernel.runtime_started`; shutdown SHALL emit `aqelyn.kernel.runtime_stopped`.
- **FR-8** Shutdown SHALL be graceful and bounded per-service; `SIGTERM`/`SIGINT` SHALL trigger it.
- **FR-9** Invalid/missing required config SHALL abort before any service starts (`ConfigError`).
- **FR-10** The Kernel SHALL wire EA-0002 object operations to emit the standard EA-0003 events.
- **FR-11** The C-001 walking skeleton (§9) SHALL run green end-to-end.

### Non-functional

- **NFR-1** Cold start of the foundation (Kernel + infra + skeleton services) < 3 s on M-tier hardware.
- **NFR-2** Graceful shutdown completes < 10 s or forces per-service timeout.
- **NFR-3** No global mutable singletons; verified by structure test.
- **NFR-4** `mypy --strict` + `ruff` clean; the Kernel runs against **in-memory** infra with zero external services for unit tests (portability from ADR-0001).

## 11. Failure handling

- Critical start failure → abort, emit nothing as "running", exit non-zero, log
  the failing service + cause.
- Runtime dependency loss → transition to `degraded`, keep serving what can be
  served, surface via `health()`; recover to `healthy` when restored.
- Shutdown timeout → force-stop the laggard, log it, continue; never hang.

## 12. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test |
|---|---|---|
| AC-1 | Services start in dependency order, stop reverse | `test_kernel_ordered_lifecycle` |
| AC-2 | Dependency cycle rejected | `test_kernel_cycle_detected` |
| AC-3 | Critical failure aborts startup | `test_kernel_critical_fail_aborts` |
| AC-4 | Non-critical failure → degraded, reported | `test_kernel_degraded_mode` |
| AC-5 | Infra injected, no globals | `test_kernel_dependency_injection` |
| AC-6 | Aggregate health correct | `test_kernel_health_aggregation` |
| AC-7 | Readiness gates on critical services | `test_kernel_readiness` |
| AC-8 | runtime_started / runtime_stopped emitted | `test_kernel_lifecycle_events` |
| AC-9 | SIGTERM triggers graceful shutdown | `test_kernel_sigterm_graceful` |
| AC-10 | Invalid config aborts pre-start | `test_kernel_config_error` |
| AC-11 | **Walking skeleton runs end-to-end green** | `test_c001_walking_skeleton` |
| AC-12 | Runs on in-memory infra with no external services | `test_kernel_inmemory_only` |

## 13. Error taxonomy (contributions)

`ServiceStartFailed`, `DependencyUnavailable`, `ConfigError`
(see CONVENTIONS §9).

## 14. Dependencies & consumers

- **Depends on:** ADR-0001; the contracts of EA-0002, EA-0003, EA-0004, Finding
  model, CONVENTIONS. Libraries: `pydantic-settings`, stdlib `asyncio`/`signal`,
  structured logging.
- **Consumed by:** every engine registers as an `AQService`; the API layer asks
  the Kernel for `health()`/`readiness`.
