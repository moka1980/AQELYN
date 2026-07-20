# C-028 Data Security Posture Management - Implementation Task Bundle

**Milestone:** C-028 (EA-0031)
**For:** Codex (implementer), Claude Code (reviewer)
**Prerequisites:** C-027 merged and green; EA-0031 Accepted; ECR-0041 and the
EA-0023 owner-contract amendment on main; CONVENTIONS and EA-0009/0010/0011/
0019/0023/0025 read.
**Definition of Done:** every ticket reviewed behaviorally; in-memory and
Postgres contracts green; ruff, ruff format --check, mypy --strict, imports, and
full suite green; no raw sensitive content; unknown never means public/safe; no
second inventory/access/compliance/exposure/risk engine.

Read EA-0031 sections 0 and 2 first. This is a classifier and router over data
stores. Its new work is:

1. classify metadata-only store descriptors with EA-0019's exact taxonomy;
2. compose that sensitivity with EA-0023's real known-surface and scorer APIs.

The implementation must not create a SurfaceFacet/public_storage abstraction.
Those types do not exist. It must use KnownSurfaceSource, KnownSurfaceRecord,
ExposureRecord, and ECR-0041 ExposureImpactContext.

## Target layout

~~~
src/aqelyn/dspm/
|-- __init__.py
|-- models.py
|-- classify.py
|-- surface.py
|-- engine.py
|-- store.py
|-- memory.py
|-- postgres.py
|-- ddl.py
\-- service.py
tests/dspm/
~~~

No taxonomy.py, inventory.py, access.py, compliance.py, risk.py, scanner.py, or
local exposure scorer.

## P1 - Types, config, and structural privacy/unknown gates

**Spec:** sections 0.1/0.2, 2, 4; FR-1/2/4/5/10/14; AC-1 through AC-5,
AC-12, AC-18.

Deliver:

- ids/errors and all EA-0031 models;
- import Classification and SchemaType from aqelyn.lake.models;
- typed metadata-only descriptor shapes with extra="forbid";
- FieldClassification and DataAsset invariants;
- DataExposure state invariants;
- typed DSPMScope and DataPostureAssessment coverage invariants;
- typed EA-0009 ClassifierRule and DSPMConfig.

Hard checks:

- attempts to add raw_value, sample, content, rows, document, blob, credential,
  or token fail at construction;
- unknown/conflict cannot be unflagged or represented as public;
- reachability_pending/classification_gap cannot carry score/derivation;
- pending assessment cannot carry completed counts.

## P2 - Classification, inventory routing, and durable stores

**Spec:** sections 3/5/6.1; FR-3 through FR-7, FR-15/16; AC-5 through AC-8,
AC-16/17.
**Depends on:** P1.

Deliver:

- metadata-only EA-0009 condition evaluation;
- evidence lookup and EA-0006 confidence pinned to observed_at;
- deterministic reliability reconciliation with durable conflict candidates;
- EA-0002 object upsert and real EA-0025 ingest, preserving object_id and
  inventory_ref;
- append-only DSPMStore in-memory/Postgres plus DDL;
- D8 query semantics: stable id order, filters before limit, exclusive cursor,
  next_cursor exactly when another matching row exists, repeated-cursor guard in
  consumers;
- bounded assessment coverage state.

Behavioral proof must drive the real object and inventory owners, not only spies.
No evidence-backed winning rule means unknown+flagged.

## P3 - Real known-surface handoff and sensitivity-aware exposure

**Spec:** sections 0.3/3/6.2; ECR-0041; FR-8 through FR-10; AC-9 through AC-12.
**Depends on:** P2.

Deliver:

- additive EA-0023 ExposureImpactContext model, optional ExposureRecord field,
  score_exposure argument, derivation binding, and owner spec/tests;
- DataStoreKnownSurfaceSource over the DSPM store, composed with the existing
  source at both factory sites;
- data exposure analysis through the real EA-0023 engine;
- known sensitivity factor passed to EA-0023; no local final scorer;
- unknown sensitivity -> flagged classification_gap with no factor/score;
- unknown reachability -> flagged reachability_pending with no score;
- known sensitive fields plus unknown fields -> confirmed exposure and separate
  classification_gap; neither state overwrites the other;
- persisted DataExposure and explain output.

Behavioral proof:

- upstream rows survive;
- same-ref placeholder replacement does not duplicate;
- a page failure or repeated cursor refuses instead of serving partial data;
- higher known sensitivity cannot lower the real EA-0023 score;
- tampering with the impact context/derivation is rejected.

## P4 - Access, compliance, findings/risk, and delegated remediation

**Spec:** sections 0/6.3; FR-11 through FR-13; AC-13 through AC-15.
**Depends on:** P3.

Deliver:

- access_context over evidenced descriptor identity claims, calling the real
  EA-0011 access_paths and analyze_risk APIs;
- no claims or retriable owner outage -> pending, never known-empty;
- data_compliance delegating to real EA-0010 assessment over data_store objects;
- exposure/classification-gap findings with evidence and eligibility none;
- EA-0013 consumption through its shipped findings path, no new SignalKind;
- optional EA-0008 propose-only remediation with requires_approval=true.

Use mutation, execute, and handler spies. All must remain empty. A programming
error from an owner must propagate; only retriable availability errors become
pending.

## P5 - Service, events, and both factory runtimes

**Spec:** section 9; FR-17; AC-17/19/20.
**Depends on:** P4.

Deliver:

- DSPMService as AQService name dspm_engine;
- exactly the three EA-0031-owned events;
- dependency/config health including unavailable classifier evidence, known
  surface, IAG, governance, findings, Workflow, and store;
- in-memory and Postgres factory wiring;
- TYPE_CHECKING plus local in-function factory imports, following the R5/T5
  circular-import pattern.

Drive factory-built runtimes in both modes. Prove the real inventory and
known-surface adapters are connected; a hand-built config or echo spy does not
settle connectivity.

## Review protocol

Review each ticket behaviorally per ECR-0007, in this order:

1. **No PII lake.** Construct forbidden raw-content fields and prove rejection;
   inspect persisted shapes. A grep is not proof.
2. **Unknown is not safe.** Unknown sensitivity is not public; unknown reach is
   not unreachable/internal; pending/partial assessments cannot look complete.
3. **Real owner seams.** EA-0019 types are imported. EA-0023 uses
   KnownSurfaceSource and ExposureImpactContext. No SurfaceFacet appears.
4. **Connectivity, not just intent.** Run at least one data store end to end
   against each real owner. Spies remain useful for envelope preservation but
   do not prove the receiving owner can act.
5. **Pagination and work bounds.** Adversarial ordering, exactly-limit,
   more-than-limit, repeated cursor, and tenant isolation on both backends.
6. **No action path.** Findings and Workflow proposals only; no execute, handler,
   revoke, move, delete, or connector call.
7. **Service discipline.** Exactly three owned events, honest degraded health,
   both factory sites, clean isolated imports.

After P5 is green, report back to the owner. Revisit ECR-0032 as a separate
behavior-preserving refactor decision; do not extract a shared posture base in
C-028.
