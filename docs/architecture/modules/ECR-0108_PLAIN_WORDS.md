# ECR-0108 — Plain words beside the finding, never instead of it

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `9a2c498`.

> ⚠️ Ninth consecutive ECR by one actor. §7 lists what independent review should attack.

## 1. Finding of record

Recorded twice against my own work — ECR-0104 §5 item 4, then ECR-0105 §3:

> UX-008 is only half-served. Modes change disclosure depth; they do not change vocabulary,
> which is what Principle 2 (Simplicity First) actually asks for. A home reader still meets
> "listening sockets" and "loopback".

Twice deferred with a stated reason, which is the point at which a deferral starts to look
like a habit. This closes it.

## 2. Decision — the reason I deferred it is also the design

ECR-0105 §3 gave the reason for not doing it:

> rewriting finding text per audience is a separate change with its own risk — producing
> [plainer words] means a second rendering of the same fact, which is exactly where a
> "simplified" version drifts from a true one.

That risk is real and it has no witness: if a home sentence and an expert sentence are both
things we wrote, nothing can tell you when they stopped meaning the same thing.

So the plain language is **additive**. The finding's own sentence is never altered in any
mode; the technical terms it happens to contain are annotated beneath it. One rendering of
the fact, one source of truth, and Principle 2 served by explaining the vocabulary rather
than by replacing it. There is no second version to drift.

`glossary.py` holds 18 terms with definitions written for someone who has never administered
a machine. `_plain_words` renders them for **home and SMB only** — an enterprise or expert
reader knows the words, and a gloss under every sentence is noise that trains a reader to
skip the section.

Matching is case-insensitive and on word boundaries, longest term first, and a term already
covered by a longer match is suppressed: a reader shown "full-disk encryption" does not also
need "encryption" explained on the same line.

## 3. The invariant, and its witness

**The finding's sentence is byte-identical in all four modes.** This is asserted by rendering
**one analysis** four ways — not by building a fresh analysis per mode, which mints new
evidence ids and would compare different findings. ECR-0104 made exactly that mistake and it
is written down; making it again here would have produced a test that passes for the wrong
reason.

The mutation that matters is M8: a home reader served a reworded sentence. It is RED, and it
is the only cell in this ECR whose failure would be a lie rather than a missing feature.

## 4. Acceptance — 8 mutations, all red

Harness `~/AQELYN_ECR0108_PREP/matrix.sh`, purged cache.

Shortest term first so the better explanation is never offered; the word boundary removed so
"key" matches inside "monkey"; case sensitivity so a capitalised term is missed; suppression
removed; an expert reader glossed; the SMB reader losing plain words; the gloss computed and
never rendered; **and a home reader given a reworded sentence**.

Necessity: three deselection runs, all GREEN, including M8's sole catcher.

## 5. An existing absence guard caught me drafting a product we do not have

The first full-suite run failed on
`test_batch_disposition_b_capability_has_no_owner[ea0054]`. EA-0054 (Web Intelligence) is a
**recorded decision not to build**, and the guard exists to keep that true. My draft glossary
defined four web- and mail-intelligence terms, so the guard fired.

The guard was right and the glossary was wrong. AQELYN's shipped checks are listeners,
firewall, updates, automatic updates, disk encryption and SSH; none of them can emit those
four words. Glossing vocabulary no finding can produce is a glossary describing a product we
do not have. The four were removed rather than the guard weakened.

**It fired a second time on the comment explaining the removal.** The census is a text scan,
so naming the terms even in prose trips it. That is the guard working, and the comment now
describes them instead of listing them.

This exposed §7 item 1 as a real gap rather than a hypothetical one, so it is now measured:
of 18 terms, **8 appear in this machine's real rendered report**. The unreached ten are
mostly inflection variants of reached ones and vocabulary on the vulnerability path, which
this collection (zero CVE matches) does not exercise. A witness now asserts the glossary is
grounded in genuine check output at all — the property that had silently failed.

## 6. A second harness defect, same family as ECR-0105

M2 first ran **GREEN**, and it was not a real result.

The matrix computes some line numbers with `grep`. That lookup returned empty, `int("")`
raised, the applier exited 1 — and `lib.sh` only treated exit code **9** as "did not apply".
Everything else fell through to a pytest run on **pristine source**, reported as GREEN.

This is the second time this project has been bitten by a mutation that did not mutate. The
first was a wrong working directory (ECR-0100); this one is a wrong exit code. Both produced
a green tick that meant nothing.

`lib.sh` now:

- rejects a non-numeric or empty line argument up front (`BAD LINE ARG`)
- rejects a line number outside the file
- fails closed on **any** non-zero applier exit, not just 9
- re-checks the sha256 after applying and refuses to proceed if the file did not change

Verified by running the empty-line case deliberately: it reports `BAD LINE ARG`, not GREEN.
M2 re-run with a correct line number is RED.

## 7. What review should attack

1. **8 of 18 terms are grounded in real output** (§5). The gap is not alarming — the rest are
   inflections and vulnerability-path words — but nothing measures the *reverse* direction: a
   term the checks use and the glossary lacks is still invisible.
2. **A definition can be wrong and every test still passes.** `test_every_glossary_entry_is_a_real_explanation`
   checks shape — longer than the term, no circularity — not correctness. Someone who knows
   the domain should read all 18.
3. **The line is drawn at SMB.** That an enterprise reader wants no help is my assumption.
4. **Glossing is per level body**, so a term used in three levels is explained three times on
   one finding. Deliberate — a collapsed level a reader opens later should not depend on
   having read an earlier one — but it is repetitive in expert-heavy findings.
5. **English only.** The user's other products are Norwegian. Nothing here is translatable
   without a second glossary, and no mechanism exists for one.

## 8. Scope

New `src/aqelyn/reporting/glossary.py`, `_plain_words` and its CSS in
`src/aqelyn/reporting/html.py`, and a new `tests/reporting/test_plain_words.py` (15 tests).
No change to any finding, schema, or stored field — this is render-time only. Plus the
`lib.sh` hardening in §6, which is outside the repository.
