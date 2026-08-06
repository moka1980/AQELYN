# ECR-0109 — The firewall reader told the truth in neither direction

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `7ad4ac7`.

> ⚠️ Tenth consecutive ECR by one actor. §5 lists what independent review should attack.

## 1. Finding of record

Running the ECR-0107 collector against the **live one.com VPS** — not a fixture — produced:

```
medium  42.0  host_firewall_active  A host firewall (ufw) is installed but not active.
```

The firewall on that machine is active, with seven rules. `ufw status` requires root; run as
an ordinary user it prints `ERROR: You need to be root to run this script` and exits 1. The
reader ignored the exit code entirely and asked only whether the output contained
`status: active`. It did not, so the machine was reported as unprotected and the owner was
advised to enable a firewall that had been running the whole time.

`collect/host.py`'s own module docstring already forbade this:

> **A fact that could not be read is `None`, never a default.** A firewall whose state could
> not be determined must not become "no firewall" — the platform's whole claim is that
> unmeasured is its own state, and a collector that quietly substitutes a default is where
> that claim would first be broken.

The doctrine was written, and the code three hundred lines below it did the opposite.

**A second defect in the same three lines, pointing the other way.** The firewalld branch
tested `"running" in output`. `firewall-cmd --state` prints **`not running`** when firewalld
is stopped, and `"running" in "not running"` is `True` — so a **stopped** firewall would have
been reported as active. Nobody had run it on a firewalld host, so it had never been seen.

One reader, two opposite lies: a false alarm on a protected machine, and silence on an
unprotected one.

## 2. Decision

Separate "did the command answer?" from "what did it say?".

```python
_FIREWALL_TOOLS = (("ufw", ["ufw", "status"], "status:"),
                   ("firewalld", ["firewall-cmd", "--state"], "running"))
_FIREWALL_ACTIVE = {"ufw": lambda out: "status: active" in out,
                    "firewalld": lambda out: out.strip() == "running"}
```

If the readable token is absent, the tool is present and the **state is unreadable** —
`firewall_active` stays `None`, `firewall` joins `unreadable`, and `check_firewall` emits the
unmeasured observation it already had. The exit code is deliberately not used as the test:
`firewall-cmd --state` exits 252 when firewalld is stopped, which is a real answer, so
keying on the exit code would have replaced one wrong reading with another.

All six states verified directly: ufw active / inactive / needs-root, firewalld running /
stopped, and no firewall installed.

Re-run against the live VPS, the false finding is gone and reads
`info 0.0 host_firewall_active — This machine's firewall could not be read.`

## 3. What this says about the method

ECR-0107 shipped this reader unchanged and its matrix was 11/11 red. Neither defect was in
that matrix, because both live in code ECR-0107 did not touch and no fixture exercised the
failing input. The bug was found by **pointing the collector at a real machine that was not
mine** — which took one script, because `read_host_facts` already takes an injectable
`runner` and that injection point works for ssh as well as it does for a test double.

A fixture proves the code does what the fixture says. Only a real machine says what the
inputs actually look like.

## 4. Acceptance — 5 mutations, all red

Harness `~/AQELYN_ECR0109_PREP/matrix.sh`, purged cache.

The regression itself (an unreadable firewall becoming inactive); an empty readable token so
any output counts as an answer; **the old substring test restored**, so a stopped firewalld
reads as active; ufw always active; and the unreadable case no longer reported as unmeasured.

Necessity: two deselection runs, both GREEN.

Six new tests. Ruff clean, `mypy --strict` clean, full suite on live Postgres. Carried matrix
stays at **84**.

## 5. What review should attack

1. **`nftables` and `iptables` are still invisible.** A machine using either directly, with no
   ufw or firewalld wrapper, reports "firewall: unreadable" — honest, and no more useful than
   the ECR-0107 update gap was.
2. **Neither tool is queried for its actual policy.** "Active" is not "default-deny inbound",
   and the observation's remediation text asks for the latter while the check measures the
   former.
3. **The unmeasured path is now easier to reach than before**, because a permission problem
   lands there. On a machine where the collector never has root, `host_firewall_active` will
   read unmeasured forever and nothing escalates that into "you should run this with more
   privilege".
4. **No test runs the real `ufw` binary.** The witnesses use captured strings, which is how
   the original defect survived: the string the tool actually emits without root is the thing
   nobody had looked at.

## 6. Scope

`src/aqelyn/collect/host.py` — `_FIREWALL_TOOLS`, `_FIREWALL_ACTIVE`, and the read loop. Six
tests appended to `tests/collect/test_collector_breadth.py`. No change to `checks.py`: the
unmeasured branch it already had was correct and simply unreachable. No schema, no
dependency, no loopback or GC change.
