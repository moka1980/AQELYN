# ECR-0106 — A posture subject becomes an asset

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `a9eeb07`.

> ⚠️ Seventh consecutive ECR by one actor. §5 lists what independent review should attack.

## 1. Finding of record

ECR-0100 left this comment in `observation_to_finding`, and it has been carried in every
review since:

> Charter section 5 requires Affected Assets, and `affected_object_ids` is where they belong
> — but it holds typed `obj_` ids, and a posture subject ("wcagvakt.no", "203.0.113.10") is
> not an object until something creates one. Minting an id here would satisfy the field with
> a reference that resolves to nothing, which is worse than leaving it empty.

The refusal was right. The debt was real. This pays it by creating the object.

**The gap was wider than the comment said.** `_ingest_posture` was already doing
`subject_id = new_id("obj")` and putting that id in the EvidenceRecord's `Subject`. So the
dangling reference the comment refused to write into the Finding was already being written
into the evidence — the exact thing ECR-0100 argued against, one field over. Reading my own
deferral carefully is what found it.

## 2. Decision

Identity lives in the subject, not in an id we happen to have minted:

- `subject_natural_key(observation)` → `NaturalKey("posture:{kind}", ref)`
- `subject_object(...)` builds an `AQObject` with **`id=""`**
- `_ingest_posture` calls `object_store.upsert(...)` and uses **the id the store returns**

`upsert` resolves by natural key, so the same host observed twice is one asset and a re-run
of the same collection updates rather than clones. The returned id goes to both the evidence
Subject and `affected_object_ids`, so nothing anywhere holds a reference the store cannot
resolve.

`ensure_posture_object_type` registers `posture.subject` on whatever store the runtime has.
Ingestion does not depend on some other module having registered it first.

Measured on the real self-scan of this machine: four observations, four findings, **one
asset**.

## 3. One deliberate refusal

**An empty `ref` is refused, not defaulted.** `subject_natural_key` raises rather than
returning a placeholder. A placeholder would silently merge every unidentifiable subject in
the estate into one asset called "unknown" — a wrong answer that looks like a working
feature. The document validator already requires a non-empty `ref`, so this is the second
lock on the same door, and it is there because the first one guards the document while this
one guards the identity.

## 4. Acceptance — 8 mutations, all red

Harness `~/AQELYN_ECR0106_PREP/matrix.sh`, run on a purged bytecode cache (ECR-0105).

The finding carrying no asset; **the ECR-0100 anti-pattern itself** — a freshly minted `obj_`
id in place of the store's — ; the kind dropped from the natural key so a host and a domain
with the same name collapse; the key built from `observation_id` so one host becomes many
assets; the object built with no natural key at all so every run clones it; an empty `ref`
given a placeholder instead of being refused; the object type never registered; and an
unlinked asset reworded as reassurance in the report.

**Necessity, measured rather than asserted.** Four deselection runs, all GREEN:

- M2 with the three id-witnesses deselected — nothing else in the suite can see a dangling link
- M6 with its sole catcher deselected
- M8 with its sole catcher deselected
- M3 with the kind witness and the natural-key shape witness deselected

The three id-witnesses are **correlated by construction** — they all assert through the same
returned id — so they are jointly necessary rather than individually so. Stated here because
reporting them as three independent witnesses would overstate the coverage.

12 tests. Ruff clean, `mypy --strict` clean, full suite on live Postgres. Carried matrix
stays at **84**, untouched.

## 5. What review should attack

1. **`posture.subject` is one object type for every kind of subject.** A host, a domain and
   a mail policy all become `posture.subject` with `kind` as an attribute. The estate's other
   engines use a type per kind (`identity`, `account`, `software_component`). This is the
   coarser choice and it is deliberate — a collector that learns a new subject kind should
   not need a schema change — but it means posture assets will not join those types without
   a merge.
2. **No relationship is created.** The object exists and the finding points at it; nothing
   relates the posture subject to any object another engine already knows about. The same
   host discovered by ISPM and by `aqelyn collect` will be two objects until something
   merges them. `ObjectStore.merge` exists and is not called.
3. **Tenant is `None` throughout**, because this path is `tenant_mode="local"`. Multi-tenant
   ingestion would need the tenant threaded into the natural-key lookup, and `upsert` already
   scopes by it — untested here because no caller supplies one.
4. **`_affected_assets` reads the subject ref out of `expert_details`**, which is a display
   structure, rather than off the resolved object. The renderer has no store. It means the
   name shown is the one the collector reported, not the one the asset settled on after a
   merge.

## 6. Scope

`src/aqelyn/reporting/posture.py` (natural key, object builder, type registration, and
`affected_object_ids` as a parameter), `src/aqelyn/reporting/analyze.py` (upsert before
evidence), `src/aqelyn/reporting/html.py` (`_affected_assets` and its CSS), and a new
`tests/reporting/test_posture_affected_assets.py`. No schema migration — `posture.subject` is
a registered object type, not a new table. No dependency, no loopback or GC change.
