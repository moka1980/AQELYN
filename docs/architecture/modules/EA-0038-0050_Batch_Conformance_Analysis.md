# EA-0038 – EA-0050 — Batch Conformance Analysis

**Subject:** the remaining archive batch — thirteen masters, `EA-0038` … `EA-0050`
**Finding A:** all thirteen are **same-generator stubs**. They share a skeleton
rather than being byte-clones (number-normalized hashes differ), but every one
carries boilerplate objectives and the generic 12-capability requirements matrix.
**No module-specific requirement text exists in any of them.**
**Finding B:** they do **not** share one disposition. Eleven are conformant via
shipped owners; **one is a genuine capability gap**; **one is not a capability at
all.**
**Recommendation:** one batch decision recording **three** dispositions — not one.
**Change control:** **ECR-0060** — *provisional number confirmed by the reviewer
against `ECR-LOG.md` at `2699006`: the highest allocated ECR is 0059 (C-034) and
0060 is free. Rule 1 discharged.*
**Status:** Accepted — implemented by C-035. All eleven Disposition-A rows verified
against shipped `src/` (§2), EA-0048's gap re-confirmed by grep at the same SHA
(§3), EA-0050 classified (§4).

---

## 1. Why a batch decision is appropriate

Five individual conformance passes (IS-026, IS-034, IS-035, IS-036, IS-037)
returned the same verdict by the same method. EA-0036 and EA-0037 were confirmed
template stubs; the reviewer has confirmed EA-0038 – EA-0050 are the same
generator output. Thirteen further passes would repeat a settled procedure at
thirteen times the cost.

**But the batch is a decision about how to *record* the outcome — never a licence
to skip the check.** That distinction is not theoretical:

> **EA-0048 has no shipped owner.** A batch that swept all thirteen into
> conformance would have certified that AI security and model governance are
> already covered by the platform. **They are not.** The one item where the
> template heuristic gives the wrong answer is the one item a lazy batch would
> have buried.

So the per-item **capability map still runs** — it is cheap, it is the step that
found EA-0048, and it is what makes the batch safe. What the batch removes is
thirteen separate analyses, ECRs, and review cycles; what it keeps is the map.

### 1.1 The batch is safe *because* GC-001 and GC-002 are live

Before the guarantee suites, eleven conformance claims verified once and recorded
in prose would have been **reviewer-protected only** — a wrong row would surface
years later as a duplicate module nobody noticed.

That is no longer the failure mode. If any row here is wrong and someone builds
the module anyway:

- a new package under `src/aqelyn/` fails **GC-001**
  `test_gc_engine_discovery_complete`;
- a new composition scorer fails **GC-001**'s scorer registry;
- a new event namespace fails **GC-002**
  `test_gc_negative_control_unowned_prefix`.

**A wrong batch row becomes a loud CI failure rather than silent duplication.**
That is the payoff those two suites were built for, arriving on the first decision
large enough to need it.

## 2. Disposition A — conformant via shipped owners (eleven)

**Proposed mapping. Each row is a hypothesis derived from archive titles and my
own spec set; the reviewer verifies each against shipped `src/` before the batch
is accepted.** Any row that fails becomes its own pass, not a footnote.

| Archive master | Proposed owner(s) | **Verified evidence @ `2699006`** |
|---|---|---|
| EA-0038 Vulnerability Intelligence Correlation | **EA-0024** | `vuln/` — *"Vulnerability Intelligence & Prioritization Engine (EA-0024)"*; `VulnerabilityIntelligenceEngine` |
| EA-0039 Threat Intelligence Fusion | **EA-0014** — spec title is *"Threat Intelligence Fusion Engine"*, **verbatim** | `threat/` — *"Threat Intelligence Fusion Engine (EA-0014)"*, **verbatim**; `ThreatFusionEngine` |
| EA-0040 Attack Path & Exposure Graph | **EA-0023** + **EA-0005** (this is IS-037's chain) | `exposure/` — *"Threat Exposure & Attack Surface Management Engine (EA-0023)"*; `KnownDataExposureEngine.reachable_paths`; `graph/` — *"Knowledge Graph (EA-0005)"*. Certified by C-034. |
| EA-0041 Security Data Lake & Telemetry Fabric | **EA-0019** — *"Security Data Lake & Telemetry Platform"*, near-verbatim; already owns both `lake` and `telemetry` prefixes | `lake/` — *"Security Data Lake & Telemetry Platform (EA-0019)"*; `DataLakeService`, `RetentionEngine`; owns both prefixes per GC-002 |
| EA-0042 Detection (engineering/coverage) | **EA-0017** | `detection/` — *"Threat Detection & Analytics Engine (EA-0017)"*; `ThreatDetectionEngine` |
| EA-0043 Incident Command & Case Management | **EA-0015** + **EA-0018** | `soc/` — *"Security Operations (SOC) Engine (EA-0015)"*; `SecurityOperationsEngine`. `response/` — *"Automated Response & Orchestration Engine (EA-0018)"*; `ResponseOrchestrationEngine` |
| EA-0044 Forensic Evidence Preservation | **EA-0016** + **EA-0004** | `forensics/` — *"Digital Forensics Engine (EA-0016)"*; `DigitalForensicsService`. `evidence/` — *"Evidence & Integrity (T4) … EA-0004-evidence-and-integrity.spec.md"* |
| EA-0045 Cyber Risk Quantification | **EA-0013** | `risk/` — *"Risk Intelligence Engine (EA-0013)"*; `RiskIntelligenceEngine` |
| EA-0046 Control Validation & Continuous Assurance | **EA-0010** | `governance/` — *"Compliance & Governance Engine (EA-0010)"*; `ComplianceEngine`, and `Control` / `ControlResult` / `FrameworkCoverage` / `ComplianceSnapshot` are the control-validation surface |
| EA-0047 Supply Chain Security Governance | **EA-0030** | `supplychain/` — *"Software Supply Chain Security and SBOM Intelligence public API (EA-0030)"*; `SupplyChainEngine` |
| EA-0049 Privacy, Data Protection & Sovereignty | **EA-0031** + **EA-0010** | `dspm/` — *"Data Security Posture Management public API (EA-0031)"*; `DSPMEngine`. Framework/compliance side via `governance/` (EA-0010) |

**Reviewer note on row EA-0046.** The analysis header called this row *"Compliance
Assurance"*; the archive master's actual title is **"Control Validation & Continuous
Assurance Engine"**. Corrected above. The disposition is unchanged — `governance/`
ships the control-validation surface — but the row is recorded under the title the
archive actually carries, since a paraphrased title is how a mis-mapping starts.

**All eleven confirmed.** No row failed, so no row becomes its own conformance pass.
The mapping is pinned mechanically by
`tests/conformance/test_batch_ea0038_0050.py::test_batch_disposition_a_owners_present`,
which fails if a package is renamed, removed, or renumbered out from under a row.

Two **verbatim / near-verbatim title matches** (0039 → EA-0014, 0041 → EA-0019)
carry the same signal strength as the package-docstring matches that made IS-037
the clearest case yet.

**For all eleven the standing prohibitions apply:** no package under
`src/aqelyn/`, no second engine, composer, or scorer, **no parallel event
namespace**, no new `SignalKind`, and no capability that acts — remediation stays
EA-0008-gated.

## 3. Disposition B — **EA-0048 is an open capability gap**

`EA-0048 — AQELYN AI Security & Model Governance Engine` (verified: stub, with
boilerplate objectives). The reviewer's grep against shipped `src/` finds
**nothing** covering AI security or model governance across all 35 packages. My own
28-spec set contains no owner for it either.

> **Reviewer correction.** An earlier pass reported that `model_governance`,
> `ai_security` and `model_card` "hit only `secrets/`". That was a substring
> artefact: the pattern included bare `llm`, which matched `fullmatch(` in
> `secrets/models.py:189` and `secrets/store.py:127`. Re-run at `2699006` over the
> precise term list — `model_governance`, `ai_security`, `model_card`, `model_risk`,
> `model_inventory`, `model_bias`, `prompt_injection`, `training_data`, `ml_model`,
> `ai_system` — the result is **zero hits anywhere in `src/`, including `secrets/`**.
> The distinction matters: "hits only in `secrets/`" reads as partial coverage and
> invites a future mapper to promote `secrets/` to partial owner. There is no
> coverage at all. Asserted by
> `tests/conformance/test_batch_ea0038_0050.py::test_batch_ea0048_no_owner`.

**This is the first genuine capability gap the archive has surfaced.** It is also
the one item where the same-generator heuristic would have produced a false
certification.

### 3.1 The false friend — EA-0020

**`EA-0020` is the "AI Decision Intelligence Engine", and it is not the owner.**
EA-0020 is **AI used *by* AQELYN** — replayable derivations, recommendations,
explainability of the platform's own reasoning. EA-0048 would be **governance *of*
customer AI/ML systems** — model inventory, model risk, training-data exposure,
inference-time abuse.

Opposite directions: one is *AQELYN's use of AI*, the other is *AQELYN's
protection of AI*. A mapper working from titles would plausibly route 0048 to 0020
and close the gap wrongly. This is the **rule 20 shape in a new dress** — a
name that looks like an owner and isn't.

### 3.2 No shipped owner ≠ should build

The gap is real; **that does not make it scope.** Two facts hold at once:

- The archive **names** a capability the platform does not have.
- The archive **specifies** nothing about it — the master is a stub, so there is
  no requirement text to build from.

That is a situation this project has not met before: **a genuine capability gap
with no specification.** Every prior module either had requirements to reconcile
or had an owner to route to; this has neither.

Therefore EA-0048 is recorded as an **open capability gap**, not a scheduled
build. If the owner wants it, **the requirements come from the owner, not from a
stub** — and it would be the first module in the platform specified from intent
rather than reconciled against the archive. That is a deliberate product decision,
and it should be made as one.

## 4. Disposition C — **EA-0050 is not a capability**

`EA-0050 — AQELYN Platform Implementation Blueprint & Coding Readiness Baseline`
(verified: stub). This is a **document about how to start coding**, not a module
claim. There is nothing to certify conformance against, and no owner to route to
— asserting "conformant" would be a category error.

It is classified **non-capability**, alongside **EA-0051** (the same family). A
batch that swept it in would have certified conformance for a process document.

## 5. Rule 20 — number collisions across this batch

**EA-0040 is the live one.** The archive's `EA-0040 Attack Path & Exposure Graph
Engine` collides with **ECR-0040**, the optimistic-default correction precedent
that is cited throughout C-034's records. The collision is **bidirectional and in
active documents**: a drafter searching "0040" finds a real, load-bearing change
decision *and* an unrelated archive title.

More generally, this batch spans numbers that overlap the ECR log's own range
(0038–0050 vs ECR-0038–0050, all of which exist and are unrelated). **A matching
number transfers no scope** (rule 20); the source family must be verified every
time. That applies to Blueprint volumes and index rows too — importing
Volume_037's *Distributed Scan Engine* would have reversed EA-0023's no-scan
boundary.

## 6. What this batch decision does **not** do

- It does **not** waive verification. Each Disposition-A row is confirmed against
  shipped code before acceptance (§7).
- It does **not** pre-approve future work. EA-0048 is recorded as a gap, not
  scheduled.
- It does **not** retire the template check. If a later archive item turns out to
  carry real requirement text, it gets its own pass.

## 7. Verification protocol for accepting the batch

1. **Confirm each Disposition-A row against shipped `src/`** — the owning package,
   and the API or docstring that realizes the archive's capability. Proportionate
   to the claim: these are restatements of already-certified owners, and
   **GC-001/GC-002 provide the mechanical backstop** (§1.1). No eleven chain proof
   tests.
2. **Confirm EA-0048 has no owner** — re-run the grep at the current SHA; a single
   false negative here is the difference between a recorded gap and a wrongly
   closed one.
3. **Confirm EA-0050's classification** — non-capability, no conformance claim.
4. **Rule 20 sweep** — no archive item's scope inherited from a same-numbered ECR,
   Blueprint volume, or index row.
5. **Record** the three dispositions, and mark the archive **exhausted as a
   requirements source** (§8).

## 8. The implication worth stating

With this batch resolved, **the archive stops being a source of requirements.**
Every remaining master is a stub; eleven restate shipped owners, one names a gap
it does not specify, and one is a process document.

That is not a loss — it means the reconciliation work is finished. **The real
backlog is now the tracked follow-ups plus whatever the owner decides to build:**

- **ECR-0034 cursor pagination** (the open half — the honest flag shipped in
  C-034; the cursor is what lets a >10 000-asset tenant be *answered* rather than
  correctly refused),
- ECR-0032 (shared posture-normalization base, four instances, still Proposed),
- EA-0018 unclamped negative-duration flake,
- EA-0027/EA-0018 enterprise-mode health probes,
- EA-0013 equal-timestamp finding tie-breaker,
- **EA-0048**, if the owner wants it — specified from intent, not from the archive.

Beyond that list, the two structural gaps every spec has deferred — **live
collection** (11 specs defer it to a future EA-0008-gated connector) and **the UI
surfaces** (23 specs name a WCAG 2.2 AA consumer that does not exist) — are
product decisions rather than reconciliation work, and are the owner's to sequence.
