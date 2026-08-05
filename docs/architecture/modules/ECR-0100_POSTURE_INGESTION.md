# ECR-0100 — Posture ingestion: a second document the collection can carry

**Status:** Proposed — implemented, awaiting independent review.
**Raised and implemented by:** Claude Code, at the owner's direction while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `bddcc6d`.

> ⚠️ **This ECR was written and implemented by the reviewer.** No independent actor has seen the
> code. The separation of implementation and review is the only structural guarantee this project
> has, and it is suspended here, not satisfied. Section 6 records what that costs and what should
> be checked first when Codex returns.

## 1. Finding of record

The owner asked to see the platform. The shipped surface runs and renders correctly, and every
table is empty — the kernel is in-memory with nothing in it. Attempting to fill it exposed the
real gap.

**AQELYN could be told exactly one kind of thing: a CVE.** `reporting/analyze.py` accepted a
collection directory containing `vulns.json` (grype-shaped, required), plus optional `kev.json`
and `collection-manifest.json`. Nothing else had an ingestion path.

Passive observation of the owner's own estate produced six real facts — four application ports
bound to `0.0.0.0` beside the reverse proxy, absent HSTS on a site that already redirects, four
missing browser-hardening headers, DMARC published at `p=none` while SPF is already `-all`, a
version-disclosing server banner, and a certificate with 82 days remaining. **None is a CVE and
none will ever become one.** On a platform whose engine families are CSPM, DSPM, SSPM and ISPM,
there was no way to record any of them.

The vulnerability path itself is sound and was confirmed end to end during this work: a real syft
SBOM of 55 packages and a real grype run against an advisory database built the same day produced
**0 matches**. Zero is the measured result, not an absent scan.

## 2. Decision

Add `posture.json` as an optional second document in the collection directory, and an ingestion
path that turns each observation into a `Finding` raised through the real finding owner.

**Posture findings are kept as their own collection, not folded into `findings`.** A posture
observation has no CVE and no `VulnPriority`; `ReportFinding` couples every entry to both. Giving
a posture finding a hollow priority would model a claim that is not true, so `CollectionAnalysis`
gains a separate `posture_findings` tuple and the report renders a separate section.

**The zero is preserved.** `len(analysis.findings)` still counts only representable vulnerability
records, so a collection with posture observations and no CVEs still reports `0 local findings` —
and the CLI appends the posture count rather than inflating the first number.

## 3. What the document must carry

`Finding` requires seventeen fields, and four of them are why AQELYN is worth using:
`what_happened`, `why_it_matters`, `how_determined`, `risk_of_inaction`. The document is **refused**
when any is missing or blank, rather than back-filled at render time. A collector that cannot say
why something matters has not collected enough.

Two traps from the arc, both closed in code and witnessed:

- **`dedup_key` is derived from `(subject.ref, check, observation_id)`**, so a re-run of the same
  collection is idempotent while two observations of one subject stay apart. ECR-0094 lost a whole
  fixture to a shared dedup key collapsing N rows into one, silently.
- **`severity_score` is carried from the observation and never recomputed.** ECR-0063 keeps it
  fixed under escalation so the keyset cursor stays stable.

A repeated `observation_id` within one document is refused for the same reason.

## 4. Scope

New: `src/aqelyn/reporting/posture.py`. Changed: `analyze.py` (loader, `CollectionAnalysis`,
ingestion step), `html.py` (a section and its styles), `cli.py` (the summary line). No schema
change, no dependency, no loopback or GC posture change, no change to the vulnerability path's
behaviour. The keyset reads and the carried matrix are untouched.

## 5. Acceptance — 18 mutations, all red

Harnesses: `~/AQELYN_ECR0100_PREP/{matrix,pipeline}.sh`.

| block | mutations | result |
|---|---|---|
| validation guards — duplicate id, narrative required, severity vocabulary, score type, score range, non-empty list | 6 | 🔴 all red |
| dedup key — must vary, must include the check | 2 | 🔴 all red |
| finding construction — score carried, evidence linked, not auto-eligible, time from observation | 4 | 🔴 all red |
| pipeline — refusal fails the run, ordering by score, distinct evidence per observation, posture fingerprinted as a source | 4 | 🔴 all red |
| renderer — section omitted when absent, section rendered when present | 2 | 🔴 all red |

40 tests across two files. Gates: `ruff check` clean, `ruff format --check` clean,
`mypy --strict` clean across 579 files, full suite on live Postgres.

The carried matrix is **84** and is untouched by this change: no carried-control file is modified
and no carried fixture is amended, so rule 34's full-run trigger is not met.

## 6. What independent review should attack first

I wrote the code, the tests and this record, so the usual adversarial pass has not happened. In
Codex's place I would go at these:

1. **The tests were written alongside the code they test.** The mutation matrix is my evidence
   that they are not decoration, but a mutation matrix written by the same author shares its blind
   spots. Re-derive the mutations independently rather than re-running mine.
2. **`posture_dedup_key` truncates a sha256 to 32 hex characters.** I judged collision risk
   negligible at observation cardinality; that judgement is unreviewed.
3. **`automation.eligibility` is hard-coded to `not_eligible`.** Deliberate — nothing observed
   passively should be actionable without a human — but it is a policy decision embedded in a
   converter, and policy arguably belongs elsewhere.
4. **The renderer is untested for escaping of hostile observation text.** `_e()` is applied to
   every field, but I did not write a witness that proves it.
5. **`posture_findings` defaults to `()` on a frozen dataclass field.** Existing callers keep
   working, which is why the change is small — and also why a caller that forgets to pass it
   would silently render nothing.

## 7. Method note

🧠 **The empty dashboard was the finding.** Seeding plausible rows would have produced a
convincing screenshot and hidden the fact that the platform has no way to be told anything but a
CVE. Refusing to invent data is what surfaced it. The same instinct caught three harness errors
tonight — a stale grep window, a wrong mutation for a legally-unreachable tiebreak, and a
mutation script whose relative paths silently matched nothing and reported six false greens.
