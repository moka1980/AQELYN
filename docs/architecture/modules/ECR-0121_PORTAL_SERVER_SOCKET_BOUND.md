# ECR-0121 — The portal's HTTP server bounds the upload at the socket

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable (out until Saturday).
**Date:** 2026-08-07
**Number:** verified free at `fbe314e` (main tip after ECR-0120, PR #323).

> ⚠️ Twenty-second consecutive ECR by one actor. §5 lists what independent review should attack.
> Post-arc completion work. claude.ai (spec author) named the at-socket bound as load-bearing, not
> a refinement — "the actual property `size ≤ 1 MiB` was supposed to buy."

## 1. Finding of record

ECR-0118 enforced the 1 MiB upload bound inside `PortalApplication.handle`, i.e. **after the whole
body was already in memory**, and the portal had no HTTP server of its own (tests drove `handle()`
directly). Against a customer who turns hostile — invite-only is not a serious barrier — that is an
authenticated **memory-exhaustion DoS** on a 4 GB box: declare or stream a multi-gigabyte body and
the process buffers it before the 413 ever fires. The bound has to live at the socket.

## 2. Decision

A `PortalServer` (asyncio, loopback, no host knob — nginx is the public face and proxies here, as
the deployed platform does) that reads the request head, then:

- parses `Content-Length`, and if it exceeds `MAX_REQUEST_BODY` (= the app's 1 MiB bound), returns
  **413 before reading a single byte of the body**;
- otherwise reads **exactly** `Content-Length` bytes (already known ≤ the bound), so a lying or
  absent length cannot make the process buffer more than the cap;
- then calls `PortalApplication.handle(method, target, headers, body)`.

The application's own `len(body)` check stays as defence in depth. The head is size-capped too
(431), and incomplete/timed-out requests get 408. `Connection: close` per request (no keep-alive to
reason about).

## 3. The property under test, over a real socket

The server tests open an actual loopback connection and speak raw HTTP.
`test_oversized_content_length_is_refused_before_the_body` is the load-bearing one: it declares a
100 MiB `Content-Length`, sends **two** body bytes, and asserts a prompt 413 — which can only happen
if the server refused on the length alone and never waited for the declared body. A boundary test
declares exactly `MAX + 1`. A normal small request routes through to `handle` (a 401 from the app,
proving end-to-end dispatch).

## 4. Acceptance — 3 mutations, all red

Harness `~/AQELYN_ECR0121_PREP/matrix.sh`. Wrong threshold (`> 0`, so any body is refused → the
normal login request goes red); oversized not surfaced as 413 (the refusal returns 200 → both
oversized tests red); and the at-socket guard removed entirely (`if False` → the server waits for a
body that never arrives and the before-body test times out — proving the guard is what makes the
refusal happen *before* the read).

ruff + `mypy --strict` clean; full suite on live Postgres. Carried matrix rises to **126**.

## 5. What review should attack

1. **`Transfer-Encoding: chunked` is not parsed** — a chunked body is treated as no
   `Content-Length` (body empty), so it cannot exhaust memory, but a chunked *upload* would silently
   read as empty and be refused downstream as malformed. nginx in front normalizes to
   `Content-Length`; a direct client using chunked gets a confusing 422, not a clear 400. Named.
2. **The read cap equals the declared length**, which the guard has already bounded to ≤ 1 MiB — so
   a client that declares 1 MiB and streams 1 MiB is fine, and one that declares ≤ 1 MiB but streams
   *more* has the extra ignored (readexactly reads exactly the declared count). That is correct, but
   worth confirming there is no path that reads past the declared length.
3. **No per-connection or per-IP rate limit here** — still nginx's job (`limit_req`); this ECR
   bounds a single request's body, not the request rate.
4. **The server is not yet wired into the deployment.** This is repo code with socket-level tests;
   standing it up (replacing the untested :8800 script) is the owner-gated deploy step.
5. **The ECR-0088 network-boundary guard was widened, not weakened.** It asserted the surface was
   the *only* inbound listener in `src`; it now allows exactly two — `surface/` and
   `portal/server.py` — and still flags a listener anywhere else, and a new positive test asserts
   the portal listener is loopback with no host knob (mirroring the surface). A reviewer should
   confirm the allow-list is those two files and nothing broader.

## 6. Scope

New `src/aqelyn/portal/server.py` and `tests/portal/test_server.py`; `PortalServer` exported from
`portal/__init__.py`. The ECR-0088 boundary guard (`tests/guarantees/surface_network_guard.py` +
`test_surface_network_boundary.py`) is updated to a named two-entry listener allow-list and a portal
loopback check. No change to the application logic, the stores, or any other domain — this adds the
transport that makes the upload bound real, without deploying it.
