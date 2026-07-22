# IS-035 Conformance Analysis — realized by the shipped EA-0032

**Subject:** IS-035 — Secrets, Keys & Certificate Lifecycle Governance Engine
**Finding:** **IS-035 renames EA-0032's shipped capability.** Secrets, keys,
certificates, their lifecycle, rotation proposals, exposure, compliance, findings,
and the value-free no-plaintext guarantee are all implemented, merged, and green
as **EA-0032 (C-029, `src/aqelyn/secrets/`)**.
**Recommendation:** do **not** build an EA-0035 module. Mark IS-035 **conformant
via EA-0032**, and realize only the genuine remainder as **additive, owner-scoped
enhancements inside `src/aqelyn/secrets/`** (**C-032**).
**Change control:** **ECR-0054** *(next free per the reviewer's handover — the log
ends at ECR-0053; re-read `ECR-LOG.md` before assigning, rule 1).*
**Status:** Proposed — owner decision.

---

## 1. The evidence

ECR-0015 check, run by the reviewer against shipped `src/`:

```
secret_asset / cryptographic_key / x509_certificate object types : 5 each  (EA-0032 owns)
rotation 28 · revocation 19 · expiry 17 · propose_rotation 3              (EA-0032 lifecycle)
sct / cky / x509 prefixes : 8 each · cas                                  (EA-0032 PREFIXES)
secrets_engine 16 · aqelyn.crypto.* 4 events                              (EA-0032 service/events)
renewal 0 · kms 0 · certificate.*lifecycle 0                             <- net-new VOCABULARY only
```

**Only the vocabulary is new.** `renewal` and `kms` are words EA-0032 doesn't use;
they are not capabilities it lacks. Everything the archive asks for — object
model, lifecycle, rotation, exposure, compliance, findings, value-safety — has an
owner, and it is the same owner in every row.

This is the **third distributed-conformance case** (IS-026 → EA-0012;
IS-034 → EA-0033/0011/0025/0032; now IS-035 → EA-0032) — though unlike IS-034 this
one is **concentrated**: a single owner duplicates the whole thing, which makes it
the easiest of the three to see and the most wasteful to miss.

## 2. What EA-0032 already owns — route/reuse, never re-derive

Verified present in shipped `src/aqelyn/secrets/`:

| Archive capability | Shipped seam |
|---|---|
| secret/key/cert ingestion (handed-in, value-free) | `SecretsIntelligenceEngine.ingest_secrets`, `ingest_crypto_assets` |
| lifecycle: expiry / strength / rotation / chain / revocation | `assess_key`, `assess_certificate`, `assess` — **tri-state `valid\|invalid\|unknown`** |
| certificate verification | two-stage: EA-0004 integrity **≠** authenticity (ECR-0039/0046) |
| exposure | `analyze_exposure` — EA-0023 seam, `credential_sensitivity` (ECR-0044) |
| rotation / revocation action | `propose_rotation` — EA-0008 gated, `source_finding`-bound, **never executes** |
| object types / prefixes | `secret_asset`/`cryptographic_key`/`x509_certificate`; `sct`/`cky`/`x509`/`cas` |
| **"no plaintext" guarantee** | **already structural** — `_ValueFreeModel`, `extra="forbid"`, no raw-value field |

The master's headline safety requirement — *no plaintext secret ever stored* — is
**not a gap to close.** It is a shipped structural guarantee, proven under
`python -O`. Re-implementing it would weaken it.

## 3. The genuine remainder

### 3.1 A deterministic per-credential governance score (the one real gap)

Verified: **EA-0032 has no per-asset score.** `CryptoAssessment` carries *counts*,
not a score. "Which credentials are worst-governed right now?" is currently
unanswerable.

The correct realization is **the EA-0033 ISPM posture-score pattern applied to
crypto** — composing EA-0032 lifecycle + EA-0025 ownership + EA-0023 exposure +
EA-0006 trust + EA-0007 mission + EA-0010 compliance into a replayable **EA-0020
`Derivation`**, under the ISPM rules exactly:

- **No second scorer** — compose EA-0013 risk / EA-0007 mission / EA-0006 trust.
- **Unknown excluded from the denominator and never favourable** — the
  `known_only × coverage_adjustment` shape that ISPM-G4 landed on. Denominator
  exclusion *alone* is insufficient: without the coverage adjustment, a credential
  with one known-good factor and nine unknowns scores like one with ten known-good
  factors — i.e. **"unknown" silently becomes "present"** (rules 4/5, ECR-0040).
- **Replayable or unrepresentable** — a score whose derivation does not replay is
  rejected at `put`, proven against the **real scorer**, not a spy (ECR-0007).

**Two hazards the archive does not name, and this analysis adds:**

- **(a) A score must not average away a known exposure.** A credential with
  perfect ownership, rotation, and compliance but an **active critical exposure**
  must not surface as well-governed. Exposure participates as a factor *and* an
  active exposure is carried as an **unsuppressable flag** on the score record,
  named in the `statement`. This is EA-0022 S5's discipline — *no green aggregate
  over an unreported fire* — applied one layer down.
- **(b) "Well-governed" is not "safe".** The score measures **governance
  hygiene**, not compromise state: a perfectly rotated, owned, compliant
  credential that has leaked is still compromised. The `statement` and any UI
  consumer SHALL say what the number measures, so a high score is never read as an
  all-clear. (The plain-language-honesty discipline of EA-0021 S4.)

### 3.2 Storage-safety governance (owner's call)

EA-0032's `SecretLocation` has kinds (`repository`/`configuration`/
`vault_reference`/`runtime_reference`/`other`) but **no approved-vs-unsafe
classification**. A **metadata-only** signal — *"is this held in an approved
vault/KMS/HSM, or somewhere unsafe?"* — is a narrow, value-free addition. **Never
store or infer the secret itself.**

### 3.3 Credential ownership handoff to EA-0025 (owner's call)

The C-031 H2 pattern applied to crypto assets: evidence-backed owner claim →
real EA-0025 `Ownership`/`reconcile`, evidence-pinned, missing = `unknown`.

## 4. What to resist

The archive's rich **lifecycle state machines**
(`Requested→Approved→…→Archived`, `Requested→Validated→Issued→…→Archived`).
EA-0032's shipped reality is **tri-state lifecycle fields** (`valid|invalid|
unknown`), which is sufficient for every governance question the master actually
poses. A 13-state credential state machine plus a transition-event store is
**archive over-specification** — it would add a second lifecycle authority for
crypto assets (the exact failure ECR-0053 rejected for identities) without a
proven gap. Build it only if a specific governance need is demonstrated against
shipped code.

## 5. Why building EA-0035 anyway is harmful

Literal construction produces: a **second secrets store**, a **second crypto
object model**, **duplicate lifecycle logic**, **duplicate `sct`/`cky`/`x509`
prefixes**, a **second `secrets_engine` service**, and a **renamed
`aqelyn.crypto.*` namespace** — doubling every credential finding and inflating
downstream counts in EA-0013 and EA-0022.

Worse than the identity case: **two engines disagreeing about whether a
certificate is expired or a key is revoked is an outage or a breach**, and the
value-free guarantee would exist in two places, only one of which was proven.

## 6. Recommendation

1. **Mark IS-035 conformant via EA-0032** (this document is the evidence, verified
   against shipped code at C-032 J1 with **real-engine** round trips).
2. **Realize §3.1 (the governance score) as an additive enhancement inside
   `src/aqelyn/secrets/`**; treat §3.2 and §3.3 as **owner-gated options**.
3. **Forbid** a second secrets engine, store, crypto model, prefix, service, or
   event namespace (**ECR-0054**). A governance-score record needs a **new,
   collision-free prefix**; its event is additive within EA-0032's own
   `aqelyn.crypto.*` namespace and re-emits nothing.
4. **Do not build lifecycle state machines** (§4).

**Verification note.** Every row in §2 must be confirmed against **shipped code**
before conformance is accepted — spies prove delegation, only the real engine
proves the capability is actually there (the IS-034 discipline).
