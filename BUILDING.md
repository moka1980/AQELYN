# Building AQELYN — C-001 Foundation Runtime

This is the developer entry point for **building** AQELYN. For the project rules
and reading order, start with [`START_HERE.md`](START_HERE.md).

## Prerequisites

- Python 3.12
- Docker + Docker Compose (for Postgres 16 + Redis 7)

## Setup

```bash
cp .env.example .env
make install          # editable install + dev tools + pre-commit hooks
make up               # start Postgres + Redis locally
make check            # ruff + mypy --strict + pytest  (must be green)
```

`python -m aqelyn` prints a scaffold banner (no runtime yet — that arrives at
T6/T7).

## What to build, in what order

Implementation is driven by the specs and the task bundle:

- **Specs (authoritative):** [`docs/architecture/foundation/`](docs/architecture/foundation/)
  — read [`CONVENTIONS.spec.md`](docs/architecture/foundation/CONVENTIONS.spec.md) first.
- **Decisions (authoritative for stack/runtime):** [`docs/architecture/decisions/`](docs/architecture/decisions/)
- **Build plan:** [`C-001_Task_Bundle.md`](docs/architecture/foundation/C-001_Task_Bundle.md)
  — ordered tickets **T0 → T7**, each mapped to its spec and the exact `pytest`
  ids it must make pass.
- **Readiness evidence:** [`Consistency_and_Traceability.md`](docs/architecture/foundation/Consistency_and_Traceability.md)

**T0 (this scaffold) is done.** Codex begins at **T1 — Conventions library**.

## Package layout

```
src/aqelyn/
├── conventions/   # T1  -> CONVENTIONS.spec.md
├── objects/       # T2  -> EA-0002 Universal Object Model
├── events/        # T3  -> EA-0003 Event Bus
├── evidence/      # T4  -> EA-0004 Evidence & Integrity
├── findings/      # T5  -> Finding model
└── kernel/        # T6  -> EA-0001 Kernel   (T7 = walking skeleton)
tests/             # mirrors the package tree; store/bus contract suites shared
```

## Rules (from START_HERE)

1. Implement from the specs; do not add fields/types/events/errors the spec
   doesn't define. Raise an Engineering Change Request instead.
2. A ticket is done only when its named acceptance tests exist and pass, on both
   in-memory and backing-store variants where the spec requires.
3. `ruff` + `mypy --strict` stay green; append-only audit tables get no
   update/delete code path.
