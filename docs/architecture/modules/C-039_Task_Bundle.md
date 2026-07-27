# C-039 — ECR-0071: Purl-less Component Identity — Task Bundle

**Milestone:** C-039 (implement ECR-0071 route (B); unblock S-003 U2)
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** S-003 U1 merged (`main @b1520f1`); **ECR-0071 read in full**, §7 and §8 especially; `SPEC_AUTHOR_NOTES.md` rules 1–31.
**Blocks:** S-003 U2 — no ad hoc parser change before this lands.
**Definition of Done:** the real 131,685-component document ingests; **the negative control still quarantines**; a second collection mints no duplicates; migration applied; both backends, both tenant modes, `python -O`; `ruff` clean; `mypy --strict src tests`; `gh pr checks` PASS before merge.

---

## The one sentence that governs the milestone

> **This is a classification change, not a tolerance change.** The quarantine is a
> shipped guarantee whose own docstring calls refusal *"the strongest form of
> acting on the signal."* Route (B) widens **what can be represented**. It must not
> widen **what can be tolerated**.

If at any point the diff contains a path that counts-and-skips a genuinely
malformed component, the milestone has inverted its own purpose. Stop and raise.

---

## V1 — Model: `cpe` and an explicit `identity_kind`

**Spec:** ECR-0071 §7.

```
purl:          str | None          # retained; strict pkg: validation WHEN PRESENT
cpe:           str | None          # new
identity_kind: "purl" | "cpe"      # semantic token, NOT NULL, NO DEFAULT
```

**Why a discriminator rather than `coalesce(purl, cpe)`** — the platform must
retain which coordinate namespace establishes identity; readers must not
recompute it from nullable fields. `coalesce` erases that namespace and stores a
**re-derived output** — ECR-0065's invariant one layer down.

The token does **not** claim why a purl is absent. A handed-in document cannot
prove that a purl is impossible rather than merely unreported. It can prove only
which supported coordinates it actually carries.

**Both fields are retained even when only one identifies.** A purl-bearing
component may also carry a `cpe`; discarding it would repeat the exact mistake this
ECR corrects.

**No default on `identity_kind`.** The parser explicitly selects `purl` whenever a
purl is claimed, otherwise `cpe` when a CPE is claimed. If neither coordinate is
present, the component is **malformed and the document quarantines**. A default
here would make a missing identity look selected.

**Acceptance:** `test_sc_identity_kind_required_no_default`,
`test_sc_both_coordinates_retained`.

## V2 — Parser: the discriminator, format-level

**Spec:** ECR-0071 §8.

**The rule is deterministic:** a present `purl` is strictly validated and selects
`identity_kind = "purl"`; otherwise a present `cpe` selects
`identity_kind = "cpe"`. Neither present → quarantine. A malformed claimed purl
does not fall back to CPE.

**Do not key on `foundBy == pe-binary-package-cataloger` or
`metadataType == pe-binary`.** Both couple the parser to **one tool's internal
taxonomy**; cataloger names change between syft versions, and a syft-only rule
**silently fails the day the estate is scanned with something else.** The platform
accepts handed-in CycloneDX, not syft output. Record the syft signatures as
*evidence* in the run log — they are what made the finding legible — never as the
rule.

`parse.py` must also **read `cpe`**, which it currently discards.

**The trap, measured:** `binary` splits **3 with-purl / 24 without** in the same
document (`chrome`, `node` ×2 carry `pkg:generic/...`). A rule relaxing on
ecosystem alone would **stop validating exactly the components that do claim a
coordinate.**

**Acceptance:** `test_sc_purlless_with_cpe_admitted`,
`test_sc_purlbearing_binary_still_validated`,
`test_sc_malformed_claimed_purl_does_not_fall_back_to_cpe`,
`test_sc_no_purl_no_cpe_still_quarantines`.

## V3 — Stores: identity, and the immutability guard

**Spec:** ECR-0071 §6, §7. There are **two store implementers** —
`InMemorySBOMStore` and `PostgresSBOMStore` — but the identity contract is broader
than those two classes. V3a enumerates the shipped purl-specific consumers that
must move with it.

- `SBOMStore.get_component(purl=...)` — the Protocol names `purl` as *the* lookup
  key; it must accept a semantic coordinate kind and value. The kind is explicit;
  a bare nullable value or prefix inference must not become a second discriminator.
- `memory.py` — dict keyed `(tenant, purl)` becomes keyed on
  `(tenant, identity_kind, identity value)`.
- `postgres.py` — the `WHERE … purl=$2 FOR UPDATE` path, and the shipped
  **`object_id`↔`purl` immutability guard** becomes
  **`object_id`↔`(identity_kind, value)`**. A component may not change *which kind*
  identifies it — that would be a different component.
- `store.py::validate_purl` stays strict for purl claims. A separate coordinate
  validator handles CPE; there is no general purl-validation bypass.

**Acceptance:** `test_sc_lookup_by_either_coordinate`,
`test_sc_identity_kind_immutable`, `test_sc_store_contract[inmemory]` / `[postgres]`.

## V3a — The purl-specific consumer seam

Shipped source uses `purl` for more than persistence. It is also:

- the parser's deduplication and dependency-edge key;
- the EA-0002 natural key and inventory handoff;
- the evidence/reference label used by provenance and findings; and
- the input to analytical APIs that genuinely operate on package URLs.

The implementation SHALL enumerate these consumers against the typed source
surface, not assume changing the two stores completes the migration.

- Component identity, parser deduplication, relationship binding, and EA-0002
  routing use the explicit `(identity_kind, identity value)`.
- A CPE-only component routes to EA-0002 with a `cpe` natural key. It must not
  enter `validate_purl`, interpolate `None` into evidence, or disappear from the
  component/coverage count.
- APIs whose domain is genuinely purl-specific may remain purl-specific, but a
  CPE-only component reaching them produces a named unavailable/unknown outcome
  or a named refusal. It never produces an empty result that reads as clean.
- Dependency references are resolved through the document's `bom-ref` map to the
  semantic component identity. If a CPE-only component participates in an edge,
  the edge is represented or the whole document is refused; it is never silently
  dropped.
- Backward-compatible purl callers continue to resolve the same records. Any
  convenience API that defaults to purl is only a compatibility wrapper around
  an explicit semantic-identity store contract, not a model default.

**Acceptance:** `test_sc_cpe_component_real_owner_round_trip`,
`test_sc_cpe_natural_key_not_purl_none`,
`test_sc_cpe_dependency_not_silently_dropped`,
`test_sc_cpe_purl_only_analysis_not_clean`.

## V4 — Migration

**Spec:** ECR-0071 §7. Shipped table: `purl text NOT NULL CHECK (purl LIKE 'pkg:%')`
with `UNIQUE (tenant_id, purl)`.

- `purl` becomes nullable; `cpe` and `identity_kind` added.
- `cpe` is non-empty and starts with `cpe:` whenever present; a claimed malformed
  CPE is refused rather than normalized into an identity.
- `locations` is persisted as an array, with an additive migration/backfill and
  every Postgres read/write mapping updated. Reconciliation unions normalized
  locations deterministically; a later observation cannot erase earlier paths by
  omission.
- **Two partial unique indexes keyed on `identity_kind`** — one deterministic
  expression per kind, and **no namespace conflation** between the coordinate
  spaces.
- One exhaustive CHECK: `identity_kind='purl'` ⇒
  `purl IS NOT NULL AND purl LIKE 'pkg:%'`; `identity_kind='cpe'` ⇒
  `purl IS NULL AND cpe IS NOT NULL AND cpe LIKE 'cpe:%'`. A row cannot select CPE
  to bypass a claimed purl.
- **Rule 9:** a CHECK constraint is persisted shape too — it needs its own
  migration step, as ECR-0064 found the hard way.
- Existing rows: every shipped component is purl-identified, so backfill
  `identity_kind='purl'` before the NOT NULL lands.

**Acceptance:** `test_sc_migration_backfills_identity_kind`,
`test_sc_partial_unique_per_kind`, `test_sc_locations_round_trip`.

## V5 — The 24 → 1 collapse, and locations

**Spec:** ECR-0071 §6, §9.

All 24 share **one** `cpe`, with **zero** overlap against any purl-bearing
component. Keyed on `cpe` they reconcile to **one component observed at 24
locations** — the correct model, not a workaround. The estate's component count
rises by **1**.

> **The collapse must not lose the locations.** One component at 24 paths is right
> *only if the 24 paths are recorded*. If `SoftwareComponent` cannot carry them
> today, **that is part of this change** — not a detail to drop on the way past.

Locations are retained as handed-in observations. They are not component identity,
are not copied into aggregate S-track reports, and are not committed as a fixture
from the real estate (ECR-0069).

**Acceptance:** `test_sc_24_collapse_to_one_with_locations`,
`test_sc_second_collection_no_duplicates`.

---

## Proof

- A document containing **both** a purl-bearing binary-classifier component **and**
  a purl-less PE component. **The discriminator is only proven when both are
  present.**
- **Mutation both directions:** remove the classification → the document
  **re-quarantines**; relax to all `binary` → **fails on the purl-bearing ones**.
- **Second collection of the same host mints no duplicates** — the regression
  `bom-ref` keying would have caused, and the reason it was struck.
- **Negative control:** package-typed, no `purl`, no `cpe` → **still quarantines.**
- A CPE-only component survives parse → store → real EA-0002 owner routing, while
  purl-only analysis reports explicit uncertainty rather than clean absence.
- Both backends, both tenant modes, `python -O`.

## Guard rails

- **Never synthesise a purl.** `pkg:generic/simple-launcher@1.1.0.14` would
  fabricate a coordinate no ecosystem issued. Syft emits `pkg:generic/` for chrome
  and node because it **has provenance**; inventing one here is guessing.
- **Strict `purl` validation stays wherever a `purl` is claimed.**
- **No skip-and-count path for malformed components** — that reverses a shipped
  guarantee.
- **No `None`-as-string identity.** Evidence refs, natural keys, and findings must
  use the selected coordinate and name its kind.

## Review protocol (Claude Code)

1. **The negative control quarantines** — package-typed, no `purl`, no `cpe`.
   **Check this first**; route (B) is the permissive route and this is the only
   thing standing between it and a tolerance path.
2. **The discriminator is format-level** — no `foundBy` or `metadataType` in the
   rule. Syft signatures appear as evidence, not as logic.
3. **Purl-bearing binaries still strictly validated** — mutate to confirm.
4. **`identity_kind` has no model default**; undeterminable → quarantine.
5. **Immutability guard covers the kind**, not just the value.
6. **The downstream purl surface is audited** — real owner routing uses the
   semantic identity; purl-only analytics fail honestly for CPE-only components.
7. **Locations preserved** through the 24→1 collapse.
8. **Second collection mints nothing** — run it twice.
9. **Migration:** CHECK constraints have their own step (rule 9); backfill precedes
   NOT NULL.
10. Both backends, both tenant modes, `python -O`; `mypy --strict src tests`;
    `gh pr checks` PASS.

**Context, one line for the record:** 15,152 components is the **first real
workload to exceed the retired ECR-0034 10,000 cap** — validating C-036's cursor
work against a real number rather than a constructed one. It sits under
`page_budget = 50_000`; nothing is degraded.

**Preserve, not folded in:** the two S-003 follow-ups (collection memory bound;
the doc-versus-code drift pins), `FIRST_DEPLOYMENT_ITEMS.md`, **EA-0048**, and the
retroactive re-review queue.

Merge on green; then **S-003 U2 unblocks.**
