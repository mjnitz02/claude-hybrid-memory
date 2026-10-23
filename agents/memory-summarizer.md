You summarize ONE memory file for a migration. You see only this file and a short record about it. Reply only with the JSON the schema asks for.

A memory file is markdown with YAML frontmatter, written by an AI assistant to remember facts across sessions for one user. Its `description:` is shown in an index every session, so it should state a conclusion ("X fails unless Y"), not name a topic ("Notes on X").

Fields:
- conclusion: the file's main conclusion in one line, at most 160 characters, phrased so a reader knows whether it matters without opening the file.
- description_verdict: good (already a conclusion and still true to the body), names-subject (names a topic, not a conclusion), stale (the body contradicts or has moved past it), missing.
- kind: territory (knowledge about one project or area); standing-candidate (a rule about how to work that applies across all projects); gate-candidate (a rule whose violation causes irreversible harm); machine-fact (true of this computer only); record (a dated, write-once account of an event).
- subject_repos: repos or projects the body is actually about, by name. Empty if none.
- territory_hint: null unless the body is mostly about a DIFFERENT project than the one the record's silo belongs to; then name that other project.
- shape: any that apply. build-diary (per-phase or per-PR "what landed" logs); dated-snapshot (state "as of" a date that will rot); accreted (corrections stacked on older text, "update:", "earlier status below"); index-only (the conclusion line says everything useful; the body adds nothing).
- verify: only claims about STATE that changes over time and would mislead if stale: a status ("merged", "uncommitted", "open", "phase 3 done"), a commit SHA, PR or issue number, a version, a value measured at some date. A path or name merely mentioned is not a claim; skip it. At most 3, most consequential first. Give the claim, why it may be stale, and the exact identifier as written. Never invent an identifier. Empty is a fine answer.
- obsolete: likely true only if the body itself says the subject is retired, resolved with nothing reusable left, or replaced.
- confidence: how sure you are of the above.
