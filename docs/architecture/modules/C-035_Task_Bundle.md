# C-035 Batch Conformance (EA-0038 – EA-0050) — Implementation Task Bundle

**Milestone:** C-035 (batch conformance decision; **no modules, and by default no production code**)
**For:** Claude Code (implementer **and** reviewer during the Codex outage) · Codex (retroactive re-review on return)
**Prerequisites:** C-034 merged & green; **`EA-0038-0050_Batch_Conformance_Analysis.md` read**; **ECR-0060 (provisional number — re-read `ECR-LOG.md`, rule 1)** decided by the owner; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–21 read.
**Definition of Done:** every Disposition-A row confirmed against shipped `src/` at the current SHA; EA-0048's absence of an owner re-confirmed; EA-0050 classified; records landed; `ruff` clean; **`mypy --strict src tests`**; **`gh pr checks <n>` confirmed PASS before merge**; **zero new packages, services, scorers, or event namespaces**; Claude Code sign-off with self-verification disclosure.

**Read the analysis §1 first.** This batch replaces thirteen conformance passes
with one decision — **but it is a decision about how to record outcomes, not a
licence to skip the capability map.** EA-0048 is the proof: it is the one item
where the same-generator heuristic gives the *wrong* answer, and a batch that
skipped the map would have certified that AI security is already owned.

**Three dispositions, not one:**

- **A — conformant via shipped owners:** EA-0038, 0039, 0040, 0041, 0042, 0043,
  0044, 0045, 0046, 0047, 0049 *(eleven)*
- **B — open capability gap, not scheduled:** **EA-0048** (AI Security & Model
  Governance)
- **C — non-capability:** **EA-0050** (Platform Implementation Blueprint),
  alongside EA-0051

> **Forbid list, all rows:** no package under `src/aqelyn/`; no second engine,
> composer, or scorer; **no parallel event namespace**; no new `SignalKind`; no
> capability that acts. **Do not schedule EA-0048** — recording a gap is not
> approving a build.

---

## N1 — Verify the eleven Disposition-A rows

**Source:** analysis §2, §7.1.
**Deliverable:** for each of the eleven, confirm against shipped `src/` at the
current SHA: the **owning package**, and the **API or docstring** that realizes
the archive's stated capability. Record the evidence per row in the analysis.

**Proportionality is deliberate.** These are restatements of owners already
certified by their own milestones, and **GC-001/GC-002 provide the mechanical
backstop** — a wrong row that someone later builds on fails
`test_gc_engine_discovery_complete`, the scorer registry, or
`test_gc_negative_control_unowned_prefix`. So **no eleven chain proof tests.** A
row is confirmed by pointing at shipped code, not by re-proving the owner.

**Two rows carry verbatim/near-verbatim title matches** — EA-0039 → **EA-0014**
(*"Threat Intelligence Fusion Engine"*) and EA-0041 → **EA-0019** (*"Security Data
Lake & Telemetry Platform"*, which already owns both the `lake` and `telemetry`
prefixes). Confirm these first; they are the strongest signal and the cheapest
checks.

**Any row that fails becomes its own conformance pass** — not a footnote, and not
a reason to build a module.
**Acceptance:** `test_batch_disposition_a_owners_present` (or an equivalent
evidence record if a test is disproportionate — reviewer's call, stated either way).

## N2 — The two exceptional dispositions

**Source:** analysis §3, §4, §7.2–7.3. **These are where a false negative is
expensive**, so they get more care than the eleven.

**EA-0048 — confirm the gap is real.** Re-run the ownership grep at the current
SHA (`model_governance`, `ai_security`, `model_card`, and equivalents) across all
packages. A single false negative here is the difference between a recorded gap
and a wrongly closed one.

**Guard the false friend:** **EA-0020 "AI Decision Intelligence Engine" is not the
owner.** EA-0020 is AI used *by* AQELYN (replayable derivations, recommendations);
EA-0048 would be governance *of* customer AI/ML systems. Opposite directions —
confirm explicitly that EA-0020 was considered and rejected as owner, so the
record shows the question was asked.

**Record it as an open capability gap, not scope** (analysis §3.2). The archive
names the capability and specifies nothing about it; requirements would come from
the owner, not the stub.

**EA-0050 — classify as non-capability**, alongside EA-0051. No conformance claim;
asserting one would be a category error.
**Depends on:** N1.
**Acceptance:** `test_batch_ea0048_no_owner`, plus recorded classification for
EA-0050.

## N3 — Rule 20 sweep and records

**Source:** analysis §5, §7.4–7.5, §8.
**Deliverables:**

- **Rule 20 sweep** — confirm no archive item's scope was inherited from a
  same-numbered ECR, Blueprint volume, or index row. **EA-0040 is the live
  collision**: the archive's *Attack Path & Exposure Graph Engine* versus
  **ECR-0040**, the optimistic-default precedent cited throughout C-034's records
  — bidirectional, and in active documents.
- **Records** — the batch analysis with per-row evidence filled in; the ECR (§ECR
  number per rule 1) carrying the three dispositions; README rows for the batch,
  EA-0048 (gap), and EA-0050 (non-capability).
- **Mark the archive exhausted as a requirements source** (analysis §8), and
  restate the tracked backlog so the next decision starts from it rather than
  from the archive.

**Depends on:** N2.
**Acceptance:** records landed; no test required.

---

## Review protocol (Claude Code)

1. **No modules, no code.** Confirm zero new packages, services, scorers, or event
   namespaces. Delivering a decision and records with no production code is the
   **expected** outcome, not an under-delivery.
2. **The map actually ran.** Each of the eleven has evidence recorded — a package
   and an API/docstring — not an assertion that it "obviously maps."
3. **EA-0048's gap is confirmed, not assumed** — grep re-run at the current SHA,
   and **EA-0020 explicitly considered and rejected** as owner (analysis §3.1).
4. **EA-0048 is not scheduled.** A recorded gap is not an approved build; the
   record says requirements would come from the owner, not the stub.
5. **EA-0050 is classified, not certified.**
6. **Rule 20 sweep clean** — especially the EA-0040 / ECR-0040 collision.
7. **GC-001 and GC-002 still green** — they are the backstop this batch's
   proportionality depends on (analysis §1.1). If either is red, the batch's
   verification budget is no longer justified and the rows need heavier proof.
8. **Rule 21** — if any mutation testing is done here, mutate consumers as well as
   producers.
9. `mypy --strict src tests`; `gh pr checks` PASS before merge.
10. **Self-verification disclosure** — with one actor implementing and reviewing,
    state on merge which checks were independently constructed and which were
    self-verified, so Codex's retroactive review knows where to look first.

**Preserve, do not absorb:** **ECR-0034's open cursor half (next item after this
milestone, per the owner's sequence)**, ECR-0032 (shared posture base), EA-0018
unclamped-duration flake, EA-0027/EA-0018 enterprise health probes, EA-0013
equal-timestamp tie-breaker, and **EA-0048** as a recorded gap.

Merge only on green; then **report back to the owner**. The next scheduled work is
**ECR-0034 cursor pagination** — the half that lets a >10 000-asset tenant be
answered rather than correctly refused.
