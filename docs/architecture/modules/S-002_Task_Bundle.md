# S-002 — Wire the `threat` Factor from CISA KEV — Task Bundle

**Track:** S (operational)
**Milestone:** S-002 (close the highest-ranked closable unknown)
**For:** Claude Code (implementer **and** reviewer during the Codex outage) · Codex (retroactive re-review on return)
**Prerequisites:** S-001 closed; **ECR-0066 implemented** (four factors + wrapper); **ECR-0067 implemented** (exposure replay compares); `S-001_Addendum_II_Report_Limits.md` read; environment warm, `postgres:16` scans cached (`--reuse` free).
**ECR:** **ECR-0068** (raised after S-002 exposed provider-state coverage decay and
the roadmap's string-derived unknown taxonomy).
**Definition of Done (AMENDED after the join check):** ~~`threat` moves off 200/200
unknown~~ — **that line encoded a premise the data falsified and is unsatisfiable by
any correct implementation.** The CVE join returns **zero** hits against `postgres:16`
*and* `debian:10`, because KEV catalogues exploited **products** (Microsoft 382,
Cisco 94, Apple 93) while a container SBOM lists **distro packages** — only 2.4% of
KEV comes from OS/library vendors, mostly kernel CVEs absent from a container by
construction. **KEV and container SBOMs describe near-disjoint populations**, so no
container target exercises this factor.

Replaced by what the milestone actually means: **every KEV-listed CVE in the corpus
yields `known`; every other yields `unknown` with the third-category reason; zero
records acquire a favourable `known` from an absence; and `threat`'s unknowns are
reported as structural rather than closable.** The 302-record corpus is therefore the
milestone's **primary** test artifact, not a disappointment — 302 real records where
the source says nothing, every one required to say so.

Also required: **no record acquires a favourable `known` from an absence**; density report re-run and states its tie or its new ordering; both backends, both tenant modes, `python -O`; `mypy --strict src tests`; `gh pr checks` PASS before merge.

---

## Why this target

S-001's density report produced a **four-way tie at 200/200 unknown**:
`baseline`, `exposure`, `mission`, `threat`. The tie dissolves rather than needing
a break, because **three of the four are unanswerable for a container image**:

| Factor | Why it cannot be answered here |
|---|---|
| `exposure` | `derive_surface` reads only **stored platform data**; a container image has no deployment, so there is no surface to derive |
| `mission` | criticality is **configured** (`criticality_tier` on object attributes); *"what mission does `postgres:16` serve"* has no answer |
| `baseline` | requires an **approved config baseline** to compare against; none exists to declare |

`threat` is the one that can be answered, and it wins on **both** tie-break
criteria at once — **CISA KEV is a public JSON file**, in the exact handed-in
shape S-001 already proved end to end, and exploitation evidence is among the
highest-signal inputs to vulnerability priority that exists.

**The second-order reading matters more than the choice.** Three factors reporting
200/200 unknown *because the target cannot answer them* is real data saying **the
container image is nearly exhausted as a target.** S-002 wires KEV against it;
**S-003 needs something with deployment context and an owner who can declare what
matters.**

---

## 1. The dominant decision: KEV is a **positive-only** catalog

This governs the whole milestone.

> **Presence in KEV means *known exploited*. Absence means *not in the catalog of
> known-exploited* — which is emphatically NOT *not exploited*.**

A mapper that reads absence as `known: not exploited` would be the
**empty-means-safe family arriving through the platform's newest input** — the
fifth instance in this sequence, after ECR-0013, ECR-0040, ECR-0064 and ECR-0066.
It would also be the most consequential, because it would assign a **favourable
known** to ~95% of records on the strength of a source that never made a claim
about them.

**Required semantics:**

| KEV state | `threat` factor |
|---|---|
| CVE **present** in KEV | `known`, high — with the KEV entry as evidence |
| CVE **absent** from KEV | **`unknown`**, with a reason — **never** a favourable `known` |

**KEV augments; it does not adjudicate.** Absence alone SHALL NOT produce a
`known` value of any polarity.

## 2. The expectation this sets — state it before the run

**Wiring KEV will not move `threat` from 200 unknown to 200 known.**

KEV is a curated catalog of actively-exploited vulnerabilities; of 302 real
records, expect **single-digit to low-double-digit** hits. The rest stay
`unknown`, correctly.

> A run that produces `threat: known=7, unknown=295` is a **complete success**.
> The factor moved from *"nothing was asked"* to *"asked, and answered for the
> seven where an answer exists."*

Say this before the run. Otherwise a correct result reads as a failed wiring.

## 3. The finding this exposes: some factors cannot be fully wired

**A positive-only source is structurally incapable of fully covering a factor.**
To move `threat` to high known-coverage you would need a source that can assert
the **negative** — *"we checked, and this is not being exploited"* — which threat
intelligence does not and cannot supply.

So `threat` will remain **mostly unknown permanently**, and that is the honest
state of the world rather than a gap.

**This breaks an assumption in the density report's ordering.** The roadmap ranks
by unknown count on the premise that **unknowns are closable**. A permanently
unknowable factor would **rank near the top forever, recommending work that cannot
be done.**

**Required: extend ECR-0066's reason taxonomy with a third category.**

| Reason | Means | Roadmap implication |
|---|---|---|
| *no `<X>` provider supplied* | nothing is wired | **wire it** |
| *`<X>` provider returned no signal* | wired, came back empty | **investigate why** |
| ***`<X>` provider supplied; cannot assert for this record*** | **wired and working; the source cannot speak to this case** | **nothing to do — this is the answer** |

The third is what KEV absence produces. Without it, S-002's success would make
`threat` look like S-003's most urgent target.

**ECR-0068 resolution:** these facts are carried as typed `unknown_cause` values,
not inferred from reason/source prose. Scoring excludes every unknown identically;
the S-track maps causes to roadmap treatment through an exhaustive table that
refuses when a future cause is unclassified.

---

## T1 — The KEV parser

**Deliverable:** a pure parser mapping the CISA KEV catalog JSON to whatever
`threat`'s provider contract requires, landing in the module that owns the factor,
in the house `parse.py` pattern (`supplychain/parse.py`, `vuln/parse.py`). No I/O,
no network, no subprocess — `dict[str, Any]` in, records out.

**Map narrowly.** KEV carries `dueDate`, `knownRansomwareCampaignUse`,
`requiredAction` and more. Map only what the factor consumes; **an unused mapped
field is a future migration for no benefit.**

**Acceptance:** `test_threat_parse_kev_document`,
`test_threat_parse_absence_is_unknown`.

## T2 — Wiring, with the absence semantics

**Deliverable:** the `threat` provider wired so KEV presence yields `known`/high
with evidence, and **absence yields `unknown`** with the §3 third-category reason.

**Verify by mutation, not by reading:** make absence produce a favourable `known`
and confirm **GC-001 AC-3** (per-factor, as widened by ECR-0066) turns **red**.
If it does not, AC-3's widening did not cover this factor and that is a finding.

**Acceptance:** `test_threat_kev_hit_known`,
`test_threat_kev_miss_unknown_not_favourable`,
`test_threat_absence_trips_ac3_when_inverted`.

## T3 — The catalog as a handed-in document

**Deliverable:** the driver fetches the KEV JSON **once and caches it**, exactly as
the scans are cached, so runs are reproducible and free. The **engine never learns
that KEV is a URL** — it receives a document, as with the SBOM.

**Boundary, unchanged from S-001:** nothing under `src/aqelyn/` references a URL,
a fetch, or a subprocess. The driver lives outside the package for the
**architectural** reason — live collection is the boundary every spec defers —
**not** because a guard would fire.

**Record the catalog's own provenance:** KEV is dated and versioned. A finding
whose `threat` factor cites KEV should cite **which** KEV, or the derivation
replays against a moving target.

**Acceptance:** `test_threat_no_network_in_src`, `test_threat_catalog_pinned`.

## T4 — Run, and re-run the density report

**Deliverable:** the full chain against the cached `postgres:16` scans, plus the
KEV catalog; then the density report.

**Check the join explicitly** (S-001's lesson): KEV keys on `cveID`, grype emits
CVE identifiers. This is a **CVE→CVE join and much simpler than S-001's purl
join** — which is exactly why it will be assumed rather than verified. Verify it.

**Then the closing question from Addendum II:** whatever the new report shows, a
`known = N/N` row is **not** evidence a factor is wired — it is evidence the corpus
never asked. `threat` at `known=7, unknown=295` is a *stronger* statement than any
`known=N/N` row in the table.

**Acceptance:** `test_s002_chain_end_to_end`, `test_s002_join_verified`,
density report attached to the PR.

---

## Success criteria — state these before the run

1. `threat` moves off 200/200 unknown.
2. **No record acquires a favourable `known` from an absence.**
3. KEV hits carry the catalog entry as evidence, and the catalog is **pinned**.
4. The report distinguishes *unwired* from *unknowable* (§3).
5. Derivations replay — including on records whose `threat` factor is now known.

**Not success criteria:** the number of KEV hits, or `threat`'s known-count.
A single-digit hit rate is the expected and correct outcome.

## Predicted failures

- **The CVE join assumed rather than checked** — simpler than purl, therefore more
  likely to be skipped.
- **Absence silently favourable** — the highest-consequence failure and the one
  the whole bundle is shaped around.
- **Over-mapping KEV fields** — mapping `dueDate` or ransomware flags because they
  are present, not because anything consumes them.
- **Catalog unpinned** — a derivation that replays today and not next week, which
  would be an ECR-0067-shaped defect arriving through data rather than code.

## Review protocol (Claude Code)

1. **Absence never produces a favourable `known`** — mutation-verified, and
   confirm **GC-001 AC-3** catches the inversion.
2. **The third reason category exists** and the report can distinguish *unwired*
   from *unknowable*; ECR raised if the reviewer judges it semantic.
3. **The join was verified**, not inferred from a hit count.
4. **Catalog pinned** — derivations cite which KEV.
5. **Boundary held** — nothing under `src/aqelyn/` fetches; driver outside the
   package for the architectural reason.
6. **Narrow mapping** — no field mapped that nothing consumes.
7. Both backends, both tenant modes, `python -O`; `mypy --strict src tests`;
   `gh pr checks` PASS.
8. **Self-verification disclosure** and the density report attached.

**Preserve:** `FIRST_DEPLOYMENT_ITEMS.md` (nothing here settles it), **EA-0048**
(unscheduled gap), and the S-003 target question — which this milestone's tie
already answered in outline: **something with deployment context and an owner who
can declare what matters.**
