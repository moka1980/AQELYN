# AQELYN Platform - START HERE

**Version:** 1.0  
**Status:** Architecture Complete - Implementation Ready  
**Architecture Baseline:** AQELYN Platform Enterprise Architecture v1.0  

---

## 1. Purpose

This is the first file every human developer, AI coding assistant, reviewer, tester, architect, and operator must read before working on AQELYN.

AQELYN is an AI-driven Cyber Intelligence Platform designed to make cybersecurity understandable, evidence-based, actionable, and trusted for individuals, companies, and government environments.

The architecture is complete. Implementation must follow the approved Engineering Archives and global engineering standards.

---

## 2. Non-Negotiable Rules

1. Do not redesign the architecture.
2. Do not reorganize the repository.
3. Do not skip Engineering Archives.
4. Do not implement undocumented functionality.
5. Do not create hidden AI prompts or undocumented AI behavior.
6. Do not weaken security, traceability, evidence, or explainability requirements.
7. Every implementation must be understandable by non-experts and actionable by experts.

---

## 3. Repository Structure

The repository structure is fixed.

```text
AQELYN/
├── archive/
├── blueprint/
├── docs/
│   └── architecture/
│       ├── decisions/        # Architecture Decision Records (ADR-NNNN-*.md)
│       ├── foundation/       # Code-ready foundation specs (C-001: EA-0001-0004, Finding, Conventions)
│       └── modules/          # Code-ready module specs post-foundation (EA-0005+)
├── src/
│   └── aqelyn/               # C-001 package: conventions, objects, events,
│                             #   evidence, findings, kernel
├── tests/
├── tools/
├── build/
├── releases/
├── scripts/
├── assets/
├── examples/
├── plugins/
├── sdk/
├── api/
├── .github/workflows/        # CI (sanctioned by the C-001 scaffold)
├── pyproject.toml            # project + ruff + mypy + pytest config
├── docker-compose.yml        # local Postgres 16 + Redis 7
├── Dockerfile
├── Makefile
├── .env.example
├── .pre-commit-config.yaml
├── BUILDING.md               # developer build entry point
├── README.md
└── START_HERE.md
```

The `src/aqelyn/` package layout, `tests/`, `.github/workflows/`, and the
root tooling files above are part of the **C-001 scaffold** and are sanctioned
by the C-001 Task Bundle. No *other* additional root folders are allowed without
a new Engineering Archive.

---

## 4. Read Before Coding

Read these documents first:

1. `README.md`
2. `docs/architecture/decisions/README.md` - Architecture Decision Records (ADR) index. **ADRs are binding technical decisions and are authoritative for runtime, stack, and deployment choices. Read all applicable ADRs before implementing any Engineering Archive.**
3. `docs/architecture/decisions/ADR-0001-runtime-and-deployment-stack.md` - Runtime, deployment target, and core technology stack (applies to every EA)
4. `docs/architecture/foundation/README.md` - Code-ready foundation specifications for the C-001 Foundation Runtime (complete): CONVENTIONS, EA-0002 Universal Object Model, EA-0003 Event Bus, EA-0004 Evidence, Finding model, EA-0001 Kernel. **Read CONVENTIONS first, then implement in the dependency order given in that README. Each spec carries a Definition of Ready; do not begin a spec until it is Accepted.**
5. `docs/architecture/modules/README.md` - Code-ready module specifications after the foundation (EA-0005 Knowledge Graph and onward), each with its own build task bundle. **Build one module at a time, in the order released; report back after each merges.**
6. Project Charter
7. Engineering Principles
8. Repository Standard
9. Architecture Guide
10. Development Rules
11. EA-0058 - Development & Coding Standards
12. EA-0059 - AQELYN Design System
13. EA-0060 - AI Engineering Handbook
14. EA-0061 - Developer Handbook
15. EA-0062 - AQELYN Engineering Portal & Mission Control
16. EA-0063 - AQELYN Final Readiness & Market Leadership Blueprint

Only then begin implementation.

---

## 5. Implementation Order

Implement sequentially:

```text
EA-0001 -> EA-0002 -> EA-0003 -> ... -> EA-0063
```

The first coding milestone is:

```text
C-001 - AQELYN Foundation Runtime
```

The C-001 build plan is defined in
`docs/architecture/foundation/C-001_Task_Bundle.md` (ordered tickets T0-T7,
each mapped to its spec and acceptance tests). Its readiness is evidenced by
`docs/architecture/foundation/Consistency_and_Traceability.md`.

Start with:

1. Kernel
2. Universal Object Model
3. Event Bus
4. Evidence Engine foundation
5. Logging and configuration
6. Test harness
7. Policy and Trust stubs

---

## 6. Product Principles

Every finding must explain:

- what happened,
- why it matters,
- how AQELYN determined it,
- what evidence supports it,
- what action is recommended,
- and what outcome is expected after remediation.

Every output must be simple enough for non-experts and deep enough for experts.

---

## 7. Definition of Done

A module is complete only when:

- code compiles,
- unit tests pass,
- integration tests pass,
- security tests pass,
- performance requirements are satisfied,
- documentation is updated,
- traceability is updated,
- requirements are satisfied,
- evidence and explainability are preserved.

---

## 8. Mission

Build the world's most understandable and trusted Cyber Intelligence Platform.

AQELYN must not merely detect problems. It must explain them, prove them, prioritize them, and help users fix them safely.

---

## 9. Final Instruction

Read. Understand. Implement. Verify. Document.

Do not redesign.
Do not simplify the architecture.
Do not skip Engineering Archives.
Build AQELYN exactly as specified.
