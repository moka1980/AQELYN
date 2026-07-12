# Architecture Decision Records (ADRs)

This folder holds AQELYN's **binding technical decisions**. Each ADR records
one decision, the context behind it, and its consequences. ADRs are the
source of truth for *how* AQELYN is built — the Engineering Archives (EA-xxxx)
say *what* to build; the ADRs say *with what and why*.

## Rules for AI agents (Codex, Claude Code) and human developers

1. **Read the applicable ADRs before implementing any EA.** Each EA names the
   ADRs it depends on.
2. **ADRs are authoritative.** If an EA and an accepted ADR conflict, the ADR
   wins for technical/runtime choices. Raise an Engineering Change Request
   rather than silently diverging.
3. **Do not change an accepted ADR in code.** Propose a new ADR (or a
   superseding one) under change control.
4. **Format is Markdown only.** ADRs are living records read and diffed in
   Git. Do not generate PDF/HTML copies — those go stale.

## Naming convention

```
ADR-NNNN-kebab-case-title.md
```

Zero-padded 4-digit number, lowercase, hyphen-separated. Numbers are never
reused.

## Status values

`Proposed` → `Accepted` → (optionally) `Superseded by ADR-NNNN` / `Deprecated`

## Index

| ADR | Title | Status | Applies to |
|---|---|---|---|
| [ADR-0001](ADR-0001-runtime-and-deployment-stack.md) | Runtime, Deployment Target, and Core Technology Stack | Accepted | All EAs from EA-0001 |

## How to add an ADR

1. Copy the format of ADR-0001.
2. Use the next free number.
3. Set status `Proposed`, open a pull request, get it reviewed.
4. On approval, change status to `Accepted` and add it to the index above.
