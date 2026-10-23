---
name: memory-restructure
description: Merge two memory territories, split one in two, or dissolve one into others, by composing mem mv, mem mv-territory and mem archive. Use when Matt asks to merge, split, combine, break up, dissolve or reorganize territories, or when a retrospective finds a territory that is the wrong shape.
---

# memory-restructure

Three reshapes the store has no single command for. Each one is a short sequence of
commands that already exist, plus a little hand editing of index prose that no command
can judge. The commands do the mechanics: files, indexes, router entries, `consumes:`,
`supersedes:` refs and silo links. You do the judgment: which memories go where, and how
two index heads become one.

For a plain rename or a move to another area, skip this skill and run
`mem mv-territory OLD NEW` directly.

## Before doing anything

Read the restructuring section of `docs/format-spec.md` (`mem mv-territory`, `mem mv`,
`mem archive`). Then:

    mem status
    mem audit --scan store

Note any existing errors. The commands report only errors they introduce, so you need the
baseline to tell the two apart.

**Show Matt the plan before any `--write`.** A reshape changes what every linked repo loads
at session start. Bring: which memories move where, which silos get relinked, and what
happens to each index head. Every command without `--write` is a dry run, so paste its
output as part of the plan.

## Rules for every recipe

- **Write to the store with a script** (python/perl/sed on `~/.claude/memory/...`), not
  Edit or Write: the harness rewrites frontmatter on memory paths. That includes indexes.
- **One command at a time, dry run first.** Each `--write` makes its own checkpoint commit,
  so each step can be reverted on its own.
- **Archiving needs Matt's reason**, in his words, for `--why`. Do not write one for him.
- **A territory's head is prose.** Its intro, its GATES section and `EXPORTS.md` never move
  on their own. Merge them by hand, and say what you dropped and why.
- **Undo** is `git -C ~/.claude/memory revert <checkpoint>` for the step, then `mem link`
  for any silo it unlinked. Every command prints its own undo line; keep it.

## Merge B into A

B disappears. Its memories, members and repos all become A's.

1. **Merge the heads.** Fold B's intro and GATES into A's index. Add B's `members:` entries
   to A's frontmatter. Union `consumes:` and `consumed_by:`, dropping A and B themselves.
   If B has an `EXPORTS.md`, merge it into A's.
2. **Move the memories:**

       ls ~/.claude/memory/territories/B/                  # every .md but MEMORY.md, EXPORTS.md
       mem mv <each B slug> A
       mem mv <each B slug> A --write

3. **Retire B's index:**

       mem archive B --why "<Matt's reason>"
       mem archive B --why "<Matt's reason>" --write

   This removes B's router entry, drops B from other territories' `consumes:`, and unlinks
   B's silos. The output lists each one.
4. **Relink each silo it listed** to A:

       mem link --territory A --dir <that repo's checkout> --write

5. **Fix the router line.** A's ROUTER.md entry now has to cover B's repos and B's
   `PULL WHEN`. Edit it by hand.

## Split A into A and C

C is new. Some of A's memories, and the repos they belong to, go there.

1. **Create C.** Write `territories/C/MEMORY.md` with the four frontmatter fields
   (`territory`, `consumes`, `consumed_by`, `members`), a one-paragraph intro and an empty
   `## MEMORIES` section. Copy the shape of an existing index. Add C's ROUTER.md entry under
   its area, with a `PULL WHEN`. Then set `consumes:`/`consumed_by:` between A and C, both
   sides, if one depends on the other.
2. **Move the memories:**

       mem mv <slugs> C
       mem mv <slugs> C --write

   A `role: gate` memory warns: its rule is also inlined in A's GATES section. Move that
   text to C's head by hand.
3. **Move the members.** Each repo that belongs to C leaves A's `members:` and joins C's.
   Its silo still points at A, and `mem link` will not repoint a live link on its own.
   Remove the symlink, then link:

       rm ~/.claude/projects/<silo>/memory                 # a symlink: no -r, no trailing slash
       mem link --territory C --dir <that repo's checkout> --write

4. **Narrow A's router line** so it stops claiming what C now owns.

## Dissolve A into others

A disappears and nothing replaces it. Each memory goes to an existing territory or retires.

1. **Decide every memory's fate** and show Matt a table: slug, destination or "archive",
   and one line of why. Do this before running anything.
2. **Move the keepers**, one `mem mv` per destination, dry run then `--write`. Move GATES
   text along with any gate memory.
3. **Archive the rest with the territory.** Whatever is still in A goes in one call, index
   included:

       mem archive A --why "<Matt's reason>"
       mem archive A --why "<Matt's reason>" --write

   Do not archive the leftover memories on their own first. That claims the default
   `archive/<area>-<name>/` group, and the territory archive then refuses to reuse it.
4. **Relink each silo it listed** to the territory its repo now belongs to with
   `mem link --territory <T> --dir <checkout> --write`, and add the repo to that
   territory's `members:`. A repo with no home stays unlinked; say so.

## Finish

    mem render && mem audit --scan store
    mem status

No new audit errors, and no `silo-dangling` in status. Report what moved where, which
silos were relinked or left unlinked, what head prose was merged or dropped, and the
checkpoint commits. Then update the routers' `PULL WHEN` text if the reshape changed what
a territory is for. The store commits itself at session end.
