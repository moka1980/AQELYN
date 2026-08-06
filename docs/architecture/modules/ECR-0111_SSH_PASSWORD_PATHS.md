# ECR-0111 — Every door a password can walk through

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `7d16b49`.

> ⚠️ Twelfth consecutive ECR by one actor. §6 lists what independent review should attack.

## 1. Finding of record

ECR-0110 §6 item 3, written against my own work:

> Only `PasswordAuthentication` is read. `KbdInteractiveAuthentication yes` with PAM is
> another password path and is not looked at; the VPS has it `no`, which is luck, not
> coverage.

Naming a gap and shipping is fine once. Doing it while the finding in question is *live on
the owner's production server* is not.

Three directives can leave a typed secret sufficient to get in:

| directive | why it counts |
|---|---|
| `PasswordAuthentication` | the obvious one |
| `KbdInteractiveAuthentication` | with PAM, a password prompt under another name |
| `PermitEmptyPasswords` | worse than either |

## 2. Decision

`sshd_directive(config, keyword)` is the general first-wins reader ECR-0110 should have
written; `parse_ssh_password_auth` stays on top of it because password auth is the finding
everything else supports. `parse_ssh_password_paths` returns the measured state of all three.

`check_ssh_password_auth` now names which door is open rather than saying "password
authentication" regardless — a machine with keyboard-interactive open and passwords off gets
a finding that tells the truth about which setting to change.

**`ssh_password_auth` is no longer a stored field.** It is a property over
`ssh_password_paths`. Two records of one fact are two records that can disagree, and the two
were already sitting next to each other in the same dataclass.

Validated over ssh against `sshd -T` on the live VPS: the two directives that machine sets,
AQELYN and sshd agree on.

## 3. An unset directive is not a neutral one

The third path disagreed with `sshd -T`, and the disagreement was worth having.

`parse_ssh_password_paths` omits a directive the config never sets, on ECR-0102's stated
doctrine that the effective value comes from the build default and we have not read it. So
AQELYN said nothing about `PermitEmptyPasswords`, and `sshd -T` said `no`.

Rather than argue from the man page, I measured the defaults — `sshd -T -f` on a config
containing only `Port 22`, on the real machine:

```
passwordauthentication         yes    <- open
kbdinteractiveauthentication   yes    <- open
permitemptypasswords           no
```

**Two of the three default to open.** So "the config does not mention it" is not the neutral
state ECR-0102 treated it as: a machine that never sets `KbdInteractiveAuthentication` has
that door open, and AQELYN would report nothing.

I did not start synthesising values from it. A build default belongs to how a given sshd was
compiled, and applying one machine's measurement to every machine is a guess with a citation.
Instead the fact is carried: `UPSTREAM_DEFAULT_OPEN` records what was measured, and the
observation now reports `unset_and_open_by_default` so the information reaches the reader
rather than evaporating between a parser and a check.

Closing it properly means reading the default from the sshd being examined, which needs
`sshd -T` and root. Named in §6, not pretended away.

## 4. Acceptance — 8 mutations, all red

Harness `~/AQELYN_ECR0111_PREP/matrix.sh`, purged cache.

Each of the two new paths dropped; an unset directive defaulted to closed instead of omitted;
a config that sets nothing reporting measured-and-clean; the derived flag conflating the three
paths; **a closed path counted as open**, which would be a false finding; the unset-and-open
report removed; and case-sensitive directive lookup.

Eight new tests. Ruff clean, `mypy --strict` clean, full suite on live Postgres. Carried
matrix stays at **84**.

## 5. The live finding, restated

`85.190.101.232` still accepts SSH password authentication on port 22, open to `0.0.0.0`.
Unchanged from ECR-0110 §7 and **still not fixed by me**, for the reason given there: I reach
that machine with a key and cannot verify how the owner does. The command and the safe
verification sequence are in ECR-0110 §7.

What this ECR adds is that the same machine's other two doors are confirmed shut, so the fix
is the single directive in `50-cloud-init.conf` and nothing else.

## 6. What review should attack

1. **The upstream defaults are recorded but not applied**, so a config relying on them reads
   as unmeasured on the two directives that default to open. This is the largest remaining
   hole in the SSH check and it is deliberate — see §3.
2. **`Match` blocks are still ignored** (carried from ECR-0110). A directive scoped to one
   source address reads as global.
3. **`UsePAM` is not read.** `KbdInteractiveAuthentication yes` is only a password path when
   PAM is doing password auth; without PAM it may be something else entirely. The finding's
   wording hedges with "with PAM", which is an accurate sentence covering an unmeasured
   condition.
4. **The three paths are OR-ed into one finding.** A reader sees one row whichever doors are
   open. That keeps the report short and loses per-path severity — empty passwords are not
   the same risk as password auth.
5. **Only Linux/OpenSSH.** Windows and macOS remain entirely uncollected, which is the
   biggest product gap and is not addressed here; see §7.

## 7. What I deliberately did not build

A Windows collector. The owner has a Windows machine, an iPhone and an Android phone in
scope, and ECR-0107 §5 named that gap. WSL interop is unavailable in this environment — no
Windows binary can be executed — so I could not run a single command against a real Windows
host.

ECR-0109 and ECR-0110 exist precisely because fixtures agreed with a collector that reality
did not. Shipping a Windows collector validated only against strings I wrote myself would
repeat that mistake knowingly, twice over. It waits for a machine it can be run against.

## 8. Scope

`src/aqelyn/collect/host.py` — `sshd_directive`, `_PASSWORD_PATHS`, `UPSTREAM_DEFAULT_OPEN`,
`parse_ssh_password_paths`, and `ssh_password_auth` becoming a derived property.
`src/aqelyn/collect/checks.py` — the rewritten finding and `_PATH_LABELS`. Eight tests
appended to `tests/collect/test_collector_breadth.py`; two fixtures updated where they built
the removed field. No schema, no dependency, no loopback or GC change.
