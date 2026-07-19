# C-011 Threat Intelligence Fusion — Implementation Task Bundle

**Milestone:** C-011 (Threat Intelligence Fusion, EA-0014)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** EA-0013 merged & green; EA-0014 spec **Accepted**; CONVENTIONS + EA-0002/0004/0005/0006/0013 + Finding model read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; **no network/credential surface; no direct action**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

This engine **fuses handed-in feed data** (no fetching, §0) and **composes** the
core (ObjectStore dedupe, KG, Trust, Evidence, Finding, Workflow). It supplies
EA-0013's reserved threat-intel signal. If a needed behavior isn't in the spec,
raise an ECR.

## Target source layout

```
src/aqelyn/threat/
├── __init__.py       # exports the engine, service, types, register_threat_events
├── models.py         # FeedRecord, ThreatIndicator, ThreatMatch, MatchReport, FusionConfig (T1)
├── normalize.py      # feed record -> ThreatIndicator; quarantine malformed (T1)
├── confidence.py     # deterministic threat confidence (reliability+corroboration+recency) (T2)
├── registry.py       # ThreatSourceRegistry protocol + in-memory + Postgres (T2)
├── correlate.py      # indicators vs estate via KG (T3)
├── engine.py         # ingest + correlate + matches_to_findings (+ EA-0013 signal) (T3/T4)
└── service.py        # ThreatFusionService(AQService) + register_threat_events (T5)
tests/threat/         # acceptance suite (in-memory + Postgres)
```

---

## T1 — Types, normalization & quarantine (no fetch)

**Spec:** §4, §6 (ingest/normalize), §0, FR-1/2/3/11; §9.
**Deliverables:** the models; normalization of handed-in `FeedRecord`s to
`ThreatIndicator`s with **no network/credential code**; malformed → quarantine;
dedupe by natural key `(indicator_type, value)` via `ObjectStore.upsert`;
`FusionConfig` validation (`ThreatConfigInvalid`); new error codes in
`conventions.errors` + CONVENTIONS §9.
**Depends on:** EA-0002 objects, conventions.
**Acceptance:** `test_tif_ingest_no_fetch`, `test_tif_quarantine_malformed`,
`test_tif_dedupe_indicators`, `test_tif_config_invalid`.

## T2 — Confidence scoring & source registry

**Spec:** §6 (confidence), FR-4/12, D3.
**Deliverables:** deterministic `score_confidence` (reuse the Trust model:
reliability + corroboration + recency); `ThreatSourceRegistry` (in-memory +
Postgres + DDL, provenance).
**Depends on:** T1.
**Acceptance:** `test_tif_confidence`,
`test_tif_source_contract[inmemory]`, `test_tif_source_contract[postgres]`.

## T3 — Correlation against the estate

**Spec:** §6 (correlate), FR-5/6/10, D4.
**Deliverables:** `correlate` (indicators vs asset objects via KG/attribute
match, tenant-scoped, bounded, `truncated` propagated, expired excluded),
`explain`.
**Depends on:** T2.
**Acceptance:** `test_tif_correlate_matches`, `test_tif_tenant_and_truncation`,
`test_tif_expiry`.

## T4 — Findings, evidence & risk signal (delegate-only)

**Spec:** §0, §6, FR-7/8/9, D5/D6, NFR-1.
**Deliverables:** evidence binding for indicators/matches; `matches_to_findings`
(mission-weighted, evidence-cited findings + threat-intel `SignalRef` to EA-0013;
any action **proposed** via Workflow, never executed).
**Depends on:** T3.
**Acceptance:** `test_tif_matches_to_findings`, `test_tif_risk_signal`,
`test_tif_actions_delegated`, `test_tif_evidence_bound`, `test_tif_no_side_effects`.

## T5 — Service + events

**Spec:** FR-13, §10.
**Deliverables:** `ThreatFusionService` (`AQService`, name
`"threat_fusion_engine"`) + `register_threat_events`; wired into the kernel
factory.
**Depends on:** T4.
**Acceptance:** `test_tif_service_health`.

## Post-delivery follow-up — ECR-0031

Add `FusionConfig.correlation_max_work` (default `5_000`, hard cap `100_000`)
to bound expired-indicator enumeration independently of result count. Exhausting
the work budget SHALL propagate `MatchReport.truncated=true`.

**Acceptance:** `test_tif_config_invalid`,
`test_tif_indicator_work_budget[inmemory]`,
`test_tif_indicator_work_budget[postgres]`.

---

## Review protocol (Claude Code) — the boundary gets the hard look

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No network/credential surface** — grep for sockets/HTTP clients/credential
   reads; `ingest` only consumes handed-in `FeedRecord`s (§0).
2. **No direct action** — matches raise findings + supply the EA-0013 signal;
   any response is a *proposed* Workflow run. Trace `matches_to_findings`.
3. Malformed feed data is quarantined, never trusted into the catalog.
4. Dedupe by natural key; confidence deterministic; correlation tenant-scoped +
   bounded; expired excluded.
5. Every indicator/match is evidence-bound.
6. `ruff` + `mypy --strict` clean; interfaces match the spec exactly.

Merge only on green review; then **report back to the owner** before the next
module.
