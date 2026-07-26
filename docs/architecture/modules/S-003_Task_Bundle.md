# S-003 — First Real Estate: the one.com VPS — Task Bundle

**Track:** S (operational)
**Milestone:** S-003 (exercise `exposure`, `mission`, `baseline` against a real deployed host)
**For:** Codex (implementer) · Claude Code (reviewer + merge)
**Prerequisites:** S-002 merged; **ECR-0066, ECR-0067, ECR-0068 landed**; `S-001_Addendum_II_Report_Limits.md` read; **owner has authorised non-mutating access to the target and the ECR-0070 transient-Syft exception.**
**ECRs:** **ECR-0069** — the data-handling boundary (§2); **ECR-0070** — the transient collector boundary (§4). Every prior S-milestone scanned public artefacts; this one does not, and both constraints are durable and inherited by S-004+.
**Definition of Done:** the chain runs on the real host; **no per-asset detail leaves the local store**; no persistent estate state changes; no service is restarted or reconfigured; any handed-in Syft executable and its isolated runtime are absent after success or failure; density report re-run and attached (counts only); both backends, both tenant modes, `python -O`; `mypy --strict src tests`; `gh pr checks` PASS before merge.

---

## Why this target, and why not a fresh one

S-002's corrected report left a **three-way tie at 200 closable unknown** —
`baseline`, `exposure`, `mission` — and all three need the same thing, which is
not a data source: a **deployment**, an **owner**, and an **approved
configuration**. None is expensive. All three are **structurally unanswerable for
a public container image.**

The chosen target is **deliberately not a fresh box.** A newly provisioned VPS
contains only what its owner just installed — a **declared estate wearing real
infrastructure's clothes**, and the same blind spot option 2 was rejected for
(rules 26/27). The value of this host is that it **accumulated**.

Reviewer-verified before drafting, read-only:

| | container (S-001/002) | this VPS |
|---|---|---|
| packages | 146 | **830** |
| listening services | **none** | **10** |
| running units | n/a | **26** |
| vendor products | none | **nginx, openssh-server** |

**`exposure` now has something to derive a surface *from*** — the factor that was
structurally unanswerable is the one this milestone exists to exercise.

---

## 1. The `exposure` source is the host's own configuration — **never a scan**

The instinct for reachability on a real host is *"what's open?"* → a network scan.
**That is wrong three times over:**

1. It may breach the provider's terms and can trip abuse detection.
2. It touches a **live production box** running services that move money.
3. **It breaks EA-0023's founding boundary** — active scanning is an **action**,
   not analysis, and would be an un-gated one.

**The correct source is what EA-0023 was always built for: the host's own state,
read locally.** Listening sockets, firewall rules, unit definitions,
reverse-proxy configuration. All read-only, all within the box, **no packet sent
anywhere.**

> **And it is better data than a scan.** A scan reports what is reachable *from
> wherever the scanner happens to sit*. The configuration reports **what the host
> intends to expose** — which is what a surface derivation actually wants, and what
> a `KnownSurfaceRecord` is shaped to carry.

Same handed-in shape as S-001: the driver reads, produces a document, hands it in.
**No engine learns a host exists.**

## 2. The data-handling boundary — new, and structural (ECR-0069)

S-001 and S-002 scanned public artefacts where nothing was sensitive. **This
inventory carries hostnames, addresses, service topology, and versions of software
the owner actually runs.**

> **Aggregate counts may leave the box. Per-asset detail may not.**

| Artefact | Contains | May it leave? |
|---|---|---|
| density report | factor counts, reasons | **yes** — PR body, discussion |
| findings dump | asset names, ports, versions | **no** — local Postgres only |
| collection documents | full host inventory | **no** — local disk only |
| declaration file (§3) | service names and tiers | **no** |

**Make this structural, not remembered.** The density report emitter SHALL be
**incapable of carrying per-asset detail** — it takes counts and reasons, and has
no code path from a finding's identifying fields to its output. A rule someone
must remember is the wrong shape here; the platform's own idiom (no person-score
type, no secret-value field) applies to its tooling.

**Never commit a collection document as a fixture.** The temptation is real —
it would make the run reproducible. It would also commit the owner's
infrastructure to a git history.

## 3. The criticality declaration — **discovery first, then declaration**

`mission` needs a real `criticality_tier` per asset, from a person. That input is
the reason a real estate was chosen over a declared one, and **it must not be
supplied by anyone who has not seen the machine.**

**Sequence, and it matters:** the driver **discovers** the 26 units → presents the
discovered list → the **owner declares against that list** → the run proceeds.
Declaring beforehand means declaring against an *inferred* inventory, which is the
inference-versus-reality problem this target was chosen to avoid.

**Vocabulary** (EA-0007 keys on `criticality_tier`, 1 most critical):

| Tier | Meaning |
|---|---|
| **1** | loss or compromise causes immediate material harm — money, personal data, legal exposure |
| **2** | significant disruption, recoverable |
| **3** | inconvenience only |
| **`undeclared`** | *not yet decided* |

> **`undeclared` is the shipped default and produces `mission: unknown`.** Not a
> placeholder filled with something plausible — the platform's own discipline
> applied to its input: **not deciding produces an honest unknown rather than a
> quiet default.** A partially completed declaration is an honest partial answer,
> **not a failure**, and the report says which assets are undeclared.

This is ECR-0013's shape prevented before it exists rather than corrected after.

## 4. No persistent estate change, **verifiably** (ECR-0070)

Nothing in this milestone installs, enables, restarts, or reconfigures estate
software or services. U1 may consume one owner-approved, checksum-pinned Syft
executable handed in under the system temporary directory. Syft's `HOME`, XDG,
and temporary paths are isolated for the collection lifetime. The executable and
the entire runtime tree SHALL be removed in a `finally` path, and collection SHALL
refuse success unless their absence is verified.

This is deliberately narrower and more honest than "no bytes are written."
Installing Syft would change persistent estate state. A package-manager-only
inventory would silently omit service virtual environments. The transient
executable preserves the complete filesystem inventory without either false
claim.

- **Enumerate every command the driver runs against the host**, in the bundle's
  output, so a reviewer can read the list rather than trust the intent.
- **No collection command may mutate estate state** — no
  `systemctl start/stop/restart/reload`, no package operation, no config write, no
  service probe that induces load. Transferring the approved Syft artifact is an
  explicit pre-collection handoff, not a hidden collector network path.
- **Production safety:** the box runs trading services. Collection SHALL be
  time-, output-, and worker-bounded and SHALL NOT restart, reload, or stress any
  unit. The root filesystem scan excludes pseudo-filesystems, transient runtime
  trees, and caches, but SHALL NOT exclude application trees or virtual
  environments.
- **Preflight and cleanup are gates:** missing required tools produce a named
  refusal before any command runs; an absent/malformed checksum refuses the
  transient executable; cleanup failure makes the whole collection fail.
- Where elevated access is genuinely required (process names on listening
  sockets), note it explicitly rather than escalating silently — and prefer the
  unprivileged form where the data is equivalent.

---

## U1 — Collection: three documents, handed in

**Deliverable:** the non-mutating driver produces, on the host:

1. **package inventory** — SBOM of the 830 packages (`syft` against the filesystem,
   as S-001 did against an image). Use installed Syft when present; otherwise use
   the ECR-0070 transient handoff. A `dpkg`-only fallback is forbidden because it
   cannot see service virtual environments;
2. **service/surface document** — listening sockets, firewall rules, unit
   definitions, reverse-proxy config (§1);
3. **unit inventory** — the 26 running units, for §3's declaration.

All three are **documents handed in**; nothing under `src/aqelyn/` learns a host
exists. Driver stays outside the package for the **architectural** reason (a
collection-invoking module inside the package *is* live collection) — **not**
because a guard would fire.

**Acceptance:** `test_s003_no_host_reference_in_src`,
`test_s003_collection_commands_enumerated`,
`test_s003_transient_syft_is_verified_and_removed`,
`test_s003_cleanup_is_verified_before_success`.

## U2 — The declaration mechanism

**Deliverable:** a declaration file mapping discovered units → `criticality_tier`,
with **`undeclared` as the default**, feeding EA-0007. Undeclared assets produce
`mission: unknown` with the reason *"criticality not declared"* — a **closable**
unknown in S-002's taxonomy, since a person can close it.

**Acceptance:** `test_s003_undeclared_is_unknown`,
`test_s003_partial_declaration_honest`,
`test_s003_declaration_never_defaults_favourably`.

## U3 — `exposure`: surface derived from configuration

**Deliverable:** the service/surface document → **EA-0025** asset registration →
**EA-0023** `KnownSurfaceSource` / `KnownSurfaceRecord` → `derive_surface`.

**The chain is longer than S-001's and that is where it will break:** services must
be ingested as assets *before* a surface can be derived from them. A service that
fails to register produces **no** surface record, and the factor reports unknown —
correctly, but for the wrong reason. **Distinguish "no surface derivable" from
"asset never registered"**; they look identical in the output and imply different
fixes.

**Acceptance:** `test_s003_services_registered_as_assets`,
`test_s003_surface_derived_from_config`,
`test_s003_unregistered_asset_distinguishable`.

## U4 — `baseline` *(conditional — build only if a baseline exists)*

**If an approved configuration baseline exists for this host**, hand it in and
compare via the **EA-0012** comparator shape.

**If none exists — which is the likely answer for a personal VPS — `baseline`
stays `unknown`, and that is a valid outcome, not a failure.** The report says
*"no approved baseline declared"*. **Do not invent a baseline to make the output
look better**; that would be option 2 smuggled in through the back door, and it
would produce exactly the ~100% known result that made option 2 the wrong choice.

**Acceptance:** `test_s003_no_baseline_is_unknown_with_reason`.

## U5 — Run, KEV re-check, density report

**KEV must be re-checked as its own step.** S-002 found KEV and container SBOMs
near-disjoint (2.4% vendor products). **nginx and openssh-server are exactly the
vendor-product class KEV catalogues** — so the result may differ. **Check the join
explicitly and report the number**, whichever way it comes out. S-002's CVE join
returning **zero** is what stopped a milestone being built on a falsified premise,
and *a silent zero is indistinguishable from a correct implementation finding
nothing.*

**Then the density report** — counts and reasons only (§2), attached to the PR.

**Acceptance:** `test_s003_kev_join_verified_and_reported`,
`test_s003_chain_end_to_end`, density report attached.

---

## Expected outcomes — write these down before the run

Per S-002's lesson (its stated expectation was **wrong**, and that was only
visible because it had been written first):

| Factor | Expected |
|---|---|
| `mission` | **partially known** — as many as are declared; undeclared stay unknown |
| `exposure` | **partially known** — 10 listening services, but the surface chain is unproven |
| `baseline` | **unknown**, with the reason *no approved baseline* |
| `threat` (KEV) | **unknown either way** — the join must be measured, not predicted |
| `cvss` | 830 packages: expect **several times S-001's 302 records** |

> **A run showing all three tied factors at ~100% known would mean something went
> wrong** — most likely a default filling in where a declaration or a derivation
> was absent.

## Predicted failures

- **The two new joins.** `service → asset` and `declaration → asset` are
  **unproven**; S-001's purl and S-002's CVE joins were both single-key and both
  needed explicit checking. What is the key here — unit name, process, port,
  path? Get it wrong and everything orphans **silently**.
- **Scale.** 830 packages may produce several thousand records — the first corpus
  large enough to touch `page_budget`, the EXPLAIN linearity question, or
  inventory limits. If any fires, that is a **first-deployment item becoming
  measurable**, not a defect.
- **A default filling a gap.** The highest-consequence failure: an undeclared
  asset scoring as tier 3, or an underivable surface scoring as unexposed.
- **Elevated access creeping in** because a command returned less than expected.

## Review protocol (Claude Code)

1. **No scan.** Confirm the exposure source is host-local configuration; no packet
   leaves the box; nothing probes a port.
2. **Read-only, enumerated.** Read the command list; confirm none mutates and none
   stresses a unit.
3. **Data boundary structural** (§2) — the report emitter has **no code path** from
   identifying fields to output. Confirm no collection document is committed.
4. **`undeclared` never defaults favourably**; partial declaration is honest.
5. **No invented baseline.**
6. **Both new joins verified explicitly** and their counts reported, including
   zero.
7. **KEV join measured, not assumed** — reported either way.
8. **Unregistered-asset versus underivable-surface distinguishable** (U3).
9. Both backends, both tenant modes, `python -O`; `mypy --strict src tests`;
   `gh pr checks` PASS.
10. **Density report attached, counts only.**

**Preserve:** `FIRST_DEPLOYMENT_ITEMS.md` (S-003 may make one measurable — record,
do not close it silently), **EA-0048**, and the retroactive re-review queue.

Merge only on green; then **report back to the owner** with the density report —
which, for the first time, will describe an estate rather than an artefact.
