---
name: memory-refine
description: Work the memory store's refine queue (fast adoption stage 5) - better descriptions, splits, promotions and relocations, one queue item at a time. Use when Matt says "refine", "work the queue", or /memory-refine [N], or when the retrospective reports a long queue.
---

# memory-refine

Works N items off the refine queue, default 10. Stages 1 to 4 landed everything roughly
right. This makes it good, one small item at a time, with only that item in view. Design:
`docs/fast-adoption.md` §8.

## Start

    mem refine queue                    # rebuild it; prints the head
    mem refine queue --territory T      # when Matt names one

The queue is `~/.claude/memory/.cache/migrate/queue.json`, already in work order. It is
**derived**: an item drops when its cause is gone, so there is no done-list to update. To
see whether an item is finished, rebuild the queue. Never edit queue.json.

Read `docs/format-spec.md` before writing any field. Nothing in this queue asks you to
verify a memory: claims are checked when a session acts on them (format-spec, *Verification
happens on use*).

## Per item

1. **Read only what the item needs.** When judging it means reading a large file, hand
   that file to an Agent with `model: sonnet` and the directive for its type (below), and
   read only the answer. Small files and audit-only items you read yourself.
2. **Decide, and say the decision in one line.** You write, not the subagent.
3. **Write to the store with a script** (python/perl/sed on `~/.claude/memory/...`), not
   Edit or Write: the harness rewrites frontmatter on memory paths. A new memory (a split's
   records, say) goes through `mem new`, which writes the fields and indexes it. A memory that
   replaces another goes through `mem supersede <old> <new>`. Never edit the old one in place.
4. **Rebuild the queue** and check that the item dropped. If it didn't, the fix missed.

| type | what dropping it takes | subagent directive |
|---|---|---|
| `standing-candidate`, `gate-candidate` | promote it, or link it to the directive that already covers it and supersede it; else Matt declines | "Is this rule true outside its one project? Quote the line that says so, or say it is project-specific. Name any of these standing directives it duplicates: <list standing/>" |
| `description` | a description that states the conclusion | "Judge this description against this body. If it names a subject rather than stating the conclusion, write one line that does." |
| `split-candidate`, `shape` | split into a short state memory plus records (format-spec, *state vs records*), or a rewrite that drops the diary | "Propose a split: one state memory (what is true now) and dated records. List each file's slug, description and which lines go where. Drop nothing." |
| `possible-duplicate` | merge and supersede, or Matt declines | "Do these two say the same thing? If so, which is newer and more complete?" |
| `index-only` | archive it, if its index line already says everything | none: read it |
| `frontmatter-not-yaml` | quote the offending value | none: mechanical |
| `low-confidence`, `territory-hint` | a read, then a fix or a decline | none: read it |
| `description-long` | a description under 160 bytes that still states the conclusion | same as `description`, plus: "in at most 160 bytes" |
| `index-degraded` | the full index back: shorten the longest descriptions, split records out of a crowded group, or propose restructuring the territory | none: `mem render --check T` names the steps it took; work the `description-long` items in that territory first |
| `index-over-cap`, `memories-over-cap`, `memories-over-target` | a shorter hand-written head or MEMORIES section; restructuring goes to Matt (`/memory-restructure`) | none: read the index |
| `field-invalid`, `missing-kind` | the value from the vocabulary in format-spec (a missing `group:` takes one of the territory's `groups:`) | none: mechanical |

**The index budget is this skill's, and only this skill's.** Render fits every index under
the harness's limit by itself, degrading its own output and never a memory's description, so
nothing on other items needs trimming to make room. Do not shorten a description because an
index is full: that is what `index-degraded` and `description-long` are for, and they want a
better description, not a shorter one.

## Ask Matt, don't act

- **Any promotion to `standing/` or `GATES.md`.** Standing is capped, and a gate edit needs
  Matt to name the file. Bring the candidate, the directive it would join or duplicate, and
  a recommendation.
- **Archiving or deleting.** Per the standing deletion rule, hand him the list with reasons.
- **A split of anything over ~10 KB.** Show the proposed files first.

Everything else (descriptions, recipes, YAML quoting, `tier: record`), just do it and
report it.

## Declining

When Matt says an item is fine as it is, append to the newest section of
`~/.claude/memory/RETRO.md`, under **Declined, with reasons**:

    - `refine:<key>` — <his reason>

The backticked `refine:<key>` is what suppresses it. Only Matt declines. You don't decline
an item because it is hard.

## Finish

    mem refine queue --limit 0          # report: N items before, M after
    mem render && mem audit --scan store --refine

No new audit errors. Report what was done per item, what was asked and is waiting on
Matt, and the queue length before and after. The store commits itself at session end.
