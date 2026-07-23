# C-033 IS-036 Conformance — Implementation Task Bundle

**Milestone:** C-033 (IS-036 conformance; **no new module, and by default no new code**)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-032 merged & green; **`IS-036_Conformance_Analysis.md` read**; **ECR-0055** decided by the owner; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–18 read; **`src/aqelyn/workflow/` (EA-0008) and `src/aqelyn/response/` (EA-0018) read before writing anything.**
**Definition of Done:** K1 green on in-memory **and** Postgres **and both tenant modes**, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; worktree `pytest` with `PYTHONPATH=$PWD/src`; **`gh pr checks <n>` confirmed PASS before merge**; **zero new execution paths**; Claude Code sign-off.

**Read `IS-036_Conformance_Analysis.md` first.** Two things make this milestone
unlike every previous one:

1. **The archive master is a template**, not a specification — no components, no
   interfaces, no requirements, no acceptance criteria. **Nothing may be built
   from its section headings.** A requirement written from a template heading is
   invented scope wearing the archive's authority.
2. **The capability ships**: EA-0018 `ResponseOrchestrationEngine` over EA-0008
   `WorkflowEngine`. This milestone's normal, expected, *correct* outcome is
   **a conformance record and no production code at all.**

> **The non-negotiable.** `autonomous` is 0 hits in `src/` **by design**. The
> archive's title word may only mean *the orchestration flow is automated* —
> **never execution without a human approving via `WorkflowEngine.approve`.**
> If anything in this milestone introduces an un-gated execution path, that is the
> defect, and it outranks every other consideration here.

**Forbidden artifacts:** `src/aqelyn/autonomous_remediation/`,
`src/aqelyn/remediation_orchestration/`, any second `*_engine` service, any second
campaign model, any `aqelyn.autonomy.*` namespace. If one appears, stop and raise
an ECR.

---

## K1 — Conformance verification (mandatory; the whole milestone by default)

**Source:** `IS-036_Conformance_Analysis.md` §2.
**Deliverable:** a conformance record proving remediation orchestration ships,
exercised against **real engines** — spies prove delegation, only the real engine
proves the capability.

Required exercises:

- **Campaign path:** drive the real `ResponseOrchestrationEngine.plan_campaign(...)`
  → `advance(...)` across phases; show the campaign **sequences proposals** and
  does **not** itself execute.
- **Gated action path:** drive the real `WorkflowEngine.propose(...)` →
  `approve(...)` → `execute(...)`; show execution happens **only** after approval.
- **Refusal path:** an **eligibility-`none`** finding-driven run is **structurally
  refused execution** — proven against the real `gating.py`, and under
  `python -O` (assertion-stripped builds must still refuse).
- **Binding:** a finding-driven proposal carries `source_finding` and
  `requires_approval=True` (rules 7, 16).

Any row of §2 that fails becomes a ticket here — **not** a reason to build a
module.
**Acceptance:** `test_is036_conformance_campaign_sequences_not_executes`,
`test_is036_conformance_gated_execution_after_approval`,
`test_is036_conformance_eligibility_none_refused`,
`test_is036_conformance_eligibility_none_refused_dash_o`,
`test_is036_conformance_source_finding_bound`.

## K2 — Read-only remediation plan view *(OWNER-GATED — DO NOT BUILD BY DEFAULT)*

> **Build this ticket only if the owner has explicitly approved it in writing.**
> The archive specifies no gap; this is a candidate, not a requirement. Absent
> approval, C-033 is K1 only, and that is a complete and correct milestone.

**If approved:** a **read-only** view composing *proposed* (never executed)
EA-0008 runs and EA-0018 campaigns across engines into one evidence-backed,
replayable plan record. Additive, inside the existing owner packages. It emits
only `requires_approval=True` proposals, holds **no execution capability**, and
adds **no new actor**.
**Acceptance (if built):** `test_is036_plan_view_readonly`,
`test_is036_plan_view_no_execution_capability`,
`test_is036_plan_view_replayable`.

---

## Review protocol (Claude Code)

**Ask this first, before correctness:** ***can anything here execute without a
human?*** Then:

1. **No un-gated execution.** Every execution path traces to
   `WorkflowEngine.execute` **after** `approve`. Attempt to reach execution
   without approval and assert refusal — under `python -O` as well.
2. **The six breach mechanisms** (analysis §3.1) — confirm **none** is present:
   - policy **auto-approval** (EA-0009 authorizes; it does not approve);
   - **pre-approved / standing** approval for a class of runs;
   - a **non-human approver** (`ActorRef` for a service account, agent, or the
     decision engine);
   - **break-glass / emergency** bypass;
   - **batch approval** covering multiple runs;
   - **`advance()` executing** a phase's actions without their own gates.
   Also: a **rollback is an action** (needs its gate), and a **"dry run" that
   touches real systems is not a dry run**.
3. **No second orchestrator.** No new package, service, campaign model, or event
   namespace; no shadowing of `WorkflowEngine` / `ResponseOrchestrationEngine`.
4. **Conformance uses real engines** (K1), not spies or grep.
5. **No invented scope.** Reject anything traceable to a template heading rather
   than to shipped code — including in this bundle. If K1 alone is delivered with
   no production code, that is the **expected** result, not an under-delivery.
6. **K2 not built** unless the owner approved it in writing; if built, it holds
   **no execution capability**.
7. **ECR-0034 not weakened** — keep coverage honest if any orchestration reads
   EA-0025 inventory.
8. **Rule 18 sweep** — any Protocol change updates every implementer including
   test doubles; `mypy --strict src tests` (not `src` alone).

**Preserve, do not absorb:** ECR-0032 (shared posture base, four instances),
ECR-0034 (inventory cap), EA-0018 unclamped-duration flake, EA-0027/EA-0018
enterprise health probes, EA-0013 equal-timestamp tie-breaker.

Merge only on green review with `gh pr checks` confirmed; then **report back to
the owner** — including, per the analysis §1.2, whether the **next** archive
master is real content or another template.
