# Standards-conformance read — EA-0058 / EA-0060 / EA-0061 (proposed record-only ECR)

**From:** claude.ai (spec author), discharging the read flagged by ECR-0086 Disposition C
**To:** owner (finding), then Codex (record commit), then Claude Code (review/merge)
**Read against:** the three archive packages as uploaded 2026-08-02 (EA-0058.zip,
EA-0060.zip, EA-0061.zip, all files dated 2026-07-09). Every count below was produced by
running the check in the sandbox, not by reading titles. I did not and cannot read the
repo; the single code-side item is marked for Claude Code.

---

## 1. The finding — there is nothing to conform to

**The conformance read is complete, and its result is that no conformance read is
possible: EA-0058, EA-0060 and EA-0061 contain no standards.** Each is 703 lines, and
the unique content of each is approximately **29 lines**: one executive-summary
sentence, eight scope-domain bullets, and twenty section *titles*. Everything else is
generator output, verified mechanically:

- **300 requirement lines (100 per document) normalize to ONE sentence.** Every
  `EA-00xx-REQ-NN-MM` reads: *"The implementation shall apply {section title,
  lowercased} consistently across all affected modules and maintain traceability to
  source requirements."* Five identical copies per section, twenty sections, three
  documents. Zero requirement content survives topic normalization.
- **All 60 "Implementation Rules" blocks are byte-identical** — the same five bullets
  in every section of every document (verified by hash equality across all three).
- **All 60 "Acceptance Criteria" blocks normalize to one template** ("{Title} is
  implemented, tested, documented, and linked to the traceability matrix," four
  identical copies each).
- The Requirements/Traceability matrices are mechanical restatements of the section
  titles ("Implement {Title} controls | Mandatory | Review + Tests"). The Engineering
  Journal, Final Review, Engineering Review ("APPROVED FOR BASELINE — structure
  verified, PDF generated"), and checklists are identical across all three packages.
  The review file approves *file structure*, not content.
- **No IS numbers are declared** in any of the three masters — the EA-0052/IS-035
  collision family does not recur here.

**This is a third generator template**, joining the two already on record: the
424-line shape (EA-0038…0050, assessed by ECR-0060) and the 485-line shape
(EA-0052…0057, assessed by ECR-0086). Different line count, different heading
grammar, same content class: the section titles are the only document-specific text.

## 2. Correction to ECR-0086's premise — same lesson, third appearance

ECR-0086's Disposition C carried these three as *"normative standards documents (703
lines each … real content, not the 485-line stub shape)"* that *"plausibly contain
coding and AI-engineering standards this platform is supposed to conform to."*

The hedge was honest — *"plausibly," "documents nobody has opened"* — and the flag
was correct to raise: the read was owed. But the premise behind it was a line-count
inference, and it was wrong. 703 ≠ 485 measured the generator, not the content. This
is the recorded lesson family's third appearance in this batch alone: **a census
reads as coverage, a bound stops tracking what it measures, and a line count reads
as content.** Worth one sentence in the ECR so the next reader inherits the
correction, not the inference.

## 3. The only normative residue — five sentences

The single set of normative sentences in all 2,109 lines is the shared
Implementation Rules block:

1. All code and configuration must be deterministic, reviewable, and testable.
2. All external inputs must be validated before processing.
3. All user-facing outputs must be understandable by non-experts and expandable for
   experts.
4. All security decisions must include evidence references and audit metadata.
5. All deviations require an Architecture Decision Record and engineering review.

These restate platform principles the repo already enforces elsewhere (evidence
references, ADR discipline, explainability, input validation, review gates).
**One verification item for Claude Code, cheap and optional:** confirm each of the
five maps to an existing shipped rule or convention, and record any that lack one.
That is the entire code-side surface of this read. I claim nothing about `src/`.

## 4. What the ECR should record

1. **Close the ECR-0086 debt as discharged.** The standards-conformance read owed on
   EA-0058/0060/0061 was performed 2026-08-02; finding: no normative content.
2. **Reclassify the three rows:** from *"non-capability, owing a separate
   standards-conformance read"* to *"non-capability — no normative content;
   generator template class 3 (703-line shape). Read performed and closed."*
   EA-0059/0062/0063 keep their existing classification; nothing here reopens them.
3. **Record the template-class-3 signature** (703 lines, 31-line section stride,
   the one-sentence REQ template) alongside the other two, so any future archive
   additions in this shape are recognized on sight.
4. **Optionally and non-bindingly:** note that EA-0058's twenty section titles form
   a reasonable *outline* for a standards document the project may someday write
   (language standards, error handling, dependency governance, release gates…).
   The archive supplies the table of contents; it does not supply the book. If such
   a document is ever wanted, it is authored fresh as its own deliverable — not
   recovered from EA-0058.
5. **Rule 20:** this needs the next free ECR number, re-checked against `ECR-LOG.md`
   at merge time per the corrected premise (the archive runs to EA-0063).

This is a **record-only ECR**: docs and the one optional five-bullet verification.
No runtime, no guards (absence guards exist only for capabilities someone might
build; nothing here is buildable), no scheduling question, no owner decision — the
delegated decision structure of ECR-0086 is untouched.

## 5. Ball

**Next: Codex** — commit this brief, author the record-only ECR per §4, flip the
unassigned-list entry to closed. **Then: Claude Code** — review, run the §3
five-bullet check if taking the option, merge. Remaining unassigned after this
closes: P-001 at scale, loopback hosting for the report (needs an ECR), and the
owner's own debts.
