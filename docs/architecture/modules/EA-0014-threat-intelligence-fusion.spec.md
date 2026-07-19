# EA-0014 — Threat Intelligence Fusion Engine — Implementation Specification

**Realizes:** EA-0014 / IS-014 (supersedes the placeholder `archive/EA-0014/EA-0014_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), EA-0002 (indicators/actors/campaigns as objects), EA-0005 (correlate indicators↔assets), EA-0004 (threat evidence), the Finding model; feeds EA-0013 (threat-intel risk signal), EA-0007 (mission weighting)
**Consumed by:** EA-0013 Risk Intelligence (the reserved threat-intel signal seam), the threat UI (indicators, actors, campaigns, matches — a WCAG 2.2 AA surface), the Finding pipeline (matched threats → findings), EA-0010 reporting
**Status:** Accepted
**Change control:** ECR-0030 (object-page bounds are surfaced; expired indicators cannot starve live ones); ECR-0031 (indicator-enumeration work budget)
**Build milestone:** C-011 (see `C-011_Task_Bundle.md`)
**Definition of Ready:** see §11

---

## 0. Scope & safety boundary (read first)

- **Fusion, not fetching.** This engine **normalizes, deduplicates, catalogs, and
  correlates threat-intelligence data that has already been received** into the
  platform (handed in as feed records, each carrying its source + evidence
  reference). It does **not** open network connections, hold feed credentials, or
  poll external services — **live external ingestion is a connector concern for a
  later EA** (the archive's "Feed Ingestion" is realized here as *accepting
  handed-in feed data*; the network/credential surface is explicitly deferred).
  This keeps EA-0014 on the same pure-analysis footing as its siblings and avoids
  opening the outbound-network surface before it's designed.
- **Detect-and-propose.** Fusion produces indicators/matches/findings and a
  risk signal for EA-0013. Any *action* on a match (block, isolate) is a
  **proposed, gated Workflow run (EA-0008)** — never executed here.
- **Untrusted input.** Handed-in feed data is treated as untrusted until
  normalized and validated; malformed records are quarantined, never trusted
  into the catalog.
- Otherwise pure/read-analysis: deterministic, explainable, tenant-scoped,
  evidence-recorded. No new authorization surface.

## 1. Purpose

The Threat Intelligence Fusion Engine turns raw, overlapping threat feeds into a
**single, deduplicated, confidence-scored view of threats** — indicators (IOCs),
threat actors, campaigns, and TTPs — and, crucially, **correlates them against
the organization's own estate**: *does any of this threat activity actually touch
our assets, and how much should we trust it?* Matches become mission-weighted
findings and the threat-intel signal that EA-0013 already reserves.

## 2. Design decisions

- **D1 — Threat objects live in EA-0002.** Indicators, actors, and campaigns are
  `AQObject`s (`object_type ∈ {threat_indicator, threat_actor, threat_campaign}`);
  relationships link indicator→actor→campaign and TTP tags. No separate threat
  store beyond the source/feed registry.
- **D2 — Normalize then deduplicate by natural key.** A feed record is normalized
  to a canonical `ThreatIndicator` and upserted via the object store's
  natural-key dedupe (EA-0002 §9) — the same IOC from three feeds becomes one
  object with three sources. Provenance preserved.
- **D3 — Confidence is scored deterministically** from source reliability +
  corroboration (multiple independent feeds) + recency — reusing the Trust
  Engine's model where possible; explainable.
- **D4 — Correlation uses the Knowledge Graph.** "Does this indicator touch us?"
  is a graph/attribute match of indicators against asset objects; each match
  carries the matched asset + the reason (explainable). Bounded (inherits KG
  caps).
- **D5 — Evidence-bound.** Every indicator and match references its source
  evidence (EA-0004); a match finding cites it — "how AQELYN knows" for threats.
- **D6 — Feeds EA-0013.** A correlated match emits/【supplies】a threat-intel
  `SignalRef` for the Risk engine (the seam EA-0013 reserved). Fusion doesn't
  score org risk itself — it supplies the signal.
- **D7 — Detect-and-propose** (§0); registered as an `AQService` (D8);
  tenant-scoped and bounded.

## 3. Ubiquitous language

| Term | Meaning |
|---|---|
| **Feed record** | A handed-in, raw threat item from a source (already received; not fetched here). |
| **Indicator (IOC)** | A normalized observable (hash, IP, domain, URL) as `object_type "threat_indicator"`. |
| **Threat actor / Campaign** | Attributed adversary / grouped activity (objects), linked to indicators. |
| **TTP** | A tactic/technique tag on indicators/actors (e.g. an ATT&CK-style id). |
| **Fusion** | Normalize + dedupe + confidence-score + catalog across sources. |
| **Match / correlation** | An indicator found to touch an estate asset, with the reason. |
| **Threat confidence** | `[0,1]` trust in an indicator, from source reliability + corroboration + recency. |

## 4. Types

```
FeedRecord   = { source_id: str, raw: dict, received_at: datetime,
                 evidence_id: str | null }                 # handed in; untrusted until normalized
ThreatIndicator = { id, tenant_id, indicator_type: str, value: str,
                    ttps: list[str], actor_ids: list[str], campaign_ids: list[str],
                    confidence: float, first_seen_at, last_seen_at,
                    sources: list[SourceRef], expires_at: datetime | null }
ThreatMatch  = { indicator_id: str, asset_id: str, match_type: str,
                 confidence: float, evidence_id: str | null, reason: str, via: "Path | null" }
MatchReport  = { matches: list[ThreatMatch], evaluated: int, truncated: bool }

FusionConfig = { source_reliability: dict[str, float], recency_half_life_days: float,
                 correlation: dict, correlation_max_work: int = 5_000,
                 min_match_confidence: float,
                 quarantine_on_malformed: bool }
```

Reuses EA-0002 `SourceRef`/objects, EA-0005 `Path`, the Trust model (confidence),
EA-0013 `SignalRef`, and the Finding model.

## 5. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class ThreatSourceRegistry(Protocol):
    async def get(self, source_id: str) -> dict: ...          # reliability + metadata; unknown -> default
    async def set(self, source_id: str, *, reliability: float, meta: dict,
                  by: ActorRef) -> dict: ...

class ThreatFusionEngine(Protocol):
    async def ingest(self, records: Sequence[FeedRecord], *,
                     tenant_id: str | None) -> list[ThreatIndicator]: ...   # normalize+dedupe+score (D2/D3); no fetch (§0)
    async def score_confidence(self, indicator: ThreatIndicator) -> float: ...
    async def correlate(self, *, tenant_id: str | None,
                        scope: "ObjectQuery | None" = None) -> MatchReport: ...  # indicators vs estate (D4)
    async def matches_to_findings(self, report: MatchReport, *, by: ActorRef,
                                  prioritize: bool = True) -> list[str]: ...   # + threat-intel signal to EA-0013 (D6)
    def explain(self, match: ThreatMatch) -> dict: ...
```

`ThreatFusionService` wraps the engine + registry as an `AQService`
(name `"threat_fusion_engine"`, depends on object store, KG, evidence/finding
stores, trust engine; health reflects their availability + config validity).

## 6. Computation (the reference model)

**Ingest.** For each `FeedRecord`: validate/normalize `raw` to a
`ThreatIndicator` (canonical `indicator_type` + `value`); malformed → quarantine
(flagged), not cataloged (§0). Upsert by natural key `(indicator_type, value)`
via the object store (dedupe across feeds, union sources, D2). Link actors/
campaigns/TTPs as relationships.

**Confidence.** `confidence = combine(source_reliability across contributing
feeds, corroboration count, recency decay)` — reuse the Trust noisy-OR/decay
model (D3). Deterministic.

**Correlate.** For in-scope indicators, match against estate assets (e.g. an IP/
domain/hash appearing in asset `attributes`, or graph reachability). Each
`ThreatMatch` carries `confidence ≥ min_match_confidence`, the matched asset, an
evidence ref, and a `reason`. The configured correlation limit bounds indicator
and asset candidates; indicator enumeration additionally examines at most
`correlation_max_work` objects (default `5_000`, hard cap `100_000`). If another
object page remains when either bound is reached, `truncated=true`. Expired
indicator pages are advanced until a live candidate is found, the limit or work
budget is filled, or the filtered indicator set is exhausted. `truncated` also
inherits from KG (ECR-0030/ECR-0031).

**Findings + signal.** Each match ≥ threshold → a finding (severity from
indicator confidence × asset criticality), evidence = the indicator's source +
match evidence, affected object = the asset; optional Mission prioritization; and
a threat-intel `SignalRef` supplied to EA-0013 (D6). Actions delegate to Workflow
(§0).

## 7. Requirements

### Functional (testable)

- **FR-1** `ingest` SHALL normalize handed-in feed records to `ThreatIndicator`s and SHALL NOT perform any network fetch or hold feed credentials (§0).
- **FR-2** Malformed/invalid feed records SHALL be quarantined (flagged), never cataloged as trusted (§0).
- **FR-3** Indicators SHALL be deduplicated by natural key `(indicator_type, value)` across feeds, unioning sources (D2).
- **FR-4** `score_confidence` SHALL be deterministic from source reliability + corroboration + recency; identical inputs → identical score (D3).
- **FR-5** `correlate` SHALL match indicators against estate assets, each match carrying the asset, an evidence ref, `confidence`, and a `reason` (D4/D5).
- **FR-6** Correlation SHALL be tenant-scoped and bounded (configured object cap + `correlation_max_work` + KG caps); `truncated` SHALL be true when either source has an unprocessed object page or KG truncates, and expired indicators SHALL NOT starve later live indicators within the work budget (ECR-0030/ECR-0031).
- **FR-7** `matches_to_findings` SHALL raise a finding per qualifying match (mission-weighted severity, evidence-cited) and SHALL supply a threat-intel `SignalRef` to EA-0013 (D6); actions SHALL be proposed via Workflow, never executed (§0).
- **FR-8** Every indicator and match SHALL reference its source evidence (EA-0004) (D5).
- **FR-9** The engine SHALL NOT mutate non-threat objects or execute any action; it writes threat objects, evidence, and (via pipeline) findings only.
- **FR-10** Expired indicators (`expires_at` past) SHALL be excluded from correlation by default, flagged.
- **FR-11** Invalid config (`min_match_confidence` outside `[0,1]`, `recency_half_life_days ≤ 0`, `correlation_max_work` outside `1..100_000`, unknown source reliability out of range) SHALL raise `ThreatConfigInvalid`.
- **FR-12** `ThreatSourceRegistry` in-memory and Postgres implementations SHALL pass one contract suite. (Threat objects persist via the existing object store.)
- **FR-13** `ThreatFusionService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (no network/credentials)** no code path in this engine opens a socket, makes an HTTP request, or reads a feed credential; enforced by test/grep.
- **NFR-2 (determinism)** identical feed records + config → identical indicators/scores/matches (excluding ids/timestamps).
- **NFR-3 (bounded)** ingest and correlation process in bounded batches; indicator enumeration examines at most `correlation_max_work` objects and inherits KG caps.
- **NFR-4 (portability & typing)** in-memory + Postgres registry pass one suite; `mypy --strict` + `ruff` clean.

## 8. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Ingest normalizes; no network/credentials | `test_tif_ingest_no_fetch` |
| AC-2 | Malformed records quarantined | `test_tif_quarantine_malformed` |
| AC-3 | Dedupe by natural key across feeds | `test_tif_dedupe_indicators` |
| AC-4 | Confidence deterministic (reliability+corroboration+recency) | `test_tif_confidence` |
| AC-5 | Correlation matches indicators to assets w/ reason | `test_tif_correlate_matches` |
| AC-6 | Correlation tenant-scoped + truncation propagates | `test_tif_tenant_and_truncation` |
| AC-7 | Matches → mission-weighted findings + evidence | `test_tif_matches_to_findings` |
| AC-8 | Threat-intel SignalRef supplied to EA-0013 | `test_tif_risk_signal` |
| AC-9 | Actions proposed via Workflow, never executed | `test_tif_actions_delegated` |
| AC-10 | Indicators/matches evidence-bound | `test_tif_evidence_bound` |
| AC-11 | Expired indicators excluded | `test_tif_expiry` |
| AC-12 | Engine mutates no non-threat object | `test_tif_no_side_effects` |
| AC-13 | Invalid config rejected | `test_tif_config_invalid` |
| AC-14 | Source registry in-memory & Postgres pass one suite | `test_tif_source_contract[inmemory]` / `[postgres]` |
| AC-15 | Registers as AQService with health | `test_tif_service_health` |
| AC-16 | Object-page cap is explicit and expired pages do not starve live indicators | `test_tif_object_page_limit_reports_truncated[inmemory|postgres]`, `test_tif_expired_page_does_not_starve_active_indicator[inmemory|postgres]` |
| AC-17 | Expired-indicator enumeration stops at its work budget and reports truncation | `test_tif_indicator_work_budget[inmemory|postgres]` |

## 9. Error taxonomy (contributions)

`ThreatConfigInvalid`, `ThreatSourceNotFound`, `MalformedFeedRecord` (added to
`conventions.errors` + CONVENTIONS §9). Reuses `StoreUnavailable`,
`TenantScopeRequired`.

## 10. Registered event types (owned by EA-0014)

`aqelyn.threat.indicator_ingested`, `aqelyn.threat.match_detected`,
`aqelyn.threat.updated` — via `register_threat_events()` (EA-0003 §7). (Archive
uses `risk.threat.updated`; mapped into the platform namespace as
`aqelyn.threat.updated`.)

## 11. Failure handling

- Invalid config → `ThreatConfigInvalid` at construction; service `unavailable`.
- Dependency unavailable → `StoreUnavailable`; service `degraded`; partial
  correlation marked incomplete, never a clean "no threats".
- A single malformed record is quarantined + flagged; the batch continues.
- A failed finding/signal emission leaves the indicator/match recorded and
  surfaces the failure; no direct action is attempted as a fallback.

## 12. Dependencies & consumers

- **Depends on:** EA-0002 objects (`upsert` natural-key dedupe); EA-0005
  `KnowledgeGraph`; EA-0006 Trust (confidence model); EA-0004
  `EvidenceStore.add`; EA-0007 (optional prioritization); the Finding model;
  **EA-0008 Workflow (any action proposed + gated)**; EA-0001 `AQService`.
- **Consumed by:** **EA-0013 Risk Intelligence** (threat-intel `SignalRef` — the
  reserved seam); threat UI (indicators/actors/campaigns/matches — **WCAG 2.2
  AA** applies); the Finding pipeline; EA-0010 reporting.

## 13. Resolved / deferred decisions

- **Fusion accepts handed-in feed data; live external fetching is a later
  connector EA** (§0). The `FeedRecord` seam is the handoff; when connectors land,
  they deliver `FeedRecord`s to `ingest` — this engine is unchanged.
- **Threat objects in EA-0002 + confidence via Trust** — reuse, no bespoke store
  or scorer.
- **Fusion supplies the risk signal; EA-0013 scores org risk** — clean division,
  matches the reserved seam.
- **STIX/TAXII/specific feed formats** are normalization adapters delivered with
  their connectors; the engine's contract is the normalized `ThreatIndicator`.
