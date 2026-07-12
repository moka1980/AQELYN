# AQELYN Module Specifications (post-foundation)

Code-ready specifications for Engineering Archives **after** the C-001
foundation (EA-0005 onward). Same discipline as `../foundation/`: Codex
implements from these; Claude Code reviews against them. The `archive/EA-xxxx/`
masters remain the immutable published records; where a module spec here is more
detailed, the spec governs implementation.

## Rules for AI agents and developers

1. Read the applicable **ADRs** (`../decisions/`) and **CONVENTIONS**
   (`../foundation/CONVENTIONS.spec.md`) before implementing any module.
2. A module is implementable only when its spec is **Accepted** and it passes
   its Definition of Ready (the spec's "Acceptance Criteria ↔ Tests").
3. Build one module at a time, in the order the owner releases specs. After each
   module merges, **report back to the owner** before starting the next.
4. Do not invent fields/types/events/behavior the spec doesn't define — raise an
   Engineering Change Request.

## Index

| Module | Realizes | Depends on | Build | Status |
|---|---|---|---|---|
| [EA-0005 Knowledge Graph](EA-0005-knowledge-graph.spec.md) | EA-0005 | EA-0002, EA-0001 | [C-002](C-002_Task_Bundle.md) | Accepted |

## Next

EA-0006 onward: each gets a code-ready spec pass (owner + planning) before Codex
builds it, because the archive masters are still placeholders.
