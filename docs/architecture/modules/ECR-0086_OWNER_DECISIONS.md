# ECR-0086 — Owner decisions (acceptance addendum)

**From:** claude.ai (spec author), deciding under explicit owner delegation of 2026-08-01
**To:** Claude Code (reviewer/merger), then Codex (implementation)
**Applies to:** ECR-0086 at `main @4de8724`, currently **Proposed**
**Effect:** With this record committed, ECR-0086 moves **Proposed → Accepted**.

---

## 0. Basis for deciding

The relay bundle deliberately left these two decisions with the owner, on the ground
that a general delegation does not cover a risk acceptance. The owner has since
delegated **these two named decisions specifically**, after the ECR surfaced what each
involves. That is an informed delegation of identified decisions, not a blanket one,
and it is exercised here. The reasoning for each decision is recorded so the owner —
or anyone after — can audit or reverse it as a decision of record, not archaeology.

---

## 1. Decision — EA-0054 Web Intelligence: **not built**

**Disposition: open capability gap, not scheduled** — the EA-0048 precedent, verbatim.
This is a deferral with preconditions, not a rejection.

EA-0054 is the only genuine first-socket crossing in the batch: it reaches across a
network to hosts that have handed nothing in. Building it before the platform has
authorization semantics would turn "scan only what you are permitted to scan" from an
enforced obligation into a comment. It stays unbuilt until **all three** of the
following hold:

1. **A surface exists.** The roadmap's honest column no longer reads "no way in, no
   way to see." Assessment engines without a surface repeat the ordering failure the
   S-track exposed.
2. **The handed-in pattern is proven in shipped code.** EA-0052 → EA-0053 (as bounded
   by Decision 2) have shipped and demonstrated the platform's assessment shape on
   endpoint data end to end.
3. **Authorization semantics are specified first.** Scope enforcement, consent
   verification, and target-authorization evidence are designed and reviewed as
   runtime obligations — with the same fail-closed shape as the platform's other
   guards — *before* any EA-0054 implementation begins.

**Re-proposal mechanics:** when the preconditions hold, EA-0054 returns as a **new
ECR** with its own number, citing this record. It is not revived by editing this one.
Nothing in a future EA-0052/0053 acceptance implies anything about EA-0054.

## 2. Decision — EA-0052-FR-004 (resident agent): **not authorized**

EA-0052, whenever it is scoped, is bounded to the **handed-in descriptor path**:

- the collector runs on the machine being assessed, executed by that machine's owner;
- privilege is the owner's, once — the S-004 conclusion, which covers exactly this
  path and nothing more;
- output returns to the platform as handed-in descriptors (the S-003 pattern, already
  proven on a real estate);
- nothing resident, nothing that phones home, no socket opened by AQELYN code in
  either direction.

FR-004's cross-platform agent is outside that boundary — an agent that ships
telemetry back opens a socket from the agent side, and it changes the collector from
something the owner runs into something that runs on the owner's machine. Those are
different risk acceptances. **FR-004 does not inherit any future EA-0052 approval.**
If a resident agent is ever wanted, it arrives as its own decision under its own ECR,
with the socket question and the residency question answered separately.

This keeps the F1 sentence true one level down: *a disposition attaches to a
requirement, not a document number* — and so does an authorization.

## 3. Acceptance obligations carried by this record

Per the reviewer's merge note, acceptance must carry the milestone or §5's own stated
failure mode applies. Therefore, the same pass that flips the status to Accepted must
queue:

1. **The three three-branch absence guards** for EA-0052, EA-0053, EA-0054 — each
   branch with a unique witness test, per the PR #283 standard. The EA-0054 guard is
   permanent for as long as Decision 1 stands; the EA-0052/0053 guards stand until
   those modules are scheduled and shipped.
2. **Guard vocabulary must cover the new domains.** `EA0048_OWNERSHIP_TERMS` is AI
   vocabulary only; the endpoint and web nets need their own term sets (endpoint,
   telemetry, agent-enrolment, process-inventory family; TLS/DNS/HSTS/DKIM/DMARC/CSP
   family), stated with the same honest limit already recorded: the net catches
   anticipated-or-conventional vocabulary or explicit declaration, not any capability.
3. **Status-line hygiene, small and optional but cheap now:** the reviewer's
   observation that 45 of 86 bodies carry no `**Status:**` line (ECR-0060 included)
   is not a defect, but adding the line to ECR-0060 while its supersession is being
   touched costs one edit and removes one "census reads as coverage" ambiguity.

## 4. What this record does not decide

- Nothing here schedules EA-0052 or EA-0053. Their disposition remains *open
  capability gap*; scheduling is a separate, later decision. When it comes, the
  recommended order stands: EA-0052 → EA-0053, collection before analysis.
- Nothing here writes or authorizes module specs for any of the three.
- Nothing here touches Dispositions A or C, the record corrections, or the
  standards-conformance read owed on EA-0058/0060/0061 — all already carried by
  ECR-0086 as merged.

**Status update (ECR-0087, 2026-08-02):** that read was performed and is closed. The three
documents are a third generator-template family with no topic-specific normative content.

---

## 5. Ball

**Next: Codex** — one pass: commit this record to `docs/` (or the ECR annex location
Claude Code prefers), flip ECR-0086 status to **Accepted — decisions recorded in
ECR-0086_OWNER_DECISIONS.md**, and implement the three absence guards per §3.
**Then: Claude Code** reviews the guards against the three-branch/unique-witness
standard and merges. Nothing further is queued with the owner.
