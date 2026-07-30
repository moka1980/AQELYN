# P-001 — A Way In and a Way to See — Task Bundle

**Track:** P (product) — **new**, per ECR-0081
**Milestone:** P-001 (the smallest change that makes the platform usable by a person)
**For:** Codex (implementer) · Claude Code (reviewer + merge) · the **owner** (the acceptance test)
**Prerequisites:** S-004 merged (`main @f2c573c`); **ECR-0081 read in full** — especially §2, which says which of this project's disciplines apply here and which do not.
**Definition of Done:** one command produces one report; a person who did not build it can answer the four questions in §Acceptance; unknowns render with their reasons; `mypy --strict src tests`; `gh pr checks` PASS.

---

## This bundle is deliberately short

**ECR-0081 §2 says design choices cannot be verified against shipped code.** A bundle that
specified every layout decision would be asserting exactly the kind of claim it just said
nobody can check.

**So: hard constraints where they matter, and judgement where judgement is required.** If a
decision below is stated, it is because getting it wrong would break something the platform
has spent forty-one milestones protecting. Everything else is the implementer's.

---

## Q1 — The entry point

`src/aqelyn/__main__.py` is an explicit placeholder and `[project.scripts]` already points
at it. **The driver exists.** Wire them.

**Minimum surface:** one command that takes a directory of collection documents and writes a
report. Plus `--reuse`, whose semantics ECR-0080 has now pinned.

**Not a CLI framework.** Subcommands, config files and plugin systems are `C-700`, not this.

**Acceptance:** the command runs from a fresh install and produces a report.

## Q2 — The findings report

**Format: a local HTML file.** No server, no port, no deployment — write it to disk, open it
in a browser. That is the minimum that renders a derivation legibly, and terminal output
cannot.

### Four constraints, each protecting something already paid for

**1. The caveat travels with the claim.**

Every finding shows what was found, **and** the unknowns that qualified it, **in the same
place**. Not a coverage section at the end that a reader skips.

> The platform's distinguishing behaviour is saying what it cannot determine. **A report
> that puts findings first and unknowns in an appendix has un-built that**, however
> accurate both halves are.

**2. The derivation is viewable, and legible.**

This is the differentiator and it has never been visible. Raw JSON fails — a reader must be
able to follow **why this number and not another**, including which factors were excluded
and why.

> *"Priority 30.8 — CVSS 7.3 known; exploitation unknown, no provider matches this identity;
> exposure unknown, no surface signal…"* — with the unknowns **visibly excluded from the
> calculation** rather than silently scored.

**3. The report must not read as though anything was done.**

The platform **proposes**; EA-0008 is the only actor and requires human approval. A
remediation shown as a completed action, or phrased as though the platform will carry it
out, contradicts the §0 boundary in the one artifact a user actually reads.

**4. Two reports, two boundaries (ECR-0069).**

| report | contains | may it leave the machine? |
|---|---|---|
| **findings** (this one) | asset names, versions, paths | **no** — local only |
| **density** (exists) | counts and reasons | yes |

**Do not merge them.** The findings report is for the operator, on their machine. Blurring
the two would put per-asset detail into the artifact designed to be shared.

**Acceptance:** a finding renders with its derivation and its unknowns; the density report is
unchanged and still count-only.

## Q3 — Packaging

It installs and the entry point works from the install, not only from a checkout.

**Acceptance:** `pip install .` then run the command.

---

## Acceptance — the test is a person, not a suite

> **Can someone who did not build this read one finding and answer:**
> 1. **What is the problem?**
> 2. **How bad is it, and why?**
> 3. **What do we not know?**
> 4. **What would I do about it?**

**Four yeses is the milestone.** Not test count, not coverage, not finding count.

**Record who read it.** The owner reading it is a **weaker test than a stranger reading it**,
because the owner already knows what the platform does. That does not make it useless — it
is the reader who is available — but **record it as the weaker test it is**, and do not treat
it as evidence that the report is legible to a newcomer.

**If a question cannot be answered, that is the finding.** It is a report defect, not a
reader failure.

### Acceptance record — protocol item 8

**Date:** 2026-07-30. **Verdict: accepted.**

**Who read it:** the **project owner** (GitHub `moka1980`), recorded at their own instruction.
They did not build the report — Codex implemented it, Claude Code reviewed it — so they satisfy
*"someone who did not build this."*

**What they read:** the real-corpus run of the merged implementation (`main` @ `879bdcd`), the
one that wrote **10,173 local findings** from the owner's actual estate, with 50,394 unknown
factors disclosed in the headline. Not a sample, not a constructed example.

**Recorded verbatim:** *"I read p-001 and is good … I accept it."*

**Three things this record does not claim, stated here so nobody later reads more into it:**

1. **The four questions were not transcribed individually.** The owner returned a single overall
   judgement, not four separate yeses. What is attested is acceptance by the reader, in aggregate.
   Which finding they read is not recorded.
2. **This is the weaker test, exactly as this section predicted.** The owner already knows what
   the platform does. Per the paragraph above: *do not treat it as evidence that the report is
   legible to a newcomer.* **The stranger read remains unrun**, and remains the stronger test
   whenever a stranger is available.
3. **The reader did not find ECR-0082.** The scoring inversion the first real run exposed was
   found by the reviewer, reading the rendered derivation. The report made it visible; the
   acceptance read is not what surfaced it, and this record must not be cited as though it were.

**What it does establish:** the milestone's own acceptance mechanism was run on a named person
rather than declared satisfied by a test suite, which is the only thing item 8 ever asked for.

### Second acceptance read — the corrected report, 2026-07-30

**Verdict: accepted.** Same reader (the project owner), on the report regenerated after the
EA-0024 scoring repair (ECR-0082 + ECR-0083). **Recorded verbatim:** *"I read the corrected
report -> accepted."*

**This was a materially different artifact from the first read, and that is the point of
recording it separately.** The first read was of an estate where 114 findings rendered
`Immediate 90.0`. After the repair the same estate reads **10,168 Low / 5 Medium / 0 High /
0 Immediate**, and the one KEV-confirmed exploited vulnerability is **first by score of 10,173**.
The report a reader opens changed more between these two reads than between any two milestones.

**Which artifact this record refers to.** The read is anchored to a hash rather than a
description, because three renders exist and only one survives:

| render | hash | status |
|---|---|---|
| 13:28 | — | reviewer-generated; **93.2% of findings failed their own visible addition**; overwritten |
| 13:48 | `0f830239…` | summary line reconciled; the **Contribution column still did not** |
| **14:44** | **`03d27643…`** | **current** — column, subtotal, surcharge, total and heading all reconcile |

**The substance across those renders is identical** — same corpus, same engine, same 10,173
findings, same scores, same unknown disclosures. What changed is which tenth is printed in the
Contribution column. So the acceptance is not invalidated by the supersession, but the record
names the artifact that still exists rather than one nobody can reproduce.

**What this second record still does not claim.** The four questions were again not transcribed
individually, and **the stranger read remains unrun** — the owner remains the weaker reader this
section predicted, and the estate's new shape makes the stronger test more valuable, not less:
"nothing is urgent" and "the tool found nothing" look identical to someone seeing it for the
first time, and only the rendering distinguishes them.

## What is explicitly out of scope

No server · no HTTP API · no authentication · no accounts · no multi-user operation ·
no connectors · no dashboard · no new engines · no scheduling.

**Those are `C-700` and they remain unbuilt.** P-001 needs none of them.

## Review protocol (Claude Code)

**Note that most of your usual instruments do not apply here**, and that is expected.
Mutation testing cannot answer *"is this legible?"* Check these instead:

1. **Unknowns render, with reasons, beside the claims they qualify** — not in an appendix,
   not omitted because the report looks better without them.
2. **The derivation is viewable and followable** — a reader can see which factors were
   excluded and why.
3. **Nothing reads as though the platform acted.** Proposals are proposals.
4. **ECR-0069 holds** — the findings report is local-only; the density report is unchanged
   and still count-only; the two are not merged.
5. **Nothing invented** — no placeholder findings, no sample data, no illustrative numbers.
6. **Scope held** — no server, no auth, no dashboard.
7. `mypy --strict src tests`; `gh pr checks` PASS.
8. **The acceptance test was run on a person**, and who they were is recorded.

---

## Carried forward, unaffected

**C2/C3 collection scope** — cheap, needs no privilege, and changes ECR-0070's command
contract, so it needs its own ECR. **The 19 declined units** — the owner's modelling
question. **EA-0048** and the three first-deployment items.

**After P-001**, the honest column reads differently: there will be *a* way in and *a* way to
see — for one person, on one machine. **`C-700` is what makes that true for anyone else.**
