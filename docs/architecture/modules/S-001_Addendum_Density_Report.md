# S-001 Addendum — The Density Report under a Refusal Discipline

**Amends:** `S-001_Task_Bundle.md` §S3, Deliverable 2
**Status:** specification, for the actor resuming S-001
**Why this exists as a file:** the specification below was worked out in
conversation and would otherwise survive only there. The actor resuming S-001 will
have fresh context and no access to it — the same reason rule 20 exists.

---

## 1. Why the report needs a specification at all

The density report is **not diagnostics**. It is a **decision artifact**: it
chooses what S-002 connects. Everything else S-001 produces can be re-run cheaply;
this one output determines the next milestone's target.

The reviewer found the current implementation misreads the factor shape and prints
`known=0` with `?` reasons for everything. That is not a cosmetic bug, because:

> **A broken reporter and a genuinely all-unknown platform produce identical
> output.**

`known=0, reasons=?` is exactly what a **correct** report would show if the
platform truly knew nothing — and given reachability, ownership and exposure are
unwired, *that is the plausible real answer*. **The camouflage is maximal precisely
when the answer matters most.**

## 2. Three states, not two

| State | Means |
|---|---|
| `known` | the factor resolved to a value |
| `unknown` | **the platform** could not determine the factor — carries its reason |
| `undetermined` | **the reporter** could not read the factor's status |

The first two are the platform speaking. The third is the **tool** speaking, and
conflating them is the whole defect.

## 3. The discipline: refuse, do not render

**Distinct rendering is not sufficient.** If `undetermined` prints alongside
`unknown` in the same table, the camouflage returns in a quieter form: a reader
scanning a column of non-`known` entries has no way to parse which rows are the
platform's answer and which are the tool's failure.

> **The reporter SHALL refuse to produce a report when it cannot read its input.**

This is the same discipline the platform already holds in two places:

- **EA-0030's SBOM quarantine** — a partial SBOM is refused, not partially
  ingested.
- **GC-001 §7** — an unclassifiable package **fails, it is not skipped**, because
  skipping recreates the gap silently.

And the reason is the same in all three: **a partially-readable decision artifact
is worse than none, because it presents as a basis for the decision it is
corrupting.**

### What "refuses" means concretely

- If **any** factor on **any** finding cannot be read, **no report is produced.**
- The failure names **which finding, which factor, and what the reporter
  observed** — enough to fix it without re-running the scan.
- It does **not** emit a partial report with a warning header. A warning above a
  table is read by nobody and does not survive being pasted into a decision.

**Consequence for the current bug:** the present failure mode is total — every
factor `undetermined`. Under this discipline that produces an immediate,
diagnostic refusal instead of a plausible-looking all-unknown table. **That is the
improvement**: the bug becomes loud instead of camouflaged.

## 4. Testing the reporter — the part that is easy to get wrong

**The reporter cannot be validated against the platform's live output**, because
the live output is what it is being used to measure. A reporter that prints
`known=0` for everything agrees perfectly with a platform that knows nothing.

> **The reporter SHALL be tested against a corpus whose known/unknown split is
> known in advance**, so its output can be checked against ground truth rather
> than against the thing it measures.

A small hand-built corpus is correct here and is **not** a fixture-shape violation
(rule 27) — the point is not to simulate real data, it is to have a known answer.
Cover at minimum: a readable `known` factor, a readable `unknown` factor with a
reason, and an unreadable factor.

**Negative control (rule 24):** feed a factor shape the reporter cannot parse and
confirm it **refuses** — not that it prints a `?` row. A test that only exercises
readable factors passes against the current broken implementation.

## 5. What the report contains

Per factor, across all findings:

- count `known`
- count `unknown`, with the **reasons grouped and counted**
- ordered by **`unknown` count descending**

Plus totals: findings evaluated, factors evaluated.

### The ordering is the recommendation — do not editorialize

The report **SHALL NOT** contain interpretation, commentary, or a suggested next
step. Ordering by unknown-density **is** the roadmap; adding a recommendation on
top would be the tool making a decision that belongs to the owner, and it would
obscure the one property that makes the ordering trustworthy — that it is
mechanical.

## 6. What this does not change

S-001's success criteria stand unchanged. Criterion 4 — *the density report is
produced* — is satisfied by a **refusal** when the input cannot be read: the
report was correctly not produced. It is **not** satisfied by a report that was
produced despite unreadable input.

The remaining S-001 item, the **second dedup run** (bundle §S4), needs no further
specification: same inputs, confirm findings deduplicate rather than double, and
confirm `last_detected_at` advances while `severity_score` does not — making
**ECR-0063** concrete on a real corpus.
