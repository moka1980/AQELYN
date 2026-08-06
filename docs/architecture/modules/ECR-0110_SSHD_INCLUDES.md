# ECR-0110 — The SSH reader was reading the wrong file, in the wrong order

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `61db602`.

> ⚠️ Eleventh consecutive ECR by one actor. §6 lists what independent review should attack.

## 1. Finding of record — with a live security consequence

ECR-0109 was found by pointing the collector at the one.com VPS. The same run reported
`ssh_password_authentication` as **unmeasured**. That was also wrong, and this time the truth
underneath it matters.

Ubuntu 26.04 ships `/etc/ssh/sshd_config` with the auth directives **commented out** and this
on line 24:

```
Include /etc/ssh/sshd_config.d/*.conf
```

`parse_ssh_password_auth` read only the main file, found nothing but comments, and returned
`None`. The real setting was in the drop-ins the whole time — and the drop-ins **disagree**:

| file | directive |
|---|---|
| `50-cloud-init.conf` | `PasswordAuthentication yes` |
| `60-cloudimg-settings.conf` | `PasswordAuthentication no` |

sshd takes the **first** obtained value and processes the glob in sorted order, so `50-` wins.
`sudo sshd -T` confirms: `passwordauthentication yes`.

**The production VPS accepts SSH password authentication on port 22, open to `0.0.0.0`.**
That is precisely the `high` / 68.0 finding this check exists to raise, and AQELYN was
reporting it as a fact it had not measured.

## 2. A second defect: the resolution rule was backwards

`parse_ssh_password_auth` kept the **last** matching directive. sshd_config(5): *"unless
noted otherwise, for each keyword, the first obtained value will be used."*

Worse, an ECR-0102 test **asserted the wrong rule** —
`test_ssh_password_auth_reads_the_last_effective_directive`. A green test that encodes a
misunderstanding is not a check; it is the misunderstanding, notarised.

I did not correct it from the man page. I proved it against a real `sshd`, both orders:

```
no then yes  =>  passwordauthentication no
yes then no  =>  passwordauthentication yes
```

Had the last value won, the collector would have read the VPS as `no` — the exact opposite
of the truth, and a **false all-clear** on the finding that matters most here.

## 3. Decision

`flatten_sshd_config(text, *, resolve)` inlines `Include` where it appears, resolving each
pattern in sorted glob order, bounded to eight levels so a self-including config cannot hang
a collector. `parse_ssh_password_auth` now returns on first match. `read_host_facts` takes an
optional `include_resolver`, defaulting to a filesystem one rooted at the config's directory.

**Validated against ground truth, not against a fixture.** Run over ssh on the real VPS with
its two conflicting drop-ins, the collector and `sshd -T` agree.

## 4. Two mutations ran GREEN and both were real

**M3** — `sorted(root.glob(...))` replaced by `list(...)` — changed nothing, because the
filesystem happened to return the files in the order the test wanted. A witness whose verdict
depends on directory iteration order is not a witness. Replaced with one that asserts the
resolver's **own output order** on three deliberately unsorted names.

**M6** — the `startswith("#")` guard in the Include branch — changed nothing because it
*cannot*. A commented Include has a first token of `#Include` or `#`, neither of which equals
`include`, so the token comparison already excludes it. Following the precedent `is_public`
set — dead code in a security-relevant path is a liability — the condition was **removed**
rather than kept looking load-bearing. The behavioural witness stays and now passes for the
right reason.

Note the deliberate inconsistency: `parse_ssh_password_auth` keeps *its* `#` guard, recorded
in ECR-0102 as unwitnessed-but-kept-for-intent. Both choices are defensible; what is not
defensible is not knowing which one you have.

## 5. Acceptance — 6 mutations, all red

Harness `~/AQELYN_ECR0110_PREP/matrix.sh`, purged cache. First-wins reverted to last-wins;
Include found but never followed; drop-ins read in filesystem order; `Include` matched
case-sensitively when the real files capitalise it; the depth bound removed; and a commented
Include followed.

Nine new tests plus one corrected ECR-0102 assertion. Ruff clean, `mypy --strict` clean, full
suite on live Postgres. Carried matrix stays at **84**.

## 6. What review should attack

1. **`Match` blocks are ignored.** `Match Address ...` scopes directives to a subset of
   connections; this parser treats everything as global. A config that enables password auth
   only for one source address will read as globally enabled.
2. **The collector still cannot run `sshd -T`**, which is the only truly authoritative answer
   and needs root. Everything here re-implements sshd's parsing, and re-implementations drift.
3. **Only `PasswordAuthentication` is read.** `KbdInteractiveAuthentication yes` with PAM is
   another password path and is not looked at; the VPS has it `no`, which is luck, not
   coverage.
4. **The include resolver reads whatever the glob matches**, with no cap on file count or
   size.
5. **The ECR-0102 test that asserted the wrong rule passed for two ECRs.** Nothing in the
   process would have caught it except running against a real machine, which is not a
   repeatable control.

## 7. The finding on the live server is NOT fixed, deliberately

Password authentication is enabled on `85.190.101.232`. I have not changed it.

Disabling it means editing `50-cloud-init.conf` and restarting sshd. I reach that machine
with a key, but I cannot verify how the owner reaches it, and getting this wrong locks them
out of their production server while they are away. That is the irreversible, outward-facing
class of change that does not get made unilaterally.

The fix, for when the owner confirms they have a working key:

```
sudo sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' \\
    /etc/ssh/sshd_config.d/50-cloud-init.conf
sudo sshd -t && sudo systemctl restart ssh
sudo sshd -T | grep -i passwordauthentication   # must print: passwordauthentication no
```

Verify by opening a **second** session before closing the first.

## 8. Scope

`src/aqelyn/collect/host.py` — `flatten_sshd_config`, `_filesystem_include_resolver`,
first-wins in `parse_ssh_password_auth`, and the `include_resolver` parameter. Nine tests
appended to `tests/collect/test_collector_breadth.py`, one corrected assertion in
`tests/collect/test_self_scan.py`. No schema, no dependency, no loopback or GC change.
