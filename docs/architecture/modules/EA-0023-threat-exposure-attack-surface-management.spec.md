# EA-0023 — Threat Exposure & Attack Surface Management Engine — Implementation Specification

**Realizes:** EA-0023 / IS-023 (supersedes the placeholder `archive/EA-0023/EA-0023_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0012 (asset/config inventory — the known surface)**, **EA-0019 (telemetry/discovery history)**, **EA-0005 (KG `paths()` — attack paths)**, **EA-0011 (identity/access risk — cited)**, **EA-0007 (mission) × EA-0006 (trust) — scoring**, EA-0013 (risk, via findings), EA-0021 (trends), EA-0020 (`Derivation` — explainability), EA-0004 (evidence), EA-0008 (Workflow — the only actor), EA-0009 (Policy)
**Consumed by:** EA-0022 (executive exposure summaries), EA-0013 (exposures arrive as findings), EA-0024 (Vulnerability Intelligence — exposure as a prioritization input), EA-0031 (data sensitivity context), EA-0032 (credential sensitivity context)
**Status:** Accepted
**Build milestone:** C-020 (see `C-020_Task_Bundle.md`)
**Change control:** ECR-0011 (no-scan boundary), ECR-0030 (object pagination),
ECR-0041 (optional evidence-backed exposure impact context for DSPM), ECR-0044
(semantic credential-sensitivity context with backward-compatible default)
**Definition of Ready:** see §9

---

## 0. Scope reconciliation

IS-023 lists thirteen components. **This engine discovers exposure by deriving it
from what the platform already knows — it never touches a target.** Four of the
"engines" are reuse of an existing owner, and the discovery boundary (§0.1) is the
whole safety story.

| IS-023 component | Realization |
|---|---|
| Asset Discovery Engine | **Reframed (§0.1 / S1)** — derives the surface from EA-0012 asset/config inventory, EA-0019 telemetry, EA-0011 access, EA-0005 KG. **No `scan()`/`probe()`/`connect()`.** Not a scanner. |
| Exposure Analysis Engine | **New** — classifies reachability/exposure over already-owned data. |
| Attack Surface Engine | **New inventory** (`AttackSurfaceAsset`); attack **paths** are **EA-0005 `paths()`** (S4), not a new path engine. |
| Exposure Scoring Engine | **Composes EA-0007 (mission) × EA-0006 (trust), risk via EA-0013** (S6) — no fourth scorer. |
| Cloud Exposure Engine | **New** — cloud reachability over known cloud-asset config (EA-0012). |
| Identity Exposure Engine | **Cites EA-0011** (S5) — asks *"is it reachable?"*; EA-0011 owns *"are the entitlements right?"*. No re-detection. |
| API Exposure Engine | **New** — API reachability over known API assets. |
| Trend Analysis Engine | **Delegates EA-0021** (S6) — no second trend engine. |
| KG / Data Lake / Risk / AI Decision Connectors | **Reuse** EA-0005 / EA-0019 / EA-0013 / EA-0020. |
| Event Publisher | **New** exposure events (§11). |
| *(reuse)* Confidence | **EA-0006 Trust**. |
| *(reuse)* Explainability | **EA-0020 `Derivation`** where a score is composed. |
| *(reuse)* Remediation | **EA-0008 Workflow** — the only actor; the engine proposes, never acts (S8). |

Tenant-scoped, append-only, **no network**, no new authorization surface.

## 0.1 The discovery boundary (the line this module turns on)

> **Scanning is something you do *to* a system, not something you learn *about*
> one.** A port scan touches a machine that does not belong to this platform: it
> can disrupt fragile services, it trips other parties' detection, and pointed at
> the wrong netblock it may be unlawful. **It is not read-only from the target's
> point of view.**

So this engine has **no `scan()`, `probe()`, or `connect()` method — none.** It
derives the attack surface entirely from data the platform already holds (EA-0012
inventory, EA-0019 telemetry, EA-0011 access, EA-0005 KG). When active scanning
eventually arrives it is **not** a method here — it is an **EA-0008 `ActionSpec`**:
capability **`scan.active`**, **at minimum reversible**, **Policy-authorized**
(scope is the entire safety question), delivered by a **connector**, and requested
as a **proposed gated run**. This engine then consumes its results as **stored
data, unchanged**. Recorded as **ECR-0011**.

## 1. The central problem: safety must not be assumed

Exposure is what an attacker can reach. The failure mode of every exposure tool
is the **quiet default**: when reachability can't be determined, calling it
"internal" makes the surface look smaller than it is.

- **S1 — No scanning; derive from known data (§0.1).** No `scan()`/`probe()`/
  `connect()` exists. The no-probing invariant is proven **behaviourally** (a
  network spy asserts zero outbound attempts across the suite) **and structurally**
  (no scan method exists to call), per **ECR-0007** — not a grep.
- **S2 — Unmatched reachability is `unknown` and flagged, never defaulted to
  internal.** Assuming safety is precisely how exposure gets missed. An asset
  whose reachability cannot be derived is recorded `reachability="unknown"` and
  flagged for attention — never silently classified internal/safe.
- **S3 — Every exposure is evidence-backed and explainable.** An `ExposureRecord`
  cites source evidence (EA-0004), asset lineage (EA-0012), and a rationale;
  confidence is EA-0006 Trust's; a composed score carries an EA-0020 `Derivation`.
  Exposure history is append-only.
- **S4 — Attack paths are EA-0005 `paths()`.** No second path engine; reachability
  chains are KG traversals with the KG's own `max_work` budget (ECR-0001).
- **S5 — Identity exposure cites EA-0011, never re-detects it.** This engine asks
  *"is it reachable?"*; EA-0011 owns *"are the entitlements right?"*. Identity
  exposure references EA-0011's `analyze_risk()`/`access_paths()`; it derives no
  entitlement verdict of its own.
- **S6 — One scorer, one trend engine.** Exposure score **composes** EA-0007
  (mission criticality) × EA-0006 (trust) with EA-0013 risk — no fourth scorer;
  exposure trends **delegate to EA-0021** — no second trend engine.
- **S7 — Exposures reach risk via the existing findings path.** A material
  exposure is raised as an EA-0013-consumable **`Finding`** (the shipped path),
  **not** a new `SignalRef` kind — a shipped contract is not churned to add a
  producer.
- **S8 — Advisory; the engine never acts.** It discovers, classifies, prioritizes,
  and proposes; remediation is an **EA-0008** gated run and recommendations are
  **EA-0020**. The engine originates no action and is never an executor.
- **S9 — A failed analysis/score looks failed, never faked (override of master
  §28.2/§28.3, ECR-0011).** A failed exposure analysis is recorded `unknown` +
  flagged; a failed re-score is recorded stale/unavailable — **never** a fabricated
  "fallback assessment" and **never** a silently retained prior score presented as
  current. Same discipline as EA-0022 (ECR-0009): a missing exposure must look
  missing.

## 2. Purpose

Leaders and defenders ask *"what can an attacker reach, and which of it matters
most?"* This engine answers from what AQELYN already knows — inventory, telemetry,
access, and the knowledge graph — **without ever touching a target**. It
classifies reachability honestly (unknown stays unknown), maps attack paths with
the KG, scores exposure by mission and trust, and hands the material items to risk
as findings. Its value is **an auditable attack surface you did not have to
attack to see**.

## 3. Design decisions

- **D1 — `ExposureRecord` cites, never asserts.** It carries `asset_ref` (EA-0012),
  `basis` (evidence refs), `reachability`, `confidence` (EA-0006), and — for a
  composed score — an EA-0020 `Derivation`. Unrepresentable without a basis.
- **D2 — `reachability` is a closed enum including `unknown`.** `external` /
  `internal` / `unknown`; `unknown` is the mandatory default when derivation is
  inconclusive (S2), never `internal`.
- **D3 — Attack paths delegate to EA-0005.** `reachable_paths()` calls KG
  `paths()`; the engine holds no traversal of its own (S4).
- **D4 — Scoring composes owners.** `score()` = f(EA-0007 mission criticality,
  EA-0006 trust, EA-0013 risk); the arithmetic is presentation over owner values
  and is replayable (EA-0020) (S6).
- **D5 — Material exposure → `Finding`.** `raise_exposure()` writes an EA-0013-
  consumable `Finding` via the shipped `FindingStore` (S7).
- **D6 — No scan surface.** The engine's public interface contains no method that
  opens a socket, resolves a host, or contacts an address (S1/§0.1). Active
  scanning is an EA-0008 `scan.active` ActionSpec consumed as stored results.
- **D7 — Registered as an `AQService`;** stores in-memory + Postgres; append-only.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Attack surface asset** | A known asset (EA-0012) evaluated for reachability (D1). |
| **Exposure** | A cited, evidence-backed reachability finding over a known asset (S3). |
| **Reachability** | `external` / `internal` / **`unknown`** — unknown is honest, not a gap to fill (S2/D2). |
| **Attack path** | An EA-0005 KG traversal to a reachable asset (S4). |
| **Exposure score** | A composed EA-0007 × EA-0006 × EA-0013 value with a replayable derivation (S6). |

## 5. Types

```
Reachability = "external" | "internal" | "unknown"          # unknown is a first-class value (S2)

AssetRef  = { kind: "asset"|"cloud"|"api"|"identity"|"domain"|"cert",
              ref_id: str, object_id: str | null = null,
              evidence_id: str | null }                       # lineage to EA-0012 (S3)
# ref_id is the known-surface identity. object_id, when present, is the EA-0002
# obj_ subject used by scoring/findings. Existing obj_-keyed callers may omit
# object_id and continue to use ref_id as both identities. A supplied object_id
# must be a valid obj_ id; when ref_id is also obj_, the two must match (ECR-0041).
ExposureBasis = { kind: "inventory"|"telemetry"|"access"|"graph", ref: str,
                  as_of: datetime, evidence_id: str | null }  # derived-from, never scanned (S1)

ExposureImpactKind = "data_sensitivity" | "credential_sensitivity"
ExposureImpactContext = { kind: ExposureImpactKind = "data_sensitivity",
                          status: "known"|"unknown",
                          factor: float | null, source_ref: str,
                          evidence_id: str, reason: str }
# known => factor in [0,1]; unknown => factor is null and cannot be scored.
# Existing omitted-kind callers remain data_sensitivity. Other owners MUST set
# their semantic kind explicitly; the complete context is derivation-bound.

ExposureRecord = { id, tenant_id, asset_ref: AssetRef, exposure_type: str,
                   reachability: Reachability,                # (S2/D2)
                   basis: list[ExposureBasis],                # MANDATORY (S3/D1)
                   impact_context: ExposureImpactContext | null, # optional, ECR-0041
                   score: float | null, confidence: float | null,  # EA-0006 (S3)
                   derivation: "Derivation" | null,           # EA-0020 where composed (D4)
                   rationale: str, flagged: bool,             # unknown ⇒ flagged (S2)
                   discovered_at: datetime, validated_at: datetime | null,
                   status: "open"|"revalidated"|"closed" }    # append-only history (S3)

AttackSurfaceAsset = { id, tenant_id, asset_ref: AssetRef, classification: str,
                       exposure_level: "high"|"medium"|"low"|"unknown",
                       discovered_at, validated_at: datetime | null,
                       basis: list[ExposureBasis] }
ReachablePath = { target_ref: str, path: list[str], via: "graph",   # EA-0005 paths() (S4)
                  max_work: int }
ExposureConfig = { max_paths: int, max_work: int, default_level: str,
                   score_weights: dict }                       # bounded (NFR-4)
```

Reuses EA-0020 `Derivation`, EA-0006 confidence, EA-0004 evidence refs, EA-0012
asset refs, EA-0013 `Finding`.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class ExposureStore(Protocol):
    async def put(self, e: ExposureRecord) -> ExposureRecord: ...   # rejects: no basis
    async def get(self, exposure_id: str, *, tenant_id: str | None) -> ExposureRecord | None: ...
    async def query(self, *, tenant_id: str | None, reachability: Reachability | None = None,
                    flagged: bool | None = None, limit: int = 100) -> list[ExposureRecord]: ...

class ExposureEngine(Protocol):
    async def derive_surface(self, *, tenant_id: str | None) -> list[AttackSurfaceAsset]: ...  # from KNOWN data (S1)
    async def analyze_exposure(self, *, asset_ref: AssetRef,
                               tenant_id: str | None) -> ExposureRecord: ...      # unknown⇒flagged (S2)
    async def reachable_paths(self, *, target_ref: str,
                              tenant_id: str | None) -> list[ReachablePath]: ...  # EA-0005 paths() (S4)
    async def score_exposure(
        self, e: ExposureRecord, *,
        impact_context: ExposureImpactContext | None = None
    ) -> ExposureRecord: ...  # EA-0007×EA-0006×EA-0013; optional ECR-0041 factor
    async def identity_exposure(self, *, asset_ref: AssetRef,
                                tenant_id: str | None) -> ExposureRecord: ...     # CITES EA-0011 (S5)
    async def trend(self, *, category: str, window_days: int,
                    tenant_id: str | None) -> "TrendRecord": ...                  # EA-0021 (S6)
    async def raise_exposure(self, e: ExposureRecord, *, by: "ActorRef") -> "Finding": ...  # findings path (S7)
    # NOTE: there is deliberately NO scan()/probe()/connect() (S1/§0.1/D6).
```

`ExposureManagementService` wraps engine + store as an `AQService`
(name `"exposure_engine"`, depends on assetconfig/graph/iag/mission/trust/risk/
forecast/evidence; health reflects owner-read availability + config validity).

## 7. Computation (the reference model)

**Derive surface.** Read known assets (EA-0012), telemetry (EA-0019), access
(EA-0011), and KG (EA-0005); classify each asset's reachability **from that data
alone**. No socket is opened (S1). Assets whose reachability is inconclusive →
`reachability="unknown"`, `flagged=True` (S2).

**Analyze / score.** Build the `ExposureRecord` with cited `basis`; score by
composing EA-0007 mission criticality × EA-0006 trust × EA-0013 risk; attach the
EA-0020 `Derivation` (replayable) (S6/D4). A composed score without a replayable
derivation is rejected (EA-0020 precedent).

When an optional `ExposureImpactContext` is supplied (ECR-0041), a known
factor scales the reachability impact in the EA-0023 risk seed and the exact
context is pinned in the derivation. The same exposure with a higher factor
cannot receive a lower score. An unknown context has no factor and is refused
for scoring rather than treated as zero. Existing callers that omit the context
retain their existing score.

`data_sensitivity` remains the default context kind for backward compatibility.
An EA-0032 producer supplies `credential_sensitivity` explicitly (ECR-0044).
The kind is part of the replay-bound context; an owner cannot relabel credential
criticality as data classification or omit its semantic kind.

For an `AssetRef` whose surface identity is not an EA-0002 id, scoring resolves
the subject as `asset_ref.object_id`; otherwise it retains the existing
`asset_ref.ref_id` behavior. The resolved subject MUST be a tenant-matching
`obj_` id and is used consistently for Mission, Risk, correlation, and finding
affected-object references. A non-`obj_` surface ref without `object_id` is
refused with `ExposureConfigInvalid`.

**Paths.** `reachable_paths` calls EA-0005 `paths()` with the config `max_work`
budget (S4/ECR-0001).

**Identity exposure.** Cite EA-0011 `analyze_risk()`/`access_paths()` as `basis`;
derive no entitlement verdict here (S5).

**Raise.** A material exposure is written as an EA-0013-consumable `Finding` via
`FindingStore.raise_finding` (S7). The engine proposes remediation as an EA-0008
gated run / EA-0020 recommendation; it never remediates (S8).

## 8. Requirements

### Functional (testable)

- **FR-1** The engine SHALL expose **no** `scan`/`probe`/`connect`/socket-opening method; the attack surface SHALL be derived from EA-0012/EA-0019/EA-0011/EA-0005 data only (S1/§0.1).
- **FR-2** An asset whose reachability cannot be derived SHALL be recorded `reachability="unknown"` and `flagged=True`; it SHALL NOT be defaulted to `internal` (S2).
- **FR-3** An `ExposureRecord` SHALL carry a non-empty `basis`; one without SHALL be rejected at construction/`put` (S3/D1).
- **FR-4** `reachable_paths` SHALL delegate to EA-0005 `paths()` (bounded by `max_work`); the engine SHALL implement no traversal of its own (S4).
- **FR-5** Identity exposure SHALL cite EA-0011 (`analyze_risk`/`access_paths`) as basis and SHALL derive no entitlement verdict (S5).
- **FR-6** A composed exposure `score` SHALL carry an EA-0020 `Derivation` and SHALL be rejected if `replay(derivation) != result` (S6).
- **FR-7** Exposure trend SHALL delegate to EA-0021; the engine SHALL implement no second trend model (S6).
- **FR-8** A material exposure SHALL be raised as an EA-0013-consumable `Finding` via the shipped `FindingStore`; no new `SignalRef` kind SHALL be added (S7).
- **FR-9** `confidence` SHALL come from EA-0006 Trust; no second confidence model (S3).
- **FR-10** The engine SHALL raise no action and SHALL NOT remediate; remediation SHALL be an EA-0008 gated run (S8).
- **FR-11** A failed analysis SHALL yield `unknown`+flagged and a failed re-score SHALL be recorded stale/unavailable — never a fabricated fallback or silently retained prior score (S9, ECR-0011).
- **FR-12** Active scanning, if configured, SHALL be an EA-0008 `scan.active` `ActionSpec` consumed as stored results; the engine SHALL NOT originate it (S1/§0.1).
- **FR-13** `ExposureStore` in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-14** `ExposureManagementService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).
- **FR-15** An optional `ExposureImpactContext` SHALL be evidence-backed and
  included in the replayable derivation. Known factors SHALL be monotonic;
  unknown context SHALL NOT be scored as zero. Omitting the context SHALL
  preserve the pre-ECR-0041 result.
- **FR-16** `AssetRef.ref_id` SHALL identify the known-surface row. When that
  identity is not an EA-0002 `obj_` id, `AssetRef.object_id` SHALL carry the
  scoring/finding subject; scoring SHALL refuse a missing or invalid subject.
  When both values are `obj_` ids they SHALL match.
- **FR-17** Postgres SHALL persist `ExposureRecord.impact_context` in a nullable
  JSONB column and restore it on every read path; in-memory and Postgres
  round-trips SHALL preserve identical derivation-bound context.
- **FR-18** `ExposureImpactKind` SHALL accept `data_sensitivity` and
  `credential_sensitivity`. `data_sensitivity` SHALL remain the omitted-kind
  default; EA-0032 callers SHALL pass `credential_sensitivity` explicitly, and
  the kind SHALL be pinned in the replayable derivation (ECR-0044).

### Non-functional

- **NFR-1 (no probing — structural + behavioural)** no scan/probe/connect method exists, and a **network spy** asserts **zero outbound attempts** across the suite (per **ECR-0007**), not a grep.
- **NFR-2 (honest unknowns)** unresolved reachability is `unknown`+flagged, never defaulted — proven by test.
- **NFR-3 (reuse, not rebuild)** paths delegate to EA-0005, identity cites EA-0011, trends delegate to EA-0021, scoring composes EA-0007×EA-0006 — proven behaviourally (spies/citation asserts), no duplicate engine.
- **NFR-4 (bounded & typed)** paths/queries bounded by `max_work`; `mypy --strict` + `ruff` clean.
- **NFR-5 (additive impact context)** ECR-0041 changes no existing caller result;
  DSPM's sensitivity is an explicit owner input, not a second exposure scorer.
- **NFR-6 (semantic compatibility)** ECR-0044 changes no omitted-kind caller;
  data and credential sensitivity remain distinguishable in stored/replayed
  contexts without introducing a second scorer.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | No scan/probe/connect method exists (structural) | `test_exp_no_scan_surface` |
| AC-2 | Network spy: zero outbound attempts (behavioural) | `test_exp_no_network` |
| AC-3 | Unresolved reachability → unknown + flagged, not internal | `test_exp_unknown_not_internal` |
| AC-4 | ExposureRecord without basis rejected | `test_exp_basis_required` |
| AC-5 | reachable_paths delegates to EA-0005 paths() | `test_exp_paths_delegate_kg` |
| AC-6 | Identity exposure cites EA-0011, no re-detection | `test_exp_identity_cites_iag` |
| AC-7 | Composed score carries replayable derivation | `test_exp_score_replayable` |
| AC-8 | Tampered derivation rejected | `test_exp_score_replay_mismatch` |
| AC-9 | Trend delegates to EA-0021 | `test_exp_trend_delegates_forecast` |
| AC-10 | Material exposure raised as a Finding (no new SignalRef) | `test_exp_raise_finding_path` |
| AC-11 | Confidence from Trust (no 2nd model) | `test_exp_confidence_from_trust` |
| AC-12 | Engine never acts (no remediation path) | `test_exp_advisory_only` |
| AC-13 | Failed analysis → unknown; failed re-score → stale/unavailable, not faked | `test_exp_failure_not_faked` |
| AC-14 | Active scan is an EA-0008 scan.active ActionSpec consumed as data | `test_exp_active_scan_is_actionspec` |
| AC-15 | Exposure store passes one suite each backend | `test_exp_store_contract[...]` |
| AC-16 | Registers as AQService with health | `test_exp_service_health` |
| AC-17 | Known impact context is derivation-bound and monotonic; omitted context preserves existing score | `test_exp_impact_context` |
| AC-18 | Unknown/tampered impact context is refused, never scored as zero | `test_exp_impact_context_unknown_or_tampered` |
| AC-19 | Inventory-keyed AssetRef uses its obj_ object_id for scoring, correlation, and findings; missing/invalid/contradictory object_id is refused | `test_exp_asset_ref_scoring_subject` |
| AC-20 | impact_context round-trips identically through in-memory and Postgres stores and still verifies against its derivation | `test_exp_impact_context_store_contract[inmemory]` / `test_exp_impact_context_store_contract[postgres]` |
| AC-21 | Omitted impact kind remains data_sensitivity and preserves the existing DSPM score/derivation | `test_exp_impact_context_kind_default_compat` |
| AC-22 | Explicit credential_sensitivity is accepted, round-tripped, and pinned in replay | `test_exp_credential_impact_context_replay` |

## 10. Error taxonomy (contributions)

`ExposureConfigInvalid`, `ExposureBasisMissing`, `ExposureNotFound`,
`ExposureNotReplayable`, `ScanNotPermitted` (added to `conventions.errors` +
CONVENTIONS §9). Reuses EA-0020 `DerivationNotReplayable`, `StoreUnavailable`,
`TenantScopeRequired`.

## 11. Registered event types (owned by EA-0023)

`aqelyn.exposure.asset_discovered`, `aqelyn.exposure.detected`,
`aqelyn.exposure.attack_surface_updated`, `aqelyn.exposure.score_updated`,
`aqelyn.exposure.closed` — via `register_exposure_events()` (EA-0003 §7).
(Archive uses `asset.discovered` etc.; kept in the platform namespace.)

## 12. Failure handling

- Invalid config → `ExposureConfigInvalid` at construction.
- Reachability inconclusive → `unknown` + flagged (S2) — **never** `internal`.
- Analysis source unavailable → the exposure is recorded `unknown`/unavailable and
  flagged, **not** a fabricated "fallback assessment" (S9, overrides master §28.2).
- Re-score fails → recorded stale/unavailable, **not** a silently retained prior
  score presented as current (S9, overrides master §28.3).
- Composed score fails to replay → withheld, not served with a caveat (EA-0020).
- Unknown ECR-0041 impact context → scoring refused; the caller retains a
  flagged, unscored gap rather than receiving a zero-impact score. Unknown,
  tampered, or invalid scoring-subject context raises `ExposureConfigInvalid`.
- A request to actively scan → `ScanNotPermitted` unless delivered as an EA-0008
  `scan.active` gated run (S1/§0.1/FR-12).

## 13. Dependencies & consumers

- **Depends on:** EA-0012 (inventory), EA-0019 (telemetry), EA-0005 (`paths()`),
  EA-0011 (identity — cited), EA-0007 × EA-0006 (scoring), EA-0013 (findings),
  EA-0021 (trends), EA-0020 (`Derivation`), EA-0004 (evidence), EA-0008 (the only
  actor), EA-0009 (policy), EA-0001 `AQService`.
- **Consumed by:** EA-0022 (executive exposure summaries — as cited figures),
  EA-0013 (exposures arrive as findings), EA-0024 (Vulnerability Intelligence —
  exposure as a prioritization input; the seam is already here), EA-0031
  (evidence-backed data-sensitivity impact context), EA-0032 (evidence-backed
  credential-sensitivity impact context).
- **Explicitly NOT:** a scanner, a second path/trend/score engine, or an actor.

## 14. Resolved / deferred decisions

- **No scanning; derive from known data** (S1/§0.1) — the boundary that lets an
  exposure engine exist without touching a target. Active scanning is an EA-0008
  `scan.active` ActionSpec. See **ECR-0011**.
- **Unknown reachability stays unknown + flagged** (S2) — assuming safety is how
  exposure gets missed.
- **Four duplications mapped** — paths=EA-0005, identity=EA-0011 (cited),
  trends=EA-0021, scoring=EA-0007×EA-0006; exposures→EA-0013 via findings (S4–S7).
- **Advisory; EA-0008 is the only actor** (S8).
- **Impact context kinds are semantic, not interchangeable.**
  `data_sensitivity` remains the backward-compatible default; EA-0032 must pass
  `credential_sensitivity` explicitly. See **ECR-0044**.
