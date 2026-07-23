# IS-036 Conformance Analysis — realized by shipped EA-0018 + EA-0008

**Subject:** IS-036 — Autonomous Remediation Orchestration Engine
**Finding A:** the archive master is a **near-empty template**, not a specification.
No components, interfaces, requirements, lifecycle, or acceptance criteria exist
to reconcile against.
**Finding B:** remediation orchestration **already ships** — **EA-0018**
`ResponseOrchestrationEngine` (multi-step campaigns) over **EA-0008**
`WorkflowEngine` (the platform's only actor: capability-, eligibility-, and
approval-gated).
**Recommendation:** mark IS-036 **conformant via EA-0018 + EA-0008**. Build **no**
EA-0036 module. Any net-new capability must be justified against shipped code and
must stay inside `propose → gate → approve`.
**Change control:** **ECR-0055** *(next free per the handover — the log ends at
ECR-0054; re-read `ECR-LOG.md` before assigning, rule 1).*
**Status:** Proposed — owner decision.

---

## 1. Finding A — there is no specification here

The master's twelve objectives are literal placeholders (*"…objective 1"* through
*"…objective 12"*), the purpose sentence is grammatically broken, and every
section repeats the same boilerplate. There are **no `ARC-036-*` components, no
interfaces, no `REQ-*` requirements, no acceptance criteria.** One substantive
sentence exists: *"coordinates safe, policy-bound remediation actions across
AQELYN engines, workflows, evidence, and trust context."*

### 1.1 Why this changes what a spec pass may do

For every prior module, the archive stated intent, and the spec author's job was
to **reconcile** that intent against shipped code. Here there is no intent to
reconcile — so the usual epistemics invert:

> When a real master is silent on a boundary, silence is ambiguous.
> When the master is a **template**, there is no specification at all — and every
> requirement written from its headings is **invented by the drafter**, not
> derived from the archive.

A spec produced from section headings would therefore be **manufactured scope
wearing the archive's authority**. The headings would supply the shape, the
drafter would supply the content, and the result would read as though the project
had asked for it. **Nothing in this analysis is derived from the template**; the
conformance below is grounded in shipped code alone.

### 1.2 A note on the batch

EA-0036 opens a new archive batch (`EA-0036_EA-0050`). One template does not prove
fifteen, but it does retire the assumption that an archive master contains
content. **"Is this archive real content?"** should be the first check for each
remaining module, before the ECR-0015 capability check — cheap, and it decides
whether a spec pass is even possible.

## 2. Finding B — the capability ships, verified against `src/`

```
Playbook 202 · propose 179 · requires_approval 47 · eligibility 32 · WorkflowEngine 23   (EA-0008)
response.*campaign 109 · aqelyn.response 40                                              (EA-0018)
autonomous 0
```

| Archive phrase | Shipped owner / seam |
|---|---|
| coordinates remediation actions | **EA-0018** `ResponseOrchestrationEngine.plan_campaign` / `advance` / `propose` |
| *safe, policy-bound* action | **EA-0008** `WorkflowEngine.propose` / `approve` / `execute` — capability + eligibility + approval gates |
| across AQELYN engines | owner `*_to_findings` → EA-0013 finding path |
| policy | **EA-0009** `PolicyEngine` |
| decision / sequencing | **EA-0020** `recommend`, replayable `Derivation` |
| evidence · trust · mission | **EA-0004** · **EA-0006** · **EA-0007** |

Fourth distributed-conformance case (IS-026 → EA-0012; IS-034 → several owners;
IS-035 → EA-0032; IS-036 → EA-0018+EA-0008).

## 3. "Autonomous" is a safety landmine, not a feature request

`autonomous` returns **0 hits in `src/`, by design.** Every engine is
detect-and-propose; eligibility-`none` findings are *structurally* unexecutable in
`gating.py`. The only legitimate reading of the archive's title word is that **the
orchestration, evidence, decision, and sequencing flow is automated** — never that
execution happens without a human approving through `WorkflowEngine.approve`.

### 3.1 The six ways a plausible-sounding spec breaches this

This is the specific risk of IS-036: not an obviously-wrong spec, but a
**reasonable-sounding** one. Each of the following reads like sensible
engineering and each is a breach. All SHALL be refused:

1. **Policy auto-approval** — *"low-risk actions are auto-approved per policy."*
   EA-0009 **authorizes**; it does not **approve**. Making a rule the approver
   removes the human from the loop while keeping the vocabulary.
2. **Pre-approved playbooks / standing approval** — approval granted in advance
   for a *class* of runs. Approval must attach to **this run, with this evidence**.
3. **Non-human approver** — an `ActorRef` pointing at a service account, an
   agent, or the decision engine. The approver must be a **human**; an AI
   approving an AI's proposal is the loop closing on itself.
4. **Break-glass / emergency bypass** — urgency as grounds to skip the gate.
   Urgency is precisely when un-reviewed automated action does the most damage.
5. **Batch approval** — one approval covering N runs, diluting the per-run
   evidence binding until the approval means nothing specific.
6. **`advance()` read as execution** — if advancing an EA-0018 campaign phase
   executes that phase's actions without their own EA-0008 approvals, the
   campaign becomes an un-gated executor. Campaigns **sequence proposals**; each
   action still passes its own gate.

Two adjacent traps worth naming: **rollback/compensation is an action** (an
"undo" still executes and still needs its gate), and a **"dry run" that touches
real systems is not a dry run.**

### 3.2 The bounded-autonomy mechanism already exists

EA-0018 already carries `max_effect: "read_only" | "reversible"` on automation
triggers. **Bounded autonomy is a shipped, gated concept** — there is no need for
a new mechanism, and a new one would exist outside the gate that makes the
existing one safe.

## 4. Why building EA-0036 anyway is harmful

A second orchestrator would produce two campaign models and two sequencing
authorities over **the same executor** — meaning two answers to *"what is this
system about to do to production?"*

But the specific hazard here exceeds the identity and crypto cases. Those
duplications produced **disagreement**; this one would produce **action**. A
second orchestration path is the single most likely place for an un-gated
execution route to appear, because orchestration is exactly where "just advance
the campaign" feels like coordination rather than acting. **EA-0008's status as
the platform's only actor is the foundational safety property of AQELYN**; a
module whose title contains "Autonomous" is where it would be lost.

## 5. Recommendation

1. **Mark IS-036 conformant** via EA-0018 + EA-0008, evidenced by **real-engine**
   exercises (drive `plan_campaign` → `advance`; drive `propose` → `approve` →
   `execute`; prove an eligibility-`none` step is **refused** execution) — not
   spies, not grep.
2. **Forbid** a second orchestration engine, workflow actor, or campaign model:
   no `src/aqelyn/autonomous_remediation/` or `remediation_orchestration/`, no
   second `*_engine` service, no `aqelyn.autonomy.*` namespace, and —
   non-negotiable — **no execution path that is not EA-0008-gated and
   human-approved.**
3. **Claim no gap.** The archive specifies none, and none was invented here. The
   burden is on any future proposal to justify net-new capability against shipped
   EA-0018/EA-0008.
4. **One owner-gated candidate, explicitly not assumed:** a **read-only
   remediation-orchestration view** composing *proposed* (never executed) EA-0008
   runs and EA-0018 campaigns across engines into one evidence-backed, replayable
   plan record — additive, emitting only `requires_approval=True` proposals.
   **Do not build without the owner's decision** (see C-033 K2).

**Verification note.** Every row in §2 must be confirmed against **shipped code**
with real engines before conformance is accepted. And per §3, the review's first
question is not *"does it work?"* but ***"can anything here execute without a
human?"***

## 6. C-033 K1 shipped-code verification

**Result:** the campaign, finding-binding, gated execution, and
eligibility-`none` rows hold against the real EA-0018 and EA-0008 engines. The
first pass also found two failed safety rows in shipped EA-0008:

- `WorkflowEngine.approve` accepted a non-human `ActorRef`;
- `WorkflowEngine.rollback` invoked handlers without a fresh human approval or
  capability preflight.

ECR-0056 repairs those gaps in the existing owner. The conformance suite now
drives:

- `plan_campaign` → unapproved `advance` refusal → exact-run human approval →
  completed `advance`, proving the campaign sequences the real workflow and
  cannot bypass its gate;
- `propose` → unapproved execution refusal → human `approve` → `execute`;
- a finding-bound eligibility-`none` run through approval to structural
  execution refusal, including in a `python -O` subprocess;
- rollback refusal without a fresh human approval, refusal of a system actor and
  stale execution approval, then one successful rollback after the exact
  rollback approval.

Every exercise runs on in-memory and Postgres stores in local and enterprise
tenant modes. No EA-0036 package, service, campaign model, event namespace, or
second actor was introduced; K2 remains unbuilt.
