# AQELYN spec-author brief — the self-scan arc (ECR-0100 … ECR-0111)

**From:** Claude Code (reviewer; the only actor who reads shipped `src/`)
**To:** claude.ai (spec author) and Codex (implementer/reviewer, returning)
**Date:** 2026-08-06

> Read this before drafting anything. Twelve consecutive ECRs were written by one actor
> while Codex was unavailable. That is the largest unreviewed run this project has had.

---

## 1. State

- **`main` = `7d16b49`**, clean. **ECR-0111 is open in PR #314.**
- **NEXT FREE ECR = 0112**, read from `docs/architecture/modules/ECR-LOG.md`, not from memory.
- **NEXT FREE GC = 005.** Rules 1–34 unchanged.
- Carried mutation matrix: **84**, untouched by every ECR below.

### What shipped in this arc

| ECR | What it does |
|---|---|
| 0100 | `posture.json` ingestion — the platform can be told a configuration fact, not only a CVE |
| 0101 | `aqelyn surface --collection DIR` seeds a live runtime |
| 0102 | `aqelyn collect` — a machine describes itself |
| 0103 | Charter UX-001/UX-002 for posture findings |
| 0104 | Progressive disclosure model + four communication modes |
| 0105 | The disclosure model actually reaches the rendered page (`--mode`) |
| 0106 | A posture subject becomes a real `AQObject`; Affected Assets resolves |
| 0107 | Collector stops assuming Debian; disk encryption; automatic updates |
| 0108 | Plain-words glossary, additive |
| 0109 | Firewall reader — two opposite lies in three lines |
| 0110 | sshd `Include` + first-wins |
| 0111 | All three password-capable auth paths |

**The loop now closes end to end:** `aqelyn collect` → `posture.json` → ingest → object +
evidence + finding → rendered report at four audience depths.

---

## 2. Restatement / false-friend check, run by me against shipped `src/`

claude.ai cannot grep the repo. These were checked here:

- **New id prefixes: none.** Everything reuses `obj`, `evd`, `fnd`, `src` from
  `conventions/ids.py::PREFIXES`.
- **New object type: `posture.subject`** (`reporting/posture.py::POSTURE_SUBJECT_OBJECT_TYPE`),
  registered at ingestion time by `ensure_posture_object_type`. Natural-key namespace is
  `posture:{kind}` — **do not reuse that namespace for a different subject taxonomy.**
- **New finding type: `posture.observation`.** New evidence type: same string.
- **New source engine: `posture_collector`.**
- **`"document_schema"`, not `"schema"`**, is the key in collector documents. `schema` is
  taken by `lake.schema` and GC-004's persisted-field census catches the collision.
- **`_GLOSSED_MODES`, `UPSTREAM_DEFAULT_OPEN`, `_PASSWORD_PATHS`, `_FIREWALL_TOOLS`,
  `_UPDATE_TOOLS`** are new module constants; none are exported types.

### One live false friend to avoid

**EA-0054 "Web Intelligence" is a recorded decision NOT to build**, and
`tests/conformance/test_batch_ea0052_0063.py` enforces its absence by **text census over
`src/`**. It fired twice on ECR-0108: once on four glossary terms, then again on the comment
that explained removing them. **Any spec that writes HSTS / CSP / SPF / DKIM / DMARC
vocabulary into `src/` will break the build.** Say "web- and mail-intelligence terms" in
prose, or reclassify the row in an ECR — do not weaken the guard.

---

## 3. Real delegation seams, quoted from shipped code

```python
# collect/host.py — the injection point that made real-machine validation possible
CommandRunner = Callable[[Sequence[str]], tuple[int, str] | None]
def read_host_facts(runner: CommandRunner = run_command, *, os_release: Path,
                    sshd_config: Path, auto_upgrades: Path,
                    include_resolver: IncludeResolver | None = None) -> HostFacts

# collect/checks.py — pure; facts in, observation dict or None out
CHECKS = (check_public_listeners, check_firewall, check_pending_updates,
          check_unattended_upgrades, check_disk_encryption, check_ssh_password_auth)
def observations_for(facts: HostFacts, *, subject_ref: str) -> Sequence[dict[str, Any]]

# reporting/analyze.py — ingestion into a caller's runtime
async def ingest_posture_into(runtime: Runtime, directory: Path) -> tuple[Finding, ...]

# reporting/disclosure.py — Charter Principle 5 / UX-008 as data
def levels(finding: Finding, *, mode: Mode = Mode.ENTERPRISE) -> Sequence[Level]
```

A new check is a pure function `(HostFacts, str) -> dict | None` added to `CHECKS`. A new
fact is a `HostFacts` field that is `None` when unread. Nothing else needs to change.

---

## 4. Carry-forward rules earned in this arc

Cumulative — these join the standing list permanently.

1. **A fact that could not be read is `None`, never a default.** Written in
   `collect/host.py`'s docstring since ECR-0102 and violated by the code below it twice
   (ECR-0109). If a spec says "reports X as absent", ask whether it means *absent* or
   *unreadable*.
2. **Only vocabulary the shipped checks can emit** may enter the glossary. A glossary is a
   claim about what the product says.
3. **A mode changes what is opened, never what is true.** The finding's sentence is
   byte-identical in all four modes and there is a witness. Any spec proposing per-audience
   *rewriting* must first answer: what witnesses the drift between the two versions?
4. **Identity belongs to the subject, not to an id we minted.** New object types get a
   natural key and let `upsert` mint the id.
5. **Two records of one fact are two records that can disagree.** `ssh_password_auth` became
   a derived property for exactly this reason (ECR-0111).
6. **Dead code in a security-relevant path is a liability**, not harmless documentation —
   the `is_public` precedent, applied again in ECR-0110. But `parse_ssh_password_auth` keeps
   its equivalent guard deliberately. What matters is *knowing which you have*.
7. **Settle semantics by running the real tool.** sshd's first-vs-last-wins was decided by
   `sshd -T -f` on two-line configs, not by the man page — and an existing green test had
   asserted the wrong rule for two ECRs.

---

## 5. Open follow-ups a new module must not weaken

- **`UPSTREAM_DEFAULT_OPEN` is recorded, not applied.** Two of three sshd password paths
  default to open; a config relying on the default reads as unmeasured. Largest hole in the
  SSH check (ECR-0111 §6.1).
- **`Match` blocks in sshd_config are ignored** — a directive scoped to one source address
  reads as global.
- **No relationship** links a `posture.subject` to objects other engines already know. The
  same host found by ISPM and by `aqelyn collect` is two objects. `ObjectStore.merge` exists
  and is not called (ECR-0106 §5.2).
- **nftables / iptables invisible** to the firewall check.
- **Windows and macOS entirely uncollected** — see §6.
- **`_technical_body` flattens nested dicts to a semicolon string**, and that now reaches a
  human eye.
- Tenant is `None` throughout the posture path (`tenant_mode="local"`).

---

## 6. The thing to spec next, and the constraint on it

**A Windows collector is the biggest product gap.** The owner has a Windows machine, an
iPhone and an Android phone in scope and asked directly how a customer self-scans them.

**I did not build it, deliberately.** WSL interop is unavailable in this environment — not
one Windows binary can be executed here. ECR-0109 and ECR-0110 exist *because* fixtures
agreed with a collector that reality did not; shipping a Windows collector validated only
against strings I wrote myself would repeat that mistake knowingly.

**So the spec must name its validation host.** A Windows collector FR that does not say
which real machine it will be run against, and what authoritative command its output will be
compared to (`manage-bde -status`, `Get-MpComputerStatus`, `Get-NetFirewallProfile`), is not
code-ready. That is the one new acceptance condition this arc adds.

---

## 7. What review should attack first

Every ECR from 0100 has a numbered "what review should attack" section; they are the
shortest path in. Highest value, in order:

1. **ECR-0111 §6.1** — unset directives that default to open.
2. **ECR-0106 §5.2** — posture subjects never merge with other engines' objects.
3. **ECR-0108 §7.2** — 18 glossary definitions whose *correctness* no test can check.
   Someone who knows the domain should read them.
4. **ECR-0105 §6.5 / ECR-0109 §5.4** — the HTML is checked by string count and a parser; no
   test loads it in a browser, and no test runs the real `ufw` binary.

**Re-run my mutations against whatever you conclude.** Harnesses are in
`~/AQELYN_ECR01{05..11}_PREP/`, driver at `~/AQELYN_ECR0096_REVIEW/lib.sh`.

⚠️ **The driver was defective twice this arc** and both were caught by a cell that ran GREEN
for no reason. It now sets `PYTHONDONTWRITEBYTECODE=1`, purges `__pycache__` on apply and
restore, and rejects a non-numeric line, an out-of-range line, any non-zero applier exit, and
an unchanged file. If you use an older copy, you will get false GREENs.

---

## 8. Live, unfixed, and the owner's call

**`85.190.101.232` accepts SSH password authentication on port 22, open to `0.0.0.0`.**
`50-cloud-init.conf` says `yes`, `60-cloudimg-settings.conf` says `no`, sshd takes the first
in sorted glob order. Confirmed with `sudo sshd -T`. The other two password doors on that
machine are confirmed shut, so the fix is one directive.

Not applied by me: I reach that machine with a key and cannot verify how the owner does.
Command and safe verification in **ECR-0110 §7**.

Also owed by the owner, checked 2026-08-06 and still absent:
`o-checker.wcagvakt.no. A 85.190.101.232`, and DMARC `p=none` → `p=quarantine`.

**Next: Codex reviews ECR-0100…0111. claude.ai specs the Windows collector, with a named
validation host.**
