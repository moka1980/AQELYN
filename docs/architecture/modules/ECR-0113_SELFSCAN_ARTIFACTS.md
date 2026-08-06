# ECR-0113 — The downloadable self-scan is the shipped collector, and stays that way

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `1d109bc`.

> ⚠️ Fourteenth consecutive ECR by one actor. §5 lists what independent review should attack.

## 1. Finding of record

The customer self-scan downloads went live at **aqelyn.com/scan** (Linux `.pyz`, Windows `.ps1`)
before this ECR — but built ad-hoc in a scratch directory, tracked nowhere, tested by nothing. A
change to `aqelyn.collect` would leave the hosted Linux download silently stale, and no test would
notice. For a security tool a customer runs on their own machine, "the download drifted from the
code we test" is exactly the failure that must not be possible.

## 2. Decision

The download is now **built from the shipped collector**, in the repo, under test.

- **`src/aqelyn/collect/selfscan.py`** — the one-shot runner (scan → `posture.json` + a
  self-contained `report.html` + console summary). Stdlib only, so the zipapp needs no deps. It
  wraps the same `read_host_facts` / `observations_for` the pipeline uses — no second implementation.
- **`tools/build_selfscan_pyz.py`** — assembles `aqelyn-selfscan.pyz` from `src/aqelyn/collect`, so
  the artifact cannot diverge from what the tests cover. Output is a build product; `dist/*.pyz` is
  gitignored and rebuilt at deploy time.
- **`tools/aqelyn-selfscan.ps1`** — the Windows collector, now version-controlled (it is source, not
  a build output). Built against a real Windows 11 machine's probe output and confirmed on that
  machine (the run produced exactly the predicted result: 12 public ports; firewall, BitLocker,
  Defender and RDP all clean).

The runner escapes every observation value into the report — the observations describe a real
machine and must never inject markup into the page that shows them.

## 3. Validated end to end, on real machines

- The repo-built `.pyz` runs and produces a valid `posture.json` (one that passes the platform's own
  `validate_posture_shape`) plus a report — asserted by a build-and-run test in a fresh process.
- The Windows `.ps1` was run on the owner's real Windows 11 laptop; output matched the prediction
  exactly. That is the ECR-0109/0110 discipline: built against real output, confirmed on the real
  machine, never against invented strings.

## 4. Acceptance — 3 mutations, all red

Harness `~/AQELYN_ECR0113_PREP/matrix.sh`, purged cache. Severity ordering removed; HTML escaping
dropped (injection); the build omitting `selfscan.py` so the zipapp cannot run. Seven tests,
including a subprocess build-and-run of the actual artifact. Ruff clean, `mypy --strict` clean
across 595 files, full suite on live Postgres. Carried matrix stays at **84**.

## 5. What review should attack

1. **The zipapp is not reproducible byte-for-byte** — `zipapp.create_archive` embeds file mtimes,
   so two builds differ. The *content* is reproducible; the SHA-256 on the download page is of a
   specific build and must be refreshed when the artifact is rebuilt (the deploy step does this).
2. **The Windows `.ps1` has no automated test** — it cannot run on the Linux CI host. It is tracked
   and was validated once by hand on a real machine; a change to it is only as safe as the next
   manual run. A Windows CI runner would close this.
3. **`report.html` is self-contained but unsigned** — a customer downloads and runs code; the page
   publishes a SHA-256 for the download, but there is no signature. Fine for now; named.
4. **The runner re-implements nothing but still duplicates the report's look** with the operator
   surface — two report styles now exist (this offline one and the platform's). They can drift in
   appearance, though not in the findings they show.

## 6. Scope

New `src/aqelyn/collect/selfscan.py`, `tools/build_selfscan_pyz.py`, `tools/aqelyn-selfscan.ps1`,
`tests/collect/test_selfscan.py`, and a `dist/*.pyz` gitignore. No change to the collector logic,
the pipeline, the schema, or any existing behaviour — this makes the already-shipped downloads
reproducible and tested.
