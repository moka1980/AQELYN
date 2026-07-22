# C-031 Machine Identity / NHI Conformance Enhancements - Implementation Task Bundle

**Milestone:** C-031 (IS-034 intent, realized through existing owners - **not a
new EA-0034 runtime module**)
**For:** Codex (implementer) / Claude Code (reviewer)
**Prerequisites:** EA-0033 merged and green;
`IS-034_Conformance_Analysis.md`, ECR-0053, ECR-0034, ECR-0039, ECR-0052, and
`SPEC_AUTHOR_NOTES.md` rules 1-18 read first.
**Definition of Done:** conformance proven against shipped code; owner
enhancements pass in-memory and Postgres where persistence is touched and both
tenant modes where a factory service is touched; `ruff` and format clean;
`mypy --strict src tests` clean; no new module/store/score/service/event
namespace; Claude Code sign-off per ticket.

> **Failure condition:** if this milestone creates
> `src/aqelyn/machine_identity/`, an `nhi_engine`, a second identity or
> lifecycle store, a second posture score, or an `aqelyn.nhi.*` namespace, stop.
> IS-034 is a distributed restatement under ECR-0053.

## H1 - Verify distributed conformance against shipped code

**Ref:** `IS-034_Conformance_Analysis.md`, ECR-0053, ECR-0015, ECR-0007.

**Deliverables:** verify every conformance row against shipped code, including
all supported non-human EA-0033 `IdentityKind` values, the real EA-0011 account
graph round trip, EA-0025 inventory ownership/lifecycle, EA-0032 crypto
lifecycle, EA-0002 relationships, EA-0005 traversal, and existing owner event
registries. Literal grep is recorded but is not the proof. Any failed row
becomes an owner-scoped C-031 repair; it never justifies a second module.

**Acceptance:** update the conformance record with commit-pinned evidence and
prove that no machine-identity package, service, store, score, or event
namespace exists. No `src/` change when every conforming row holds.

## H2 - Ownership handoff: EA-0033 descriptor to EA-0025 owner

**Ref:** archive FR-003; conformance remainder H2; EA-0025 `Ownership`,
`InventoryIntelligenceEngine.ingest/reconcile/ownership`; rules 6 and 17.

**Deliverables (existing `ispm/` and, only if the owner contract genuinely
requires it, `inventory/`):**

- Add a strict typed ownership claim to the handed-in identity descriptor. It
  carries owner refs, rationale, source, observation time, and EA-0004 evidence;
  it carries no provider payload or credential material.
- Verify every ownership claim before any EA-0002, EA-0025, or ISPM write.
  Missing evidence raises `EvidenceNotFound`; failed integrity raises
  `EvidenceTampered`; a retriable evidence-store outage remains distinguishable.
- Route the claim through the real EA-0025 inventory report and pin the exact
  inventory/evidence refs used by the normalized identity. Do not copy EA-0025's
  reconciliation into ISPM.
- Prove conflicting owner claims are resolved by EA-0006 reliability and
  recorded by EA-0025; equal-reliability disagreement remains unresolved and
  visible. Missing ownership remains unknown and cannot improve posture.

**Acceptance:** `test_nhi_ownership_real_inventory_round_trip`,
`test_nhi_ownership_conflict_uses_trust`,
`test_nhi_ownership_evidence_failure_writes_nothing`, and store round-trip tests
on both backends. Use a healthy/missing/tampered three-way evidence table.

## H3 - Value-free identity-to-credential/workload bindings

**Ref:** archive section 13 relationship vocabulary; conformance remainder H3;
EA-0032 crypto object types; EA-0002 `ObjectStore.relate`; EA-0005 traversal;
ECR-0039; rules 6, 8, 13, 14, and 18.

**Deliverables (existing `ispm/`, reusing EA-0032 and graph owners):**

- Add a strict binding descriptor for a supplied identity/account to a typed
  EA-0002 target. Crypto targets are EA-0032's real `secret_asset`,
  `cryptographic_key`, or `x509_certificate` objects; workload targets must
  already exist. The descriptor is value-free and rejects unknown relation or
  target types, cross-tenant targets, and duplicate claims.
- Verify the binding evidence and derive claim confidence through EA-0006 before
  writing. EA-0004 integrity alone must never become authenticity. If an
  authenticity claim is needed, use a typed owner verifier or leave it unknown.
- Persist one evidence-backed EA-0002 relationship and retain its `rel_` id on
  the normalized identity. Traverse only through EA-0005 with explicit bounds;
  do not add local graph walking.
- A missing/tampered evidence record writes neither relation nor favourable
  control/posture state. A repeated ingest is idempotent on the relation.

**Acceptance:** `test_nhi_crypto_binding_real_owner_round_trip` (real EA-0032
object -> EA-0002 relation -> EA-0005 traversal),
`test_nhi_binding_no_secret_value`, `test_nhi_binding_integrity_not_authenticity`,
`test_nhi_binding_evidence_failure_writes_nothing`,
`test_nhi_binding_cross_tenant_refused`, and a Protocol-conformance gate for
every updated spy/adapter. A call-only spy is insufficient for the round trip.

## H4 - Lifecycle ownership map and narrow append-only remainder

**Ref:** archive sections 14/18; conformance remainder H4; EA-0025 S3 lifecycle;
EA-0032 crypto lifecycle; ECR-0014; ECR-0034.

**Deliverables (existing owner packages only):**

1. Encode and test the conformance analysis's lifecycle ownership table before
   adding storage. `provisioned/active/modified/archived/unreported` stay with
   EA-0025; credential rotation stays with EA-0032. Source silence maps only to
   EA-0025 `unreported`.
2. For lifecycle semantics that cannot be reconstructed from those owners,
   persist a narrow evidence-backed append-only identity lifecycle observation
   in EA-0033. It records source, evidence, actor where present, observation
   time, reason, and the routed owner state. It is not a state machine or a
   second lifecycle engine.
3. Explicit revoked evidence may route to EA-0025 decommission only through its
   existing evidence/attributed-decision gate. Suspended identities remain in
   inventory. Silence can never synthesize either state.
4. Register an additive `aqelyn.ispm.*` lifecycle event only if the
   identity-specific persisted transition cannot be represented by
   `aqelyn.inventory.lifecycle_changed`; credential events remain
   `aqelyn.crypto.*`. Never re-emit owner events under an NHI namespace.
5. Keep inventory coverage honest under unresolved ECR-0034. A bounded inventory
   read cannot be described as the complete machine-identity estate.

**Acceptance:** `test_nhi_lifecycle_owner_map`,
`test_nhi_lifecycle_active_revoked_silence_distinct`,
`test_nhi_source_silence_only_unreported`,
`test_nhi_revocation_requires_positive_evidence`,
`test_nhi_lifecycle_append_only[inmemory|postgres]`, and event ownership tests
if an event is added.

---

## Review protocol (Claude Code)

1. **No second module.** No machine-identity package, service, repository,
   score, lifecycle engine, or event namespace.
2. **Capabilities, not names.** H1 proves semantic ownership against shipped
   code; zero literal collisions are not evidence of net-new capability.
3. **Real owners after spies.** H2/H3 drive real EA-0025/EA-0032/EA-0002/EA-0005
   round trips. Spies prove dispatch only.
4. **Ownership is historical.** The handoff pins the inventory/evidence refs it
   used; later reads do not recompute against today's owner data.
5. **No synthetic trust.** EA-0004 integrity never establishes provider or
   workload authenticity; confidence comes from EA-0006.
6. **No values.** Construct forbidden nested value fields under normal Python
   and `python -O`, while legitimate key/certificate kinds remain constructible.
7. **Absence is not a favourable state.** Compare active, revoked/suspended,
   and source-silent cases; silence is unreported/unknown only.
8. **No action path.** Any remediation uses the owning finding and EA-0008
   proposal with `source_finding` bound; prove the applicable owner gate through
   the real workflow.
9. **Protocol doubles conform.** Run `mypy --strict src tests`; additive owner
   arguments/results are forwarded and asserted by every double (rule 18).
10. **Persistence and tenancy.** Both stores where touched, tenant isolation,
    append-only history, D8 pagination where a query is added, and both tenant
    modes for any factory/service change.
11. **ECR-0034 remains visible.** C-031 neither claims nor deepens an exhaustive
    inventory while the 10,000-row cap is unresolved.

Merge each ticket only on green behavioral review, then report back to the owner
before IS-035.
