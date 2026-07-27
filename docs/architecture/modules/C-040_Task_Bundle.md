# C-040 — ECR-0072: Absence Is Not a Value — Task Bundle

**Milestone:** C-040 (implement ECR-0072; unblock S-003 U2)
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** C-039 merged (`f96d7e5`); **ECR-0072 read in full**, §3 and §4 especially; `SPEC_AUTHOR_NOTES.md` rules 1–31.
**Blocks:** S-003 U2 — the real estate must ingest **unedited**, and a CPE-only component must not vanish from prioritization.
**Definition of Done:** the real 131,685-component document ingests with **no hand-editing**; **the contradiction control still quarantines**; a CPE-only component is either prioritized or **named unavailable**, never silently omitted; both backends, both tenant modes, `python -O`; `ruff` clean; `mypy --strict src tests`; `gh pr checks` PASS before merge.

---

## The governing sentence, unchanged from C-039

> **This narrows what counts as a conflict. It does not widen what is tolerated.**

A genuine contradiction — **two different non-null values for one identity** —
**still quarantines**. If the diff acquires a path that tolerates one, the
milestone has inverted its own purpose. Stop and raise.

## Sequence

**W1 unblocks the parse; W2 and W3 unblock U2.** Both are needed before U2
completes — the seam becomes live the moment U2 wires real components to EA-0024 —
but W1 is what lets the estate be read at all, so it goes first.

---

## W1 — Absence is not conflict, across every optional field

**Spec:** ECR-0072 §1–§3.

**The correct decision is already in the file.** `locations` and `direct` merge on
absence at `parse.py:246-247`. It was applied to two fields when it was a property
of every optional one — **rule 29**, and the closing question *"is this site the
only one that could have had it?"* was never asked when those two were written.

**Classification — implement exactly this, and record the evidence basis:**

**Contradiction-only** (a difference is always a contradiction; absence is itself
one):

| field | basis |
|---|---|
| `name` | **proven** — 0.0% absent, never differs |
| `version` | **proven** — 0.0% absent, never differs |
| `component_type` | **proven** — 0.0% absent, never differs |
| `identity_kind` | **structural** — cannot differ within a group |
| the **identifying** coordinate | **structural** — it is the group key |

**Absence-mergeable** (value beats absence; two different non-null values
contradict):

| field | basis |
|---|---|
| `licenses` | **proven by real data** |
| the **non-identifying** coordinate | **structural** |
| `supplier` | **format semantics — NOT corpus-proven** (100% absent here) |
| `hashes` | **format semantics — NOT corpus-proven** (100% absent here) |

> **Fix all optional fields, not only `licenses`.** Confining it to the field the
> corpus exposed would be **rule 29 committed inside a repair for rule 29**. And a
> field that is **never present never differs**, so 100% absence is the most
> camouflaged state there is (**rule 30**) — a scanner populating `supplier`
> partially would reproduce this failure exactly.

**Do not route to `ComponentConflict`.** Checked before specifying: within one
document both observations share the same `source_id`, `evidence_id` and therefore
reliability, so `_reconcile` degenerates to `unresolved: true` **by construction** —
a rename of the problem that would mark ordinary multi-environment installs as
permanent unresolved conflicts. FR-8 remains correct for the cross-document case it
was built for.

**Acceptance:** `test_sc_absence_merges_informative_value`,
`test_sc_contradiction_still_quarantines`,
`test_sc_contradiction_only_fields_refuse_on_absence` *(per field — a control
exercising only `licenses` proves nothing about `supplier`)*.

## W2 — Typed prioritization API

**Spec:** ECR-0072 §4, option (i).

`component_vulns_to_prioritization` widens to
`Sequence[ComponentIdentity | str]`, with `str` retained as the **documented
purl-compatibility form**. Same for any sibling purl-only analytical API — enumerate
them with **mypy, not grep** (rule 22).

**Measured, this is shallow:** vulnerabilities bind by
`asset_ref.ref_id == component.object_id`, **not by purl**. Everything downstream is
already identity-agnostic; the `Sequence[str]` entry point is the only barrier. The
`_required_component_purl` guard at `engine.py:436` becomes **reachable in
production**, which it is not today.

**Why not option (ii):** requiring the FR-16 named unavailable at every enumerating
caller makes it a property that must be re-established for each new caller — rule 29
as a standing tax rather than a fixed defect. And C-039's V3a already prescribes (i).

**Acceptance:** `test_sc_prioritization_accepts_component_identity`,
`test_sc_purl_str_still_accepted`, `test_sc_guard_reachable_without_cast`.

## W3 — Coverage: a component nobody can assess is **not** clean

**Spec:** ECR-0072 §4, the fourth arrival.

Even with W2, **a CPE-only component receives zero vulnerabilities from every
shipped provider** — none matches by CPE (`grep -rn "cpe" src/aqelyn/vuln/
src/aqelyn/threat/` returns nothing). Left alone it presents as **"0
vulnerabilities": indistinguishable from assessed-and-clean.**

**Required:** the component is recorded in **EA-0024 coverage as explicitly
unassessable**, reason *"no provider matches identity_kind=cpe"*, and **SHALL NOT
present as zero vulnerabilities.** EA-0024's coverage is already mandatory and
`PriorityFactor` already carries `status="unknown"` — the machinery exists and is
simply not wired to this case.

**Taxonomy placement** (S-002's): **closable** — *no provider supplied for this
identity kind* — because a CPE-matching provider could be built. It belongs in the
density report as a **roadmap entry**, not a structural dead end.

**Acceptance:** `test_vuln_cpe_only_named_unassessable`,
`test_vuln_cpe_only_not_zero_findings`,
`test_vuln_cpe_only_appears_closable_in_density`.

---

## Proof

- **The real, unedited estate document ingests end-to-end** — reviewer re-runs
  before merge, no hand-editing. This is the milestone's actual pass condition.
- **Negative control, non-negotiable:** two different non-null values for one
  identity → **still quarantines.**
- **Per-field mutation** for every contradiction-only field.
- **CPE-only prioritization:** either prioritized or **named unavailable**, never
  silently omitted. **The vulnerability must be constructed** — no CPE
  vulnerability provider exists, so a real CVE for such a component **cannot be
  sourced**. Legitimate, and what C-039's test already does; stated so nobody hunts
  for corpus data that cannot exist.
- Both backends, both tenant modes, `python -O`.

## Review protocol (Claude Code)

1. **The contradiction control quarantines.** **Check this first** — route (A) is
   the permissive route and this is the only thing between it and a tolerance path.
2. **Every optional field merges, not just `licenses`** — and every
   contradiction-only field **refuses on absence**, mutation-verified per field.
3. **No `ComponentConflict` path for the within-document case** (§W1).
4. **The guard is reachable without a cast** (W2) — that was the tell.
5. **A CPE-only component is never "0 vulnerabilities"** — it is named
   unassessable, and closable in the density report.
6. **The real document, unedited.** A test corpus passing proves the code; the real
   document passing proves the milestone.
7. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS.

**Correction to carry (ECR-0072 §5):** ECR-0071 §9 and C-039's protocol both said
*"15,152 components — the first real workload to exceed the retired ECR-0034 10,000
cap."* **Wrong.** 15,152 is package-typed **entries**; after identity dedup the
estate yields **7,972 components**, **below** the retired cap. `page_budget =
50_000` is unaffected; the exceeds-10,000 claim is **withdrawn**. Corrected in
ECR-0071 in place.

**Preserve, not folded in:** the two S-003 follow-ups (collection memory bound; the
doc-versus-code drift pins), `FIRST_DEPLOYMENT_ITEMS.md`, **EA-0048**, and the
retroactive re-review queue.

Merge on green **and on the real document ingesting**; then **S-003 U2 unblocks.**
