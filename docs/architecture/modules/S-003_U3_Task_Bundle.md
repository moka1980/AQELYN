# S-003 U3 — Exposure from Observed Binds — Task Bundle

**Milestone:** S-003 U3 (implement ECR-0073)
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** U1, U2, C-039, C-040, **ECR-0073** all merged (`main @2aeb012`); working tree clean; **ECR-0073 read in full**; `SPEC_AUTHOR_NOTES.md` rules 1–31.
**Data handling (ECR-0069):** **counts and classes only.** No port, address, service name, path or hostname appears in this bundle, in any test fixture, in any PR body, or in any output that leaves the estate.
**Definition of Done:** measured reachability replaces the hardcode; **the basis names its real source**; the three states are distinguishable by name; **the degraded guard still fails closed**; both backends, both tenant modes, `python -O`; `mypy --strict src tests`; `gh pr checks` PASS; real-estate run before merge.

---

## The one guarantee this unit must not weaken

`InventoryKnownSurfaceSource` **raises `InventoryUnavailable` when the inventory
report is `degraded`** (C-034/C-036). That is the fail-closed guarantee ECR-0073 §8
says U3 inherits, **it was mutation-proven when it shipped, and U3 is the first
change to touch this class since.**

**A control must still fail when it is removed.** Check this before anything else in
review — a refactor of the surrounding method is exactly how a load-bearing guard
gets quietly dropped.

---

## X1 — The basis vocabulary: **route (A)**, add a kind

**The problem, verified by running the shipped code:** `ExposureBasis.kind` is a
closed frozenset of four — `inventory, telemetry, access, graph` — validated on
construction. **None means "observed host state."** The current source claims
`kind="inventory"`, which after U3 becomes **exactly the false claim ECR-0073 §3
forbids**: the judgement would come from a socket observation while the basis says
it came from the inventory.

**Decision: add a kind.** And the argument against reusing `telemetry` is stronger
than "explicit is better":

> **`telemetry` has a specific meaning in this platform** — EA-0019's ingested
> telemetry events, with a lake behind them. **A collector's socket table is not
> one.** A record claiming `telemetry` would make *"which telemetry produced this?"*
> unanswerable, because there is none in the lake to find. That is a **provenance
> claim to a pipeline the record never went through**.

**Route (C) — provenance in `ref` alone — is insufficient**, because `kind` would
still say `inventory`. But **do both**: the new kind names the *class* of evidence,
and `ref` records *what specifically* was observed. A kind without a ref is a
category; a ref without a kind is a footnote.

### Naming criterion — not the name itself

The four existing members name **sources of evidence**. The new one must:

- name the **source class** — *the host's own observed runtime state* — **not the
  specific artifact.** A member meaning "socket bind" would need a sibling the first
  time a process list or mount table is read; a member meaning "observed host state"
  would not.
- be **unmistakable against `telemetry`** (EA-0019 events) and **`inventory`**
  (registered assets).

The exact token is the reviewer's to finalise.

### On ECR-0073 §8

The brief calls this *"§8's one exception."* **It is narrower than that.** §8's claim
was that **the computation** does not change — `_level_for` and `derive_surface` are
untouched, and they are. **A vocabulary widening does not touch computation**; it is
an **additive contract change**, and §8 was stated at the wrong granularity rather
than being wrong. Name it as additive in the record, so a later reader does not
conclude §8 was violated and reason from that.

**Acceptance:** `test_exposure_basis_kind_accepts_observed_state`,
`test_exposure_basis_bind_derived_not_inventory`,
`test_exposure_basis_ref_records_specific_evidence`.

## X2 — Asset registration: nothing new is required

`InventoryIntelligenceEngine.ingest` takes `reports: Sequence[Mapping[str, Any]]`
plus a `DiscoverySource`; `_asset_from_report` requires only `asset_type`.

**So the U1 documents are handed in as-is** — no new store, no protocol change, no
model widening. This is the same path **EA-0030 already uses** to route parsed
components into EA-0025, so U3 follows an established precedent rather than inventing
one.

**Acceptance:** `test_s003_services_registered_as_assets`.

## X3 — Replace the hardcode with a measured judgement

`InventoryKnownSurfaceSource` hardcodes **`reachability=None`** for every asset.
U3 replaces that with a measured classification, per **ECR-0073 §5**:

| bind class | reachability |
|---|---|
| wildcard | **external** |
| loopback | **internal** |
| **anything else** | **`None` → level `"unknown"`** |

**No heuristics for the third class.** A socket bound to a specific address may sit
on a public interface or a private one, and **the host's own socket table cannot
say which.** An `unknown` here is the honest limit of the evidence, not a gap in the
implementation.

`_level_for` already maps `external → high`, `internal → low`, everything else →
`"unknown"`, and `KnownSurfaceRecord.reachability` is already `Reachability | None`.
**Nothing downstream needs widening.**

*(Incidental, flagged so nobody "fixes" it here: `VALID_EXPOSURE_LEVELS` contains
`"medium"`, which `_level_for` can never return. **Not U3's problem** — leave it.)*

**Acceptance:** `test_s003_reachability_measured_from_bind`,
`test_s003_third_bind_class_stays_unknown`.

## X4 — The three states, wired to their real cases

ECR-0073 §4 requires three distinguishable states. **Wire each to the case that
actually produces it** — not to a synthetic stand-in:

| state | real case | named reason |
|---|---|---|
| **registered asset, no surface derivable** | an asset with no observed listener | *no surface evidence* |
| **surface observed, not attributable** | **14 of 16 listeners** — no process information under unprivileged collection | *observed, join key unavailable* |
| **not registered at all** | **the tier-4 services** — no unit, therefore not in the declaration roster, therefore not EA-0025 assets | *not registrable* |

**The third row resolves a U2 residual.** Tier-4 services were recorded as
"structurally unrepresentable"; ECR-0073 §4's third state is exactly their state, and
**U3 is where it becomes visible.** Wiring it here closes that residual — **provided
the wiring is real.** If state 3 is only reachable by a constructed fixture, the
residual is not closed.

**The operational test for whether these may be collapsed** (ECR-0073 §4): two states
may merge only if they imply the **same next action**. These imply three different
ones — derive a surface, obtain the join key, register the asset.

**Acceptance:** `test_s003_unregistered_asset_distinguishable`,
`test_s003_observed_unattributable_named`,
`test_s003_tier4_service_is_state_three`.

## X5 — Make the residual legible in the output

ECR-0073 §6/§7's privileged-read decision is **the owner's and outstanding**. U3 is
specified to work **without** it — and to make the residual **visible in the data**,
so the decision is informed by the instrument rather than argued in prose.

Concretely: the count of listeners in each state, and the reason string for state 2,
must reach the density report as a **closable** unknown. **One owner decision yields
both the proxy topology and the listener PIDs**, so the report should point at one
item, not two.

**Acceptance:** `test_s003_unattributable_appears_closable_in_density`.

---

## Proof

- **Basis honesty is mechanical, not nominal.** A test must **fail** when a
  bind-derived record claims an inventory or configuration basis. §3 is only real if
  a mutation can break it.
- **The degraded guard still fails closed** after the source is rewritten —
  mutation-verified.
- **The negative control that is the point of the unit:** a registered asset with no
  derivable surface, and an observed unattributable listener, must produce
  **different, named** outcomes. *A test that cannot tell them apart has tested
  nothing.*
- **Unknown must not become a level:** force `_level_for`'s default and watch a
  control fail.
- **State 3 is exercised by a service that genuinely has no unit**, not a stand-in.
- Both backends, both tenant modes, `python -O`.
- **Real-estate run before merge**, counts only in any output.

### The prediction is falsifiable, and that is deliberate

ECR-0073 §9 states: *"`exposure` will not move to mostly-known — the count barely
moves, the reasons change."* **The reviewer will test it against the real document.**

**If it does not hold, that is a finding about the prediction, not something to
quietly restate.** S-002's stated expectation was wrong, and that was only visible
because it had been written down first.

## Review protocol (Claude Code)

1. **The degraded guard still fails closed.** Check first — U3 is the first change to
   this class since it was mutation-proven.
2. **The basis names its real source**, and a mutation claiming `inventory` fails.
3. **No heuristic for the third bind class** — it stays unknown.
4. **The three states are distinguishable by name**, and **state 3 is reached by a
   real tier-4 service**.
5. **Nothing downstream changed** — `_level_for` and `derive_surface` untouched;
   `"medium"` left alone.
6. **The residual is legible** in the density report as one closable item.
7. **ECR-0069 respected** — no port, address, service name, path or hostname in the
   diff, the fixtures, the PR body, or the report.
8. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS.

---

## Recommended next, **not** folded in: ECR-0074

The reviewer's second U2 residual — `ispm/scoring.py:347`,
`if not result.impacts: return 0.0, None`, so an asset with no mission object
contributes **0.0, the most favourable value**, rendered `0.000` rather than
`unknown` — is **the same disease U3 is curing, one factor over**, in a different
module.

Keep it out of U3, as recommended. But **ECR-0074's first question should not be the
defect.** It should be:

> **Why did GC-001 AC-3 not catch this?**

ECR-0066 widened AC-3 to **per-factor**, and ECR-0068 widened it again for provider
state. A factor returning a favourable value with no provider is **precisely** what
AC-3 asserts against. So either ISPM's scorer is **not discovered** as a composition
scorer, or this path **does not go through the factor mechanism AC-3 inspects**.

**Either answer is a hole in the guarantee, and that matters more than the defect** —
because it would be **AC-3's third gap**, and the first two were both found by real
data rather than by the guard. The third U2 residual (*"decided not to declare"*
recorded as *"not declared"*) belongs in the same ECR: both are unknowns whose
**cause** is misstated.

**Carried forward, unresolved:** the privileged-read decision (owner's); the
collector's absent memory bound; the two U1 doc-versus-code drift pins; C-040's
vacuous `scanned -= unassessable_inventory` assertion; U2's untested
`used_default_tier` refusal. **U4's baseline remains conditional on U4's own
criteria.**
