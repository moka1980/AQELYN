# S-004 — The Privileged Capture — Task Bundle

**Track:** S (operational)
**Milestone:** S-004 (implement ECR-0077; close the four dependents)
**For:** the **owner** (capture only) · Codex (implementer) · Claude Code (reviewer + the real-estate run)
**Prerequisites:** S-003 complete; C-041 merged (`main @b5c574b`); **ECR-0077 read in full**; `SPEC_AUTHOR_NOTES.md` rules 1–32.
**Data handling (ECR-0069):** **counts and classes only.** No service name, port, address, path, hostname or certificate subject appears in this bundle, in any test, in any fixture, in any PR body, or in the density report.
**Definition of Done:** the four dependents resolve or report an honest unknown; **the driver gains no privileged path**; every derivation cites which capture it used; a stale cross-document join **refuses**; both backends, both tenant modes, `python -O`; `mypy --strict src tests`; `gh pr checks` PASS.

---

## The sentence that governs the milestone

> **The driver does not need privilege. The owner needs it, once.**

A document produced by a privileged command **run manually** is indistinguishable, to every
engine, from one the driver produced. So this milestone adds a **capability** without adding
a **collector**.

**If the diff gains a `sudo`, an elevated subprocess, a privileged service account, or a new
entry in ECR-0070's enumerated driver command list — the milestone has become the thing it
was designed to avoid.** Stop and raise.

---

## W1 — Owner capture *(blocking; nothing else can start)*

**Owner action, once, manually.** Three documents, all read-only:

| document | contains | why |
|---|---|---|
| **proxy configuration dump** | front-end → upstream topology, certificate references | the two-hop chain; C5's certificate path |
| **firewall ruleset listing** | filtering rules as configured | corroborates bind-derived reachability |
| **privileged socket listing** | listeners **including process ownership** | listener → asset attribution |

**Each capture records its timestamp** (ECR-0077 §4a). Save alongside the existing S-003
collection documents.

> **ECR-0069, harder than before.** A proxy configuration can carry certificate paths,
> upstream credentials and internal topology. **Local disk only. Never committed as a
> fixture. Never in a PR body.** The temptation is stronger this time because a
> hand-captured document is awkward to reproduce and committing it would make the run
> repeatable — **that is precisely the trade ECR-0069 forbids.**

**Acceptance:** three documents present, each with a recorded capture time; none in git.

## W2 — Hand-in, pinned

**Deliverable:** the documents are parsed and handed in exactly as the SBOM is — pure
parsers, no I/O, no subprocess, no network. **Nothing under `src/aqelyn/` learns a host, a
command, or a privilege level exists.**

**Every derivation that consumes one of these documents cites which capture it used.** A
configuration dump is a point-in-time snapshot; an uncited one replays against a moving
target, which is ECR-0067's shape arriving through data rather than code.

**Acceptance:** `test_s004_no_privileged_path_in_src`,
`test_s004_derivation_cites_capture`, `test_s004_parsers_pure`.

## W3 — The freshness gate *(the hazard specific to this milestone)*

The socket observations and the proxy configuration are **captured at different times**.
Joining a listener observed at one moment to a topology captured at another can produce a
**confident wrong answer** — a service that has since restarted, moved or been
reconfigured.

> **A stale cross-document join must refuse, not resolve.** The tolerance is an owner
> decision; **distinguishability is not.** A join across documents whose ages are unknown is
> the same defect family as an unpinned catalogue.

**Deliverable:** capture times compared before any cross-document join; beyond tolerance →
**refuse with a named reason**, never a best-effort resolution.

**Acceptance:** `test_s004_stale_join_refuses`,
`test_s004_join_reason_names_the_staleness`.

## W4 — Attribution, and the state that must survive

**Deliverable:** listener → asset attribution using process ownership, joined to the unit
inventory.

> **U3's third state — *observed but not attributable* — must remain expressible.** A
> listener from a process that has since exited, or one owned outside the visible namespace,
> is still exactly that. **A state that becomes rare is not a state that becomes wrong**, and
> removing it because the common case now resolves would delete the distinction U3 was built
> to preserve.

**The three-way contrast still holds** (U3): registered-with-no-surface, observed-but-
unattributable, and not-registered-at-all remain **distinguishable by name**, with three
different remediations.

**Acceptance:** `test_s004_attribution_resolves_where_evidence_exists`,
`test_s004_unattributable_state_still_reachable`,
`test_s004_three_states_still_distinguishable`.

## W5 — The two-hop chain

**Deliverable:** where the proxy configuration **declares** a front-end → upstream
relationship, the chain becomes derivable and is expressed through the shipped EA-0023 seam.

**Two honest limits to encode rather than paper over:**

1. **The chain is only as good as the declaration.** A configuration states intent; if a
   declared upstream is not on this estate, the chain **terminates outside what the platform
   can see**. That is an unknown with a named reason, not a failure.
2. **Bind-derived reachability and declared topology are different evidence.** Record which
   produced a judgement (ECR-0073 §3 — a record may not claim a basis it did not use).

**Acceptance:** `test_s004_declared_chain_derived`,
`test_s004_offestate_upstream_is_unknown_with_reason`,
`test_s004_basis_distinguishes_bind_from_config`.

## W6 — Baseline C1 and C5

**C1** becomes checkable from the privileged socket listing. It evaluates through **U4's
existing resolution gate** — resolve, then compare; unresolved short-circuits to `unknown`.
**Do not bypass the gate** because evidence is now available.

**C5 needs two things, and only one of them is in the proxy configuration.**

| | source |
|---|---|
| certificate **path** | proxy configuration ✓ |
| certificate **validity** | **not in it** |

> **Route the certificate metadata to EA-0032**, which already owns certificate lifecycle
> with tri-state expiry, chain and revocation. **Do not build a validity check inside the
> baseline comparator** — that would be a second certificate authority in a platform whose
> §0 is *one capability, one owner*, and EA-0032's tri-state already refuses the
> absence-means-valid reading a bespoke check would invite.

**C5 therefore becomes** a baseline claim evaluated against **EA-0032's assessment**, and it
stays `unknown` if the certificate metadata was not captured — honestly, and with the reason
naming which half is missing.

**Acceptance:** `test_s004_c1_checkable_via_gate`,
`test_s004_c5_routes_to_ea0032`, `test_s004_c5_unknown_when_cert_metadata_absent`.

## W7 — Run, and re-run the density report

**Deliverable:** the full chain, then the density report — counts and reasons only.

**The report should show the closable column shrinking**, and the reasons changing for what
remains. **Reasons must still distinguish closability class**; a factor that is now unknown
for a *different* reason has not simply stayed the same.

**Acceptance:** `test_s004_chain_end_to_end`, density report attached to the PR.

---

## Expectations — written before the run

Per S-002's discipline, where the stated expectation was **wrong** and that was only visible
because it had been written first:

| | expected |
|---|---|
| **attribution** | most of the previously unattributable listeners resolve — **not all**; expect a residue |
| **two-hop chain** | derivable for the declared relationships; some upstreams may sit off-estate |
| **C1** | **checkable** — pass or fail, no longer unknown |
| **C5** | **still unknown** unless certificate metadata was captured too |
| **exposure** | the closable unknowns fall materially; the structural ones do not |

> **A run showing 16 of 16 attributed and every claim resolved would mean something went
> wrong** — most likely a resolution accepted on evidence that does not support it, which is
> the shape U4's `pid=1` fixture nearly filed as a defect.

## Proof

- **No privileged path in `src/`** — mutation: introduce one and confirm a control fails.
- **Every derivation cites its capture**; an uncited one is rejected.
- **A stale join refuses** — drive it with documents whose capture times differ beyond
  tolerance.
- **The unattributable state is still reachable** — a listener with no resolvable owner
  produces it.
- **C5 routes to EA-0032**; no validity logic in the baseline comparator.
- **ECR-0069 structural** — the report emitter still cannot carry per-asset detail;
  no capture document is committed.
- Both backends, both tenant modes, `python -O`.
- **Real-estate run by the reviewer before merge**, counts only in any output.

## Review protocol (Claude Code)

1. **No `sudo`, no elevated subprocess, no new driver command.** ECR-0070's enumerated list
   is **unchanged** — the driver does not run these captures.
2. **No capture document committed**, in any form, including as a test fixture.
3. **Captures pinned**; derivations cite which one.
4. **Stale joins refuse**, with the reason naming staleness rather than absence.
5. **The unattributable state survives** and is reachable.
6. **C5 goes to EA-0032**, not to a bespoke check.
7. **Basis honesty** — bind-derived and config-derived judgements are distinguishable.
8. `mypy --strict src tests`; both backends; both tenant modes; `python -O`;
   `gh pr checks` PASS.

**Carried forward, unaffected:** the **19 declined units** (owner's — *deliberately
unweighted*, *deferred*, or *inherited*); the three first-deployment items; **EA-0048**.

**After this,** the roadmap's honest column is what remains: **there is still no way in and
no way to see.**
