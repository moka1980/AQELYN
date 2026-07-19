# EA-0030 — Software Supply Chain Security & SBOM Intelligence — Implementation Specification

**Realizes:** EA-0030 / IS-030 (supersedes the placeholder `archive/EA-0030/EA-0030_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0002 (components are objects), EA-0005 (dependency graph), EA-0025 (software inventory), EA-0024 (component vulns), EA-0010 (license compliance), EA-0013 (supply-chain risk), EA-0004 (provenance attestation backbone)**, EA-0006 (Trust), EA-0008 (remediation gated)
**Consumed by:** EA-0024 (components as vuln-bearing assets), EA-0013 (risk signal), the supply-chain UI (a WCAG 2.2 AA surface)
**Status:** Accepted
**Build milestone:** C-027 (see `C-027_Task_Bundle.md`)
**Change control:** ECR-0037 (durable Trust reconciliation + D8 store pagination),
ECR-0038 (truncation-bearing path result + content-addressed reachability path)
**Definition of Ready:** see §12

---

## 0. Scope reconciliation — genuinely new, with heavy reuse

The ECR-0015 check confirms **net-new surface**: `sbom`, `supply.chain`,
`component.vuln`, `license` → **0 shipped specs**. Nothing models software
components or their dependency graph. But four of six components have owners:

| IS-030 component | Realization |
|---|---|
| 12.1 Software Inventory | **EA-0025** — a software component is an asset; inventory/lifecycle/`unreported` all apply. **Restatement.** |
| **12.2 SBOM Intelligence** | **NET-NEW** — parse/normalize SPDX + CycloneDX into components + dependency edges (§2). |
| **12.3 Dependency Analysis** | **NET-NEW modelling** (deps as edges) **+ EA-0005 traversal** for transitive reach (§2 S1). |
| **12.4 Provenance Verification** | **NET-NEW verification logic**, **reusing the EA-0004 hash-chain/attestation backbone** (as EA-0016 forensics reused it). |
| 12.5 Supply Chain Compliance | **EA-0010** — a license policy is a policy/framework; license *identification* is new (§2), scoring is EA-0010's. |
| 12.6 Supply Chain Risk | **EA-0024** (component CVE prioritization) + **EA-0013** (aggregate risk). Not a parallel path. |

So EA-0030's **genuinely-new core** is: **SBOM parsing, the dependency graph,
provenance verification, and license identification.** Everything else routes to
its owner.

### 0.1 Boundary

SBOMs and provenance attestations are **handed in** (`SBOMDocument` /
`ProvenanceAttestation` posted to the platform). This engine reads no build
system, clones no repo, calls no package registry — **build/registry integration
is an EA-0008-gated connector action** (`supplychain.fetch`), per EA-0025 §0.1.

## 1. The central problem: your risk is the code you didn't write

A modern application is a few thousand lines you wrote on top of **hundreds of
thousands you didn't** — pulled in transitively, most never directly imported,
each a potential entry. The supply-chain question is unique because of the
**graph**: a vulnerability six dependencies deep, in a package you've never heard
of, can still be the one that reaches you — *or* it can be unreachable dead
weight. Answering "which of my 900 transitive dependencies actually matters"
needs the dependency graph, and AQELYN already has a graph engine.

- **S1 — The dependency graph is EA-0005.** A `DependencyRelationship` is an
  **edge** (`component --depends_on[version_range]--> component`). "What
  transitively reaches this vulnerable package?" and "what does this package
  transitively pull in?" are **KG traversals** — bounded, explainable. No second
  graph engine.
- **S2 — A component vulnerability is an EA-0024 vulnerability.** A CVE in a
  dependency flows through **EA-0024's existing prioritization** (the 6-factor
  derivation), not a parallel supply-chain vuln scorer. **Supply chain adds one
  factor EA-0024 should weigh: transitive reachability** — a vuln in a directly-
  called dependency is not the same as one in an unreachable transitive dep, and
  saying so is this engine's contribution to the priority, supplied as a signal.
- **S3 — Provenance is verified, never assumed.** An unsigned or unverifiable
  component is **flagged `unverified`**, not treated as trusted-by-default.
  Verification reuses the **EA-0004** hash-chain + attestation machinery (the
  EA-0016 forensics precedent — one integrity backbone). A failed signature is
  surfaced, never suppressed.
- **S4 — Detect-and-propose.** Upgrading/removing a dependency is a **proposed
  gated EA-0008 run**; nothing is patched here.
- **S5 — Compose, don't rebuild** (§0): inventory → EA-0025, CVE prioritization →
  EA-0024, license scoring → EA-0010, risk → EA-0013, graph → EA-0005,
  attestation → EA-0004, confidence → EA-0006.
- **S6 — SBOM is a claim, not ground truth.** A handed-in SBOM asserts what a
  build *says* it contains; it carries its source + is evidence-backed, and
  conflicting SBOMs for the same artifact are reconciled (EA-0025 pattern), not
  blindly trusted.

Deterministic, tenant-scoped, bounded, no network.

## 2. Purpose

Turn a handed-in SBOM into a **queryable, risk-aware dependency graph**: every
component and transitive dependency as a graph you can traverse, each component's
known vulnerabilities prioritized *with its reachability*, its license
identified and checked, and its provenance verified rather than assumed — so
"are we exposed to the next Log4Shell, and if so where and how deep" has an
evidence-backed answer.

## 3. Design decisions

- **D1 — SBOM parsing is format-specific, output is normalized.** SPDX + CycloneDX
  parsers → `SoftwareComponent` objects (EA-0002) + `DependencyRelationship`
  edges (EA-0002/EA-0005). Unparseable/partial SBOM → quarantined, flagged (the
  EA-0014 handed-in-data discipline).
- **D2 — Components are EA-0025 assets** (`object_type "software_component"`),
  deduped by `purl` (package URL) natural key; inventory/lifecycle is EA-0025's.
- **D3 — Dependencies are EA-0005 edges**; transitive reach = traversal (S1).
- **D4 — Component CVEs route to EA-0024**, carrying a **reachability signal**
  (S2). This engine identifies the component↔CVE match (via `purl`/version); the
  prioritization is EA-0024's.
- **D5 — Provenance verification reuses EA-0004** (S3): an attestation's
  signature/hash is verified against the component; result is `verified` /
  `unverified` / `failed`, evidence-recorded.
- **D6 — License identification is new; license *policy* is EA-0010** (S5).
- **D7 — Registered as an `AQService`;** store in-memory + Postgres.

## 4. Types

```
SBOMFormat = "spdx" | "cyclonedx"
ReachabilityStatus = "direct" | "transitive" | "unreachable" | "unknown"
AssessmentStatus = "complete" | "truncated" | "pending"

SBOMDocument = { doc_id: str, format: SBOMFormat, subject_ref: str,   # the artifact it describes
                 raw: dict, source_id: str, observed_at: datetime,
                 evidence_id: str | null }                            # handed in (§0.1/S6)

SoftwareComponent = { object_id, tenant_id, purl: str,               # package URL natural key (D2)
                      name: str, version: str, component_type: str,
                      licenses: list[str],                            # identified (D6)
                      supplier: str | null, hashes: dict,
                      provenance_status: "verified"|"unverified"|"failed",  # S3
                      direct: bool, source_id: str, observed_at: datetime,
                      evidence_id: str, conflicts: list[ComponentConflict] }
ComponentConflict = { fields: list[str], candidates: list[ComponentConflictCandidate],
                      resolved_by: str | null, resolved_evidence_id: str | null,
                      unresolved: bool, reason: str }                 # ECR-0037
QuarantinedSBOM = { doc_id, tenant_id, source_id, observed_at, evidence_id,
                    raw: dict, reason: str, flagged: true,
                    quarantined_at: datetime }                        # ECR-0037

DependencyRelationship = { from_purl: str, to_purl: str,
                           version_constraint: str | null, scope: str,   # runtime|dev|optional
                           edge_id: str }                            # -> EA-0002/EA-0005 (D3)

DependencyPathResult = { paths: list[Path], truncated: bool }       # ECR-0038

ReachabilitySignal = { component_purl: str, cve_id: str,
                       reachable: ReachabilityStatus = "unknown",
                       depth: int | null, path_ref: str | null,
                       path: Path | null,                            # exact EA-0005 path (S2/ECR-0038)
                       reason: str }

ProvenanceAttestation = { component_purl: str, kind: str,            # slsa|sigstore|signature
                          raw: dict, evidence_id: str | null }        # handed in
ProvenanceResult = { component_purl: str, status: "verified"|"unverified"|"failed",
                     detail: str, evidence_id: str }                 # EA-0004-backed (S3)

SupplyChainAssessment = { id, tenant_id, run_at, subject_ref: str,
                          components: int, direct: int, transitive: int,
                          unverified_provenance: int, vulnerable_components: int,
                          assessment_status: AssessmentStatus = "pending", evidence_id: str }
SupplyChainConfig = { license_policy_id: str | null, sensitive_scopes: list[str],
                      max_depth: int, batch_size: int }
```

Reuses EA-0002 objects/edges, EA-0005 traversal, EA-0024 vuln path, EA-0004
attestation, EA-0006 reliability.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class SBOMStore(Protocol):
    async def put_component(self, c: SoftwareComponent) -> SoftwareComponent: ...   # purl dedupe
    async def get_component(self, purl: str, *, tenant_id: str | None) -> SoftwareComponent | None: ...
    async def put_assessment(self, a: SupplyChainAssessment) -> SupplyChainAssessment: ...
    async def get_assessment(self, assessment_id: str, *,
                             tenant_id: str | None) -> SupplyChainAssessment | None: ...
    async def query(self, *, tenant_id: str | None, provenance: str | None = None,
                    limit: int = 1000, cursor: str | None = None
                    ) -> tuple[list[SoftwareComponent], str | None]: ...  # ECR-0037/D8
    async def quarantine(self, item: QuarantinedSBOM) -> QuarantinedSBOM: ...
    async def get_quarantine(self, doc_id: str, *,
                             tenant_id: str | None) -> QuarantinedSBOM | None: ...

class SupplyChainEngine(Protocol):
    async def ingest_sbom(self, doc: SBOMDocument, *,
                          tenant_id: str | None) -> list[SoftwareComponent]: ...    # parse+normalize (D1); no fetch (§0.1)
    async def dependency_paths(self, purl: str, *, direction: str,
                               tenant_id: str | None) -> DependencyPathResult: ...  # EA-0005 (S1/ECR-0038)
    async def reachability(self, component_purl: str, cve_id: str, *,
                           tenant_id: str | None) -> ReachabilitySignal: ...        # S2
    async def component_vulns_to_prioritization(self, purls: Sequence[str], *,
                                                by: ActorRef) -> list[str]: ...     # -> EA-0024 (D4/S2)
    async def verify_provenance(self, attestations: Sequence[ProvenanceAttestation], *,
                                tenant_id: str | None) -> list[ProvenanceResult]: ... # EA-0004 (S3)
    async def assess(self, *, subject_ref: str, tenant_id: str | None) -> SupplyChainAssessment: ...
    async def license_findings(self, *, tenant_id: str | None, by: ActorRef) -> list[str]: ...  # id here; policy EA-0010
    def explain(self, sig: ReachabilitySignal) -> dict: ...
```

`SupplyChainService` wraps engine + store as an `AQService`
(name `"supplychain_engine"`, depends on object/kg/inventory/vuln/compliance/
risk/evidence/trust; health reflects availability + config validity).

**Deliberately absent:** any registry/build fetch (§0.1); any second vuln scorer
(EA-0024) or second graph engine (EA-0005).

## 6. Computation (the reference model)

**Ingest SBOM.** Parse the handed-in `SBOMDocument` (format-specific) →
`SoftwareComponent`s (dedupe by `purl`, route to **EA-0025** as assets) +
`DependencyRelationship` edges (→ **EA-0002**, traversable by **EA-0005**).
Unparseable → quarantine, flagged (D1). Conflicting SBOMs for one artifact →
reconciled by EA-0006 (S6). Evidence-recorded.

**Dependency paths + reachability.** `dependency_paths` traverses EA-0005 (up =
"who depends on this", down = "what this pulls in"), bounded by `max_depth`,
`truncated` propagated through `DependencyPathResult`. `reachability` classifies
a component/CVE as `direct` / `transitive` (with depth + the exact EA-0005
`Path`, content-addressed by `path_ref`) / `unreachable` / **`unknown`** — and `unknown`
is never rendered as `unreachable` (the empty-means-safe trap: absence of a
computed path is not proof of no path) (S2).

**Component vulns → EA-0024.** Match component `purl`/version to CVEs;
`component_vulns_to_prioritization` hands them to **EA-0024** with the
`ReachabilitySignal` so EA-0024's derivation can weigh "is the vulnerable code
actually reachable" — a genuinely better priority than CVSS-on-a-transitive-dep
(S2/D4).

**Provenance.** `verify_provenance` checks each attestation's signature/hash via
the **EA-0004** backbone; `verified`/`unverified`/`failed`, evidence-recorded; an
`unverified` component is flagged, **never assumed trusted** (S3).

**License + assess.** Identify licenses per component (new); `license_findings`
raises findings that **EA-0010** scores against license policy. `assess`
snapshots the graph + provenance + vuln counts (evidence-recorded). Its
`assessment_status` starts as `pending`, becomes `complete` only after all
in-scope work finishes, and becomes `truncated` when a bound stops the work.

## 7. Requirements

### Functional (testable)

- **FR-1** `ingest_sbom` SHALL parse handed-in SPDX/CycloneDX only; the module SHALL clone no repo, call no registry, and expose no fetch method (§0.1).
- **FR-2** Parsed components SHALL be `SoftwareComponent`s deduped by `purl` and routed to **EA-0025**; the module SHALL NOT implement its own inventory/lifecycle (D2/S5).
- **FR-3** Dependencies SHALL be **EA-0002 edges**; transitive reach SHALL use **EA-0005** traversal bounded by `max_depth`; `dependency_paths` SHALL return `DependencyPathResult` and propagate the owner's `truncated` signal; the module SHALL NOT implement graph traversal (S1/D3/ECR-0038).
- **FR-4** `reachability` SHALL classify `direct|transitive|unreachable|unknown`, default to `unknown`, and SHALL NEVER report `unknown` as `unreachable` (absence of a computed path ≠ no path). A transitive signal SHALL embed the exact EA-0005 `Path`; `path_ref` SHALL be its deterministic content address, and a mismatched path/reference pair SHALL be unconstructable (ECR-0038).
- **FR-5** Component CVEs SHALL be routed to **EA-0024** with a `ReachabilitySignal`; the module SHALL NOT implement a second vulnerability scorer (S2/D4).
- **FR-6** `verify_provenance` SHALL use the **EA-0004** hash-chain/attestation backbone; an unverifiable component SHALL be `unverified` (flagged), never assumed trusted; a failed signature SHALL be surfaced (S3).
- **FR-7** Unparseable/partial SBOMs SHALL be persisted as flagged `QuarantinedSBOM` records before `SBOMParseError` is raised; no component from that document is accepted (D1/ECR-0037).
- **FR-8** Conflicting SBOMs for one artifact SHALL be reconciled by EA-0006 reliability, with winning source metadata and every candidate persisted in `ComponentConflict`; equal-reliability disagreements remain explicitly unresolved (S6/ECR-0037).
- **FR-9** License *identification* SHALL be performed here; license *policy scoring* SHALL be **EA-0010**; the module SHALL NOT implement license policy (D6/S5).
- **FR-10** Dependency upgrade/removal SHALL be a **proposed gated EA-0008 run**; the module SHALL change nothing (S4).
- **FR-11** Supply-chain risk aggregation SHALL be **EA-0013**; the module SHALL NOT implement a risk scorer (S5).
- **FR-12** All operations SHALL be tenant-scoped and bounded; invalid config (unknown format, `max_depth ≤ 0`, `batch_size ≤ 0`) SHALL raise `SupplyChainConfigInvalid`.
- **FR-13** `SBOMStore` in-memory and Postgres implementations SHALL pass one contract suite; component queries use an exclusive object-id cursor, apply all filters before `limit`, and return `next_cursor` exactly when another matching component exists (EA-0002 D8/ECR-0037).
- **FR-14** `SupplyChainService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).
- **FR-15** `SupplyChainAssessment.assessment_status` SHALL default to `pending`; it SHALL be `complete` only after all in-scope work finishes and `truncated` whenever a configured bound stops the assessment.

### Non-functional

- **NFR-1 (reachability honesty — structural)** `unknown` reach is a distinct value from `unreachable`; a component/CVE whose reachability was not computed is never presented as safe; verified behaviourally (default `unknown`, not `unreachable`), per **ECR-0007** and the ECR-0035 precedent.
- **NFR-2 (no rebuild)** graph → EA-0005, CVE prioritization → EA-0024, inventory → EA-0025, license policy → EA-0010, risk → EA-0013, attestation → EA-0004; delegation spies prove it.
- **NFR-3 (no fetch)** socket spy proves zero outbound; no registry/build method.
- **NFR-4 (provenance not assumed)** unverified ≠ trusted; proven by test.
- **NFR-5 (bounded & typed)** batched, depth-capped; store passes one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Handed-in SBOM only; no fetch/clone/registry | `test_sc_no_fetch` |
| AC-2 | SPDX + CycloneDX parse → components + edges | `test_sc_parse_formats` |
| AC-3 | Components deduped by purl, routed to EA-0025 | `test_sc_components_to_inventory` |
| AC-4 | Dependencies are EA-0002 edges; reach delegates to EA-0005 and propagates truncation | `test_sc_dependency_graph` |
| AC-5 | Reachability defaults to unknown; truncation is unknown, never unreachable; transitive paths are content-addressed | `test_sc_reachability_unknown_not_safe` |
| AC-6 | Component CVEs → EA-0024 w/ reachability signal | `test_sc_vulns_to_ea0024` |
| AC-7 | Provenance verify via EA-0004; unverified flagged | `test_sc_provenance_verify` |
| AC-8 | Failed signature surfaced, not suppressed | `test_sc_provenance_failure` |
| AC-9 | Unparseable SBOM quarantined | `test_sc_quarantine` |
| AC-10 | Conflicting SBOMs reconciled by Trust | `test_sc_sbom_conflict` |
| AC-11 | License identified here; policy → EA-0010 | `test_sc_license_delegates` |
| AC-12 | Upgrade/removal proposed + gated | `test_sc_remediation_gated` |
| AC-13 | Risk aggregation → EA-0013; no local scorer | `test_sc_delegations` |
| AC-14 | No side effects; tenant isolation | `test_sc_no_side_effects` |
| AC-15 | Invalid config rejected | `test_sc_config_invalid` |
| AC-16 | Store in-memory & Postgres pass one suite | `test_sc_store_contract[inmemory]` / `[postgres]` |
| AC-17 | Registers as AQService with health | `test_sc_service_health` |
| AC-18 | Assessment defaults pending; bounded partial work is truncated, never complete | `test_sc_assessment_status_not_clean` |
| AC-19 | Store pagination is stable and filter-complete on both backends | `test_sc_store_contract[inmemory]` / `[postgres]` |

## 9. Error taxonomy (contributions)

`SupplyChainConfigInvalid`, `SBOMParseError`, `ComponentNotFound`,
`ProvenanceUnverifiable` (added to `conventions.errors` + CONVENTIONS §9). Reuses
EA-0004 `EvidenceTampered`, `StoreUnavailable`, `TenantScopeRequired`.

## 10. Registered event types (owned by EA-0030)

`aqelyn.supplychain.sbom_ingested`, `aqelyn.supplychain.dependency_risk_detected`,
`aqelyn.supplychain.provenance_failed` — via `register_supplychain_events()`
(EA-0003 §7). (Archive uses `dependency.risk.detected`; mapped into the platform
namespace.) Component-CVE events stay EA-0024's; risk events stay EA-0013's (§0).

## 11. Failure handling

- Invalid config / unparseable SBOM → `SupplyChainConfigInvalid` / `SBOMParseError`
  + quarantine; never silent acceptance.
- EA-0005/EA-0024/EA-0025 unavailable → `StoreUnavailable`; service `degraded`;
  reachability marked `unknown` (not `unreachable`), components stored, gap
  surfaced — **a partial supply-chain picture is never presented as clean** (S2).
- Provenance backbone unavailable → components marked `unverified` (flagged), not
  `verified` — absence of verification is not verification (S3).
- A dep whose reachability exceeds `max_depth` → assessment `truncated`, surfaced;
  work that never ran remains `pending`, never clean-looking `complete`.
- Remediation proposal failure → finding stands, delegation failure surfaced, no
  direct change (S4).

## 12. Dependencies & consumers

- **Depends on / routes to:** **EA-0025** (inventory), **EA-0005** (dependency
  graph), **EA-0024** (component CVE prioritization), **EA-0010** (license
  policy), **EA-0013** (risk), **EA-0004** (provenance attestation), **EA-0006**
  (Trust); EA-0002 (objects/edges); **EA-0008** (remediation gated); EA-0001
  `AQService`.
- **Consumed by:** **EA-0024** (components are vuln-bearing assets, enriched with
  reachability); **EA-0013** (supply-chain risk signal); the supply-chain UI
  (**WCAG 2.2 AA**).

## 13. Resolved / deferred decisions

- **The dependency graph is the point, and it is EA-0005** (S1) — transitive
  reach is traversal, not a new engine.
- **A component vuln is an EA-0024 vuln** (S2) — enriched with **reachability** as
  a new prioritization signal, not scored in a parallel path.
- **Provenance verified, never assumed** (S3), reusing EA-0004 — one integrity
  backbone (the EA-0016 precedent).
- **SBOM/attestations handed in** (§0.1) — build/registry fetch is an
  EA-0008-gated connector action.
- **`unknown` reachability ≠ `unreachable`** (S2/NFR-1) — the ECR-0035 empty-means-
  safe lesson, applied at spec time rather than found in review.
