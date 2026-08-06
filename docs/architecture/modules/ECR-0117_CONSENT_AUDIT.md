# ECR-0117 — Consent before a write, and an append-only audit of every one

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable (out until Saturday).
**Date:** 2026-08-07
**Number:** verified free at `be41d74` (main tip after ECR-0116, PR #319).

> ⚠️ Eighteenth consecutive ECR by one actor. §5 lists what independent review should attack.
> Third ECR of the customer-account arc (0115–0119).

## 1. Finding of record

The next ECR (0118) lets a customer **upload** their scan — a *write*. Charter **UX-005** requires
explicit consent for anything automated, and the platform login honestly admitted the "audited
command path" did not yet exist. Before the write path is built, the platform needs two things it
does not have: a record that the customer **consented** to store their scan, and an **append-only
audit** of who did what, when. Both must be per-tenant — one customer's consent or audit trail must
never be visible to another.

## 2. Decision

A new `src/aqelyn/consent/` package, following the identity backend pattern exactly (ECR-0116):
async protocols, an in-memory backend for tests/local, an asyncpg backend for production, selected
by `build_consent_stores`.

- **`ConsentRecord`** — `con_` id, tenant_id, account_id (who consented), a closed `scope`
  (`store_scan`), the `text_version` agreed to, `granted_at`, `revoked_at`. `ConsentStore` offers
  `record`, `active(tenant, scope)` (the latest non-revoked consent), and `revoke`.
- **`AuditEvent`** — `aud_` id, tenant_id, actor_account_id, a closed `action`
  (`consent_granted` / `consent_revoked` / `scan_ingested` / `data_deleted`), a `detail` string
  (e.g. the upload digest), `at`. `AuditLog` offers only **`append` and `list`** — there is no
  update or delete path, so the log is append-only by construction. Postgres uses a `bigserial seq`
  for stable insertion order; both tables index `tenant_id` first.

Scopes and actions are closed `Literal`s so a typo cannot invent an unreviewed scope or an
unrecorded action.

## 3. The properties under test

Every test runs on both backends (Postgres skipped without `AQELYN_DATABASE_URL`). The load-bearing
properties:

- **Consent gates correctly:** no consent → `active` is `None`; recorded → active; revoked → not
  active; re-consent after revoke → active again with the new `text_version`.
- **Tenant isolation:** tenant B never sees tenant A's consent (`test_consent_is_tenant_scoped`),
  revoking B never disturbs A (`test_revoke_is_tenant_scoped`), and A's and B's audit trails are
  disjoint (`test_audit_is_tenant_scoped`).
- **Append-only:** two appends both survive, in insertion order, and the store exposes no way to
  alter a recorded event.

## 4. Acceptance — 8 mutations, all red

Harness `~/AQELYN_ECR0117_PREP/matrix.sh`, cache purged, Postgres live so both parametrizations run.
Memory: active-ignores-revocation, active-ignores-tenant, revoke-ignores-tenant,
audit-list-ignores-tenant. Postgres: the same four, expressed against the SQL (`revoked_at IS NULL`
dropped; each `WHERE tenant_id=$1` turned into a tautology). Each turns the expected backend's
parametrization red — the tenant-scope mutations correctly fail the cross-tenant tests.

ruff + `mypy --strict` clean across 617 files; full suite **2126 passed, 5 skipped** on live
Postgres. Carried matrix rises to **111**.

GC-004: `actor_account_id`, `revoked_at`, `text_version` are newly persisted with no external reader,
so they are added to `EXEMPT_FIELDS` — consumers receive `ConsentRecord`/`AuditEvent` envelopes
through `active()`/`list()` rather than reading these fields directly. The guard was **not** weakened.

## 5. What review should attack

1. **"Append-only" is enforced by omission, not by a constraint.** The store simply exposes no
   update/delete, and the DDL grants none — but nothing at the database level *prevents* a future
   method (or a direct `UPDATE`) from mutating a row. A tamper-evident hash chain (as evidence uses)
   would make append-only provable rather than conventional. Named, not built.
2. **`detail` is a free-text string.** ECR-0118 will put the upload digest there; there is no schema
   on it yet, so a caller could write anything. Fine while the only writer is the ingest path.
3. **Consent is per (tenant, scope), and there is one scope.** The moment a second scope or a
   per-account consent is needed, `active` and `revoke`'s "latest non-revoked" semantics need review
   — today they are deliberately minimal.
4. **No rate limit or size bound here** — those live at the route layer (0118/nginx). This ECR is the
   data layer only.

## 6. Scope

New `src/aqelyn/consent/{__init__,models,store,memory,postgres,ddl,factory}.py`; new
`tests/consent/` (conftest + tests + `__init__.py`); two id prefixes (`con`, `aud`) in
`conventions/ids.py`; one `EXEMPT_FIELDS` group and its pinned mirror. No change to identity, the
collector, the surface, or any other domain — this adds the consent/audit layer 0118 will gate on.
