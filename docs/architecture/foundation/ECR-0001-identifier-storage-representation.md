# ECR-0001 - Identifier and Tenant Storage Representation

**Status:** Proposed
**Raised:** 2026-07-12
**Raised by:** Codex, from Claude Code C-001 review finding
**Scope:** C-001 Foundation Runtime; CONVENTIONS; EA-0002; EA-0003; EA-0004; Finding model; EA-0001 wiring

## 1. Summary

C-001 currently persists AQELYN typed identifiers and `tenant_id` values as
PostgreSQL `text`, while the accepted CONVENTIONS spec says internal keys are
UUIDv7 values stored as PostgreSQL `uuid`, and tenant IDs are `uuid | null`.
The implementation is internally coherent, but it diverges from the binding
specs and must be resolved by an explicit owner decision.

## 2. Evidence

Binding specs:

- `docs/architecture/foundation/CONVENTIONS.spec.md` section 1 says the
  internal key is UUIDv7 and is stored as PostgreSQL `uuid`.
- `docs/architecture/foundation/CONVENTIONS.spec.md` section 5 says
  `tenant_id` is `uuid | null`.
- The persistence sections in the foundation specs use UUID-typed IDs and
  tenant IDs in their SQL examples.

Implementation:

- `src/aqelyn/conventions/ids.py` mints canonical external identifiers such as
  `obj_<uuidhex>` and `fnd_<uuidhex>`.
- Postgres DDL files persist those canonical external identifiers directly as
  `text` primary keys and foreign keys.
- Postgres DDL files persist `tenant_id` as `text NULL`.
- In-memory tests use simple tenant strings such as `t1` and `t2`.

## 3. Why It Matters

The current implementation passes functional tests, but future modules need one
clear rule for IDs and tenants. If the rule remains unstated, later modules may
mix raw UUID columns, prefixed text IDs, and opaque tenant strings. That would
weaken schema consistency, migration safety, traceability, and cross-module
reviewability.

## 4. Decision Options

### Option A - Enforce UUID columns

Change Postgres schemas to store raw UUIDv7 payloads in `uuid` columns and keep
the prefixed form only at API/model boundaries.

Required follow-up:

- Add encode/decode helpers that convert `obj_<uuidhex>` to raw UUID and back.
- Update all Postgres stores, joins, indexes, and tests.
- Decide how non-typed values such as current `source_id` fixtures and
  `tenant_id` strings become valid UUIDs.
- Add migration tests proving external IDs round-trip exactly.

Benefits:

- Strictly matches the current wording of CONVENTIONS.
- Uses native PostgreSQL UUID typing and indexing.

Risks:

- Broad C-001 churn after the foundation is otherwise green.
- Requires careful treatment of every typed-ID family and tenant ID.
- Easy to create accidental prefix loss at persistence boundaries.

### Option B - Sanction canonical text storage for C-001

Amend CONVENTIONS and the foundation persistence specs to state that the
canonical persisted key for C-001 typed IDs is the full external form
`{prefix}_{uuidhex}` stored as `text`, while the UUIDv7 payload remains mandatory
inside the typed ID. Also explicitly decide whether `tenant_id` is an opaque text
scope key for C-001 or a UUID string that must validate as UUID.

Required follow-up:

- Revise CONVENTIONS section 1 to distinguish the UUIDv7 payload from the
  persisted canonical typed ID.
- Revise CONVENTIONS section 5 to state the selected tenant representation.
- Revise EA-0002, EA-0003, EA-0004, and Finding model persistence DDL examples
  to match the approved storage rule.
- Add tests that assert persisted IDs are valid typed IDs and tenant IDs follow
  the approved rule.

Benefits:

- Matches the current, tested implementation.
- Preserves prefix information in primary keys, foreign keys, logs, and manual
  database inspection.
- Avoids broad late-stage churn in C-001.

Risks:

- Gives up native UUID column typing for C-001 typed IDs.
- Must be documented clearly so future modules do not treat arbitrary text as a
  valid ID.

## 5. Recommendation

Approve Option B for C-001, with a strict validation requirement:

- Typed artifact IDs remain full canonical strings in storage, but the UUIDv7
  payload inside them must validate through `parse_id`.
- `tenant_id` must be decided explicitly before EA-0005 begins. If the owner
  wants enterprise tenants to be UUIDs, keep API type `str` but validate UUID
  shape and update tests away from `t1`/`t2`.

This recommendation preserves the green C-001 implementation while making the
convention explicit and reviewable.

## 6. Acceptance Criteria

This ECR is resolved only when one option is accepted and implemented through a
PR that:

1. Updates the affected specs or code so they agree.
2. Keeps `ruff`, `mypy --strict`, and the full C-001 test suite green.
3. Adds or updates tests covering the selected ID and tenant storage rule.
4. Receives Claude Code review against CONVENTIONS, the affected specs, and this
   ECR.

## 7. Current Disposition

No runtime changes are authorized by this ECR while it is Proposed. C-001 may be
considered functionally green, but final foundation sign-off should wait for the
owner to approve Option A or Option B and for the resulting PR to pass review.
