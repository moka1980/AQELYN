# C-032 IS-035 Conformance & Credential Governance Score — Implementation Task Bundle

**Milestone:** C-032 (IS-035 conformance; **additive enhancement to EA-0032 — not a new module**)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-031 merged & green; **`IS-035_Conformance_Analysis.md` read**; **ECR-0054** decided by the owner; `SPEC_AUTHOR_NOTES.md` Part 1 rules 1–18 read; **`src/aqelyn/secrets/` (EA-0032) and `src/aqelyn/ispm/scoring.py` (EA-0033) read before writing code.**
**Definition of Done:** tests pass on in-memory **and** Postgres **and both tenant modes**, under normal Python **and `python -O`**; `ruff` clean; **`mypy --strict src tests`**; worktree `pytest` with `PYTHONPATH=$PWD/src`; **`gh pr checks <n>` confirmed PASS before every merge**; **no new package, service, secrets store, crypto model, duplicate prefix, or event namespace**; `make check` green; Claude Code sign-off per ticket.

**Read `IS-035_Conformance_Analysis.md` first.** IS-035 **renames EA-0032**.
Secrets, keys, certificates, tri-state lifecycle, rotation proposals, exposure,
compliance, findings, and the **value-free no-plaintext guarantee** all ship today
in `src/aqelyn/secrets/`. Only the words `renewal` and `kms` are new.

> **All work lands in `src/aqelyn/secrets/`.** If this milestone produces
> `src/aqelyn/secrets2/`, `credential_governance/`, a second secrets store or
> crypto object model, a duplicate `sct`/`cky`/`x509` prefix, a second
> `*_engine` service, or a renamed event namespace — the reconciliation has gone
> wrong. Stop and raise an ECR.

**Do not re-implement the no-plaintext guarantee.** It is already structural
(`_ValueFreeModel`, `extra="forbid"`), proven under `python -O`. Reuse it.

**Do not build the archive's lifecycle state machines** (`Requested→Approved→…→
Archived`, 13 states). EA-0032's tri-state lifecycle *fields* are the shipped
reality and are sufficient; a state-machine engine or transition-event store would
create a second lifecycle authority for crypto assets — the exact failure ECR-0053
rejected for identities.

**Verification standard:** owner **spies prove delegation**, then **real-engine
round trips prove the capability**. The score in particular is driven against the
**real scorer**, never a spy (ECR-0007).

## Target changes — EA-0032 only

```
src/aqelyn/secrets/
├── models.py     # + CredentialGovernanceScore (+ GovernanceFactor) — NEW prefix, verify
│                 #   collision-free against PREFIXES (sct/cky/x509/cas are TAKEN) (J2)
│                 # + optional: SecretLocation approved-vs-unsafe classification (J3)
│                 # + optional: evidence-backed owner claim (J4)
├── scoring.py    # NEW file: compose -> EA-0020 Derivation -> 0-100 (J2)
├── store.py      # + put_score, rejecting unreplayable (J2)
├── memory.py / postgres.py   # + score persistence; rule 9 — check the target table's
│                 #   shape before calling any field additive (columnar vs jsonb)
├── engine.py     # + score_credential(); wire into existing assess()
└── service.py    # additive method + ONE additive aqelyn.crypto.* event. NO new service.
tests/secrets/    # + test_crypto_gov_* cases
```

**No new directories. No new service registration.**

---

## J1 — Conformance verification (real engines, not grep)

**Source:** `IS-035_Conformance_Analysis.md` §2.
**Deliverables:** for every row of the ownership table, point to shipped code and a
green test — then prove the capability is *actually exercisable*: ingest a secret,
a key, and a certificate through the **real** `SecretsIntelligenceEngine`; run the
**real** `assess_key`/`assess_certificate` and show tri-state lifecycle results;
run the **real** `analyze_exposure` and `propose_rotation`. Confirm the value-free
guarantee holds under `python -O`. Any row that fails becomes a ticket here —
**not** a reason to build a module.
**Acceptance:** `test_crypto_conformance_lifecycle`,
`test_crypto_conformance_exposure_and_proposal`,
`test_crypto_conformance_value_free_dash_o`.

## J2 — Deterministic per-credential governance score (the one real gap)

**Source:** analysis §3.1. EA-0032 has **no** per-asset score today —
`CryptoAssessment` carries counts.
**Deliverables:** `score_credential(asset_id, *, tenant_id) -> CredentialGovernanceScore`
composing **EA-0032 lifecycle + EA-0025 ownership + EA-0023 exposure + EA-0006
trust + EA-0007 mission + EA-0010 compliance** into a replayable **EA-0020
`Derivation`**, 0–100. Follow **EA-0033's `scoring.py` shape** — read it first.

**Non-negotiables (the ISPM rules, exactly):**
- **No second scorer** — compose EA-0013 risk / EA-0007 / EA-0006.
- **`known_only × coverage_adjustment`** — unknown factors are excluded from the
  denominator **and** low coverage adjusts the result down. Denominator exclusion
  alone lets one known-good factor plus nine unknowns score like ten known-good
  factors, i.e. **"unknown" becomes "present"** (rules 4/5, ECR-0040).
- **Replay-or-reject** — `put_score` rejects a score whose derivation does not
  replay; driven against the **real scorer**.
- **(a) Exposure is not averaged away** — an **active critical exposure** is
  carried as an **unsuppressable flag** on the score record and named in
  `statement`; a known-exposed credential SHALL NOT present as well-governed
  (EA-0022 S5 discipline).
- **(b) "Well-governed" ≠ "safe"** — `statement` SHALL say the score measures
  **governance hygiene**, not compromise state.
- **New prefix**, verified collision-free against `PREFIXES` (`sct`/`cky`/`x509`/
  `cas` are taken), registered in **both** `conventions/ids.py::PREFIXES` and
  CONVENTIONS §1; new errors in `errors.py` + CONVENTIONS §9.
- **One additive event** in EA-0032's own namespace (e.g.
  `aqelyn.crypto.governance_scored`); **re-emit nothing**.
- **Rule 9:** check the target table's shape before treating the score as an
  additive field.

**Depends on:** J1.
**Acceptance:** `test_crypto_gov_score_replay`,
`test_crypto_gov_score_composed_not_rescored`,
`test_crypto_gov_unknown_three_way` *(same subject with the factor **known-good**,
**known-bad**, and **unknown** → three distinguishable results; **unknown must not
be the favourable one**)*,
`test_crypto_gov_coverage_adjustment`,
`test_crypto_gov_exposure_not_averaged_away`,
`test_crypto_gov_statement_says_governance_not_safety`,
`test_crypto_gov_prefix_collision_free`,
`test_crypto_gov_store_contract[inmemory]` / `[postgres]`.

## J3 — Storage-safety classification *(owner-gated — build only if approved)*

**Source:** analysis §3.2. `SecretLocation` has kinds but no approved-vs-unsafe
classification.
**Deliverables:** a **metadata-only** signal — approved vault/KMS/HSM vs unsafe
location — feeding J2's score as a factor. **Never store or infer the secret**;
unclassifiable location → `unknown`, **never** "approved" (rules 4/5).
**Depends on:** J2.
**Acceptance:** `test_crypto_location_classification`,
`test_crypto_location_unknown_not_approved`.

## J4 — Credential ownership handoff to EA-0025 *(owner-gated — build only if approved)*

**Source:** analysis §3.3; the **C-031 H2** pattern applied to crypto assets.
**Deliverables:** evidence-backed owner claim → **real EA-0025
`Ownership`/`reconcile`/`ownership`**; conflicts by EA-0006 reliability, recorded;
ties `unknown`. **Rule 17:** pin owner refs at computation time; never recompute
from today's estate.
**Depends on:** J2.
**Acceptance:** `test_crypto_owner_roundtrip_ea0025`,
`test_crypto_owner_conflict_reliability`.

## Explicitly out of scope

- A **new package or service** (`secrets2`, `credential_governance`,
  `*_engine`), a second **secrets store**, **crypto object model**, or
  **event namespace**; duplicate `sct`/`cky`/`x509` prefixes.
- **Lifecycle state machines / transition-event stores** (analysis §4).
- **Connectors.** The provider list (Vault/CyberArk/Azure Key Vault/AWS Secrets
  Manager/KMS/PKI/HSM) is the EA-0031/EA-0034 trap — handed-in descriptors only;
  no credential held, nothing polled, nothing scheduled (rule 13).
- **Any direct action.** Rotation/revocation stays EA-0032's `propose_rotation`.
- **Re-implementing value-safety** — already structural; reuse `_ValueFreeModel`.

---

## Review protocol (Claude Code)

1. **No second secrets engine.** No new package, service, store, crypto model,
   duplicate prefix, or event namespace; everything lands in
   `src/aqelyn/secrets/`. **The hardest check of the milestone.**
2. **Conformance with real engines** (J1) — lifecycle, exposure, and proposal
   exercised through the real `SecretsIntelligenceEngine`, not spies.
3. **Score obeys the ISPM rules** — drive the **real scorer**: assert the
   **three-way** known-good / known-bad / **unknown** contrast and that **unknown
   is not the favourable result**; assert `known_only × coverage_adjustment` (nine
   unknowns must not score like nine known-goods); assert replay-or-reject, and
   that a tampered derivation is **withheld**, not caveated. Under `python -O` too.
4. **Exposure not averaged away** — a credential with an active critical exposure
   and otherwise perfect governance must **not** present as well-governed; the flag
   is unsuppressable and named in `statement`.
5. **"Well-governed" ≠ "safe"** — the statement says what the number measures.
6. **No second scorer** — composition traces to EA-0013/EA-0007/EA-0006;
   delegation spies plus real-owner reads.
7. **Value-free intact** — no plaintext field anywhere, under `python -O`;
   `_ValueFreeModel` reused, not reimplemented.
8. **No-action boundary against the *owning* contract** (rule 16). For EA-0032
   that is eligibility-**`none`** — a **structural execute-block**, *not* EA-0011's
   `assisted`. Prove the **exact applicable** boundary against the real workflow;
   do not import ISPM's assisted-path assertions.
9. **Prefix/error registration at both sites**; one additive event; nothing
   re-emitted.
10. **Rule 18 sweep** — if any Protocol changed, every implementer **including
    test doubles** is updated, and `mypy --strict src tests` is green (not `src`
    alone).
11. **ECR-0034 not weakened** — any EA-0025-backed read keeps coverage honest;
    no claim that the first 10 000 assets are the whole estate.

**Preserve, do not absorb:** ECR-0032 (shared posture base — still Proposed at
four instances), ECR-0034 (inventory cap), EA-0018 unclamped-duration flake,
EA-0027/EA-0018 enterprise health probes, EA-0013 equal-timestamp tie-breaker.

Merge only on green review with `gh pr checks` confirmed; then **report back to
the owner** before IS-036.
