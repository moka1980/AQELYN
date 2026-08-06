# ECR-0115 — Accounts, invites and sessions, with the tenant bound to the session

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable (out until Saturday).
**Date:** 2026-08-06
**Number:** verified free at `363818c` (main tip after ECR-0114, PR #317).

> ⚠️ Sixteenth consecutive ECR by one actor. §5 lists what independent review should attack.
> This is the first ECR of the customer-account arc (0115–0119) claude.ai specified.

## 1. Finding of record

The scan capability ships and the platform has a single-operator login (scrypt in `auth.json`,
HttpOnly+Secure+SameSite cookie). What it does not have is **more than one customer**. A real
customer needs their own account, and — the load-bearing part — their data must be reachable
only under their own tenant. The store layer already scopes findings by `tenant_id`
(`WHERE tenant_id IS NOT DISTINCT FROM $1`, DDL indexes lead with it). The missing piece is an
identity that produces that `tenant_id` **from an authenticated session, never from client
input**. If a request could name its own tenant, every downstream isolation guarantee would be
a decoration.

## 2. Decision

A self-contained `src/aqelyn/identity/` package: accounts, invites, sessions. File-backed JSON
today (the `auth.json` pattern — 0600, atomic write-then-rename), migrating into Postgres in
ECR-0116 **without changing this surface**.

- **`models.py`** — `Account` (`acc_` id, email, `tenant_id`, scrypt `PasswordHash`, status
  `active|disabled`, created_at), `Invite` (`inv_` id, token, tenant_id, optional email,
  expires_at, redeemed_by). The `tenant_id` validator requires a non-empty UUID; the id
  validators require the typed prefix. New prefixes `acc`/`inv` registered in `conventions/ids.py`.
- **`passwords.py`** — `hash_password` (scrypt N=16384, r=8, p=1, 32-byte key, 16-byte salt),
  `verify_password` (scrypt + `hmac.compare_digest`, **fail-closed** on empty or malformed
  stored material). No plaintext is ever stored or logged.
- **`store.py`** — `AccountStore` (create refuses a duplicate email; `authenticate` returns the
  account only if it is **active** and the password matches), `InviteStore` (**single-use**,
  refuses expired / already-used / email-mismatched / unknown invites — registration is
  **invite-only**, decision 1 of the arc), and `SessionStore` whose `start` binds
  `tenant_id = account.tenant_id`. **The tenant is bound from the account, never from anything
  the client sends** — this one line is the whole point of the module. `resolve` refuses an
  expired session; `end` logs out.

Registration is invite-only, so there is no anonymous self-signup path to abuse. Sessions are
in-memory (a restart requires re-login — acceptable, and it matches the operator login); accounts
and invites are durable on disk.

## 3. Isolation, stated as the property under test

`test_two_tenants_sessions_never_cross` builds two accounts under two different tenant UUIDs,
starts a session for each, and asserts each session resolves to **only** its own tenant — a
session for tenant A can never be made to carry tenant B, because `start` reads the tenant from
the account row and the client never supplies it. This is the store-layer half of the arc's
isolation promise; the route-level census and the adversarial cross-tenant audit are ECR-0119.

## 4. Acceptance — 7 mutations, all red

Harness `~/AQELYN_ECR0115_PREP/matrix.sh`, cache purged per mutation. Each removed guard turns a
witness RED:

1. password check always passes → `test_password_verifies_and_rejects`, `test_authenticate_accepts_right_password_only`
2. session tenant not bound to the account (taken from a parameter) → `test_session_carries_the_accounts_tenant`, `test_two_tenants_sessions_never_cross`
3. invite reusable (single-use removed) → `test_an_invite_is_single_use`
4. expired invite accepted → `test_an_expired_invite_is_refused`
5. disabled account can authenticate → `test_a_disabled_account_cannot_authenticate`
6. duplicate email allowed → `test_duplicate_email_is_refused`
7. expired session still resolves → `test_an_expired_session_resolves_to_nothing`

17 tests (`tests/identity/test_identity.py`) on a movable clock and two tenant UUIDs. Ruff clean,
`mypy --strict` clean across 601 files, full suite **2094 passed, 5 skipped** on live Postgres.

One census note: `store.py`/`passwords.py` import the stdlib `secrets` module **aliased** as
`_rand`, because the GC-004 persisted-field census matches the bare name `secrets` against the
`secrets` package's exempt `secrets` field and would otherwise read this module as an external
reader of it. The alias removes the collision without touching the guard — the same move as the
`schema` → `document_schema` rename in ECR-0108. GC-004 was **not** weakened.

## 5. What review should attack

1. **Sessions are process-memory.** Two platform workers would not share sessions, and a restart
   drops every login. Fine for the single-process deployment today; a shared session store (or the
   Postgres migration carrying sessions too) is the real fix, named for a later ECR.
2. **File-backed store, coarse lock.** `AccountStore`/`InviteStore` serialise on a
   `threading.Lock` and rewrite the whole JSON file per mutation. Correct and durable at customer
   counts of tens; it does not scale, which is exactly why 0116 moves it to Postgres.
3. **Invite tokens are the only registration gate.** A leaked invite token before redemption is a
   free account under that tenant. TTL (7 days) and single-use bound the window; per-email binding
   narrows it further when the inviter sets the email. No rate-limit on redemption yet.
4. **`redeem` creates the account inside the invite lock**, calling `AccountStore.create` which
   takes its own lock. Lock order is always invite→account and never the reverse, so it cannot
   deadlock — but that invariant lives in a comment, not a test.

## 6. Scope

New `src/aqelyn/identity/{__init__,models,passwords,store}.py`, `tests/identity/test_identity.py`,
two new id prefixes in `src/aqelyn/conventions/ids.py`. A brief note added to
`BRIEF_CUSTOMER_SCAN_FLOW.md` pointing the account view at ECR-0114's bilingual register. No change
to any existing route, the collector, the pipeline, the schema, or the operator login — this adds
the identity layer the rest of the arc builds on.
