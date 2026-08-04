# ECR-0098 - The residual sixteen, part 1: ordering clauses

**Status:** Proposed
**From:** claude.ai, from Claude Code's post-ECR-0097 review; classification and
implementation by Codex
**Date:** 2026-08-04
**Number:** 0098, re-verified after ECR-0097 at `81e7c3e`

## 1. Census and measured boundary

The population is defined by this command:

```text
rg -n "ORDER BY.*LIMIT" src | exclude literal LIMIT 1 point lookups
```

It returns thirty paged reads. ECR-0090 through ECR-0097 cover fourteen; this
ECR covers the sixteen residual methods below. The prior review measured one
ordering mutation per residual read. Fifteen were silent; only `vuln.query`
was caught, by C-038/R3's `VulnerabilityStore` control.

That measurement says nothing yet about leading keys, resume predicates, or
termination. Those classes remain unknown for this population and are the
measurement precondition for ECR-0099. A census command defines the boundary
of a claim; it does not prove anything outside that boundary.

## 2. Classification before witnesses

Inspection of the public APIs corrects the source brief: **all sixteen are
cursorless bounded ordered lists**. None accepts or returns a cursor, and none
uses the CTE-backed outer-order shape. The applicable witness is therefore an
ordered-prefix witness for every method, not a keyset walk.

| Package | Public read | Ordered by | Witness treatment |
|---|---|---|---|
| assetconfig | `DriftSnapshotStore.history` | `run_at, id` | behavioural prefixes |
| decision | `RecommendationStore.query` | `created_at, id` | behavioural prefixes |
| executive | `KPIDefinitionStore.versions` | `version` | allocation-aware behavioural prefixes |
| executive | `ReportStore.query` | `period, id` | behavioural prefixes |
| exposure | `ExposureStore.query` | `discovered_at, id` | behavioural prefixes |
| forecast | `ForecastStore.query` | `issued_at, id` | behavioural prefixes |
| forecast | `PredictionModelStore.query` | `method, version, id` | behavioural prefixes |
| governance | `SnapshotStore.history` | `run_at, id` | behavioural prefixes |
| idthreat | `IdentityDetectionStore.query` | `detected_at, id` | behavioural prefixes |
| lake | `TelemetryRecordStore.query` | `occurred_at, id` | behavioural prefixes |
| lake | `TelemetryRecordStore.list_quarantine` | `received_at, insertion sequence` | behavioural prefixes after backend alignment |
| response | `CampaignStore.query` | `updated_at DESC, id` | behavioural prefixes |
| risk | `RiskStore.query` | `score DESC, id` | behavioural prefixes |
| risk | `RiskSnapshotStore.history` | `run_at, id` | behavioural prefixes |
| soc | `SOCStore.query_incidents` | `priority DESC, updated_at DESC, id` | behavioural prefixes |
| vuln | `VulnerabilityStore.query` | `discovered_at, id` | behavioural prefixes plus C-038 defence in depth |

### 2.1 Allocation-aware executive fixture

`KPIDefinitionStore.propose()` allocates monotonically increasing versions, so
ordinary public writes correlate insertion order with the order being tested.
That is not a witness. Its fixture may seed the backing store in reverse
version order, but the read under test remains the public `versions()` API and
the fixture must prove all N definitions survived before checking prefixes.

### 2.2 Lake classification finding

Classification found a live backend contract divergence that the source brief
incorrectly declared absent. Postgres orders quarantine rows by
`(received_at, seq)`, where `seq` is persisted insertion order. Memory orders
equal timestamps by `(source_id, reason)` even though neither field is the
Postgres tie-break and `Quarantine` exposes no sequence field.

The canonical contract is `(received_at, insertion sequence)`: it preserves
Postgres's durable ordering and the natural append order already held by the
memory store. Memory must use a stable sort on `received_at`. This is the one
production correction in the ECR; the earlier tests-only scope is amended
rather than allowing witnesses to encode two answers.

## 3. Requirements

**R1 - Thirty-two witnesses.** Each of the sixteen public reads receives one
memory and one Postgres ordered-prefix witness. Fixtures insert six independent
rows in an order that conflicts with the read order, assert the store retained
all six, and assert every prefix for limits 1 through N. Postgres uses
`forced_keyset_plan` as insurance, never as the claimed mechanism.

Fixtures name every ordering column. Multi-column fixtures make the full tuple
observable; descending columns are explicit. Natural-key dedup is checked
before choosing identifiers. The executive fixture follows section 2.1, and
the lake fixture proves the aligned insertion-sequence tie-break.

**R2 - Mutation and necessity.** For each read and backend, deleting the sort
or SQL `ORDER BY` turns exactly its new witness red. Deselecting that witness
under the mutation returns green. The PR records the 32-row result matrix.
`tests/conformance/` remains in every probe because it is the existing catcher
for `vuln`.

**R3 - Scope C-038/R3 to its mechanism.**
`tests/conformance/test_ordering_determinism.py` witnesses
`VulnerabilityStore` only. Its repo-wide audit sentence becomes an explicitly
historical, unguarded observation. The ECR log records the amendment.

**R4 - No weakening.** The carried 57 controls stay red under their mutations.
Touching a carried-control file requires the full carried matrix to be rerun.

**R5 - Part 2 is measured before it is specified.** ECR-0099 measures leading
keys, predicates, and termination for this exact sixteen-method population.
Where a class does not apply to a cursorless API, it is recorded as not
applicable with grounds. Incidental coverage is claimed deliberately, not
inferred.

## 4. Scope

One memory ordering correction, tests, and records. No schema, dependency,
surface, loopback, persistence shape, or GC posture changes. Reads remain
bounded and read-only.

## 5. Method rules

Cover methods, not files: one module may contain several reads with different
coverage. Every census states its command, and every closure claim cites its
census. A classification deliverable precedes fixture design because a witness
written for the wrong API can be green while proving the wrong property.

## 6. Acceptance and handoff

Codex implements the backend alignment, thirty-two witnesses, C-038 scoping,
and the mutation/necessity matrix. Claude Code reviews the 32 new and 57
carried controls, checks the classification against public APIs, and writes the
ECR-0099 measurement brief. ECR-0098 becomes Accepted only when that work
ships.
