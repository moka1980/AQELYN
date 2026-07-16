# C-020 Threat Exposure & Attack Surface Management - Implementation Task Bundle

**Milestone:** C-020 (Threat Exposure & Attack Surface Management, EA-0023)
**For:** Codex (implementer) / Claude Code (reviewer)
**Prerequisites:** EA-0022 merged & green; EA-0023 spec **Accepted**; **EA-0023 section 0.1 and section 1 read first**; CONVENTIONS + EA-0004/0005/0006/0007/0008/0009/0011/0012/0013/0019/0020/0021 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres where a backing store is required; `ruff` clean; `mypy --strict` clean; **no scan/probe/connect/network surface**; unknown reachability remains `unknown` + flagged; no duplicated path/trend/score/identity engines; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0023 section 0.1 first.** This module is not a scanner. It derives exposure
from data AQELYN already holds. A port scan touches a target and is therefore an
EA-0008 `scan.active` gated action for a future connector, not a method here. If
a needed behavior is not in the spec, raise an ECR.

**Verification standard (ECR-0007):** invariants are structural and behavioural.
For this module that means no public scan/probe/connect method exists, and a
network spy proves zero outbound attempts. Do not substitute a grep for the
proof.

## Target source layout

```
src/aqelyn/exposure/
|-- __init__.py       # exports engine, service, stores, types, register_exposure_events
|-- models.py         # AssetRef, ExposureBasis, ExposureRecord, AttackSurfaceAsset,
|                     #   ReachablePath, ExposureConfig (E1)
|-- engine.py         # derive/analyze, paths/identity/trend delegation, score, raise (E2-E4)
|-- store.py          # ExposureStore protocol + validators (E2)
|-- memory.py         # in-memory ExposureStore (E2)
|-- postgres.py       # Postgres ExposureStore + DDL (E2)
`-- service.py        # ExposureManagementService(AQService) + register_exposure_events (E5)
tests/exposure/       # acceptance suite (in-memory + Postgres)
```

---

## E1 - Types, config, taxonomy & no-scan surface

**Spec:** section 0.1, section 1 (S1/S2/S3), section 5, section 8 FR-1/2/3/12, section 10.
**Deliverables:** exposure models and validation; `Reachability` with
`unknown`; `ExposureConfig`; error codes (`ExposureConfigInvalid`,
`ExposureBasisMissing`, `ExposureNotFound`, `ExposureNotReplayable`,
`ScanNotPermitted`) in `conventions.errors` + CONVENTIONS section 9. No public
`scan`/`probe`/`connect` API or socket/network dependency. Active scanning is
represented only as a refused/gated `scan.active` ActionSpec handoff concept,
not execution.
**Depends on:** CONVENTIONS, EA-0020 `Derivation` types, EA-0004 evidence refs.
**Acceptance:** `test_exp_no_scan_surface`, `test_exp_no_network`,
`test_exp_unknown_not_internal`, `test_exp_basis_required`,
`test_exp_active_scan_is_actionspec`.

## E2 - ExposureStore + known-data derivation

**Spec:** section 6, section 7 derive/analyze, FR-2/3/11/13, NFR-2.
**Deliverables:** `ExposureStore` protocol, in-memory + Postgres stores and DDL;
contract suite; tenant scoping; append-only exposure history; `derive_surface`
and `analyze_exposure` over handed-in/known inventory inputs only. Inconclusive
reachability yields `unknown` + `flagged=True`; source failure records/returns an
unknown flagged result rather than fabricating a fallback.
**Depends on:** E1.
**Acceptance:** `test_exp_store_contract[inmemory]`,
`test_exp_store_contract[postgres]`, `test_exp_unknown_not_internal`,
`test_exp_failure_not_faked`.

## E3 - Reuse delegations: KG paths, IAG identity, Forecast trends

**Spec:** section 1 (S4/S5/S6), section 7 paths/identity/trend, FR-4/5/7, NFR-3.
**Deliverables:** `reachable_paths` delegates to EA-0005 `paths()` with
`max_work`; identity exposure cites EA-0011 results as basis and derives no
entitlement verdict; exposure trend delegates to EA-0021 and implements no
second trend model. No traversal, identity-risk, or trend logic is duplicated.
**Depends on:** E2.
**Acceptance:** `test_exp_paths_delegate_kg`, `test_exp_identity_cites_iag`,
`test_exp_trend_delegates_forecast`.

## E4 - Score, findings path, advisory-only behaviour

**Spec:** section 1 (S3/S6/S7/S8/S9), section 7 analyze/score/raise, FR-6/8/9/10/11.
**Deliverables:** `score` composes EA-0007 mission, EA-0006 trust/confidence,
and EA-0013 risk into a replayable EA-0020 `Derivation`; replay mismatch is
rejected/withheld; material exposure raises an EA-0013-consumable `Finding`
through the shipped findings path; no new `SignalRef` kind; remediation is only
a proposed EA-0008 path and the engine never acts.
**Depends on:** E3.
**Acceptance:** `test_exp_score_replayable`, `test_exp_score_replay_mismatch`,
`test_exp_raise_finding_path`, `test_exp_confidence_from_trust`,
`test_exp_advisory_only`, `test_exp_failure_not_faked`.

## E5 - Service + events

**Spec:** FR-14, section 11.
**Deliverables:** `ExposureManagementService` (`AQService`, name
`"exposure_engine"`) + `register_exposure_events`; in-memory and Postgres
kernel-factory wiring using the established `TYPE_CHECKING` + in-function import
pattern; health reflects owner-read availability + config validity.
**Depends on:** E4.
**Acceptance:** `test_exp_service_health`.

---

## Review protocol (Claude Code) - do not turn exposure into scanning

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **No probing.** There is no public scan/probe/connect method, and the network
   spy shows zero outbound attempts. This is behavioural proof, not a grep.
2. **Unknown is honest.** Unmatched reachability becomes `unknown` + flagged,
   never `internal` or safe by default.
3. **Reuse, not rebuild.** Paths delegate to EA-0005; identity cites EA-0011;
   trends delegate to EA-0021; scoring composes EA-0007 x EA-0006 with risk.
4. **Findings path only.** Material exposures flow through the existing
   `FindingStore`; do not churn EA-0013 with a new `SignalRef` kind.
5. **Advisory only.** The engine does not remediate or execute; any response is
   a proposed, gated EA-0008 run.
6. **Failure looks failed.** Analysis failure is unknown/flagged; re-score
   failure is stale/unavailable, not a fabricated fallback or silent old score.
7. **Service import discipline.** The final ticket must avoid the R5/T5 circular
   import trap: `TYPE_CHECKING` imports plus in-function runtime imports.

Merge only on green review; then **report back to the owner** before the next
module.
