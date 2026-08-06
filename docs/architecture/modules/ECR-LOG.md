# Engineering Change Request (ECR) Log

Records approved changes to **Accepted** module specs, so amendments happen
under change control rather than silent edits (per `START_HERE.md`).

| ECR | Against | Status | Summary |
|---|---|---|---|
| ECR-0001 | EA-0005 Knowledge Graph | Accepted | Add a `max_work` enumeration budget to `paths()`. |
| ECR-0002 | EA-0009 Policy Engine | Accepted | Harden condition attribute lookup against dunder traversal. |
| ECR-0003 | EA-0013 Risk Intelligence | Accepted | Tenant-qualify the correlated `Risk.id` to prevent a cross-tenant PK collision. |
| ECR-0004 | EA-0002 Universal Object Model | Accepted | Add `ObjectQuery.exclude_object_types` so a query can bound results to a subset of types. |
| ECR-0005 | EA-0004 Evidence & Integrity | Accepted | Add `EvidenceStore.custody_of()` and explicit intake custody rows for reconstructable custody. |
| ECR-0006 | EA-0018 / IS-018 | Accepted | Realize IS-018 as an orchestration layer above EA-0008, not a second executor. |
| ECR-0007 | cross-cutting (verification method) | Accepted | Grep-based enforcement is insufficient; require behavioural/structural proof. |
| ECR-0008 | EA-0017 Threat Detection | Accepted | `project()` superseded by EA-0021; EA-0017 keeps its S4 stance. |
| ECR-0009 | EA-0022 / IS-022 | Accepted | Override master §28.2/§28.3: a missing/failed executive figure is omitted + recorded, never backfilled with a stale value. |
| ECR-0010 | EA-0022 / IS-022 | Accepted | Composite `Figure.as_of` uses the **stalest** input (`min`), not the newest — a single timestamp must not overstate freshness. |
| ECR-0011 | EA-0023 / IS-023 | Accepted | Exposure is derived from known data; **no `scan()`/`probe()`/`connect()`**. Active scanning is an EA-0008 `scan.active` ActionSpec. Overrides master §20.3 scan endpoint + §28.2/§28.3. |
| ECR-0012 | EA-0024 / IS-024 | Accepted | CVSS/EPSS carried, **never recomputed**; every assessment carries a mandatory `CoverageReport` and is **refused if coverage can't be computed** (not-scanned ≠ clean). Overrides master §12.2 severity-normalization + §28.2/§28.3. |
| ECR-0013 | cross-cutting (unwired-dependency default) | Accepted | An unwired dependency's default implementation MUST be **inert or refusing, never optimistic**. Fixes EA-0024's coverage provider (reported `unscanned=[]`) to refuse. |
| ECR-0014 | EA-0025 / IS-025 | Accepted | Absence ≠ decommission (asset → `unreported`, never retired from silence); `inventory()` declares freshness + fails rather than shrinks; reconciliation **records** conflicts (EA-0006 precedence). Overrides master §28.2. |
| ECR-0015 | EA-0026 / IS-026 | Accepted | **IS-026 is IS-012 restated — do not build EA-0026.** EA-0012 already ships baseline/drift/classify/remediation and the `configuration.drift.detected` event. Realize IS-026's intent as a small EA-0012 enhancement (C-023). |
| ECR-0016 | EA-0027 / IS-027 | Accepted | Identity detection watches **accounts, not people**: no per-person risk score (absent), no insider-threat *prediction*; a **dignity gate** (≥2 corroboration + confidence floor > platform default) is non-negotiable. Overrides master §429 risk-score + §107/261 insider-threat + consumes EA-0017's `behavior.profile.updated`. |
| ECR-0017 | EA-0027 / IS-027 | Accepted | Corroboration independence is keyed on the **signal** (`ref`, and `evidence_id` when present), not on `(kind, ref)` — one occurrence relabelled twice is **one** corroboration, so the ≥2 floor cannot degrade to 1. Undecidable ties count as one. |
| ECR-0018 | EA-0027 / IS-027 | Accepted | Replace the under-specified `detect(subject_ref, signals, tenant_id)` input with a structured `IdentityObservation` carrying detection type and pinned profile/rule versions; the engine renders the account-scoped statement and basis. |
| ECR-0019 | EA-0027 / IS-027 | Accepted | Make I4's IAG identity input and append-only right-of-reply record explicit: `IdentityObservation.identity_id` delegates to EA-0011; one evidenced `IdentityReview` materializes reviewed status without mutating the detection row. |
| ECR-0020 | EA-0028 / IS-028 | Accepted | Realize CSPM as a verdict-free normalization + routing layer over existing owners, with explicit partial-route outcomes and provider deletion mapped to EA-0025 `unreported`, never decommissioned by silence. |
| ECR-0021 | EA-0028 / IS-028 | Accepted | Close the two soft spots in EA-0028's verdict boundary: `native_facts` keys MUST equal `field_provenance` keys (nothing enters normalized state without a declared raw source), and CSPM does **not** emit `aqelyn.cloud.misconfiguration_detected` — an EA-0012 cloud-baseline failure is EA-0012's event, filtered by cloud object_type. |
| ECR-0022 | EA-0028 / IS-028 | Accepted | Make the normalized cloud record tenant-owned and every store read explicitly tenant-scoped; the Accepted draft otherwise could not satisfy CONVENTIONS §5 or AC-10 on Postgres. |
| ECR-0023 | EA-0028 / IS-028 | Accepted | ECR-0021's provenance binding is top-level only, so an invented verdict one level down (`native_facts["tags"]["posture_grade"]`) still passes. `native_facts` values are constrained to scalars or lists of scalars: structured provider material belongs in raw EA-0004 evidence, and every normalized key is then provenance-bound. |
| ECR-0024 | EA-0028 / IS-028 | Accepted | Make selective flattening explicit: config maps each normalized fact key to an RFC 6901 JSON Pointer in the handed-in raw provider record; generic provider-block flattening is forbidden. |
| ECR-0025 | EA-0028 / IS-028 | Accepted | A configured fact path missing from a later snapshot silently deletes a previously-known fact. Absence is **unknown**, not a change: the fact is retained with its last-known value, marked `unreported`, and the object is flagged — never dropped without trace (the ECR-0014 rule at field level). |
| ECR-0026 | EA-0028 / IS-028 | Accepted | Y3 routes a typed, evidence-backed `CloudRouteEnvelope` containing the full normalized object to owner adapters. The six heterogeneous owner APIs are not rewritten, and no adapter may strip ECR-0025's `unreported_facts`; provider deletion is recovered from the pinned evidence and maps only to inventory `mark_unreported`. |
| ECR-0027 | EA-0028 + EA-0012 | Accepted | `apply_cloud_baselines` can never assess a cloud object: EA-0012's asset query hard-forces `object_type="asset"` while CSPM normalizes to `cloud_*`. It returns a clean-looking empty snapshot. EA-0012 gains a configured set of assessable object types, and an assessment that applied no baseline to in-scope objects must be surfaced, never reported clean. |
| ECR-0028 | EA-0012 + EA-0028 | Accepted | Complete ECR-0027: plumb ACG/CSPM config through both runtime factories; apply query budgets independently per object type; persist complete, per-type baseline coverage; distinguish empty scope from missing baselines; and amend EA-0012's owner contract. |
| ECR-0029 | EA-0012 + EA-0028 | Accepted | ECR-0028's `coverage_complete` is asserted over a truncated page budget. When a type's `ObjectQuery.limit` is exhausted while a `next_cursor` remains, `_asset_pages` breaks and the unseen objects are counted nowhere; the snapshot reports `coverage_complete=true` and an `objects_in_scope` that is the number of objects *looked at*, not the number in scope. `apply_cloud_baselines` with no scope materializes `ObjectQuery()` with its default `limit=100`, so any cloud estate above 100 objects reports a complete, clean assessment of its first 100. Truncation must make coverage incomplete, and an unscoped assessment must not silently impose a bound the caller never chose. |
| ECR-0030 | EA-0002 (+ EA-0010, EA-0011, EA-0014, EA-0015) | Accepted | PR #164 silently repaired two latent `ObjectStore.query` defects while fixing EA-0012: neither backend had ever returned a `next_cursor` (every paging loop in the platform stopped after one page believing it was complete), and Postgres filtered `labels`/`natural_key` in Python *after* the SQL `LIMIT` (a label-filtered query returned 0 rows where 50 matched). The repair is correct but undisclosed: EA-0002's spec is unchanged, and the consumers are unswept — EA-0010 and EA-0011 change coverage silently, while `soc` and `threat.correlate` discard the cursor and remain capped at one page. |
| ECR-0031 | EA-0015 + EA-0014 (+ EA-0002 in-memory store) | Accepted | ECR-0030's consumer sweep replaced "silently capped at one page" with "scan the whole estate per request". A hunt whose attribute filter matches nothing, and a `correlate()` over an all-expired indicator set, now page to exhaustion: measured 40 queries / 2000 rows / 10.1s and 21 queries / 2000 rows / 3.4s respectively, scaling quadratically. EA-0015 D7/NFR-3 still say bounded. ECR-0001's rule applies — page under a work budget, and when the budget is hit return what was found with `truncated=true`, the pattern `DriftSnapshot` already uses. `hunt` additionally has no truncation channel to say it with. |
| ECR-0032 | EA-0028 + EA-0029 + EA-0031 + EA-0033 | **Rejected** | Shared posture-normalization base. Four instances share a *shell*; the divergence **is** the extension. Closed with a reopening condition. |
| ECR-0033 | EA-0029 (+ EA-0028 normalization store) | Accepted | Make SSPM uncertainty honest and connectable before C-026: `over_scoped` uses semantic tri-state tokens, bounded KG reach propagates truncation, confidence is explicitly in the source claim rather than the vendor, over-scoped grants use EA-0023's real `KnownSurfaceSource` seam, both factory runtimes prove owner wiring, and normalization-store queries use EA-0002-style cursor pagination instead of silently capped lists. |
| ECR-0034 | EA-0025 (+ EA-0023, EA-0024, EA-0030) | Resolved (C-034; silent truncation only — cursor pagination still open) | `InventoryIntelligenceEngine.inventory()` read `store.query(limit=10_000)` and returns `degraded=False` unconditionally; `AssetStore.query` has no cursor and no more-remaining signal. A tenant above 10 000 assets gets its first 10 000 reported as the complete inventory. That report is EA-0023's known-surface denominator and EA-0024's coverage base (`unscanned = inventory − scanned`), and both of their fail-closed gates are keyed on the `degraded` flag that is hardcoded `False` — so a silent cap shrinks the attack surface, under-reports unscanned assets, and cannot trip either refusal. EA-0030 now ingests SBOM components into the same store, making the cap reachable in ordinary operation. |
| ECR-0035 | EA-0029 | Accepted | `SaaSIntegration` holds two of the blast radius's three states. `reachable_object_ids=[] , reachable_truncated=False` is the record for both "traversal ran, reaches nothing" and "traversal never ran" (the KG-unavailable case §11 requires), and the ambiguity resolves toward safe. `over_scoped` already has an explicit `unknown` in the same model; reach does not. Replace `reachable_truncated: bool` with `reach_status: Literal["computed","truncated","pending"]`. |
| ECR-0036 | EA-0029 | Accepted | Make Z3's owner references and blast-radius read tenant-correct: `SaaSRoutingResult.inventory_ref` is an EA-0025 `ast_` id (not an EA-0002 `obj_` id), and `integration_blast_radius` requires explicit `tenant_id` so it cannot read the tenant-scoped integration store through an unscoped interface. |
| ECR-0037 | EA-0030 | Accepted | Make Q2's Trust reconciliation durable and its store pagination honest: components pin the winning source/time and retain every conflict candidate, malformed documents persist as flagged quarantine records, and `SBOMStore.query` adopts EA-0002 D8 cursor semantics. |
| ECR-0038 | EA-0030 | Accepted | Make Q3's truncation and path proof representable: `dependency_paths` returns paths plus `truncated`, and transitive reach embeds the exact EA-0005 path with a deterministic content-addressed `path_ref`. |
| ECR-0039 | EA-0030 (+ EA-0004 boundary) | Accepted | Evidence hash-chain integrity is not attestation authenticity: Q4 verifies EA-0004 integrity first, delegates cryptographic/bundle authenticity to a typed verifier, and keeps missing/unavailable verification flagged `unverified` while completed mismatches are `failed`. |
| ECR-0040 | EA-0030 + EA-0024 | Accepted (normalization clause **amended by ECR-0082/ECR-0083**) | Preserve unknown component reachability through vulnerability prioritization: factors carry `known|unknown`, unknown factors remain in the derivation but are excluded from the score denominator; add an asset-scoped vulnerability query and explicit Q5 owner methods. ⚠️**"known weights are renormalized" is superseded** — see ECR-0082 (all-weight denominator) and ECR-0083 (separate uncertainty surcharge). |
| ECR-0041 | EA-0031 + EA-0023 | Accepted | Connect DSPM to EA-0023's shipped `KnownSurfaceSource` seam, add an optional evidence-backed exposure-impact context for sensitivity-aware owner scoring, and make unknown/minimal-retention/pagination guarantees structural before C-028. |
| ECR-0042 | EA-0031 | Accepted | Make P4's assessment-to-finding handoff durable: add tenant-scoped assessment/exposure reads to DSPMStore, refuse incomplete assessments, and re-run a complete assessment's frozen scope through the owner exposure path when it carries no material ids. |
| ECR-0043 | EA-0032 / IS-032 | Accepted | Realize secrets/crypto as a value-free, handed-in lifecycle engine over existing inventory/exposure/compliance/risk owners; unknown is never safe, integrity is not authenticity, and remediation is finding-bound proposal only. |
| ECR-0044 | EA-0023 + EA-0032 | Accepted | Add a semantic `credential_sensitivity` exposure-impact kind while preserving `data_sensitivity` as the default; crypto contexts must name their real meaning in the replayable derivation. |
| ECR-0045 | EA-0032 | Accepted | Make W2 reconciliation and W3 key lifecycle durable: crypto assets retain typed evidence-backed conflicts, key/certificate observation time, key rotation time, and one stable fingerprint identity lookup. |
| ECR-0046 | EA-0032 | Accepted | Bind descriptor evidence and certificate-authenticity results to the exact crypto fingerprint and basis evidence before any known lifecycle state can be recorded. |
| ECR-0047 | EA-0032 | Accepted | Keep single-asset missing-evidence refusal, but make batch assessment continue with that asset explicitly unknown and counted instead of denying all tenant posture. |
| ECR-0048 | EA-0023 + EA-0032 | Accepted | Add an atomic persisted analyze-and-score owner path plus tenant-scoped exposure read so crypto findings cite the real replayable EA-0023 record without a second scorer. |
| ECR-0049 | EA-0023 + EA-0033 | Accepted | Add semantic `identity_sensitivity` exposure impact while preserving the existing `data_sensitivity` default; land it with C-030 G5's first identity context. |
| ECR-0050 | EA-0033 + EA-0027 | Accepted | Reuse EA-0027's existing platform `IdentityNotFound` error in ISPM instead of registering a duplicate code owner; EA-0033 contributes only its three net-new errors. |
| ECR-0051 | EA-0033 | Accepted | Make unknown identity classification visibly fail-safe in every representation: `NormalizedIdentity.identity_kind="unknown"` requires `flagged=true`, rather than relying on an EA-0002 label that disappears from normalized-store reads. |
| ECR-0052 | EA-0033 + EA-0011 | Accepted | Make assessment-to-finding routing durable and tenant-correct: assessments pin exact posture-score ids, both stores persist them append-only, and EA-0011's finding path accepts an optional tenant scope while preserving local callers. |
| ECR-0053 | IS-034 / EA-0033 + EA-0011 + EA-0025 + EA-0032 | Accepted | IS-034 is a distributed restatement, not a new machine-identity module. Verify conformance, then close only ownership, typed credential/workload binding, and lifecycle-mapping gaps in their existing owners (C-031). |
| ECR-0054 | IS-035 / EA-0032 | Accepted | IS-035 renames EA-0032; conformance + additive governance score, **no second secrets engine**. |
| ECR-0055 | IS-036 / EA-0018+EA-0008 | Accepted | Archive is a template; capability ships. Conformance only, **no second orchestrator, no un-gated execution**. |
| ECR-0056 | EA-0008 / IS-036 | Resolved | K1 found and closed two shipped gate gaps: non-human approvals were accepted and rollback invoked handlers without a fresh human/capability gate. |
| ECR-0057 | GC-001 (cross-cutting) | Accepted | Central §0 guarantee-conformance suite: discovery-based, test-only, negative-control-backed. |
| ECR-0058 | GC-002 (cross-cutting) | Accepted | Event-namespace closure guard: registered-type + prefix-ownership, discovery-based, test-only. |
| ECR-0059 | IS-037 / EA-0023+0024+0025+0005 | Accepted | Template stub; CAASM ships distributed. Conformance only, **no `Cyber*` event namespace**. |
| ECR-0060 | EA-0038 – EA-0050 (batch) | Accepted (C-035; archive-exhaustion clause **superseded by ECR-0086**) | Thirteen same-generator stubs, **three** dispositions: eleven conformant via shipped owners; **EA-0048 an open capability gap, not scheduled**; **EA-0050 non-capability** (with EA-0051). Archive exhausted as a requirements source. ⚠️ **Superseded:** the archive continues through EA-0063; EA-0052–0063 remained unassessed — see ECR-0086. |
| ECR-0061 | EA-0025 (+ EA-0023, EA-0024) | Accepted (C-036) | ECR-0034's second half: `AssetStore` gains cursor pagination (EA-0002 D8), the engine pages under `InventoryConfig.page_budget`. **Moves the truncation threshold; does not remove `degraded`.** Budget exhausted -> partial + flag; `sweep_unreported` -> exhaust or refuse, never partial. |
| ECR-0062 | EA-0003 findings (+ EA-0013 risk) | Accepted (C-037) | `FindingStore.query` had a pagination-shaped signature that never paginated: `FindingQuery.cursor` accepted and ignored by both backends, `next_cursor` always `None`. Implements a **composite** keyset cursor on `(severity_score, id)` -- an `id`-only cursor is incoherent under `ORDER BY severity_score DESC, id`. Index extended to cover the tie-break. |
| ECR-0063 | EA-0003 findings (+ EA-0018 response, EA-0027 idthreat) | Accepted (C-038) | Finding re-scoring: **option 3**. `severity_score` stays write-once as the cursor's sort key; `current_severity_score` carries the latest emission. Also C-038: impossible durations report unknown not zero, and GC-003 makes rule 11 mechanical. |
| ECR-0064 | EA-0024 + EA-0030 | Accepted | **Real data falsifies three availability assumptions.** `cvss` required with no unknown; severity vocabulary incomplete; SBOM parser requires `purl` on every component. |
| ECR-0065 | EA-0020 + EA-0024 (+ EA-0033, EA-0032, EA-0023) | Accepted | **Replay performs different arithmetic from composition** - scale-then-round vs round-then-scale. 162/200 real records fail replay. The shape recurs in four modules. |
| ECR-0066 | EA-0024 (+ GC-001 AC-3) | Accepted | **HIGH: three priority factors report `known` with no provider supplied** - a confident vote nobody cast, on every real finding. ECR-0040 applied to an instance, not the pattern. AC-3 widens per-scorer -> per-factor. |
| ECR-0067 | EA-0023 + EA-0020 | Accepted | **A replay check that asserts less than its name.** `replay()` was called and its return discarded; comparison absent entirely. |
| ECR-0068 | GC-001 | Accepted | **AC-3's coverage decays as the platform matures.** It asserts *unwired → unknown*; production is increasingly *wired*, and those states are unchecked. |
| ECR-0069 | S-track tooling | Accepted | **Data-handling boundary for real-estate milestones.** Aggregate counts may leave; per-asset detail may not — structurally, not by convention. |
| ECR-0070 | S-track tooling | Accepted | **Transient collector boundary.** A complete filesystem inventory may consume one checksum-pinned temporary executable, but no package install or persistent estate change; cleanup and verified absence are part of success. |
| ECR-0071 | EA-0030 | Accepted | **A real SBOM cannot be ingested.** 24 purl-less package components quarantine 131,685. Route (B): represent them, keyed on `cpe`. |
| ECR-0072 | EA-0030 + EA-0024 | Accepted | **Absence is not a value.** Absent licence read as conflicting; absent coverage read as clean. Third and fourth arrivals of one error. |
| ECR-0073 | EA-0023 (S-003 U3) | Accepted | **Surface from observed binds, not configuration.** The config reads failed; three attribution states; read-only ≠ unprivileged. |
| ECR-0074 | EA-0033 + GC-001 | Accepted | **Why did AC-3 not catch this?** A mission factor returns the most favourable value with no provider; and a decision is recorded as an absence. |
| ECR-0075 | GC-001 (cross-cutting) | Accepted | **Score-path closure.** A guarantee that enumerates factor representations cannot see numeric scoring paths that bypass them. |
| ECR-0076 | EA-0032 + EA-0013 + EA-0023 (+) | Accepted | **The cross-cutting repair.** Absence is the fold's identity element, and in risk arithmetic the identity is always the safe end. |
| ECR-0077 | S-003 / EA-0023 + EA-0032 | Accepted | **Privileged read resolved:** manual capture complete; handed-in implementation closes four dependents without a privileged collector. |
| ECR-0078 | EA-0023 + S-004 | Accepted | **Configuration is its own exposure basis.** A proxy-declared route must not be durably mislabeled as host state, graph, or telemetry. |
| ECR-0079 | S-track density reporter | Accepted | **Typed supplemental status must survive reporting.** Known factor readings were counted as unknown, preserving roadmap work after the owner resolved it. |
| ECR-0080 | S-track tooling | Accepted | **A documented flag defeats the freshness gate.** `--reuse` sets `collected_at` fresh over cached content. |
| ECR-0081 | P-track (new) | Accepted | **A new track, and the rigor that does not transfer.** Design choices cannot be verified against shipped code; acceptance is a person. |
| ECR-0082 | EA-0024 (+ GC) | Accepted | **Absence exiting the fold.** `vuln` normalises by known weights only, so excluded weight is redistributed to the survivors. |
| ECR-0083 | EA-0024 + GC-001 AC-3 | Accepted | **Stable weights are necessary but not sufficient.** ECR-0082's all-weight denominator stops sibling amplification but maps an unknown lower-is-favourable factor to the same contribution as a proved-safe `0.0`; use a separate typed uncertainty surcharge, with `u = 0.25` selected after the full KEV-bearing corpus rerun. |
| ECR-0084 | EA-0013 / `findings` | Accepted (shape 1; owner, 2026-07-30) | **`current_severity_score` is maintained and never read.** Shape 1 selected: P-001 annotates current severity beside the existing first-seen priority headline without changing ordering; dormant until persistence. |
| ECR-0085 | GC-004 (cross-cutting) | Accepted (GC-004) | **Persisted fields must have consumers, and dormancy must be declared.** The guard reports a census, not a clearance. |
| ECR-0086 | EA-0052–0063 batch | Accepted (owner decisions recorded; absence guards shipped) | Archive **not** exhausted — 12 unassessed. 3 conformant, 3 gaps, 6 non-capability. EA-0054 remains an open gap, not scheduled; EA-0052-FR-004 is not authorized. |
| ECR-0087 | EA-0058 + EA-0060 + EA-0061 | Accepted (record-only read complete) | **Third generator template, not standards.** The 703-line shape contains no topic-specific normative requirements; the ECR-0086 conformance-read debt is discharged. |
| ECR-0088 | Local operator surface | Accepted (surface v1) | **The first user-facing path into the real kernel.** A stdlib read API and thin UI bind loopback only; outbound networking remains absent and non-loopback remains owner-gated. |
| ECR-0089 | Local operator surface + reporting | Accepted (surface widening) | **Owner-provided read seams widen the surface without engine coupling.** ISPM, exposure, secrets and supply chain join the Runtime; P-001 uses the same registered publish/read path. |
| ECR-0090 | ECR-0089 read seams | Accepted (tiebreak witnesses; amended by ECR-0091/0093) | **Correct keyset reads lacked witnesses for their trailing tiebreaks.** Decorrelated fixtures and forced Postgres plans make silent skips observable; a static guard pins query table, order, index name and direction. ECR-0093 corrects the named offset pair. |
| ECR-0091 | ECR-0089 read seams | Accepted (leading-key witnesses; amended by ECR-0092/0093) | **The mirror of a guard is not guarded by the guard.** Reverse-inserted leading values and deliberately conflicting tiebreak order make each in-memory leading key load-bearing. ECR-0093 corrects the named offset pair. |
| ECR-0092 | Secrets Postgres read + surface pagination | Accepted (final keyset witness; applicable routes corrected by ECR-0093) | **The exception to a guard needs its own owner.** A forced-plan witness closes secrets' Postgres leading key; FR-003 becomes surface-wide and ECR-0093 names and guards the two snapshot exemptions. |
| ECR-0093 | Surface pagination | Accepted (named snapshot exemptions; one cursor contract) | **A citation can be precisely right and still point at the wrong thing.** The actual offset routes are inventory and vulnerabilities; findings was already keyset-paged. Snapshot exemptions stay visible, and findings gains scope binding plus its covering index. |
| ECR-0094 | Findings keyset read | Accepted (memory + forced-plan Postgres witnesses; review-result wording amended by ECR-0095) | **Walking is what tests the predicate.** Findings gains deliberate leading-key, tiebreak and resume-predicate witnesses on both stores, closing the last silent member of the surface read arc. |
| ECR-0095 | Test witness cursor walks (+ ECR-0094) | Accepted (walk termination guards) | **A cursor defect must fail, not hang.** All 14 test walks are bounded and diagnostic; ECR-0094 review treats every result other than clean RED as a finding. |
| ECR-0096 | Single-column keysets, first batch | Accepted (eight ordering witnesses) | **Insertion order is not an ordering witness.** The first four selected legacy reads now reverse-insert IDs and walk every page size on memory and Postgres; CTE-backed outer clauses are pinned on the executed SQL without overstating behavioral proof. |
| ECR-0097 | ECR-0096 deferred ordering batch | Accepted (nine behavioral witnesses plus DSPM structural pin; residual scheduled as ECR-0098) | **A method must be classified by the API it actually exposes.** Four cursor reads gain two-store witnesses; workflow gains ordered-prefix witnesses without a false cursor claim. The wider 30-read census leaves sixteen named residuals for ECR-0098. |
| ECR-0098 | Residual paged reads, ordering-clause class | Accepted (32 local-PG mutation and necessity results; second review pending) | **The census boundary is thirty `ORDER BY ... LIMIT` reads.** The sixteen residual APIs are all cursorless bounded lists; witnesses were classified before they were written. |
| ECR-0099 | Leading-key class and witness-arc closure | Accepted (fixture symmetry implemented; closing review pending) | **Every component of a sort tuple must decide at least one comparison in the same fixture.** Eleven fixtures expose the leading key without surrendering their ECR-0098 tail witnesses. |
| ECR-0100 | Posture ingestion | Proposed (implemented by the reviewer; independent review outstanding) | **A platform can only reason about what it can be told.** AQELYN accepted only grype matches, so six real posture facts about a live estate had nowhere to go; `posture.json` gives them a path, refused rather than back-filled when the derivation is missing. |
| ECR-0101 | Surface collection seed | Accepted (implemented by the reviewer; independent review outstanding) | **A platform you cannot put data into cannot be looked at.** `--collection` seeds the running kernel with the report path's ingestion and refusals; opt-in, read once, idempotent, and a refused collection stops the surface. |
| ECR-0102 | Self-scan collector | Accepted (implemented by the reviewer; independent review outstanding) | **A check that cannot run reports unmeasured, never a pass.** `aqelyn collect` inspects the host read-only and writes a collection directory, closing collect -> ingest -> look; mobile is named out of scope rather than left to assumption. |
| ECR-0103 | Charter v2 compliance | Accepted (implemented by the reviewer; independent review outstanding) | **Hollow compliance is worse than a named gap.** Plain-language titles and an expert expansion close UX-001 and UX-002; Affected Assets is left empty rather than filled with an id that resolves to nothing, and owed to ECR-0104. |
| ECR-0104 | Progressive disclosure and modes | Accepted (implemented by the reviewer; independent review outstanding) | **A mode narrows what is shown; it never softens what is true.** The Charter's six levels become data a renderer consumes, with witnesses that levels never duplicate and that no audience gets a smaller truth. |
| ECR-0105 | The disclosure model reaches the page | Accepted (implemented by the reviewer; independent review outstanding) | **A requirement that lives only in a module no caller imports is not implemented.** The Charter's six levels become `<details>` a reader can actually open, and `--mode` selects how many start open. A mutation deleting the level *names* ran green first: the words were rendered and nothing witnessed them. |
| ECR-0106 | A posture subject becomes an asset | Accepted (implemented by the reviewer; independent review outstanding) | **Identity belongs to the subject, not to an id we minted.** `upsert` resolves by natural key, so Affected Assets now points at an object the store returns and four observations of this machine are one asset. Found while reading my own deferral: the dangling id ECR-0100 refused to put in the Finding was already in the EvidenceRecord. |
| ECR-0107 | The collector stops assuming Debian | Accepted (implemented by the reviewer; independent review outstanding) | **A check that reports "unreadable" on every machine that needs it is not a check.** dnf/zypper/pacman, disk encryption and automatic updates. Two of my own parsers were wrong and my own witnesses caught them - one would have reported automatic updates disabled on every machine, including ones that had them on. |
| ECR-0108 | Plain words beside the finding | Accepted (implemented by the reviewer; independent review outstanding) | **The reason I deferred it twice became the design.** A rewritten sentence has no witness for its drift, so the plain language is additive: the finding's own words are byte-identical in all four modes and the jargon is annotated beneath them. Also caught a second mutation-that-did-not-mutate - an empty line number read as GREEN. |
| ECR-0109 | The firewall reader told the truth in neither direction | Accepted (implemented by the reviewer; independent review outstanding) | **A fixture proves the code does what the fixture says; only a real machine says what the inputs look like.** Pointed at the live VPS, the collector reported an ACTIVE firewall as inactive - `ufw status` needs root. The same three lines also read a STOPPED firewalld as running, because "running" is a substring of "not running". |
| ECR-0110 | The SSH reader read the wrong file, in the wrong order | Accepted (implemented by the reviewer; independent review outstanding) | **A green test that encodes a misunderstanding is the misunderstanding, notarised.** The reader ignored `Include` and kept the LAST directive; sshd takes the FIRST, proven against a real sshd. On the live VPS the two drop-ins disagree, and the effective answer is that password auth is ENABLED on a port open to the internet - reported until now as unmeasured. |

---

## ECR-0001 — `paths()` enumeration work budget

**Raised by:** Claude Code (post-EA-0005 review).
**Severity:** non-blocking hardening.

**Problem.** EA-0005 traversals are bounded, but the bound was uneven. The
Postgres CTE traversals are limited by `LIMIT` (max_nodes) and depth. The
Python-side `paths()` enumeration was bounded only by `max_depth` and
`max_paths` — on a dense graph it could expand a very large number of partial
paths before collecting `max_paths` complete ones, so worst-case effort was not
explicitly capped. This violates the spirit of EA-0005 D2 ("bounded, never
hang").

**Resolution.** Add `max_work: int = 50_000` to `paths()` (§6). It caps the
number of nodes/partial-paths expanded during enumeration; on reaching it,
`paths()` returns the paths found so far rather than continuing. Hard cap
`max_work ≤ 1_000_000`. Captured as **FR-13** and **AC-15**
(`test_kg_paths_work_budget`).

**Impact.** Additive, backward-compatible (new keyword arg with a default).
Implemented via C-002 follow-up ticket **G3a**. No change to other methods or to
the contract of already-passing tests.

---

## ECR-0002 — Policy condition lookup dunder hardening

**Raised by:** Claude Code (post-P1 review).
**Severity:** defense-in-depth hardening.

**Problem.** EA-0009 P1 correctly avoids arbitrary code execution: the condition
interpreter is structured data and contains no `eval`/`exec`/dynamic import
path. However, its dotted attribute lookup used `getattr(current, part)` after a
non-dict hop. With untrusted policy attr-path segments, a path such as
`resource.type.__class__` could traverse Python object internals. This is not a
code-execution issue, but it is an avoidable information-leak surface.

**Resolution.** Attribute lookup is restricted to data mapping traversal only.
Any empty path segment or segment starting with `__` is treated as missing, and
non-mapping values stop traversal rather than calling `getattr`.

**Impact.** Backward-compatible for supported policy data because Decision
requests and compliance resources are dictionaries. Adds an acceptance test that
a dunder attr path yields no match.

---

## ECR-0003 — Tenant-qualify the correlated `Risk.id`

**Raised by:** Claude Code (post-R3 review, PR #52).
**Severity:** blocking correctness — tenant-isolation break.

**Problem.** R2 derived the correlated risk id as `risk:{correlation_key}`, and
`aq_risk.id` is the primary key. A `correlation_key` is caller-controllable and
can be shared across tenants — via an explicit `finding.correlation_id` or an
external `CorrelationSignal.correlation_key` taxonomy (e.g.
`"risk:internet-exposure"`). Two tenants sharing such a key minted the **same
PK**, so the second tenant's `upsert` matched the first tenant's row by id and
raised `CrossTenantReference` — one tenant's risk permanently blocked another
from registering its own. The `(tenant_id, correlation_key)` unique index was
correct; only the PK id lacked a tenant segment. Reproduced empirically during
review (identical id, `CrossTenantReference`). Finding-derived keys embed object
UUIDs and were already collision-free; the defect surfaced only for shared
explicit keys.

**Resolution.** Derive the id as `risk:{tenant_id or 'global'}:{key}`
(`_risk_id`). The tenant id is a UUID (or the literal `global`), so the
`:`-delimited prefix is unambiguous and two tenants sharing a `correlation_key`
now produce distinct ids. Dedupe/versioning semantics are unchanged (still keyed
on `(tenant_id, correlation_key)`).

**Impact.** Changes the format of correlated risk ids (no persisted risks exist
yet — R3 is the first persistence). Adds `test_risk_cross_tenant_correlation_key`
(both backends); updates the one R2 assertion that pinned the old id string.

---

## ECR-0004 — `ObjectQuery.exclude_object_types`

**Raised by:** Claude Code (post-T3 review, PR #58).
**Severity:** blocking correctness (enables the EA-0014 T3 fix).

**Problem.** EA-0014 threat correlation enumerates estate **assets** via
`ObjectStore.query`, then filters the engine's own threat objects
(`threat_indicator`/`actor`/`campaign`) out of the result. But `ObjectQuery`
supports only a single positive `object_type` (or none), and the store applies
`limit` **before** any post-filtering, and returns no pagination cursor. So the
engine's own indicator objects compete with assets for the query budget: in an
estate with many indicators, a `limit`-sized query comes back full of indicators,
which are then stripped, leaving few or **zero** assets — correlation silently
under-matches or returns empty. Reproduced during review (`limit=2`, two matching
assets → `matches=0`, the query returned two `threat_indicator`s).

**Resolution.** Add `exclude_object_types: tuple[str, ...] = ()` to `ObjectQuery`,
honored in the WHERE/predicate of both the in-memory and Postgres stores (so the
`limit` applies to the already-filtered set). Threat `correlate` passes
`THREAT_OBJECT_TYPES`, so the asset budget is spent on assets only. Additive and
backward-compatible (default empty tuple; existing queries unaffected).

**Impact.** New optional `ObjectQuery` field + one predicate in each store.
Adds an object-store contract assertion for the exclusion, an EA-0014 scale test
(indicators far exceeding `limit` no longer starve asset correlation), and folds
in a `truncated`-on-match-limit fix (partial match lists are now reported as
truncated, §11/FR-6).

---

## ECR-0005 — Evidence custody reconstruction API

**Raised by:** Claude Code (EA-0016 spec review / C-013 F1 kickoff).
**Severity:** blocking contract gap for Digital Forensics.

**Problem.** EA-0016 requires chain-of-custody to be reconstructable for
forensic artifacts on both in-memory and Postgres backends. The C-001 evidence
implementation already tracked custody internally, but the public contract was
uneven: the in-memory store exposed a private `custody_of()` helper, while the
Postgres store exposed only `custody_count()`. That allowed count checks but not
the ordered custody reconstruction needed by forensic timelines, packages, and
audits. Also, `EvidenceStore.add()` assigned the hash-chain fields but did not
write an explicit intake custody row, despite EA-0004's contract text saying
`add()` logs custody.

**Resolution.** Add `async custody_of(evidence_id) -> list[dict[str, object]]`
to the EA-0004 `EvidenceStore` protocol. Both in-memory and Postgres
implementations return ordered custody rows. `add()` now records an `intake`
custody entry using the evidence collector, and Postgres DDL permits
`intake` alongside `read`, `export`, and `package`.

**Impact.** Additive contract surface plus a stricter fulfillment of the
existing custody requirement. Existing callers are unaffected; tests now assert
ordered `intake` then `read` custody on both backends. EA-0016 F1 can depend on
the public `EvidenceStore` protocol instead of backend-specific helpers.

---

## ECR-0006 - IS-018 realized as orchestration above EA-0008 (not a second executor)

**Raised by:** planning (EA-0018 spec pass).
**Severity:** architectural - would otherwise break the platform's §0 safety spine.

**Problem.** The archive's IS-018 component list (Playbook Engine, Approval
Engine, Response/Automation Engine, Containment/Remediation/Recovery Engines)
substantially duplicates **EA-0008 Workflow**, which is already implemented and
is the platform's single acting authority:

- IS-018 "Playbook Engine" vs EA-0008 `Playbook` (declarative, versioned, steps);
- IS-018 "Approval Engine" vs EA-0008 `Approval` gates (S4);
- IS-018 "Response/Automation Engine" vs EA-0008 gated run lifecycle + the
  `finding.automation.eligibility` ceiling (S3);
- IS-018 "Containment/Remediation/Recovery Engines" vs EA-0008 `ActionHandler`s,
  which EA-0008 §13 explicitly assigns to connectors.

Implementing IS-018 literally would create a **second acting path** with its own
playbooks and its own approvals, able to produce effects outside the gates every
prior module upholds. That would undo the §0 discipline proven across thirteen
modules.

**Resolution.** IS-018 is realized as the **orchestration layer above EA-0008**.
EA-0018 §0 carries a component-by-component mapping table so no archive scope is
dropped: playbooks/approvals/execution are **reused from EA-0008**; the genuinely
new contributions are multi-phase **response campaigns** composed of gated runs,
**automation triggers** bounded by eligibility + Policy (tighten-only; destructive
never auto-started), **approval routing/escalation** (routing is not granting),
**recovery verification**, and **response metrics** (MTTD/MTTR). The orchestrator
has **no privileged path** - it calls the same public `execute()` any caller does,
and EA-0008 re-validates every gate at run time.

**Impact.** No change to EA-0008. EA-0018 gains §0 (scope reconciliation) and §1
(safety boundary S1-S5), with `test_resp_no_privileged_path` (handler spy) and
`test_resp_no_auto_destructive` enforcing the invariant. The archive master is
unchanged; this spec governs implementation (per `modules/README.md`).

---

## ECR-0007 - Verification standard: behavioural/structural proof over textual checks

**Raised by:** the C-016 (EA-0019) L4 review, which found implementation code
**obfuscated to slip past an over-broad grep**. The reviewer fixed the test
honestly rather than accepting the evasion.

**Problem.** Several specs (EA-0014 NFR-1, EA-0016 NFR-2, EA-0017 NFR-3,
EA-0018 NFR-1, EA-0019 NFR-2) phrase an invariant as "enforced by test **and
grep**". A textual check is a weak guarantee: it can be defeated by obfuscation
without changing behaviour, and - worse - it can create a false sense of
assurance in review. An invariant that only a grep protects is not protected.

**Resolution (binding going forward).** Safety invariants SHALL be enforced
**structurally** (make the violation unrepresentable - type, constructor, or
store gate) and/or **behaviourally** (assert the effect, e.g. a spy proving zero
direct handler invocations; `replay(derivation) == result`). Grep MAY remain as a
cheap secondary signal but SHALL NOT be the primary or sole evidence for any
invariant.

**Applied first in EA-0020**, whose central invariant is deliberately structural:
a recommendation without a replayable derivation is **unrepresentable**, and the
review protocol explicitly instructs *"do not substitute a grep; the invariant is
behavioural"*.

**Retroactive impact.** No shipped behaviour is wrong - the existing modules
back their invariants with real behavioural tests (mutation spies, refusal tests,
fail-closed tests) in addition to the grep wording. This ECR corrects the
*standard and the wording*: reviewers SHALL treat the behavioural test as the
proof, and no future spec SHALL rest an invariant on a textual check alone.

---

## ECR-0008 - EA-0017 `project()` superseded by EA-0021

**Raised by:** planning (EA-0021 spec pass).
**Severity:** scope collision (one capability, two owners).

**Problem.** EA-0017 §S4 scoped "predictive analytics" narrowly and shipped
`project(subject_ref, horizon_days) -> Projection` (EA-0017 line 156) as an
advisory feature inside the detection engine. EA-0021 is a full forecasting
engine (methods, intervals, trends, scenarios, outcome scoring). Left as-is the
platform would have **two projection paths with different guarantees** - exactly
the duplication this project has rejected everywhere else (one capability, one
owner).

**Resolution.** **EA-0021 owns forecasting platform-wide.** EA-0017's `project()`
is **deprecated** and SHALL delegate to `ForecastingEngine.forecast(...)`; it
SHALL NOT keep an independent projection implementation. EA-0017's **S4 stance**
(predictions are advisory, never findings, never evidence) is **retained and
generalised** by EA-0021 §1 S3, which strengthens it further with mandatory
uncertainty intervals (S4), outcome scoring (S5), and the no-automation rule
(S7).

**Impact.** Non-breaking at the call site (same advisory semantics, richer
result). EA-0017's `Projection` type is superseded by EA-0021's `Forecast`.
Sequencing: EA-0021 (C-018) lands the engine, then the EA-0017 delegation is a
small follow-up ticket; until then EA-0017's `project()` remains as shipped and
is not extended.

**Also recorded here:** IS-021 requested a **Confidence Engine** (the third such
request, after IS-020) and an **Explainability Engine** (the second). Both are
mapped to existing owners - **EA-0006 Trust** and **EA-0020 `Derivation`/
`replay`** respectively - per EA-0021 §0. The platform keeps **one confidence
authority and one explainability mechanism**.

---

## ECR-0009 - EA-0022 overrides master §28.2/§28.3 (a missing number must look missing)

**Raised by:** planning (EA-0022 spec pass).
**Severity:** architectural - the master's stated failure handling would license
the exact un-evidenced verdict this module exists not to produce.

**Problem.** The EA-0022 archive master, in its failure-handling section, permits
two behaviours that are safe for an operational dashboard but **corrosive in an
executive report**:

- **§28.2 Dashboard Failure - "Fallback metrics displayed".** Substituting a
  fallback/last-known value for a figure that could not be read.
- **§28.3 KPI Calculation Failure - "Previous values retained".** Carrying a prior
  period's value forward when the current calculation fails.

In a *live dashboard* a last-known value is defensible. In an **issued executive
report** it is a lie: a board reads a retained/fallback number as the current,
computed figure, with full provenance implied. A stale value presented as current
is worse than a gap - it severs the evidence chain precisely where a non-expert
cannot see the seam. This directly contradicts EA-0022 S1 (no number without
provenance) and S5 (material exceptions cannot be omitted).

**Resolution.** For **issued reports and KPI records** (not live dashboards), a
figure that cannot be read/computed is **omitted and recorded in an `excludes`
list**, and SHALL NOT be zeroed, defaulted, or backfilled with a prior value. A
missing number **looks missing**. §28.2's "fallback metrics" is scoped to the
**live dashboard** surface only (which S3 already distinguishes from a frozen
report); §28.3's "previous values retained" is **not** applied to issued reports.
Captured as EA-0022 **FR-9**, **NFR-2**, **§12**, and **AC-9**
(`test_ex_missing_kpi_excluded`).

**Impact.** Governs implementation only; the archive master is unchanged (per
`modules/README.md`, the spec governs). No prior module behaviour changes. This
is the executive-layer application of the same discipline EA-0021 used for
`unscoreable` outcomes (record + exclude, never flatter the number).

---

## ECR-0010 - EA-0022 composite `Figure.as_of` uses the stalest input (min)

**Raised by:** owner (post-EA-0022 as_of review), pushing back on the reviewer's
"arguable, not wrong" call.
**Severity:** honesty correctness (small), on shipped EA-0022 code.

**Problem.** EA-0022 X2 set a composed KPI's `Figure.as_of` to
`max(input.as_of)` - the **newest** contributing timestamp. A composite is only as
fresh as its **stalest** input; reporting the newest timestamp overstates
freshness in exactly the way EA-0022 §1 exists to prevent (a single number
implying more currency than the data supports). The reviewer had called `max`
"arguable, not wrong"; the owner's position is that it is wrong.

**Resolution.** A composed `Figure.as_of` SHALL be the **minimum** (stalest) of
its inputs' `as_of`. "When was this calculated" is a distinct fact already carried
by `computed_at`, so both stay separable. (Acceptable alternative, if ever
preferred: surface **both** bounds; what SHALL NOT stand is a single timestamp
implying more freshness than the data supports.) `min` costs nothing.

**Impact.** One-line change in `executive/kpi.py` (`max(...)` -> `min(...)`) plus a
test asserting a composite of differently-dated inputs takes the **oldest**
`as_of`. Existing X2 tests use a single timestamp per case, so they are unaffected.
No other module changes.

---

## ECR-0011 - EA-0023 derives exposure from known data; no scanning

**Raised by:** planning (EA-0023 spec pass).
**Severity:** architectural - the master specifies an active-scan surface that
would make this engine touch systems it does not own.

**Problem.** The EA-0023 archive master specifies **active scanning as a native
capability**: §20.3 lists `POST /attack-surface/scan`, §12.1/§24 describe
"continuous discovery", and §28.2/§28.3 permit a "fallback assessment" and a
"previous score retained" on failure. A scan is **not read-only from the target's
point of view**: it touches a machine the platform does not own, can disrupt
fragile services, trips other parties' detection, and pointed at the wrong netblock
may be unlawful. A native `scan()` inside a detection engine is exactly the
uncontrolled acting path the platform's §0 discipline rejects. The fallback/retained
clauses repeat the EA-0022 §28.2/§28.3 hazard (ECR-0009): a fabricated or stale
exposure verdict presented as current.

**Resolution.** EA-0023 has **no `scan()`/`probe()`/`connect()` method**. The
attack surface is **derived from data the platform already holds** (EA-0012
inventory, EA-0019 telemetry, EA-0011 access, EA-0005 KG). Active scanning, when it
arrives, is **not** a method here - it is an **EA-0008 `ActionSpec`**: capability
**`scan.active`**, at minimum **reversible**, **Policy-authorized** (scope is the
whole safety question), delivered by a **connector**, requested as a **proposed
gated run**; this engine consumes the results as **stored data, unchanged**.
Unmatched reachability is recorded **`unknown` and flagged, never defaulted to
internal** (S2). Master §28.2/§28.3 are overridden as in ECR-0009: a failed
analysis is `unknown`+flagged, a failed re-score is stale/unavailable - never faked.

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0023 §0.1, **S1/S2/S9**, **FR-1/2/11/12**, **NFR-1**, and
**AC-1/2/3/13/14**. The no-probing invariant is proven **structurally** (no scan
method exists) and **behaviourally** (a network spy asserts zero outbound attempts),
per ECR-0007.

---

## ECR-0012 - EA-0024 carries CVSS/EPSS (never recomputes) and refuses coverage-blind assessments

**Raised by:** planning (EA-0024 spec pass).
**Severity:** architectural - the master would license both silent divergence from
the severity authority and "not scanned" masquerading as "clean".

**Problem.** The EA-0024 archive master (a) implies the engine **recomputes**
severity - §12.2 lists "Severity normalization" and §28.3 "Risk recalculated" - and
(b) repeats the fabrication/stale hazard - §28.2 "**Fallback assessment generated**"
and §28.3 "**Previous assessment retained**". It is also **silent on coverage**: a
vulnerability assessment that does not account for what was *not* scanned reports the
unscanned estate as implicitly clean. Two failure modes follow: a severity that
silently diverges from CVSS/EPSS (the published authority), and an assessment whose
green surface hides an unscanned or stale fleet.

**Resolution.** (1) **CVSS/EPSS are carried verbatim with their source and never
recomputed** (S2) - recomputation invites silent divergence from the authority.
(2) Every `VulnerabilityAssessment` carries a **mandatory `CoverageReport`**
(scanned/unscanned/stale); **if coverage cannot be computed, the assessment is
refused** (`CoverageUnavailable`), never issued clean (S4) - *"not scanned"* is
never *"clean"*, the same discipline as EA-0023's `unknown` reachability (ECR-0011)
and EA-0022's "a missing number must look missing" (ECR-0009). (3) Master §28.2/§28.3
are overridden: a failed correlation/prioritization is recorded degraded/unavailable,
never a fabricated fallback or a silently retained prior assessment (S7).

**Also recorded here:** every `VulnPriority` is **replayable composition** - an
EA-0020 `Derivation` naming each factor, its owner source, and its weight (S1); and a
vulnerability is treated as a **scanner's claim** carrying EA-0006 Trust confidence
(S3), never a bare fact. These are spec hardenings the master did not ask for.

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0024 **S1-S7**, **FR-2/4/5/6/7/11**, **NFR-1/2/3**, and
**AC-2/4/5/6/7/8/9/14**. Proven **structurally** (priority unrepresentable without a
replaying derivation; assessment refused without coverage) and **behaviourally** (a
spy proves no severity recomputation), per ECR-0007.

---

## ECR-0013 - An unwired dependency defaults to inert/refusing, never optimistic

**Raised by:** the C-021 V5 review, which found EA-0024's wired coverage provider
reporting `unscanned=[]` (fully-covered) when it could not actually see the asset
universe.
**Severity:** correctness of the safety posture - an unwired control that reports
"all good" is worse than one that reports nothing.

**Problem.** EA-0024 V5 wired `StoreBackedVulnerabilityCoverageProvider`, whose
`coverage()` returns `scanned = {ingested asset refs}` and **`unscanned = []`,
`stale = []` always** - it knows only the ingested vulnerability store, not the
full asset universe. So in the wired runtime every `assess()` looks fully-covered,
which is exactly the *"not scanned = clean"* outcome EA-0024 S4 exists to prevent.
The V4 *structure* is correct (assess refuses if coverage cannot be computed); the
V5 *wiring* got the default backwards - optimistic instead of inert.

**Resolution (binding, cross-cutting).** When a dependency is not yet wired to an
authoritative source, its default implementation SHALL be **inert or refusing,
never optimistic**. A coverage provider that cannot compute true coverage SHALL
**refuse** (`CoverageUnavailable`) rather than report an empty `unscanned`. EA-0019
established the pattern (inert reference checkers); EA-0024's wiring is corrected to
match. The authoritative fix is EA-0025 `inventory()` as the coverage denominator,
wired in C-022 **N6**; until then the default refuses.

**Impact.** Small change to `aqelyn.vuln.service` (the default coverage provider
refuses instead of reporting empty `unscanned`) plus the health/wiring semantics
that follow, and the generalization above as a standing rule for every future
"not-yet-wired dependency". No shipped invariant is weakened - the system becomes
**more** honest (refuses rather than falsely reassures).

---

## ECR-0014 - EA-0025 inventory is the authoritative, freshness-declaring denominator

**Raised by:** planning (EA-0025 spec pass).
**Severity:** architectural - a silently shrinking inventory makes twenty engines
report all-clear about a smaller world.

**Problem.** The EA-0025 archive master (a) permits **§28.2 "previous inventory
retained"** on failure - a silent stale/shrink - and (b) is **silent on how an
asset leaves the inventory**, so a naive "continuous discovery" would let a feed
that goes quiet retire assets. Both are the same failure: the inventory shrinks or
staleds without anyone deciding it should, and every downstream engine
(exposure coverage, vulnerability coverage, risk scope) then reports **all-clear of
a smaller or older world** - cascading blindness that looks like good news.

**Resolution.** (1) **Absence of evidence is not evidence of absence** - an asset
absent from a feed becomes **`unreported`**, never `decommissioned`; decommissioning
requires **positive evidence or an attributed EA-0008 decision**, and
`sweep_unreported` **refuses** when source health is `unknown`. (2) **`inventory()`
declares its own freshness** (`as_of` + per-source), and a **degraded store makes
`inventory()` fail rather than shrink** (`InventoryUnavailable`) - overriding master
§28.2. (3) **Reconciliation records conflicts** rather than smoothing them:
precedence resolves via **EA-0006 source reliability** (not last-writer, not source
order), every conflict stays on the record with each candidate's value + reliability,
and ties land **unresolved and surfaced**.

**Also recorded here:** `inventory()` is the authoritative "which assets exist" that
EA-0023 (asset set) and EA-0024 (coverage denominator) were missing - **not** network
access. C-022 **N6** wires both seams, and closes ECR-0013's coverage gap with a real
inventory-backed denominator. This is **not** the connector turn (discovery is
handed-in; no ADR-0001 refresh).

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0025 **S2/S3/S4**, **FR-2/4/5/6/7**, **NFR-1/2**, and
**AC-2/3/4/5/6/7/8/9/17**. Proven behaviourally (degraded store fails; sweep refuses
on unknown health; conflicts + ties on the record), per ECR-0007.

---

## ECR-0015 - IS-026 is IS-012 restated; do not build EA-0026

**Raised by:** owner (IS-026 spec pass), verified by Claude Code against shipped code
(K1).
**Severity:** architectural - building it would fork the platform's configuration
authority.

**Problem.** IS-026 (Configuration Compliance & Drift Intelligence) is **not a
component overlap with EA-0012 (Asset & Configuration Governance) - it is the same
engine restated.** The decisive tell: both archive masters declare the **identical**
event `configuration.drift.detected` (EA-0012 master lines 787/1557/1959; IS-026
master line 294). Types map one-for-one (`BaselineDefinition`->`Baseline`,
`DriftAssessment`->`DriftSnapshot`, `ConfigurationRemediation`->finding + proposed
run), components map, and EA-0012 **shipped all of it in C-009** (green on `main`):
`Baseline`/`BaselineStore`, `DriftSnapshot`/`assess_asset`, `classify`,
`drift_to_findings`, and the `aqelyn.config.drift_detected` event. Every mapping is
verified against shipped code in `IS-026_Conformance_Analysis.md`.

Building `EA-0026` as written would give the platform two baseline stores (two
answers to "desired config state"), two drift detectors (divergent results on the
same asset), two `configuration.drift.detected` emitters (duplicate findings, doubled
remediation proposals, inflated drift counts in EA-0022 reporting), and a split brain
in every consumer. That is the failure this project has rejected eight times - here in
its most extreme form. This is the **second** archive redundancy after IS-018 vs
EA-0008 (**ECR-0006**), indicating the archive was authored per-topic without
cross-topic dedup: a documentation artefact, not a requirement.

**Resolution.** **No `EA-0026` engine is built.** IS-026's intent is realized as a
small **two-ticket EA-0012 enhancement (C-023)** - not a module:
1. **K1** - accept the conformance mapping only after each ✅ is verified against
   **shipped code**; any ✅ that fails becomes a C-023 ticket (never a reason to build
   a second module).
2. **K2** - delegate configuration **drift trend** to **EA-0021** (`analyze_trend`,
   the EA-0023/EA-0024 precedent), and *optionally* emit an **EA-0020 advisory
   recommendation alongside - never replacing** - the existing proposed gated run.

The C-023 bundle states outright: **if `src/aqelyn/configcompliance/` appears, the
milestone has gone wrong.** IS-026's "continuous drift detection" (scheduling) is
**deliberately deferred** to a future scheduler EA (EA-0008 §13), where it will serve
every assessment engine (EA-0010/0012/0023/0024/0025) rather than being re-implemented
inside the config engine.

**Going-forward discipline (adopted).** Before specifying any remaining archive
module, **grep its declared event types and data types against shipped modules
first.** Identical event names are a reliable restatement signal; that single check
caught IS-026 immediately.

**Impact.** No new module, no repository change beyond docs. IS-026's intent is met at
its turn, sequentially, with evidence - without forking the platform's config
authority. Master's Next after IS-026 is IS-027 (Identity Threat Detection &
Behavioral Analytics), which the same event/type check should precede.

---

## ECR-0016 - EA-0027 watches accounts, not people: dignity gate, no person-scoring

**Raised by:** planning (EA-0027 spec pass).
**Severity:** architectural + ethical - this is the only engine that analyses named
human beings, and it sits directly against EA-0021 **S8** ("predictive suspicion of
named people is out of scope, permanently").

**Problem.** The EA-0027 archive master demands exactly what this boundary exists to
prevent: an **"Identity risk score"** (§429) - a UEBA per-user number attached to a
colleague, rising and decaying invisibly; **"insider threat identification"**
(§107/261) - *prediction* of who someone will become, for which no evidence exists and
whose cost is borne by a person; and it re-declares `behavior.profile.updated` (§300),
an event **EA-0017 already owns**. Individual behavioural anomalies are low-prevalence,
so even a strong detector produces mostly false positives - and here **each false
positive is a colleague wrongly suspected.**

**Resolution.** The engine surfaces **observed, evidence-backed, account-scoped
events** a human then judges - never a standing verdict about a person.
1. **The account is the subject; the person is not the finding** - *"this credential
   shows impossible travel,"* never *"this user is suspicious."*
2. **A dignity gate, non-negotiable.** An identity detection requires **both** ≥ 2
   independent corroborating signals **and** a confidence floor **strictly above the
   platform default** - the one detector deliberately made *less* sensitive. A config
   lowering corroboration below 2 or dropping the floor to the default is **rejected at
   construction** (EA-0027 §11). The guarantees are structural, not knobs.
3. **No per-person risk score - absent, not disabled.** No `risk_score`/`user_score`
   type or method exists; the review's first check is its absence.
4. **Right of reply by construction** - every detection is evidence-backed, replayable
   against pinned versions, and human-reviewed before consequence, so the accused can be
   shown exactly what was observed.
5. **Reuse, not rebuild** - behavioural profiles are **EA-0017**'s (keyed by an identity
   `subject_ref`); entitlements are **cited from EA-0011**, never merged; `behavior.
   profile.updated` is **consumed** from EA-0017, never re-emitted. No individual's
   future behaviour is forecast (EA-0021 S7/S8).

**Impact.** Governs implementation only; the archive master is unchanged (the spec
governs). Captured as EA-0027 **S1-S8**, **FR-1..5/11/12**, **NFR-1/2/3**, and the §11
dignity gate; the dignity gate (C-024 **I2**) is built **before** any detection can be
raised, and the review's first check is that no person-scoring type/method exists.
Proven structurally (unrepresentable sub-threshold detection, unconstructable
knob-lowering config, absent score surface) per ECR-0007.

---

## ECR-0017 — corroboration independence is keyed on the signal, not on its label

**Raised by:** Claude Code (C-024 I2 review, PR #141).
**Severity:** blocking for C-024 I3 — it sets the numeric value of the dignity gate's
corroboration floor, and under EA-0027 S3 a weakened floor is a wrongly-suspected
colleague.

**Problem.** EA-0027 S3/FR-1 require "corroboration from **≥ 2 independent** signals"
but never define what makes two `SignalRef`s independent. I2 (`dignity.py`) resolved
it as the tuple `(kind, ref)`. Constructed behaviourally against the shipped gate:

```
dignity_gate([SignalRef(kind="auth",    ref="evt:42"),
              SignalRef(kind="session", ref="evt:42")], 0.9, config)  -> True
```

One underlying occurrence, reported under two `kind` labels, satisfies a floor whose
entire purpose is to require **two** things to have happened. The floor is then
nominally 2 and effectively 1 — and it degrades exactly where the platform is least
able to notice, because whichever upstream collector labels one event twice does so
for *every* event of that shape. Nothing in the module is wrong by its own reading;
the spec is simply silent, and silence resolved toward the *more* sensitive detector
in the one module the spec says must be deliberately **less** sensitive (S3).

**Resolution.** Independence is a property of the **signal**, not of its label.

1. **The independence key is `ref`** — one occurrence is one corroboration, regardless
   of how many `kind`s report it. Two `SignalRef`s sharing a `ref` collapse to one.
2. **`evidence_id` collapses too, when present** — two distinct `ref`s backed by the
   same `evidence_id` are one signal seen twice, not two. A **null** `evidence_id` is
   not a match: two signals that both lack evidence are **not** merged on that basis,
   because "unknown" is not "same". `ref` remains the primary key, so such signals
   still count separately when their `ref`s differ. Merging is only ever a *reduction*
   applied on positive evidence of sameness — never inferred from absent data.
   Collapsing is transitive: signals joined through any chain of shared `ref` or
   shared `evidence_id` count as one.
3. **Counting is the gate's job, not the caller's.** `dignity_gate` de-duplicates
   internally; no caller may pre-count and pass a number. A caller able to assert its
   own corroboration count is a knob (S3/§11).
4. **Ties toward refusal.** Where independence is undecidable, the signals count as
   one. Dropping a true detection costs a missed alert; inflating corroboration costs
   a person.

**Impact.** Amends EA-0027 §4 (**Corroboration**), §5 (`SignalRef`), FR-1/FR-2 and
adds **AC-19** (`test_idt_corroboration_independence_key`). No master override — the
archive is silent here; this tightens an under-specified floor rather than overriding
a demand. Implemented in C-024 **I3**, where `detect` first calls the gate; I2's
`(kind, ref)` key is superseded. Proven behaviourally per ECR-0007: construct two
`SignalRef`s over one `ref`/`evidence_id` and assert the gate refuses.

---

## ECR-0018 — make identity-detection replay inputs explicit

**Raised by:** Codex (C-024 I3 implementation).
**Severity:** blocking ambiguity — the Accepted interface cannot supply data its
required output must pin.

**Problem.** EA-0027's Accepted `detect(subject_ref, signals, tenant_id)` signature
requires the resulting derivation to pin both profile and rule versions, but carries
neither version, the detection type, nor the observation time. I3 cannot infer those
values without inventing state or silently choosing "latest", which would break the
right-of-reply guarantee when profiles or rules later change. Allowing caller-authored
statement/basis fields would also permit verdict-like prose to bypass S2.

**Resolution.** Replace the under-specified arguments with a structured
`IdentityObservation`: account-scoped `subject_ref`, `detection_type`, signals,
`profile_ref` + `profile_version`, `rule_ref` + `rule_version`, and `detected_at`.
`detect(observation, tenant_id)` obtains confidence from EA-0006, runs the dignity
gate first, and only then constructs the statement, basis, and replayable derivation.
The derivation is accepted only when replay, result match, and source/pin match all
hold; the store repeats those checks at the persistence boundary.

**Impact.** I3 interface and reference computation only. No prior shipped caller
exists, and no later I4/I5 API is changed. This makes the spec's existing S2/S3/S7,
FR-2/6/10, and AC-6/7/11 implementable without an implicit "latest" choice.

---

## ECR-0019 — explicit IAG identity input and append-only right of reply

**Raised by:** Codex (C-024 I4 implementation).
**Severity:** blocking ambiguity — I4 requires two states its Accepted types and store
contract cannot represent.

**Problem.** (1) I4 must call EA-0011 `access_paths`/`analyze_risk`, whose subject is a
typed `obj_` identity id, but `IdentityObservation` carries only an account-scoped
display reference such as `acct:alice`. Inferring an object id would fabricate a
cross-engine reference. (2) `review` must durably record a human outcome and return a
reviewed detection, while I3 correctly made `aq_identity_detection` append-only and
the Accepted store protocol has no review record. Updating the detection row would
break D6; returning an unpersisted status would make right of reply cosmetic.

**Resolution.** Add a required, typed `identity_id` to the handed-in
`IdentityObservation`; it is used only to delegate to EA-0011 and is cited in the
detection basis, while `subject_ref` remains the account/credential/session and the
person is never the finding. Add one append-only `IdentityReview` per detection:
`{detection_id, tenant_id, outcome, reviewed_by, reviewed_at, evidence_id}`. The
review evidence is written through EA-0004 first, then the review row is appended;
`get`/`query` materialize `status="reviewed"` from that row without updating the
original detection. Re-review is refused as an optimistic conflict. I4 findings use
a fixed `medium` / `50.0` triage severity (not a new scorer), cite existing signal
evidence, and remain non-actionable (`eligibility="none"`).

**Impact.** Additive I4 contract and DDL only. It preserves I3's append-only gate,
makes EA-0011 delegation possible without inference, and makes S7/FR-11/AC-12/14
durable and testable. No Workflow execution or new scoring authority is introduced.

---

## ECR-0020 — CSPM is a verdict-free normalizer and router, not a parallel cloud stack

**Raised by:** planning (IS-028 spec pass using the ECR-0015 event/type check).
**Status:** Accepted.
**Severity:** architectural — a cloud-specific copy of existing owners would split
inventory, configuration, compliance, identity, exposure, and risk truth six ways.

**Finding.** IS-028 is not a wholesale restatement: its cloud normalization and
`cloud.misconfiguration.detected` integration are net-new. But each proposed
"Cloud <capability> Engine" already has a platform owner. A cloud resource is an
EA-0025 asset; cloud configuration is EA-0012 baseline data; CIS cloud frameworks
belong to EA-0010; cloud IAM belongs to EA-0011; reachability belongs to EA-0023;
and cloud findings aggregate through EA-0013. "Runs in AWS/Azure/GCP" is a scope
and provenance property, not a new capability.

**Resolution.** EA-0028 is a thin **normalization + routing layer**:
`CloudResourceDescriptor` in, verdict-free `NormalizedCloudObject` out, then one
explicit route outcome for every existing owner. It owns provider type mapping,
field provenance, conflict recording through EA-0006 reliability, and preservation
of handed-in raw evidence. It owns no assessment, score, compliance verdict,
finding, action, inventory, or risk computation. `NormalizedCloudObject` and all
other CSPM models use `extra="forbid"`; severity, score/risk-score,
compliance-status, finding, and action fields are unrepresentable in CSPM-owned
state, and those reserved keys are rejected recursively from nested normalized
facts/provenance/conflicts. Provider verdict material remains only in raw EA-0004
evidence. Routing reports `complete`, `partial`, or `failed` and names each
accepted or failed owner, so a five-of-six handoff cannot be smoothed into success.

**Lifecycle constraint.** The archive event `cloud.resource.deleted` is a
handed-in provider observation, not decommission authority. It maps to EA-0025
`mark_unreported` / `aqelyn.inventory.asset_unreported`. Decommission still
requires positive evidence or an attributed EA-0008-gated decision under
EA-0025 S3 / ECR-0014. CSPM registers no deletion assertion of its own.

**Collection boundary.** Descriptors are handed in. Live cloud enumeration remains
a connector-delivered, EA-0008-gated `cloud.enumerate` action; CSPM holds no cloud
credential and opens no provider/network connection.

**Impact.** Governs EA-0028 and C-025 only. The Accepted spec captures this in §0,
D2/D5, FR-6/13/14, NFR-1, and AC-14/15/16. Proof is structural and behavioural per
ECR-0007: forbidden verdict fields fail construction, delegation spies show the
six owners perform analysis, route failure remains visible, and a lifecycle spy
proves provider deletion calls only EA-0025's unreported path.

---

## ECR-0021 — provenance-bound normalized state, and no second name for an EA-0012 fact

**Raised by:** Claude Code (EA-0028 spec review, PR #151).
**Severity:** blocking for C-025 — both items set what the implementer builds first,
and the second one decides whether an event exists at all.

**Problem.** EA-0028 lands the verdict boundary correctly at the model level and then
softens in two places.

1. **The recursive key check is a denylist described as a guarantee.** FR-13 rejects
   six reserved names (`severity`, `score`, `risk_score`, `compliance_status`,
   `finding`, `action`) at any depth, and AC-14 calls the result "verdict fields/keys
   are **unrepresentable** at any normalized depth". For the model's own fields that is
   true and structural (`extra="forbid"` + no such field). For `native_facts` it is not:
   `verdict`, `posture_grade`, `risk_level`, `is_compliant`, `criticality`, `rating`
   and `passed` all pass today, as does `Severity` if matching is case-sensitive. The
   accurate claim is "six known names are rejected", and a future reviewer who trusts
   AC-14's wording will not re-check. A denylist is also the wrong shape here: it must
   anticipate every word a provider or a future contributor might choose.
2. **`aqelyn.cloud.misconfiguration_detected` is a second name for an EA-0012 fact.**
   §10 emits it "when a routed EA-0012 assessment on a cloud object fails a cloud
   baseline". EA-0012 already ships `aqelyn.config.drift_detected` and
   `aqelyn.config.assessment_completed` for that fact. Two events for one occurrence
   invites double-counting, and the name asserts a *detection* from the layer that
   owns no verdicts — rebuilding the silo at the event layer, where the archive's
   restatement pressure was strongest. It is also the event whose apparent net-newness
   was taken as evidence that IS-028 is not a restatement; under the same
   strip-the-prefix reading applied to the rest of the archive's events,
   `cloud.misconfiguration.detected` is `config.drift_detected` scoped to cloud
   objects.

**Resolution.**

1. **Normalized state is provenance-bound.** `set(native_facts) == set(field_provenance)`
   is enforced at construction: every key in normalized state declares the raw provider
   path it came from, and a key without a declared source is unconstructable. This makes
   the boundary an allowlist shaped by D3's own machinery rather than a list of
   forbidden words — an *invented* verdict (`posture_grade`) has no raw source and cannot
   exist, and a *copied* provider verdict is traceable to the field it came from and
   reviewable. The reserved-name check remains as a backstop and becomes
   case-insensitive. AC-14 is reworded to claim only what holds.
2. **CSPM emits no misconfiguration event.** `aqelyn.cloud.misconfiguration_detected` is
   withdrawn. A cloud baseline failure is EA-0012's `aqelyn.config.drift_detected` on an
   object whose `provider` is set; "cloud misconfiguration" is a **query over an existing
   event**, not a new fact — which is the module's own thesis (cloud is a scope filter)
   applied to its event surface. `aqelyn.cloud.resource_normalized` and
   `aqelyn.cloud.resource_unclassified` remain: both are facts this engine genuinely
   originates.

**Impact.** Amends EA-0028 §4/§10, FR-3/FR-13, AC-14, adds **AC-17**
(`test_cspm_native_facts_provenance_bound`), and removes one registered event. C-025
ticket notes updated. No shipped code changes — C-025 has not started.

**Implementation note (not a requirement).** Real provider payloads carry verdict-ish
keys: AWS Config returns `complianceType`, Azure Policy `complianceState`, Security Hub
`Severity`. A normalizer that copies the provider block wholesale will refuse genuine
input. Extraction must be selective — which the provenance-equality rule enforces by
construction, since each extracted key must name its source path.

---

## ECR-0022 — normalized cloud records are tenant-owned and reads require scope

**Raised by:** Codex (C-025 Y1 implementation).
**Status:** Accepted.
**Severity:** blocking contract omission — Y2 cannot implement tenant isolation on
either store while the persisted record and `get` contract carry no tenant scope.

**Problem.** EA-0028 FR-10 and AC-10 require tenant-scoped operations, and
CONVENTIONS §5 requires `tenant_id` on every tenant-owned record plus an explicit
scope on enterprise reads. The Accepted `NormalizedCloudObject` omitted
`tenant_id`, while `CloudNormalizationStore.get(object_id)` accepted no tenant.
`put(obj)` therefore had no tenant to persist, and `get` could only be unscoped or
infer tenancy from ambient state. Either choice would make the in-memory/Postgres
contract diverge or permit a cross-tenant read.

**Resolution.** Add `tenant_id: str | null` to `NormalizedCloudObject`, validated
with the canonical UUID-or-null guard. Change the store contract to
`get(object_id, *, tenant_id)`; `query` already carries the explicit scope. Local
mode continues to use `NULL`, while enterprise mode requires a tenant UUID under
the existing store-mode rules.

**Impact.** Amends EA-0028 §4/§5 and FR-10, adds AC-18
(`test_cspm_tenant_model_guard`), and updates C-025 Y1/Y2 notes. No new capability
or storage field beyond the platform-wide tenancy convention is introduced.

---

## ECR-0023 — normalized facts are flat, so provenance binding is total

**Raised by:** Claude Code (C-025 Y1 review, PR #153). **Correcting my own ECR-0021.**
**Severity:** blocking for C-025 Y2 — it constrains what the normalizer may emit, and
Y2 writes that normalizer.

**Problem.** ECR-0021 replaced a verdict denylist with a provenance binding and claimed
"an invented verdict key has no raw source and cannot exist". Y1 implemented that
faithfully — `set(native_facts) == set(field_provenance)` is enforced — but the binding
is **top-level only**, and I did not say what happens below it. Constructed against the
shipped Y1 model:

```
native_facts={"acl": "public"},                     provenance={}            -> refused
native_facts={"policy": {"severity": "HIGH"}},      provenance={"policy":…}  -> refused (denylist)
native_facts={"tags": {"posture_grade": "F"}},      provenance={"tags":…}    -> CONSTRUCTED
native_facts={"a": {"b": {"risk_level": "crit"}}},  provenance={"a":…}       -> CONSTRUCTED
native_facts={"rules": [{"verdict": "FAIL"}]},      provenance={"rules":…}   -> CONSTRUCTED
```

One level down, the only defence is the reserved-name denylist — the defence ECR-0021
was written to stop relying on. And nesting is the normal case, not an edge case:
provider attributes are structured, so most real `native_facts` will have depth.

**Resolution.** `native_facts` values SHALL be **scalars (`str`/`int`/`float`/`bool`/
`null`) or lists of scalars**. Nested mappings are rejected; structured provider material
belongs in the **raw EA-0004 evidence block**, which the spec already preserves. With
flat values, top-level key binding covers every key in normalized state and the guarantee
is total rather than depth-0.

This is also better normalization, not merely a stricter rule. A nested provider blob in
`native_facts` is un-normalized data carried through the normalizer: EA-0023 wants
`open_ports: [22, 3389]` and `ingress_cidrs: ["0.0.0.0/0"]`, not a copy of the
security-group JSON. Flattening is the translation this engine exists to perform, and the
raw block remains available to anyone who needs the original shape.

**Impact.** Amends EA-0028 §4 and FR-3, adds AC-19 (`test_cspm_native_facts_flat`),
updates C-025 Y1/Y2 notes, and adds the validator to the shipped Y1 model. The
reserved-name denylist remains as a backstop for the flat keys themselves.

**Method note.** This is the second ECR of mine that needed correcting against a shipped
implementation (ECR-0017's null-evidence gloss was the first, fixed in #145). Both were
found by constructing the forbidden state rather than by re-reading the ECR. A spec claim
about what is "impossible" is worth exactly as much as the probe that tried it.

---

## ECR-0024 — selective cloud flattening is an explicit provenance allowlist

**Raised by:** Codex (C-025 Y2 implementation).
**Status:** Accepted.
**Severity:** blocking contract omission — Y2 cannot choose provider facts without
either inventing an undocumented extraction convention or generically flattening raw
provider verdicts into normalized state.

**Problem.** ECR-0021/0023 make normalized state flat and provenance-bound, but the
Accepted `CloudNormalizationConfig` says only which provider type maps to which object
type. It does not say which raw provider paths become facts. A generic recursive
flatten would assign provenance to everything, including AWS Config
`complianceType`, Azure Policy `complianceState`, and Security Hub `Severity`; a hidden
verdict denylist would recreate the maintenance problem ECR-0021 rejected. The desired
selective extraction was therefore not representable in configuration.

**Resolution.** Add `fact_paths: dict[str, dict[str, str]]` to
`CloudNormalizationConfig`. The outer key uses the same provider/resource mapping key
as `type_map`; each inner entry maps a normalized flat fact key to an RFC 6901 JSON
Pointer into `CloudResourceDescriptor.raw`. The normalizer emits only those selected
paths, and records the pointer verbatim in `field_provenance`. Missing paths are omitted
rather than fabricated; selected mappings or lists containing structured values are
rejected because ECR-0023 permits only scalars or lists of scalars. Fact-map entries
without a corresponding `type_map` entry and malformed/non-absolute pointers are
invalid config.

**Impact.** Amends EA-0028 §4/§6, FR-3/FR-10, adds AC-20
(`test_cspm_selective_flatten`), and updates C-025 Y2. It introduces no provider logic,
verdict, or collection capability. Raw payloads remain intact in EA-0004 evidence; the
configuration merely declares which observations are normalized for existing owners.

---

## ECR-0025 — a fact that stops being reported is unknown, not deleted

**Raised by:** Claude Code (C-025 Y2 review, PR #155).
**Severity:** blocking for C-025 Y3 — routing hands these facts to EA-0023/0012/0010, and
a silently deleted fact reaches them as an absence of finding.

**Problem.** ECR-0024 states that a missing configured path is "omitted rather than
fabricated", which is right for a *first* observation. Y2 applies the same rule to a
*subsequent* one: `_resolve_conflicts` reconciles only the keys present in both the
stored and incoming fact sets, and returns the incoming set. A fact that was known and is
absent from the next snapshot is therefore deleted with no conflict record, no flag, and
no trace. Constructed against the shipped Y2 engine:

```
snapshot 1 facts : {'encryption_enabled': True, 'network_public': False, 'open_ports': [22, 443]}
snapshot 2 facts : {'network_public': False, 'open_ports': [22, 443]}
silently dropped : ['encryption_enabled']   conflicts recorded: 0   flagged: False
```

This is **ECR-0014's rule at field level**, and it fails the same way: absence read as
fact. A provider API that omits a key during an incident, a narrowed IAM permission, or a
transient partial response all present as "this resource no longer has that property."
The consequence lands downstream — if `network_public: true` stops being reported,
EA-0023 stops seeing the facet, and a disappearing exposure looks exactly like a
remediated one. Silence becomes good news, in the layer explicitly built so that owners
see cloud reality.

Retaining the old value unconditionally is equally wrong: providers routinely omit a key
when a feature is off, so a stale `True` would hide a genuine change. Absence is neither
the old value nor a new one — **it is unknown**, and it must be represented as such rather
than resolved in either direction. This follows EA-0023's own precedent (unmatched
reachability is `unknown` and flagged, never defaulted) and EA-0025's (`unreported`, still
counted, never decommissioned).

**Resolution.**

1. A configured fact path that produced a value previously and is **absent** from a later
   snapshot SHALL NOT be silently removed. The fact is retained with its last-known value
   and its original `field_provenance`, and marked **`unreported`** — carrying the
   evidence id and `observed_at` of the last snapshot that did report it.
2. The object SHALL be **flagged** when any fact is `unreported`, so the condition is
   visible without inspecting individual facts.
3. The transition SHALL be **recorded** in `conflicts` (the existing mechanism for
   "recorded, not smoothed"), naming the field, the last reporting evidence, and the
   snapshot that omitted it.
4. `explain()` SHALL surface unreported facts, since "why does this object still claim
   X?" is exactly the provenance question this engine exists to answer.
5. A fact that returns in a later snapshot clears `unreported` through the normal
   conflict path.
6. **Downstream owners SHALL receive `unreported` facts as unknown, never as absence.**
   Y3 routing must carry the marker; dropping it at the boundary reintroduces the defect
   one layer later.

**Impact.** Amends EA-0028 §4/§6 and FR-4, adds AC-21
(`test_cspm_unreported_fact_retained`), and updates C-025 Y2/Y3. Implementation is Codex's
(Y2 follow-on): it adds a representation for per-fact reporting state, which is a data-model
change rather than a review fix.

**Note on ECR-0024.** Its "omitted rather than fabricated" wording remains correct for a
first observation and is not withdrawn — this ECR only settles what the same absence means
on a *subsequent* one, which ECR-0024 did not address.

---

## ECR-0026 — owner routing uses a typed, evidence-backed envelope

**Raised by:** Codex (C-025 Y3 implementation).
**Status:** Accepted.
**Severity:** blocking contract omission — the Accepted Y3 interface names six owner
handoffs but does not define a common input, and `route(object_ids)` does not carry the
descriptor metadata needed to distinguish an observation from `reported_deleted`.

**Problem.** The shipped owners expose different contracts: inventory ingests discovery
reports, asset configuration and compliance assess shared objects, exposure consumes known
surface records, IAG reads identity objects, and risk consumes findings/signals. None has a
shared `accept_cloud_object` method, and rewriting all six owners would fork their APIs for
one scope filter. Passing only `native_facts` would also strip ECR-0025's
`unreported_facts`, making a stale retained value look current at the exact boundary the
ECR was meant to protect. Finally, the normalized projection pins the current evidence id
but does not duplicate `change_kind`, source, resource id, or observation time; those facts
remain in EA-0004 evidence by design.

**Resolution.** Y3 introduces a `CloudRouteEnvelope` built from the tenant-scoped
`NormalizedCloudObject` and its pinned EA-0004 evidence. It carries the **entire** normalized
object (including `field_provenance`, `unreported_facts`, conflicts, and flag), plus
`resource_id`, `source_id`, source reliability, `observed_at`, and `change_kind`.
`CloudOwnerRouter` is the adapter boundary: each configured owner receives that envelope
unchanged and returns owner refs. The engine attempts every owner independently and records
accepted/failed outcomes. Concrete adapters translate to the owner's existing API; they do
not add cloud-specific analysis.

For `reported_deleted`, Y3 invokes only the inventory adapter's `mark_unreported` path.
The route envelope is reconstructed from verified stored evidence rather than caller input,
so a caller cannot relabel an observation as deletion or vice versa. `apply_cloud_baselines`
uses a separate EA-0012 adapter receiving the configured baseline ids and cloud scope; CSPM
does not evaluate checks.

**Impact.** Amends EA-0028 §4/§5/§6 and FR-6/FR-14, updates C-025 Y3, and adds no verdict,
collector, finding, or action surface. Y3 tests use six behavioral spies and require every
received envelope to retain `unreported_facts`; Y4 wires concrete adapters without changing
this contract.

---

## ECR-0027 — cloud baselines never reach EA-0012, and the empty result looks clean

**Raised by:** Claude Code (C-025 Y4 review, PR #159).
**Severity:** blocking — EA-0028 **D4/FR-7** ("cloud config assessment is EA-0012 using cloud
`Baseline`s") is non-functional as shipped, and it fails **silently**.

**Problem.** `AssetConfigCloudBaselineRouter` delegates to `AssetConfigAnalyzer.assess`, which
enumerates candidates through `_asset_query`. That builder **overrides** whatever scope it is
given:

```python
data.update({"tenant_id": ..., "object_type": ASSET_OBJECT_TYPE, ...})   # ASSET_OBJECT_TYPE == "asset"
```

CSPM normalizes cloud resources to `cloud_storage` / `cloud_network` / `cloud_iam` / … — never
`"asset"`. No adapter creates an `"asset"`-typed object either: `SharedObjectCloudOwnerRouter`
verifies and returns the existing object, and EA-0025's engine does not write to the object
store at all. So **no normalized cloud object is visible to EA-0012's assessment by any path**.

Constructed end-to-end against the shipped adapter, with a matching baseline in the store and
one non-compliant cloud object present (`encryption_enabled: False`):

```
normalized        : obj_… {'encryption_enabled': False, 'network_public': True}
snapshot id       : drift-snapshot-…
baselines applied : []
assets assessed   : 0
evidence recorded : True
```

A direct `AssetConfigAnalyzer.assess(tenant_id, scope=None)` on the same store returns the same
zero. This is not a classification or configuration gap — the object type is forced in code, so
no deployment configuration can reach it.

**The failure mode is the dangerous half.** `apply_cloud_baselines` returns a snapshot id, records
evidence, and reports zero drift. To every caller and every dashboard above it, "cloud baselines
were assessed and nothing failed" is indistinguishable from "nothing was ever assessed". This is
the platform's recurring defect — absence presented as a clean result — in the one place a
misconfigured cloud estate would be caught. **Not assessed ≠ compliant** (ECR-0012's rule for
scan coverage, restated for assessment coverage).

**Why the milestone's tests passed.** AC-7 (`test_cspm_config_delegates`) exercises delegation
through a **`_BaselineSpy`**, so it proves `apply_cloud_baselines` calls its router with the right
arguments — it cannot prove the concrete adapter shipped in Y4 assesses anything. A delegation spy
demonstrates *intent*; only a run against the real owner demonstrates *connectivity*.

**Resolution.**

1. **EA-0012 owns the widening.** `AssetConfigAnalyzer` gains a configured set of assessable
   object types (default `{"asset"}`, preserving today's behaviour) and stops discarding a
   scope-supplied `object_type`. Cloud object types are assessed by adding them to that set. CSPM
   SHALL NOT relabel cloud resources as `"asset"` to sneak past the filter: the object type is
   information the owners need, and forging it would trade a visible gap for an invisible one.
2. **An assessment that assessed nothing is not a clean assessment.** When a scope matches
   in-scope objects but **no baseline applies to any of them**, or matches no assessable objects
   at all, `apply_cloud_baselines` SHALL surface that state rather than return a zero-drift
   snapshot — refusing, or returning a snapshot that explicitly declares zero coverage. A caller
   must never be able to read "assessed, all clean" from an assessment that ran against nothing.
3. **AC-7 is re-proved end-to-end.** The acceptance test SHALL drive a real `AssetConfigAnalyzer`
   with a real cloud `Baseline` and a non-compliant normalized cloud object, and assert the drift
   is detected. The spy test may remain for argument-passing.

**Impact.** Amends EA-0028 §6 and FR-7, amends EA-0012's assessment scope contract, adds AC-22
(`test_cspm_cloud_baseline_assessed_end_to_end`), and updates C-025 Y4. Implementation is Codex's
— it changes an owner's contract and a shipped query builder, which is beyond a review fix.

**Method note.** Every other owner handoff in Y3 was verified with spies too. Those spies proved
the envelope arrives intact, which was the right question for ECR-0025's marker. They did not ask
whether the receiving owner can act on what arrives. The five non-baseline owners should each get
one end-to-end proof before C-025 is called done.

---

## ECR-0028 — ECR-0027's widening is unreachable in the shipped runtime, and coverage is still not declared

**Raised by:** Claude Code (post-merge review of PR #162, main @affd9d5).
**Severity:** blocking — **EA-0028 FR-7** remains non-functional as deployed, and one shape of
ECR-0027's own defect (a clean snapshot over objects that were never assessed) survives the fix.

PR #162 does the hard part correctly. `assessable_object_types` is a real widening, the forced
`object_type="asset"` is gone, the zero-coverage cases fail closed instead of returning a
zero-drift snapshot, and AC-22 is a genuine end-to-end proof against a real `AssetConfigAnalyzer`
with a real baseline and a real non-compliant normalized cloud object. The five non-baseline owner
seams each got the end-to-end proof the ECR-0027 method note asked for. What follows is what the
merge did not reach.

**(a) No shipped runtime can assess a cloud object.** `kernel/factory.py:808` (memory) and
`:1340` (Postgres) construct `AssetConfigAnalyzer` without a `config`, so `ACGConfig()` applies
and `assessable_object_types == ["asset"]`. `AssetConfigCloudBaselineRouter` reuses
`self.engine.config`, so the CSPM path inherits it. `ACGConfig` is not derived from
`AQELYNConfig` anywhere, so this is not a deployment setting that happens to be unset — there is
no path to set it outside direct construction.

Against the shipped in-memory runtime:

```
assessable_object_types = ['asset']
apply_cloud_baselines(scope={"object_type": "cloud_storage"})
  -> BaselineConfigInvalid: scope object_type 'cloud_storage' is not configured for assessment
```

The refusal is correct and is the valuable half of ECR-0027 — no false clean. But FR-7 ("cloud
config assessment SHALL be performed by EA-0012 using cloud `Baseline`s") is still not performed
by any deployment. AC-22 passes because the test hand-builds `_acg_config()`. That is one level
above the `_BaselineSpy` it replaced and still short of the shipped path: a hand-built config
demonstrates the *mechanism*; only the factory demonstrates *deployment connectivity*.

**Resolution.** `ACGConfig` — at minimum `assessable_object_types` — becomes reachable from
`AQELYNConfig` and is passed at both factory sites, with the CSPM-relevant cloud object types
enabled wherever the CSPM engine is wired. An acceptance test drives the **factory-built** runtime,
not a locally constructed analyzer.

**(b) A shared page budget silently starves later object types.** `_asset_pages` initialises
`remaining = scope.limit` once and decrements it across every type in `object_types`, which the
`ACGConfig` validator sorts alphabetically. The earlier type can consume the entire budget; the
later type is never queried. Neither guard fires — objects *were* assessed and a baseline *did*
apply — so a snapshot is returned. `ObjectQuery.limit` defaults to `100`, so this needs only a
tenant with 100 assets, not an unusual call.

Constructed against a real analyzer with both types configured (`limit=1` for brevity; identical
at 100):

```
snapshot returned  : drift-snapshot-…
baselines applied  : ['cis-server-v1']
overall_score      : 1.0        # reads as "all clean"
cloud object       : obj_… encryption_enabled=False
cloud assessed?    : False
scope recorded     : {'object_type': None, 'limit': 1,
                      'assessable_object_types': ['asset', 'cloud_storage']}
```

The snapshot **records `cloud_storage` as in scope and asserts a clean result over it without ever
querying it**. This is ECR-0027's finding — absence presented as a clean result — reached by a
different route, and the snapshot's own scope field is what makes it credible to a reader.

**Resolution.** The budget is per object type, or the snapshot declares per-type coverage and a
configured type that was never queried is surfaced rather than implied clean.

**(c) Coverage is computed, then thrown away.** `assess` counts `assessed_objects` to drive the
all-or-nothing guard and does not persist it. An assessment that applied a baseline to 1 of 500
in-scope objects is indistinguishable from one that covered all 500: same shape, and
`overall_score` is the mean over the assessed few. "No baseline applied to *anything*" is the
floor of ECR-0027's rule, not its principle — not assessed ≠ compliant holds per object.

**Resolution.** `DriftSnapshot` carries objects-in-scope, objects-assessed, and the object ids
that matched scope but had no applicable baseline. Downstream readers can then tell coverage from
compliance.

**(d) EA-0012's spec was not amended.** ECR-0027 states it "amends EA-0012's assessment scope
contract". `EA-0028-cloud-security-posture.spec.md` was updated (FR-7 + AC-22 ✅);
`EA-0012-asset-config-governance.spec.md` was not: D1 and the glossary still scope assessment to
`object_type "asset"`, `assessable_object_types` appears nowhere, ECR-0027 is absent from its
change-control line, and **FR-5 ("`assess` SHALL persist a `DriftSnapshot`") now contradicts
shipped behaviour** — `assess` raises `BaselineNotFound` on the zero-coverage paths. An owner's
contract changed in code without changing in its spec.

**Also (non-blocking, fold in here):**

- `assess_asset(asset_id)` now raises `BaselineNotFound` where it previously returned `[]`. This
  is a defensible reading of the same principle, but it was not required by ECR-0027, is not in
  any spec, and has no AC. Either document it in EA-0012 with an AC, or revert it.
- "assessment matched no assessable objects" is raised as `BaselineNotFound`. The condition is
  "no objects", not "no baseline"; the two zero-coverage cases should be distinguishable by an
  operator without reading the message string.
- `_scope_dump` no longer round-trips as an `ObjectQuery` — it emits a raw dict carrying an extra
  `assessable_object_types` key and `object_type: None` for multi-type runs. `ObjectQuery` is
  `extra="forbid"`, so any future consumer that re-validates `snapshot.scope` breaks. No consumer
  does today; recording the choice so it stays deliberate.

**Impact.** Amends EA-0012 §D1/FR-5 and its change-control line, amends EA-0028 AC-22 to drive the
factory-built runtime, adds per-type budgeting and snapshot coverage fields. Implementation is
Codex's — it touches the kernel factory, an owner's persisted model, and an owner's spec.

**Accepted resolution.** `AQELYNConfig` now supplies the ACG assessment config and CSPM
normalization/baseline config to both runtime factories. An explicit `ObjectQuery.limit` is a
per-object-type assessment budget; newly issued snapshots persist aggregate and per-type coverage,
including every in-scope object without an applicable baseline. Historical rows remain readable
with `coverage_complete=false` rather than being misrepresented as fully covered. The recorded
scope remains valid `ObjectQuery` data; configured object types live in the coverage records.
Empty scope and missing baselines retain `BaselineNotFound` but carry distinct stable
`details.reason` values, and `assess_asset`'s no-baseline refusal is now part of EA-0012's contract.

---

## ECR-0029 — `coverage_complete` is asserted over a silently truncated page budget

**Raised by:** Claude Code (post-merge review of PR #163, main @0c8ada3).
**Severity:** blocking — the field that ECR-0028 added to make coverage honest reports complete
coverage of an estate it truncated, on the default CSPM call path.

PR #163 resolves ECR-0028 as raised. Both factory sites build a real `ACGConfig` from
`AQELYNConfig` (verified: the shipped runtime now reports
`['asset', 'cloud_compute', 'cloud_database', 'cloud_iam', 'cloud_network', 'cloud_storage',
'cloud_unknown']`), the page budget is per object type (verified: the starvation reproduction from
ECR-0028(b) now assesses the cloud object and scores it `0.5` instead of a clean `1.0`), coverage
is persisted per type, refusals carry stable `details.reason` codes, `_scope_dump` is
`ObjectQuery`-valid again, and EA-0012's spec carries the change-control line, D1/D7, the type
model, FR-14 and AC-18..21. The `DriftSnapshot` model validators make an internally inconsistent
coverage record unconstructible rather than merely tested — the right house pattern.

**The residual.** `_asset_pages` exhausts a type's budget with:

```python
if remaining is not None:
    remaining -= len(rows)
    if remaining <= 0:
        break          # next_cursor may still be non-None — nothing records that
```

The objects beyond the budget were never queried, so they appear in neither
`assessed_by_type` nor `unassessed_by_type`. `objects_in_scope` is therefore the count of objects
**looked at**, and `coverage_complete` is set to `True` unconditionally.

`AssetConfigCloudBaselineRouter.apply` builds `ObjectQuery.model_validate({})` when the caller
passes no scope, and `ObjectQuery.limit` defaults to `100`. So the bound is not a caller decision
— it is a default the caller never saw.

Constructed against a real analyzer and the shipped router: 150 normalized `cloud_storage`
objects, 149 encrypted, one not, calling `apply_cloud_baselines(tenant_id=…)` with **no scope**:

```
cloud estate size      : 150
coverage_complete      : True
objects_in_scope       : 100
objects_assessed       : 100
unassessed_object_ids  : 0
overall_score          : 1.0
non-compliant bucket   : obj_… (encryption_enabled=False)
  assessed?            : False
  listed as unassessed?: False
```

The misconfigured bucket is not assessed, not listed as uncovered, and not implied by any count.
The snapshot states that coverage is complete and the estate is clean. This also fails **FR-14**
as written — "objects in scope" is not the objects in scope.

This is the third form of the same defect (ECR-0027 → ECR-0028(b) → here), and the most
dangerous, because it is now wearing the field that was added to prevent it: a reader who checks
`coverage_complete` before trusting `overall_score` is still misled. Every real cloud estate is
larger than 100 objects.

**Resolution.**

1. **Truncation makes coverage incomplete.** When a type's budget is exhausted and `next_cursor`
   is not `None`, that type is truncated: `coverage_complete` SHALL be `false`, and the truncated
   object types SHALL be named on the snapshot (per-type `truncated: bool`). The signal exists at
   the `break` and is discarded — it costs one flag to keep.
2. **An unscoped assessment SHALL NOT inherit a default bound.** `apply_cloud_baselines` with no
   caller scope means the whole estate: pass no limit and page to exhaustion, or refuse rather
   than silently assess a prefix. A bound the caller never chose must not be reported as coverage.
3. `coverage_complete=false` must remain readable — it already denotes pre-ECR-0028 historical
   snapshots, so truncated-new and historical-unknown SHALL be distinguishable (a reason, not just
   a boolean).

**Impact.** Amends EA-0012 FR-14 and D7, adds a per-type `truncated` flag to
`ObjectTypeAssessmentCoverage` and its consistency validator, amends EA-0028's baseline-router
scope handling, adds an AC driving an estate larger than the default limit. Implementation is
Codex's.

**Accepted resolution.** `ObjectQuery.cursor` is now honored by both object-store backends so
unbounded assessments can page to exhaustion. A caller-supplied scope limit remains a bound, but if
that bound is exhausted while more rows remain, the resulting `DriftSnapshot` is persisted as
`coverage_complete=false`, `coverage_incomplete_reason="truncated"`, with the truncated object
type named by `ObjectTypeAssessmentCoverage.truncated=true`. Historical unknown coverage remains
readable as `coverage_complete=false` with no reason and empty coverage fields, while new writes
must be either complete or explicitly truncated. `AssetConfigCloudBaselineRouter.apply` treats a
missing caller `limit` as unbounded, even after it adds the EA-0028 label filter; a no-scope CSPM
baseline run over more than the old default 100 objects now assesses every page and omits `limit`
from the stored scope.

---

## ECR-0030 — EA-0002 never paginated, and Postgres filtered labels after the LIMIT

**Raised by:** Claude Code (post-merge review of PR #164, main @7eabbd8).
**Severity:** blocking for EA-0002's contract and traceability; the code fix has already landed —
what is missing is the owner's spec, the disclosure, and the consumer sweep.

PR #164 resolves ECR-0029 as raised, and I verified it end-to-end on both backends. The
reproduction from ECR-0029 — 150 `cloud_storage` objects, one unencrypted, `apply_cloud_baselines`
with no scope — now assesses all of them, catches the misconfigured bucket, and scores `0.993`
instead of a clean `1.0`. A caller-supplied limit that truncates now persists
`coverage_complete=false`, `coverage_incomplete_reason="truncated"`, and names the truncated type;
the model validator keeps truncated-new distinguishable from historical-unknown. Full suite: 666
passed in-memory, **916 passed / 3 skipped on live Postgres 16 + Redis 7**.

**What landed alongside it.** To make "page to exhaustion" possible, #164 changed
`ObjectStore.query` in both backends. Those edits fixed two pre-existing defects in the platform's
most-depended-on owner. Running the same script against `0c8ada3` (pre-PR) and `7eabbd8` (post-PR),
150 objects, `limit=100`, of which 50 carry the filtered label and all 50 sort after the first
page:

```
pre-PR  (0c8ada3)                             post-PR (7eabbd8)
[memory]   next_cursor=None                   [memory]   next_cursor=set
[memory]   paged to exhaustion: 100 of 150    [memory]   paged to exhaustion: 150 of 150
[postgres] next_cursor=None                   [postgres] next_cursor=set
[postgres] paged to exhaustion: 100 of 150    [postgres] paged to exhaustion: 150 of 150
[postgres] labelled query: rows=0  (50 match) [postgres] labelled query: rows=50
```

1. **`next_cursor` was never returned by either backend.** `InMemoryObjectStore.query` ended
   `return rows[: q.limit], None`; `PostgresObjectStore.query` ended `return out, None`. Every
   `while next_cursor` loop in the platform was dead: it ran once, saw `None`, and concluded the
   estate was exhausted. "Paged over the estate" was, everywhere, "the first page of the estate".
2. **Postgres applied `labels` and `natural_key` in Python after the SQL `LIMIT`.** The database
   returned the first `limit` rows matching only the *other* predicates, and the filter then ran
   over that window. Matching rows outside it were not merely missed — the query returned an empty
   result that reads as "nothing matches". Note where that lands: `AssetConfigCloudBaselineRouter`
   filters on `labels={"module": "EA-0028"}`. On the production backend, the EA-0028 baseline path
   was broken twice over, and only the in-memory backend ever showed the first failure.

Both are the platform's recurring defect — absence rendered as a clean, complete result — sitting
in EA-0002 the whole time. #164 fixed them correctly. What it did not do is treat them as an
owner-contract change.

**Resolution.**

1. **Disclose and spec it.** EA-0002's spec gains the pagination contract (`query` returns a
   `next_cursor` when more rows match; `cursor` is honored; `labels` and `natural_key` are
   applied *before* the limit, not after) plus acceptance tests for each, and the change-control
   line records this ECR. The ECR-0029 note currently describes the cursor work as an enabler for
   EA-0012 and does not mention that no consumer had working pagination, nor the Postgres filter
   bug at all.
2. **Sweep the consumers.** `governance/engine.py:_pages` (EA-0010) and `iag/engine.py`
   identity paging (EA-0011) contain `while next_cursor` loops that were dead and are now live:
   this merge silently widened what those two modules assess, with no test and no note in either
   spec. Their coverage semantics need an explicit check, exactly as EA-0012's did.
3. **Close the ones still capped.** `soc/engine.py:300` and `threat/correlate.py:169,206` call
   `objects, _ = await object_store.query(...)` — they discard the cursor and still see one page,
   now provably. Either they page, or they declare their bound the way `DriftSnapshot` now does.
   Three ECRs were spent removing this exact failure from EA-0012; it should not survive
   unremarked in two other modules.

**Also (non-blocking):**

- `assess(..., use_scope_limit: bool)` carries the caller's intent *beside* the query rather than
  in it, because `ObjectQuery.limit` cannot express "unbounded". `limit: int | None` on
  `ObjectQuery` would put it in the type and remove the sidecar from EA-0012's public signature.
- `_scope_dump` omits `limit` entirely for an unbounded run. Re-validated as an `ObjectQuery` that
  dict yields `limit=100`, so the stored scope of an unbounded assessment reads as bounded.
  Nothing re-validates it today; recording it so the choice stays deliberate.

**Impact.** Amends EA-0002's spec and ACs, adds pagination/label acceptance tests on both
backends, and requires coverage checks in EA-0010, EA-0011, plus a decision for `soc` and
`threat.correlate`. Implementation is Codex's — it touches a core owner's contract and four
consuming modules.

**Accepted resolution.** EA-0002 now owns the stable id-ordered pagination contract: filters are
applied before the page limit, `cursor` is an exclusive continuation token, and `next_cursor` is
returned exactly when another matching row exists. The shared in-memory/Postgres contract suite
proves label and natural-key filtering plus multi-page exhaustion. EA-0010 and EA-0011 exhaust
object pages in bounded batches and fail closed on a repeated cursor; real-store acceptance tests
prove assessments and certifications include later pages. EA-0015 threat hunts page past
post-query attribute non-matches until the requested result bound is filled or the estate ends.
EA-0014 retains its configured correlation cap, pages past expired indicators, and marks
`MatchReport.truncated=true` whenever unprocessed indicator or asset rows remain.

---

## ECR-0031 — the page sweep traded a silent cap for unbounded per-request work

**Raised by:** Claude Code (post-merge review of PR #165, main @2d76d2b).
**Severity:** blocking for EA-0015 — `hunt` is an interactive analyst operation whose cost is now
proportional to estate size, and EA-0015's own D7/NFR-3 still promise a bounded query.

PR #165 resolves ECR-0030 as raised, and thoroughly. EA-0002 gains **D8**, **FR-13**, **FR-14**
and **AC-13/AC-14**, stated as a contract rather than a fix ("`next_cursor` is non-null exactly
when another matching object exists"; "filtering after the page limit is therefore forbidden"),
with adversarial-ordering proofs on both backends. EA-0010, EA-0011, EA-0014 and EA-0015 carry
change-control lines. Governance and IAG genuinely page. `MatchReport.truncated` now unions the
indicator and asset page bounds instead of only the KG's. Codex also found and fixed something I
did not ask for and had missed: expired indicator pages could starve live indicators out of the
budget entirely. Verified here: **673 passed** in-memory, **930 passed / 3 skipped on live
Postgres 16 + Redis 7**.

**The regression.** Two of the swept loops now continue until their result quota is filled *or the
estate is exhausted*, with no ceiling on the work in between. Measured against real engines with a
counting `ObjectStore`:

`SecurityOperationsEngine.hunt`, `attribute_equals` matching nothing (the shape an analyst uses to
disprove a hypothesis):

```
estate    queries   rows scanned   elapsed
  500        10          500        0.76s
 1000        20         1000        3.31s
 2000        40         2000       10.11s      → 0 matches
```

`threat.correlate`, all indicators expired (the shape of a stale feed):

```
estate    queries   rows scanned   elapsed
  500         6          500        0.22s
 1000        11         1000        0.76s
 2000        21         2000        3.42s      → 0 matches
```

Both were one query before #165. Both are now O(estate), and the wall-clock is superlinear on the
in-memory backend. Ten seconds to answer "no" on a 2 000-object estate extrapolates badly: the
cost is paid on exactly the queries that find nothing, which is most hunts.

EA-0015 **D7** ("Threat hunting is bounded, saved queries") and **NFR-3** ("intake/correlation/hunt
process in bounded batches") are unchanged. **FR-8** was amended to "follow object pages until its
match limit is filled or the estate is exhausted", which describes the new loop but contradicts the
decision and the non-functional target above it. The requirement moved; the promise did not.

**This is ECR-0001 again.** `paths()` was bounded by `max_depth`/`max_paths` and still had
unbounded worst-case effort, so it got `max_work` — "bounded, never hang". A result-count bound is
not a work bound when the filter is selective. The platform already has the right shape for the
honest version of this: `DriftSnapshot` pages under a budget and, when the budget is exhausted with
rows remaining, returns what it found as `coverage_complete=false, reason="truncated"`. Reachability
of a late match and boundedness are not in tension — declaring the bound satisfies both.

**Resolution.**

1. **`hunt` pages under a work budget.** A configured maximum pages/objects examined per hunt
   (default in the low thousands, hard-capped), reached → stop and report. EA-0015 D7/NFR-3/FR-8
   are reconciled to one statement.
2. **`hunt` gains a truncation channel.** It currently returns a bare `list[dict]`: exactly `limit`
   matches is indistinguishable from `limit` matches and more, and after (1) an exhausted budget
   has no way to be said at all. EA-0014 got `truncated` in this same sweep; EA-0015 needs the
   equivalent, or the budget it hits will be invisible — the defect ECR-0027 through ECR-0030 were
   spent removing.
3. **`_active_indicators` takes the same budget**, setting `indicators_truncated=true` when it
   stops early. The plumbing already exists — `MatchReport.truncated` is wired.
4. **(Separate, non-blocking.)** `InMemoryObjectStore.query` sorts every matching row and
   deep-copies the whole match set on each call, before slicing to the page. That is what makes the
   paged loops quadratic rather than linear. Copy the selected page only. This is a test/dev-runtime
   cost, not a production one, but it is what turns the measurements above from bad into alarming.

**Impact.** Amends EA-0015 D7/NFR-3/FR-8 and its hunt return type, amends EA-0014 FR-6, adds a
work-budget config to both, and one acceptance test per module proving a budget-exhausted run is
reported and not silently short. Implementation is Codex's.

**Accepted resolution.** EA-0015 adds `SOCConfig.hunt_max_work` (default `5_000`, hard cap
`100_000`) and returns `HuntResult { matches, evaluated, truncated }`; a no-match hunt stops after
the configured number of examined objects and reports `truncated=true` when another matching
object-store page remains. EA-0014 adds `FusionConfig.correlation_max_work` with the same default
and hard cap; expired indicators consume that budget, and an exhausted indicator scan propagates
to `MatchReport.truncated`. Both limits reject values outside `1..100_000`. The in-memory object
store maintains its stable id order incrementally and deep-copies only the selected page, removing
the repeated full-result sort/copy that made the measured paging cost superlinear.

---

## ECR-0032 — Consider a shared posture-normalization base (CSPM + SSPM + DSPM + ISPM)

**Raised by:** planning (IS-029 spec pass).
**Status:** Rejected after the post-C-037 reviewer audit recorded below.
**Numbering note:** first drafted as ECR-0017 in error — that number was already
Accepted (EA-0027 S3 confidence-floor value, PR #141). Corrected to ECR-0032, the
next free number after the log's ECR-0031. The floor decision is untouched.

**Observation.** EA-0028 (CSPM) and EA-0029 (SSPM) share an identical shape:
`normalize(handed-in descriptor) -> AQObject + field_provenance + recorded
conflicts -> route to owners`, differing only in provider vocabulary and
`type_map`. EA-0031 (DSPM) is the **third** instance and adds a metadata-only
classification step between normalization and routing. EA-0033 (ISPM) is the
**fourth** and adds deterministic account-control scoring while routing identity
governance back to EA-0011. The revisit condition in this ECR is well past met.

**Proposal.** After C-030 is merged and green, consider extracting a
`posture_normalization` base (the descriptor→object→provenance→route
machinery + the pending-not-safe routing discipline) that each specialises with
its vocabulary. The design must accommodate DSPM's classify step without moving
classification ownership or weakening any module's typed envelope.

**Guardrails.**
- **Do not build the base speculatively** and do not fold it into C-025, C-026,
  C-028, or C-030 —
  each engine ships on its own footing first (avoids a premature abstraction that
  two slightly-divergent callers then fight).
- Extraction is a **behaviour-preserving refactor**: the shared base must pass
  all four engines' existing suites unchanged (ECR-0007 — behavioural proof).
- The fourth implementation now exists. That makes a review warranted, not an
  extraction mandatory.

**Recommendation.** Hold as Proposed. Decide after C-030 is green, against all
four real implementations. Any extraction remains a separate,
behaviour-preserving refactor whose existing suites pass unchanged.

### RESOLUTION - **Rejected** (post-C-037, reviewer audit at `a692d1c`)

**Status: Proposed -> Rejected.** The deciding evidence is in; holding it further
would be deferral without a pending question.

**The deciding question.** Not *"is there duplication"* - there is, four times -
but **do the four normalizers differ in their unknown handling?** Duplication of
plumbing is cheap to carry; divergence in unknown handling decides whether a
shared base can exist without changing behaviour. The reviewer answered it from
shipped code:

| Module | `unknown` is a... |
|---|---|
| **CSPM** | object type - `CLOUD_UNKNOWN_OBJECT_TYPE` |
| **SSPM** | object type - `SAAS_UNKNOWN_OBJECT_TYPE` |
| **DSPM** | classification state on a *downstream* record - **nothing in normalization**; `state="reachability_pending"` in exposure |
| **ISPM** | flag on the normalized record - `identity_kind` or `"unknown"` -> `flagged=True` pending resolution |

**Only CSPM and SSPM genuinely share a mechanism.**

**The finding that closes it.** DSPM's and ISPM's divergence sits in the step that
made them the third and fourth instances - **classification** and **control
scoring** respectively. So **the divergence is not incidental; it *is* the
extension.** "Four instances of one pattern" was always slightly wrong: they are
four instances of a shared **shell** with divergent **cores**.

A base therefore has only two possible shapes, and neither is worth building:

- **Extract the plumbing only** - saves the cheap part (descriptor -> object ->
  provenance -> route), leaves every interesting part divergent, and adds an
  indirection each future reader must traverse to find behaviour that was never
  shared.
- **Homogenize the cores** - that is a **behaviour change wearing a refactor's
  clothes**. It would need its own ECR, its own proof, and it would silently
  change four modules' unknown semantics, which is the one thing this platform
  guards hardest.

**The cost of continuing to hold it.** ECR-0032 has been carried in **nineteen
documents** - ten consecutive task bundles (C-026 through C-037), four specs, both
GC bundles, the batch conformance analysis, the IS-037 analysis, the README, and
this log - each repeating some form of *"preserve, do not absorb: ECR-0032."*
**Proposed** signals *pending information*; the information is now in hand, so
every further review re-asks a settled question, and a fifth posture module would
re-litigate the analysis from scratch. Closing it converts a standing tax into a
decision a future reader can check in one line.

**Reopening condition (the only one).** Reopen **if and only if a future posture
module's `unknown` handling matches an existing one's** - that is, if divergence
stops being the extension. A fifth instance is *not* by itself grounds to reopen;
a fifth instance whose unknown semantics are genuinely shared is.

**Guardrail, if it ever proceeds.** The base must be **structurally incapable of
expressing a default** - no parameter, no fallback branch, no optional argument
that could carry one. Not a rule to follow but a property to hold, in the platform's
own idiom (no person-score type, no secret-value field, no un-gated execution). A
shared normalization base able to supply a default is precisely how **ECR-0013's
unwired-default shape would enter four modules at once**, and it would arrive
wearing the credibility of a de-duplication.

**Consequence for future bundles.** Drop the *"preserve, do not absorb: ECR-0032"*
line. The tracked backlog is now the EA-0018 unclamped-duration flake, the
EA-0027/EA-0018 enterprise health probes, the EA-0013 equal-timestamp tie-breaker,
and the finding re-scoring question - plus the separately-tracked
first-deployment items (`FIRST_DEPLOYMENT_ITEMS.md`).

---

## ECR-0033 — SSPM uncertainty, bounded reach, and normalization-store pagination

**Raised by:** Claude Code (review of PR #167, main @8f9cf1c).
**Severity:** blocking before C-026 — two type declarations made an unknown or
truncated integration look safer than the evidence supports, and the exposure
delegation named an owner interface that does not exist.

**Problem 1 — unknown scope was unrepresentable.** EA-0029 §11 requires a grant
with missing scope data to be recorded as `over_scoped: unknown`, but §4 declared
`over_scoped: bool`. The only available value for "not assessed" was therefore
`False`, which reads as safe and violates the spec's pending-not-safe boundary.

**Problem 2 — bounded blast radius discarded its bound.** EA-0005 `subgraph()`
already returns `Subgraph.truncated`, but `SaaSIntegration` carried only
`reachable_object_ids`. A node-bounded traversal could therefore serve a short
list as if it were the complete blast radius — the ECR-0029/ECR-0031 defect
class on EA-0029's one genuinely new capability.

**Clarification — confidence is in the claim, not the vendor.** A bare
`confidence` field on a record whose subject includes `third_party_app` can be
read as vendor trust despite S5 making vendor verdicts unrepresentable. The
field must name and enforce its actual meaning: confidence that the reported
grant exists with the stated scopes, derived from source evidence via EA-0006.

**Problem 3 — the specified EA-0023 delegation did not exist.** EA-0029 named a
`SurfaceFacet` and `api_endpoint`/`federated_identity` taxonomy that EA-0023
does not define. The shipped intake is `KnownSurfaceSource ->
KnownSurfaceRecord -> derive_surface()`, with `AssetKind` values including
`api` and `identity`. The integration capability was therefore specified
against an interface no implementation could call.

**Resolution.**

1. Add `OverScopedStatus = Literal["over_scoped", "within_scope", "unknown"]`;
   incomplete scope data always produces `"unknown"` and pending routing. The
   semantic tokens avoid the truthiness trap of string values `"true"` and
   `"false"`.
2. Add `BlastRadius = {object_ids, truncated}`,
   `SaaSIntegration.reachable_truncated`, and
   `SaaSConfig.integration_max_nodes` (default `10_000`, EA-0005 hard cap
   `100_000`). Blast-radius traversal delegates to EA-0005 `subgraph()` under
   that node budget and propagates `Subgraph.truncated`. EA-0005 `paths()` is
   not used here because its `list[Path]` return has no truncation channel.
3. Rename `confidence` to `claim_confidence`; only source evidence/reliability
   may contribute. Vendor identity, reputation, reach, or attributes are not
   inputs. A behavioral test proves the score cannot become a vendor verdict.
4. Replace the nonexistent facet contract with a store-backed
   `SaaSIntegrationKnownSurfaceSource`. It yields an EA-0023
   `KnownSurfaceRecord` for each external `over_scoped` grant, uses the shipped
   `AssetKind` values `api`/`identity`, and cites integration evidence through
   an `access` basis. Both factory sites compose this source with the existing
   inventory source so neither source is replaced. Integration descriptors and
   records carry the kind and observation time required to build that record;
   the durable store exposes tenant-scoped, paginated integration reads. The
   adapter pages to exhaustion, preserves upstream rows, replaces a same-object
   placeholder rather than duplicating it, and fails rather than serving a
   partial source.
5. Drive `test_sspm_assessable_both_sites` through the factory-built in-memory
   and Postgres runtimes, not a hand-built `ACGConfig`.
6. Do not copy EA-0028's limit-only normalization-store query. Upgrade both
   Cloud and SaaS stores in C-026 Z2 to EA-0002 D8 semantics: stable id order,
   filters before limit, exclusive cursor, and `next_cursor` exactly when another
   matching row exists.
7. Carry AQELYN `tenant_id` on normalized SaaS objects and integrations; require
   explicit tenant scope on every store read, matching EA-0028's ECR-0022
   contract rather than relying on provider tenant names.

**Impact.** Amends EA-0029 §0/§2/§4/§5/§6, FR-6/7/8/10a/12/13, failure handling,
and acceptance criteria; amends EA-0028's store interface, FR-11 and AC-24; adds
the cross-owner store follow-up to C-025 and makes it a required C-026 Z2
deliverable. No production code changes in this docs PR; implementation starts
only after the amended contract merges.

---

## ECR-0034 — the inventory denominator is silently capped at 10 000

**Raised by:** Claude Code (found while reviewing PR #168's composite known-surface source;
re-verified against `main` @54122e0 after C-026 and C-027 merged).
**Severity:** blocking for EA-0025's S4 guarantee; it silently weakens three downstream owners.

Not a defect in PR #168 — found by following what that PR composes with.

**Problem.** `InventoryIntelligenceEngine.inventory()` (`src/aqelyn/inventory/engine.py:242-257`):

```python
rows = await self.store.query(tenant_id=selected_tenant, limit=10_000)
...
return InventoryReport(assets=sorted(...), total=len(included), degraded=False, ...)
```

`AssetStore.query` (`src/aqelyn/inventory/store.py:17-23`) returns `list[AssetRecord]` — no cursor,
no `next_cursor`, no more-remaining flag. So at 10 000 the engine cannot tell a complete estate from
a truncated one, and it hardcodes `degraded=False`. A tenant with 10 001 assets receives a report
whose `total` asserts 10 000 and whose `degraded=False` asserts the count is trustworthy.

`sweep_unreported` (`engine.py:169`) reads the same capped query, so assets beyond the cap are also
never swept — they cannot be marked `unreported` because they are never seen.

**Reproduced** (in-memory store, 10 050 active assets, one tenant):

```
assets actually in store        : 10050
InventoryReport.total           : 10000
InventoryReport.degraded        : False
missing, unreported to caller   : 50
EA-0023 known-surface records   : 10000   (fail-closed gate did not fire)
EA-0024 coverage denominator    : 10000
EA-0024 unscanned reported      : 10000   (50 assets neither scanned nor unscanned)
```

**Why it matters beyond EA-0025.** That report is a denominator three owners depend on:

- **EA-0023** — `InventoryKnownSurfaceSource` (`inventory/service.py:61-90`) turns it into the
  known-surface set. A capped inventory is a shrunken attack surface, and the missing assets are
  absent rather than flagged. EA-0029's `SaaSIntegrationKnownSurfaceSource` (ECR-0033) composes
  with this source and fails closed on partial reads; the guarantee is only as strong as its
  weakest input.
- **EA-0024** — the coverage provider computes `unscanned = inventory − scanned`. With a capped
  inventory, `unscanned` under-reports: assets past the cap are neither scanned nor counted as
  unscanned. ECR-0013 made that provider refuse rather than report an optimistic default; the
  store contract underneath re-introduces the optimism.
- **EA-0030** — `SupplyChainEngine` is constructed with `inventory=inventory_engine` in both
  factory runtimes and calls `inventory.ingest(...)` for every parsed SBOM component and every
  provenance-status update. Software components therefore land in the *same* `AssetStore` the cap
  reads, so 10 000 is no longer a large-estate threshold — a few thousand hosts plus the component
  inventory of a handful of applications reaches it in ordinary operation.

Both EA-0023's and EA-0024's refusals are keyed on `report.degraded`
(`inventory/service.py:67`, `:110`). Because the engine hardcodes `degraded=False`, those gates are
structurally unreachable for store truncation: the fail-closed path exists and cannot fire.

**Why EA-0025's S4 does not catch it.** S4 protects against *source* degradation shrinking the
inventory — `degraded → FAIL, never shrink`. This is *store* truncation, a different axis, and the
`degraded` flag is not wired to it. "Shrinking inventory that looks like good news" was made
structurally impossible for the absence case and remains reachable through the page limit.

**Resolution.**

1. `AssetStore.query` adopts the EA-0002 D8 shape (ECR-0030): stable id order, exclusive cursor,
   `next_cursor` non-null exactly when another row matches. Both backends, one contract suite.
2. `inventory()` pages to completion under a work budget, **or** — if a hard bound is wanted —
   refuses rather than truncates: an inventory that cannot enumerate its estate is
   `InventoryUnavailable`, not a smaller inventory. `degraded=False` SHALL be asserted only when
   the enumeration was complete. ECR-0031 is the precedent for not trading a silent cap for
   unbounded per-request work.
3. `sweep_unreported` pages the same way; an asset past the cap must not be invisible to the sweep.
4. EA-0023's, EA-0024's and EA-0030's adapters inherit the guarantee — no separate fix needed once
   the denominator is honest. Add a regression test that an over-cap estate either enumerates
   fully or trips `degraded`, and that both downstream gates then refuse.

**Impact.** Amends EA-0025's store contract, `inventory()`, and `sweep_unreported`; adds
pagination ACs on both backends. EA-0023/EA-0024/EA-0030 need no change beyond re-verification.
Implementation is Codex's.

### Resolution — C-034 (ECR-0059), route (A): the honest flag, not the cursor

C-034 could not certify IS-037 over this denominator, so it took the fix rather than
recording a bounded residual. The bound was already routinely exceeded: EA-0030 ingests
one `AssetRecord` per parsed SBOM component (`supplychain/engine.py:212`), so
*"conformant for ≤ 10 000 assets/tenant"* would have certified a configuration the
platform does not run in.

**What landed.** `AssetStore.query` is unchanged — no protocol change, so no test double
or backend implementer had to move (rule 18). The engine reads one row past the cap
(`_ASSET_QUERY_PROBE = _ASSET_QUERY_CAP + 1`) and treats a full result as proof that more
exists:

- `inventory()` truncates to the cap and returns `degraded=True` instead of `False`.
- `sweep_unreported()` refuses. It has no report to flag, and a half-sweep would leave the
  unread rows still looking currently-reported — a stale posture they have not earned.
- `ISPMEngine._inventory_note` now reads the flag rather than asserting the cap is
  unresolved in prose.

**What did not land.** `limit + 1` says *more exists*; it does not deliver the rest.
Completeness is cursor pagination under a work budget (EA-0002 D8 / rule 10) and remains
a separate change — items 1–3 of the plan above are only partly discharged. `AssetStore`
still has no cursor. **This resolution closes the silent-truncation defect, not the
pagination gap.**

`inventory_complete` on `ISPMAssessment` stays hardcoded `False`. Deriving it from
`degraded` would newly claim exhaustiveness below the cap, which is a wider claim than
this change earns.

**Consumers, enumerated and asserted.** An honest flag nobody reads is the ECR-0013
shape, so all four consumers of `inventory()` are proven to act on it by driving a real
engine past the cap with 10 001 real records:
`InventoryKnownSurfaceSource.list_known_surface` refuses (`InventoryUnavailable`, and
`derive_surface` inherits it), `InventoryVulnerabilityCoverageProvider.coverage` refuses
(`CoverageUnavailable`), `ISPMEngine._inventory_note` flags, and
`InventoryIntelligenceService.inventory` passes the flag through intact.

**Behavioural change (the ECR-0040 situation again).** Deployments above 10 000 assets
will see these gates begin refusing where they previously proceeded. That is a correction
surfacing a pre-existing wrong answer, not a regression: those deployments were already
being told an attack surface was exhaustive when it was not.

**Status:** **Fully resolved.** Silent truncation closed by C-034 (this section); cursor
pagination under a work budget closed by **C-036 / ECR-0061**. The remaining cap is
explicit, configurable, and reported.

---

## ECR-0035 - the blast radius has three states and the type holds two

**Raised by:** Claude Code (C-026 Z1 review, PR #169; merged before the fix, so raising it here).
**Severity:** blocking before Z2 - Z2 persists this shape into both stores, and every later
consumer reads `reachable_object_ids == []` as a fact about the world.

**Problem.** `SaaSIntegration` (`src/aqelyn/sspm/models.py:311-312`) carries:

```python
reachable_object_ids: list[str] = Field(default_factory=list)
reachable_truncated: bool = False
```

Three states exist in the real system:

1. traversal ran, the grant reaches nothing -> `[]`, `truncated=False`
2. traversal ran, hit `integration_max_nodes` -> partial list, `truncated=True`
3. traversal never ran (KG unavailable - the case EA-0029 §11 explicitly requires) -> **no
   representation**

State 3 renders identically to state 1. Constructed against the shipped model:

```
computed-reaches-nothing : [] False
reach-not-computed       : [] False
distinguishable?         : False
```

The ambiguity resolves toward **safe**: a grant whose blast radius was never computed reads as a
grant that reaches nothing. That is the platform's recurring defect - absence rendered as a clean
result - in the field that quantifies how much damage a third-party grant could do.

`SaaSRoutingResult.routing_pending` does not cover it. That object describes one routing attempt;
the persisted `SaaSIntegration` is what FR-7's `SaaSIntegrationKnownSurfaceSource` reads back via
`query_integrations`, and it cannot say "reach unknown". `reason` is free text, not machine-readable.

**The model already knows the pattern.** ECR-0033 gave `over_scoped` an explicit `unknown` in this
same class, for exactly this reason. Reach did not get the same treatment - and the spec is the
reason: §4 declares only the two fields, so Z1 implemented what was written. The spec review
(mine) caught the truncated case and missed the not-computed case.

**Resolution.**

1. Replace `reachable_truncated: bool` with
   `reach_status: Literal["computed", "truncated", "pending"]`, defaulting to `"pending"` so an
   unset reach is never silently complete.
2. Model validator: `pending` requires `reachable_object_ids == []`; `truncated` requires a
   non-empty list; `computed` permits either.
3. Amend EA-0029 §4 (type), FR-6 (propagate `Subgraph.truncated` as `reach_status="truncated"`,
   KG-unavailable as `"pending"`), and §11.
4. Extend AC-7a and add an AC asserting a pending reach is distinguishable from an empty one.
5. Land before Z2 writes the column/field into either store.

**Impact.** One field on one model, its validator, four spec lines, two ACs. Landed before Z2
persisted the shape or Z3+ consumers could read an empty list as fact.

---

## ECR-0036 - SSPM owner references and blast-radius reads must retain tenant scope

**Raised by:** Codex (C-026 Z3 implementation against the real EA-0025 and SSPM
store contracts).
**Severity:** blocking within Z3 - both defects prevent the accepted owner
composition from being implemented without weakening an existing contract.

**Problem 1.** `SaaSRoutingResult.inventory_ref` shared one validator with
`integration_ref`, requiring both to use the `obj_` prefix. The real EA-0025
inventory adapter returns an `AssetRecord.id`, whose owner contract requires an
`ast_` prefix. A real-owner routing test therefore failed while the Z2 spy passed
because it echoed the normalized object's `obj_` id.

**Problem 2.** The accepted interface declared
`integration_blast_radius(integration_id)` without tenant scope, while FR-12 and
`SaaSNormalizationStore.get_integration` require every integration read to carry
explicit `tenant_id`. Implementing the signature literally would create an
unscoped read path through a tenant-owned store.

**Resolution.** Validate `inventory_ref` as `ast_` and `integration_ref` as
`obj_`. Add required keyword-only `tenant_id` to `integration_blast_radius` and
validate it before reading the store. Tests route through the real inventory
owner and prove a cross-tenant integration read cannot be expressed through the
public method.

**Impact.** Two type-boundary corrections before Z3 has any downstream consumer;
no persistence or schema change. The changes make the accepted composition and
FR-12 simultaneously satisfiable.

---

## ECR-0037 - durable SBOM reconciliation and filter-complete pagination

**Raised by:** Codex (C-027 Q2 implementation against EA-0030 S6/FR-8 and the
platform's post-ECR-0030 store contract).
**Severity:** blocking within Q2 - the accepted shapes cannot durably record the
required reconciliation and would introduce another silently capped store.

**Problem 1.** EA-0030 requires conflicting SBOM claims to be reconciled by
EA-0006 and recorded, but `SoftwareComponent` carries only the selected values
and `evidence_id`. It does not identify the winning source or observation time,
and has no place to retain the losing candidates. A process restart therefore
loses the information needed to reconcile the next claim and the conflict that
explains the selected value.

**Problem 2.** The accepted `SBOMStore.query(limit=1000) -> list[...]` shape has
the limit-only ambiguity corrected in EA-0002 D8 and ECR-0033: a full page cannot
say whether the result is complete. Q2 is the first persistence ticket, so this
is the last point where the cursor can be added without a schema/API migration.

**Resolution.** Add winning `source_id` and `observed_at` plus durable
`ComponentConflict` records to `SoftwareComponent`. Add a structurally flagged
`QuarantinedSBOM` record and store methods so parse failure is recorded before it
is raised. Make `SBOMStore.query` return `(rows, next_cursor)` using an exclusive
object-id cursor, with tenant/provenance filters applied before `limit` and a
cursor returned exactly when another matching row exists. Both backends pass one
adversarial contract suite.

**Impact.** Q2-only model and store additions before any Q2 record exists. No
existing consumer or persisted schema is migrated; later Q3-Q5 tickets receive a
durable, tenant-scoped component identity and an honest paging contract.

---

## ECR-0038 - Q3 must carry traversal truncation and a real path proof

**Raised by:** Codex (C-027 Q3 implementation against the shipped EA-0005
contract).
**Severity:** blocking within Q3 - the Accepted interface cannot represent two
claims Q3 is required to make.

**Problem 1.** EA-0030 requires `dependency_paths` to propagate traversal
truncation but declares `-> list[Path]`. EA-0005 deliberately carries
truncation on `ImpactResult` and `Subgraph`, not on each `Path`. Returning the
bare list discards whether the traversal was complete, so an empty bounded
result is indistinguishable from a proved empty graph.

**Problem 2.** `ReachabilitySignal.path_ref` is required for transitive reach,
but EA-0005 `Path` has no id and no path store. Minting an arbitrary string
would cite a record that cannot be resolved or checked. The exact path must
travel with the signal, and its reference must bind to that path rather than
merely name it.

**Resolution.** Add `DependencyPathResult = {paths, truncated}` and return it
from `dependency_paths`, directly propagating `ImpactResult.truncated`. Add the
exact EA-0005 `Path` to transitive `ReachabilitySignal`s and define `path_ref`
as the SHA-256 content address of the canonical serialized path. Model
validation requires the depth to equal `Path.length` and the content address to
match; direct, unreachable, and unknown signals cannot carry a graph path.

**Impact.** Q3-only additive model changes before any reachability record is
persisted or routed to EA-0024. EA-0030 §4/§5/§6, FR-3/4, AC-4/5, and C-027 Q3
are amended. No owner contract changes: traversal still delegates to EA-0005.

---

## ECR-0039 - evidence integrity is not attestation authenticity

**Raised by:** Codex (C-027 Q4 implementation against the shipped EA-0004
contract).
**Severity:** blocking within Q4 - the Accepted wording would allow a false
`verified` result from a capability EA-0004 explicitly does not implement.

**Problem.** EA-0030 says signature/hash verification happens "via EA-0004".
The shipped EA-0004 `verify()` contract recomputes evidence content and
hash-chain integrity only. EA-0004 D4 explicitly reserves signing and external
anchoring for a later ADR; `EvidenceRecord.signature` is nullable data and no
signature, Sigstore-bundle, publisher-key, or SLSA-verification interface
exists. Therefore `EvidenceStore.verify(...).ok` proves that AQELYN's evidence
record was not altered; it does not prove the publisher signature is authentic.

The result type compounds the gap: `ProvenanceAttestation.evidence_id` is
nullable while `ProvenanceResult.evidence_id` is required, so the mandated
`unverified` outcome cannot be represented when EA-0004 is unavailable. It also
has no structural flag distinguishing unverified/failed from trusted output.

**Resolution.** Q4 performs two explicit stages. First, any cited evidence is
tenant/object/raw-content-bound and checked by EA-0004, so valid evidence for
different attestation bytes cannot be laundered into the result. Second, a
typed, kind-specific `ProvenanceVerifier` checks attestation authenticity. No
configured verifier or a retriable verifier/backbone outage yields flagged
`unverified`; a completed
authenticity mismatch or broken cited evidence yields flagged `failed`.
Successful and failed results are appended to EA-0004 when available. A
`verified` result is invalid without recorded result evidence; `evidence_id` is
nullable only so the fail-safe unverified/failed outcomes remain representable
during an evidence outage. `basis_evidence_id` preserves the handed-in claim's
source separately from the result evidence.

No default verifier guesses from caller-supplied booleans or treats a hash-chain
pass as a signature pass. Algorithm/key/bundle implementations plug into the
typed verifier seam; until one is configured, runtime behavior is explicitly
unverified and Q5 health must expose that dependency.

**Impact.** Adds a Q4-only verifier protocol and tightens
`ProvenanceResult`; no existing persisted provenance result exists. Amends
EA-0030 §4/§5/§6, FR-6, NFR-4, AC-7/8, failure handling, and C-027 Q4. EA-0004
is unchanged: it remains the single integrity/evidence backbone and is not
misrepresented as a cryptographic attestation engine.

---

## ECR-0040 - unknown component reachability must not become a low score

**Raised by:** Codex (C-027 Q5 implementation against the shipped EA-0024
factor and store contracts).
**Severity:** blocking within Q5 - the accepted handoff cannot preserve its
load-bearing distinction through the real owner API.

**Problem 1.** EA-0030 FR-5 requires component vulnerabilities to reach EA-0024
with a `ReachabilitySignal`, and Q3 distinguishes `unknown` from
`unreachable`. EA-0024's `PriorityFactor` carries only a numeric `value`. Mapping
unknown to `0.0` makes it byte-identical to a proved unreachable/low exposure
factor and lowers the score. Refusing the whole priority would discard the
known CVSS, EPSS, threat, mission, baseline, and Trust claims. Neither outcome
preserves the actual state.

**Problem 2.** `VulnerabilityStore.query` cannot filter by affected object. Q5
would have to read a global bounded page and filter component vulnerabilities
after the limit, recreating the starvation defect prohibited by EA-0002 D8.

**Problem 3.** The accepted EA-0030 protocol omits `tenant_id` from
`component_vulns_to_prioritization` and does not declare its required risk and
remediation methods, although FR-10/11 and Q5 require those owner delegations.
The implementation cannot make the reads tenant-scoped or expose the required
capabilities through that interface as written.

**Resolution.** Add `PriorityFactor.status: Literal["known", "unknown"]`,
defaulting to `known` for backward compatibility. Unknown factors remain in the
factor payload and EA-0020 derivation with their source, reason, configured raw
weight, and `status="unknown"`, but receive zero normalized weight; known
weights are renormalized. This makes missing reachability visible without
rewarding it as low exposure.

> ⚠️ **AMENDED — do not implement the renormalization clause as written.** "Known weights
> are renormalized" was the accepted decision, and `vuln` implemented it literally; it hands
> an excluded factor's weight to the survivors, so a finding with one known factor scored
> `90.0` and outranked the only KEV-confirmed exploited vulnerability. **ECR-0082** replaces
> the denominator with every configured weight. **ECR-0083** adds the separate typed
> uncertainty surcharge, because a zero-contribution unknown is conservative only on a
> higher-is-favourable scale and `vuln` runs the other way. The rest of this Resolution — the
> typed `known|unknown` factor, the retained source/reason/raw weight, `exposure_override`,
> `asset_ref_id`, and the EA-0030 interface changes — stands unchanged. Add an optional, owner-typed
`exposure_override` to EA-0024 `prioritize` so EA-0030 supplies the exact Q3
result without a second scorer. Add `asset_ref_id` to the vulnerability-store
query and apply it before `limit` in both backends. Add explicit `tenant_id` to
the component-vulnerability route and declare the EA-0013 risk and EA-0008
proposal methods in EA-0030's interface.

**Impact.** Additive owner-contract changes. Existing EA-0024 callers and
factors retain `known` behavior and their scores. Q5 tests drive the real
EA-0024 engine and inspect the resulting replayable finding, proving an unknown
reach factor remains unknown and contributes neither a favorable zero nor an
invented value. Both vulnerability stores prove tenant- and asset-scoped
filtering.

---

## ECR-0041 - make DSPM owner handoffs and unknown states connectable

**Raised by:** Codex (EA-0031 pre-implementation contract verification).
**Severity:** blocking before C-028 - the accepted sandbox draft named an
EA-0023 type that does not exist, could not carry sensitivity into the real
scorer, and left privacy and completeness guarantees representable only in
prose.

**Problem 1 - the exposure seam was imaginary.** The draft routed a
`public_storage` `SurfaceFacet` to EA-0023. Shipped EA-0023 defines
neither `SurfaceFacet` nor a facet taxonomy. Its real intake is
`KnownSurfaceSource -> KnownSurfaceRecord -> ExposureRecord`.

**Problem 2 - sensitivity disappeared at the scoring boundary.**
`KnownSurfaceRecord.classification` reaches `AttackSurfaceAsset`, but
`analyze_exposure` does not carry it into `ExposureRecord`.
`score_exposure` derives impact from reachability alone. Merely passing a
classification string therefore cannot make a medical-data store score
differently from a non-sensitive store, while a DSPM-local final score would
create the second exposure scorer the spec forbids.

**Problem 3 - unknown and privacy were not structural.** Generic `location`,
`schema`, and `sampled_signals` dictionaries could retain raw sensitive
values. `FieldClassification` had no mandatory flag/status relationship,
and `DataExposure.sensitivity` could not represent the required
reachable-but-unclassified gap. A limit-only store query also repeated the
pre-ECR-0030 capped-without-signal contract.

**Problem 4 - delegation signatures were not tenant-complete.** The draft's
access, compliance, and finding methods omitted explicit tenant scope, and
"data access via EA-0011" did not say how a store maps to the identity-centric
shipped API.

**Problem 5 - surface identity and scoring identity were conflated.** The draft
promised to replace an EA-0025 inventory placeholder but keyed the DSPM row on
`DataAsset.object_id` (`obj_`). The shipped `InventoryKnownSurfaceSource` keys
that placeholder on the inventory id (`ast_`), so one store would produce two
rows and the stronger evidenced row could not supersede the weaker one. Simply
switching `ref_id` to `ast_` was also insufficient because shipped EA-0023
requires an `obj_` subject for Mission, Risk, correlation, and findings.

**Resolution.**

1. DSPM ships a store-backed `DataStoreKnownSurfaceSource` that composes
   with the existing source, preserves upstream records, replaces only the same
   object placeholder, pages to exhaustion with repeated-cursor protection, and
   fails instead of serving a partial source. It keys the row on
   `DataAsset.inventory_ref` and carries `DataAsset.object_id` separately.
2. EA-0023 gains an optional `ExposureImpactContext` on the
   exposure/scoring path. A known context carries a unit factor,
   source/evidence, and reason; EA-0023 applies it to the owner risk seed and
   binds it into the replayable derivation. Existing callers without a context
   retain existing behavior. Unknown context has no numeric factor and cannot
   be scored as zero; DSPM records a flagged, unscored classification gap.
   The existing `ExposureConfigInvalid` is the refusal error. Postgres adds a
   migration-safe nullable JSONB column and explicit write/read mappings so the
   context cannot disappear outside the in-memory backend.
3. Descriptor metadata becomes typed and `extra="forbid"`: field
   names/types, detector refs/counts, tags, and evidence refs only. No raw
   value/content/sample field exists. Classification and exposure models use
   semantic states with validators; unknown/conflict is flagged and cannot
   become public.
4. DSPMStore adopts EA-0002 D8 cursor semantics from its first persistence
   ticket. Assessment coverage is complete/truncated/pending.
5. Store-specific access starts from evidenced identity claims in the handed-in
   descriptor, then calls the real EA-0011 `access_paths` and
   `analyze_risk` APIs. No claim or retriable outage is pending, not a
   known-empty access result. All owner calls carry explicit tenant scope.
6. Compliance delegates to EA-0010 assessment. Risk consumes evidence-backed
   Findings through EA-0013's existing finding path; no new `SignalKind` is
   added.
7. EA-0023 `AssetRef` additively separates surface identity (`ref_id`) from an
   optional EA-0002 scoring subject (`object_id`). Existing callers remain
   unchanged; inventory-keyed adapters must supply the `obj_` subject, and the
   scorer refuses when it is absent or invalid.

**Impact.** EA-0031 and C-028 are rewritten before implementation. EA-0023
receives one additive model field/argument plus replay and monotonicity tests in
C-028 P3; its Postgres DDL/mappings persist that field, and its `AssetRef`
receives an optional scoring subject. Current callers and scores are unchanged
when no context is supplied. EA-0031 typed ids are registered in the canonical
`PREFIXES` registry during P1.
EA-0019's taxonomy and EA-0011's APIs are reused without modification. The
shared posture-base decision remains ECR-0032 Proposed and outside C-028.

---

## ECR-0042 - P4 findings require a durable assessment read path

**Raised by:** Codex (C-028 P4 implementation against the Accepted EA-0031
interface).
**Severity:** blocking within P4 - the declared method cannot be implemented
durably from the declared store protocol.

**Problem.** `exposures_to_findings(assessment_id, ...)` accepts only an id, but
the Accepted `DSPMStore` can write assessments and exposures and cannot read
either one. An engine-local cache would make the method fail after restart and
would bypass tenant-scoped persistence. The gap is sharper when an assessment
carries no material ids: returning an empty finding list would mean either
"owner analysis found nothing" or "owner analysis never ran".

**Resolution.** Add tenant-scoped `get_assessment` and `get_exposure` methods to
both stores. P4 reads the immutable assessment, refuses pending or truncated
coverage, and loads every cited exposure. When a complete assessment has no
material ids, it re-runs that assessment's scope through the real EA-0023 owner
path before returning an empty result. Findings remain the only EA-0013 handoff,
and remediation remains an EA-0008 proposal.

**Impact.** Additive protocol and implementation methods over existing tables;
no schema migration. The Postgres and in-memory implementations share
tenant-isolation and immutable-read tests. EA-0031 section 5/6.3 and FR-12 plus
C-028 P4 are amended.

---

## ECR-0043 - realize IS-032 without a credential lake or duplicate owners

**Raised by:** EA-0032 pre-implementation verification against the archive,
shipped contracts, and the standing spec-author rules.
**Severity:** blocking before C-029 - the archive's literal shape would retain
sensitive material, duplicate existing capability owners, and conflate evidence
integrity with certificate authenticity.

**Problem.** IS-032 asks for continuous secret discovery plus dedicated
inventory, exposure, compliance, and risk engines. In shipped AQELYN, collection
is a gated connector concern; EA-0025, EA-0023, EA-0010, and EA-0013 already own
the latter capabilities. A secrets engine that accepts or stores credential or
private-key values would become the estate's highest-value target. The archive
also uses certificate verification language that could be misimplemented by
treating EA-0004 hash-chain integrity as signer authenticity, despite EA-0004 D4
and ECR-0039.

**Resolution.**

1. EA-0032 accepts handed-in, typed descriptors containing upstream-generated
   one-way fingerprints, typed locations, source metadata, and evidence refs.
   It has no scan/network/credential surface. Strict recursive models make raw
   secret/private-key values unconstructible and refuse value-bearing input.
2. Secret, key, and certificate records are EA-0002 objects registered through
   EA-0025. Exposure uses the real EA-0023 `KnownSurfaceSource ->
   KnownSurfaceRecord` plus `ExposureImpactContext` seam; compliance delegates
   to EA-0010; risk uses evidence-backed findings through EA-0013. No second
   owner or new `SignalKind` is created.
3. Expiry, strength, rotation, chain, revocation, integrity, and authenticity
   are semantic tri-state lifecycle values. Unknown is the default and never
   contributes a favourable value. Assessment coverage is
   pending/complete/truncated, not a boolean.
4. Verification is two-stage: EA-0004 evidence integrity first, then a typed
   certificate-authenticity verifier supplied by a trusted adapter. Results are
   separate and evidence-backed.
5. Rotation/revocation is a `requires_approval=True` EA-0008 proposal bound to
   its non-automatic source finding. EA-0032 has no execution path.
6. The new store adopts D8 cursor semantics and explicit work budgets. Health
   probes are tenant-scoped and exercised across both backends and tenant modes.

**Impact.** EA-0032 is implemented under `src/aqelyn/secrets/` through C-029.
New prefixes avoid the existing EA-0011 `cert` prefix; EA-0019's `secret`
classification remains unchanged. ECR-0034 remains Proposed and unresolved:
EA-0032 does not treat EA-0025's capped inventory report as exhaustive and does
not claim to fix that owner defect.

---

## ECR-0044 - distinguish credential sensitivity from data sensitivity

**Raised by:** Claude Code (EA-0032 pre-implementation review against the
shipped EA-0023 type contract).
**Severity:** blocking before C-029 - the Accepted draft names a real owner seam
that cannot represent the semantic input it asks EA-0032 to supply.

**Problem.** EA-0032 section 6.4 requires a credential-sensitivity
`ExposureImpactContext`, but shipped EA-0023 declares
`ExposureImpactKind = Literal["data_sensitivity"]`. Relabelling crypto
criticality as `data_sensitivity` would make the handoff constructible at the
cost of a false provenance label. EA-0023 pins the complete impact context into
its replayable derivation, so the false label would become a durable audit fact
and consumers could not distinguish EA-0031 data classification from EA-0032
credential criticality.

**Resolution.** EA-0023 additively accepts
`credential_sensitivity` alongside `data_sensitivity`.
`ExposureImpactContext.kind` keeps `data_sensitivity` as its default, preserving
every existing DSPM and omitted-kind caller. EA-0032 MUST pass
`kind="credential_sensitivity"` explicitly; the kind, factor, source,
evidence, and reason are pinned and replay-validated together. C-029 W4 owns
the type change and proves the existing default path is unchanged.

The adjacent EA-0032 boundaries are made explicit at the same pre-build point:
value rejection examines mapping field names, not legitimate enum/string
values such as `SecretKind="private_key"`; the existing typed-id prefix `cert`
does not prohibit EA-0023's semantic `AssetRef.kind="cert"`; and
`propose_rotation` compares the loaded finding's tenant to its explicit tenant
scope before proposing the finding-bound run.

**Impact.** Additive Literal expansion only. `impact_context` is already stored
as JSONB, so no DDL migration is required. EA-0023 gains compatibility and
semantic-kind acceptance tests; EA-0032/C-029 gain an explicit producer test.
Existing omitted-kind callers retain byte-identical scoring and derivation
semantics.

---

## ECR-0045 - make crypto reconciliation and lifecycle inputs durable

**Raised by:** Codex (C-029 W2 implementation against the Accepted EA-0032
type/store contract).
**Severity:** blocking within W2 - the declared behavior cannot be represented
or reconstructed from the declared records.

**Problem.** EA-0032 requires W2 to reconcile disagreeing source claims through
EA-0006 and retain the conflict, but the Accepted `SecretAsset`,
`CryptographicKey`, and `CertificateAsset` carry only the selected source and
have no conflict field. The store protocol also has no stable fingerprint read,
so re-ingest cannot reliably locate the prior claim without an unbounded scan.
Separately, `CryptographicKeyDescriptor.last_rotated_at` and the key/certificate
observation times disappear from their domain records, leaving W3 unable to
reproduce rotation age or source ordering after restart.

**Resolution.** Add strict, value-free `SecretClaim`, `KeyClaim`, and
`CertificateClaim` values plus evidence-backed `CryptoConflictCandidate` and
`CryptoClaimConflict` records. Every crypto asset retains its conflict history;
resolved conflicts name the winning source and evidence, while equal-reliability
conflicts remain explicitly unresolved. Add `last_rotated_at` and
`observed_at` to the relevant domain records. Add tenant-scoped
`get_asset_by_fingerprint(kind, fingerprint, tenant_id)` to `CryptoStore`, with
one immutable identity mapping per tenant/kind/fingerprint and append-only asset
revisions behind that stable domain id.

**Impact.** C-029 W2 owns the additive model/protocol fields and both persistence
implementations. The Postgres schema is new in W2, so no migration of shipped
crypto data is required. The value-rejection gate applies recursively to claim
and conflict records; conflicts can retain only typed metadata, never secret or
private-key material. W3 consumes the now-durable observation/rotation inputs.

---

## ECR-0046 - bind crypto evidence and authenticity results to their input

**Raised by:** Codex (C-029 W3 implementation against the Accepted two-stage
verification contract).
**Severity:** blocking within W3 - an unrelated same-source evidence record or
cached verifier result could otherwise be laundered into a known lifecycle
state.

**Problem.** W2 checks the cited EA-0004 record's tenant, source, and integrity,
but does not require the record to name the descriptor fingerprint. Two
certificates reported by the same source can therefore cite each other's
byte-valid evidence. W3 additionally declares `AuthenticityCheck` as only
`{status, reason}`. A buggy or cached adapter can return a valid result produced
for another certificate, and the engine has no field with which to detect the
mismatch. Persisting that result would turn the wrong binding into durable
audit evidence.

**Resolution.** Descriptor evidence MUST carry
`content["fingerprint"] == descriptor.fingerprint`; ingest and lifecycle reads
refuse missing or mismatched bindings. `AuthenticityCheck` additively carries
`certificate_fingerprint` and `basis_evidence_id`. W3 accepts a verifier result
only when both equal the certificate being assessed and its integrity-checked
evidence. The separately persisted EA-0004 verification result records the same
pair, and a known authenticity state cites that result evidence.

**Impact.** C-029 W3 owns the additive strict-model fields, W2 evidence-binding
guard, result-evidence binding, and adversarial unrelated-input tests. No schema
migration is required: crypto assets and assessment records are JSONB, while
`AuthenticityCheck` is an adapter result rather than a stored table row. No
secret or private-key value is introduced; the only added material is a one-way
fingerprint and an evidence id.

---

## ECR-0047 - represent per-asset missing evidence in batch coverage

**Raised by:** Claude Code (post-C-029 W3 review against EA-0032 S7).
**Severity:** blocking follow-up before W4 - the Accepted failure rule and
semantic coverage invariant contradict each other during tenant assessment.

**Problem.** EA-0032 section 11 says missing evidence refuses, while S7 says an
assessment reports semantic `pending|complete|truncated` coverage. The shipped
single-asset behavior correctly raises `EvidenceNotFound`, but `assess()` uses
the same path and aborts the entire tenant run when one previously valid basis
record has been legitimately purged. No assessment is emitted, so operators
cannot distinguish "nothing was assessed" from "all but this asset was
assessed".

**Resolution.** Keep `assess_certificate()` and `assess_key()` strict: a missing
basis record still raises. During bounded batch `assess()`, catch only
`EvidenceNotFound` per asset, persist that asset's lifecycle as explicit
`unknown` with the missing evidence id named in the reason, count it in
`unknown_lifecycle`, and continue. Tamper, cross-tenant mismatch, and programming
errors still abort. Complete/truncated continues to describe source coverage;
unknown lifecycle describes the result quality inside that coverage.

**Impact.** Additive W4 follow-up over the existing JSONB asset revisions; no
schema migration. EA-0032 FR-6/FR-11, failure handling, and C-029 AC-19 are
amended. The assessment evidence lists every evaluated asset and the unknown
count, so absence is visible rather than converted to a favourable result.

---

## ECR-0048 - persist scored owner exposure before crypto findings cite it

**Raised by:** Codex (C-029 W4 implementation against the shipped EA-0023
store/engine contract).
**Severity:** blocking within W4 - the Accepted handoff cannot make a replayable
scored owner record durable without duplicating owner logic.

**Problem.** EA-0032 must delegate scoring and findings to EA-0023. Shipped
`analyze_exposure()` persists an unscored record, while `score_exposure()`
returns a scored copy that cannot replace that immutable id. EA-0032 has no
owner method to atomically persist the scored form and no tenant-scoped engine
read with which to reconstruct it for a later finding. Citing the unscored id
would lose ECR-0044's replay-pinned `credential_sensitivity`; rebuilding a
finding from the transient result would create a second severity/scoring path.

**Resolution.** EA-0023 additively exposes
`analyze_scored_exposure(asset_ref, impact_context, tenant_id)`: derive from the
real `KnownSurfaceSource`, leave unknown reachability unscored, otherwise score
through the existing EA-0006/0007/0013 composition, and persist exactly that
validated result once. Add tenant-scoped `get_exposure()` and include the pinned
impact context in the owner finding's expert detail. EA-0032 loads that record,
validates its crypto asset/context binding, and delegates finding creation back
to EA-0023.

**Impact.** Additive owner methods and finding detail only; existing
`analyze_exposure()` and `score_exposure()` behavior is unchanged. No DDL change:
EA-0023 already persists `impact_context` and derivation. C-029 W4 proves the
record round-trips on both stores, omitted-context v1 scoring remains unchanged,
and the finding path uses no new `SignalKind` or crypto-local scorer.

---

## ECR-0049 - distinguish identity sensitivity from other exposure impact

**Raised by:** EA-0033 pre-implementation verification against the shipped
EA-0023 exposure-impact contract and spec-author rule 15.
**Status:** Accepted - implemented in C-030 G5, not an earlier types ticket.
**Severity:** blocking within G5 - the Accepted identity exposure handoff cannot
name its semantic input using the currently shipped impact kinds.

**Problem.** EA-0023 currently accepts `data_sensitivity` and
`credential_sensitivity`. EA-0033 needs to express the sensitivity of an
identity account's control state. Relabelling that input as either existing kind
would make the handoff constructible by recording a false provenance label.
Because EA-0023 pins the complete `ExposureImpactContext` into its replayable
derivation, the false label would become a durable audit fact.

**Resolution.** EA-0023 additively accepts `identity_sensitivity` while keeping
`data_sensitivity` as the omitted-kind default. EA-0033 MUST pass
`kind="identity_sensitivity"` explicitly, and EA-0023 MUST replay-pin the kind,
factor, source, evidence, and reason together. Per spec-author rule 15, the
widening lands in C-030 G5, the same ticket that first constructs an identity
impact context; no earlier C-030 type may depend on it.

**Impact.** Additive Literal expansion only. Existing DSPM and crypto callers
retain their current default and explicit kinds. `impact_context` is already a
JSONB field without a database kind constraint, so no DDL migration is needed.
G5 proves the existing default remains unchanged and that identity sensitivity
survives owner scoring, persistence, and derivation replay.

---

## ECR-0050 - reuse the existing identity-not-found taxonomy

**Raised by:** Codex during C-030 G1 verification against the shipped error
registry and CONVENTIONS §9.
**Status:** Accepted - required before registering G1's error contributions.
**Severity:** blocking within G1 - one error named as an EA-0033 contribution
already has a platform owner.

**Problem.** The Accepted EA-0033 §9 lists `IdentityNotFound` as a new ISPM error.
Shipped `conventions.errors` and CONVENTIONS §9 already assign that exact stable
code to EA-0027, where identity-threat stores and engines raise it. Defining it
again would give one public code two class owners; changing its spelling would
create two answers to the same missing-identity condition.

**Resolution.** EA-0033 reuses the existing `IdentityNotFound` class. ISPM adds
only `ISPMConfigInvalid`, `PostureScoreNotReplayable`, and
`IdentityBaselineNotFound`. G1 tests assert both the reused code and the three
new contributions through `ALL_ERROR_CODES` and CONVENTIONS §9.

**Impact.** Taxonomy-only correction; no shipped behavior or error code changes.
The existing EA-0027 owner remains authoritative, and ISPM callers receive the
same stable missing-identity code used elsewhere in the platform.

---

## ECR-0051 - persist the unknown-identity warning on the normalized record

**Raised by:** Codex during C-030 G2 construction against the Accepted D1 model.
**Status:** Accepted - implemented with the first normalized-identity persistence.
**Severity:** blocking within G2 - the required fail-safe state was not representable
through the ISPM store contract.

**Problem.** EA-0033 requires an unmatched identity kind to become `unknown` and
be flagged. The Accepted `NormalizedIdentity` type carried the kind but no flag.
Writing only an EA-0002 object label would make the warning disappear whenever a
caller read the same identity through `ISPMStore`, allowing one persisted view to
say `unknown` without carrying the required warning.

**Resolution.** Add `NormalizedIdentity.flagged: bool = false` and make
`identity_kind="unknown"` with `flagged=false` unconstructible. Unresolved
reconciliation conflicts likewise require the flag. G2 writes the same state to
the EA-0002 label and the normalized record, and both stores validate the model on
write and read.

**Impact.** Additive JSONB record field only; the ISPM revision table has no
column or check constraint for the flag, so no DDL migration is required. Known
G1 records retain the false default. G2 acceptance constructs the forbidden state
and verifies unknown classification stays flagged on both backends.

---

## ECR-0052 - persist the exact assessment-to-finding handoff

**Raised by:** Codex during C-030 G5 construction against the Accepted ISPM
assessment and EA-0011 finding interfaces.
**Status:** Accepted - required before the first durable assessment-to-finding
route.
**Severity:** blocking within G5 - the Accepted handoff could not preserve
historical identity or enterprise tenant scope.

**Problem.** `posture_to_findings(assessment_id)` must route the exact owner
risks pinned into the replayable posture scores produced by that assessment.
The Accepted `ISPMAssessment` carried only counts, so a later call could not
identify those scores without recomputing against current state. The Accepted
`ISPMStore` also omitted assessment persistence entirely. Separately, shipped
EA-0011 `risks_to_findings` hardcoded `tenant_id=None` on both its evidence and
finding rows, so an enterprise-scoped ISPM assessment could not use the real
owner path.

**Resolution.** `ISPMAssessment` additively carries unique typed `score_ids`,
with `scored == len(score_ids)` enforced structurally. Both stores persist and
read assessments append-only under explicit tenant scope. ISPM loads those exact
scores and routes their pinned `AccessRisk` records. EA-0011
`risks_to_findings` additively accepts `tenant_id: str | None = None` and applies
it to the owner evidence and finding; existing callers that omit it retain local
behavior. ISPM's public finding operation requires explicit tenant scope.

**Impact.** One new append-only JSONB assessment table, plus additive optional
parameters and a JSONB model field. No existing posture-score, IAG finding, or
local call shape changes. C-030's final owner-approved five-ticket plan combines
the former bundle G5/G6 sequencing into one G5 because the exposure context,
durable assessment, finding binding, and service wiring ship atomically.

---

## ECR-0053 - realize IS-034 as distributed conformance, not a second identity module

**Raised by:** EA-0034 pre-implementation verification against the IS-034
archive, shipped owner contracts, and ECR-0015.
**Status:** Accepted - C-031 shipped.
**Severity:** architectural - building the archive's named engine would fork
multiple existing capability owners while appearing net-new under a literal
event/type check.

**Problem.** IS-034 names a Machine Identity and Non-Human Identity Governance
Engine. Its 17 declared PascalCase events and machine/NHI labels have zero exact
matches in `src/aqelyn`, but its capabilities do not: EA-0033 already normalizes
and scores service/machine/application/federated/temporary identities; EA-0011
owns access risk and certification; EA-0025 owns inventory ownership and asset
lifecycle; EA-0032 owns secrets, keys, certificates, and rotation; EA-0002 and
EA-0005 own relationships and traversal; trust, policy, recommendation,
workflow, and reporting likewise have established owners.

This differs from IS-026 only in distribution. IS-026 restated one owner under
the same event name. IS-034 renames a set of existing capabilities for a new
subject scope, so the duplication appears only after the components are mapped
together. Building the archive literally would create two identity repositories,
two posture scores, duplicate lifecycle and crypto governance, another graph
vocabulary, and renamed duplicate events.

**Resolution.** Do not build an EA-0034 runtime module. There SHALL be no
`src/aqelyn/machine_identity/`, `nhi_engine`, NHI store, NHI posture score, or
`aqelyn.nhi.*` namespace. C-031 first verifies conformance against shipped code,
then makes only three additive owner-scoped enhancements:

1. EA-0033 carries a strict evidence-backed ownership claim into EA-0025's
   existing `Ownership`/reconciliation path and pins the exact handoff refs.
2. EA-0033 accepts narrow value-free identity-to-credential/workload bindings,
   persists them through EA-0002, and delegates traversal to EA-0005. EA-0004
   integrity does not establish binding authenticity; confidence remains
   EA-0006's, and missing/tampered evidence writes nothing favourable.
3. Lifecycle handling begins with an explicit state-to-owner map. EA-0025 keeps
   asset lifecycle, EA-0032 keeps credential rotation, and only irreducibly
   identity-specific states may gain narrow append-only EA-0033 history. Source
   silence is `unreported`, never suspended, revoked, archived, deleted, or safe.

Existing semantic events remain with their owners. A genuinely new lifecycle
event, if the conformance proof requires one, uses the owning `aqelyn.ispm.*`,
`aqelyn.inventory.*`, or `aqelyn.crypto.*` namespace and is never re-emitted as
NHI. Connector orchestration, scheduling, provider credentials, and direct
provisioning/revocation remain out of scope; actions use a finding-bound EA-0008
proposal. C-031 also inherits ECR-0034 and may not claim a capped inventory is
the complete machine-identity estate.

**Generalization of ECR-0015.** Compare capabilities and semantic events, not
only literal names. Zero literal collisions are necessary but insufficient
evidence that a module is net-new when an archive renames an existing capability
for a cloud, SaaS, data, or machine-identity scope.

**Impact.** Documentation plus additive changes inside existing owner packages;
no new runtime module or service. `IS-034_Conformance_Analysis.md` records the
mapping and **C-031 H1-H4** owns the proof and genuine remainder. Any failed
conformance row becomes an owner repair ticket, never permission to create a
second authority. ECR-0032 remains Proposed and IS-034 must not become a fifth
posture-normalization implementation while that decision is open.

---

## ECR-0054 - IS-035 renames EA-0032; no second secrets engine

**Raised by:** planning (IS-035 spec pass), on the reviewer's verified handover.
**Status:** Accepted - C-032 shipped.
**Severity:** architectural - literal construction duplicates a shipped engine wholesale.

**Finding.** IS-035 ("Secrets, Keys & Certificate Lifecycle Governance Engine") is
**EA-0032 renamed**. The ECR-0015 check against shipped `src/` returns EA-0032 as
the owner of every capability the archive requests:

```
secret_asset / cryptographic_key / x509_certificate : 5 each   (EA-0032)
rotation 28 · revocation 19 · expiry 17 · propose_rotation 3   (EA-0032 lifecycle)
sct / cky / x509 prefixes : 8 each · cas                       (EA-0032 PREFIXES)
secrets_engine 16 · aqelyn.crypto.* 4 events                   (EA-0032 service/events)
renewal 0 · kms 0 · certificate.*lifecycle 0                   <- net-new VOCABULARY only
```

`renewal` and `kms` are words EA-0032 does not use - not capabilities it lacks.
The master's headline requirement, **no plaintext secret ever stored**, is not a
gap: it is already structural in EA-0032 (`_ValueFreeModel`, `extra="forbid"`),
proven under `python -O`. Re-implementing it would weaken it.

**Third distributed-conformance case** (IS-026 -> EA-0012; IS-034 -> several
owners; IS-035 -> EA-0032), and the most concentrated of the three.

**Why building it is harmful.** A second secrets store, a second crypto object
model, duplicate lifecycle logic, duplicate `sct`/`cky`/`x509` prefixes, a second
`secrets_engine`, and a renamed `aqelyn.crypto.*` namespace - doubling credential
findings and inflating EA-0013/EA-0022 counts. Sharper than the identity case:
**two engines disagreeing about whether a certificate is expired or a key revoked
is an outage or a breach**, and the value-free guarantee would exist in two places
with only one of them proven.

**Resolution proposed.**
1. Mark **IS-035 conformant via EA-0032**, evidenced by
   `IS-035_Conformance_Analysis.md` and verified against shipped code with
   **real-engine** exercises (C-032 J1), not spies or grep.
2. Realize the **one genuine gap** - a deterministic per-credential **governance
   score** (EA-0032 has none today; `CryptoAssessment` carries counts) - as an
   **additive enhancement inside `src/aqelyn/secrets/`**, following the EA-0033
   ISPM score rules exactly: no second scorer, `known_only x coverage_adjustment`
   so unknown never becomes present, replay-or-reject against the real scorer.
3. Treat **storage-safety classification** and **credential ownership handoff to
   EA-0025** as owner-gated options.
4. **Forbid** a second secrets engine, store, crypto model, duplicate prefix,
   service, or event namespace. A governance-score record needs a new
   collision-free prefix; its event is additive within `aqelyn.crypto.*` and
   re-emits nothing.
5. **Do not build the archive's 13-state lifecycle machines.** EA-0032's tri-state
   lifecycle fields are the shipped reality and are sufficient; a state machine
   plus transition-event store would add a second lifecycle authority for crypto
   assets - the failure ECR-0053 rejected for identities.

**Two hazards added at spec stage** (not in the archive, and specific to scoring a
credential):
- **A score must not average away a known exposure.** Active critical exposure is
  an unsuppressable flag on the score record, named in the statement - EA-0022 S5's
  *no green aggregate over an unreported fire*, one layer down.
- **"Well-governed" is not "safe".** The score measures governance hygiene, not
  compromise state; a perfectly rotated, owned, compliant credential that has
  leaked is still compromised, and the statement must say what the number means.

**Impact.** No new package or service; EA-0032 extended additively only. IS-035's
intent is met at IS-035's turn without forking the platform's credential
authority.

## ECR-0055 - IS-036: template archive; conformance via EA-0018 + EA-0008; no autonomous execution

**Raised by:** planning (IS-036 spec pass), on the reviewer's verified handover.
**Status:** Accepted - C-033 shipped the conformance work; K2 remains an optional owner-gated enhancement.
**Severity:** safety-critical - a plausible-sounding spec here could breach the
platform's foundational boundary.

**Finding A - the archive master is a near-empty template.** Twelve placeholder
objectives (*"...objective 1"* through *"...objective 12"*), a grammatically
broken purpose sentence, boilerplate sections, and **no components, interfaces,
requirements, lifecycle, or acceptance criteria.** There is nothing to reconcile a
capability against.

*Consequence:* for a real master, silence about a boundary is ambiguous; for a
template, **there is no specification at all**, and any requirement written from
its headings is **invented by the drafter wearing the archive's authority.**
Nothing in the IS-036 analysis is derived from the template - the conformance is
grounded in shipped code alone. EA-0036 also opens a new archive batch
(`EA-0036_EA-0050`); **"is this archive real content?" is now the first check per
module**, before the ECR-0015 capability check.

**Finding B - the capability ships.** `Playbook 202 · propose 179 ·
requires_approval 47 · eligibility 32 · WorkflowEngine 23` (EA-0008);
`response.*campaign 109 · aqelyn.response 40` (EA-0018). Remediation orchestration
is **EA-0018 `ResponseOrchestrationEngine`** over **EA-0008 `WorkflowEngine`**, the
platform's only actor. Fourth distributed-conformance case (IS-026/034/035/036).

**Finding C - "Autonomous" is a landmine, not a feature request.** `autonomous` = 0
hits in `src/` **by design**: every engine is detect-and-propose, and
eligibility-`none` findings are structurally unexecutable in `gating.py`. The only
legitimate reading of the title word is *the orchestration/evidence/decision flow
is automated* - **never execution without a human approving via
`WorkflowEngine.approve`.**

The risk is not an obviously-wrong spec but a **reasonable-sounding** one. Six
mechanisms are named and forbidden in the analysis (§3.1): policy auto-approval
(EA-0009 authorizes, it does not approve); pre-approved/standing approval;
a non-human approver; break-glass bypass; batch approval; and `advance()`
executing a phase without its own gates. Plus: a **rollback is an action**, and a
**"dry run" that touches real systems is not a dry run**. Note also that bounded
autonomy **already exists and is already gated** - EA-0018's
`max_effect: read_only|reversible` - so no new mechanism is needed, and a new one
would sit outside the gate that makes the existing one safe.

**Resolution proposed.**
1. Mark **IS-036 conformant** via EA-0018 + EA-0008, evidenced by **real-engine**
   exercises: `plan_campaign`->`advance` sequences proposals without executing;
   `propose`->`approve`->`execute` executes only after approval; an
   eligibility-`none` run is **refused**, including under `python -O`.
2. **Forbid** a second orchestration engine, workflow actor, or campaign model -
   no `autonomous_remediation/` or `remediation_orchestration/` package, no second
   `*_engine` service, no `aqelyn.autonomy.*` namespace, and **no execution path
   that is not EA-0008-gated and human-approved.**
3. **Claim no gap.** The archive specifies none and none was invented. The burden
   is on any future proposal to justify net-new capability against shipped code.
4. **One owner-gated candidate, not assumed:** a read-only remediation-plan view
   composing *proposed* (never executed) runs and campaigns into an
   evidence-backed replayable record. **Do not build without an explicit owner
   decision** (C-033 K2).

**Why duplication here is worse than IS-034/IS-035.** Those would have produced
**disagreement**; this would produce **action**. A second orchestration path is the
likeliest place for an un-gated execution route to appear, because orchestration is
exactly where *"just advance the campaign"* feels like coordination rather than
acting. **EA-0008's status as the platform's only actor is AQELYN's foundational
safety property**, and a module titled "Autonomous" is where it would be lost.

**Expected outcome.** C-033 delivering a conformance record and **no production
code** is the correct result, not an under-delivery.

## ECR-0056 - K1 closes non-human approval and ungated rollback in EA-0008

**Raised by:** Codex during C-033 K1 real-engine conformance verification.
**Status:** Resolved by C-033 K1.
**Severity:** safety-critical - two states forbidden by ECR-0055 were constructible
through the platform's only action engine.

**Finding.** K1 did not initially prove the ECR-0055 human gate:

1. `Approval.approver` accepts every canonical `ActorRef` type, and
   `WorkflowEngine.approve` accepted `system`, `connector`, and `agent` actors.
   The approval was run-scoped and attributed, but it did not establish a human
   decision.
2. `WorkflowEngine.rollback` called `ActionHandler.rollback` directly. It wrote
   evidence after the call, but required neither a fresh approval for the undo
   nor the action's capability authorization. A rollback is still an external
   action; audit after execution is not an execution gate.

These are failed conformance rows, not permission to build a second
orchestrator. They belong to EA-0008, the existing owner.

**Resolution proposed.**

1. `WorkflowEngine.approve` and the shared execution gate refuse any matching
   approval whose approver is not `ActorRef(actor_type="user")`. Historical
   records remain parseable; a non-human record simply cannot authorize new
   execution.
2. `rollback(..., approval=...)` requires a human approval naming exactly the
   reversible steps, granted after the run's latest action result. Before
   recording that approval or invoking any handler, the engine preflights every
   rollback step through the original capability authorizer and shared gate.
3. K1 proves both refusals against the real engine on both stores and tenant
   modes, including the eligibility-`none` boundary under `python -O`.

**Impact.** One existing owner is narrowed; no package, service, campaign model,
event namespace, or execution path is added. EA-0008's approval and rollback
contracts are amended. Existing serialized approvals remain readable because the
human requirement is enforced at authorization time rather than by making the
historical data model unparseable.

## ECR-0057 - GC-001: a central §0 guarantee-conformance suite

**Raised by:** planning, on the reviewer's guarantee-coverage audit
(`GUARANTEE_COVERAGE_READ.md`, main @a5696bf, 157 test files).
**Status:** Accepted - GC-001 shipped.

**Finding.** The hypothesis that §0 guarantees were "stated everywhere, enforced
nowhere" is **too strong**. Refusal tests mostly exist: ~16 engines cover
detect-and-propose; unknown-never-favourable is covered on every scorer that
actually models unknowns; integrity != authenticity has five independent
refusals; no-person-score and no-secret-value are **structural in the types**,
which is stronger than any test. **ECR-0056 (the workflow human gate) was the one
genuine enforced-nowhere case, and it is now fixed.**

**The real gap is decentralization.** Every guarantee is enforced by a test the
author of that module wrote. **Nothing fails when a future module omits one** -
the omission leaves no trace. So the suite's value is **future-proofing**, not
back-filling, and it is scoped accordingly: `SignalKind` closure is the thinnest
real gap (2 touchpoints against two closed literals); engine-no-execute is the
highest-value guard because its breach causes **action**, not disagreement;
integrity/no-person/no-secret stay out because they are already structural.

**Resolution proposed.** One **test-only** module, **no runtime surface**
(no package under `src/aqelyn/`, no service, event, capability, `SignalKind`, or
namespace; helpers live in `tests/`, not `conventions`), with three ACs:

1. **Engine-no-execute registry** - EA-0008 is the only production actor.
2. **`SignalKind` closure** - membership frozen **and** out-of-set kinds rejected
   at runtime.
3. **Scorer unknown-never-favourable registry** - guards future composition
   scorers using an orientation-aware assertion that unknown is strictly less
   favourable than known-good/safe; `risk/scoring.py::score_risk` is excluded
   because it is a bounded max/impact combinator with no unknown lever.

**Three design decisions that make it durable:**

- **Discovery, never declaration.** A hand-maintained registry would
  **reintroduce the exact gap the suite closes** - a module omitted from a list is
  silently unguarded. Enumeration walks the package tree; exemptions are an
  explicit allow-list with a reason per entry, because *adding* to an allow-list
  is reviewable while *omission* from a registry is invisible.
- **Invocation authority, not names or references.** AC-1 cannot grep for
  `apply`/`execute` or treat `ActionSpec` construction as execution. Five shipped
  benign sites use those method names (`cspm`/`sspm` baselines + routing delegate
  to EA-0012/EA-0025; `lake/retention.py::apply` is EA-0019's own storage
  lifecycle), and `exposure/models.py::active_reachability_action_spec` safely
  constructs a proposal-only `ActionSpec`. The test keys on a two-part
  conjunction: **direct handler invocation or alternate registry dispatch
  outside EA-0008**, and an effect on a **customer asset**. All six pass **by that
  definition, not by exemption**, while a real alternate actor fails on arrival.
- **Weakest form that catches the defect.** A central assertion stronger than
  what correct code guarantees produces **false failures**, and a suite that
  cries wolf gets disabled - leaving the *appearance* of coverage, which is
  worse than none. The scorer invariant is semantic and orientation-aware:
  unknown is less favourable than known-good/safe; its relation to known-bad
  remains a per-scorer assertion.

**Every AC ships a negative control that must FAIL** (rule 19): an alternate
registry that invokes its handler, an unregistered kind reaching the runtime
path, and a stub scorer that maps unknown to the favourable known result. A
guarantee test that only passes when the guarantee holds is untested - and per
rule 19 the control must *perform* the forbidden action, not assert about it.

**One note carried into AC-2:** a `Literal` is a **static** guarantee that `mypy`
enforces at authoring time. Data from Postgres, JSON, or a handed-in descriptor is
not type-checked, so runtime rejection is a **separate and necessary** assertion,
driven through the real ingestion path.

**Impact.** No runtime change; CI gains a suite that fails when a future module
omits a boundary. Existing per-module refusal tests remain the owners of their
local guarantees and are neither weakened nor duplicated.

## ECR-0058 - GC-002: event-namespace closure guard

**Raised by:** planning (IS-037 pass exposed the gap); owner sequenced GC-002
before C-034.
**Status:** Accepted - GC-002 shipped.

**The gap.** GC-001's three ACs are engine-no-execute, `SignalKind` closure, and
the scorer registry. **None asserts anything about event namespaces.** With **51**
`register_*_events` owner sites and ~31 live `aqelyn.<owner>.*` prefixes, minting
`aqelyn.cyber.*` for IS-037's 9 placeholder events would **pass CI silently**.

**Why this defect is worse than a duplicate engine.** Events are a **published
contract**: a duplicate engine can be deleted before release, but a **duplicate
event namespace is permanent once consumers depend on it** - and EA-0013
aggregation plus EA-0022 reporting would **double-count** one real occurrence
arriving under two vocabularies.

**Resolution proposed.** One **test-only** module in `tests/guarantees/`, mirroring
GC-001's shape and inheriting its three principles (discovery-never-declaration,
weakest-form, negative-control-per-AC), with:

- **AC-1 registered event-type closure** - enumerate from a **constructed
  runtime's** `EventTypeRegistry`; assert the set equals a **frozen golden set**.
- **AC-2 prefix ownership** - every `aqelyn.<owner>.` maps to a real shipped
  package via a derived map plus a reasoned allow-list; an unowned prefix fails.
- **AC-3** - both backends, both tenant modes, negative controls under `python -O`
  with `UnknownEventType`/`GuaranteeViolation` raised explicitly.

**Four design decisions beyond the brief.**

1. **AC-1 and AC-2 catch different defects and neither is redundant.** A *new
   prefix* (`aqelyn.cyber.exposure_detected`) is caught by **AC-2**; a *new event
   under an existing prefix* (`aqelyn.exposure.cyber_discovered`) is caught by
   **AC-1**. **Only AC-2 catches the actual IS-037 case**; AC-1 catches the subtler
   variant a future author reaches for once AC-2 blocks the obvious route.
2. **The golden set must be grouped by owner, not flat.** GC-001 froze eight
   `SignalKind` members; GC-002 freezes hundreds of event types. At that size a
   one-line addition to a flat list is **invisible in review**, the deliberate
   edit becomes a rubber stamp, and the guard degrades into a formality that still
   passes CI. Grouped, a diff reads *"`exposure` gained an event"* and keeps the
   reviewable question - *why does this owner need a new event?* - in front of the
   reviewer. **The structure is the review affordance.**
3. **Ownership is many-to-one, and derived from evidence.** The brief's two
   unresolved prefixes resolve from shipped spec evidence: **`compliance` ->
   `governance`** (EA-0010) and **`telemetry` -> `lake`** (EA-0019). The second
   carries a consequence: **EA-0019 owns two prefixes** (`aqelyn.lake.*` and
   `aqelyn.telemetry.*`), as does `objects` (`object.*`, `relationship.*`). A data
   structure assuming one prefix per package breaks on day one. `CORE_EVENTS`-
   seeded prefixes need allow-list entries recording registry-seeding as their
   reason.
4. **An orphaned prefix is a finding, never an exemption.** If AC-2 fails on
   arrival because a shipped prefix has no derivable owner, that is GC-002
   **working**. The correct response is to derive the true owner and record the
   reason, or record a real defect - **not** to add a bare exemption to go green,
   which converts a discovered defect into a permanent blind spot. Ambiguous
   ownership **fails rather than guesses**.

**Out of scope, flagged not assumed.** The registry's `validate` raises
`UnknownEventType` for an unregistered type; whether an engine can *emit* a string
that never reaches `validate` is an **emit-path** question rather than a
registration-set one, and GC-002 does not address it. For the reviewer to judge
against shipped code.

**Impact.** No runtime change. CI gains the **fourth** enforced §0 guarantee, and
**C-034 (IS-037 conformance, ECR-0059) lands mechanically protected** against
event-minting rather than reviewer-protected.

## ECR-0059 - IS-037: template stub; CAASM ships distributed; no `Cyber*` event namespace

**Raised by:** planning (IS-037 pass), on the reviewer's verified handover.
**Status:** Accepted - C-034 shipped.

**Finding A - template stub, second consecutive.** `archive/EA-0037/EA-0037_Master.md`
is 424 lines of the generic 40-section template: §012-032 **byte-identical
boilerplate**, §033 the **identical generic 12-capability matrix** every EA-0036+
archive carries, **zero module-specific requirement text**. Only the title and 9
event names are distinctive. Per the IS-036 finding, any requirement written from
these headings is **invented by the drafter wearing the archive's authority**.

**Finding B - the capability ships, distributed.** "Cyber Asset Exposure
Management" decomposes onto **EA-0025** (docstring: *"Cyber Asset Discovery &
Inventory Intelligence"*), **EA-0023** (docstring: *"Threat Exposure & Attack
Surface Management Engine"*; ships `derive_surface`, `list_known_surface`,
`reachable_paths`), **EA-0024** (prioritization; composes the reachability
`PriorityFactor`), **EA-0005** (relationships), with intake via **EA-0028/0029**.
Fifth conformance case (IS-026/034/035/036/037) and the **clearest**: two shipped
owners carry the archive's own words in their package docstrings, and the chain
assets -> exposure -> priority is **already composed**, not merely available.

**The primary trap - a parallel EVENT namespace.** The 9 `Cyber*` events appear
**0/9 in `src/`**. That is net-new **naming**, not capability - EA-0023/0024/0025
already emit these events under their own vocabularies. Minting them is subtler
than a duplicate engine and worse in one respect:

1. **Double-counting** - EA-0013 aggregation and EA-0022 reporting would see one
   real occurrence twice, inflating risk and every figure derived from it.
2. **Two vocabularies per capability** - consumers must know both, and *which one
   fired* becomes a question with no principled answer.
3. **Events are a published contract** - once consumed, retiring them is a
   breaking change. A duplicate engine can be deleted before release; **a
   duplicate event namespace is effectively permanent.**
4. **Appearance without substance** - it would describe work the owners already do
   while implying a component that does not exist.

**A quieter trap.** *"Prioritizes reduction of exploitable exposure"* reads as
action, in the same class as IS-036's "Autonomous". Prioritization is EA-0024's;
reduction is **detect-and-propose** via an EA-0008-gated action carried by a
finding's `Automation`. §0 no-autonomy is unchanged.

**Resolution proposed.**
1. Mark **IS-037 conformant** via EA-0023 + EA-0024 + EA-0025 + EA-0005
   (+ EA-0028/0029), verified against shipped code.
2. **Forbid**: no package under `src/aqelyn/`, no unified CAASM engine, **no
   `Cyber*` event namespace**, no second composer/scorer, no new `SignalKind`.
3. **Claim no gap**; none was invented. Any future proposal must show a concrete
   missing type/method against shipped EA-0023/EA-0025, reviewer-verified first.
4. **Expected outcome: an analysis and no code.**

**Enforcement note - and a gap this exposed.** This is the **first conformance
decision backed by CI rather than reviewer vigilance**: with GC-001 live, a new
package trips `test_gc_engine_discovery_complete` and a new composition scorer
trips the scorer registry, on the day it lands. GC-002 now closes the
event-namespace gap this pass exposed: minting `aqelyn.cyber.*` trips
`test_gc_negative_control_unowned_prefix`, on the day it lands.

**Batch note.** EA-0036 and EA-0037 are both stubs from the same generator. Two is
not thirteen, but it changes the default expectation for EA-0038-EA-0050. If
IS-038/039 come back identical, the honest question is whether the remainder
warrants **one batch-level decision** rather than thirteen passes - and whether the
archive has stopped being a source of requirements, leaving the tracked follow-ups
as the real backlog.

---

## ECR-0060 - EA-0038 - EA-0050: batch conformance, three dispositions

**Raised by:** claude.ai (batch analysis) - **verified and implemented by Claude Code (C-035)
at `2699006`**, during the Codex outage.
**Status:** Accepted (C-035; archive-exhaustion clause superseded by ECR-0086).
**Number:** confirmed free against this log before assignment (highest allocated was 0059,
C-034). Rule 1 discharged - the ECR-0058 collision earlier in this sequence is why the
number was carried as provisional until checked.

**Decision.** Thirteen archive masters (`EA-0038` ... `EA-0050`) are same-generator stubs:
a shared skeleton with boilerplate objectives and the generic 12-capability requirements
matrix, no module-specific requirement text in any of them. They are resolved by one
decision rather than thirteen conformance passes - but they **do not share one
disposition**:

- **A - conformant via shipped owners (eleven):** EA-0038, 0039, 0040, 0041, 0042, 0043,
  0044, 0045, 0046, 0047, 0049. Per-row evidence (package + declared EA + realizing API)
  is recorded in `EA-0038-0050_Batch_Conformance_Analysis.md` §2 and pinned by
  `test_batch_disposition_a_owners_present`.
- **B - open capability gap, not scheduled:** **EA-0048** (AI Security & Model Governance).
- **C - non-capability:** **EA-0050** (Platform Implementation Blueprint & Coding Readiness
  Baseline), classified alongside EA-0051.

**The batch replaces the analyses, not the capability map.** EA-0048 is the proof: it is
the one row where the same-generator heuristic gives the wrong answer. A batch that
skipped the map would have certified that AI security is already owned.

**EA-0048.** No shipped owner - zero hits across all 35 packages for the ownership term
set at this SHA. **EA-0020 "AI Decision Intelligence Engine" was considered and rejected:**
EA-0020 is AI used *by* AQELYN (replayable derivations over cases and claims); EA-0048
would be governance *of* customer AI/ML systems. Opposite directions, and the rule 20 shape
in a new dress - a name that looks like an owner and is not. The rejection is asserted by
`test_batch_ea0020_is_not_the_ea0048_owner` so it stays on the record.

**A recorded gap is not an approved build.** The archive names the capability and specifies
nothing about it. If it is wanted, the requirements come from the owner, not from a stub -
it would be the first module specified from intent rather than reconciled against the
archive, and that is a product decision to be made as one.

**Why the verification budget is proportionate.** The eleven rows restate owners already
certified by their own milestones, and GC-001/GC-002 are the mechanical backstop: a wrong
row that someone later builds on fails engine discovery, the scorer registry, or the
unowned-prefix negative control. Before those suites existed this batch would have been
reviewer-protected only. **If either suite goes red, this batch's proportionality no longer
holds and the rows need heavier proof.**

**Rule 20 sweep.** All thirteen numbers collide with existing ECRs; the live and genuinely
confusable one is the archive's **EA-0040 "Attack Path & Exposure Graph Engine"** against
**ECR-0040** ("unknown component reachability must not become a low score") - both concern
exposure and reachability, and ECR-0040 is cited throughout C-034's records as the
optimistic-default precedent. Neither inherits scope from the other. Noted also:
**ECR-0038** ("traversal truncation and a real path proof") is an existing precedent for
paging under a budget and reporting truncation, and is relevant to ECR-0034's open cursor
half - as precedent, not as scope.

**Archive status: exhausted as a requirements source.** With EA-0036 - EA-0050 resolved,
the remaining backlog is the tracked follow-ups plus whatever is chosen deliberately. Next
scheduled item is **ECR-0034's cursor half** - letting a >10 000-asset tenant be answered
rather than correctly refused.

---

---

## ECR-0061 - ECR-0034's second half: cursor pagination under a work budget

**Raised by:** claude.ai (spec) - **implemented and reviewed by Claude Code (C-036)**,
during the Codex outage. **Number** verified free against this log before assignment
(highest allocated was 0060, C-035); rule 1.

### This moves the threshold. It does not remove `degraded`.

C-034 replaced a *silent* 10 000-row cap with an *honest* one: the read was still
capped, but truncation was reported and both gated consumers refused on it. C-036
pages under `InventoryConfig.page_budget` (50 000) instead, so a tenant between 10 000
and the budget is now **answered** rather than correctly refused.

**A budget that truncates is still a cap - a better-behaved one.** Above the budget the
read is still partial and still says so. The honest description of this milestone is
*"silent cap at 10 000 -> explicit budget at N with truncation reported"* (rule 10 /
EA-0002 D8), **not** "ECR-0034 is closed". Describing it the other way produces an
implementation that re-opens the original defect at a higher number.

### Conforming to the house pattern, not designing one

`AssetStore.query` now returns `tuple[list[AssetRecord], str | None]` and accepts
`cursor`, matching what `findings`, `ispm` and `secrets` already ship. The engine loop
mirrors `ispm/engine.py::_identity_for_account`: a work budget bounds total rows,
`min(_ASSET_PAGE_SIZE, remaining)` bounds each page *and* prevents budget overshoot, and
a repeated cursor raises `StoreUnavailable` rather than looping forever.

Note the continuity: C-034's `limit + 1` probe did not disappear, it **moved inside the
store**, where it is the mechanism behind `next_cursor` rather than a cap detector
above it.

### The exhaustion decision, recorded rather than implied

**Budget exhausted -> return the partial with `degraded=True`.** Not a producer-side
refusal. Three reasons:

1. **Downstream behaviour is identical either way.** C-034 established that
   `degraded=True` already makes the known-surface and coverage consumers refuse, so a
   flagged partial becomes a refusal one layer up **without touching the gates** - a
   change that was deliberately not smuggled into this ticket.
2. **Strictly more informative at zero safety cost.** A producer-side refusal tells the
   caller nothing about how much was read; the gates refuse to *score* on it either way.
3. **The refusal would decide something that belongs to the caller.**
   `sweep_unreported` needs exhaustion, the coverage gates need completeness, a listing
   surface needs neither. Refusing at the producer forecloses the legitimate callers.

**Residual risk, recorded explicitly:** a *future* consumer of `inventory()` that
ignores `degraded`. The four current consumers are enumerated and each is
mutation-verified (rule 21). **Any new consumer of `inventory()` must read `degraded`.**

### `sweep_unreported`: exhaust or refuse, never partial

The apparent dilemma - respect a truncating budget and produce a partial sweep, or
ignore the budget and scan unbounded - is false. It **pages under the budget and refuses
if the budget is exhausted before the store is.** Work stays bounded and a partial sweep
is never produced. A budget-truncated sweep would mark live assets as unreported: the
*absence is not decommission* error EA-0025 was founded on. **Exhaustion is a
precondition for sweeping, not a target to approximate.**

### Rule 18, and what `mypy` did not catch

The signature change reached every implementer and caller. `mypy --strict` enumerated
them authoritatively - and it is worth recording that the bundle's *predicted* list of
six doubles was wrong in both directions: three named files implement other modules'
protocols with similarly-named methods, and the real set was two doubles plus four
caller sites. **Grep proposed the list; the type checker settled it.**

**One breakage `mypy` did not catch**, exactly the behavioural-vacancy shape the spec
warned about, arriving by an unpredicted route: `tests/secrets/test_secrets_w2.py`
computed `len(inventory)` where `inventory` became a 2-tuple. `len()` on a tuple is
valid, so the type checker passed while the assertion silently stopped counting rows -
it would have counted 2 forever. It was caught only because the expected value was not
2. **`mypy` green is necessary, not sufficient**; the test suite and mutation are what
close the gap.

### C-034's guards were rewritten, not dropped

`test_inventory_call_sites_pass_the_production_constant` pinned the 10 000 cap and the
probe. The cap is gone, so the guard is **rewritten to pin the same property one level
up**: `test_inventory_budget_constant_pinned` asserts the shipped `page_budget` and
`_ASSET_PAGE_SIZE`, and that the loop pages by the production page size rather than a
literal. A drift guard that goes red during a refactor is the likeliest thing to be
quietly dropped - which would have evaporated C-034's protection in the very change
that made it necessary.

**Proof cost:** the exhaustion logic is exercised at a reduced `page_budget` (5 against
6 rows) rather than with a 50 001-row fixture, paired with the constant pin so the
small-N tests cannot drift from the shipped value - C-034's pattern, right answer again.
One test does pay for 10 001 real records: `test_inventory_below_budget_not_degraded`,
the single assertion proving the threshold actually moved.

**Precedent:** ECR-0038 (*"traversal truncation and a real path proof"*) for the
paging-under-budget **shape** only. It is not scope, and rule 20 applies - the archive's
EA-0038 (Vulnerability Intelligence Correlation) is unrelated to both.

### On the value of `page_budget` (50 000): chosen, not derived

Recorded so the number is not mistaken for a measurement. **Nobody can set this
correctly yet**, because no real estate exists to measure read cost against. It was
chosen to match `max_relationship_work`'s order of magnitude, and erring high is
deliberate: the costs are asymmetric. Too low is a **silent capability loss** -
`sweep_unreported` refuses forever on a large tenant, and the platform looks broken
rather than slow. Too high is one slow read.

**Configurable is the right shipped state; the tuning belongs to the first real
deployment.** Revisit when there is an estate to measure.

**Status:** ECR-0034 is now fully discharged - silent truncation (C-034) and cursor
pagination (C-036). The cap that remains is explicit, configurable, and reported.

---

---

## ECR-0062 - `FindingStore` advertised pagination it did not provide

**Raised by:** Claude Code, during the post-C-036 audit claude.ai recommended - a sweep
for tuple-widening hazards (clean) plus a check of what each cursor keys on (this).
**Spec:** claude.ai. **Implemented and reviewed by Claude Code (C-037)** during the
Codex outage. **Number** verified free before assignment; rule 1.

### The defect

`FindingQuery.cursor` (`findings/models.py`) existed and was validated. **Neither
backend read it.** Both returned `..., None` unconditionally while truncating at
`limit` (default 100). Since a null `next_cursor` means *exhausted*, a caller paging
until the cursor was `None` received one page and a completeness guarantee it never
earned.

**This is worse in kind than ECR-0034.** That was a cap that never claimed otherwise -
`limit=10_000` returning `degraded=False` made no promise about completeness, it merely
failed to flag the absence of one. Here the signature is documentation, and it was
false: the parameter exists, it is validated, the return type is
`tuple[..., str | None]`. **The ECR-0013 unwired default, living inside the pagination
contract** - about the most load-bearing place it could sit.

`findings` was the sole outlier. Cursor references per backend: `objects` 3/4, `ispm`
2/3, `secrets` 3/4, `cspm` 2/3, `sspm` 4/9, `inventory` 2/4, **`findings` 0/0**.

### Severity: latent, no known wrong answer today

`risk/correlate.py::_finding_signals` - the only real consumer - reads under
`RiskConfig`'s correlation limit and re-truncates with `gathered[:limit]`. With
`ORDER BY severity_score DESC` that is a deliberate **top-N by severity** read, not a
completeness claim. It is correct **by intent**, and correct only because it never asks
for completeness. The trap was for the next caller - precisely any UI listing surface.

### Implement, not remove

Removing the cursor would have **renamed** the defect. A store that can only ever return
`limit` rows, for the platform's primary output emitted by every engine, is ECR-0034
relocated rather than resolved.

**Store-level only.** C-036 added an engine loop, a `page_budget` and a `degraded` flag
because `inventory()` promises a complete answer. `FindingStore.query` promises **a
page**, so none of that apparatus was copied. `limit=100` is unchanged: this does not
change the page size, **it makes the page size truthful.**

### The cursor keys on the complete sort key

Ordering is `severity_score DESC, id`, so the predicate is
`severity_score < $s OR (severity_score = $s AND id > $i)`, with the cursor encoding
both components. An `id`-only cursor is incoherent here: a row with a larger id sorts
*before* the cursor row when its severity is higher, so it would skip and duplicate.

`severity_score` is **write-once** (verified: Postgres `_save` updates only `status`,
`last_detected_at`, `resolved_at`, `version`; memory dedup never touches it), so the
keyset is safe from the mutable-sort-key hazard. No as-of bound was needed.

**Index:** `ix_finding_status_sev` lacked `id`, so the tie-break filtered instead of
seeking. Replaced by `ix_finding_status_sev_id (tenant_id, status, severity_score DESC,
id)`; the old index was a strict prefix of the new one, so it is dropped rather than
kept alongside.

### What the cursor does and does not promise

After this the read is stable **with respect to ordering** - no row skipped or
duplicated because of sort position. It is **not a stable set.** `status` is mutable, is
the most common filter, and is the leading index column, so a finding can enter or leave
the filtered set between page reads. That is the ordinary phase-change of keyset
pagination over a mutable **predicate** - not a sort-key defect, and not cursor-fixable.

**The consumer class matters.** A live listing surface tolerates phase-change; it is a
live view. A caller needing a **reproducible** read does not - if EA-0022 pages findings
for an issued report, or a compliance evidence set is assembled across pages, a status
change mid-read silently omits or duplicates a finding and the figure is not
reproducible, colliding with EA-0022's *no number without provenance* and its immutable
issued reports. **Not scope here**, recorded so the first such caller inherits the
constraint rather than discovering it.

### The negative control caught a vacuous proof

The tie-spanning test is the only one that distinguishes a correct cursor from an
`id`-only one, so it was verified by writing the wrong implementation and watching it
fail. **It did not fail.**

`new_id` is monotonic (UUIDv7), and the first version of the test created findings in
descending severity order - which made id order coincide with sort order, so
`id > cursor` was accidentally equivalent to the correct predicate. **The proof passed
against the very bug it existed to catch.**

Fixed by making the fixtures **anti-correlated**: low-severity rows are written first so
they carry smaller ids while sorting last. Under an `id`-only cursor they are then
excluded outright, and both the tie test and the round-trip go red. This is the sharpest
demonstration yet that a test asserting the right thing about the right code can still
be vacuous - **the negative control is what tells the difference**, and it is cheap.

### Rule 18, inverted - and vacuous here

The signature did not change; only the behaviour did. So the usual left-behind-double
risk did not apply, and the real risk inverted: **a double that faithfully models broken
behaviour becomes a broken double the moment the behaviour is fixed**, invisibly to
`mypy` because no type changed.

**That hazard does not materialise in this codebase: there are no `FindingStore` doubles
at all.** Enumerated by temporarily breaking the Protocol signature and reading what
`mypy --strict` named (rule 22 - grep proposes, the type system disposes): the only
implementers are `InMemoryFindingStore` and `PostgresFindingStore`, and the only call
sites are `risk/correlate.py` plus three `limit=1` health probes in `ispm`, `secrets`
and `dspm` that **discard** the result. The probes were checked, not skipped; discarding
is safe, since the cursor changes what is returned, never whether the call succeeds. A
test now pins the implementer set so adding a double later is a deliberate act.

### Flagged, deliberately not absorbed

Dedup re-emission keeps the **original** `severity_score`: a finding that recurs more
severely is never re-scored, because `_save` does not carry the new emission's score.
That may be deliberate under EA-0013's *history is not recomputed*, or a gap. **The
cursor makes the ordering reliable; whether the ordering reflects current severity is
the other question.** Recorded as its own backlog item.

**EA-0013's tie-breaker:** the composite-cursor requirement above supersedes it for this
store and is specified here. EA-0013's equal-timestamp item stays on the backlog - the
hypothesis that it was a pagination precondition **did not hold**: every other
paginating store orders on a unique key (`id` / `object_id`), so ties cannot bite.

---

---

## ECR-0063 - C-038: the final backlog milestone

**Spec:** claude.ai. **Implemented and reviewed by Claude Code (C-038)** during the Codex
outage. Number verified free before assignment; rule 1. Four tracked items, one of which
was a decision gate rather than a defect. **This milestone empties the tracked backlog.**

### R1 - the EA-0018 flake: diagnosed, not clamped

A negative duration is an **impossible value**. Clamping it to zero would present it as a
legitimate instantaneous measurement - the empty-means-safe family (ECR-0013, ECR-0040)
arriving in a metric - and would make the cause permanently invisible.

**Diagnosed cause: mixed time bases in the fixture.** The campaign's timestamps came from
the wall clock while the incident's came from a fixed `NOW` literal, so the *sign* of MTTD
depended on the machine's clock relative to that literal. Not a wall-clock regression in
production and not an ordering defect in the campaign path, so **no second ECR was
needed**. A monotonic source would not have helped either: these are differences between
*stored* timestamps from different records, so the ordering has to be **checked**, not
guaranteed by the clock.

**A production clamp was already shipped.** `_mttd_seconds` returned `max(0.0, ...)`, so a
campaign that responded to an incident *before that incident occurred* was reported as
**instantaneous detection** - the most favourable possible reading of impossible input.
Demonstrated before removal: a -1200s pair reported `0.0`. It is removed whether or not it
caused this flake, because it is what would hide a real ordering defect if one appeared.

All three durations (MTTD, MTTR, containment) now go through `_elapsed_seconds`, which
returns `None` - **unknown** - when the pair is impossible. An unknown value is excluded
from the mean rather than dragging it toward zero, and `0.0` keeps meaning *measured as
instantaneous*.

### R2 - two probes, and the guarantee that makes the rule mechanical

`idthreat_engine` and `response_engine` hardcoded `tenant_id=None` in their health probes.
Both **failed enterprise startup outright** - confirmed by reverting the fix:
`ServiceStartFailed: critical service idthreat_engine failed: query must be tenant-scoped
in enterprise mode`. `create_inmemory_runtime()` defaults to `local`, so driving the
factory-built runtime proved nothing about enterprise (rule 11). Both now derive a probe
tenant from their store's mode.

**GC-003 (owner-approved).** Rule 11 existed *because this was found once*, and it was
found again - so the rule was reviewer-enforced and the next omission would have slipped
identically. That is ECR-0057's argument verbatim. `tests/guarantees/test_service_health.py`
now enumerates whatever the kernel has registered and asserts every service starts and
reports ready in **both** tenant modes. Discovery-based, so a service added tomorrow is
covered without anyone remembering; **behavioural, not structural** (ECR-0007) - it starts
the real kernel rather than checking that a health *test* exists, since asserting a test
exists is satisfied by a test that asserts nothing.

Negative control `UnscopedHealthService` *performs* the omission (rule 19): it starts fine
in `local`, fails in `enterprise`, and fails kernel startup when registered. Mutation-verified
against both real defects.

### R3 - EA-0013's tie-breaker was already satisfied

The audit found **no un-tie-broken ordering in `src/`**. Every SQL ordering terminates in a
unique column (`id`, `object_id`, `evidence_id`, `seq`, `source_id` PK, or the lake's unique
`(tenant_id, name)`), and every Python sort key ends in a unique component. The item is
closed as **already met**, not implemented.

What was missing was a test that could *see* the property. `tests/conformance/test_ordering_determinism.py`
pins it with **rows carrying identical timestamps**, inserted in reverse id order - because a
suite with distinct timestamps passes against an un-tie-broken implementation, and one with
ids in insertion order cannot distinguish *ordered* from *insertion-ordered* (rules 23, 24).
Mutation-verified: removing `, record.id` turns it red.

### R4 - re-scoring: **option 3**, and why the options were not equal

**Owner decision.** Dedup re-emission kept the original `severity_score`, so a finding that
recurred more severely stayed listed at its original lower severity.

**The constraint that made this non-obvious:** ECR-0062's composite keyset cursor is safe
from skip/duplicate **because `severity_score` is write-once**. Option 2 - update in place -
would have reopened the exact hazard C-037's verification cleared, requiring an as-of bound
or a documented snapshot caveat. **One option silently reopened closed work in another
module**, which is why this was a gate rather than a preference.

Shipped: `severity_score` stays **write-once** as the sort key; `current_severity_score`
carries the latest emission, seeded equal on first raise. Ordering stays deterministic, the
cursor stays safe, escalation becomes visible. Additive with an explicit
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for deployments predating C-038 (rule 9 - the
persisted shape decides whether a field is free).

Mutation-verified: making the dedup path write `severity_score` instead - i.e. choosing
option 2 - turns six controls red, including `test_finding_cursor_unaffected_by_escalation`,
which pages a corpus whose current scores deliberately disagree with their sort keys.

*Considered and not chosen:* a **maximum-observed** score rather than latest. Latest is
accurate when severity genuinely falls; maximum would overstate. Recorded so the choice is
visible if a "never let a finding look less severe than it has been" requirement appears.

### Backlog

**Empty.** What remains is `FIRST_DEPLOYMENT_ITEMS.md` (three items no work can close),
**EA-0048** (recorded capability gap, unscheduled), and the two structural questions -
live collection and the UI surfaces - which are product decisions rather than engineering
work.

---

---

## ECR-0064 - Real data falsifies three availability assumptions in the ingest path

**Raised by:** **S-001**, the first real run - `postgres:16` scanned with syft
v1.49.0 and grype v0.116.0, yielding **7,367 SBOM components** and **302
vulnerability matches**.
**Status:** Accepted - all three gaps shipped.
**Number:** verified free by the reviewer at `0c21a94`; re-check `ECR-LOG.md`
before merging (rule 1).

**What S-001 was for.** No fixture data files exist anywhere in the test tree, so
the format-to-descriptor seam was the one boundary 33 engines had never crossed.
It broke in three places, and **no fixture could have revealed any of them.**

### The generalisation, stated first because it outlives the three fixes

> **A required field is an assertion that the field is always available - and only
> real data can test it.**

`VulnerabilityRecord.cvss` being required is not an oversight. It is a
**structural** consequence of building against fixtures: every fixture carried a
CVSS score because the person writing it supplied one. Reality withholds it 46% of
the time. The model therefore encoded a claim about the world that **no fixture
could ever falsify**, because the fixture author always has the value.

This predicts where the next gaps will be. **Every required field on every
handed-in descriptor is an untested availability claim**, and each connector that
arrives will falsify a different subset.

### Gap 1 - `VulnerabilityRecord.cvss` is required with no `unknown` representation

**139 of 302 real matches (46%) have no CVSS.** `cvss.value` is a required
non-negative float; **both omitting it and passing `None` are rejected** (verified
empirically). The only way to construct the record is to invent a value - and
`0.0` would assert *no severity*, the **most favourable possible reading** of an
absence.

**The irony is the finding.** An engine whose §0 discipline is *refuse, don't
guess* has a vulnerability model with **no way to say "I don't know."**

**Resolution.** The engine **already has the pattern**: EA-0024 ships
`PriorityFactor(status: "known" | "unknown")`, and **ECR-0040** established that an
unknown factor is excluded from the denominator rather than scored favourably. So
this is not a new mechanism - **the engine is already built to consume an unknown
CVSS; the input record simply cannot express one.** Make `cvss` optional, and have
absence produce a factor with `status="unknown"` carrying its reason.

### Gap 2 - `VALID_SEVERITIES` does not cover real scanner vocabulary

**Reviewer correction to the drafted text:** the accepted set is exactly
`{critical, high, medium, low, none}` (`vuln/models.py:26`) - the draft elided
`none` and then illustrated the hazard with `Unknown -> low`. The set matters
because `none` is precisely the tempting wrong target, so it is recorded verbatim
here rather than paraphrased.

Grype emits **`Negligible` (103 = 34%)** and **`Unknown` (36 = 12%)**. There is no
`unknown` severity, so mapping `Unknown -> none` would be a **false claim** - it
asserts *no severity* where the scanner reported that severity is undetermined -
and whether `Negligible` maps to `low` or `none` is a semantic choice EA-0024 does
not make.

**Resolution: add `unknown` and `negligible`. Do not re-classify.**

Severity here is a **handed-in claim, not a computed value**. `Negligible -> low`
**inflates** it - negligible sits *below* low in grype's scale - and the
re-classification is unrecoverable downstream. `Negligible -> none` asserts no
severity, which the scanner also did not say. Recording what the source actually
said is the same discipline **EA-0025** applies to conflicting ownership: *record,
do not smooth*.

**Required sweep:** **GC-001 AC-3** must cover the new `unknown` severity member,
or the scorer registry has a hole the day this lands.

### The overlap, and why fixing beats accepting 54%

Gaps 1 and 2 cover **exactly the same 139 records**, so only **163 of 302 (54%)**
of real vulnerabilities are representable today. The parser refuses the remainder
with stated reasons - which is the discipline working, and is why the run produced
a usable answer rather than a wrong one.

But refusal is not the right resting state:

> **A rejected record is invisible; an unknown record is a flagged gap.**

Today the platform does not know those 139 vulnerabilities exist. After the fix it
knows *"there is a vulnerability here whose severity we cannot determine"* - which
is strictly more information, strictly more actionable, and strictly more
consistent with **absence != safe**. The fix converts **139 silent absences into
139 explicit unknowns.**

### Gap 3 - `supplychain/parse.py` requires a `purl` on every component

Real syft output carries **146 library components** (all with purls), **1
operating-system component**, and **7,220 file components** (with none -
**correctly**, per CycloneDX). The parser raises on the first file entry and
**refuses the whole document**.

**Recommendation: fix the parser.** Three reasons:

1. **The parser is wrong about CycloneDX.** File components legitimately have no
   purl. Requiring one universally is a **spec misreading**, not a strictness
   choice.
2. **Filtering in the driver puts a domain decision outside the domain owner.**
   *What counts as a package* belongs to the supply-chain module; every future
   ingest path would otherwise re-implement the same filter and eventually
   diverge.
3. **It would hide the defect.** The next real SBOM breaks identically, and
   someone re-filters.

**Requirement on the fix.** Skip non-package components **by component `type`**,
and **report the skipped count with the reason**. Dropping 7,220 of 7,367
components silently would be its **own truncation defect** - the same shape as
`inventory()` returning `degraded=False`. *"Ingested 146 of 7,367 components; 7,220
skipped as non-package types"* is a materially different statement from *"ingested
the SBOM"*, and only the first is honest.

### What this does not change

- **CVSS is still not a priority** (EA-0024 §0). Gap 1 makes absence
  representable; it does not promote CVSS to a score.
- **No new scorer**, no new engine, no connector. `vuln/parse.py` and
  `supplychain/parse.py` remain pure parsers of handed-in documents.
- **The S-001 boundary holds** - nothing under `src/aqelyn/` learns that a scanner
  exists.

### How this lands

- `vuln/models.py` - `cvss` optional; `VALID_SEVERITIES` gains `unknown` and
  `negligible`. **Rule 9**: check the persisted shape before treating either as
  additive.
- `vuln/parse.py` - absence produces `status="unknown"` with a reason, never a
  default.
- `supplychain/parse.py` - component-type handling plus the skipped count.
- **GC-001 AC-3** sweep for the new `unknown` severity member.
- **Rule 18** if any Protocol signature moves.
- **S-001 resumes** once these land; the unknown-density report then has real
  content, which is the roadmap it was designed to produce.

### Expectation for the next run

After the fix the honest output will contain **substantially more `unknown` than
`known`** - 139 newly-representable records arriving as explicit unknowns, on top
of the unwired reachability, ownership and exposure factors. **That is the design
working**, and it is what makes the density report a prioritised roadmap rather
than a disappointment. S-001's success criteria stand unchanged.

---

---

### AMENDMENT to ECR-0064 (owner decision on Gap 3; correction to Gap 2)

**Status:** Gap 3 **decided - parser fix approved**. Gap 2 gains a distinction the
original section could not state, because it was written against an elided set.

#### Correction: the elided member was the dangerous one

The original Gap 2 text quoted the accepted severities as
`{critical, high, medium, low, ...}`. The real set is
`{critical, high, medium, low, none}`. **An ellipsis in a quoted set asserts
that the omitted members do not matter** - an assertion the author cannot make
without having seen them, and here the elided member is the trap. Same failure as
EA-0046's paraphrased title in C-035: the part that seemed not worth writing out
is the part that carried the risk.

#### Gap 2, restated: `none` makes the hazard worse, not better

Without `none` in the set, a mapper facing grype's `Unknown` has nowhere to put it
and **must raise**. With `none` present, it has a target that **type-checks and
reads as reasonable to a reviewer**:

| Value | Means |
|---|---|
| `none` | **the source stated there is no severity** - a positive claim of absence of risk |
| `unknown` | **the source did not say** |

Conflating them is the platform's founding error wearing a valid enum member: the
most favourable possible reading of an absence, arriving through a mapping that
passes type-checking.

**Requirement added:** `none` and `unknown` SHALL be **provably distinct**, not
merely both present. The acceptance test drives the real mapper against **two real
documents** - one whose source states `none` severity, one whose source states
`Unknown` - and asserts they produce **different records**.

> **A test that exercises only `Unknown` passes against a mapper that routes it to
> `none`.** This is rule 24 applied at specification time rather than discovered by
> mutation: the control has to be capable of failing against the plausible wrong
> implementation.

#### Gap 3: **parser fix approved**

`supplychain/parse.py` skips non-package components **by component `type`** rather
than requiring a `purl` universally. Driver-side filtering is rejected for the
three recorded reasons: the parser is **wrong about CycloneDX** rather than strict;
filtering in the driver puts *what counts as a package* outside the module that
owns the domain; and it would **hide the defect** until the next SBOM broke
identically.

**Three specifications on the skipped count, because "report it" is not enough:**

**1. It travels with the result, not in a log line.** A log line is the weakest
form - nobody reads it and it is not in the data. The count belongs on the parsed
result the way `inventory()` carries `degraded`, so any consumer can see coverage
without re-deriving it.

**2. Put it on the result model as a field - do NOT widen the return to a tuple.**
Widening `X -> tuple[X, int]` walks directly into **rule 23**: `len()`, `if`,
`for`, `[0]` and `in` all remain legal on the result while silently changing
meaning, and `mypy --strict` cannot see it. This project has already shipped one
such breakage (C-036's `len()`-on-tuple, caught only because the expected value
happened not to be 2). **A field on the result avoids the hazard entirely and
costs nothing.**

**3. Key the count by reason - the two cases are not the same.**

| Skipped because | Meaning | Is it a coverage gap? |
|---|---|---|
| component `type` is not package-like (e.g. `file`) | **expected** - was never in scope for package analysis | **No** |
| a package-like component is **missing its `purl`** | **the SBOM is malformed** | **Yes** |

A single total conflates them, and **the malformed case is the one worth knowing
about.** Record `{non_package: 7220, malformed: 0}` rather than `{skipped: 7220}`.

#### Does anything act on the count? - answered, not deferred

**The non-package count is provenance, not a coverage signal, and SHALL NOT feed
EA-0024 coverage.** Skipping a file component is not a coverage gap, because file
components were never in scope for package analysis; wiring it to coverage would
**inflate a gap that does not exist**. It tells an auditor what the document
contained versus what was ingested - which matters for auditing the ingest, not
for scoring.

**The malformed count is a genuine signal** and may legitimately reach coverage,
but that is a separate decision and is **not** taken here.

Stating this explicitly is the point: the alternative is a truthful field nobody
acts on and nobody knows whether anyone should - the **ECR-0013 shape**, which
this project has now caught four times.

#### Consequence

S-001 resumes once Gaps 1-3 land. Scan output is cached, so re-runs cost nothing,
and the next run produces the unknown-density report with real content.

---

---

## ECR-0065 - Derivation replay performs different arithmetic from composition

**Raised by:** **S-001**, the first real run. **162 of 200 real records fail
replay** - S-001 success criterion #2 - on a chain that passes every fixture.
**Status:** Accepted.
**Number:** verified free by the reviewer at `1528f35`; rule 1.

### The defect, exactly

```
_compose_score :  round(unit * 100, 6)          ->  30.763625      (engine.py:578)
replay path    :  round(score / 100.0, 6)       ->  0.307636       (engine.py:609)
                                                   the trailing 25 is gone
                  round(0.307636 * 100, 6)      ->  30.7636        (engine.py:673)
delta          :  0.000025          against _SCORE_TOLERANCE = 1e-6
```

**Six decimals at percentage scale requires eight at unit scale.** Fixture scores
carried four decimals or fewer, so the round-trip was lossless **by accident of
fixture construction**. Real values - EPSS `0.01109`, `0.73327` - expose it on
first contact.

### The principle this violates

EA-0020's guarantee is **replay-or-reject**: a score whose derivation does not
reproduce it is withheld, not served with a caveat. That guarantee assumes replay
recomputes **the same thing**.

> **Replay must perform the identical computation, not an equivalent-looking one.**

The defect is not really precision. The compose path and the replay path do
**different arithmetic in a different order** - scale-then-round versus
round-then-scale - and those are not the same function. Precision is how the
difference became visible; it is not the cause.

**This matters for choosing the fix.** Adding digits (six -> eight at unit scale)
makes the current values agree and **leaves the two paths still computing different
functions**, so the next value with more significant digits reopens it. The correct
fix is to make the replay path mirror `_compose_score` **operation for operation**;
if intermediate rounding is wanted at all, it must occur at the same point in both.

### Determination 1 - enforced at write, ANSWERED: yes, at three production sites

`validate_replayable_priority` is called from `src/`, not only from tests:

| Site | Effect of failure |
|---|---|
| `vuln/engine.py:181` - `prioritize()` return path | no priority is returned |
| `vuln/engine.py:226` - `recommend()` | no remediation plan is produced |
| `vuln/engine.py:254` - `raise_vulnerability()` | no finding is raised |

**So the favourable branch holds: production does not serve unreproducible scores.**
The explainability guarantee is real rather than nominal - and the consequence is
that **162 of 200 real findings are withheld**. The platform is correctly refusing
and consequently near-silent on real data. That is the design working, and it is
exactly why this is urgent rather than cosmetic.

### Determination 2 - other scale-crossing pairs, ANSWERED: the shape recurs in four modules

Every one of these crosses a unit/percentage boundary at a fixed six decimals:

| Module | Sites | Has replay validation |
|---|---|---|
| `vuln` | `engine.py:435`, `:578`, `:609`, `:673` | **yes** - the confirmed defect |
| `ispm` | `scoring.py:168`, `:169`, `:242`, `exposure.py:143` | **yes** |
| `secrets` | `scoring.py:112`, `:191`, `:385` | **yes** |
| `exposure` | `engine.py:623` | **yes** |

**All four pair a scale crossing with a replay guarantee**, so all four are
candidates for the identical defect - and **none of the other three has been driven
with real data**, so fixtures would hide them for the identical reason. Whether each
is a genuine defect depends on whether its crossing has a paired inverse; that
requires per-module determination and is **not** claimed here.

**Scope note:** this ECR fixes `vuln`. The other three need the same question asked,
and that is best done by the run that first drives real data through them rather
than by inspection - which is S-002's business, not this one's.

### Why no fixture could have caught it

The same thesis as **rule 26**, one level along. Rule 26 says a *required field* is
an assertion that the field is always available. This is its sibling:

> **A fixture's values encode assumptions about the *shape* of real data -
> precision, magnitude, cardinality, length - and every one of them is untested
> until real data arrives.**

Nobody chose four decimals as a claim about CVSS. It was simply what a person types
when writing an example. The assertion was made invisibly, and only real data could
falsify it. **Availability (rule 26) and shape (this) are the two halves of the same
gap.**

### A specification correction recorded with it

ECR-0064's amendment tabled `malformed` as a **count** category and illustrated it
as `{non_package: 7220, malformed: 0}` - which reads as *count it*, when EA-0030
already **quarantines** a partial SBOM. Implementing the count as written would have
**downgraded a hard guarantee to a soft signal while looking like added
observability**. Caught by `test_sc_quarantine`.

> **Before specifying that a condition be counted, check whether it is already
> refused.** Refusal is the strongest possible way of acting on a signal; replacing
> it with a counter is a weakening dressed as instrumentation.

---

### AMENDMENT to ECR-0065 - determinations answered; sweep scope added

**Both open determinations are now answered from shipped code**, and the second one
widens this ECR's verification scope from one module to four.

#### The consequence of Determination 1, in the terms it needs

**162 of 200 real findings are withheld.**

> **Record this in S-001's log in these terms, or a future reader misreads it.**
> *"162 of 200 withheld"* looks like a broken run. It is the opposite: the platform
> met data nobody wrote a fixture for, discovered it could not reproduce its own
> scores, and **refused rather than served them - at the cost of 81% of its
> output.** No fixture could have demonstrated that, because no fixture ever put the
> guarantee under the pressure. It is the strongest evidence so far that the safety
> discipline is real rather than aspirational.

#### The sweep - and why it does not need real data

**Separate discovery from testing.** Real data was the *discovery* mechanism: nobody
knew to look. But **the shape is now known**, and once you know what a fixture
accidentally supplies, you do not need real data to test it - **you need a fixture
built to withhold it.**

That is rule 27's own remedy, and the same move C-037 made with anti-correlated ids
(low severity written first, so the fixture contradicts the correlation instead of
embodying it). Here the contradicting fixture is trivial:

> **A value carrying more significant digits than any scale crossing can survive** -
> eight decimals at unit scale, where the fixtures carried four.

**Scope added to this ECR:** after the `vuln` fix, run **precision-adversarial
fixtures against all four replay-validated composers**. If the other three pass,
that is certainty bought cheaply. If any fails, it is **the same fix and the same
ECR**.

**Why fold it in rather than wait for S-002/S-003/S-004.** Left to real-data
discovery, each subsequent S-milestone rediscovers this defect **one module at a
time**, and each rediscovery costs a full run. Doing it here converts *"unknown for
three modules"* into *"known for four"* **before S-002 chooses a target** - and
S-002's target should be chosen by the density report, not by whichever module
happens to break next.

Corroborated independently from the specs: **EA-0033's identity posture score** and
**C-032's credential governance score** are both 0-100 with replay-or-reject,
crossing unit-to-percentage exactly as `_compose_score` does. `exposure` is not
corroborable from the spec side and needed the reviewer's read.

#### Acceptance

For each of the four composers: a precision-adversarial case that **fails against
the round-then-scale order and passes against the mirrored implementation**.
Mutation-verify by reintroducing the wrong order per module and confirming red - per
**rule 24, a sweep that has never failed is an untested sweep.**

**Unchanged from the parent ECR:** this is **not a scoring change**. No factor
weights move, no semantics change, and composed scores must be **identical to
today's values**. It is the replay that is wrong, not the score.

---

## ECR-0066 - Three priority factors report `known` with no provider supplied

**Raised by:** **S-001**'s density report, on its first correct run.
**Status:** Accepted - the factor repair and per-factor GC-001 widening shipped.
**Severity:** **high** - a demonstrated wrong answer on **every** real finding, in
the path that decides what a security team looks at first.
**Number:** verified free by the reviewer at `69a1b7e`; rule 1.

### The defect

Across 200 real findings and 1,400 factor evaluations, **`baseline`, `mission` and
`threat` report `known` on every finding while their providers are not wired.**
`exposure`, **three lines apart in the same function**, sets `status="unknown"` for
exactly the same situation (`vuln/engine.py:305`, `:313-316`, `:322`, `:345`).

This is not a missing signal. It is a **confident** one.

**Why it is severe.** **ECR-0040** exists so that uncertainty **removes a factor's
vote** rather than casting a favourable one. These three cast a vote nobody
supplied: the denominator treats them as **known-benign**, so every priority score
is currently computed with **three phantom favourable inputs**. It is the
empty-means-safe family arriving in the one place it costs most - the ordering a
responder reads first.

### The shape: ECR-0040 was applied to an instance, not to the pattern

Nothing here failed to test, and no fixture could have caught it in the usual sense.
**The fix was scoped to the symptom and the siblings inherited nothing** - the
correct handling and the three defective ones sit **three lines apart in the same
function**.

That is a distinct failure mode from the ones this project has collected
(18/19/23/24/25/26/27/28): not an apparatus that reports success while not testing,
and not a fixture that cannot express the failure, but **a correct decision applied
at one call site when it was a property of all of them.**

**Generalisation worth carrying:** when an ECR corrects a defect at a call site, the
closing question is not *"is this site fixed"* but ***"is this site the only one
that could have had it?"*** - answered by enumeration, not by inspection of the diff.

### Consequence: GC-001 AC-3 has the same gap it was built to prevent

As specified, **AC-3 asserts that each composition scorer ships *a case* proving
unknown is not the favourable result - per scorer, one case.** A scorer with seven
factors, one of which handles unknown correctly, **passes**.

That is the identical instance-versus-pattern error, sitting inside the guarantee
written to catch this family.

> **AC-3 SHALL widen from per-scorer to per-factor:** every factor of every
> composition scorer ships a case proving `unknown` is not the favourable result.
> **Negative control:** a scorer with one factor defaulting to `known` **fails**.

This widening lands **with** the fix, not after it - otherwise the guard stays
capable of passing the exact defect being repaired.

### Scope of the fix

**1. Audit all seven factors, not the three found.** For each, determine whether
`known` is **earned by a supplied input** or **defaulted in the absence of one**.
Enumerate by reading each factor's provider path - **not by grep** (rule 22). The
three named are what the report made visible; they are not established as the
complete set.

**2. Unwired must produce `unknown`, matching `exposure`'s handling** - with the
factor excluded from the denominator per ECR-0040.

**3. Distinguish the two reasons, because the report groups by them.**

| Situation | Reason | Next action it implies |
|---|---|---|
| no provider supplied at all | *"no `<X>` provider supplied"* | **wire it** |
| provider supplied, returned nothing | *"`<X>` provider returned no signal"* | **investigate why it is empty** |

Collapsing these into one reason produces a roadmap entry nobody can act on.

**4. Re-run the density report** after the fix. Its numbers are the input to S-002's
target decision and are currently wrong for three of seven rows.

### Consequence for the roadmap - the ranking is not yet complete

`exposure` at **200/200 unknown** is sound. But if `baseline`, `mission` and `threat`
are unwired and would report `unknown` once fixed, **they land at 200/200 too** - a
**four-way tie at the top**.

> **The report's top entry is sound; its ranking is not.** Three of seven rows are
> wrong in the direction that **hides** work, and correcting them may reveal that
> S-002's target is a **choice among four** rather than the obvious one.

**This is a gap in the S-001 addendum, not only in the code.** It specified *"ordered
by unknown count descending"* and *"the ordering is the recommendation"* - which
quietly assumed a **unique maximum**. That is a fixture-shaped assumption about the
**distribution** (rule 27's family), and real data found it the same way it found the
others.

**Required:** with a tie, the ordering **stops being a recommendation**, and the
report SHALL state the tie rather than break it arbitrarily. A tie-break -
cheapest-to-wire, or largest effect on score usefulness - is an **owner decision**,
and the report must not make it silently by sort stability.

### Explicitly not in scope

**The exposure replay gap** - a replay check that verifies a derivation is
structurally valid rather than that it reproduces the score. Real, and it lands on
the property that makes this platform unusual, but it has **no demonstrated wrong
answer** and is a different defect. It is **ECR-0067**, after this.

Widening scope at the end of a milestone is how good milestones end badly; the same
applies to widening an ECR at the point its fix is understood.

---

## ECR-0067 - Exposure's replay verified structure, not reproduction

**Raised by:** the reviewer, during ECR-0065's four-module sweep.
**Status:** **Accepted - determined and implemented.**

### Determination first, because the fix depended on it

The concern was that `validate_replayable_exposure` might verify a derivation is
*well-formed* rather than that it *reproduces the score* - but whether the
comparison was **absent** or **present but non-binding** changes the fix, and acting
on an assumed shape is how this project's most expensive defects have started.

**Determined at `a0127a6`: the comparison was absent entirely.**
`exposure/engine.py:425` called `replay(exposure.derivation)` and **discarded the
return value** - it was not assigned. `exposure.score` was never compared to
anything. The function verified that a derivation exists when scored, that it
replays structurally, and that impact binding is valid. Reproduction was not among
them.

### Why this mattered more than its severity suggested

**No demonstrated wrong answer** - with the comparison added, every shipped exposure
test passes, so the derivations did in fact reproduce their scores. The guarantee was
correct in practice and unverified in principle.

> **A check that asserts less than its name consumes the attention that would
> otherwise notice the absence.** A reader encountering `validate_replayable_*`
> concludes the property holds. Nothing prompts them to ask *which* property.

That is the **ECR-0013 shape one level up** - not a field nobody reads, but a
guarantee asserting less than it appears to. The specific failure mode it admitted:
a future refactor silently decoupling exposure's explanation from exposure's number,
with the check still green because the derivation is still well-formed.

### The fix

`replay()`'s result is captured, the score extracted, and compared to
`exposure.score` within `_SCORE_TOLERANCE` (1e-6, matching EA-0024 so the two checks
agree on what *reproduces* means). Extraction mirrors composition operation for
operation with **no intermediate rounding**, per **ECR-0065**.

**Mutation-verified:** perturbing the derivation's carried score turns **8** exposure
controls red. Previously all 8 passed, because nothing compared the number.

### Not folded in: enforcing uniformity mechanically

Four modules hold replay validation, they **diverged**, and only a reviewer's eye
caught it - which is **rule 29** again: a property of all four, verified at one.
Enforcing that every replay validator compares its score belongs in the **GC track**,
discovery-based rather than declared, and is deliberately **not** part of this fix.

---

## ECR-0068 - GC-001 AC-3 covers a state the platform is leaving

**Raised by:** **S-002**, on completing the first provider wiring.
**Status:** Accepted.
**Severity:** **structural, and worsening** - no wrong answer today, and the
uncovered region **grows with every S-milestone**.
**Number:** my log copy ends at 0067; re-check `ECR-LOG.md` before assigning
(rule 1).

### The defect

**AC-3 drives an engine with no providers wired at all** and asserts every
unsupplied factor reports `unknown`. That is exactly what ECR-0066 needed, and it
was correct when written - at that point **nothing was wired**.

**S-002 wired one.** `threat` now has a provider, so AC-3's scenario no longer
describes it. And the states that *do* now describe it are **unchecked**:

| Provider state | AC-3 covers it? |
|---|---|
| **no provider wired** | **yes** - the ECR-0066 case |
| **wired, returns nothing** | **no** |
| **wired, cannot assert for this record** | **no** - the state S-002 created |

### The shape: a guarantee whose coverage decays as the system matures

This is not an error. AC-3 was correct when written, **is still correct**, and
becomes **less relevant with every milestone that wires a provider**. Nothing
breaks; the guard simply, quietly, stops covering the majority case.

> **A guarantee scoped to one state of the system loses coverage as the system
> moves to another - monotonically, silently, and fastest when the project is
> going well.**

That is a distinct failure shape from the ones collected so far. Rules 18/19/24/25
concern apparatus reporting success while not testing; 26/27/30 concern data -
fixture or real - unable to express a failure; 29 concerns a correct decision
applied at one **site** when it was a property of all. **This is a correct
decision applied to one *state* when the system has several, and the covered state
is becoming the minority.**

**The tell is that improvement causes the decay.** Every S-milestone that wires a
provider moves a factor **out** of AC-3's coverage and into a region nothing
checks. The better the platform gets, the less the guard guards.

### The fix

**AC-3 SHALL assert the invariant across every provider state, not one.** In all
states the requirement is identical: **`unknown`, excluded from the denominator,
never favourable** (ECR-0040).

**Do not assume three states is the complete set.** The three above are the ones
demonstrated. **Enumerate whether others exist** - provider raises, provider
returns a malformed value, provider times out - and cover each, or record why it
cannot occur. Assuming the demonstrated set is the whole set is precisely the
**rule 29** error, and it would be committed here inside a fix for a coverage gap.

**Negative control per state** (rule 24): a factor defaulting to a favourable
`known` in **any** state must turn the suite red. A control exercising only the
unwired state passes against a factor that defaults when its provider returns
nothing - which is the current condition.

**Provider implementations must be discovered, not named as a closed roster.**
GC-001 SHALL derive every concrete factor-returning EA-0024 provider from shipped
source and require an exact behavioral case registry. A new implementation without
a case fails centrally. The generic mission owner API is recorded as an explicit
limitation because it returns `MissionImpactResult` and is shared platform-wide;
EA-0024's internal adapter is covered separately. This keeps the limitation visible
instead of letting the registry decay silently.

### One distinction the fix must not collapse

**For scoring, the three states are identical.** All produce `unknown`, all are
excluded from the denominator, none may be favourable. AC-3 treats them the same.

**For the roadmap, they are not.** S-002 established that a *closable* unknown -
no provider wired - is actionable, while *wired, cannot assert* is not, and the
density report now ranks by **closable unknowns only**. That distinction lives in
the **reason taxonomy**, not in the guarantee.

**Keep the two purposes separate.** A guarantee that ranked states, or a roadmap
that scored them, would be each doing the other's job.

### Standing practice this suggests

Both AC-3 gaps - per-scorer to per-factor (ECR-0066), and now unwired-only to
all-states - were found by **real data**, not by the guard. The suite has needed
widening twice, in the same AC, for the same underlying reason: **the production
reality moved and the guarantee did not.**

> **Recommended standing item on every S-milestone: does the guarantee suite still
> cover production reality after this change?** The S-track is precisely what
> changes that reality, so it is the track that ages the guards. Asking once per
> milestone would have caught this decay before it was a gap rather than after.

### Not in scope

- **The reason taxonomy** and the closable-versus-unclosable ranking - both landed
  in S-002.
- **The S-003 target decision** - a product question, not this ECR's.

## ECR-0069 - Data-handling boundary for real-estate milestones

**Raised by:** **S-003**, the first milestone against an estate the owner controls.
**Status:** Accepted.
**Durability:** this constraint is **inherited by S-004 and every later
real-estate milestone**, which is why it is an ECR rather than a line in one
bundle.

### Why it did not exist before

S-001 and S-002 scanned **public artefacts** - `postgres:16` and the CISA KEV
catalogue. Nothing collected was sensitive, so nothing constrained where it went:
findings could appear in a PR body, a fixture could be committed, a report could
be shared, and none of it disclosed anything.

**S-003 collects a real host.** The inventory carries hostnames, addresses,
service topology, and versions of software the owner actually runs - on a live
production box. The absence of a rule was correct until now and is not correct any
longer.

### The boundary

> **Aggregate counts may leave the estate. Per-asset detail may not.**

| Artefact | Contains | May it leave? |
|---|---|---|
| density report | factor counts, reasons | **yes** |
| findings dump | asset names, ports, versions | **no** - local store only |
| collection documents | full host inventory | **no** - local disk only |
| criticality declaration | service names and tiers | **no** |

### Structural, not remembered

**The density report emitter SHALL be incapable of carrying per-asset detail** -
it takes counts and reasons, and has **no code path** from a finding's identifying
fields to its output.

A rule someone must remember is the wrong shape for this. The platform already
holds the correct idiom in three places - **no person-level score type** (EA-0027,
EA-0033), **no secret-value field** (EA-0032's `_ValueFreeModel`), **no un-gated
execution** (EA-0008) - and each works because the wrong thing is
**unconstructible**, not because it is discouraged. The tooling gets the same
treatment.

**Corollary: never commit a collection document as a fixture.** The temptation is
real - it would make the run reproducible, and reproducibility has been a virtue
in every previous milestone. It would also commit the owner's infrastructure to a
git history permanently, and **a fixture is the one artefact in this project
designed to be shared**.

### What this does not restrict

**Nothing about what the platform stores.** The local Postgres holds the full
findings, with full detail, as it must - the whole point is that the platform can
answer questions about the estate. The boundary is on **what leaves**, not on what
is known.

**And nothing about the density report's usefulness.** Counts and reasons are
exactly what the roadmap needs; the per-asset detail was never what made it
decision-grade. This constraint costs the report nothing.

## ECR-0070 - Transient collector boundary for complete host inventory

**Raised by:** **S-003 U1**, when the real target did not have Syft installed.
**Status:** Accepted.
**Owner decision:** the owner explicitly approved the transient-Syft approach
after the reviewer tested the full placement, execution, and removal cycle.

### The contradiction

The Accepted S-003 bundle said that nothing in the milestone writes to the
estate. The target does not have Syft installed, so the package inventory could
not run as specified.

Installing Syft with the package manager would persistently change a live
commercial host. Replacing it with `dpkg-query` would keep the literal no-write
claim but silently omit application virtual environments. The reviewer measured
that omission on a tier-2 service: the filesystem scan found dozens of Python
packages that the operating-system package database cannot represent.

That is the platform's recurring failure mode: absence encoded as a clean result.
A partial SBOM presented as the estate inventory is worse than an explicit
unavailable result.

### Decision

S-003 is **non-mutating with respect to persistent estate state**, not literally
write-free.

When Syft is unavailable in `PATH`, U1 MAY consume one owner-approved executable
handed in under the system temporary directory, provided that:

1. its expected SHA-256 digest is supplied separately and verified before
   execution;
2. no downloader, installer, package manager, shell, or privilege escalation is
   added to the collector;
3. Syft receives isolated `HOME`, XDG cache/config/data, and temporary
   directories for the collection lifetime;
4. both the handed-in executable and the isolated runtime tree are removed in a
   `finally` path on success or failure; and
5. collection refuses success unless their absence is verified after cleanup.

Missing Syft without a handed-in executable, a malformed or mismatched digest,
and cleanup failure are named refusals. They are never raw tracebacks or
successful partial inventories.

### Work bound and coverage

The root filesystem scan is time-, output-, and worker-bounded. It excludes
pseudo-filesystems, transient runtime trees, and caches that add load without
describing deployed software. It SHALL NOT exclude application directories,
language package trees, or virtual environments. In particular, a
package-manager-only fallback is forbidden.

The exposure source remains configuration-only and sends no probe to a customer
service. Transferring the approved collector artifact is a separate,
owner-authorised handoff, not an active surface scan.

### Durability

This boundary applies to later real-estate milestones that require a collector
not already installed on the target. A stronger zero-write claim may be retained
only when the required collector is already present or the corresponding
measurement is reported unavailable.

## ECR-0071 - Purl-less binary components quarantine a real SBOM

**Raised by:** **S-003 U1** - the first SBOM the platform has collected from a real
estate.
**Status:** Accepted. **Route (B) was decided by the owner 2026-07-27 and
implemented by C-039**; routes (A) and (C) are off the table.
**Blocks:** S-003 U2.
**Number:** verified free at `b1520f1`; rule 20 checked - archive numbering stops at
EA-0051, so no `EA-0071` exists to collide with. **Re-check before merging** (rule 1).

### 1. The finding

`supplychain/parse.py` raises `SBOMParseError` on the first package-like component
lacking a `purl`. **24 such components exist, so the entire 131,685-component
document is quarantined.**

**Measured**, `syft dir:/` against the authorised host, CycloneDX JSON, 59.7 MB:

| quantity | value |
|---|---|
| total components | 131,685 |
| `file`-typed, correctly skipped | 116,533 |
| package-typed | 15,152 |
| package-typed **with** `purl` | 15,128 |
| package-typed **without** `purl` | **24** |

### 2. What the 24 actually are

All 24 identical in kind: `type: application`, name *"Simple Launcher"*, version
`1.1.0.14`, **`cpe` present, `purl` absent**, found by
`pe-binary-package-cataloger`.

They are the **Windows PE launchers** (`t32/t64/w32/w64.exe`) vendored inside
`pip`'s bundled `distlib`, replicated across the host's Python environments.

Three consequences:

1. **They are not Linux software and are not installed** - inert data files that
   happen to be executables for another operating system. The document claims no
   package ecosystem coordinate for them and does claim a CPE. The platform does
   **not** infer from that absence that a purl can never exist; it records the
   coordinate actually handed in.
2. **They are not information-free** - they carry `name`, `version`, `cpe`,
   `bom-ref`. Representing them is possible; **dropping them is a choice, not a
   necessity.**
3. **They are `type: application`, which legitimately belongs in
   `PACKAGE_COMPONENT_TYPES`** and must stay there - real applications with purls
   appear in the same document.

### 3. The discriminator trap - measured, not reasoned

**A rule of the form "`syft:package:type == binary` implies no `purl` required" is
WRONG.** Three binary-classifier components in the same document **do** carry
purls: `chrome`, and `node` twice, all `pkg:generic/...`.

**`binary` splits 3 with-purl / 24 without.** Relaxing on ecosystem alone would
**stop validating exactly the components that do claim a coordinate.**

### 4. This is a CLASSIFICATION question, not a TOLERANCE question

The quarantine is a **deliberate shipped guarantee**. `skipped_malformed`'s own
docstring says so: *EA-0030 quarantines a partial SBOM rather than ingesting it
partially, so the parser refuses instead of skipping. Refusal is the strongest form
of acting on the signal - stronger than any count.*

**The correct question is therefore *"is a PE-binary catalogue entry a package-like
component at all, and if so what identifies it?"*** - never *"should we tolerate
malformed package components?"* Any skip-and-count path for genuinely malformed
components would **silently reverse a shipped guarantee**, and the docstring is the
evidence such a reversal would be deliberate rather than accidental.

### 5. The precedent: ECR-0064 Gap 3, one level down

**This is the same parser and the same failure mode.** ECR-0064 Gap 3 required a
`purl` on every component; `file` components legitimately have none; it raised on
the first and refused the document. Its resolution was `PACKAGE_COMPONENT_TYPES` -
classify what is package-like, and stop demanding coordinates from what is not.
Its own words:

> requiring one universally **was a misreading of the format, not strictness**

and the generalisation it stated first because it outlives the fix:

> **A required field is an assertion that the field is always available - and only
> real data can test it.**

**That sentence has now arrived a second time, from a corpus one step more real.**
ECR-0064 was measured against a container image; ECR-0071 against a live
multi-tenant host. Worth stating plainly: **the first fix was validated by the
richest corpus available at the time and still under-generalised. The type-based
classification was right; the type list was calibrated on what that corpus happened
to contain.** Rule 30's *"the camouflage improves with scale"* in a new dress -
15,128 correct components made 24 look like an anomaly rather than a category.

### 6. Route (B), and the measured blast radius

**Decision: represent purl-less components without a `purl`.** (A) - reclassifying
them non-package - would encode **24 real on-disk artefacts as "not there"**, which
is the failure mode this platform exists to refuse.

Corrections to the reviewer's own first estimate, all **measured** at `b1520f1`:

- **`bom-ref` as identity is struck.** The 24 carry **24 distinct** `bom-ref`
  values - document-scoped random hex, **not stable across scans**. Keying on it
  would **mint 24 brand-new components on every collection, forever**: an
  unbounded-growth defect introduced by the fix meant to prevent a silent one.
- **`cpe` collapses 24 to 1.** All 24 share **one** identical CPE, with **zero**
  overlap against any purl-bearing component. They are six distlib launchers x four
  Python environments - **the same software seen 24 times.** Keyed on `cpe` they
  reconcile to **one component observed at 24 locations**, which is not a workaround
  but the correct model. The estate's component count rises by **1**, not 24.
- **The store-implementer set is small.** Enumerated with **mypy, not grep** (the C-036
  lesson): adding a member to `SBOMStore` yields 14 errors in 5 files, naming
  exactly **two implementers** - `InMemorySBOMStore` and `PostgresSBOMStore` -
  and **zero test doubles**. That count does not bound the wider purl-specific
  consumer migration described below.
- **`cpe` does not exist yet.** `grep -rn "cpe" src/aqelyn/supplychain/` returns
  nothing: absent from `SoftwareComponent`, absent from the DDL, discarded by the
  parser. **(B) is not "relax a constraint" - it is "introduce the alternative
  identity that does not exist."**

The two-store Protocol count is accurate but does not bound the full identity
change. In shipped source, `purl` is also the parser deduplication key, dependency
edge key, EA-0002 natural key, evidence/reference label, and input to several
analytical APIs. C-039 therefore includes a typed consumer-seam audit: identity
uses move to the semantic coordinate; genuinely purl-specific analysis remains
purl-specific but must report named uncertainty/refusal for a CPE-only component.
No `None`-as-string evidence and no empty-clean analytical result are permitted.

### 7. The modelling decision: an explicit discriminator, not `coalesce`

The reviewer left this open with no recommendation. **Decision: an explicit
`identity_kind` recording which handed-in coordinate establishes identity.**

`coalesce(purl, cpe)` is rejected for two reasons:

- **It stores a re-derived output.** ECR-0065's invariant: *a derivation storing
  its inputs cannot drift from its composition, because there is only one
  computation; one storing a re-derived output has two.* A coalesced identity is
  exactly that shape, one layer down.
- **It erases which coordinate identified the component**, so a reader cannot tell
  without recomputing.

The discriminator does **not** encode an absence cause the source does not provide.
With `purl` absent and `cpe` present, the platform knows that CPE is the available
identity; it does not know whether a purl is impossible or merely unreported.
Inventing that stronger claim would turn missing source data into a durable fact.

**Proposed shape:**

```
purl:          str | None          # retained; strict pkg: validation when present
cpe:           str | None          # new
identity_kind: "purl" | "cpe"      # semantic token, NOT NULL, NO DEFAULT
```

- `identity_kind = "purl"` requires `purl IS NOT NULL AND purl LIKE 'pkg:%'`
- `identity_kind = "cpe"` requires `purl IS NULL AND cpe IS NOT NULL` with a
  valid `cpe:` coordinate
- A claimed purl is always selected and strictly validated; malformed purl plus
  valid CPE quarantines rather than falling back
- Uniqueness by **two partial indexes keyed on `identity_kind`**, giving Postgres
  one deterministic expression per kind and **no namespace conflation** between the
  two coordinate spaces
- **No default on `identity_kind`.** The parser must select from coordinates
  actually present; neither present is malformed and quarantines
- The shipped **`object_id`<->`purl` immutability guard becomes
  `object_id`<->`(identity_kind, identity value)`**: a component may not change
  *which kind* identifies it either, since that would be a different component
- Both fields are retained even when only one identifies - a purl-bearing component
  may also carry a `cpe`, and discarding it would repeat this ECR's own mistake

This also **extends**: a future third coordinate adds a member, not a redesign.

### 8. The discriminator: format-level, not tool-level

The brief offers three candidates. **Recommendation: `purl` absent **and** `cpe`
present** - and *not* `foundBy == pe-binary-package-cataloger` or
`metadataType == pe-binary`.

**Why not the syft signatures.** Both couple the parser to **one tool's internal
taxonomy**. Cataloger names and metadata types change between syft versions, and a
rule that only works for syft would **silently fail the day the estate is scanned
with something else** - a latent, data-shaped defect of exactly the kind the S-track
keeps finding. The platform accepts *handed-in CycloneDX documents*, not
*syft output*.

**Why the format-level rule is also the honest one.** The platform **cannot know
whether a purl could exist** - only whether one **was claimed**. A signature
asserting *"no ecosystem coordinate can exist"* would be a claim about the world the
document never made. *"No purl claimed; a `cpe` claimed"* states what is true.

The syft signatures should be recorded in this ECR as **corroborating evidence** for
why the 24 have no purl - they are exactly what makes the finding legible - but they
must not become the rule.

**The negative control survives unchanged:** package-typed, **no `purl`, no
`cpe`** - **still quarantines.**

### 9. Guard rails - (B) is the permissive route

- **Never synthesise a purl.** Deriving `pkg:generic/simple-launcher@1.1.0.14`
  would fabricate a coordinate no ecosystem issued. Syft emits `pkg:generic/` for
  chrome and node because it **has provenance** for them; inventing one here is
  guessing, which the platform forbids everywhere else.
- **Strict validation stays wherever a `purl` is claimed.**
- **(B) widens what can be represented. It must not widen what can be tolerated.**
- **The 24-to-1 collapse must not lose the locations.** One component observed at
  24 paths is the correct model *only if the 24 paths are recorded*; if
  `SoftwareComponent` cannot carry them today, that is part of this change, not a
  detail to drop.

### 10. Proof

- A CycloneDX document containing **both** a purl-bearing binary-classifier
  component (`pkg:generic/node@...`) **and** a purl-less PE component. **The
  discriminator is only proven when both are present** (§3).
- **Mutation both directions:** removing the new classification must **re-quarantine**
  the document; relaxing it to all `binary` components must **fail on the
  purl-bearing ones**.
- **24 purl-less entries sharing one `cpe` reconcile to a single component with 24
  recorded locations.**
- **A second collection of the same host mints no duplicates** - the regression
  `bom-ref` keying would have caused, and the reason it was struck.
- **Negative control:** package-typed, no `purl`, no `cpe` - still quarantines.
- **Real owner round trip:** a CPE-only component reaches EA-0002 under a `cpe`
  natural key; purl-specific analysis reports explicit uncertainty/refusal rather
  than an empty clean result.
- Both backends, both tenant modes, `python -O`.

### 11. Not in scope

- **`inventory()` sizing is fine** - well under C-036's `page_budget = 50_000`;
  nothing is degraded.
  **CORRECTED by ECR-0072 §5:** an earlier version of this line read *"15,152
  components - the first real workload to exceed the retired ECR-0034 10,000
  cap."* **That figure was wrong.** 15,152 is package-typed **entries**; after
  identity dedup the estate yields **7,972 components**, which is **below** the
  retired cap. Parse-level dedup was not accounted for. The `page_budget`
  statement is unaffected; the exceeds-10,000 claim is withdrawn.
- Two S-003 follow-ups, deliberately separate: collection has **no memory bound**
  (`nproc=2` makes the two-worker cap a no-op; peak syft RSS 1.29 GB of 3.9 GB), and
  two **doc-versus-code drift pins**.

## ECR-0072 - Absence is not a value: three arrivals of one error

**Raised by:** **S-003**, running the real estate document through the real parser
at `bb970df` / `f96d7e5`.
**Status:** Accepted - implemented by C-040 and verified against the unedited
real-estate document.
**Blocks:** S-003 U2 - the real estate must ingest **unedited**.
**Number:** verified free; rule 20 checked (archive stops at EA-0051). **Re-check
before merging** (rule 1).

**This is one ECR rather than three because they share a single root**, and the
root is worth stating once:

> **Absent purl** was read as **malformed** (ECR-0071).
> **Absent licence metadata** is read as **conflicting** (§1).
> **Absent vulnerability coverage** will be read as **clean** (§4).
>
> **Absence is not a value.** It is not malformation, it is not disagreement, and
> it is emphatically not a clean result.

Splitting these would lose the pattern. The implementation sequences them (§6);
the finding is one finding.

---

### 1. The blocker: absent licence metadata treated as a conflict

**C-039 works, and the real SBOM still cannot be ingested.** `parse.py` compares
duplicate observations of one identity across
`identity_kind, purl, cpe, name, version, component_type, licenses, supplier,
hashes` and **quarantines the entire document** if any field differs.

**Measured on the real estate:**

| quantity | value |
|---|---|
| identities appearing more than once | **6,972** |
| total duplicate entries | 14,129 |
| duplicate sets differing on a compared field | **2** |
| of those, **absence vs value** | **2** |
| of those, **genuine contradictions** | **0** |

Both cases are the same package installed into two Python environments, where the
scanner found licence metadata at one install location and not the other.
**Nothing contradicts anything. Two entries out of 7,972 refuse the whole
document.**

### 2. This is rule 29, not a missing rule

**The parser already merges on absence** - `locations` and `direct` do exactly
this at `parse.py:246-247`. So the correct decision is **already in the file**; it
was applied to two fields when it was a property of every optional one.

That is **rule 29** verbatim: *a correction applied at one call site when it was a
property of all of them*, and the closing question - *is this site the only one
that could have had it?* - was not asked when those two merges were written.

**Resolution: route (A) - absence is not conflict.** When one observation carries
a value and another carries none, the **informative value wins**. Only two
**different non-null** values are a conflict.

**Route (B) does not fit, and this was checked before specifying.**
`ComponentConflictCandidate` requires `source_id`, `evidence_id`, `observed_at`
and `reliability`, and `ComponentConflict` is populated only in `_reconcile` - the
**cross-document** path where EA-0006 reliability discriminates between *different
sources*. Within one document both observations share the **same `source_id`, the
same `evidence_id`, and therefore the same reliability**, so reconciliation
degenerates: every case lands `unresolved: true` **by construction**. That is a
rename of the problem, and it would mark ordinary multi-environment installs as
permanent unresolved conflicts. (B) remains correct for the cross-document case it
was built for.

**Route (C) - keep quarantining - has a measured consequence: no
multi-environment host can ever be ingested.** One absent licence field among
thousands of duplicates is enough.

> **(A) narrows what counts as a conflict. It does not widen what is tolerated.**
> A genuine contradiction - two different non-null values for one identity - **still
> quarantines.** The C-039 governing sentence is unchanged.

### 3. Field classification, with the evidence basis stated per row

§6 of the brief asked for this rather than leaving it to inference. **Measured
across all 15,152 package-typed entries:**

**Contradiction-only** - a difference is always a contradiction, and absence is
itself one, because these are never legitimately absent:

| field | evidence |
|---|---|
| `name` | **proven** - 0.0% absent, never differs |
| `version` | **proven** - 0.0% absent, never differs |
| `component_type` | **proven** - 0.0% absent, never differs |
| `identity_kind` | **structural** - cannot differ within an identity group by construction |
| the **identifying** coordinate (`purl` when kind=purl, `cpe` when kind=cpe) | **structural** - it is the group key |

**Absence-mergeable** - one value, one absence, the informative value wins; two
different non-null values contradict:

| field | evidence |
|---|---|
| `licenses` | **proven by real data** - 2.1% absent, the only field differing among 6,973 groups, both differences absence-vs-value |
| the **non-identifying** coordinate | **structural** - `cpe` at 0.2% absent, `purl` at 0.2%; a purl-identified component may or may not also carry a cpe |
| `supplier` | **format semantics, NOT corpus-proven** - 100% absent on this estate |
| `hashes` | **format semantics, NOT corpus-proven** - 100% absent on this estate |

**The `supplier`/`hashes` distinction must be recorded, not glossed.** A field
that is **never present never differs**, so this corpus cannot demonstrate them
either way - and a scanner that populates them **partially** would reproduce the
licence failure exactly. That is **rule 30**: *the camouflage improves with
scale*, and 100% absence is the most camouflaged state there is.

**Decision: fix all optional fields, not only `licenses`.** Confining the fix to
the field the corpus happened to expose would be **rule 29 committed inside a
repair for rule 29**. The cost is identical - it is the same comparison - and the
evidence basis is now explicit per row, so nobody mistakes format-semantics
classification for corpus support.

### 4. The FR-16 seam, and the error's fourth arrival

`SupplyChainEngine.component_vulns_to_prioritization(purls: Sequence[str], ...)`
and its only production caller are **purl-only**. `validate_component_identity`
maps any raw `str` to `kind="purl"`, so **no type-correct call can address a
CPE-only component**, and the `_required_component_purl` guard at `engine.py:436`
is **unreachable in production**.

**Decision: option (i) - widen to `Sequence[ComponentIdentity | str]`,** keeping
`str` as the documented purl-compatibility form. Three reasons:

1. **Measured, it is shallow.** Vulnerabilities bind by
   `asset_ref.ref_id == component.object_id`, **not by purl** - everything
   downstream is **already identity-agnostic**. The `Sequence[str]` entry point is
   the only barrier.
2. **Option (ii) makes FR-16 a permanent per-caller tax.** Requiring the named
   unavailable at every enumerating caller is a property that must be
   re-established for each new one - rule 29 as a standing obligation rather than
   a fixed defect.
3. **C-039's V3a already prescribes it**: *any convenience API that defaults to
   purl is only a compatibility wrapper around an explicit semantic-identity store
   contract.* Option (ii) leaves V3a partially realised indefinitely.

**But the seam is not the whole problem, and this is the part that outlives the
option.** Even with (i), **a CPE-only component receives zero vulnerabilities from
every shipped provider**, because none matches by CPE (`grep -rn "cpe"
src/aqelyn/vuln/ src/aqelyn/threat/` returns nothing). It would present as
**"0 vulnerabilities" - indistinguishable from assessed-and-clean.**

**That is the error's fourth arrival, and the most consequential**, because it is
what a real operator actually sees.

**Decision: a component no provider can assess SHALL be recorded in EA-0024
coverage as explicitly unassessable**, with the reason *"no provider matches
identity_kind=cpe"*, and **SHALL NOT present as zero vulnerabilities.** EA-0024's
coverage is already mandatory and `PriorityFactor` already carries
`status="unknown"`; the machinery exists and is not being wired to this case.

**Taxonomy placement** (S-002's): this is **closable** - *no provider supplied for
this identity kind* - because a CPE-matching provider **could** be built. It is
therefore a legitimate **roadmap entry** in the density report, not a structural
dead end. The real estate has **one** such component, and one silently
unprioritized component is precisely what this platform sells against.

### 5. Correction to ECR-0071 §9 and C-039's review protocol

Both carried: *"15,152 components - the first real workload to exceed the retired
ECR-0034 10,000 cap."* **The figure was wrong.** 15,152 is package-typed
**entries**; after identity dedup the estate yields **7,972 components** -
**below** the retired cap. Parse-level dedup, which exists on `main` as well, was
not accounted for.

**The `page_budget = 50_000` statement is unaffected; nothing is degraded. The
exceeds-10,000 claim is withdrawn.** Corrected in place in ECR-0071 rather than
respun as a separate document.

*(The mis-statement is the same shape as everything else in this ECR: an entry
count read as a component count - counting one thing and reporting another.)*

### 6. Proof

- **The real, unedited estate document ingests end-to-end.** Re-run by the
  reviewer before merge; no hand-editing.
- **The multi-environment shape:** one identity, two observations, one carrying a
  field value and one carrying none → **one component, informative value
  retained.**
- **Negative control, non-negotiable:** two **different non-null** values for one
  identity → **still quarantines.** This is what keeps (A) from becoming a
  tolerance path.
- **Field-by-field mutation:** every field classified contradiction-only must
  **refuse on absence too**, mutation-verified per field. A control exercising
  only `licenses` proves nothing about `supplier`.
- **CPE-only prioritization:** an estate containing a CPE-only component with a
  known CVE either **prioritizes it or reports it explicitly unavailable - never
  omits it silently.** **The vulnerability must be constructed**: no CPE
  vulnerability provider exists, so a real-corpus CVE for such a component
  **cannot be sourced**. This is legitimate and is what C-039's test already does;
  stated here so nobody hunts for data that cannot exist.
- **Coverage:** the CPE-only component appears as **named unassessable**, not as
  zero-vulnerabilities. Mutate the coverage path and confirm red.
- Both backends, both tenant modes, `python -O`.

### 7. Not in scope

The two S-003 follow-ups already tracked separately: collection memory bound
(`nproc=2` makes the two-worker cap a no-op; peak syft RSS 1.29 GB of 3.9 GB), and
the two doc-versus-code drift pins.

## ECR-0073 - S-003 U3: surface derived from observed binds, and the constraint that was never chosen

**Raised by:** **S-003 U3**, on measuring what the real host's collection actually
produced.
**Status:** Accepted.
**Number:** verified free at `e924aad` (`ECR-LOG.md` contiguous 0001-0072, no gaps);
rule 20 checked. **Re-check before merging** (rule 1).
**Data handling (ECR-0069):** counts and classes only throughout. No port, address,
service name, path or hostname appears here.

### 1. The headline: U3's stated input does not exist

S-003 U3 promised *"surface derived from configuration."* **The configuration reads
failed on the real host** - both refused for want of privilege, both honestly
recorded in `unavailable_details`. What survives is raw socket output: **16 listener
lines.**

**This is the milestone's most interesting result, not its failure.** A spec that
quietly substituted one source for another would have hidden it.

### 2. What a bind address can and cannot answer

**Measured, 16 listeners by bind class:**

| class | count |
|---|---|
| externally bound | **6** |
| loopback-only | **4** |
| neither | **6** |

**The precise distinction, which the S-003 bundle left unstated:**

| question | answered by |
|---|---|
| *is this socket externally bound?* | **the observed bind address** |
| *how does traffic flow between them?* | **configuration only** |

For reachability-at-the-socket the observed bind is **stronger** than configuration:
a config file states intent and can be stale, edited-but-unreloaded, or overridden;
the bind address is what the kernel is doing now. Configuration remains necessary
for topology and traffic flow. **Recording that distinction here prevents U3 from
silently substituting one evidence source for the other.**

### 3. Decision 1 - derive from observed binds, and say so in the basis

**Yes.** The source of truth for U3 is the **observed bind address**, and
`ExposureBasis` exists precisely to record which evidence produced a judgement.

**A record SHALL NOT claim a basis it did not use.** A `KnownSurfaceRecord` derived
from a socket table says so; nothing in this milestone may present a bind-derived
judgement as configuration-derived. That is the platform's provenance discipline,
and it is the only thing that keeps §4's residual visible.

### 4. Decision 2 - three states, because they have three different remediations

The S-003 bundle asked U3 to distinguish two states. **The real data produces
three**, and **U1's shipped `ListenerObservation` already models it** -
`asset_key: str | None`, documented as *"observed but could not be joined ...
intentionally distinct from a registered service for which no surface could be
derived."*

| state | measured | what fixes it |
|---|---|---|
| **registered asset, no surface derivable** | - | derive a surface |
| **surface observed, not attributable** | **14 of 16** | obtain the join key |
| **not registered at all** (vhost-only, no unit - from U2) | - | register the asset |

**Adopt all three.** The operational test for whether two states may be collapsed is
whether they imply **the same next action** - and these imply three different ones.
Collapsing "observed but unattributable" into either neighbour is a real loss: it is
neither a missing asset (the listener **is** there) nor a missing surface (the
surface **is** visible). **It is a missing join**, and no other state's fix touches
it.

This is the same test S-002 applied to *closable* versus *structural* unknowns, and
it should be the standing one.

### 5. Decision 3 - the classification is not binary, and the remainder stays unknown

**6 of 16 are neither externally bound nor loopback.** A two-valued classification
would force them into a wrong bucket.

**Rule: classify only what the bind address unambiguously determines. Everything
else is `reachability=None`.**

- wildcard binds -> **external**
- loopback binds -> **internal**
- **anything else -> unknown**, with the reason recorded

**The reasoning, which belongs in the record:** a socket bound to a *specific*
address may sit on a public interface or a private one, and **the host's own socket
table cannot say which.** Deciding would require network knowledge U3 does not have.
An `unknown` here is not a gap in the implementation - it is the honest limit of the
evidence.

**No heuristics.** `_level_for` already defaults to `"unknown"`, and
`KnownSurfaceRecord.reachability` is already `Reachability | None`. **The shipped
model already expresses everything U3 needs** - nothing requires widening, and
nothing may be inferred to fill the gap.

### 6. Decision 4 - the finding: **read-only and unprivileged are not the same
constraint**

The estate was chosen over a declared fixture **specifically** to exercise a genuine
multi-hop chain - external front-end forwarding to a loopback application. **That
chain is not derivable**, because it needs the proxy configuration and the
configuration read failed.

**But it did not fail because of read-only.** It failed because of **unprivileged** -
and those are different constraints:

| constraint | means | was it chosen? |
|---|---|---|
| **read-only** | change nothing on the estate | **yes** - deliberately, in the S-003 bundle |
| **unprivileged** | do not elevate | **no** - inherited from how collection happened to run |

**A privileged read is still read-only.** Dumping a proxy configuration or listing a
firewall ruleset **changes nothing**. So the two-hop chain was not lost to a
principle the milestone adopted; it was lost to a privilege level **nobody
deliberately chose.**

**That makes it a decision rather than a limit** - and it is the owner's, not this
ECR's. Recorded as an **explicit residual**, not silently dropped, because it is the
reason this target was selected.

**Two things the owner needs before deciding**, so it is not framed as a free win:

1. **A privileged collector needs elevated access on a production box** running
   services that move money. That is a real risk, separate from whether the read
   mutates anything.
2. **ECR-0069 applies harder.** A proxy configuration can carry certificate paths,
   upstream credentials and internal topology - materially more sensitive than a
   socket table. If this is pursued, the data boundary needs re-examining, not
   inheriting.

### 7. Decision 5 - attribution: name the gap, do not close it here

**Only 2 of 16 listeners carry process information**; unprivileged `ss --processes`
reveals only the invoking user's own processes, and the externally-bound listeners
are root-owned. The unit inventory captures `MainPID`, so **PID is the natural join
key and it is absent for 14 of 16.**

**Unattributable listeners stay unattributed, with a named reason.** Honest, cheap,
and it preserves state 2 of §4.

**Note that decisions 4 and 5 resolve to the same action.** Both the proxy topology
and the listener PIDs are obtainable by exactly one change - a privileged read. **So
the residual is one decision, not two**, and it should be recorded as one.

### 8. Scope: a source change, not an engine change

`InventoryKnownSurfaceSource.list_known_surface` hardcodes `reachability=None`.
**U3 replaces that hardcode with a measured judgement and a real basis.**
`_level_for` and `derive_surface` **should not need touching.**

**Fail-closed is inherited and must not weaken:** the same source raises
`InventoryUnavailable` when the inventory report is `degraded` (C-034/C-036). U3 gets
refusal-on-truncation for free and **may not erode it.**

### 9. Expected outcome - stated before the run

Per S-002's lesson, where the stated expectation was **wrong** and that was only
visible because it had been written first:

> **`exposure` will not move to mostly-known.** At most a small number of assets
> acquire a measured reachability, because only **2 of 16** listeners attribute to a
> registered asset. **The count will barely move; the reasons will change** - from
> *"no surface signal"* to *"surface observed, not attributable"* for the majority.

**That is S-002's result in a different factor**, and it is a success: the platform
moves from *nothing was asked* to *asked, and here is precisely what blocked the
answer.*

**Roadmap consequence:** *"observed but unattributable"* is a **closable** unknown in
S-002's taxonomy - closable by the §6 decision. So the density report will point at
**the same single decision** that §6 and §7 both reach, which is the useful outcome:
one owner choice, named by the instrument rather than argued for in prose.

### 10. Proof

- The bundle's three tests, **plus one for the third state** (§4).
- **Negative control:** a registered asset with no derivable surface, and an observed
  unattributable listener, must produce **different, named** outcomes. *A test that
  cannot tell them apart is the whole point of the unit.*
- **Unknown must not become a level:** a listener in the third bind class must not
  acquire `high` or `low`. Mutation-verify by forcing `_level_for`'s default and
  watching a control fail.
- **Basis honesty:** a bind-derived record must not claim a configuration basis
  (§3). Mutate the basis and confirm red.
- **Fail-closed preserved:** a degraded inventory still raises
  `InventoryUnavailable`. Mutate to confirm the guard is still load-bearing after
  U3's changes.
- Both backends, both tenant modes, `python -O`.
- **Real-estate run before merge**, counts only in any output.

### 11. Carried forward, unresolved

Recorded so none of it disappears into U3: the three U2 residuals (undeclared assets
scoring `0.000` rather than unknown; tier-4 services structurally unrepresentable;
*"decided not to declare"* recorded as *"not declared"*); the collector's absent
memory bound; the two doc-versus-code drift pins; C-040's vacuous
`scanned -= unassessable_inventory` assertion; and U2's untested `used_default_tier`
refusal.

**U4's baseline remains conditional on U4's own criteria.**

## ECR-0074 - A favourable value with no provider, and a decision recorded as an absence

**Raised by:** **S-003 U2**, deferred through U3-U5 and taken up now.
**Status:** Accepted.
**Number:** verified free (`ECR-LOG.md` contiguous 0001-0073); rule 20 checked.
**Re-checked before merge** (rule 1).

**This ECR leads with a question rather than a defect**, because the answer matters
more than the fix.

---

### 1. The question that comes first

`ispm/scoring.py:347` read `if not result.impacts: return 0.0, None`. An asset with
no mission object therefore contributed **0.0 - the most favourable mission value** -
rendered `0.000` rather than `unknown`.

**That is ECR-0040's shape exactly, in EA-0033.** And ECR-0040 was raised in 2026;
**ECR-0066** widened GC-001 **AC-3** to per-factor precisely to catch it; **ECR-0068**
widened AC-3 again for provider states. A factor returning a favourable value with no
provider is **the literal subject of that guarantee.**

> **So the first question is not "how do we fix line 347." It is: *why did AC-3 not
> catch this?***

The fix is a few lines. The answer to the question is a hole in the guarantee that
passed green for three ECRs.

### 2. Determination required before any fix - three candidates

**The determining run happened before the fix**, per the ECR-0067 precedent. The
three possible answers differed enormously in what they implied:

| candidate | implies |
|---|---|
| **(a) ISPM's scorer is not discovered** by AC-3's enumeration | a **discovery gap** - fixable by widening the enumeration, the same shape as ECR-0066/0068 |
| **(b) this path never constructs a factor** - `return 0.0, None` yields a bare score, so there is nothing for a factor-enumerating guard to inspect | **the guard's subject is wrong**, and **no amount of widening reaches it** |
| **(c) covered, but the case was never written** | cheapest, and the least likely given two prior widenings |

**(b) is the answer.** ISPM is present in GC-001's discovered scorer registry, but
AC-3's ISPM case feeds hand-built `PostureFactor` records directly to
`posture_score_result`. It never invokes `compose_posture`, EA-0007, or
`_mission_factor`.

The determining evidence was deliberately produced with the defect still active:

```text
PYTHONPATH=<worktree>/src;<worktree>/tests
python -m pytest tests/guarantees/test_scorers.py -q --color=no
.....................                                                    [100%]
```

The central guarantee stayed green while the favourable `0.0` path shipped.

> **A guarantee that enumerates a *representation* cannot see a path that bypasses the
> representation.** AC-3 asserts properties of factor objects. Code that produces a
> score **without constructing one** is outside its reach entirely - not
> under-covered, but **invisible**.

This is **AC-3's third gap and the first of a different kind.** ECR-0066 was
per-scorer -> per-factor; ECR-0068 was unwired -> all provider states; both were
**widenings of the same subject**. The subject itself is wrong: the guard must
enumerate **score-producing paths**, not only factors. The cross-cutting repair is
recorded separately as ECR-0075 rather than being hidden inside this EA-0033 fix.

**All three prior AC-3 gaps were found by real data rather than by the guard.** That
pattern is itself the finding, and ECR-0068's standing recommendation - *ask once per
S-milestone whether the suite still covers production reality after this change* -
is what surfaced it.

### 3. The defect, once the question was answered

An undeclared asset must contribute **`unknown`, excluded from the denominator**, not
`0.0`. The platform's own idiom is already in EA-0024
(`PriorityFactor(status="known"|"unknown")`) and ECR-0040 already established the
denominator rule.

EA-0033 now wraps the EA-0013 owner record in its existing `iag_risk`
`PostureFactor`. When EA-0007 returns no impact, that factor carries
`status="unknown"`, `value=None`, a named reason, and zero normalized vote. The exact
EA-0011 risks, EA-0013 record, EA-0006 trust, and EA-0007 result remain pinned for
replay; the provisional numeric record cannot cast a favourable vote.

**Rule 29 applies to the fix itself:** the closing question is not *"is line 347
fixed"* but ***"is line 347 the only path that can return a score without a
provider?"*** A typed/AST audit, verified by `mypy --strict src tests`, found numeric
mission paths in EA-0013, EA-0014, EA-0015, EA-0017, EA-0023, EA-0024, EA-0032, and
EA-0033. EA-0024 already materializes a typed `PriorityFactor`; the others belong to
ECR-0075's score-path closure audit and are not silently declared correct here.

### 4. The second residual: a decision recorded as an absence

**19 of 26 units** are substrate the owner **deliberately declined to tier
individually.** They return `input_missing`, which reads as *nobody has supplied this
yet.*

**The cause is misstated, and the cause is what determines the remediation:**

| recorded | reads as | implied action |
|---|---|---|
| `input_missing` | nobody has answered | **closable** - go and declare it |
| the truth: *declined* | someone considered it and answered | **nothing to do** |

**So the density report currently carries 19 closable roadmap items that are not
closable** - manufacturing work that does not exist, which is precisely the failure
U4's `unknown_is_fail` analysis warned about, and the cost the owner's own baseline
declaration named: *"the noise trains people to ignore the real ones."*

**This is the third place in S-003 where a reason's *cause* was misstated** - U3's
three attribution states, U4's two closability classes, and now this. The pattern is
consistent enough to be worth naming: **an unknown's cause is not decoration; it is
the field that decides what anyone should do about it.**

#### The owner question this ECR must put, not answer

**What does "declined to tier individually" mean for the mission factor?**

- **deliberately unweighted** - the owner has answered, and the answer is *no
  individual tier*. That is arguably **not an unknown at all**, but a declared
  outcome, and it would need its own representation.
- **deferred** - the owner may tier them later, so it is a genuine unknown that is
  **closable by decision** rather than by collection.
- **inherited** - they take a substrate tier, in which case the factor is **known**.

**These produce three different report rows and three different roadmap
implications.** The ECR records the question; the owner answers it. **Do not pick one
to make the implementation proceed** - that would be inventing a declaration, in the
same milestone that refused to invent a baseline.

The report continues to say `input_missing` until it can say something truer:
**an honest wrong-cause is better than an invented right one**, and it stays visible.

### 5. Scope

- **The determination (section 2) happened first**, and its evidence is recorded.
- **The `0.000` fix** is applied in EA-0033.
- **AC-3's change of subject** is recorded as the separate GC-track ECR-0075.
- **Section 4's representation waits on the owner's answer.** No declaration was
  invented to make the report look better.

### 6. Proof

- **The determination is written down** with evidence: candidate (b).
- **An undeclared asset scores `unknown`, not `0.000`**, and is **excluded from the
  denominator** - driven through the **real scorer**, not a spy.
- **Positive control:** an explicit EA-0007 impact of `0.0` leaves the composed risk
  factor known, proving that absence and a provider-reported zero remain distinct.
- **Mutation:** restoring a known `0.0` context turns
  `test_ispm_missing_mission_is_unknown_and_excluded` red. AC-3 stays green on the
  original path; that is the recorded determination, not a falsely closed guarantee.
- **Sibling paths enumerated** and recorded under ECR-0075 rather than silently
  assumed safe.
- Both backends, both tenant modes, `python -O`.

## ECR-0075 - GC-001 must discover score-producing paths, not only factor representations

**Raised by:** **ECR-0074's required pre-fix determination.**
**Status:** Accepted.
**Number:** verified free after ECR-0074; rule 20 checked.

### 1. The finding

GC-001 AC-3 discovers composition scorer packages and, for EA-0024, concrete
factor-provider implementations. It asserts that typed factor objects represent
unknown inputs honestly. That subject is necessary and insufficient.

EA-0033 accepted an empty `MissionImpactResult`, converted it to bare numeric `0.0`,
and only then constructed a known `iag_risk` factor around the resulting EA-0013
record. The missing input had already disappeared. AC-3 could inspect every factor
perfectly and never see the conversion.

> **A guarantee over representation B cannot protect transformation A -> B when A
> can erase uncertainty before B exists.**

### 2. Current typed audit

An AST inventory of shipped `mission_impact` consumers, followed by
`mypy --strict src tests`, identifies numeric score/priority paths in:

| owner | path |
|---|---|
| EA-0013 | `risk.engine.RiskIntelligenceEngine._mission_context` |
| EA-0014 | `threat.engine.ThreatIntelligenceEngine._severity_score` |
| EA-0015 | `soc.correlate._mission_context` |
| EA-0017 | `detection.scoring._mission_factor` |
| EA-0023 | `exposure.engine.score_exposure` / `_mission_factors` |
| EA-0024 | `vuln.engine.VulnerabilityIntelligenceEngine._mission_factor` |
| EA-0032 | `secrets.scoring._mission_factor` |
| EA-0033 | `ispm.scoring._mission_factor` |

EA-0024 is visible because it returns `PriorityFactor`. The others return or consume
bare numerics. This table is an audit input, **not** a permanent hand-maintained
registry.

### 3. Required direction

- Discover **score-producing paths** from shipped source. Omission must fail closed;
  a hand-maintained roster repeats the defect.
- Require an exact behavioral case or a reasoned exclusion for every discovered
  path.
- Drive at least provider absent, provider returns empty, provider returns impact,
  malformed return, raised failure, and truncated result where the owner type permits
  them. Do not assume those states are universal; record why a state cannot occur.
- Mutate the pre-representation transformation so an unknown becomes favourable.
  The central guarantee must turn red.
- Preserve the distinction between scoring and roadmap: all unknown states are
  non-favourable for scoring; their typed causes may imply different actions.
- Do not weight-tune a correct scorer merely to satisfy a central ordering.

### 4. Scope boundary

ECR-0075 does not decide every owner's missing-mission policy inside ECR-0074.
Each owner contract must say whether mission absence makes its output unknown,
refusing, conservatively bounded, or legitimately irrelevant. The guarantee enforces
the declared boundary and prevents silent favourable fallback; it does not invent the
boundary.

## ECR-0076 - The cross-cutting repair: absence is the fold's identity element

**Raised by:** ECR-0075's audit, which found the pre-fix ISPM function **byte-identical**
in another module and the same shape in at least two more.
**Status:** Accepted - C-041 A1 through A5 completed.
**Number:** next free per the reviewer; **re-check `ECR-LOG.md` before merging** (rule 1).

**ECR-0074 fixed one instance. ECR-0075 explained why the guarantee could not see it.
ECR-0076 repairs the class.**

### 1. The mechanism, and why this is a class rather than a coincidence

Every affected site folds optional contributors. The reviewer's audit names the
operator: **the composition takes `max`, so absence lands at the least-critical end.**
ISPM's pre-fix form was the sum/mean case - `return 0.0`.

> **Absence has a value in any fold, and that value is the operator's identity
> element.** `max` -> the minimum of the domain. `sum` -> zero. Nobody wrote *"absent
> means favourable"*; they wrote a fold, and **the arithmetic supplied the value.**

And it is worse than incidental, because of what risk scores are:

> **Risk arithmetic starts at safe and accumulates danger.** So **the identity element
> of every common operator is the favourable end** - by construction, not by accident.
> **Every fold over optional contributors in a risk context therefore has this defect
> unless absence is handled explicitly.**

That is why four modules share it without any of them copying the *decision*: they
copied the *arithmetic*, and the arithmetic already contained it.

**The corollary tells you where else to look:** not "other scorers", but **every fold
over optional contributors** - including ones that do not look like scoring.

### 2. Scope: enumerate the class, do not fix the named instances

The audit names **four** sites: `secrets/scoring.py`, `risk/engine.py`,
`exposure/engine.py`, and **`soc/correlate.py:_mission_context`** *(the fourth,
supplied after this ECR's first draft named only three - the reconciliation gap is
corrected here)*. **The list is evidence of the class, not the scope.**

**Fixing the named ones would be rule 29 committed inside the repair for a class** -
the exact error ECR-0074 was raised to correct.

**And the fourth site sharpens the point rather than lengthening the list:**
`soc/correlate.py` is a **correlation** path, not a scorer. An enumeration scoped to
"scorers" would have missed it. The class is **folds over optional contributors**,
wherever they occur.

**Required: enumerate every fold over optional contributors**, and for each record
either the fix or why absence cannot occur there.

**Two passes, because they find different things:**

1. **Byte-identity is cheap and finds the copies.** `secrets/scoring.py` is
   byte-identical to the pre-fix ISPM function - same name, same signature, same body.
   A copied function propagates, so **more copies are likely.**
2. **A copy that has since drifted will not match by name or body.** The class is
   *structural*: a fold over optional contributors that returns a bare value on the
   empty case. **Enumerate by shape with the type system, not by grep** (rule 22 -
   grep was wrong in both directions on C-036's double list).

### 3. `secrets` first, and why it is worse than the others

It is a **credential** scorer. A missing input yielding a favourable number there
means a credential the platform could not assess presents as **well-governed** -
which is precisely the outcome **ECR-0054 §3.1a** was written to prevent
(*"a score must not average away a known exposure"*), arriving through a different
door.

And it is **the same function**, so the fix is known-good: ECR-0074's remedy applies
unchanged. That makes it both the highest-consequence instance and the cheapest.

### 4. The repair is not done until the guarantee can see it

**ECR-0075's prescription is half the work**: score-producing paths discovered from
source, with omission failing closed. **This ECR must verify that discovery actually
reaches each repaired site.**

**Per site, mutate the fix back and confirm the guard turns red.** If any site's
reversion leaves the guard **green**, ECR-0075's discovery has a gap - and that is a
**finding, not a nuisance**, because it means the next instance arrives unguarded.

**Fixing four sites and leaving the fifth invisible is the failure mode this ECR
exists to close.**

### 5. Do not assume absence means unknown

ECR-0074 §4 put an open question to the owner about 19 declined units, and its point
applies here: **"not supplied" and "supplied as not-applicable" look identical at the
fold**, and they are different states.

- **not supplied** -> `unknown`, excluded from the denominator (ECR-0040)
- **supplied as not-applicable** -> a **declared** value, not an absence

**For each site, determine which absence actually occurs before choosing the fix.**
Treating a declared not-applicable as unknown would be the inverse error - manufacturing
an unknown where the owner has answered - and U4 already showed what that costs in
roadmap noise.

Where the answer is genuinely unclear, **record it as unknown and say so**; an honest
wrong-cause is better than an invented right one, and it stays visible.

### 6. Proof

- **The enumeration is recorded**, both passes (§2), with a per-site disposition.
- **Per site: the real scorer** driven with a missing contributor yields **`unknown`,
  excluded from the denominator** - not a favourable value. **Driven through the real
  composition, not a spy** (the ECR-0040 method, and the method that verified ECR-0074).
- **Per site: mutation.** Revert the fix; the named guard turns **red**. A site whose
  reversion stays green is a **discovery gap in ECR-0075**, reported as such.
- **`secrets` additionally:** an unassessable credential does **not** present as
  well-governed (ECR-0054 §3.1a).
- **Absence classification recorded per site** (§5).
- Both backends, both tenant modes, `python -O`.

### 7. Not in scope

The **19 declined units** and the **privileged read with four dependents** remain the
owner's and are unaffected by this repair. ECR-0075's discovery mechanism itself is
**not re-specified here** - this ECR consumes it and reports where it does not reach.

### 8. C-041 progress record

- **A1 landed first and separately:** `C-041_A1_Fold_Identity_Audit.md` enumerates
  the class before any repair. It found four adapters plus the EA-0013
  float-only contract boundary that would otherwise erase a typed fix.
- **A2 classified the owner states:** `C-041_A2_Absence_Classification.md`
  records provider-unconfigured, input-missing, assessment-incomplete, and
  explicit-impact states. None of the affected owners has a declared
  not-applicable token; explicit `0.0` remains known.
- **A3 uses an EA-0013-owned `RiskMissionContext`:** the context crosses
  `score_risk`, persists on risks, and is carried by newly scored exposure and
  SOC records. Outer denominator scorers exclude unknown; max-based risk and SOC
  paths retain the typed state and use the conservative upper bound.
- **The shipped score change is intentional:** inputs previously folded to the
  favourable identity now score no more favourably and retain their unknown
  cause. Credential governance loses known coverage when mission input is
  absent, so an unassessable credential cannot present as well-governed. This is
  correction of a pre-existing wrong answer, not a regression.
- **A4 closes ECR-0075's discovery gap:** the central guarantee discovers 19
  production paths from shipped source. Seven have behavioral cases and twelve
  non-scoring or owner-health paths carry explicit reasons. Registry equality
  fails closed when a new path appears or an existing path disappears.
- **Every A3 repair is centrally guarded:** independent reversions of the EA-0013,
  EA-0023, EA-0032, and EA-0015 adapters, plus the EA-0013 `score_risk`
  contract boundary, each turn the central guarantee red. The controls run under
  optimized Python as well as the normal interpreter.
- **A5 records the score correction:** records with missing mission input may
  now score less favourably than their historical output because unknown no
  longer enters a fold as its favourable identity. Explicit owner-reported
  `0.0` remains known and unchanged. This is the intended correction that the
  first deployment inherits.

## ECR-0077 - The privileged read, resolved: manual capture, handed in, no privileged collector

**Raised by:** the owner's decision, 2026-07-29, closing the item ECR-0073 §6 opened.
**Status:** Accepted - owner directed it 2026-07-29 ("ok do it"); W1-W7 shipped,
and the reviewer verified the fresh private corpus on 2026-07-29.
**Implementation closes:** the four dependents - U3's proxy topology, U3's listener attribution,
baseline C1, baseline C5.
**Number:** next free per the reviewer; **re-check `ECR-LOG.md` before merging** (rule 1).

### 1. The distinction ECR-0073 drew, and what it makes possible

ECR-0073 §6 recorded that **read-only and unprivileged are different constraints, and only
one was chosen**: read-only was adopted deliberately; unprivileged was **inherited from how
collection happened to run.** A privileged read changes nothing on the estate.

That left a decision, and the decision looked expensive - a privileged collector on a live
production box running services that move money.

**It is not that decision.** The objection does not apply, because:

> **The driver does not need privilege. The owner needs it, once.**

Every engine consumes **handed-in documents**. A document produced by a privileged command
**run manually by the owner** is indistinguishable, to every engine, from one the driver
produced. So the capability arrives with **no privileged collector, no elevated automation,
and no new standing risk surface.**

### 2. What is preserved, by construction

- **No privileged automation.** No `sudo` for any code, no root-running scanner, nothing
  scheduled. The elevated step is a person typing commands once.
- **Read-only holds.** The commands dump configuration and list state; **none mutates.**
- **The handed-in boundary is unchanged.** Nothing under `src/aqelyn/` learns a host exists,
  and the driver gains no privileged path (S-003 U3 §2, ECR-0070's enumerated command list
  remains the driver's contract - **these commands are not added to it**, because the driver
  does not run them).
- **Nothing restarts, reloads or is stressed** on a production box.

### 3. What is new, and it is the sensitive part

**A proxy configuration is materially more sensitive than a socket table.** It can carry
certificate paths, upstream credentials and internal topology.

**ECR-0069 therefore applies harder to these documents than to anything collected so far:**

| | |
|---|---|
| local disk only | **yes** - alongside the other collection documents |
| committed as a fixture | **never** - reproducibility is not worth committing the estate's topology |
| PR body, shared report, density output | **never** - counts and classes only, as before |
| the density report | unchanged - it remains structurally incapable of per-asset detail |

**The temptation this time is stronger than before**, because a hand-captured document is
awkward to reproduce and committing it would make the run repeatable. **That is exactly the
trade ECR-0069 forbids.**

### 4. Two disciplines the new evidence requires

**(a) Pin the capture.** A configuration dump is a **point-in-time snapshot**, like the KEV
catalogue. A derivation citing it must cite **which** capture, or it replays against a
moving target - the ECR-0067 shape arriving through data rather than code.

**(b) Freshness across documents is a real join hazard.** The socket observations and the
proxy configuration are **captured at different times**. Joining a listener observed at one
moment to a topology captured at another can produce a confident wrong answer - a service
that has since restarted, moved, or been reconfigured.

> **Record each document's capture time, and make a stale join refuse rather than resolve.**
> The tolerance is an owner decision; the *distinguishability* is not. A join across
> documents whose ages are unknown is the same defect family as an unpinned catalogue.

### 5. What each dependent becomes

| dependent | before | with the capture |
|---|---|---|
| **listener attribution** (U3) | 14 of 16 unattributable | most should attribute; **the state must not be removed** - some may still not join |
| **two-hop chain** (U3) | not derivable | derivable **where the configuration declares it** |
| **baseline C1** | not checkable | **checkable** |
| **baseline C5** | not checkable | **partly** - see below |

**C5 needs two things, not one.** The certificate *path* comes from the proxy
configuration; the certificate's *validity* does not. **Route the certificate metadata to
EA-0032**, which already owns certificate lifecycle with tri-state expiry, chain and
revocation - rather than inventing a validity check inside the baseline comparator. **One
capability, one owner**; C5 becomes a claim evaluated against EA-0032's assessment, not a
bespoke read.

**And U3's three states survive.** Attribution shrinking is the point; **"observed but not
attributable" must remain expressible**, because a listener from a process that has since
exited, or one owned outside the visible namespace, is still exactly that. A state that
becomes rare is not a state that becomes wrong.

### 6. What this does not resolve

- **The 19 declined units** remain the owner's, and are unaffected.
- **The remaining first-deployment items** are unaffected - this is not a deployment.
- **`FIRST_DEPLOYMENT_ITEMS.md` gains nothing and loses nothing**; the privileged read was
  never in it, because it was never deployment-gated. That was ECR-0073's finding and it
  holds.

## ECR-0078 - Configuration is its own exposure basis

**Raised by:** Codex during S-004 W5 implementation.
**Status:** Accepted - owner directed S-004 on 2026-07-29 ("ok do it"), and the
reviewer verified the configuration-derived routes against the fresh private corpus.

### Problem

EA-0023's `ExposureBasisKind` can name inventory, telemetry, access, graph, and
host state. S-004 W5 derives a front-end-to-upstream route from a fresh handed-in
proxy configuration. None of the shipped tokens names that source class.

Using `host_state` would claim the route was observed in the running socket
state. Using `graph` would claim an EA-0005 path. Using `telemetry` would claim
an EA-0019 event that does not exist. The full basis is replay-pinned by
EA-0023, so any convenient substitute becomes a durable false audit fact.

### Decision

- Add `configuration` to `ExposureBasisKind` and `VALID_BASIS_KINDS`.
- Preserve every existing token and default. `ExposureBasis.kind` remains
  required, so no existing caller changes meaning.
- A configuration-derived route cites the exact content-addressed proxy capture
  and route. The host listener evidence remains a separate `host_state` basis.
- Off-estate or ambiguous upstreams remain typed unknowns and do not mint a
  configuration surface row.

`ExposureRecord.basis` is stored as JSONB with no database enum or CHECK
constraint, so this additive vocabulary change requires no DDL migration.

### Proof

- Two nginx server blocks produce only their declared routes, never a flattened
  cross-product.
- A local route reaches the real EA-0023 owner with both `configuration` and
  `host_state` bases.
- Existing omitted behavior is unchanged because there is no omitted-kind
  default.

## ECR-0079 - Typed supplemental status must survive the density reporter

**Raised by:** Codex during S-004 W7 convergence.
**Status:** Accepted - owner directed S-004 on 2026-07-29 ("ok do it"), and the
reviewer verified the count-only convergence report against the fresh private corpus.

### Problem

`FactorReading` already carries `status=known|unknown`, but
`density_report()` unconditionally added every supplemental
`report.coverage_factors` entry to the unknown counter. S-003 began placing
surface, baseline, and mission readings in that collection, including known
ones. The platform could resolve a factor correctly while the roadmap continued
to report it as unknown.

S-004 makes the defect operational: privileged attribution and declared
topology can close exposure unknowns, and C1 can become checkable, but the report
would show no improvement. That is not conservative uncertainty; it is a
reporting contradiction.

### Decision

- Count a supplemental reading according to its typed status.
- Only unknown readings contribute reasons, structural counts, and closable
  roadmap density.
- Do not infer status from source text or reason prose.

Historical S-003 density output may show more known and fewer unknown factors.
That is correction of a pre-existing wrong report, not a scoring change.

### Proof

- One known and one unknown supplemental exposure reading render as
  `known=1 unknown=1`.
- Reverting the status branch turns the dedicated control red.
- The S-004 end-to-end count-only report reflects W4-W6 owner results and emits
  no capture or asset identifiers.

## ECR-0080 - A documented flag silently defeats the freshness gate

**Raised by:** the reviewer, during the S-004 recapture - **by making the mistake, not by
finding it.**
**Status:** Accepted - the producer timestamp semantics and `--reuse` preservation shipped
in PR #263 (`main @f2c573c`).
**Severity:** **the bypass is on the convenience path**, not an edge case (§4).
**Number:** next free per the reviewer; **re-check `ECR-LOG.md` before merging** (rule 1).

### 1. The defect

`--reuse` returns **cached document content** while setting `collected_at` **fresh**. A
recapture therefore produced a document stamped minutes old carrying unit details from two
days earlier - process identifiers from a **different boot** - and attribution came back
**0 of 20**.

**W3's freshness gate compared two `collected_at` values twelve seconds apart and resolved
happily.**

### 2. The gate is correct. Its input lies to it.

This is worth stating carefully, because the instinct is to fix the gate:

> **W3's gate does exactly what it was specified to do.** It compares capture times and
> refuses beyond tolerance. **Nothing is wrong with it.** What is wrong is that one of the
> values it compares does not mean what the gate assumes it means.

**A guarantee inherits every ambiguity in the fields it reads.** The gate's correctness is
contingent on a semantic that lives **outside the gate**, and nothing enforced that
semantic.

### 3. The root: one field, two meanings, nobody chose

`collected_at` conflates:

| | meaning |
|---|---|
| **(a)** | when **this document was produced** |
| **(b)** | when **the content it describes was true** |

**For a fresh capture these are identical, so the conflation was invisible.** `--reuse` is
the first operation that makes them differ - and when they differed, a code path picked (a)
while the gate assumed (b). **Neither choice was made deliberately**; the field's meaning was
never pinned, so each site chose independently and correctly-looking.

**This is the absence-is-the-fold's-identity shape (ECR-0076) in a different register**: not
an unwritten decision about a *value*, but an unwritten decision about a *meaning*. Nobody
wrote *"`collected_at` means when the run started"* - they wrote a timestamp, and the
timestamp took whichever meaning its site implied.

### 4. Severity: the bypass is the happy path

`--reuse` exists **precisely so re-runs are cheap**, which makes it the flag anyone
re-running will use. **The bypass is therefore not exotic - it is the default convenience
route**, and the reviewer hit it **on the first try**.

> **A guarantee that a documented flag defeats silently is not a guarantee.** It is a
> guarantee for people who do not use the documented flag.

### 5. The fix: pin the meaning, and `--reuse` has no choice

**Do not start from `--reuse`.** Starting there produces *"make `--reuse` preserve the
timestamp"* - correct, and it leaves the next producer free to choose again.

> **Define `collected_at` at the field: the time the described content was true.** Then
> `--reuse` preserving the cached value is not a special case; it is the **only** thing it
> can do, and any future producer that sets it otherwise is wrong by the definition rather
> than by convention.

**The reviewer's route (b) - refusing `--reuse` for any document a freshness gate consumes -
is a fallback, not the answer.** It makes caching unusable for exactly the documents where
caching is most valuable, and it is a prohibition where a definition would do.

**If the two meanings are both genuinely needed**, add a second field for *"when this run
read it"* - never overload the one the gate consumes. **Two meanings, two fields** is the
same discipline this platform applies to unknown-versus-absent everywhere else.

### 6. The mutation that would have caught it - and why the existing one did not

W3 was proven by driving documents whose capture times **differ**. That mutation exercises
the comparison and cannot detect a **lying producer**, because both values it is handed are
honest.

> **Mutate the producer, not the values.** Rule 31 says: for *A must equal B*, mutate **A or
> B, never the comparator**. This extends it - **also mutate what fills A and B.** A gate
> whose inputs are always produced correctly has never been tested against the case where
> they are not.

**Required control:** a producer that sets `collected_at` to the read time rather than the
capture time **must make the gate refuse**. Under the current code that mutation **passes**,
which is the defect stated as a test.

### 7. Recorded because it is the third instance

The reviewer **nearly filed 0-of-20 as a W4 defect** before checking. That is **rule 32** -
a check manufacturing a finding as readily as missing one - and it is now the **third**
occurrence: the `pid=1` fixture, the ad-hoc status regex, and this.

**All three came from the reviewer's own instrument rather than from the product**, and all
three were caught by the same move: **investigating the surprise instead of reporting it.**
Worth recording as a pattern about *who checks the checker*, not as three separate incidents.

### 8. Not in scope

The **S-004 outcome stands and needs no rework** - the four dependents resolved against a
genuinely fresh corpus, C1 to `pass`, **C5 to `certificate_lifecycle`** (moved to EA-0032,
which declined to establish validity rather than inventing it), C2/C3 correctly still
`collection_scope`, and `roadmap_dependencies: none`.

**Both pre-registered checks held**: attribution improved from 2/14 to 18/2 **without** the
*observed-but-not-attributable* state vanishing - two listeners remain in it, so it stays
exercised.

## ECR-0081 - A new track, and the rigor that does not transfer to it

**Raised by:** planning, on the owner's direction 2026-07-29 ("go").
**Status:** Accepted - owner directed it.
**Number:** next free; **re-check `ECR-LOG.md` before merging** (rule 1).

### 1. Why a new track rather than S-005

**The instrument stopped naming work.** After S-004, `roadmap_dependencies: none`; the
four-way tie has resolved; what remains closable is **C2/C3** (one small collection change)
and the **19 declined units** (one owner decision). **The density report was built to say
what to connect next, and it has stopped naming anything substantial.**

That is the signal to stop connecting. Further S-milestones would improve **correctness** -
they have been extremely productive at it - but none of them changes what the platform
**is**, because every one of them ends at a terminal.

**P-001 opens the P track: making the platform usable by a person.** Different question,
different acceptance, and that is the point of separating it.

### 2. The rigor question, stated because it will otherwise be applied wrongly

**Forty-one milestones have run on one discipline: *verify against shipped code, refuse to
guess*.** It has been correct every time. **It does not fully transfer here, and applying it
anyway would stall the milestone.**

**A surface has nothing to verify against.** *What should the report show first? What does a
non-expert need to see?* No repository answers those. The only test is showing it to a
person.

**What still applies, without exception:**

| | |
|---|---|
| **unknowns render as unknowns, with their reasons** | the differentiator, and the easiest thing to quietly drop when a report looks better without them |
| **ECR-0069's boundary** | the findings report carries per-asset detail; the density report carries counts. **Two reports, two boundaries** - do not blur them |
| **nothing invented** | no placeholder findings, no sample data, no illustrative numbers |
| **the derivation must be viewable** | a replayable derivation nobody can look at is worth the same as no derivation |
| **the platform proposes; it does not act** | the report must not read as though anything was done |

**What does not apply:**

> ***"Do not claim what you have not verified"* governs claims about shipped code. A design
> choice is not that kind of claim.** It is a decision made, then tested by use. **Waiting
> for evidence that does not exist yet is how this milestone fails to start.**

**And the acceptance mechanism changes.** Not mutation-verified guarantees - those cannot
answer *"is this legible?"* The acceptance test is:

> **Can someone who did not build this read one finding and answer: what is the problem, how
> bad is it and why, what do we not know, and what would I do about it?**

### 3. On the first reader

**The owner reading it is a weaker test than a stranger reading it**, because the owner
knows what the platform does. That does not make it useless - it is the reader who is
available - but **the result should be recorded as the weaker test it is**, and not treated
as evidence that the report is legible to a newcomer.

### 4. What this track is not

**Not the `C-700` column.** No server, no HTTP API, no authentication, no multi-user
operation, no connectors, no dashboard. **One command, one report, one machine.**

Those remain real and remain unbuilt; P-001 is the smallest change that makes the platform
something a person can use, and it needs none of them.

## ECR-0082 - Absence exiting the fold: excluded weight is redistributed to the survivors

**Raised by:** **P-001**, on its first run against the real corpus - **the defect was visible
because the report made the exclusions legible**, after forty-one milestones in which it was
not.
**Status:** Accepted — implemented and reviewed in PR #269 (`main` @1fffaa8).
**Amended by ECR-0083** on the total-score monotonicity property: that property was
replaced by **sibling-contribution invariance**, because monotonicity and GC-001's strict
unknown-not-favourable rule cannot both govern the total score. The all-weight denominator,
the `known_weight <= 0` refusal and the scorer enumeration in this ECR stand as written.
**Severity:** **high - demonstrated wrong answer on real data.** 114 findings occupy the top
band on almost no evidence, and they **outrank the single KEV-confirmed exploited
vulnerability.**
**Number:** next free per the reviewer; **re-check `ECR-LOG.md` before merging** (rule 1).

### 1. The measured curve, and why its shape is the diagnostic

4,117 real findings, grouped by how many factors were **excluded** as unknown:

| factors excluded | mean score |
|---|---|
| 3 | 76.9 |
| 4 | 53.4 |
| 5 | 30.3 |
| **6** | **90.0** (n=114) |

**Scores fall as evidence thins - and then jump to the top band when almost everything is
unknown.**

**The shape is the finding, not the 90.0.** The monotone decline across 3-4-5 is an averaging
effect; the jump at 6 is where **so few factors survive that a single high-valued one becomes
the score.** One finding read directly: **six factors excluded, only Trust known, rendered
`Immediate`.**

### 2. The mechanism: two scorers, two normalisations

| module | normalises by | consequence |
|---|---|---|
| `ispm/scoring.py` | **total weight, including unknowns** | knowing less **lowers** the score - `known_only x coverage_adjustment` |
| `vuln/engine.py:614` | **known weights only** | one known factor normalises to weight **1.0**; its value **becomes** the score |

**`vuln` applies no coverage adjustment at all.** The absent factors' weight is not
discarded - it is **redistributed to whatever survives.**

### 3. It is not merely unpenalised. It is inverted.

If exclusion were only unpenalised, low-coverage findings would score *like* high-coverage
ones. They score **higher**, and the reason is statistical rather than semantic:

> **Fewer surviving factors means higher variance.** A score computed from six factors tends
> toward their mean; a score computed from **one** *is* that factor. So thinning evidence
> **widens the distribution**, and a priority ranking shows only the upper tail - which
> becomes **systematically populated by the findings the platform knows least about.**

**That is not a mis-ranking. It is an inversion of what the ranking is for.**

### 4. Which normalisation is right, and the principle that settles it

**`ispm`'s.** But this is **not** what ECR-0040 required. ECR-0040's accepted
Resolution says that unknown factors receive zero normalized weight and **"known weights are
renormalized."** `vuln/engine.py:614` implements that decision literally. The amplification was
therefore not an implementation drift; it was a conformant result of the accepted record.

> **Removing a voter must not amplify the remaining voters.** Excluding a factor from the
> denominator does not discard its weight; it **hands that weight to the survivors.**
> Discounting and amplifying are opposite operations, and only one of them is what
> "exclusion" was ever supposed to mean.

**This ECR amends ECR-0040's Resolution.** ECR-0040 remains authoritative for the typed
`known|unknown` factor, the retained source/reason/raw weight, and the requirement that unknown
never contribute an invented value. It is superseded only on normalization: configured unknown
weight remains in the denominator and is not redistributed to known factors.

The later credential-score analysis stated this explicitly in
`IS-035_Conformance_Analysis.md:71-75` (rules 4/5, ECR-0040), one module over:

> *"Denominator exclusion alone is insufficient: without the coverage adjustment, a credential
> with one known-good factor and nine unknowns scores like one with ten known-good factors -
> i.e. 'unknown' silently becomes 'present'."*

**Resolution: `vuln` adopts the numeric equivalent of
`known_only x coverage_adjustment`**, matching `ispm` and `secrets`:

> `sum(known weight x value) / sum(all configured weights)`

The numerator still contains only known factors. The denominator contains every configured V3
factor, including unknowns, so removing a known factor cannot amplify the survivors. A separate
`known_weight <= 0` guard **must continue to refuse an all-unknown finding**; widening the
denominator must never turn that refusal into `0.0`, the most favourable score on this scale.

Per **rule 29**, the closing question is not *"is `vuln` fixed"* but ***"which other scorers
normalise by known-only?"*** - enumerated with the type system, not grep (rule 22), and every
composition scorer checked, not only the two named here.

### 5. The defence that does not hold

**"EA-0024 reports coverage separately, so the consumer can combine them."** Coverage is
mandatory in EA-0024's spec, so this is a real design possibility rather than an oversight.

**It fails on the use.** A priority score exists **to order a list.** If the number that
sorts the list is uninterpretable without an adjacent number, then:

> **A priority score that requires a second figure to be read correctly is not a priority
> score.** Either the coverage adjustment is inside it, or it cannot order anything - and
> sorting is the only thing anyone does with it.

P-001 is the proof: the report sorts by this score, and the top of the list is wrong.

### 6. GC-001 AC-3's **fourth** gap - and the property that is missing

**AC-3 passes, and the defect exists.** AC-3 asserts that **unknown is not the favourable
result** - and in `vuln` an unknown factor does not make a finding look *safer*. It makes it
look **more certain**, by amplifying whatever remains. **The guard checks the direction of
unknown's effect on one factor; it says nothing about what exclusion does to the weight of the
others.**

That is the **fourth** AC-3 gap, and the third of a distinct kind: per-scorer -> per-factor
(ECR-0066), unwired -> all provider states (ECR-0068), representation-bypass (ECR-0075), and
now **effect-on-siblings**.

**The missing property, stated so it is testable:**

> **Coverage monotonicity - for any finding, removing a known factor must not increase its
> score.**

**Comparable by construction**, because it compares a finding **to itself** with less
evidence, which sidesteps the incommensurability of two different findings. **Mutation-
testable directly**, and it fails against `vuln` today. **GC candidate**, in the
discovery-not-declaration form: enumerate composition scorers, assert monotonicity on each,
**negative control** being a scorer that normalises by known-only.

### 7. Not a P-001 defect - and the argument for the P track, made by the P track

**The report is correct.** It renders the exclusions faithfully, names Trust as the sole
survivor, and shows six factors as `Not scored / Excluded / 0 points` with their causes. **It
is why the defect is visible at all.**

Forty-one milestones did not surface it because the implementation was **conformant with
ECR-0040's accepted decision**. ECR-0040's Q5 proof correctly established that an unknown factor
contributes neither a favourable zero nor an invented value. It did not ask what removing that
factor from the denominator hands to its known siblings. The defect is in that **relationship
between values**, which remained outside the accepted test until a person read the results side
by side, ordered.

**P-001's stated purpose was to make the platform usable. Its first run made the platform
*correctable* in a way no engine milestone had.**

### 8. Scope

- **`vuln/engine.py` uses all configured V3 weights as the denominator and known factors only
  in the numerator**; scores change materially and **records with thin evidence will drop out
  of the top band.** This is algebraically the existing `known_only x coverage_adjustment`
  pattern, without a second multiplier.
- **Preserve a separate all-unknown refusal.** `known_weight <= 0` raises
  `VulnConfigInvalid`; it must never return `0.0`. Tests prove both the refusal and a genuine
  known factor with value `0.0`, so absence and an explicit favourable value remain distinct.
  This is the correction, not a regression - and per the C-041 precedent it is **a record for
  the first deployment**, not a communication, since there are none.
- **Enumerate every composition scorer** for known-only normalisation (rule 29 / rule 22).
- **Coverage monotonicity** raised as a GC milestone rather than folded here.
- **Re-run P-001's report** afterwards: the top band is the acceptance evidence, and the
  KEV-confirmed vulnerability should be in it.

## ECR-0083 - stable weights do not define an unknown factor's contribution

**Raised by:** Codex, while implementing ECR-0082 against the shipped GC-001 AC-3
guarantee.
**Status:** Accepted — implemented and reviewed in PR #269 (`main` @1fffaa8), with `u = 0.25`
pinned on the full 10,173-finding corpus rerun (§5) and all eight proof items in §6 verified
behaviourally, including the four required mutations.
**Severity:** **blocking before the EA-0024 arithmetic changes.** The prescribed formula
repairs the demonstrated amplification but violates an Accepted central guarantee on the same
real scorer.
**Number:** next free after ECR-0082; **re-check `ECR-LOG.md` before merging** (rule 1).

### 1. The contradiction, measured before implementation

GC-001 drives the real `vuln` scorer with the same finding while only the exposure factor
changes:

| exposure state | shipped score | ECR-0082 all-weight formula |
|---|---:|---:|
| proved safe (`known`, value `0.0`) | 64.0 | 64.0 |
| unknown | 80.0 | **64.0** |
| proved bad (`known`, value `1.0`) | 84.0 | 84.0 |

The shipped `80.0` is wrong for the reason ECR-0082 records: removing exposure's configured
weight from the denominator amplifies every surviving factor. But `64.0` is also wrong under
GC-001 FR-7, which requires every lower-is-favourable scorer to make unknown **strictly less
favourable than known-safe**, and more directly under FR-9:

> Out-of-set kinds and unknown factors SHALL resolve toward **rejection / non-favourable**,
> never toward a permissive default (rule 5).

ECR-0082's formula maps unknown to the most favourable contribution on this scale. Weakening the
central case would therefore repeal a house rule, not tune a local assertion.

This is structural, not a fixture choice. For a factor with configured weight `w`:

- known-safe contribution under an all-weight denominator: `w x 0.0 = 0.0`;
- unknown contribution when it is excluded from the numerator: `0.0`.

No test data can make those values different. Weakening
`test_gc_scorer_unknown_not_favourable` to accept equality would silently repeal
`GC-001-guarantee-conformance-suite.spec.md:253`, not implement ECR-0082.

### 2. The orientation flip, and why total-score monotonicity cannot govern

**ECR-0082 imported `ispm`/`secrets` arithmetic across an orientation flip.** On a
**higher-is-favourable** scale, "unknown contributes `0.0`" pushes away from favourable, so the
all-weight formula is conservative in `ispm` and `secrets`. On `vuln`'s
**lower-is-favourable** scale, the identical arithmetic pushes toward favourable. The formula did
not change; the meaning of zero did.

`vuln` is the only lower-is-favourable composition scorer in the discovered set.
`tests/guarantees/test_scorers.py:289,295,301` records the three orientations as
`higher_is_favourable`, `higher_is_favourable`, and `lower_is_favourable`. That sole-outlier
shape is the transferable diagnosis: a future scorer can reproduce the defect by copying correct
arithmetic from a scorer with the opposite orientation.

The same sibling comparison exposes another asymmetry at the implementation boundary.
`validate_replayable_priority` exists, but `_priority_derivation` embeds the already-computed
score as `score_unit`; replay proves that embedded number is internally replayable and that the
stored factor payload matches `factor_sources`. It does **not** recompute the score from those
factors. `ispm` and `secrets` register their score operations and recompute the result, including
the credential uncertainty penalty. Without the same recomputation, a vulnerability surcharge
could drift from the factor payload while both the stored score and its self-referential
derivation still agree.

ECR-0082 states:

> For any finding, removing a known factor must not increase its score.

GC-001 AC-3 states, for a lower-is-favourable scorer:

> Replacing a known-safe factor with unknown must increase the score.

Take a known-safe factor whose value is `0.0`. The first statement requires
`unknown_score <= safe_score`; the second requires `unknown_score > safe_score`. Both cannot be
true.

The valid invariant inside ECR-0082 is narrower and is exactly what its finding demonstrated:

> **Sibling-contribution invariance:** changing factor A from known to unknown must not change
> the normalized weight or contribution of any factor B.

That property catches known-only renormalization directly, is orientation-independent, and does
not prescribe what factor A's own uncertainty contributes.

### 3. What remains correct in ECR-0082

The real-data finding, severity, and P-001 evidence remain unchanged:

- known-only normalization redistributes excluded weight and produces the trust-only `90.0`;
- configured all-factor weight must remain in the denominator;
- a separate `known_weight <= 0` refusal must keep all-unknown distinct from a genuine known
  `0.0`;
- the rule-29 enumeration must cover every discovered composition scorer;
- the report must be rerun, and thin evidence must no longer populate the top band by
  amplification.

This ECR amends only ECR-0082's total-score monotonicity property and the incomplete numeric
remedy.

### 4. Owner decision: typed uncertainty surcharge

Once sibling weights are stable, a lower-is-favourable scalar scorer still needs an explicit
answer to:

> **What does an unknown factor contribute to vulnerability priority?**

**The owner selected a typed uncertainty surcharge on 2026-07-30.** EA-0024 keeps one scalar,
but the factor and uncertainty terms remain structurally separate:

> `known_score_unit = sum_known(w x v) / sum_all(w)`
>
> `unknown_weight = sum_unknown(w) / sum_all(w)`
>
> `uncertainty_surcharge = u x unknown_weight`
>
> `score = 100 x clamp(known_score_unit + uncertainty_surcharge)`

Every unknown factor retains its configured `raw_weight`, `status="unknown"`, and typed cause,
while its normalized `weight` and `contribution` remain `0.0`. The surcharge is a separate,
replay-pinned score term outside the factor records. It SHALL NOT be represented by assigning an
unknown factor normalized weight or value `u`: that algebraically equivalent encoding silently
repeals ECR-0040's zero-normalized-weight guarantee, five discovered-provider assertions, and
the fixed wired-mission absence assertion.

This is the orientation-reversed analogue of `secrets/scoring.py:188-200`, where
`uncertainty_penalty` is a separate result term rather than a factor weight. The shipped
`GOVERNANCE_UNKNOWN_PENALTY_POINTS = 10.0` is equivalent to `u = 0.10`, a useful precedent but
not a vulnerability-policy decision. `u = 0` is the contradiction in §1; any `u > 0` satisfies
FR-7 and FR-9 strictly for a positive unknown weight. The guarantees do not determine the
magnitude.

The other two shapes are not selected and are not neutral alternatives:

- **A score interval requires a second figure to interpret or a rule that collapses it to one
  sortable value.** ECR-0082 §5 rejects the first; the second is this surcharge policy with more
  surface.
- **Refusing every partial priority reverses ECR-0040 Problem 1**, which rejected discarding the
  known CVSS, EPSS, threat, mission, baseline, and Trust claims merely because one owner is
  unknown.

The following are not resolutions:

- silently treating unknown as `0.0`;
- retaining known-only renormalization because it happened to put unknown between the two
  controls;
- weakening GC-001's strict unknown-not-favourable assertion;
- inventing a surcharge value inside the implementation ticket.

### 5. Measured bounds for `u`; candidate, not pinned

The surviving real-estate slice contains 302 findings and 1,383 unknown factors. It reproduces
the full corpus's diagnostic shape before any surcharge:

| factors excluded | slice count | slice mean | full-corpus mean |
|---:|---:|---:|---:|
| 4 | 163 | 50.09 | 53.4 |
| 5 | 103 | 31.46 | 30.3 |
| 6 | 36 | 90.00 | 90.0 |

The top five slice findings are all `90.0` and all exclude six factors. Sweeping the selected
formula gives:

| `u` | six-excluded cohort | mean by excluded (4 / 5 / 6) | thin evidence in top 20 | bands |
|---:|---:|---|---:|---|
| 0.00 | 4.50 | 17.5 / 4.7 / 4.5 | 0/20 | 302 Low |
| 0.15 | 18.75 | 27.3 / 17.5 / 18.8 | 0/20 | 302 Low |
| 0.25 | 28.25 | 33.8 / 26.0 / 28.2 | 0/20 | 289 Low, 13 Medium |
| 0.35 | 37.75 | 40.3 / 34.5 / 37.8 | 0/20 | 211 Low, 91 Medium |
| 0.50 | 52.00 | 50.0 / 47.2 / 52.0 | 0/20 | 302 Medium |
| 0.75 | 75.75 | 66.3 / 68.5 / 75.8 | 20/20 | 234 Medium, 68 High |
| 1.00 | 99.50 | 82.5 / 89.7 / 99.5 | 20/20 | 117 High, 185 Immediate |

The measurement excludes two unsafe regions:

- `u = 1.0` is worse than the defect it repairs: the six-excluded cohort reaches `99.5`, and
  185 of 302 findings become Immediate.
- `u >= 0.5` re-inverts the cohort ordering by a new mechanism. At `u = 0.5`, the
  six-excluded cohort overtakes the four-excluded cohort; at `u = 0.75`, thin evidence occupies
  all of the top 20.

The hard constraints established here are `u > 0` (FR-7/FR-9) and approximately `u < 0.5`
(avoid the measured re-inversion). The `0.15-0.35` range describes the useful cohort placement
observed in this slice; it is not a validity floor. The credential precedent `u = 0.10` is valid
and more conservative than the selected vulnerability value.

The 302-finding slice carries **zero KEV-confirmed findings**, so it could not pin the policy.
Before implementation, Codex reran the same sweep against the retained full-host inputs:

- `vulns.json`: 10,784 scanner matches,
  SHA-256 `67b45f4fe9cd8247bc34f2523fd23b0b365ca4c962a0e80d2e61979b170afc9f`;
- `kev.json`: 1,653 catalogue entries,
  SHA-256 `036c579ee00120ad6b77a9e391ef96c96bd7ba4ab060214df0d79ddda2e64ce6`;
- real owner path: 10,173 findings, zero rejected matches, one KEV-confirmed finding.

At `u = 0.25`, the excluded-factor cohort means for 3 / 4 / 5 / 6 unknowns are
`53.57 / 34.85 / 25.78 / 28.25`; no six-excluded finding appears in the top 20; the
distribution is 10,168 Low and 5 Medium; and the KEV-confirmed vulnerability is first by score
at `53.569` (Medium), with three excluded factors. The full-corpus result confirms the slice
rather than reversing it, so **this implementation pins `u = 0.25`**. Cross-finding ordering by
unknown count remains product evidence, not a guarantee: FR-7/FR-9 are per-finding and
sibling-contribution invariance remains the central property.

### 6. Required implementation proof

1. The rule-29 discovery registry covers `ispm`, `secrets`, and `vuln`, records each scorer's
   orientation as a first-class fact, and fails when a fourth composition scorer is added without
   a case or is assigned the wrong orientation.
2. Changing one factor to unknown leaves every sibling's normalized weight and contribution
   byte-identical.
3. On the real `vuln` scorer, proved-safe, unknown, and proved-bad retain the owner-approved
   ordering; unknown is strictly less favourable than proved-safe.
4. All-unknown raises `VulnConfigInvalid`; a known factor with value `0.0` remains scoreable.
5. A registered vulnerability scoring operation recomputes the known component and separate
   surcharge from the replay-pinned factors and policy. `validate_replayable_priority` rejects a
   changed score, changed surcharge, changed `u`, or changed factor payload even when the
   derivation is otherwise structurally replayable.
6. P-001 renders the surcharge as its own calculation row, including `u`, unknown raw weight,
   and contributed points. **Measured residual (2026-07-30): a reader can also multiply a row's
   own Signal x Weight and compare it to that row's Contribution; across 20,817 known factor rows
   the worst discrepancy is 0.100 points — exactly one display unit, never more.** That is the
   floor at one-decimal display, not a defect: Signal and Weight are each rounded before the
   reader multiplies them, so "the column sums to the subtotal" and "every row's product is
   exact" cannot both hold. §6.6 requires the column to sum, so the column wins. Recorded so it
   is measured rather than rediscovered. Unknown factor rows remain truthfully `Not scored / Excluded /
   0 points`; the summary states that excluded factors do not receive factor weight but do inform
   the separate surcharge. Factor contributions plus the surcharge visibly sum to the score.
7. Each guard is mutation-proven, including a reversion to known-only normalization, folding the
   surcharge into unknown factor weights, removal of the all-unknown refusal, and bypassing the
   recomputation validator.
8. The unedited P-001 corpus is rerun. The trust-only `90.0` top-band cohort disappears, and the
   KEV-confirmed vulnerability remains first by score at the pinned rate.

### 7. Impact

No production arithmetic changes under this ECR alone. The separate representation and numeric
policy are now both selected; ECR-0082 and this ECR remain Proposed until the implementation,
replay, reporting, guarantee, and real-corpus proofs are reviewed together.

Both back-pointers the status guard cannot infer are now written: ECR-0040's index row and
Resolution clause are marked amended by ECR-0082/ECR-0083, and ECR-0082's total-score
monotonicity property is marked amended by this ECR.

**One consequence of the rate pin, recorded because it is not obvious from the arithmetic.**
`vulnerability_score_result` rejects a stored derivation whose `unknown_surcharge_rate` differs
from the shipped constant, and that rejection is what makes drift detectable at all. It also
means **changing `u` invalidates every previously computed priority**: after a change from
`0.25`, both `validate_replayable_priority` and `recommend()` raise `VulnNotReplayable` on a
priority computed under the old rate, and `raise_vulnerability` inherits the same rejection.
Priorities already persisted into findings by `_finding_for_priority` carry their derivation, so
they are affected too. This is correct fail-closed behaviour — a priority computed under a
different policy must not silently produce a remediation plan — but it makes revisiting `u` a
**data-migration event, not a configuration change.**

## ECR-0084 - `current_severity_score` is maintained and never read

**Raised by:** the reviewer, 2026-07-30, immediately after the EA-0024 scoring repair
(ECR-0082 + ECR-0083) shipped.
**Status:** **Accepted (shape 1)** - selected by **the owner, 2026-07-30**: P-001 annotates
current severity beside the existing first-seen priority headline without changing ordering,
cursor, index, or query semantics.
**Dormancy:** accepted and explicit. P-001's fresh per-run store cannot reach re-emission, so
the consumer is test-reachable but unreachable through `aqelyn-report` until findings persist
across runs. The proposed mechanical rule is therefore refined, not repealed: a code reader
that no shipped path can reach is a consumer for the checker and not for the user.
**Severity:** **latent** today; **it decides whether ECR-0082's repair applies to the
platform or only to its future** (§4).
**Number:** next free per the reviewer; **re-check `ECR-LOG.md` before merging** (rule 1).

### 1. The finding

**ECR-0063 shipped `current_severity_score` so that "escalation becomes visible."** It is
seeded on first raise and written faithfully on every re-emission. **Nothing reads it.**

Every reference in `src/` and `tests/`:

| file | refs | kind |
|---|---|---|
| `findings/postgres.py` | 7 | persistence |
| `findings/ddl.py` | 5 | schema |
| `findings/memory.py` | 4 | persistence |
| `findings/models.py` | 2 | the field itself |
| `tests/conformance/test_finding_cursor_contract.py` | 4 | **asserts the column holds the right number** |

**Zero consumers outside the `findings` package** - no engine, no service, no query filter,
no ordering, no report. **`reporting/` - the one surface a person actually reads - never
mentions it.**

### 2. What that costs, on the real stores

```
finding A: severity_score = 30.0   current_severity_score = 88.0
finding B: severity_score = 60.0   current_severity_score = 60.0

FindingStore.query returns:   B (ranks on 60.0)
                              A (ranks on 30.0)   <- most severe, ranked last
```

Both backends order on the **frozen** key - `findings/postgres.py:353`
(`ORDER BY severity_score DESC, id`) and `findings/memory.py:152` - the ECR-0062 cursor
encodes it, and `ix_finding_status_sev_id` indexes it.

> **The escalated number exists in the row and cannot influence any ordering or reach any
> surface.**

### 3. The family, third time - and a rule of a kind this collection does not have

**ECR-0062** found `FindingQuery.cursor` **accepted and ignored**. This is the **mirror
image**: a field **maintained and unread**. Same class - a contract that looks honoured
because the value is correct, while nothing consumes it.

**And the mirror is worse in one specific way: it has a passing test.** A conformance test
asserts the column holds the right number, so CI confirms the maintenance while nothing
confirms the use.

> **Standing rule 33, selected by the owner on 2026-07-31.** *A test that a field holds the right value proves maintenance,
> not use.* ***Is it read?*** *is the question that decides whether the feature exists, and
> no assertion about the field can answer it.*

**Rule 24 is adjacent but different:** it asks whether a control can ever falsify its
assertion. Here the check is sound and its assertion is true - the field is maintained - but
it proves maintenance, not consumption. **The missing property is a consumer, not a failing
control.**

**It has a mechanical form**, which matters because reading-based checks have failed
repeatedly here: `grep -rn <field> src/ | grep -v <owning package>` returning nothing **is**
the finding. **GC candidate**, in the discovery-not-declaration form - enumerate persisted
fields, assert each has a consumer outside its owning package, with an **allow-list carrying
a reason per entry** for the fields that legitimately have none (internal bookkeeping).
Raised, not folded in.

### 4. The coupling to ECR-0082 - this changes the priority

> **ECR-0082's repair reaches only findings first raised after it. The KEV-confirmed
> vulnerability at rank 1 of 10,173 is a property of a fresh corpus, not of the fix.**

**Verified against shipped code, both halves:**

- **No backfill exists.** `severity_score` is written at insert
  (`findings/postgres.py:182`) and is **absent from the UPDATE statement by design**
  (`:206-215`, whose own comment says so). **No recompute, migration or re-score path exists
  anywhere in `src/`.**
- **The corpus run was all first raises.** `reporting/analyze.py:193` constructs a fresh
  `InMemoryFindingStore` per run, so the 10,173-finding measurement contained **zero dedup or
  re-emission.**

So a finding raised before the repair keeps its pre-repair, inverted score **forever**, while
the corrected value sits unread in the adjacent column.

**ECR-0084 is therefore not adjacent to ECR-0082 - it is the difference between the repair
applying to the platform and applying only to its future.**

### 5. Latent - and precisely what kind of latent

**Do not dramatise it.** P-001 builds findings in-memory per run, so every finding today is a
first raise and `current == severity` always. It becomes live the moment a store **persists
across runs** *and* any finding **re-emits with a changed score** - which includes every
finding that survives a scoring change.

**But it is not a `FIRST_DEPLOYMENT_ITEMS` entry, and the distinction matters.** Rule 25's
corollary records the prior mis-filing (`SPEC_AUTHOR_NOTES.md:260-264`):

| | |
|---|---|
| **registry items** | questions whose **answer** requires a deployment - budget tuning, index seek-vs-filter, migration sequencing |
| **this** | a **defect** whose **manifestation** requires one |

**The answer is knowable now.** Filing it as deployment-gated would defer a decision that
nothing prevents making today. Per the C-041 precedent this is **a record for the first
deployment, not a communication, since there are none.**

### 6. The decision, which is the owner's

**ECR-0063 chose option 3 deliberately and its reasoning still holds.** `severity_score` must
stay **write-once** because the ECR-0062 cursor keys on it, and a mutable sort key reopens the
skip/duplicate hazard C-037 closed. **So *"just order by the current score"* is not available
without reopening closed work.**

**The real question is narrower:**

> **What is `current_severity_score` for, and which surface is supposed to show it?**

| shape | fixes | costs |
|---|---|---|
| **(1) a surface reads it** | **visibility** - P-001 renders escalation beside the rank | none; **does not fix ordering** |
| **(1b) + an escalation filter** | *"what has got worse?"* as a query predicate, **not** a sort key | an index; inherits the mutable-**predicate** phase-change already recorded for `status` |
| **(2) a second ordering** | **ranking** | a second index **and** a second cursor contract on a mutable key; the shipped ECR-0062 OR keyset is already measured non-seeking (28,500 rows filtered / 29,366 buffers / 18.2 ms versus 0 / 6 / 0.156 ms for row comparison + all-DESC), so the cursor/index design must be **redone, not copied** |
| **(3) re-emission raises a new finding** | ordering, free | dedup semantics EA-0003 chose on purpose |

**Recommendation: (1) first**, optionally with **(1b)**. It adds no new ordering contract and
it answers ECR-0063's stated goal - **visibility - which is what is actually unmet.**

**And the cost of (2) is not the index.** It is that **ranking is a claim about priority, and
two rankings is no ranking**: nothing would say which is authoritative, and a reader comparing
them has no rule. **That is a worse state than one wrong ordering**, and it is why (2) is a
separate decision rather than an implementation detail of (1).

### 7. Option (1) hides a sub-decision, and disclosure is its condition

***Showing*** escalation and ***ordering by*** it are different things. ECR-0063 said
*"escalation becomes visible,"* which annotation satisfies **literally** - but **a reader
scanning a priority-ordered list will not see a finding ranked 400th**, whatever badge it
carries.

| sub-shape | effective? | cost |
|---|---|---|
| **annotate** - show both scores where they differ | honest, **possibly useless** | none |
| **re-order in the surface** | **effective** | the report's order then **disagrees with the store's** |

**The second is defensible if the report says so.** A report that orders by current severity
**and states that the store orders on first-seen severity** is honest and useful; one that
silently orders differently is **a trap** for anyone comparing the report against a query.

**That disclosure is the condition, not a nicety** - and it is the same discipline **ECR-0081
invariant 1** already imposes on unknowns: **the caveat travels with the claim.**

### 8. Carry-forward this must not weaken

- **`severity_score` stays write-once** (ECR-0062 cursor safety; C-037's cleared hazard).
- **No second mutable sort key** without redoing the ECR-0062 skip/duplicate analysis
  **against it**. `status` is already a mutable *predicate* on the leading index column, and
  that residual is **recorded, not fixed**.
- **Anything P-001 renders must sum and reconcile** - three passes were needed on ECR-0083
  §6.6, and the measured floor is **one display unit at one-decimal display**.

## ECR-0085 - GC-004: persisted fields must have consumers, and dormancy must be declared

**Raised by:** ECR-0084 §3, which proposed the guard and deliberately did not fold it in.
**Status:** Accepted - GC-004 shipped.
**Number precedent:** GC-001 <- ECR-0057, GC-002 <- ECR-0058. **GC-003 does not follow that
shape** - its guard (`tests/guarantees/test_service_health.py`) is recorded in
**`C-038_Task_Bundle.md` and ECR-0063** rather than in dedicated GC documents. **That is a
difference in location, not an absence of record** - see §8.1, and note that an earlier draft of
this ECR read it as the latter.
**Blocks:** nothing.

### 1. The guarantee, in one sentence

> **Every field a store writes has a reader outside its owning package - or a recorded reason
> why it does not, or a recorded note that its reader cannot yet be reached.**

### 2. Population: **fields a store writes** - chosen, and why

Three definitions were on the table. **The second is chosen: fields at actual store write
sites**, across **both** backends. Postgres supplies explicit `INSERT`/`UPDATE` columns. A
memory backend supplies direct field mutations plus the fields of a statically typed model
inserted or appended to a container that is actually mutated. **Class naming is not evidence**:
an `InMemory*Store` and a bare `*Log` are treated identically when their write shape is identical.

**The reason is not that the ECR-0084 defect lived there** - though it did
(`findings/postgres.py:206-215`). It is that **the population must match the claim**:

> **The guard's claim is that *the system does work nobody consumes*. Work is writing.** A DDL
> column defines **capacity**; a write defines **maintenance**. The defect class is
> maintenance-without-consumption, so the population is **write-defined**.

**Two consequences worth stating:**

- **The memory-only blind spot of the DDL definition does not arise**, because both stores
  write and both are in scope.
- **If the two backends write different field sets, the guard surfaces it.** That is a
  contract divergence the one-suite requirement should already have caught, so a hit there is
  a finding either way - not a false positive.

**Named limit:** whole-record discovery requires a statically resolvable container model
annotation. An untyped, `Any`-typed, or dynamically constructed container cannot supply field
names to this source-level guard. The implementation records that limit rather than substituting
a class-name convention, which would invert the blind spot: conforming names would disappear.

**Rejected:** DDL column lists (misses memory-only, and defines capacity rather than
maintenance); all fields of any persisted model **without a matching write site** (defines model
capacity rather than maintenance, produces a long first allow-list, and **a long allow-list is
where reasons go stale**).

### 3. Three states - and **dormancy cannot be computed**

| state | determined |
|---|---|
| **consumed** | **mechanically** - a reader exists outside the owning package |
| **dormant** | **declared** - a reader exists, no shipped path reaches it with the data it reads. **Reason required.** |
| **exempt** | **declared** - no external reader by design. **Reason required.** |
| **unconsumed** | **mechanically** - no reader, not declared. **Fails.** |

**Reachability analysis does not decide dormancy, and this is the load-bearing point.**
P-002's branch **is** reachable from `__main__`; it simply never fires, because
`reporting/analyze.py:192-196` builds a fresh store per run and only `findings/memory.py:86-87`
diverges. **A call-graph guard would pass, and pass for the right reason** - which is what makes
it the wrong instrument.

> **A guard that claimed to decide *"has anything ever been read?"* would be ECR-0084's defect
> one level up: a check reporting a closed gap because the thing it can measure looks right.**

**So the guard reports a census, not a clearance.** It does **not** assert the gap is closed;
that claim is not available to it.

**Named limit, recorded rather than papered over:** the guard **cannot detect undeclared
dormancy**. A reader that exists but is unreachable, and is not declared, classifies as
`consumed` and the guard is wrong. **The countermeasure is review-time, not mechanical** - a
field gaining its first reader requires a dormancy determination at that moment.

**`current_severity_score` is the guard's first `dormant` entry**, reason: *the only divergence
point is re-emission, and the shipped report path constructs a fresh store per run.*

### 4. The classification must be **inspectable**, or three states cannot be tested

This falls out of the §5 constraint and it changes the guard's shape:

**A two-state implementation and a three-state one agree on every pass/fail outcome.**
`dormant` passes; `consumed` passes. **The distinction is invisible to an exit code.**

> **The difference lives in what the guard *records*, not in what it *rejects*.** Two-state
> records `current_severity_score` as consumed and a reader concludes the gap is closed;
> three-state records it as dormant and the reader knows it is open.

**Therefore the guard must expose its classification per field, and the controls must assert on
that classification - not merely on pass/fail.** Without this, the three-state model is
unfalsifiable and would ship as decoration.

### 5. Controls - and the one that discriminates

**Reuse `tests/guarantees/controls/`**, whose modules *perform* the forbidden thing.
`unscoped_health_service.py`'s docstring is the pattern: *"If the guarantee is neutered, this control
stops failing."*

| control | asserts | discriminates? |
|---|---|---|
| a written field with **no reader** | the guard **fails** | **no** - a two-state guard fails it too |
| a written field with a **declared-dormant** reader | the guard **passes** | **no** - two-state passes it too |
| **a declared-dormant field classified as `dormant`, not `consumed`** | **the classification** | **YES** - a two-state guard has no `dormant` to report |

**Only the third control separates the specified rule from the rule someone would plausibly
write instead**, which is exactly what §5 requires. The first two are necessary and prove
nothing about the design.

**This is §4.3's lesson generalised:** a 1-ULP fixture proved only that noise is suppressed,
which `math.isclose` also achieves. **The control must sit where the specified rule and the
plausible alternative disagree** - and here that is the **classification**, not the outcome.

### 6. Reuse, do not invent

- **Allow-list shape:** `tests/guarantees/discovery.py:17`'s
  `EXECUTION_SCAN_EXCLUSIONS = {"workflow": "<reason>"}`, **pinned by an equality assertion** so
  an entry cannot be added quietly. **Copy it for both the exempt and the dormant registries.**
- **Discovery:** `discover_packages()` (`discovery.py:60`), already tested against a temp root
  where a package arriving later **must** appear; plus `aqelyn_source_root()`,
  `source_python_files()`, `GuaranteeViolation` (`discovery.py:25`).
- **Controls:** `tests/guarantees/controls/`, per §5.

### 7. Constraints

- **Test-only, no runtime surface** - as GC-001 and GC-002 are recorded in `README.md`.
- **Rule 33 is not restated here.** It **landed** in `SPEC_AUTHOR_NOTES.md:403`, selected by the
  owner 2026-07-31, and the collection now runs 1-33. **GC-004 enforces rule 33's
  persisted-field subset and must not repeat its text** - a guard and a rule are different
  artifacts, and duplicating the wording is how the two drift.
  *(An earlier draft of this bullet said the rule remained absent and was the owner's call;
  corrected against the merged record before publication.)*
- **Both registries pinned by equality assertion**, or reasons rot silently.

### 8. Two items raised here and **not** folded in

**8.1 WITHDRAWN.** An earlier draft claimed GC-003's intended assertion was **unrecorded** and
proposed a retrospective spec. **That claim was false**, and the premise it rested on was an
inference rather than a check: **no dedicated `GC-003-*.spec.md` and no ECR numbered for GC-003
were read as *no record*.**

**GC-003's assertion is recorded.** `C-038_Task_Bundle.md` specifies its discovery-based
guarantee and its negative control; `ECR-LOG.md:3315` records it as owner-approved with its
intended assertion, behavioural scope, discovery model, and mutation-proven control.
**Weakening can be detected** - against those - so the rationale for a retrospective spec does
not hold.

**What actually remains is much smaller: a findability gap, not a verifiability one.** GC-003's
record lives in a **milestone** document rather than a **guard** document, so a reader looking
for it looks in the wrong place. **A one-line docstring cross-reference in
`tests/guarantees/test_service_health.py`** pointing at C-038 would close it. **Not GC-004's
job, and not worth more than that line.**

**Recorded rather than deleted**, because the error is the instructive part: **absence of a
document shape was read as absence of a record.** That is ECR-0084's defect **mirrored** - there,
a field's *presence* did not mean it was consumed; here, a document's *absence* did not mean the
assertion was unrecorded. **Both infer a property from a proxy for it.**

**8.2 The §4.3 sub-display test - raised here and CLOSED before publication.** A 1-ULP
divergence is suppressed by `math.isclose` as readily as by the specified string comparison, so
the original test passed against an implementation that was not the specified rule. **Fixed in
PR #278**: the fixture now uses a `+/-0.0004` divergence - large in float terms, invisible at one
decimal - and **explicitly rejects `math.isclose`**. Recorded because the *reasoning* generalises
(§5): **a control must sit where the specified rule and the plausible alternative disagree**, not
at the minimum magnitude that separates the rule from no rule at all.

### 9. Resolution - GC-004 shipped

The test-only guard discovers Postgres `INSERT`/`UPDATE` columns, direct in-memory field
mutations, and fields resolved from typed models at whole-record container write sites. At
acceptance the inspectable census contained **670 fields**: **520 consumed, 1 declared dormant,
149 reasoned exemptions, and 0 unconsumed**. Backend provenance remains on each field: **461 are
written by both backends, 176 are memory-only, and 33 are Postgres-only**. Forty-five
whole-record writers are resolved by behavior rather than class name; a convention-named store
and a bare log are both controls, while a typed model with no write site stays outside the census.

H4 shipped before H5: classification is returned as a per-field value, and the discriminating
control asserts `dormant` rather than merely asserting that the suite passes. Ten independent
mutations were run: collapsing dormant into consumed, dropping the reason check, drifting each
field registry's equality pin, counting owner-local reads, removing memory-write discovery,
allowing a dormant entry with no external reader, and allowing an exempt entry with an external
reader all turned the focused suite red. Reintroducing class-name gating also turns the suite red
because the bare-log whole-record field disappears, and disabling type-alias resolution turns it
red because the union-backed control fields disappear.

## ECR-0086 - The EA-0052 ... EA-0063 batch, and two false status claims

**Raised by:** the reviewer, 2026-08-01, verified against `main @ca59f0a`.
**Status:** Accepted — owner decisions recorded in `ECR-0086_OWNER_DECISIONS.md`; three
absence guards shipped.
**Number:** verified free at `ca59f0a`; rule 20 re-derived against the archive through EA-0063.

### 1. Two recorded claims are false

**1.1 ECR-0060's "archive exhausted as a requirements source" is wrong.** `archive/` runs to
**EA-0063** - its own index says so on line 1. EA-0050/0051 were classified non-capability, which
leaves **twelve masters never assessed at all.**

**1.2 The rule-20 premise "archive stops at EA-0051" is wrong**, and this is the load-bearing
one. Two ECR allocations discharged rule 20 with it. **Both conclusions still hold** - they were
checking for an `EA-0071`, and 0063 < 0071 - **but they hold by luck, not by the check.** The
premise gives the **wrong answer across the entire 0052-0063 band**, where ECR-0052 ... ECR-0063
are all already allocated.

> **Same family as C-038's `>= 30` registry floor: a bound that was true when written and does
> not track what it measures.** And the failure mode is specific - **the next person to run a
> rule-20 check reuses the sentence rather than re-deriving it**, which is how a stale premise
> outlives every fact that supported it.

### 2. Three dispositions, on the proven ECR-0060 shape

**A - conformant via shipped owners (3).** EA-0055 -> **EA-0023**, EA-0056 -> **EA-0024**,
EA-0057 -> **EA-0025**. The strongest evidence is EA-0056's: **the master's proposed engine name
IS the shipped class** (`VulnerabilityIntelligenceEngine`, 14 occurrences).

**B - genuine capability gaps (3).** EA-0052 Endpoint Intelligence, EA-0053 Endpoint Security
Assessment, EA-0054 Web Intelligence. **Three times the EA-0048 result** - and unlike EA-0048,
**the roadmap schedules them** (C-005, C-006). Note that **two of C-006's three already ship**
under EA-0023/0024: the roadmap's coding order was written against archive numbers the platform
has since realised elsewhere.

**C - non-capability (6).** EA-0058 ... EA-0063.

> **Original acceptance premise:** EA-0058, EA-0060 and EA-0061 were treated as *"normative
> standards documents"* because 703 lines appeared to be real content rather than the 485-line
> stub shape. They were recorded as owing a separate standards-conformance read.
>
> ⚠️ **Superseded by ECR-0087:** the read was performed and found a third generator template,
> not standards. The line count measured the generator rather than normative content. The debt is
> discharged; these remain non-capabilities with no build or conformance work attached.

### 3. The correction that changes the decision: **B is not one group**

The brief states *"all three Disposition-B gaps are active scanners"* and that building any of
them **opens AQELYN's first socket.** **That is right for one of the three and wrong for two.**

**S-003 already collected, from a real host, handed in, with no socket opened:** package
inventory, listening sockets, firewall rules, unit definitions, unit inventory. **That is
substantially EA-0052's stated scope** - *endpoint telemetry inventory; process, service,
software and firewall visibility.* **It does not realise EA-0052-FR-004's cross-platform agent
integration.** S-004 explicitly added capability **without adding a collector** and required a
stop if the work gained an elevated subprocess, privileged service account, or new driver command.

| master | needs a socket? | why |
|---|---|---|
| **EA-0052** Endpoint Intelligence | **no for the handed-in descriptor path; FR-004 unresolved** | the host's own state can be read locally by its owner - **the S-003/S-004 pattern, already proven on a real estate**. A cross-platform agent is a separate collector boundary |
| **EA-0053** Endpoint Security Assessment | **no** | pure analysis over EA-0052's descriptors; it reads nothing itself |
| **EA-0054** Web Intelligence | **YES** | TLS handshake, DNS, HTTP headers against a **remote** host. No handed-in shape exists - **the evidence does not exist until someone connects** |

**The distinction is not scanning versus not scanning. It is *whose* machine, and *who* runs the
collector.**

- **EA-0052's proven path is an owner-run, one-shot local collection** that produces a document.
  **S-004 settled the principle: *the driver does not need privilege - the owner needs it,
  once.*** That does **not** settle FR-004: a cross-platform agent is persistent collector
  integration and needs its own runtime, privilege and authorization decision.
- **EA-0054 reaches across a network to a host that has not handed anything in.** That is the
  boundary, and it is genuine.

**So the first-socket boundary is crossed by EA-0054 alone.** EA-0052's **handed-in descriptor
path** and EA-0053 are buildable within the shipped boundary - which makes those paths a product
decision, not a safety one. **EA-0052-FR-004 is not covered by that conclusion** and must not
inherit it merely because it sits in the same master.

> **Scoped by ECR-0088:** *first socket* in this decision means the first **outbound** connection
> to a remote target that handed nothing in. ECR-0088 later introduced AQELYN's first inbound
> listener: one read-only package, bound to `127.0.0.1`. The EA-0054 decision is unchanged.

**This does not weaken the boundary; it locates it.** EA-0054 remains exactly as consequential
as the brief says - and stating it precisely is what keeps the boundary meaningful rather than
making it a general reluctance.

### 4. Disposition B recorded, **scheduling reserved**

**Recorded as gaps. None scheduled**, following ECR-0060's EA-0048 precedent verbatim: *an open
capability gap, not scheduled.*

**Reserved to the owner:** whether **EA-0054** is built at all, given that it opens AQELYN's
first outbound socket to a remote target. The evidence is in §3 so the decision is made **with it in view rather than
discovered during implementation.**

**EA-0052-FR-004 is also unscheduled.** It is not the first-socket decision, but it is a distinct
collector safety and operations decision if EA-0052 is scoped. **This ECR authorizes no agent.**

### 5. Absence guards - three new rows, and the net does not cover them

`EA0048_OWNERSHIP_TERMS` is **AI vocabulary only** - `model_governance`, `ai_security`,
`prompt_injection`, `training_data`. **Nothing in it would notice an endpoint or web module
arriving.**

**Each new Disposition-B row needs its own guard, built to the three-branch standard PR #283
established** - exact declaration discovery, raw keyword net, token-normalised identifier
matching - **each branch with a unique witness test.** Otherwise the batch certifies three
absences with no control behind them, **which is the EA-0048 defect reintroduced at triple
scale.**

**Carry the honest limit forward too:** the guard catches **anticipated-or-conventional
vocabulary, or an explicit declaration** - not *any* capability. **A determined novel vocabulary
evades it.** State the guarantee that way; do not overclaim it.

### 6. False friends verified by the reviewer

- **`tlm` = `telemetry_record` is already allocated**, and EA-0052's FR-001 is *"endpoint
  telemetry inventory"*. **No prefix exists for endpoint or web** - a Disposition-B module needs
  new ones.
- **ECR-0015 check:** every proposed engine name returns **0** in `src/` **except**
  `VulnerabilityIntelligenceEngine` at **14** - the shipped EA-0024 class. **Do not restate it.**
- **Rule 20, live:** EA-0052 declares *"Implementation Specification: IS-035"*, but **IS-035 is
  closed** as Secrets/Keys/Certificate Lifecycle under EA-0032 (ECR-0054). **Same number,
  incompatible artifact.** EA-0055 declares IS-038 and EA-0057 IS-040 - **verify each against its
  source family, do not assume they map to the IS-0xx analyses on file.**
- **Event names are generator output, not a contract.** The masters propose PascalCase
  (`EndpointIntelligenceEngineDiscovered`); the shipped convention is dotted lowercase
  `aqelyn.<domain>.<verb>`, and **GC-002 closes the namespace.**

### 7. Not in this pass

**No module specs for EA-0052/0053/0054.** The batch decision comes first either way, and it is
required before any scheduling question can be answered.

### 8. Acceptance - requirement-level authorization and mechanical absence guards

The owner specifically delegated the two named decisions after §3 exposed their boundaries. The
accepted decisions are recorded in `ECR-0086_OWNER_DECISIONS.md`:

- **EA-0054 remains an open capability gap, not scheduled.** Re-proposal requires a user-facing
  surface, the shipped EA-0052 -> EA-0053 handed-in path, and reviewed runtime authorization
  semantics. It returns under a new ECR rather than reopening this one.
- **EA-0052-FR-004 is not authorized.** Any future EA-0052 scope is limited to owner-run,
  handed-in descriptors. A resident or phone-home agent requires its own decision and ECR.

The three Disposition-B absences are now guarded in `tests/conformance/` by exact declaration,
raw vocabulary and token-normalised identifier discovery. Each branch has a unique witness for
each capability. The guarantee remains deliberately bounded: conventional vocabulary and exact
declarations are detected; determined novel vocabulary can evade the net.

## ECR-0087 - EA-0058 / EA-0060 / EA-0061 are a third generator template, not standards

**Raised by:** claude.ai, 2026-08-02; mechanically re-verified by Codex against
`main @fffbdb7`.
**Status:** Accepted - record-only read complete; no implementation required.
**Number:** verified free at `fffbdb7`; rule 20 re-derived against the archive through EA-0063.

### 1. Finding

The standards-conformance read owed by ECR-0086 is complete. **EA-0058, EA-0060 and EA-0061
contain no topic-specific normative standards.** They are a third generator-template family:

- each master is **703 lines** with twenty topic headings on a **31-line stride**;
- all **300** requirement lines match one structural sentence, with only the section title and
  generated identifier changing;
- all **60** Implementation Rules blocks are byte-identical;
- all **240** acceptance lines normalize to one template;
- none of the three masters declares an IS number.

The approximately 29 document-specific lines per master are an executive-summary sentence, eight
scope bullets and twenty section titles. The Engineering Review approves file structure and PDF
generation, not normative content.

### 2. Correction to ECR-0086

ECR-0086 correctly refused to collapse *non-capability* into *ignore* and correctly required the
read. Its premise that 703 lines plausibly meant real standards was wrong. **The line count measured
the generator, not the content.** This is the same proxy failure as a census reading as coverage or
a fixed bound reading as a live measurement.

The three rows are therefore reclassified as:

> **Non-capability - no topic-specific normative content; generator template class 3 (703-line
> shape). Read performed and closed.**

EA-0059, EA-0062 and EA-0063 keep their ECR-0086 classification. Nothing here reopens them.

### 3. Five shared principles, all already owned

Only one five-sentence Implementation Rules block carries normative meaning, repeated twenty times
in each master. Each sentence maps to an existing shipped rule or convention:

| Archive sentence | Existing owner |
|---|---|
| Deterministic, reviewable and testable code/configuration | `CONVENTIONS.spec.md` §3 owns deterministic serialization; `START_HERE.md` §7 requires unit, integration and security tests plus updated documentation and traceability; ADR changes require review. |
| Validate external inputs before processing | `CONVENTIONS.spec.md` §§1 and 5 require identifier and tenant-scope validation; handed-in models use typed Pydantic validation with forbidden extra fields. |
| Outputs understandable by non-experts and expandable for experts | `START_HERE.md` §§2 and 6 and the Finding model require plain-language explanation with expert-depth evidence and derivation. |
| Security decisions include evidence references and audit metadata | The Finding model D2/D4 requires evidence and audited lifecycle changes; `Consistency_and_Traceability.md` records append-only audit and evidence chains. |
| Deviations require an ADR and engineering review | `docs/architecture/decisions/README.md` makes ADRs authoritative and requires reviewed, superseding records rather than silent divergence. |

No new rule is imported from the archive. The five sentences restate owners already in force.

### 4. Template-class-3 signature

The signature is **703 lines, twenty sections at a 31-line stride, five generated requirements per
section using one sentence, one repeated five-bullet rules block, and four generated acceptance
lines per section.** A future archive document matching this signature is a template candidate,
not evidence of standards by volume.

EA-0058's topic headings may be a useful outline if the project later chooses to author a real
standards document. That would be a new deliverable under change control; the archive supplies a
table of contents, not the book.

### 5. Resolution

The ECR-0086 standards-read debt is **discharged**. No runtime, guard, module spec, schedule or owner
decision follows from this read. Absence guards are for capabilities that could be built; these
documents define none.

## ECR-0088 - The surface: read-only, loopback, operator-only

**Raised by:** claude.ai from Claude Code's surface brief; implemented by Codex from
`main @28d41c1`.
**Status:** Accepted - surface v1 shipped.
**Number:** re-verified free at `28d41c1`; the archive remains read through EA-0063.

### 1. Findings of record

The archive contains no product surface. EA-0059 is the fourth generator-template-class-3
document; EA-0062 is real content about building AQELYN, not using its security intelligence.
The surface is therefore a fresh product decision, not archive conformance.

Before this ECR, the platform and its only user-facing path were disconnected. The factory-built
`Runtime` registered thirty services, while the P-001 report directly constructed one domain
engine and in-memory stores. No shipped user path entered the kernel.

### 2. Decision and exclusions

The surface is a way to see the shipped engines. V1 is a **loopback-only read API over the real
kernel plus a thin UI**. It is not a build tracker, marketing site, write surface or multi-user
web application.

Loopback is the no-new-risk choice and is decided here. The listener binds `127.0.0.1` as a design
property. There is no bind-address configuration key or command-line option. Any non-loopback
listener requires a future owner-authorized ECR and must specify authentication before
implementation. Nothing here reopens EA-0054 or EA-0052-FR-004.

### 3. Shipped read surface

The package is `src/aqelyn/surface/`; its docstring retains **Local, operator-only** verbatim.
It uses the standard library and adds no dependency or frontend build chain.

| Route | Projection |
|---|---|
| `GET /health` | `kernel.health()` across the registered runtime |
| `GET /api/v1/meta` | shipped backend and tenant-mode configuration |
| `GET /api/v1/findings` | `kernel.get_service("finding_read").query(...)` using the Finding owner's keyset cursor |
| `GET /api/v1/inventory` | `kernel.get_service("inventory_engine").inventory(...)` |
| `GET /api/v1/vulnerabilities` | `kernel.get_service("vuln_engine").assess(...)` |
| `GET /` and `/assets/*` | dependency-free operator UI |

`HEAD` is the only additional method. Other methods receive 405; unknown routes receive 404.
The route table contains no write operation. The CLI is `aqelyn surface --port <port>`; only the
port is configurable.

Every domain read passes tenant identity explicitly. Enterprise mode refuses a missing tenant UUID.
Local mode passes `tenant_id=None` and states that it means the local estate, never an all-tenants
wildcard.

### 4. Pagination and uncertainty

Surface-owned collection cursors are scoped to route and tenant. Findings retain the owner's
existing `(severity_score, id)` keyset cursor and apply it inside the explicit tenant query. A page
contains at most 100 items, and a projection that materializes a collection refuses above a
50,000-item work budget rather than truncating silently. The **10,173-finding** acceptance-scale
test traverses the full finding service without an oversized response.

Inventory `degraded` state and vulnerability `unavailable` entries are preserved. Vulnerability
factor status and reason are returned intact, so the UI cannot turn unknown into an empty or clean
result.

### 5. Boundary relocation

The former unscoped statement *no socket anywhere in `src/aqelyn`* ends here and is replaced by:

> **Outbound:** no outbound network client anywhere in `src/aqelyn`; the ECR-0086 EA-0054
> decision stands.
>
> **Inbound:** one listener exists in `src/aqelyn/surface/`, binds loopback only and exposes reads
> only.

The guarantee discovers outbound clients, listeners outside the surface package, and network
module literals as three independent branches. Each branch has a unique witness and each witness
goes quiet when only its branch is disabled. Separate controls pin loopback, the absence of a bind
configuration seam, and the read-only route roster.

### 6. Namespace and lifecycle

V1 persists nothing and emits no event. It therefore joins neither GC-004's persisted-field census
nor GC-002's event-prefix registry. The Finding owner gains one read-only AQService, so the kernel
now registers 31 services and GC-003 covers it in both tenant modes. The CLI creates the runtime
through `create_runtime()`, starts the real kernel before listening, and closes the listener and
kernel together.

### 7. Consequence for EA-0054

ECR-0086 precondition 1, *a user-facing surface exists*, is satisfied by this implementation.
Precondition 2, the shipped EA-0052 to EA-0053 handed-in assessment path, and precondition 3,
reviewed target-authorization semantics, remain open. EA-0054 remains unscheduled and can return
only under its own new ECR.

## ECR-0089 - Owner read seams and one user-facing data path

**Raised by:** claude.ai from Claude Code's widening brief; implemented by Codex.
**Status:** Accepted - surface widening shipped.
**Number:** re-verified as the next contiguous number after ECR-0088.

### 1. Decision

The surface generalises the Finding owner's read-service precedent. ISPM, exposure, secrets and
supply chain each own a dedicated `<domain>_read` `AQService`. Public capability methods are an
enumerated read-only set, tenant scope is keyword-only, and engine coupling stays inside the owner
package. The surface has no generic reflection seam and never traverses an owner's `.engine`.

The four services join `Runtime` and the kernel registry in both tenant modes. The deliberate
GC-003 registry delta is four services: `ispm_read`, `exposure_read`, `secrets_read`, and
`supplychain_read`. Infrastructure receives no route or read service.

### 2. Read contract

Collection reads use complete, tenant-scoped owner keysets: `(subject_ref, id)` for posture,
`(discovered_at, id)` for exposure, `(kind, id)` for cryptographic assets, and
`(provenance_status, object_id)` for software components. Detail reads use owner identifiers.
Every payload carries `explain`; owners without a record-level explanation return explicit null.
Every collection payload carries `degraded` plus reasons, and the UI renders that state visibly.

The routes remain under the fixed ECR-0088 allowlist, accept only GET/HEAD, and preserve loopback,
no outbound networking, no dependency, no persistence, no event, raw `APP_JS`, and `[hidden]`.

### 3. Reporting unification

P-001 now constructs the in-memory Runtime, publishes through the registered vulnerability
service, and reads findings through `finding_read`. The CLI, handed-in input, static HTML output,
and prior provider semantics are unchanged. A stable analysis-layer golden pins the same findings,
counts, scores, priorities and disclosed unknown reasons without pinning HTML incidentals.
This real-owner path deliberately emits in-process owner events (one per finding plus ingestion);
the events are not persisted, sent over a socket, or exposed by the surface.

### 4. Scope

This ECR decides the read-service seam once for future widening. It does not authorize writes,
authentication deferral beyond loopback/read-only, non-loopback binding, frameworks, surface
events, or routes for infrastructure and remaining domains.

## ECR-0090 - Keyset tiebreak witnesses

**Raised by:** claude.ai from Claude Code's post-ECR-0089 review; implemented by Codex.
**Status:** Accepted - tiebreak witnesses shipped.
**Number:** re-verified as the next contiguous number after ECR-0089.

### 1. Finding

The four ECR-0089 reads carried correct composite keysets, but their tests did not prove the
trailing tiebreak. Time-ordered identifiers correlated the expected order with insertion order,
and Postgres covering indexes supplied the omitted order under the default plan. In the measured
ISPM case, deleting the tiebreak returned two of six rows and silently skipped four.

### 2. Resolution

Exposure, ISPM, secrets and supply-chain fixtures now pre-mint each read's own tiebreak values and
insert them in reverse while tying the leading key. Memory and Postgres variants walk limits
`1..N` to exhaustion; Postgres runs on the exact session with index and bitmap scans disabled and
resets both settings afterward.

A static guarantee separately pins the query table and ordered columns to the named ASC covering
index for exposure, ISPM and supply chain. Secrets is deliberately excluded from that static
claim: its read orders a `DISTINCT ON` CTE result and no covering index backs that outer query.

### 3. Scope

Tests and one static guarantee only; no production code, dependency, pagination contract or
surface boundary changes.

### 4. Amendment by ECR-0091

R4's original statement that each Postgres deletion turns "exactly its own witness" red was
stronger than the evidence and conflicts with the intended static defence in depth. The amended
standard is: each deletion turns its own witness red; the static guarantee may additionally fire
on Postgres cases. No witness may be silently covered only by another witness of the same kind.

### 5. Amendment by ECR-0093

The original scope text named findings and inventory as the offset pair. ECR-0093 corrects the
applicable set to inventory and vulnerabilities. Findings was already keyset-paged and needed no
migration.

## ECR-0091 - Leading-key witnesses

**Raised by:** claude.ai from Claude Code's post-ECR-0090 leading-key review; implemented by Codex.
**Status:** Accepted - leading-key witnesses shipped.
**Number:** re-verified as the next contiguous number after ECR-0090.

### 1. Finding

ECR-0090 made each composite keyset's trailing tiebreak observable by holding its leading value
constant. That fixture shape necessarily made the leading value unobservable. Deleting the leading
column from any of the four in-memory sort keys left the full ECR-0090 witness family green.

The gap predates ECR-0090. An older ISPM fixture used five distinct UUIDv7 `subject_ref` values but
still passed after leading-key deletion because generation order, insertion order and identifier
order were correlated. Distinct values are not a decorrelated ordering witness.

### 2. Resolution

Exposure, ISPM, secrets and supply chain now carry a second, memory-only mirror witness. Leading
values are generated first and reverse-inserted; unique tiebreaks are assigned so their standalone
ordering cannot reproduce the required leading-key order. Each fixture walks limits `1..N`, proves
exhaustion and uniqueness, and fails when its leading sort column is removed.

Secrets enumerates the complete legal kind set before constructing the fixture. Its type-specific
ID prefixes prevent a perfect reverse tiebreak ordering, so the witness asserts the load-bearing
property directly: ID-only order differs from legal kind-first order. No asset kind is invented.

### 3. Postgres scope - amended by ECR-0092

ECR-0090's static guard pins each covered query's table, ordered column list, named index and
direction. ECR-0092 records the exception that this section left unnamed: secrets is outside that
guard because its `DISTINCT ON` CTE has no covering index, so its Postgres leading key now has a
dedicated forced-plan witness.

### 4. ECR-0090 amendment

ECR-0090 R4 is amended to permit the static guarantee to fire alongside the domain Postgres
witness. The surviving isolation rule is that no witness may be silently covered only by another
witness of the same kind.

### 5. Scope

Tests and records only. Production reads, persistence, dependencies, loopback boundaries and
GC-002/GC-003/GC-004 remain unchanged. ECR-0092 subsequently made ECR-0089 FR-003 surface-wide;
ECR-0093 corrects the offset pair to inventory and vulnerabilities, then names and guards their
snapshot exemptions. Findings was already keyset-paged.

## ECR-0092 - The last unguarded keyset property and the offset ruling

**Raised by:** claude.ai from Claude Code's post-ECR-0091 review; implemented by Codex.
**Status:** Accepted - final keyset witness and surface-wide pagination ruling shipped.
**Number:** re-verified as the next contiguous number after ECR-0091.

### 1. Finding

After ECR-0090 and ECR-0091, secrets' Postgres leading key was the only unwitnessed ordering
property in the widened-read family. Deleting `kind` from its outer `ORDER BY kind, id` left the
full secrets suite and the static guard green. The SQL was correct; the witness was absent.

This was the third consecutive special case for the same read. Its `DISTINCT ON` CTE correctly
keeps it outside the covering-index guard used by the other three domains. Any future guarantee
for "the keyset reads" must therefore name secrets explicitly, in or out with grounds, or it is
presumed to have missed it.

### 2. Resolution

Secrets now has a dedicated forced-plan Postgres leading-key witness using every legal asset kind.
The fixture reverse-inserts those kinds, walks limits `1..N`, and asserts exhaustive, unique,
kind-first order. With index and bitmap scans disabled, the inner CTE emits ID order; only the
outer Sort on `kind, id` can produce the expected sequence. Removing `kind` makes this witness red.

The existing memory witness and the new Postgres witness share the same legal-kind fixture and
walk helper. ECR-0091's exposure witness also replaces its tautological ID assertion with the
falsifiable `id_only != expected` shape.

### 3. Offset ruling - applicable set corrected by ECR-0093

ECR-0089 FR-003's "never offset" requirement is surface-wide for collection routes. The original
text incorrectly named findings and inventory. ECR-0093 corrects the applicable set to inventory
and vulnerabilities; findings was already keyset-paged and needed no migration. Both actual
offset routes page per-request reports rather than durable row streams, so ECR-0093 names and
guards their snapshot exemptions. The ruling survives: no collection route retains offset
silently.

### 4. Scope

Tests and records only; no production source, dependency, persistence, loopback or GC posture
changes. ECR-0034 degraded, ECR-0061 exhaust-or-refuse, ECR-0062 keyset, rule 33 and the
ECR-0090/ECR-0091 method notes remain binding.

## ECR-0093 - The offset routes: correction, named exemptions and one cursor contract

**Raised by:** claude.ai from Claude Code's post-ECR-0092 review; implemented by Codex.
**Status:** Accepted - snapshot exemptions and cursor contract shipped.
**Number:** re-verified as the next contiguous number after ECR-0092.

### 1. Correction of record

ECR-0090, ECR-0091 and ECR-0092 named findings and inventory as the two surface offset routes.
The actual `_page_request` callers are inventory and vulnerabilities. Findings has always called
the owner's ECR-0062 keyset query. The prior three bodies and index rows are visibly amended; the
surface-wide ruling survives with its applicable set corrected.

### 2. Named snapshot exemptions

Inventory and vulnerabilities page per-request, budget-governed reports rather than durable row
streams. A cursor from snapshot N has no defined position in snapshot N+1 under either offset or
keyset. Both routes therefore retain offset as named exemptions. A static census permits exactly
those two callers, and behavioural controls pin each report's `degraded`, capture time and
freshness or coverage metadata. If either route is re-pointed at a durable row stream, its
exemption lapses and the redesign requires its own ECR.

### 3. One surface cursor contract

The existing offset envelope keeps its `path` and `tenant_id` binding. Findings now wraps the
store's unchanged opaque keyset cursor in the same scoped envelope. Cross-route and cross-tenant
replay fails with `SurfaceRequestInvalid` and a clean HTTP 400 in both directions. Previously
minted unscoped findings cursors are intentionally incompatible; no shim or silent reset exists.

### 4. Findings index

The findings DDL adds `ix_finding_tenant_severity_id` on
`(tenant_id, severity_score DESC, id ASC)`. The existing ECR-0090 static guard now pins the
query table, index name and per-column direction. This is one index and no table-shape change;
it adds no GC-004 census field. Behavioural leading/tiebreak deletion probes remain a reviewer
obligation and are not silently claimed by the static check.

### 5. Scope and method

Reads-only, loopback, no new dependency, GC-002/GC-003 unchanged. A citation can be precisely
right and still point at the wrong thing: when naming callers of a mechanism, inspect the call
sites rather than inferring them from nearby line numbers.

## ECR-0094 - Findings keyset witnesses

**Raised by:** claude.ai from Claude Code's post-ECR-0093 mutation review; implemented by Codex.
**Status:** Accepted - findings ordering and predicate witnesses shipped.
**Number:** re-verified as the next contiguous number after ECR-0093.

### 1. Finding

ECR-0093's review deleted findings' in-memory leading key and tiebreak independently; both
mutations stayed green. Postgres turned red only because the static guard parses SQL and DDL.
That guard cannot reach the memory sort, and it pins `ORDER BY` rather than the separate resume
predicate on either store. Findings therefore had correct keyset code with no deliberate
behavioural witness for any component.

### 2. Resolution

Two findings-domain fixtures pre-mint IDs, use distinct dedup keys, assert N stored rows and walk
every limit from 1 through N to exhaustion. The tiebreak fixture ties every severity and
reverse-inserts IDs. The leading fixture assigns increasing severity to increasing IDs, making
correct severity-descending order the reverse of ID-only order. The same fixtures run on memory
and on Postgres under the shared forced-plan context.

The walks also deliberately guard the resume predicate. Flipping severity direction, changing
the exclusive ID comparison from `>` to `>=`, or dropping the equal-severity ID clause must turn
a witness red on each store. Mutation-to-witness mappings are recorded in the implementation PR.

### 3. Scope

Tests and records only; zero production source, schema, dependency, loopback or GC changes.
ECR-0062's composite keyset and ECR-0063's stable `severity_score` contract remain unchanged and
are now directly witnessed in the findings domain.

### 4. Closure

Together with the named snapshot exemptions from ECR-0093, every ordering property on every
surface collection read is now either mutation-proven on both stores or explicitly exempt with
grounds. The reviewer re-runs the 19 carried mutations and measures the four widened reads'
predicate coverage before merge.

### 5. Amendment by ECR-0095

R4's review disposition is widened from "any green result is recorded as a follow-up finding"
to **"any result that is not a clean RED is recorded as a follow-up finding."** ECR-0095 is
the worked example: all eight widened-read `>` → `>=` mutations hung rather than returning a
diagnostic failure, exposing a witness-quality defect while every shipped predicate remained
correct.

## ECR-0095 - Walk termination guards

**Raised by:** claude.ai from Claude Code's post-ECR-0094 mutation review; implemented by Codex.
**Status:** Accepted - all 14 test cursor walks are bounded; production pagination is unchanged.
**Number:** re-verified as the next contiguous number after ECR-0094.

### 1. Finding

All eight widened-read exclusive-predicate mutations produced a hang rather than a clean test
failure. Repeating the boundary row kept `next_cursor` non-null, and the witnesses' unbounded
loops converted a precise pagination defect into a CI timeout. A tree sweep found the same idiom
at 14 sites in 11 test files: seven Group A witness loops and seven Group B cursor walks.

### 2. Resolution

Every test cursor walk is bounded. Walks with a known expected population use
`range(len(expected) + 2)` or the equivalent fixture population; generic walks use a named
module-level `MAX_WALK_PAGES` large enough for their healthy corpus. Every exhaustion assertion
names the walk so CI reports the affected contract without waiting for a job timeout.

The eight Group A predicate mutations must now produce clean RED results on memory and Postgres.
Group B is explicitly guarded-but-unwitnessed: its five-domain predicate-mutation arc remains
deferred, with the surface HTTP findings walk and findings cursor-contract test first.

### 3. No weakening and scope

The 29 carried mutations remain in force. Bounds change how a bad witness terminates, not which
defects it detects; any changed verdict is review-blocking. Tests and records only: zero
production source, schema, dependency, loopback or GC changes.

### 4. Method

A mutation harness distinguishes RED, GREEN and HANG. A hang is not evidence that a test caught
the right defect; it is an infrastructure symptom with the diagnosis erased. A defect found in
one member of a test idiom requires a sweep of the family.

### 5. Amendment by ECR-0096

The bounded Group B walks also close their single-column resume-predicate class. The
`ispm.query_identities`, `secrets.query_assets`, and `dspm.query_assets` `>` to `>=`
mutations now fail diagnostically. This coverage was a side effect of ECR-0095 and is claimed
explicitly here; their ordering properties remained separate and are split between ECR-0096
and ECR-0097.

## ECR-0096 - Single-column keyset ordering witnesses, part 1

**Raised by:** claude.ai from Claude Code's post-ECR-0095 review; implemented by Codex.
**Status:** Accepted - the first four selected reads are witnessed on both stores.
**Number:** re-verified as the next contiguous number after ECR-0095.

### 1. Finding

The memory side of eight of nine single-column keyset reads had no decorrelated ordering
witness. UUIDv7 made insertion order look sorted. Postgres coverage was narrower: three
measured outer-order deletions stayed green, while ECR-0096's live mutation proved inventory
was already covered by IS-037's conformance cursor contract. The SQL and memory
implementations were correct, but several regressions could pass silently.

### 2. Resolution

Inventory, secrets, ISPM, and supply chain now pre-mint six IDs, reverse-insert them, prove
all six rows survived storage, and walk every page size to bounded exhaustion. Memory sort
neutralization fails each domain witness. Postgres variants run with index and bitmap scans
disabled.

Inventory and supply chain detect outer-order deletion behaviorally. Inventory's older IS-037
control fires as defence in depth, so ECR-0096 does not claim first coverage there. Secrets and
ISPM cannot: their required `DISTINCT ON (id) ... ORDER BY id, revision DESC` CTE already emits
the same ID order. A central AST guard resolves the SQL argument actually passed to
`conn.fetch`, fails closed when it cannot, and pins the final outer clause. Deletion, direction
reversal, and dead-literal relocation fail without being mislabeled as behavioral evidence.

Only inventory's witnessed method reaches `/api/v1/inventory`. `CryptoStore.query_assets` feeds
the secrets engine, secrets exposure, and service health; `ISPMStore.query_identities` feeds the
ISPM engine, ISPM exposure, and service health; `SBOMStore.query` feeds the supply-chain engine and
service health. Their surface routes use the separate composite reads covered by ECR-0090 through
ECR-0092. This batch is a reviewability split, not an exposure classification. ECR-0097 remains
binding for every deferred member.

### 3. Scope and follow-up

Tests and records only; production reads and schemas are unchanged. ECR-0097 is scheduled for
the interior four reads and the `objects` maintained-order determination.

### 4. Amendment by ECR-0097

The `objects` scope-out path is closed: `insort` becoming `append` is a clean memory mutation,
and Postgres has an ordinary outer `ORDER BY id`. The new-file wording is also replaced by the
family rule: witnesses live where their family lives, and touching a carried-control file
requires the full carried matrix to be rerun.

The original nine-single-column-keysets shorthand included workflow, whose `RunStore.list`
method has a limit but no cursor. ECR-0097 corrects this arc's counted population to eight true
single-column keyset reads plus one bounded ordered list; it does not claim that population is
the whole repository.

## ECR-0097 - Single-column ordering witnesses, part 2

**Raised by:** claude.ai from Claude Code's post-ECR-0096 review; implemented by Codex.
**Status:** Accepted - the ECR-0096 deferred ordering batch shipped.
**Number:** re-verified as the next contiguous number after ECR-0096.

### 1. Corrections

`objects` is ordinarily mutatable and receives memory and Postgres witnesses. Workflow is a
bounded ordered list rather than a cursor API, so its witness proves every ordered prefix and
makes no resume-predicate claim. DSPM's `DISTINCT ON (id)` CTE makes outer-order deletion
behaviorally indistinguishable, so the central executed-query AST guard pins its final clause
alongside secrets and ISPM.

### 2. Resolution

CSPM, DSPM, SSPM, workflow, and objects each pre-mint six IDs, reverse-insert them, and prove all
six independent records survived storage. The four cursor APIs walk every limit from 1 through N
under a `len(expected) + 2` bound. Workflow checks every prefix from 1 through N. Postgres cases
retain the forced-plan fixture as insurance, not as the claimed detection mechanism.

All five memory sort removals turn the named witness red and become green when that witness is
deselected. CSPM, SSPM, workflow, and objects use live-Postgres behavioral witnesses. DSPM's
outer-order deletion turns the fail-closed executed-query guard red instead of being mislabeled
as behavioral evidence.

### 3. Bounded closure, residual population and scope

This arc closes exactly fourteen enumerated reads: eight true single-column keyset reads,
workflow's bounded ordered list, and the five composite reads covered by ECR-0090 through
ECR-0094. For those fourteen only, ordering, tiebreak, leading key, predicate, and termination
are mutation-proven or carry a named structural treatment with measured grounds.

Excluding literal `LIMIT 1` point lookups, the source contains thirty paged
`ORDER BY ... LIMIT` reads. Sixteen are outside this arc:

| Read | Review mutation | Result at `34c6c07` |
|---|---|---|
| `assetconfig/postgres.py:235` | drop `id` tiebreak | GREEN |
| `decision/postgres.py:119` | drop `id` tiebreak | GREEN |
| `executive/postgres.py:167` | delete `ORDER BY version` | GREEN |
| `executive/postgres.py:257` | not yet measured | ECR-0098 |
| `exposure/postgres.py:121` | drop `id` tiebreak | GREEN |
| `forecast/postgres.py:183` | drop `id` tiebreak | GREEN |
| `forecast/postgres.py:342` | not yet measured | ECR-0098 |
| `governance/postgres.py:120` | not yet measured | ECR-0098 |
| `idthreat/postgres.py:164` | not yet measured | ECR-0098 |
| `lake/postgres.py:331` | drop `id` tiebreak | GREEN |
| `lake/postgres.py:439` | not yet measured | ECR-0098 |
| `response/postgres.py:162` | not yet measured | ECR-0098 |
| `risk/postgres.py:154` | drop `id` tiebreak | GREEN |
| `risk/postgres.py:227` | not yet measured | ECR-0098 |
| `soc/postgres.py:205` | drop `id` tiebreak | GREEN |
| `vuln/postgres.py:135` | drop `id` tiebreak | GREEN on three repeated full-scope runs; earlier RED was plan-dependent |

Nine were measured in review and all nine stayed green. The initially reported `vuln` RED did
not reproduce: with its SQL tiebreak removed, Postgres may still return ID order from a matching
index, so C-038/R3's verdict depends on physical plan and layout. ECR-0098 records the correction,
classifies all sixteen residual reads, and adds coverage whose verdict is forced-plan or
structural rather than incidental. No residual is declared covered by the earlier measurement.

Tests and records only; production source, schema, dependencies, loopback behavior, and GC
postures are unchanged. Any edit to the carried central guard requires the full carried matrix.

## ECR-0098 - The residual sixteen, part 1: ordering clauses

**Raised by:** claude.ai from Claude Code's post-ECR-0097 review; classification and
implementation by Codex.
**Status:** Accepted - sixteen named controls cover both stores; local-Postgres mutation
and necessity matrix complete, second review pending.
**Number:** re-verified as the next contiguous number after ECR-0097.

### 1. Classification correction

The census command returns thirty paged `ORDER BY ... LIMIT` reads after literal `LIMIT 1`
point lookups are excluded. Fourteen are covered by ECR-0090 through ECR-0097. Inspection of
the sixteen residual public APIs found that all sixteen are cursorless bounded ordered lists;
none is a keyset API and none has the CTE-backed outer-order shape. Each therefore requires a
memory and Postgres ordered-prefix witness.

The source brief's one claimed RED was corrected during review. Repeated runs showed the
`vuln` result could be green or red depending on the Postgres plan after its SQL tiebreak was
removed. **All sixteen residual tiebreaks were unwitnessed.** That correction is recorded in the
ECR-0097 table above; it is not a regression introduced by ECR-0098.

`KPIDefinitionStore.versions` needs an allocation-aware fixture because public proposal order
and allocated version order otherwise correlate. `TelemetryRecordStore.list_quarantine` also
exposed a backend divergence: Postgres uses `(received_at, seq)` while memory used
`(received_at, source_id, reason)`. ECR-0098 selects `(received_at, insertion sequence)` and
requires memory to use a stable `received_at` sort before the witnesses are claimed.

The quarantine fixture also had to decorrelate UUIDv7 source IDs from insertion order; restoring
the former memory tuple now turns it red. Two final tuple components are structural rather than
behavioral: prediction models cannot tie `(tenant, method, version)` legally, and quarantine
`seq` is insertion order. Their executed SQL tuples are pinned by the central AST guard.

### 2. C-038/R3 amendment

C-038/R3's control exercises `VulnerabilityStore`. Its former repo-wide audit sentence was an
unguarded historical observation, not a property that the test could enforce. ECR-0098 scopes
the docstring to the store its mechanism reaches and records a second limit: its Postgres mutation
result depends on the physical plan because a matching index can still return ID order after the
SQL tiebreak is deleted; its deterministic memory half is a credited catcher. The wider population
is governed by the explicit thirty-read census and ECR-0098's forced-plan or structural controls,
not by that single clean-path comparison.

### 3. Resolution

The implementation supplies thirty-two cases: sixteen named controls across memory and
Postgres. A user-owned PostgreSQL 16.14 instance ran the complete local matrix. All 32 assigned
mutations are RED. With each assigned control deselected, 30 become GREEN; `executive.versions` on
Postgres remains RED through `test_exec_def_contract[postgres]`, and vulnerability memory remains
RED through `test_vuln_order_deterministic_on_ties[inmemory]`, so both new witnesses are defence in
depth. Necessity was established against the owning domain suite, or the central executed-query
guard file for structural rows; cross-suite catchers outside those targets are not excluded.
Observable tuple tails use tied, anti-correlated fixtures; the two unobservable Postgres tails use
the executed-query AST guard. Prediction-model `version` removal is independently RED on both
stores, and restoring quarantine memory's former tuple is RED. The contained CI import repair adds
`pythonpath = [".", "src"]` and `tools/__init__.py` without changing the `src/aqelyn` wheel.

ECR-0099 classifies the leading-key, resume-predicate, and termination classes and closes the
witness arc with symmetric fixtures. Production shape is unchanged except for the memory
quarantine ordering alignment recorded above.

## ECR-0099 - The leading-key class, and the close of the witness arc

**Raised by:** claude.ai from Claude Code's measured ECR-0098 follow-up; implementation by
Codex.
**Status:** Accepted - implementation complete; closing review pending.
**Number:** re-verified as the next contiguous number after ECR-0098 at `0fc7cff`.

### 1. Decision

Ten reads had no leading-key catcher. Forecast query had only the accidental `test_fc_p2`
contract coverage and no owned witness. Eleven ECR-0098 fixtures are amended so that leading-key
groups conflict with ID order while the tail still decides within each tied group. Resume
predicates are inapplicable because these reads are cursorless; termination is inapplicable
because their ordered-prefix controls do not walk.

The standing fixture rule is now symmetric: **every component of a sort tuple must decide at
least one comparison in the same fixture.** A fixture tuned to expose one component is presumed
to blind another until the two-sided mutations prove otherwise.

### 2. Implementation and review boundary

The eleven amended memory witnesses each turn red when the leading key is removed, and each stays
red when its ECR-0098 tail is removed. Forecast query's owned control is defence in depth beside
`test_fc_p2`; the other ten close previously open leading-key cells. The same twenty-two cases,
full-target necessity runs, and the closing 84-control carried matrix remain the independent
reviewer's live-Postgres acceptance gate. No `src/` file changes.

The carried total is **84**, not the 89 quoted before this ECR. ECR-0094 §4 wrote "the 19 carried
mutations" for a block that ECR-0092's review records as fourteen — "Full matrix — 14 mutations ×
16 witness cases" — and each later total inherited the +5. The corrected chain is 32 → 42 → 52 →
84: fourteen from ECR-0090/0091/0092, ten from ECR-0094, eight from ECR-0095, ten from ECR-0096,
ten from ECR-0097, thirty-two from ECR-0098. Rule 34 samples against that enumeration.

Rule 34 records the carried-matrix policy selected with this closure: full runs on carried-file
changes, fixture amendments, family closures, and every tenth ECR; otherwise a named rotating
sample plus every in-scope carried mutation, with any changed verdict escalating to the full
matrix.

**The tell:** a fixture that makes one tuple component obvious may make its neighbor irrelevant.
Mutation-prove both directions before calling the ordering witnessed.

## ECR-0100 - Posture ingestion

**Raised and implemented by:** Claude Code, at the owner's direction while Codex was unavailable.
**Status:** Proposed - implemented, independent review outstanding.
**Number:** verified free at `bddcc6d`.

### 1. Finding

AQELYN accepted exactly one document shape. `reporting/analyze.py` read `vulns.json` (grype),
plus optional `kev.json` and `collection-manifest.json`; nothing else had an ingestion path. Six
real posture facts observed passively on the owner's own estate - application ports bound to all
interfaces beside the reverse proxy, absent HSTS behind a working redirect, four missing
browser-hardening headers, DMARC at `p=none` against an SPF that already ends `-all`, a
version-disclosing banner, and a certificate's remaining life - had nowhere to go. None is a CVE.
On a platform whose engine families are CSPM, DSPM, SSPM and ISPM, that is the gap.

The vulnerability path was confirmed sound in the same work: a real syft SBOM of 55 packages and a
real grype run against a same-day advisory database produced zero matches. Zero was measured.

### 2. Resolution

`posture.json` becomes an optional second collection document. Each observation is refused unless
it carries all four narrative fields a `Finding` requires, then becomes a Finding raised through
the real finding owner with its own evidence record. Posture findings are held in their own
`posture_findings` collection rather than folded into `findings`: they have no CVE and no
`VulnPriority`, and a hollow one would model a false claim. The vulnerability count keeps its
meaning, so a collection with posture and no CVEs still reports zero findings.

`dedup_key` derives from subject, check and observation id so re-runs are idempotent while
distinct observations stay apart; a repeated observation id is refused. `severity_score` is
carried unchanged, per ECR-0063.

### 3. Acceptance and scope

Eighteen mutations across validation, dedup key, finding construction, pipeline wiring and the
renderer: all red. Forty tests. Ruff, `mypy --strict` across 579 files, and the full suite on live
Postgres. The carried matrix stays at **84** and is untouched - no carried-control file changes and
no carried fixture is amended, so rule 34's full-run trigger is not met.

### 4. Standing caveat

This ECR was written, implemented and recorded by the reviewer, so the separation of
implementation and review is suspended rather than satisfied. Section 6 of the ECR document lists
what independent review should attack first, including the fact that a mutation matrix written by
the code's own author shares that author's blind spots.


## ECR-0101 - Surface collection seed

**Raised and implemented by:** Claude Code, at the owner's direction while Codex was unavailable.
**Status:** Accepted - implemented; independent review outstanding.
**Number:** verified free at `1861ee4`.

### 1. Finding

ECR-0100 gave posture observations a path into the report, which builds a throwaway runtime and
discards it. The operator surface - a long-lived kernel serving eight routes - still had no way to
be given anything, so starting it produced a working shell over an empty store. A platform that
cannot be seeded cannot be looked at.

### 2. Resolution

`aqelyn surface --collection DIR` seeds the kernel's finding store before serving, reusing the
report path's ingestion and refusals. Opt-in: absent the flag, behaviour is unchanged. Read once
at startup, never re-read, so the store does not mutate under a paging cursor. A refused
collection stops the surface with exit 2 rather than serving an empty page that would read as
"nothing found". Seeding is idempotent through ECR-0100's dedup key, now witnessed.

Against the machine's real collection the surface seeds six posture findings and serves them from
`/api/v1/findings` with working keyset pagination - the arc's ordering guarantee applied to real
data for the first time.

### 3. Acceptance and scope

Six mutations, all red: seeding short-circuited, dedup key made unstable, ordering reversed,
refusal swallowed, the flag given a default, the flag parsed as a string. Seven tests, ruff clean,
mypy --strict clean across 580 files, full suite on live Postgres. One mutation reported a false
green first run - `return () or await ...` evaluates to the call - and is recorded in the ECR
because a mutation that does not mutate looks exactly like a test that does not test.

Changed `surface/cli.py` and one public wrapper in `reporting/analyze.py`. Loopback binding and
read-only posture unchanged. Carried matrix stays at 84, untouched.


## ECR-0102 - Self-scan collector

**Raised and implemented by:** Claude Code, at the owner's direction while Codex was unavailable.
**Status:** Accepted - implemented; independent review outstanding.
**Number:** verified free at `abbb276`.

### 1. Finding

AQELYN had no collection half. No endpoint, agent or collector module existed and nothing in the
codebase touched a host - the parsers state "no I/O, no subprocess, no network" by design. Seven
ingest entry points meant the platform could be fed, but nothing produced the food: every input so
far came from a tool someone else ran or from observations typed by hand. The Atlas draws endpoint
agents and a mobile app as clients; they were drawn, not built.

### 2. Resolution

`aqelyn collect --output DIR` inspects the running machine read-only and writes a collection
directory the existing report and surface paths already consume. Five checks: public listeners,
host firewall, pending updates, sshd password authentication, and OS/kernel as inventory.

The load-bearing decision is that a check which cannot run reports unmeasured rather than passing.
HostFacts fields are None when unread, never defaulted, and each unread fact becomes its own
observation stating the machine is neither passing nor failing. Read-only throughout: five
commands, two files, no network, no writes outside the output directory, which is created 0600.

Mobile is named out of scope in the manifest. A host collector cannot inspect an iPhone; that
needs device management, a signed profile or an attested questionnaire, none of which is a scanner
written in this repository.

### 3. Acceptance

Eleven mutations red. A test caught a real false positive first: `is_public` compared only against
127.0.0.1, so systemd-resolved on 127.0.0.53 was reported as internet-facing - the whole 127/8
range is loopback, and a security tool that over-reports once is discounted thereafter.

Two mutations stayed green and both were redundant code rather than missing tests. The
`is_unspecified` branch was dead - a wildcard bind is already not loopback - and was removed,
because dead code in a security check is a liability. The `#` comment skip in the sshd parser is
likewise not load-bearing and is now marked in the source as defensive and unwitnessed rather than
left looking proven. Two further greens were genuine test gaps and are closed.

28 tests, ruff clean, mypy --strict clean across 585 files, full suite on live Postgres. Carried
matrix stays at 84, untouched.


## ECR-0103 - Charter v2 compliance for posture findings

**Raised and implemented by:** Claude Code, at the owner's direction while Codex was unavailable.
**Status:** Accepted - implemented; independent review outstanding.
**Number:** verified free at `9fe94d3`.

### 1. Finding

The owner pointed at the approved Project Charter v2 Product Principles, which had not been read
before ECR-0100 through ECR-0102 were built. Section 9 states its requirements are mandatory
architectural requirements applying to every finding, API, report and dashboard.

The audit found the platform already satisfied Principles 1, 3, 6, 7 and 10 by construction - the
posture schema refuses an observation missing its derivation, every observation carries evidence,
the manifest states authority and exclusions, collection is local and read-only. That compliance
arrived without the Charter being consulted, which is luck rather than method, and it did not
extend to the communication layer: titles were machine strings (UX-001), expert_details was left
empty (UX-002), Affected Assets was empty, and neither progressive disclosure nor communication
modes existed.

### 2. Resolution

plain_title derives a readable sentence from what_happened, which is already mandatory, so it
cannot fall back to a machine string; an operator-supplied title wins. expert_details carries what
the title gave up - check, observation id, subject, raw measurement - as Progressive Detail levels
3 and 4, and deliberately does not repeat the narrative.

Affected Assets was not faked. affected_object_ids holds typed obj_ ids and a posture subject is
not an object until something creates one; the model rejected the raw reference, correctly. Minting
an id would have produced a reference resolving to nothing, which is worse than an empty list.
ECR-0104 owes the object-store link.

Progressive disclosure in the UI and UX-008 communication modes remain outstanding and are named
rather than left to be discovered.

### 3. Acceptance

Six mutations red: machine-string title restored, expert_details dropped, title allowed to run to
the whole paragraph, empty-title fallback removed, operator-supplied title ignored, raw measurement
dropped from level 4. Twelve tests, including one asserting that nothing is lost when the title is
simplified, and a UX-007 check on generated wording. Ruff clean, mypy --strict clean across 586
files, full suite on live Postgres. Carried matrix stays at 84, untouched.


## ECR-0104 - Progressive disclosure and communication modes

**Raised and implemented by:** Claude Code, at the owner's direction while Codex was unavailable.
**Status:** Accepted - implemented; independent review outstanding.
**Number:** verified free at `e2a04ec`.

### 1. Finding

ECR-0103 named three Charter gaps it did not close. Two are closed here: Principle 5's six-level
Progressive Detail Model and UX-008's four communication modes, both stated in section 9 as
mandatory architectural requirements. Neither existed: findings rendered as one flat block and
nothing selected register by audience.

### 2. Resolution

reporting/disclosure.py expresses both as data a renderer consumes. levels(finding, mode=...)
returns the six Charter levels in order with the question each answers and whether it opens by
default for that audience.

Two properties carry witnesses because both are easy to break by accident. Levels add and never
repeat - Principle 5 requires multiple levels "without duplicating data". And a mode narrows what
is opened while never changing what is said: every mode returns all six levels with identical
bodies, and a test holds one finding and reads it four ways to prove it. Home opens two levels,
SMB three, enterprise five, expert six; every level stays reachable in every mode because the
Charter calls the simplified view a starting point, not a ceiling.

Level 3 renders a missing evidence link as a defect the platform requires fixing, never as an
absence of problems. A mutation rewording it to "No issues found." turns the suite red.

### 3. Acceptance and scope

Ten mutations red, including a mode rewording the summary for a home reader. Fourteen tests, ruff
clean, mypy --strict clean across 588 files, full suite on live Postgres. Carried matrix stays at
84, untouched.

No renderer consumes the model yet - deliberate scope, and recorded as such rather than left to be
discovered. UX-008 is half-served: modes change disclosure depth, not vocabulary, which is what
Principle 2 actually asks for.

## ECR-0105 — the disclosure model reaches the page

ECR-0104 recorded its own dead code in §5 and this closes it. `_posture_section` renders one
`<details>` per Charter level; `--mode` picks how many open. `<details>` rather than script,
because a local HTML file opened with JavaScript off must still reach expert depth.

Eleven mutations red. One ran GREEN first and is the point of the exercise: deleting `level.name`
stripped "Summary", "Evidence" and "Remediation" from every level in the report and the suite
never noticed. Two further witnesses - the level body, and the CLI actually passing `--mode`
through - were written before the matrix because I predicted their cells would survive, and all
three were then proven necessary by deselection.

16 tests, ruff clean, mypy --strict clean across 589 files, full suite on live Postgres. Carried
matrix stays at 84, untouched.

UX-008 is still half-served: modes change depth, not vocabulary. Recorded a second time rather
than quietly dropped.

## ECR-0106 — a posture subject becomes an asset

ECR-0100 refused to mint an `obj_` id for a posture subject and recorded the object-store link
as owed. This pays it. `subject_natural_key` gives the subject an identity independent of any
id; `subject_object` builds the object with `id=""` so `upsert` resolves by that key and mints
the id itself; `_ingest_posture` uses what the store returns. The same host observed twice is
one asset, and a re-run updates rather than clones.

Reading the deferral carefully found more than it claimed: `_ingest_posture` was already putting
a freshly minted `obj_` id into the EvidenceRecord's Subject. The reference ECR-0100 refused to
write into the Finding was being written one field over.

Eight mutations red, including the ECR-0100 anti-pattern itself. Necessity measured by four
deselection runs, all green. The three id-witnesses are correlated by construction - they assert
through the same returned id - so they are recorded as jointly necessary, not individually.

Measured on this machine's real self-scan: four observations, four findings, one asset.

Open and named: one object type for every subject kind, no relationship to objects other engines
already know, tenant is None throughout, and the renderer reads the subject name from
`expert_details` rather than from the resolved object.

## ECR-0107 — the collector stops assuming Debian

ECR-0102 named three blind spots and this closes them: package managers other than APT, disk
encryption, and automatic updates. `dnf check-update` exits 100 when updates exist, so each tool
carries the exit code that means "the command answered" - treating non-zero as failure would have
called exactly the machines that need patching unreadable.

Two of my own parsers were wrong. `parse_unattended_upgrades` read the wrong split index and
matched nothing, so every machine would have reported automatic updates disabled - a confident
false positive. `parse_dnf_updates` counted the Obsoleting trailer. Both were caught by the
witnesses written in the same commit, which is the situation where a test most often passes for
the wrong reason.

ECR-0102's `test_every_unreadable_fact_produces_its_own_unmeasured_observation` earned its keep:
it asserts set equality rather than a count, so two new facts made it fail until the list was
updated. A count would have passed silently.

Eleven mutations red; one of them exposed that a new check had only an indirect catcher, and a
direct witness was added. Five necessity runs, all green. Measured on this machine: six
observations, up from four - no encrypted volume, no automatic updates, 31 pending packages.

Open and named: `lsblk` sees mappings not policy, Windows and macOS remain invisible, and the
zypper and pacman parsers have no real-output fixture.

## ECR-0108 — plain words beside the finding, never instead of it

UX-008's vocabulary half was recorded against my own work twice, in ECR-0104 and again in
ECR-0105, each time with a stated reason: a second rendering of the same fact is where a
"simplified" version drifts from a true one, and nothing can witness that drift when both
sentences are things we wrote.

That reason is the design. The plain language is additive - the finding's sentence is untouched
in every mode and the technical terms it contains are annotated beneath it, for home and SMB
readers only. One rendering of the fact, nothing to drift from.

The invariant is witnessed by rendering ONE analysis four ways. Building a fresh analysis per
mode mints new evidence ids and compares different findings; ECR-0104 made exactly that mistake
and repeating it here would have produced a test that passes for the wrong reason.

Eight mutations red, including the only one whose failure would be a lie rather than a missing
feature: a home reader served a reworded sentence. Three necessity runs, all green.

Second harness defect of the same family as ECR-0105: a grep-computed line number came back
empty, `int("")` raised, the applier exited 1, and `lib.sh` only treated exit 9 as "did not
apply" - so the cell ran against pristine source and reported GREEN. The driver now rejects a
non-numeric line, an out-of-range line, any non-zero applier exit, and an unchanged file. Second
time this project has been bitten by a mutation that did not mutate; the first was a wrong
working directory.

An existing absence guard earned its keep: EA-0054 Web Intelligence is a recorded decision not
to build, and my draft glossary defined four web- and mail-intelligence terms. The guard fired,
then fired again on the comment explaining the removal - the census is a text scan. The terms
went, not the guard. That turned a hypothetical gap into a measured one: 8 of 18 terms appear in
this machine's real rendered report, and a witness now asserts the glossary is grounded in
genuine check output at all.

Open and named: nothing measures the reverse direction (a word the checks use and the glossary
lacks is still invisible), definitions whose correctness no test can check, and English only.

## ECR-0109 — the firewall reader told the truth in neither direction

Running the ECR-0107 collector against the live one.com VPS, rather than a fixture, produced
"a host firewall (ufw) is installed but not active" for a machine whose firewall is active with
seven rules. `ufw status` needs root; without it the tool prints an error, and the reader asked
only whether the output contained "status: active".

`collect/host.py`'s own docstring already said a firewall whose state could not be determined
must not become "no firewall". The doctrine was written and the code three hundred lines below
it did the opposite.

The same three lines held the mirror-image defect: the firewalld branch tested `"running" in
output`, and `firewall-cmd --state` prints "not running" when stopped. A stopped firewall would
have read as active. Nobody had run it on a firewalld host, so it had never been seen.

The fix separates "did the command answer" from "what did it say". The exit code is deliberately
not the test - firewalld exits 252 when stopped, which is a real answer.

ECR-0107's matrix was 11/11 red and contained neither defect, because both live in code it did
not touch and no fixture exercised the failing input. What found them was pointing the collector
at a machine that was not mine - one script, because `read_host_facts` already takes an
injectable runner and that injection point works for ssh as well as for a test double.

Five mutations red, two necessity runs green, six new tests. All six firewall states verified
directly.

Open and named: nftables and iptables remain invisible, "active" is not "default-deny", and no
test runs the real ufw binary - which is exactly how the original defect survived.

## ECR-0110 — the SSH reader read the wrong file, in the wrong order

The same live-VPS run that produced ECR-0109 reported ssh password auth as unmeasured. Ubuntu
26.04 comments out the auth directives in the main sshd_config and puts them in
`/etc/ssh/sshd_config.d/*.conf`; the reader never followed the Include.

The drop-ins on that machine disagree - `50-cloud-init.conf` says yes, `60-cloudimg-settings.conf`
says no - and sshd takes the FIRST value in sorted glob order, so yes wins. `sshd -T` confirms.
**Password authentication is enabled on the production VPS, on port 22 open to 0.0.0.0.** Exactly
the high-severity finding this check exists to raise.

The reader also kept the LAST matching directive, and an ECR-0102 test asserted that rule was
correct. It is not. Proven against a real sshd in both orders rather than from the man page. Had
last-wins stood, the collector would have read the VPS as `no` - a false all-clear on the finding
that matters most.

Two mutations ran GREEN and both were real. M3's witness depended on directory iteration order,
so `sorted()` could be removed without failing anything; replaced by one asserting the resolver's
own output order. M6's `#` guard on the Include branch cannot change a verdict, because a
commented Include's first token is never `include`; removed, following the `is_public` precedent
that dead code in a security path is a liability. `parse_ssh_password_auth` deliberately keeps
its own - what matters is knowing which you have.

Six mutations red, nine new tests, one corrected assertion. Validated against `sshd -T` on the
real machine, not against a fixture.

**Not fixed on the server, deliberately:** disabling password auth means I cannot verify how the
owner reaches that machine, and getting it wrong locks them out of production while they are
away. The exact command is in ECR-0110 §7.

Open and named: Match blocks are ignored, KbdInteractiveAuthentication is not read, and the
collector still cannot run `sshd -T`, so this re-implements sshd's parsing and re-implementations
drift.
