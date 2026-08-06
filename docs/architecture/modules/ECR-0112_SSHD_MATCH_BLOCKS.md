# ECR-0112 — A Match block makes the answer conditional, not global

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `5525dda`.

> ⚠️ Thirteenth consecutive ECR by one actor. §5 lists what independent review should attack.

## 1. Finding of record

Carried from ECR-0110 §6.2 and ECR-0111 §6.2, both written against my own work:

> `Match` blocks are ignored. `Match Address ...` scopes directives to a subset of
> connections; this parser treats everything as global.

Named twice, and it is not cosmetic. `flatten_sshd_config` + first-wins read every directive
as if it were unconditional, so a `Match`-scoped `PasswordAuthentication yes` after a global
`no` was read as `no` — or as `yes`, depending on order. Either way the single global boolean
was a claim the config did not make.

## 2. Proven against a real sshd, not reasoned about

The precedent from ECR-0110 is that sshd semantics are settled by running sshd. `sshd -T -f`
on the live host:

```
PasswordAuthentication no
Match Address 0.0.0.0/0
    PasswordAuthentication yes
```

- `sshd -T` (no `-C`): `passwordauthentication no` — the connection-independent value.
- `sshd -T -C addr=10.1.2.3,...`: `passwordauthentication yes` — password auth **is on** for
  those connections.

So a global-only read reports `no` while every matching connection gets `yes`: **a false
all-clear on the finding that matters most.** And `Match all` was confirmed to return to
unconditional scope — `Match Address … {yes}` then `Match all {no}` reports `no` globally.

## 3. Decision

The collector cannot run `sshd -T -C` (needs root and a specific connection), so it does not
try to evaluate Match blocks. It does two honest things instead:

- **Global scope is read on its own.** `_directive_scopes` returns the first-wins value in
  unconditional scope — directives inside a `Match` other than `Match all` no longer leak into
  it. `Match all` returns to unconditional scope, matching sshd.
- **A Match-governed password directive is reported as conditional.**
  `match_scoped_password_paths` names which paths a Match block decides, the check surfaces
  *"a Match block sets … for some connections, so the effective answer depends on who is
  connecting; this was not fully measured,"* and a config whose **only** opening is inside a
  Match block still raises the finding rather than going silent.

This is the doctrine the module already states — unmeasured is its own state — applied to a
value that is partly measured: the global part is reported, the conditional part is flagged as
conditional, and neither is passed off as the other.

## 4. Acceptance — 6 mutations, all red

Harness `~/AQELYN_ECR0112_PREP/matrix.sh`, purged cache.

The Match-scoped directive read as global (the false all-clear returns); the Match header
ignored; `Match` / `Match all` inverted; last-wins instead of first-wins in global scope; a
Match-only opening going silent; and a conditional-only config returning no finding at all.

Six new tests, validated against `sshd -T` on the live host. Ruff clean, `mypy --strict`
clean, full suite on live Postgres. Carried matrix stays at **84**.

## 5. What review should attack

1. **`Match` matching is not evaluated at all**, only detected. A `Match User nonexistent`
   that can never fire is still reported as conditional, which slightly over-flags — the safe
   direction, but noise on a config with dead Match blocks.
2. **A `Match all` at the very top** followed by directives is unconditional and handled, but
   a malformed `Match` with no criteria is treated as conditional. sshd would reject that
   config; the collector does not validate it.
3. **The conditional finding gives no severity distinction** between "global open" and "open
   only inside a Match" — both land at 68.0. A connection-scoped opening may be lower risk,
   and the collector cannot tell.
4. **Still no `sshd -T`.** This is the third ECR re-implementing sshd's parser; each one
   narrows the gap and none closes it. The authoritative path needs root.

## 6. Scope

`src/aqelyn/collect/host.py` — `_directive_scopes`, `sshd_directive` delegating to it,
`match_scoped_password_paths`, and the `ssh_password_match_scoped` field.
`src/aqelyn/collect/checks.py` — the conditional clause in `check_ssh_password_auth`. Six
tests appended to `tests/collect/test_collector_breadth.py`. No schema, no dependency, no
loopback or GC change.
