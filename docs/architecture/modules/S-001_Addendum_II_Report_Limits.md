# S-001 Addendum II — What the Density Report Cannot See

**Amends:** `S-001_Addendum_Density_Report.md`
**Occasioned by:** ECR-0066's audit, which found a fourth defective factor
(`epss`) that **the report itself could not have revealed**.
**Status:** specification note — a limit on the roadmap instrument.

---

## 1. The finding

ECR-0066's audit was required to cover **all seven** factors rather than the three
the density report surfaced. That requirement paid twice, and the second payment
is the one with a lasting consequence:

**`epss` had the same defect as `baseline`, `mission` and `threat` — a missing
branch that reports `known` when no value is supplied. It never fired**, because
**every real record in the corpus carried an EPSS score.** The report therefore
showed `epss: known=200`, which is **indistinguishable** from a factor that is
genuinely always known.

## 2. The limit, stated so it is not forgotten

> **The density report measures the corpus, not the code.**
>
> A factor that is always `known` **on the current corpus** cannot be
> distinguished from a factor that is always `known` **by default**. Only
> enumeration separates them.

The report is therefore **a roadmap over what the corpus happened to exercise** —
not a coverage claim, and not an audit. Treating a `known=N/N` row as evidence that
a factor is correctly wired is exactly the inference this addendum exists to
prevent.

**What covers the remainder is enumeration** — reading each provider path and
recording whether `known` is *earned by a supplied input* or *defaulted in the
absence of one*, as ECR-0066's audit did.

## 3. Why more data does not fix this

The instinct is that a larger corpus would eventually contain a record lacking
EPSS and expose the branch. That is true only by luck, and the direction of the
effect is the wrong one:

**A larger corpus in which every record carries EPSS hides the defect exactly as
well as a small one** — and makes the row *look* better evidenced, because `known
= 20,000/20,000` reads as stronger confirmation than `known = 200/200`. **The
camouflage improves with scale.**

Only a record that *lacks* the value reveals the branch, and nothing guarantees
real data supplies absences where they are needed.

## 4. The sibling to rules 26 and 27

Rule 26: a **required field** is an assertion the field is always available, and
fixtures cannot falsify it because the fixture author always has the value.
Rule 27: a **fixture's values** encode assumptions about the shape of real data —
precision, magnitude, cardinality — untested until real data arrives.

S-001 makes the third member of the family visible, and it cuts the other way:

> **Real data is not adversarial either.** It supplies what it supplies. It
> falsifies a *different* set of assumptions than fixtures do — not all of them —
> and the ones it leaves untouched are invisible precisely because the run
> *succeeded* against them.

So the S-track does not supersede enumeration; it **relocates** what enumeration
is for. Before real data, the audit's job was to find what nobody had thought to
test. After real data, its job is to find **what the corpus happened not to
exercise** — which is a smaller set, but a set that now wears the appearance of
having been tested.

## 5. Consequence for how the report is read

- A `unknown = N/N` row is **sound evidence**: the platform said it could not
  determine the factor, and it said why.
- A `known = N/N` row is **not** evidence that the factor is wired. It is evidence
  that **the corpus never asked**.
- The report ranks **what to connect next**; it does not certify **what is already
  connected**. Those are different questions and only the first is in scope.

**Practical rule:** any new factor, or any factor whose provider path changes,
requires the enumeration — a `known = N/N` row is not a substitute, at any corpus
size.
