# AQELYN spec-author brief — the customer self-service scan flow

**From:** Claude Code (reviewer; the only actor who reads shipped `src/` and runs the servers)
**To:** claude.ai (spec author) and Codex (implementer/reviewer)
**Date:** 2026-08-06
**Owner must relay this** — claude.ai reads neither the repo nor my filesystem.

> The user story this closes: *a customer signs in, runs the read-only collector on their own
> device, uploads the result, and sees their own findings — and no one else's.*

---

## 1. What already works (do NOT rebuild)

The scan capability is real and shipped. The gap is **accounts + upload**, not scanning.

- **Collectors → `posture.json`.** Linux (`aqelyn collect`, the ECR-0102…0112 host collector) and
  Windows (a new PowerShell collector) both emit the same `posture.json` schema. Both are LIVE for
  download at **https://aqelyn.com/scan** (Linux `.pyz`, Windows `.ps1`, each with a SHA-256). Both
  were validated against real machines (a Linux server and a real Windows 11 laptop).
- **Ingestion exists.** `reporting/analyze.py::ingest_posture_into(runtime, directory)` already turns
  a collection directory into raised Findings, through the real finding store, with evidence records.
- **The posture document is already validated.** `reporting/posture.py::validate_posture_shape`
  refuses malformed / incomplete observations (the four narrative fields, severity range, etc.).
  **Reuse it on upload — the uploaded file is untrusted input.**
- **Subjects already become objects.** ECR-0106 gives each posture subject a natural-key `AQObject`
  via `upsert`, so Affected Assets resolve and re-uploads dedupe.
- **Presentation exists.** Progressive disclosure (ECR-0104/0105), the plain-words glossary
  (ECR-0108), and the HTML report all render findings already.
- **A secure session login exists (built 2026-08-06).** The platform now has real auth:
  scrypt-hashed password in `auth.json`, an HttpOnly+Secure+SameSite=Strict session cookie, every
  data route gated, nginx `limit_req` on `/login`. **This is single-operator.** The customer flow
  extends it to multi-user — the crypto and cookie handling are the template to copy, not redo.

**So the build is: multi-user identity, durable per-tenant storage, a consented upload, and
per-tenant isolation.** Everything downstream of "a validated posture.json for tenant T" exists.

---

## 2. Current runtime state (accurate as of this brief)

- `main` at the latest tip (read the ECR-LOG for the SHA and next free ECR — never from memory).
- The platform runs on the aqelyn.com VPS as two loopback systemd services: `aqelyn-surface`
  (:8765, the kernel + data API) and `aqelyn-platform` (:8800, the frontend). nginx is the only
  public face. **Backend is `memory` / `tenant_mode=local`** — nothing persists across a restart.
- The surface is loopback-only **by design (ECR-0088)** and must stay so. The customer-facing layer
  is the **platform** (with real auth), never the raw surface exposed to the internet.

---

## 3. The build, as candidate ECRs (dependency order)

**ECR-A · Identity model (multi-user).** Customer accounts with per-user scrypt-hashed credentials,
sessions, and a `tenant_id` per account. Generalises the single-operator `auth.json` login. Decide
self-registration vs invite-only (see §6). Every account maps to exactly one tenant.

**ECR-B · Durable storage.** Accounts and findings must survive a restart, so move from
`backend=memory` to `backend=postgres` (the kernel already supports it: `AQELYNConfig.backend`,
`database_url`; `backend=postgres` requires `AQELYN_DATABASE_URL`). Infra step: stand up PostgreSQL
on the VPS (loopback, like the WCAGvakt/disponit pattern) — **owner decision: same box or a new
one** (the box is 2 vCPU / 4 GB and already runs nginx + two services). Keeps the surface's
in-memory path for the public demo; the customer store is Postgres.

**ECR-C · Consent + audit path (Charter UX-005).** An upload is a *write*. UX-005 requires explicit
consent for anything automated, and the surface's read-only property (ECR-0088) must not be
silently reversed. The customer explicitly consents to store their scan; every upload is audited
(who, when, what digest). This is the "audited command path" the prototype login honestly said did
not exist.

**ECR-D · Authenticated upload/ingest.** A gated `POST /api/v1/scans` that:
1. requires a valid session (ECR-A);
2. reads the uploaded `posture.json`, **bounded in size**, and runs `validate_posture_shape` — refuse
   malformed input with a located reason, never repair it;
3. ingests via the existing `ingest_posture_into`-style path **into the caller's tenant only**;
4. returns the customer's findings for their account.
The collector download page already produces exactly this file; add an "upload" affordance.

**ECR-E · Per-tenant isolation.** A customer sees only their own assets/findings. The read services
(`finding_read`, `inventory`, etc.) must scope every query by `tenant_id`; add a test that tenant A
can never see tenant B's data. This is the highest-risk correctness property in the whole flow.

---

## 4. Security requirements (learned from the login build — non-negotiable)

- Passwords: `hashlib.scrypt` salted per user; compare with `hmac.compare_digest`. Never store plaintext.
- Sessions: cryptographically random tokens; cookie `HttpOnly; Secure; SameSite=Strict; Path=/`.
- Rate-limit auth and upload endpoints (nginx `limit_req`, already patterned for `/login`).
- **The uploaded posture.json is hostile input.** Bound its size; validate hard; never `eval`/trust
  fields; the JSON parser + `validate_posture_shape` are the gate. A malformed upload must not crash
  or poison another tenant.
- **No cross-tenant leak** — the property ECR-E exists to guarantee, tested adversarially.
- Consent before any write (UX-005); audit trail is append-only.
- Do not expose the loopback surface (ECR-0088). The platform is the boundary.
- Keep the public `/api/summary` counts-only; never let per-customer detail reach an unauthenticated route.

---

## 5. False friends / things not to break

- **ECR-0088 loopback surface** — the surface binds 127.0.0.1 with no config key. The customer flow
  goes through the platform, not by exposing the surface.
- **`validate_posture_shape`** — do not weaken it to accept a customer's imperfect upload. A refused
  document is the honest outcome; the collector always produces a valid one.
- **`document_schema` not `schema`** — the collector key avoids the GC-004 census collision with
  `lake.schema`. Keep it.
- **EA-0054 Web Intelligence is a recorded decision NOT to build** — its absence guard is a text
  census over `src/`; do not write HSTS/CSP/SPF/DKIM/DMARC vocabulary into `src/`.
- **"Unmeasured is a state"** — the collectors report unread facts as info/unmeasured, never as a
  default. The upload path must preserve that; do not coerce missing fields to "clean".

---

## 6. Open decisions for the owner / claude.ai

1. **Registration:** self-service sign-up vs invite-only (a security product with open sign-up
   invites abuse; invite-only is safer to start).
2. **PostgreSQL location:** the existing 4 GB VPS (co-located with nginx + services) or a new box.
3. **What is stored:** the raw uploaded `posture.json` (re-renderable, but it is the customer's data)
   vs only the derived findings. Retention period.
4. **Multi-tenancy depth:** `tenant_mode=enterprise` vs a lighter per-account scoping in `local`.
5. **Mobile** remains a separate track (device-management enrollment / signed profile), not part of
   this flow.

---

## 7. What review should attack first

1. **Per-tenant isolation (ECR-E)** — the one bug here that is a breach, not a blemish. Adversarial
   test: authenticate as tenant A, attempt every read/route for tenant B's ids; all must refuse.
2. **Upload as hostile input (ECR-D)** — oversized files, malformed JSON, valid-JSON-invalid-shape,
   duplicate observation ids, unicode/huge fields. `validate_posture_shape` must hold.
3. **Session and consent** — no write without a valid session AND recorded consent; audit is
   append-only and cannot be forged by the client.
4. **Persistence correctness (ECR-B)** — the keyset/pagination discipline of the witness arc
   (ECR-0090…0099) applies to the Postgres finding reads; do not regress it.

---

## 8. Sequencing summary

Identity (A) → durable storage (B) → consent/audit (C) → upload (D) → tenant isolation (E, tested
throughout). The scanning, ingestion, object-linking, disclosure and rendering are all already done;
this brief is entirely about turning "one operator, in memory" into "many customers, each seeing only
their own scan, persisted and consented."

**Next actor: claude.ai turns this into ECRs; Codex implements; I review and run it on the real box.**
