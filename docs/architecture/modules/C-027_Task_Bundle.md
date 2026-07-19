# C-027 Software Supply Chain Security & SBOM — Implementation Task Bundle

**Milestone:** C-027 (Software Supply Chain Security & SBOM, EA-0030)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-026 (EA-0029) merged & green; EA-0030 spec **Accepted**; **EA-0030 §1 read**; CONVENTIONS + EA-0004/0005/0010/0013/0024/0025 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no fetch/clone/registry; no second vuln scorer or graph engine; unknown ≠ unreachable; unverified ≠ trusted**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0030 §1 first.** The supply-chain problem is unique because of the
**graph**: your risk isn't the code you wrote, it's the hundreds of thousands of
transitive lines you didn't — and a vuln six dependencies deep can still reach
you, *or* be unreachable dead weight. Answering "which of my 900 transitive deps
actually matters" is a **traversal**, and AQELYN already has a graph engine
(EA-0005) and a vuln prioritizer (EA-0024). This module supplies the **new**
parts — SBOM parsing, the dependency graph, provenance verification, license
identification — and **routes** everything else.

**Two traps this module must not fall into (both are prior lessons):**
- **`unknown` reachability is not `unreachable`** — the ECR-0035 empty-means-safe
  bug family. A CVE whose reachability wasn't computed is never "safe".
- **`unverified` provenance is not `trusted`** — absence of a signature check is
  not a passing signature.

**Verification standard (ECR-0007):** structural (`unknown`/`unreachable` are
distinct values; no verdict-by-default) + behavioural (delegation spies for
EA-0005/EA-0024/EA-0025/EA-0010/EA-0013/EA-0004; socket spy). Not textual checks.

## Target source layout

```
src/aqelyn/supplychain/
├── __init__.py       # exports the engine, service, types, register_supplychain_events
├── models.py         # SBOMDocument, SoftwareComponent, DependencyRelationship,
│                     #   ReachabilitySignal, ProvenanceAttestation, ProvenanceResult,
│                     #   SupplyChainAssessment, SupplyChainConfig (Q1)
├── parse.py          # SPDX + CycloneDX parsers -> components + edges; quarantine (Q2)
├── graph.py          # dependency_paths + reachability via EA-0005 (Q3)
├── provenance.py     # verify_provenance via EA-0004 backbone (Q4)
├── store.py          # SBOMStore protocol (Q2)
├── memory.py / postgres.py  # stores + DDL (Q2)
├── engine.py         # ingest + route-to-EA-0024/0025/0010/0013 + assess + license id (Q3/Q5)
└── service.py        # SupplyChainService(AQService) + register_supplychain_events (Q5)
tests/supplychain/    # acceptance suite (in-memory + Postgres)
```

**No `vuln.py`, no `traversal.py`, no `risk.py`** — those are EA-0024/EA-0005/
EA-0013. If they appear, the milestone has gone wrong.

---

## Q1 — Types & config

**Spec:** §4, FR-4/12/15; §9. **Deliverables:** models with fail-safe defaults
(`ReachabilityStatus="unknown"`, `AssessmentStatus="pending"`); config validation
(`SupplyChainConfigInvalid`); error codes in `conventions.errors` + CONVENTIONS §9.
**Acceptance:** `test_sc_config_invalid`, `test_sc_assessment_status_not_clean`.

## Q2 — SBOM parsing (handed-in) + store

**Spec:** §0.1, §6, FR-1/2/7/8/13, D1/D2, S6, NFR-3.
**Deliverables:** SPDX + CycloneDX parsers → `SoftwareComponent`s (dedupe by
`purl`, route to **EA-0025**) + `DependencyRelationship` edges; **no fetch/clone/
registry**; unparseable → **quarantine, flagged**; conflicting SBOMs reconciled by
**EA-0006**; `SBOMStore` (in-memory + Postgres + DDL), including EA-0002
D8-style filter-complete cursor pagination and durable conflict/quarantine
records (ECR-0037).
**Depends on:** Q1.
**Acceptance:** `test_sc_no_fetch`, `test_sc_parse_formats`,
`test_sc_components_to_inventory`, `test_sc_quarantine`, `test_sc_sbom_conflict`,
`test_sc_store_contract[inmemory]`, `test_sc_store_contract[postgres]`.

## Q3 — Dependency graph + reachability (unknown ≠ unreachable)

**Spec:** §1 (S1/S2), §6, FR-3/4, D3, NFR-1.
**Deliverables:** dependencies as **EA-0002 edges**; `dependency_paths` (up/down)
via **EA-0005**, `max_depth`-bounded, returning `DependencyPathResult` with
`truncated` propagated; `reachability`
classifying `direct|transitive|unreachable|unknown` — **`unknown` is the type default
and is never rendered `unreachable`**. A transitive signal embeds the exact
EA-0005 `Path`, and `path_ref` content-addresses that path (ECR-0038).
**Depends on:** Q2.
**Acceptance:** `test_sc_dependency_graph`, `test_sc_reachability_unknown_not_safe`.

## Q4 — Provenance verification (unverified ≠ trusted)

**Spec:** §1 (S3), §6, FR-6, D5, NFR-4.
**Deliverables:** `verify_provenance` uses **EA-0004** for cited/result evidence
integrity and a kind-specific `ProvenanceVerifier` for authenticity (ECR-0039);
EA-0004 integrity alone never means a valid signature. `verified|unverified|failed`
remain distinct and evidence-recorded where the backbone is available;
**unverified flagged, never assumed trusted**; failed signature **surfaced**.
**Depends on:** Q3.
**Acceptance:** `test_sc_provenance_verify`, `test_sc_provenance_failure`.

## Q5 — Route component vulns + license + risk + service

**Spec:** §6, FR-5/9/10/11/14, D4/D6, S4/S5.
**Deliverables:** `component_vulns_to_prioritization` → **EA-0024** carrying the
`ReachabilitySignal` (no second scorer); license **identification** here,
`license_findings` → **EA-0010** for policy; risk aggregation → **EA-0013**;
upgrade/removal = **proposed gated EA-0008 run**; `SupplyChainService`
(`AQService`, name `"supplychain_engine"`) + `register_supplychain_events`; wired
into the kernel factory.
**Depends on:** Q4.
**Acceptance:** `test_sc_vulns_to_ea0024`, `test_sc_license_delegates`,
`test_sc_delegations`, `test_sc_remediation_gated`, `test_sc_no_side_effects`,
`test_sc_tenant_isolation`, `test_sc_service_health`.

---

## Review protocol (Claude Code) — the graph is the point; the traps are old friends

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **`unknown` ≠ `unreachable`.** They must be distinct values; a CVE whose reach
   wasn't computed defaults to `unknown` and is **never** presented as safe.
   Degrade EA-0005 and assert reachability becomes `unknown`, not `unreachable`
   (S2/NFR-1 — the ECR-0035 family).
2. **`unverified` ≠ `trusted`.** With no attestation or a broken one, the
   component is `unverified`/`failed` and **flagged** — absence of a check is not
   a passing check (S3/NFR-4).
3. **No second engine.** Graph traversal is **EA-0005**; CVE prioritization is
   **EA-0024** (component vulns routed **with** the reachability signal, not
   re-scored); inventory **EA-0025**; license policy **EA-0010**; risk
   **EA-0013**; attestation **EA-0004**. Delegation spies (NFR-2). If any of these
   is reimplemented in `supplychain/`, it's wrong.
4. **No fetch.** Socket spy proves zero outbound; no registry/clone/build method
   (§0.1).
5. **SBOM is a claim** — unparseable → quarantined; conflicting SBOMs reconciled
   by Trust, recorded (S6).
6. **Partial ≠ clean** — degraded dependencies produce `unknown`/`truncated`, a
   surfaced gap, never a clean-looking supply-chain report.
7. `ruff` + `mypy --strict` clean; tenant-scoped; interfaces match the spec.

Merge only on green review; then **report back to the owner** before the next
module.
