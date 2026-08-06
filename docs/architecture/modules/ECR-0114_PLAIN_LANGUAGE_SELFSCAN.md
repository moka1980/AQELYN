# ECR-0114 — The self-scan report speaks to a person, not an operator

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `5b3e61a`.

> ⚠️ Fifteenth consecutive ECR by one actor. §5 lists what independent review should attack.

## 1. Finding of record

The owner ran the Windows self-scan and the report read like this:

> HIGH — 12 port(s) are reachable from beyond this machine — on every interface: 135, 445, 902…
> On Windows, ports 135/139/445 are RPC, NetBIOS and SMB file sharing.
> Determined by: Read listening sockets with Get-NetTCPConnection…

That is written for an operator. AQELYN's Charter Principle 2 (Simplicity First) says the
output must be understandable by everyone, non-technical included — and it should show what is
**good**, not only problems. The self-scan report broke both.

A second, sharper finding surfaced first: on the real Windows machine every escaped field in
the report was **blank**. `HtmlEnc` used `.Replace([char]34, "&quot;")`, which has no
`(char, string)` `String.Replace` overload, so it threw, `$ErrorActionPreference =
SilentlyContinue` swallowed it, and the function returned nothing. **I had "validated" the
console output, which does not use `HtmlEnc` — not the report the customer opens.** Lesson
recorded: validate the artifact the customer sees, not a summary beside it.

## 2. Decision

A plain-language layer, shared by both collectors.

- **`src/aqelyn/collect/plain.py`** maps each `check` id to a plain **headline**, a plain
  **meaning**, a plain **what-to-do**, and a reassuring line for when the check **passed** —
  written for someone with no security background. Non-alarmist severity words (Principle 8):
  "Worth attention", "Worth improving", not "HIGH".
- **The report has three sections:** *Worth a look* (findings, plain, with the raw technical
  text tucked into a "Show the technical detail" expander), *Looking good* (the checks that
  passed, each a ✓ and a plain sentence), and *Could not check* (unmeasured, with how to read
  it). A summary line up top: "N looking good · M worth a look".
- **`posture.json` is unchanged** — it stays the technical record for the platform. Only the
  human-facing `report.html` gets the plain layer.
- The Windows `.ps1` carries the same `$PLAIN` table and the same three-section report, so a
  Windows customer sees exactly what a Linux one does.

Passed checks are computed as the collector's known check ids minus the ones that produced an
observation — a check that said nothing passed.

## 3. Validated where it could be, and where it could not

- The Linux runner and report are covered by tests and were run on this machine: a clean
  machine now shows "Looking good" items, not a bare problem list.
- The Windows `.ps1` **cannot be run or even parsed here** (no PowerShell on the Linux host).
  It mirrors the tested Linux logic line for line, and the validated collection code is
  untouched — but its final proof is the owner running it. This is the standing limit named
  since ECR-0107: a Windows collector is only as validated as its last real run.

## 4. Acceptance

11 tests on the Linux side (`tests/collect/test_selfscan.py`), including: the report shows a
plain headline not raw jargon, a "Looking good" section exists, every emitted check has a
plain-language entry (a new check without one fails the test), and the zipapp still builds and
runs. Ruff clean, `mypy --strict` clean across 596 files, full suite on live Postgres. Carried
matrix stays at **84**.

The HtmlEnc bug is fixed and, because the console path never exercised it, its fix is only
proven by the owner's re-run — which is exactly the gap this ECR's §1 lesson is about.

## 5. What review should attack

1. **The Windows `.ps1` has no automated test** and could not be parsed on CI. The plain-language
   port is a hand-translation of tested Python; a PowerShell CI runner is the real fix.
2. **The plain wording is mine, not a copywriter's or a native speaker's.** It is English only;
   the owner's customers may be Norwegian. Plain-*language* and plain-*English* are not the same
   thing — a second glossary (i18n) is a named follow-up.
3. **`plain.py` and `checks.py` are kept in sync by a test**, but the Windows `$PLAIN` table is a
   separate copy of the same words — it can drift from `plain.py` with nothing to catch it.
4. **"Looking good" hides nuance.** A check that passed shows one green line; a customer cannot
   see *how* it passed (which is often fine, but it is less information than the operator surface).

## 5a. Multilingual (added same session)

Plain-*language* is not plain-*English* — the owner's customers may be Norwegian. The plain
layer is now bilingual: `plain.py` carries `PLAIN` (en) and `PLAIN_NB` (Norwegian bokmål) plus a
`UI` table of chrome strings per language, and `pick_language()` selects from the computer's
locale (`LANG`/`LC_ALL` on Linux, `Get-Culture` on Windows), English as the fallback. A test
asserts every English check id has a Norwegian entry, so one cannot ship without the other.

One Windows-specific trap handled: the `.ps1` is saved **UTF-8 with BOM**, or PowerShell 5.1
reads the å/ø/æ in the string literals as the system ANSI codepage and mangles them. English is
still the default; a Norwegian computer now gets a Norwegian report with no configuration.

## 6. Scope

New `src/aqelyn/collect/plain.py` (bilingual); rewritten report in `src/aqelyn/collect/selfscan.py`;
`plain.py` added to the zipapp build; the Windows `tools/aqelyn-selfscan.ps1` ported (and its
`HtmlEnc` bug fixed); tests updated. No change to `posture.json`, the pipeline, or any check
logic — this is entirely about how the customer-facing report reads.
