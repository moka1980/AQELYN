# ECR-0101 — The surface can start holding a collection

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `1861ee4`.

> ⚠️ **Written, implemented and merged by one actor.** ECR-0100 carries the same caveat and the
> same standing request: when independent review resumes, this is unreviewed code in a security
> platform. §5 lists what to attack.

## 1. Finding of record

ECR-0100 gave posture observations an ingestion path, but only into the *report*.
`analyze_collection` builds a throwaway in-memory runtime, renders HTML, and discards everything.

The operator surface is the other case: a long-lived kernel serving eight routes. It had no way to
be given anything. Starting it produced a working shell over an empty store — `/api/v1/findings`
returning `{"items": [], "returned": 0}` — and no shipped path could change that.

**A platform you cannot put data into cannot be looked at.** That is what the owner ran into when
they asked to see what AQELYN looks like.

## 2. Decision

`aqelyn surface --collection DIR` seeds the running kernel's finding store from a collection
directory before serving, using the same ingestion and the same refusals as the report path.

- **Opt-in.** With no `--collection`, behaviour is exactly as before. An unseeded surface stays
  the default.
- **Read once at startup, never re-read.** The surface is read-only over a kernel; a watcher that
  re-ingested on change would make the store mutate under a paging cursor.
- **A refused collection stops the surface** and exits 2. Serving an empty page after rejecting
  the input would read as *nothing found*, which is the opposite of what happened.
- **Seeding is idempotent.** ECR-0100's `dedup_key` derives from subject, check and observation
  id, so restarting against the same collection does not double every finding. That is now
  witnessed rather than assumed.

`ingest_posture_into(runtime, directory)` is the public entry point — the report path's ingestion,
against a caller's runtime instead of a throwaway one.

## 3. Result

Against the real collection on this machine:

```
$ python -m aqelyn surface --port 8765 --collection ~/aqelyn_collection
AQELYN surface: http://127.0.0.1:8765
Seeded 6 posture findings from /home/ubunto/aqelyn_collection

$ curl -s 'http://127.0.0.1:8765/api/v1/findings?limit=3'
returned: 3 | next_cursor: eyJpbm5lciI6IjQ0LjB8Zm5k…
  high    72.0  listening_sockets_public on 85.190.101.232
  medium  48.0  response_header_present on https://wcagvakt.no
  medium  44.0  response_header_set on https://wcagvakt.no
```

Keyset paging works over the seeded findings, which is the arc's own guarantee applied to real
data for the first time.

## 4. Acceptance — 6 mutations, all red

Harness `~/AQELYN_ECR0101_PREP/matrix.sh`.

| mutation | result |
|---|---|
| seeding short-circuited so nothing reaches the store | 🔴 RED (4 witnesses) |
| `dedup_key` made unique per call, so a restart doubles | 🔴 RED |
| ordering reversed | 🔴 RED |
| refusal swallowed instead of propagated | 🔴 RED |
| `--collection` given a default, so seeding stops being opt-in | 🔴 RED |
| `--collection` parsed as `str` instead of `Path` | 🔴 RED |

Seven tests. `ruff` clean, `mypy --strict` clean across 580 files, full suite on live Postgres.

**One mutation was a no-op on the first run.** `return () or await …` evaluates to the call,
because `()` is falsy — so it reported GREEN while changing nothing. Corrected to
`return () if True else await …`, which is 🔴 RED on four witnesses. Recorded because a
mutation that does not mutate is indistinguishable from a test that does not test.

## 5. What review should attack

1. **`cast(Any, ...)` on the finding reader in tests** hides the protocol. It silences mypy rather
   than satisfying it.
2. **Seeding happens after `kernel.start()` but before `server.start()`.** I chose that so a
   refusal fails before the port opens; the ordering is unreviewed.
3. **Only posture is seeded.** Vulnerability records are not, so a collection with real CVEs
   still surfaces nothing. That is a deliberate scope cut, not an oversight — and it is a gap.
4. **No test starts an actual server.** The tests seed a runtime and query the service the surface
   reads; the CLI wiring itself is covered only by argument-parsing tests.

## 6. Scope

Changed: `surface/cli.py` (argument, seeding, exit code), `reporting/analyze.py` (one public
wrapper). No schema, dependency, loopback or GC change. The listener still binds `127.0.0.1` and
the surface remains read-only. Carried matrix stays at **84**, untouched.
