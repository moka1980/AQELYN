# ECR-0102 — `aqelyn collect`: a machine can describe itself

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `abbb276`.

> ⚠️ Third consecutive ECR written, implemented and merged by one actor. §6 lists what
> independent review should attack.

## 1. Finding of record

The owner asked how a customer scans their own computer or phone. The answer was: they cannot.

**AQELYN had no collection half at all.** `ls src/aqelyn/` had no `endpoint`, `agent` or
`collector`; nothing in the codebase touched a host. The two parsers that mention subprocesses say
*"No I/O, no subprocess, no network"* in their docstrings — by design. Seven `ingest*` entry points
existed, so the platform could be **fed**, but nothing **produced the food**. Every input so far
came from a tool someone else ran (grype, syft) or from observations typed by hand.

The Atlas draws *Endpoint Agents*, *Desktop Agent* and *Mobile App* as clients. They were drawn,
not built.

## 2. Decision

`aqelyn collect --output DIR` inspects the machine it runs on, read-only, and writes a collection
directory that `aqelyn <dir>` renders and `aqelyn surface --collection <dir>` serves. That closes
the loop for computers: **collect → ingest → look**, with no manual step.

Five checks: public listeners, host firewall state, pending package updates, sshd password
authentication, and the OS/kernel recorded as inventory.

**A check that cannot run reports `unmeasured`, never a pass.** This is the load-bearing decision.
`HostFacts` fields are `None` when unread — never a default — and each unread fact becomes its own
observation saying the machine is *"neither passing nor failing"*. A collector that quietly
substituted "no firewall found" for "we could not look" is exactly where this platform's central
claim would first be broken, so most of the test suite exists to make that impossible.

**Read-only by construction.** It runs `hostname`, `uname -r`, `ss -tlnH`, a firewall status query
and `apt-get -s upgrade` (simulate — changes nothing), and reads two files. No network connection.
No writes outside the output directory, which is created `0600`.

## 3. Mobile is out of scope, and that is the honest answer

A host collector cannot inspect an iPhone; iOS gives no third-party process that access. Real
options are device management (Intune, Jamf), a signed configuration profile, or an attested
questionnaire — each a separate product surface with signing and store implications, none of them
a scanner written in this repository. The manifest says so in its exclusions rather than leaving a
reader to assume phones were covered.

## 4. Result

On the development host:

```
$ python -m aqelyn collect --output ~/selfscan
Wrote 3 documents to /home/ubunto/selfscan
  4 observations, 2 facts unreadable
      high  10 port(s) are reachable from beyond this machine — on every interface:
            3000, 3100, 3200, 4317, 4318, 5000, 5432, 9009, 55432; on a specific
            routable address: 53.
    medium  31 package update(s) are pending on this machine.
      info  This machine's firewall could not be read.
      info  This machine's ssh password auth could not be read.
  not measured: firewall, ssh_password_auth
```

Fed straight through: `aqelyn ~/selfscan` renders 4 posture observations; seeding a runtime from
it yields 4 findings the surface serves.

## 5. Acceptance — and two greens that were the finding

Harness `~/AQELYN_ECR0102_PREP/matrix.sh`. Eleven mutations red across: unmeasured-gap recording,
unmeasured observation generation, the "neither passing nor failing" wording, loopback
classification, scope-suffix stripping, sshd directive case-insensitivity, `0600` permissions, and
the manifest naming its gaps.

**A test caught a real false positive before any of that.** `is_public` compared against
`127.0.0.1` only, so `127.0.0.53` — systemd-resolved — was reported as internet-facing. The whole
`127.0.0.0/8` range is loopback. A security tool that over-reports once is discounted thereafter,
so this mattered more than the mutation score. Now decided with `ipaddress`, and an address that
cannot be parsed is called public: over-reporting an unknown beats silently clearing it.

**Two mutations stayed green, and both were redundant code rather than missing tests.**

- The `is_unspecified` branch in `is_public` — `0.0.0.0` is not loopback, so the general test
  already covered it. **Removed.** Dead code in a security check is a liability.
- The `#` comment skip in the sshd parser — a commented directive already fails the token
  comparison. **Kept, and marked in the source as defensive and unwitnessed** rather than left
  looking proven.

Two further greens were genuine test gaps, now closed: every unreadable fact must produce its own
unmeasured observation (counting the ones that exist cannot catch a missing one), and an
unparsable bind address must read as public.

28 tests. Ruff clean, `mypy --strict` clean across 585 files, full suite on live Postgres. Carried
matrix stays at **84**, untouched.

## 6. Charter v2 compliance — partial, and the gap is named

Read after implementation, which is the wrong order and is why this section exists.

**Aligned by construction.** Principle 1 (Explain Before You Recommend) is enforced in code: the
posture schema *refuses* an observation missing what-happened, why-it-matters, how-determined or
risk-of-inaction. Principle 3 (Evidence Before Opinion) — every observation carries an evidence
record. Principle 6 (Transparency) — the manifest states what was collected, by what authority,
and what was excluded. Principle 7 (Privacy First) — local, read-only, no network, `0600`.
Principle 8 (Security Without Fear) — objective wording throughout.

**Not yet compliant, and this is a real gap:**

- **UX-001 — non-technical summary.** Titles are machine strings
  (`listening_sockets_public on 85.190.101.232`). The Charter requires plain language.
- **UX-002 — expert-detail expansion.** `Finding.expert_details` exists in the model and this
  converter leaves it empty.
- **§5 Affected Assets.** `Finding.affected_object_ids` exists and is left empty.
- **Principle 5 / Progressive Detail Model.** Six disclosure levels are specified; the report
  renders one flat block.
- **UX-008 — communication modes** (home, SMB, enterprise, expert) do not exist.

The Charter is explicit that these are *mandatory architectural requirements*, not styling. They
are scheduled as ECR-0103 rather than quietly deferred.

## 7. What review should attack

1. **`run_command` executes real subprocesses.** Fixed argv, no shell, module-constant commands —
   but it is the first code in this repository that runs anything, and that deserves a second read.
2. **`apt-get -s upgrade` is Debian-only.** On other distributions the fact reads unmeasured, which
   is correct but means the collector is quietly less useful there than it looks.
3. **Severity thresholds are my judgement** — more than three public ports is "high", twenty
   pending updates is "medium". Defensible, unvalidated.
4. **No test runs the CLI end to end**; `main()` is covered only through its parts.
5. **The collector trusts `hostname`** as the subject reference. Two machines with the same
   hostname would collide in the dedup key.
