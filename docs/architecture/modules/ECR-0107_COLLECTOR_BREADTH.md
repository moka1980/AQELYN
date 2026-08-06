# ECR-0107 — The collector stops assuming Debian

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable.
**Date:** 2026-08-06
**Number:** verified free at `77858e3`.

> ⚠️ Eighth consecutive ECR by one actor. §5 lists what independent review should attack.

## 1. Finding of record

ECR-0102 shipped `aqelyn collect` with four checks and named its own blind spots: disk
encryption, automatic updates, and package managers other than APT. Those are not exotic
gaps. A Fedora or Arch machine reported `pending_updates: unreadable` — honest, and useless.

Two of the three missing checks are among the most consequential facts about a laptop. A
stolen unencrypted machine hands over everything on it regardless of every access control the
running system enforced.

## 2. Decision

**Updates, by whichever package manager is installed.** `_UPDATE_TOOLS` tries apt, dnf,
zypper and pacman in order; the first one present answers. Each carries the exit code that
means "the command answered", because **`dnf check-update` exits 100 when updates exist**.
Treating non-zero as failure would have reported exactly the machines that need patching as
unreadable — the single case the check exists for.

**Disk encryption.** `lsblk -rno TYPE` and look for a `crypt` mapping. The absence of one is
a real answer, not an unknown: the command ran and listed every device.

**Automatic updates.** Read `APT::Periodic::Unattended-Upgrade` from
`/etc/apt/apt.conf.d/20auto-upgrades`. The directive set to `"0"` and never mentioned both
read `False` — operationally identical, nothing installs updates on its own. The file being
**absent** reads `None`, because a machine with no APT is not a machine that declined
automatic updates.

Everything stays read-only, fixed argv, no shell.

Run against this machine: six observations, up from four. It has no encrypted volume, no
automatic updates, and 31 pending packages — three real findings the collector could not
previously see.

## 3. Two of my own parsers were wrong, and my own tests caught them

`parse_unattended_upgrades` read `line.split('"')[3]`. The correct index is 1 —
`APT::Periodic::Unattended-Upgrade "1";` splits into three parts, not four. It matched
nothing, so **every machine would have reported automatic updates disabled**, including ones
that had them on. A confident false positive.

`parse_dnf_updates` counted the `Obsoleting Packages` trailer as updates, inflating the count
by one per obsoleted package.

Both were caught by the witnesses in the same commit, before the matrix ran. Recorded because
"I wrote the parser and the test together" is the situation in which a test most often passes
for the wrong reason, and here it did not.

## 4. Acceptance — 11 mutations, all red

Harness `~/AQELYN_ECR0107_PREP/matrix.sh`, purged cache.

dnf's exit 100 treated as failure; dnf removed from the tool list; a machine with no package
manager silently ceasing to report the gap; the wrong device type so encryption is never
detected; an unreadable device table reported as unencrypted; any mention of the directive
counting as enabled; a commented-out directive counting as enabled; an absent config reported
as a declined setting; each new check written but never called; and the dnf trailer counted.

**One weakness the matrix exposed.** M8's only catcher was ECR-0102's
`test_every_unreadable_fact_produces_its_own_unmeasured_observation` — true, but indirect and
one witness deep. A direct check-level witness was added and M8 now has two catchers.

**That ECR-0102 test earned its keep.** It asserts set equality over the unmeasured facts
rather than a count, so adding two facts made it fail until the list was updated. A count
would have passed silently.

Necessity: five deselection runs, all GREEN.

23 tests in the new file. Ruff clean, `mypy --strict` clean across 591 files, full suite on
live Postgres. Carried matrix stays at **84**.

## 5. What review should attack

1. **`lsblk` sees mappings, not policy.** A machine with an encrypted data volume and a plain
   root reports `True`. The check answers "is anything encrypted", not "is the thing that
   matters encrypted", and the observation's wording does not make that distinction.
2. **Windows and macOS are still invisible.** BitLocker and FileVault have no path here. The
   user has both an iPhone and an Android phone in scope, and neither is addressed by
   anything in this ECR.
3. **The zypper and pacman parsers have no real-output fixture.** They were written from the
   documented format, not from a captured run on those distributions. The dnf one was tested
   against a realistic sample; the other two are the weakest code in this change.
4. **`unattended-upgrades` being enabled in config is not proof it runs.** The timer could be
   masked. The check reads intent, and reports it as if it were behaviour.
5. **Only `20auto-upgrades` is read.** APT merges the whole of `apt.conf.d`; a later file
   could override it.

## 6. Scope

`src/aqelyn/collect/host.py` (four parsers, three `HostFacts` fields, multi-manager update
detection), `src/aqelyn/collect/checks.py` (two checks, added to `CHECKS`), one amended
assertion in `tests/collect/test_self_scan.py`, and a new
`tests/collect/test_collector_breadth.py`. No schema change — posture observations already
carry arbitrary checks. No dependency, no loopback or GC change.
