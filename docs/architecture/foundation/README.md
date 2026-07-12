# AQELYN Foundation Specifications

Code-ready specifications for the **C-001 Foundation Runtime**. These are the
implementation-grade versions of the foundation Engineering Archives and the
cross-cutting product/model contracts. **Codex implements from these; Claude
Code reviews against them.**

## Relationship to the archive

The `archive/EA-xxxx/` folders are the **published, immutable** engineering
records. The specs here are the **working, code-ready** designs that realize
them. Where a foundation spec is more detailed than its archive master, the
spec governs implementation. Changes go through change control (a new ADR or a
spec revision in a pull request), never silent edits.

## Rules for AI agents and developers

1. Read the applicable **ADRs** (`../decisions/`) before implementing any spec
   here — ADRs are authoritative for runtime/stack/deployment.
2. Read **CONVENTIONS** before any other spec — every spec relies on it.
3. A spec is implementable only when it passes its **Definition of Ready**
   (each spec's "Acceptance Criteria to Tests" section). Reviewers verify each
   named test exists and passes.
4. Do not invent fields, types, or behavior not in the spec. Raise an
   Engineering Change Request instead.

## The pack (complete)

| Spec | Realizes | Depends on | Status |
|---|---|---|---|
| [CONVENTIONS](CONVENTIONS.spec.md) | Cross-cutting conventions | ADR-0001 | Accepted |
| [EA-0002 Universal Object Model](EA-0002-universal-object-model.spec.md) | EA-0002 | ADR-0001, CONVENTIONS | Accepted |
| [EA-0003 Event Envelope & Bus](EA-0003-event-envelope-and-bus.spec.md) | EA-0003 | EA-0002 | Accepted |
| [EA-0004 Evidence & Integrity](EA-0004-evidence-and-integrity.spec.md) | EA-0004 | EA-0002, EA-0003 | Accepted |
| [Finding model](Finding-model.spec.md) | Charter Finding Standard | EA-0002/3/4 | Accepted |
| [EA-0001 Kernel](EA-0001-kernel.spec.md) | EA-0001 | all of the above | Accepted |

## Build order (dependency order, not numeric)

Contracts are designed first, then built bottom-up; the Kernel is built last
because it wires the rest:

```
CONVENTIONS
   -> EA-0002 Object Model
        -> EA-0003 Event Bus
             -> EA-0004 Evidence
                  -> Finding model
                       -> EA-0001 Kernel  (ends in the C-001 walking skeleton)
```

The **C-001 walking skeleton** (EA-0001 section 9) is the milestone that proves
the whole foundation fits together: kernel start -> object created -> event
published -> evidence recorded -> finding raised -> healthy -> stop.

## Working documents

| Doc | Purpose |
|---|---|
| [Consistency & Traceability](Consistency_and_Traceability.md) | Cross-spec consistency check (pass) + Charter→spec traceability matrix. |
| [C-001 Task Bundle](C-001_Task_Bundle.md) | Ordered build tickets (T0–T7) for Codex; review protocol for Claude Code. |
| [ECR-0001 Identifier Storage Representation](ECR-0001-identifier-storage-representation.md) | Proposed change request for the C-001 UUID-vs-text persistence decision. |

## Status

All specs are **Accepted**. The C-001 foundation is **implemented and green**
except for proposed ECR-0001, which must be accepted or rejected before final
foundation sign-off. See `../../..` source under `src/aqelyn/` and the test
suite under `tests/`. With Postgres + Redis enabled, 89 tests pass and 1 is
skipped; `ruff` + `mypy --strict` clean; the C-001 walking skeleton runs end to
end.
