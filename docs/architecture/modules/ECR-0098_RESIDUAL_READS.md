# ECR-0098 - The residual sixteen, part 1: ordering clauses

**Status:** Accepted - implementation complete; second review required
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
ECR covers the sixteen residual methods below. The prior review initially
recorded fifteen silent ordering mutations and one red `vuln.query` result.
Repetition showed the red result was an outlier: **all sixteen were
unwitnessed**. C-038/R3's result changed with the Postgres physical plan, so it
could not carry the claim assigned to it. This is a correction to the source
brief, not a regression introduced by this ECR.

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
| forecast | `PredictionModelStore.query` | `method, version, id` | behavioural `method, version`; structural `id` pin |
| governance | `SnapshotStore.history` | `run_at, id` | behavioural prefixes |
| idthreat | `IdentityDetectionStore.query` | `detected_at, id` | behavioural prefixes |
| lake | `TelemetryRecordStore.query` | `occurred_at, id` | behavioural prefixes |
| lake | `TelemetryRecordStore.list_quarantine` | `received_at, insertion sequence` | behavioural alignment; structural Postgres `seq` pin |
| response | `CampaignStore.query` | `updated_at DESC, id` | behavioural prefixes |
| risk | `RiskStore.query` | `score DESC, id` | behavioural prefixes |
| risk | `RiskSnapshotStore.history` | `run_at, id` | behavioural prefixes |
| soc | `SOCStore.query_incidents` | `priority DESC, updated_at DESC, id` | behavioural prefixes |
| vuln | `VulnerabilityStore.query` | `discovered_at, id` | forced-plan behavioural prefixes |

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

The first fixture repeated the arc's correlation trap: UUIDv7 `source_id`
values increased with insertion order, so the former `(received_at,
source_id, reason)` implementation returned the expected rows. The corrected
fixture assigns descending IDs inside each equal-timestamp insertion group.
Both stores agree on the clean path, while restoring the former memory tuple
turns its named witness red.

### 2.3 Two tuple tails are structural

Two final components cannot be separated by a legal behavioral fixture:

- `PredictionModelStore` enforces `UNIQUE (tenant_key, method, version)`.
  The fixture makes `method` and `version` independently observable, but no
  valid pair can tie so that `id` decides. The executed SQL tuple is pinned by
  AST instead of inventing an illegal duplicate.
- `list_quarantine` assigns `seq` from insertion. On a newly populated table,
  heap order, insertion order, and `seq` order coincide. Its clean behavioral
  witness proves `received_at` and cross-backend alignment; the executed SQL
  tuple pins `seq`.

Deleting either structural component turns the central executed-query guard
red, and deselecting that guard under the mutation returns green. These are
named structural results, not mislabeled behavioral coverage.

## 3. Requirements

**R1 - Thirty-two witnesses.** Each of the sixteen public reads receives one
memory and one Postgres ordered-prefix witness. Fixtures insert six independent
rows in an order that conflicts with the read order, assert the store retained
all six, and assert every prefix for limits 1 through N. Postgres uses
`forced_keyset_plan` as insurance, never as the claimed mechanism.

Fixtures name every ordering column. Every behaviorally observable component
ties all preceding columns and anti-orders the next component; descending
columns are explicit. Natural-key dedup is checked before choosing identifiers.
The executive fixture follows section 2.1. The two components that cannot be
separated legally are pinned structurally under section 2.3.

**R2 - Mutation and necessity.** For each read and backend, deleting the sort,
the SQL ordering component, or the structural tuple component named in section
2.3 turns its assigned witness red. Deselecting that witness under the mutation
returns green. The PR records the 32-row result matrix. C-038/R3 is not credited
as a catcher because its mutation verdict is plan-dependent.

**R3 - Scope C-038/R3 to its mechanism.**
`tests/conformance/test_ordering_determinism.py` witnesses
`VulnerabilityStore` only. Its repo-wide audit sentence becomes an explicitly
historical, unguarded observation. Its clean-path comparison remains useful,
but it is not mutation evidence: without the SQL tiebreak, a matching index may
still return ID order. The ECR log records both limits.

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

## 6. Resolution and handoff

The backend alignment and all thirty-two cases are present: sixteen named read
controls, each covering memory and Postgres. A user-owned PostgreSQL 16.14
instance supplied the local database matrix; the evidence is no longer
delegated to merge review.

The matrix below uses the trailing observable component unless noted. `RED`
means the assigned control failed under mutation; `GREEN` means the same
mutated implementation passed when that control was deselected.

| Read | Backend | Mutation | Control | Without control |
|---|---|---|---|---|
| assetconfig history | memory | drop `id` from sort | RED | GREEN |
| assetconfig history | Postgres | drop `id` from SQL | RED | GREEN |
| decision query | memory | drop `id` from sort | RED | GREEN |
| decision query | Postgres | drop `id` from SQL | RED | GREEN |
| executive versions | memory | delete version sort | RED | GREEN |
| executive versions | Postgres | delete version order | RED | GREEN |
| executive reports | memory | drop `id` from sort | RED | GREEN |
| executive reports | Postgres | drop `id` from SQL | RED | GREEN |
| exposure query | memory | drop `id` from sort | RED | GREEN |
| exposure query | Postgres | drop `id` from legacy SQL only | RED | GREEN |
| forecast query | memory | drop `id` from sort | RED | GREEN |
| forecast query | Postgres | drop `id` from SQL | RED | GREEN |
| forecast models | memory | delete tuple sort | RED | GREEN |
| forecast models | Postgres | drop structural `id` pin | RED | GREEN |
| governance history | memory | drop `id` from sort | RED | GREEN |
| governance history | Postgres | drop `id` from SQL | RED | GREEN |
| idthreat query | memory | drop `id` from sort | RED | GREEN |
| idthreat query | Postgres | drop `id` from SQL | RED | GREEN |
| lake query | memory | drop `id` from sort | RED | GREEN |
| lake query | Postgres | drop `id` from SQL | RED | GREEN |
| lake quarantine | memory | delete stable time sort | RED | GREEN |
| lake quarantine | Postgres | drop structural `seq` pin | RED | GREEN |
| response query | memory | drop `id` from sort | RED | GREEN |
| response query | Postgres | drop `id` from SQL | RED | GREEN |
| risk query | memory | drop `id` from sort | RED | GREEN |
| risk query | Postgres | drop `id` from SQL | RED | GREEN |
| risk history | memory | drop `id` from sort | RED | GREEN |
| risk history | Postgres | drop `id` from SQL | RED | GREEN |
| SOC incidents | memory | drop `id` from sort | RED | GREEN |
| SOC incidents | Postgres | drop `id` from SQL | RED | GREEN |
| vulnerability query | memory | drop `id` from sort | RED | GREEN |
| vulnerability query | Postgres | drop `id` from SQL | RED | GREEN |

Additional controls exercise the middle `version` component of prediction
models on both stores; both mutations are red. Restoring quarantine memory's
former `(received_at, source_id, reason)` tuple is also red against the
decorrelated fixture while clean memory and Postgres agree.

The C-038 docstring now records its physical-plan limit. The central structural
guard pins the two unobservable SQL tails. Claude Code independently reruns the
32 new and 57 carried controls and writes the ECR-0099 measurement brief.
