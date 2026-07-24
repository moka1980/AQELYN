# IS-037 Conformance Analysis — realized by shipped EA-0023 + EA-0024 + EA-0025 + EA-0005

**Subject:** IS-037 — Cyber Asset Exposure Management Engine (CAASM / EASM)
**Finding A:** the archive master is a **template stub** — 424 lines of the generic
40-section publication template, §012–032 byte-identical boilerplate, and the same
generic 12-capability requirements matrix every EA-0036+ archive carries. **Zero
module-specific requirement text.**
**Finding B:** the capability is **fully shipped and distributed** across
**EA-0025** (discovery/inventory), **EA-0023** (exposure + attack surface),
**EA-0024** (prioritization), **EA-0005** (relationships), with external surface
intake via **EA-0028/EA-0029**.
**Recommendation:** mark IS-037 **conformant**. Build **no** EA-0037 module, and —
the specific trap here — **mint none of the 9 `Cyber*` events.**
**Change control:** **ECR-0059** *(landed; GC-002 holds ECR-0058).*
**Status:** Accepted — implemented by C-034. §6's condition is discharged via
**route (A)**: ECR-0034 is fixed for silent truncation, so this certification is not
made over a denominator the platform cannot verify. See ECR-0034's resolution note —
the cursor-pagination half remains open and is not claimed here.

---

## 1. Finding A — a template stub, second in a row

`archive/EA-0037/EA-0037_Master.md` is the same generator output as EA-0036:
§012–032 are **byte-identical boilerplate**, and §033's Requirements Matrix is the
**identical generic 12-capability list** (Discovery, Normalization, Inventory,
Assessment, Policy, Trust, Evidence, Recommendation, Event-Pub, Analytics, API,
Workflow) carried by every EA-0036+ archive. The only module-specific content is
the title and 9 event names.

Per the IS-036 finding (§1.1 there), the epistemics are unchanged: **there is no
specification, so any requirement written from these headings is invented by the
drafter wearing the archive's authority.** Nothing below is derived from the
template.

## 2. Finding B — the capability ships, and two owners carry the literal words

| EA-0037 sub-capability | Shipped owner (verified in `src/`) |
|---|---|
| "discovers assets" | **EA-0025** — package docstring: *"Cyber Asset Discovery & Inventory Intelligence"* |
| "measures exposure" + "maps attack-surface relationships" | **EA-0023** — docstring: *"Threat Exposure & Attack Surface Management Engine"*; ships `derive_surface() -> list[AttackSurfaceAsset]`, `list_known_surface()`, `reachable_paths()`, reachability scoring |
| "prioritizes reduction of exploitable exposure" | **EA-0024** — *"Vulnerability Intelligence & Prioritization Engine"*; composes the reachability `PriorityFactor` |
| attack-surface **relationships** | **EA-0005** Knowledge Graph |
| external surface intake | **EA-0028** / **EA-0029** via `KnownSurfaceSource` / `KnownSurfaceRecord` |

This is the **clearest** of the five conformance cases (IS-026, IS-034, IS-035,
IS-036, IS-037): two shipped owners carry the archive's own words in their package
docstrings. The chain assets → exposure → priority is not merely *available* — it
is **already composed** by `derive_surface`/`reachable_paths` feeding EA-0024's
reachability factor.

## 3. The primary trap: a parallel **event namespace**

ECR-0015 grep: the 9 `Cyber*` events — `CyberDiscovered`, `CyberUpdated`,
`CyberAssessmentCompleted`, `CyberRiskDetected`, `CyberPolicyViolationDetected`,
`CyberRecommendationGenerated`, `CyberWorkflowRequested`, `CyberEvidenceLinked`,
`CyberArchived` — appear **0/9 in `src/`.**

**That is net-new *naming*, not net-new capability.** Every one of those events is
already emitted by EA-0023/EA-0024/EA-0025 under their own vocabularies. This is a
subtler failure than a duplicate engine, and worth stating precisely, because
"just add the events" sounds cheap:

1. **Downstream double-counting.** EA-0013 aggregates signals and EA-0022 reports
   figures. Two event vocabularies for one capability means one real-world
   occurrence arriving twice — inflating risk aggregation and every executive
   figure computed from it.
2. **Two vocabularies per capability.** Every consumer must then know both, and
   *which one fired* becomes a meaningful question with no principled answer.
3. **Events are a published contract.** Once emitted, they are consumed; retiring
   them is a breaking change. A duplicate engine can be deleted before release —
   **a duplicate event namespace is effectively permanent.**
4. **It is the appearance of a capability with nothing behind it.** The `Cyber*`
   namespace would describe work EA-0023/0024/0025 are already doing, while
   implying a component that does not exist.

## 3.1 A second, quieter trap: "prioritizes reduction"

The title phrase *"prioritizes reduction of exploitable exposure"* is the same
class of wording as IS-036's "Autonomous": it reads as **action**. It is not.
Prioritization is EA-0024's, and any reduction is **detect-and-propose** — an
EA-0008-gated action carried by a finding's `Automation`, never an engine acting.
The §0 no-autonomy boundary is unchanged here.

## 4. Why building EA-0037 anyway is harmful

A "unified CAASM engine" would be a **second composer** over assets → exposure →
priority, which the EA-0032/EA-0033 single-scorer lineage forbids, plus a parallel
event namespace (§3). It would produce two answers to *"what is our attack
surface"* — and because EA-0024's prioritization consumes exposure, a second
exposure composer would also silently change vulnerability priority.

## 5. The primary trap is now **CI-enforced**, not reviewer-enforced

**This is the first conformance decision backed by a test rather than by reviewer
vigilance.** With **GC-001** live, a new package under `src/aqelyn/` trips
`test_gc_engine_discovery_complete` and a new composition scorer trips the scorer
registry, on the day it lands.

The event-namespace gap this analysis originally raised — GC-001 asserts nothing
about event namespaces, so `aqelyn.cyber.*` would have passed CI silently — was
taken up as **GC-002 (ECR-0058)** and is **merged and enforcing**:
`test_gc_negative_control_unowned_prefix` fails the day anyone mints a `cyber`
prefix. **§3's primary trap is therefore mechanically closed**, and C-034 inherits
that protection rather than relying on review to supply it.

## 6. The condition on this certification — ECR-0034

**This analysis certifies conformance by pointing at a denominator the platform
cannot currently verify.** EA-0023's known-surface denominator and EA-0024's
coverage base both derive from `InventoryIntelligenceEngine.inventory()`, which
(verified at main @91b2f45):

- reads `store.query(limit=10_000)` (`inventory/engine.py:245`, `:169`,
  `service.py:115`),
- returns **`degraded=False` unconditionally** (`inventory/engine.py:256`;
  `models.py:334` default `False`),
- over an `AssetStore.query` with **no cursor and no more-remaining signal**.

So a tenant above 10 000 assets has its **first 10 000 reported as the complete
inventory** — and because EA-0023's and EA-0024's fail-closed gates key on the
`degraded` flag that is hardcoded `False`, **the cap cannot trip either refusal.**
EA-0030 SBOM ingest now makes >10k reachable in ordinary operation.

**Certifying an exhaustive attack surface on a silently-capped read is the
platform asserting something it cannot know** — the unknown-not-safe violation
this whole conformance program exists to prevent. **IS-037 therefore cannot be
certified unconditionally.** C-034 must take one route and say which:

- **(A) Fix ECR-0034.** Give `AssetStore.query` a more-remaining signal
  (`limit+1`, or `has_more`), and have `inventory()` set `degraded=True` when the
  cap is hit, so the existing `degraded`-keyed gates fail closed on a truncated
  denominator.
- **(B) Record a bounded residual** — *"IS-037 conformant for inventories ≤ 10 000
  assets/tenant; above the cap the denominator is silently truncated (ECR-0034,
  unresolved)"* — with ECR-0034 left Proposed and C-034 recorded as the ticket
  that re-confirmed it on the critical path.

### 6.1 Why (A) is the honest route

**(B)'s bound is already routinely exceeded.** A bounded certification is only
meaningful if the bound holds in practice; EA-0030 SBOM ingest pushes ordinary
tenants past 10 000 assets. So *"conformant for ≤ 10 000"* certifies conformance
for a configuration the platform **does not actually run in** — which is an
unconditional certification with a footnote, not a bounded one. (B) is a
defensible temporary posture only with the fix scheduled; it is not a resting
state.

### 6.2 Two things the fix must get right

- **An honest flag is necessary but not sufficient.** Every consumer of the capped
  denominator must **demonstrably refuse or flag**. A gate that reads `degraded`
  and only logs it, or a third consumer that never reads it, leaves a truthful
  field nobody acts on — the **ECR-0013 unwired-default shape**, and the same
  "stated everywhere, enforced nowhere" pattern GC-001 exists to catch. Prove it
  by **driving the chain past the cap**, not by observing that a gate mentions
  `degraded`.
- **`limit+1` and a cursor are different fixes.** `limit+1`/`has_more` says *more
  exists* — the **minimal, safety-critical** half, and all that is needed to stop
  the platform claiming completeness it lacks. A cursor delivers **completeness**
  (EA-0002 D8 / rule 10: page under a work budget, report `truncated`), which is a
  larger change with its own blast radius and belongs in its own ticket. Doing the
  first now does not preclude the second.

### 6.3 A behavioural change worth announcing

Making `degraded` honest will cause **existing deployments above 10 000 assets to
see gates begin refusing where they previously proceeded.** That is the
**ECR-0040 situation again** (EA-0024's exposure factor, where correcting an
optimistic default made scores rise): it is a **correction surfacing a
pre-existing wrong answer, not a regression** — and it should be said plainly
before someone reads the diff and misreads it.

## 7. Recommendation

1. **Mark IS-037 conformant** via EA-0023 + EA-0024 + EA-0025 + EA-0005
   (+ EA-0028/EA-0029), verified against shipped code — **conditioned on §6.**
2. **Forbid**: no package under `src/aqelyn/`, no unified CAASM engine, **no
   `Cyber*` event namespace** (now GC-002-enforced), no second composer/scorer,
   no new `SignalKind`.
3. **Claim no gap.** The archive specifies none, and none was invented. Any future
   proposal must show a concrete missing type or method against shipped
   EA-0023/EA-0025, verified by the reviewer before it becomes scope.
4. **Resolve ECR-0034 explicitly** (§6) — route (A) preferred per §6.1; either way
   the >10k case is **demonstrated by the proof test, never asserted in prose.**
5. **Expected code footprint:** the proof test, plus route (A)'s narrow `src/`
   change if taken. No CAASM module either way.

## 8. Note on the remaining batch

EA-0036 and EA-0037 are both template stubs from the same generator, with
byte-identical boilerplate and an identical requirements matrix. Two is not
thirteen, but it is enough to change the default expectation for
`EA-0038 … EA-0050`.

The reviewer's per-module template-check is cheap and should continue. But if
IS-038 and IS-039 come back identical, the honest question for the owner is
whether the remaining batch warrants **one batch-level conformance decision**
rather than thirteen individual passes — and, more importantly, whether the
archive has **stopped being a source of requirements**, in which case the real
backlog is the tracked follow-ups (ECR-0032, ECR-0034, the EA-0018 duration flake,
the EA-0027/EA-0018 enterprise health probes, the EA-0013 tie-breaker) plus
whatever the owner actually wants built.
