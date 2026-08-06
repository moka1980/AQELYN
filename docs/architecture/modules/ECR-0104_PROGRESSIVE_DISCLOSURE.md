# ECR-0104 — Progressive disclosure and communication modes

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `e2a04ec`.

> ⚠️ Fifth consecutive ECR by one actor. §5 lists what independent review should attack.

## 1. Finding of record

ECR-0103 closed UX-001 and UX-002 and named three things it did not close. Two of them are
here: **Principle 5** (the six-level Progressive Detail Model) and **UX-008** (home, SMB,
enterprise and expert communication modes). Charter §9 calls both mandatory architectural
requirements.

They were absent entirely. A finding rendered as one flat block with no notion of levels, and
nothing anywhere selected register by audience.

## 2. Decision

`reporting/disclosure.py` expresses both as **data a renderer consumes**, not as markup
decisions scattered through one. `levels(finding, mode=...)` returns the Charter's six levels in
order, each with its number, name, the question it answers, its body, and whether it opens by
default in that mode.

Two properties are easy to violate by accident and both have witnesses:

**Levels add, they never repeat.** Principle 5 says the interface "supports multiple information
levels without duplicating data". A level that restates the one above it is a bug, and
`test_levels_do_not_duplicate_one_another` fails when it happens.

**A mode narrows what is shown; it never softens what is true.** Principle 8 forbids alarmist
language, but nothing licenses telling a home user a smaller truth. Every mode returns all six
levels with identical bodies — only `open_by_default` differs.
`test_a_mode_never_changes_the_content_of_a_level` holds one finding and reads it four ways.

Home opens 2 levels, SMB 3, enterprise 5, expert 6. Every level stays reachable in every mode,
because Principle 5 calls the simplified view "a starting point, not a ceiling".

## 3. One deliberate refusal

Level 3 renders a missing evidence link as *"No evidence record is linked to this finding, which
the platform requires"* — never as an absence of problems. UX-006 requires the link, so its
absence is a defect in the finding and must read as one. A mutation replacing that string with
"No issues found." turns the suite red.

## 4. Acceptance — 10 mutations, all red

Harness `~/AQELYN_ECR0104_PREP/matrix.sh`. Level 2 made a copy of level 1; technical detail
stripped of its filtering; the evidence id redacted; absent evidence reworded as reassurance;
expert mode opening only four levels; home mode opening all six; the summary made conditionally
closed; **a mode rewording the summary for a home reader**; the audit level deleted; and the
Charter's exact question text altered.

14 tests. Ruff clean, `mypy --strict` clean across 588 files, full suite on live Postgres.
Carried matrix stays at **84**, untouched.

## 5. What review should attack

1. **No renderer consumes this yet.** The model is built and witnessed; the HTML report still
   renders its flat block. That is deliberate scope, and it means the levels are correct but
   unused — the exact "dead code" criticism I levelled at myself in ECR-0102.
2. **The open-by-default numbers are my judgement.** Two levels for home, three for SMB. Nothing
   validates them against a real reader.
3. **`_technical_body` flattens a dict to a semicolon string.** Fine for the current shapes,
   crude for nested ones.
4. **UX-008 is only half-served.** Modes change disclosure depth; they do not change vocabulary,
   which is what Principle 2 (Simplicity First) actually asks for. A home reader still meets
   "listening sockets" and "loopback".

## 6. Scope

New `src/aqelyn/reporting/disclosure.py` and its tests. No change to any existing behaviour, no
schema, no dependency, no loopback or GC change. Nothing existing imports it yet.
