# ECR-0103 — Charter v2 compliance for posture findings

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `9fe94d3`.

## 1. Finding of record

The owner pointed at `Project_AQELYN_Charter_v2_Product_Principles`, which I had not read. It is
approved, it is a pre-coding baseline, and §9 states its requirements are **mandatory
architectural requirements** applying to every finding, API, report and dashboard — not styling.

Reading it after implementing ECR-0100 through ECR-0102 was the wrong order. The audit:

**Already satisfied, by construction rather than intent.** Principle 1 (Explain Before You
Recommend) is enforced in code — the posture schema *refuses* an observation missing what-happened,
why-it-matters, how-determined or risk-of-inaction. Principle 3 (Evidence Before Opinion): every
observation carries an evidence record. Principle 6 (Transparency): the manifest states what was
collected, under what authority, and what was excluded. Principle 7 (Privacy First): local,
read-only, no network, `0600`. Principle 10 (Trust Through Engineering): the mutation discipline.

That the platform's own culture produced Charter compliance without the Charter being consulted is
worth noting — but it is luck, not method, and it did not extend to the communication layer.

**Violated:**

- **UX-001** — titles were machine strings: `listening_sockets_public on 85.190.101.232`.
- **UX-002** — `Finding.expert_details` exists in the model and the converter left it empty.
- **§5 Affected Assets** — `Finding.affected_object_ids` exists and was left empty.
- **Principle 5** — six progressive-disclosure levels specified; the report renders one block.
- **UX-008** — home / SMB / enterprise / expert communication modes do not exist.

## 2. Decision

Close UX-001 and UX-002 now; name the rest.

**`plain_title()`** derives a sentence a non-expert can read from `what_happened`, which is already
mandatory — so it cannot fall back to a machine string. An operator-supplied `title` wins.

**`expert_details()`** carries what the title gave up: check name, observation id, subject, and the
raw measurement. Progressive Detail levels 3–4. It deliberately does **not** repeat the narrative;
deeper levels add detail rather than restating the summary.

## 3. Affected Assets: not faked

`affected_object_ids` holds typed `obj_` ids. A posture subject — `wcagvakt.no`, `203.0.113.10` —
is not an object until something creates one. My first attempt put the raw reference there and the
model rejected it, correctly.

**Minting an id to satisfy the field would have produced a reference that resolves to nothing**,
which is worse than an empty list and precisely the kind of hollow compliance this Charter exists
to prevent. The subject travels in `expert_details` meanwhile. **ECR-0104 owes the object-store
link** — posture subjects becoming real objects is the honest fix, and it is a design change, not
a field assignment.

## 4. Still outstanding

- **Principle 5 progressive disclosure** in the rendered report and the surface. The data now
  supports it — `expert_details` is populated — but no UI consumes it as levels.
- **UX-008 communication modes.** Nothing selects register by audience.
- **§5 Affected Assets**, per §3.

Named here rather than left for a reader to discover.

## 5. Acceptance — 6 mutations, all red

Harness `~/AQELYN_ECR0103_PREP/matrix.sh`: reverting to a machine-string title, dropping
`expert_details`, letting the title run to the whole paragraph, removing the empty-title fallback,
ignoring an operator-supplied title, and dropping the raw measurement from level 4.

12 tests, including one that asserts **nothing is lost** when the title is simplified — the
identifiers removed from it must still be reachable in `expert_details` — and a UX-007 check that
the words this codebase generates carry no fear-based language.

Ruff clean, `mypy --strict` clean across 586 files, full suite on live Postgres. Carried matrix
stays at **84**, untouched.

## 6. What review should attack

1. **`plain_title` splits on `". "`.** An abbreviation would truncate badly. Unwitnessed.
2. **The UX-007 word list is mine and short.** It checks generated text, not operator prose, and
   a real content review is a different exercise.
3. **`expert_details` is `dict[str, Any]`** — untyped by the model, so nothing constrains what a
   future collector puts there.
4. **I audited my own compliance against a Charter I read after building.** A second read by
   someone who was not trying to pass would likely find more.
