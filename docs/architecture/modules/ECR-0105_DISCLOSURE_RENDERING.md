# ECR-0105 — The disclosure model reaches the page

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `34b99c6`.

> ⚠️ Sixth consecutive ECR by one actor. §6 lists what independent review should attack.

## 1. Finding of record

ECR-0104 §5 item 1, written by me against my own work:

> **No renderer consumes this yet.** The model is built and witnessed; the HTML report still
> renders its flat block. That is deliberate scope, and it means the levels are correct but
> unused — the exact "dead code" criticism I levelled at myself in ECR-0102.

A Charter requirement that exists only in a module no caller imports is not implemented. Charter
§9 calls Principle 5 and UX-008 mandatory architectural requirements; until this ECR, a person
opening the report saw none of it.

## 2. Decision

`_posture_section` now renders one `<details class="level">` per Charter level, and
`render_findings_report` takes `mode: Mode = Mode.ENTERPRISE`. The report CLI grows `--mode`
with the four Charter values.

`<details>` rather than script. Principle 5's expert depth must survive with JavaScript off —
this report is a local file a person may open from a USB stick or mail it to an auditor, and a
level that collapses into nothing without a script is a level that is not there. The mode sets
`open`, never presence.

## 3. One deliberate refusal

**A mode still does not change vocabulary.** ECR-0104 §5 item 4 recorded this and it remains
open. Wiring the renderer was the honest scope; rewriting finding text per audience is a
separate change with its own risk — Principle 2 asks for plainer words, and producing them
means a second rendering of the same fact, which is exactly where a "simplified" version drifts
from a true one. Left open rather than half-done. Recorded again so it is not lost.

## 4. A byte-perfect restore is not a restore

The most important thing this ECR produced is a defect in **my own mutation harness**, which
every AQELYN review since ECR-0096 has depended on.

`test_the_cli_actually_passes_the_mode_through` passed alone, then failed in the suite, then
failed alone. The source was pristine and `sha256sum`-verified against `HEAD`. The renderer,
called directly, returned two open levels for home. The CLI, on the same source, returned five.

The running bytecode was the mutated version. Python validates `__pycache__` against the source
mtime **as integer seconds** and the source **size**. The harness does `cp` to a backup, rewrites
the file, runs pytest — which compiles and caches the mutation — then `mv`s the backup back. `mv`
restores the backup's mtime, which is the `cp` time, in the same second as the rewrite. When the
replacement is the same length as the original, the size matches too, and the mutated `.pyc`
stays valid against pristine source. Here `mode=Mode(args.mode)` → `mode=Mode.ENTERPRISE` is
fifteen characters either way.

Proven, not inferred: the cached code object for `cli.py` contained no `mode` name at all, while
the file on disk did.

The same trap runs in the other direction — an applied mutation served from a stale pristine
cache is simply inert, which reads as GREEN. That is ECR-0100's *"a mutation that does not mutate
is indistinguishable from a test that does not test"*, arriving by a route that no content check
can see.

**Fix.** `lib.sh` now exports `PYTHONDONTWRITEBYTECODE=1` and purges `__pycache__` on apply and
on restore. Writing no bytecode is the only version of this with no timing hole in it.

**Blast radius, measured rather than assumed.** All 432 `mut` calls across every harness from
ECR-0094 onward were re-read; 16 are length-preserving. Poison is per-file and is cleared by the
next write to that file, so a cell only runs poisoned when the preceding length-preserving cell
targeted a *different* file, or when it was the last cell in a script. Every historical case was
self-clearing. The single escape in 432 was `m7.sh` in this ECR — the one that caught it.
**No shipped verdict is affected.** The matrix below was then re-run from a purged cache.

## 5. Acceptance — 11 mutations, all red

Harness `~/AQELYN_ECR0105_PREP/matrix.sh`. The renderer truncated to level 1; the mode argument
dropped on the way to `levels()`; nothing ever open; everything always open; the question, the
name and the body each stripped from the rendered summary; the CLI parsing `--mode` and then
discarding it; the CLI default flipped to home; and the two carried ECR-0104 model cells.

**One ran GREEN first.** M7 deleted `level.name` from the
rendered summary — the report lost the words "Summary", "Evidence", "Remediation" from every
level — and the whole suite stayed green. The Charter names the six levels; nothing witnessed
that the names arrived. Two more that I predicted would survive did survive in the ECR-0104 test
set, which is why the witnesses for the level body and for the CLI passthrough were written
before the matrix ran rather than after it.

All three new witnesses were proven **necessary**: with each one deselected, its own mutation
returns to GREEN.

16 tests, on a purged cache. One of them, the mode banner witness, was strengthened from a
bare substring check to an element check after review of my own §6 list. Ruff clean, `mypy --strict` clean across 589 files, full suite on live Postgres.
Carried matrix stays at **84**, untouched.

## 6. What review should attack

1. **The open-by-default counts are still my judgement**, now visible to a reader rather than
   only to a test. Two levels for home, five for enterprise. Nothing validates them.
2. **Level bodies are escaped and rendered as flat text.** `_technical_body`'s semicolon
   flattening now reaches a human eye. It is legible for the current observation shapes and
   ugly for a nested one.
3. **UX-008 remains half-served** — see §3.
4. **No test opens the file in a browser.** The HTML is checked by string count and by a
   parser, which is how I have been caught before: a structural check is not a load check.

## 7. Scope

`src/aqelyn/reporting/html.py` (`_posture_section`, `render_findings_report` signature, level
CSS), `src/aqelyn/reporting/cli.py` (`--mode`), and a new
`tests/reporting/test_disclosure_rendering.py`. No schema, no dependency, no loopback or GC
change. `render_findings_report` keeps its old single-argument call working by defaulting the
mode.
