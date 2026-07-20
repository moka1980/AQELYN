# C-029 Secrets Security & Cryptographic Asset Intelligence - Task Bundle

**Milestone:** C-029 (EA-0032)
**Implementer:** Codex
**Reviewer:** Claude Code
**Prerequisites:** C-028 merged and green; EA-0032 Accepted; ECR-0043/ECR-0044 logged;
EA-0032 sections 0, 1, and 4 read before implementation.

**Definition of Done:** all acceptance tests pass on in-memory and Postgres;
`ruff`, format, and `mypy --strict` are clean; no secret value is constructible or
persistable; unknown never reads as safe; integrity never implies authenticity;
owners are used through their shipped APIs; no effect executes; both tenant modes
are exercised in both factory runtimes.

ECR-0007 applies: safety is proven structurally and behaviorally. Grep may be a
secondary signal, never the proof. Run the value/state gates under `python -O`.

## Target layout

```text
src/aqelyn/secrets/
  __init__.py
  models.py
  store.py
  memory.py
  postgres.py
  ddl.py
  ingest.py
  lifecycle.py
  exposure.py
  engine.py
  service.py
tests/secrets/
```

No `inventory.py`, `risk.py`, scanner, connector, action handler, or raw-value
store belongs in this package.

## W1 - Types, taxonomy, and structural value/state gates

**Spec:** sections 0.1, 0.2, 1, 4, 9; FR-1/3/11/12/13.

**Deliverables:**

- Strict typed descriptors and domain models from section 4, including typed
  `SecretLocation`/`CryptoScope`; no free-form metadata mapping.
- Recursive pre-construction rejection of value-bearing key names, credential
  URL components, and malformed fingerprints via `SecretValueRejected`. Inspect
  mapping keys, not ordinary field values; positively prove
  `SecretKind="private_key"` remains valid.
- `Lifecycle` invariant: known requires evidence; unknown requires reason.
- `CryptoAssessment` invariant: pending carries no results; truncated requires a
  reason; complete forbids one.
- `CryptoConfig` validation.
- Register `sct`, `cky`, `x509`, `cas` and four error codes in code and
  CONVENTIONS. Preserve `cert = iag_certification`.

**Acceptance:** AC-1, AC-3, AC-12, AC-15, AC-16.

## W2 - Evidence-first ingest and durable stores

**Spec:** sections 5, 6.1; D1/D2/D6; FR-2/6/7/14/15.

**Deliverables:**

- Handed-in ingest only; no socket, scan, repository, vault, KMS, or HSM read.
- Validate evidence before any local or owner write. Missing and tampered
  evidence are distinct refusals; retriable unavailability is not converted to
  a safe record.
- Reconcile source claims via EA-0006; retain conflicts rather than last-writer.
- Create EA-0002 objects and drive the real EA-0025 `ingest` adapter, retaining
  distinct `object_id` and `inventory_ref`.
- `CryptoStore` memory/Postgres + DDL, immutable records, tenant isolation, deep
  copy isolation, and EA-0002 D8 cursor semantics from the first schema.
- Engine scans page under `max_work`, reject repeated cursors, and expose
  truncation.

**Acceptance:** AC-2, AC-6, AC-7, AC-13, AC-14, AC-16.

## W3 - Lifecycle and two-stage verification

**Spec:** sections 1, 4, 6.2/6.3; D3/D4; FR-3/4/5/6/11.

**Deliverables:**

- Certificate expiry, chain, revocation, integrity, and authenticity lifecycle.
- Key strength and rotation lifecycle.
- No-expiry, unknown algorithm, missing rotation, unreadable chain, and
  unavailable revocation each produce unknown, never valid.
- EA-0004 integrity first; typed `CertificateAuthenticityVerifier` second;
  persist the verifier result as EA-0004 evidence. A valid verifier result with
  unrelated/tampered input cannot be laundered into authenticity.
- `unknown_lifecycle` is counted in semantic assessment coverage.

**Acceptance:** AC-3, AC-4, AC-5, AC-6, AC-12.

## W4 - Exposure, owner handoffs, findings, and gated proposals

**Spec:** sections 0.3, 1 S3/S5, 5, 6.4/6.5; FR-8/9/10.

**Deliverables:**

- A crypto `KnownSurfaceSource` that composes with the real
  `InventoryKnownSurfaceSource`, replaces the same `ast_` placeholder, carries
  the `obj_` scoring subject, preserves upstream rows, pages honestly, and fails
  instead of serving a partial source.
- Add `credential_sensitivity` to EA-0023 `ExposureImpactKind` while retaining
  `data_sensitivity` as the omitted-kind default. No DDL migration: the context
  is already JSONB. Prove existing DSPM/default scoring and derivations are
  unchanged.
- Supply an evidence-backed
  `ExposureImpactContext(kind="credential_sensitivity")`; absent/unknown context
  cannot reduce EA-0023 scoring, and the exact semantic kind is replay-pinned.
  Unknown reachability remains pending.
- Real EA-0010 compliance delegation and evidence-backed, non-automatic
  findings for EA-0013. No new `SignalKind`.
- Finding-driven rotation/revocation playbook proposed with
  `requires_approval=True` and `source_finding=finding`. Drive the real EA-0008
  engine through approval and prove execution is refused by eligibility `none`;
  handler/mutation spies remain empty. Load the finding first and refuse when
  its tenant does not match the explicit request tenant.
- ECR-0034 is not deepened: no capped EA-0025 inventory report is presented as
  exhaustive.

**Acceptance:** AC-8 through AC-12.

## W5 - Service, events, and both factory runtimes

**Spec:** sections 7 FR-13/16, 10, 11.

**Deliverables:**

- `SecretsIntelligenceService` (`AQService`, name `secrets_engine`) with health
  reflecting config and required owner-read availability.
- Mode-aware `_health_tenant()` for every tenant-scoped probe.
- Exactly four owned events via `register_crypto_events`; payloads are
  fingerprint/reference only.
- Factory wiring at both sites using real owner engines and local imports under
  `TYPE_CHECKING`/in-function runtime import discipline.
- Parameterize the Cartesian product `(backend, tenant_mode)`:
  memory/local, memory/enterprise, Postgres/local, Postgres/enterprise. Drive
  service lifecycle and real owner connectivity without suppressing unscoped
  reads.
- Isolated `import aqelyn.secrets`, `import aqelyn.kernel.factory`, isolated
  `pytest tests/secrets`, and full suite.

**Acceptance:** AC-17, AC-18.

## Review protocol

Review each ticket behaviorally, hardest checks first:

1. Construct nested adversarial inputs using value/sample/content/blob/token/
   password/private-key **field-name** aliases. Every attempt is refused under
   normal Python and `python -O`; no rejected value appears in logs/errors/events.
   Also prove that the legitimate typed value `SecretKind="private_key"` is
   accepted.
2. Build healthy/missing/tampered/retriable evidence controls. Losing evidence
   must never improve posture or permit an owner write.
3. Exercise every lifecycle attribute's unknown state and every assessment
   coverage state. Pending-with-results and known-without-evidence must be
   unconstructible.
4. Verify authenticity through the typed adapter. EA-0004 integrity alone must
   never produce `authenticity=valid`.
5. Drive EA-0025, EA-0023, EA-0010, EA-0013, and EA-0008 as real receiving
   owners, not only spies. A spy proves a call happened; it does not prove the
   receiver can act on the payload. For EA-0023, prove explicit
   `credential_sensitivity` replay and unchanged omitted-kind DSPM behavior.
6. Prove finding-tenant validation and `source_finding` binding against real
   Workflow execution after an approval. Nothing rotates, revokes, or reissues.
7. Hammer D8 pagination adversarially on both stores; use a repeated-cursor
   source and a work-budget exhaustion case.
8. Drive all four backend/tenant-mode factory combinations. Do not treat default
   local mode as enterprise evidence.
9. Keep ECR-0034 visible and unresolved; C-029 must neither silently depend on
   the capped denominator nor claim to fix it.

Merge each ticket only after its named acceptance slice and standard repository
gates are green. W5 green completes EA-0032.
