---
name: memory-migrate
description: Migrate one memory territory from the legacy per-directory silos (~/.claude/projects/*/memory) into the machine-local store, incrementally and safely. Use when consolidating scattered project memory, when mem status shows pending silos, or when a repo's memory should move into a shared territory.
---

# memory-migrate

Moves ONE territory at a time out of the legacy per-directory silos. One territory per
invocation. Do not batch: a half-migrated store is worse than either end state, because
ambiguity about where a memory lives is the disease being cured.

## Before doing anything

Read `docs/migration.md` and follow its nine steps in order. For several silos at once,
use fast adoption instead (`docs/fast-adoption.md`, `mem migrate`).

**This machine's map is the store itself**: `~/.claude/memory/MACHINE.md` and `ROUTER.md`
say what territories exist and how they relate. Then read `docs/format-spec.md` for the
field rules.
Then:

    mem status
    mem audit --scan legacy --json > /tmp/before.json

Keep `/tmp/before.json`. It is what proves nothing was lost.

If Matt did not name a territory, propose one from the migration doc's ordering and
confirm before moving anything.

## The invariant, which is not negotiable

Every silo is in exactly one of three states at any instant: **not yet reviewed**,
**migrated** (memory dir is a symlink, no local knowledge), or **archived**. Never a mix.
`silo-mixed-state` in the audit is a stop-work error.

**Archive is a completed verdict, not a skip.** A silo whose working directory no longer
exists archives cleanly and is done.

## The judgment step

Step 4 of the doc is per-file and does not automate. Five verdicts: **keep**, **merge**,
**promote** (to `standing/`, `GATES.md`, `MACHINE.md` or an export), **relocate**, **archive**.

**Relocate** is the one people miss. A silo often holds facts about a *different* repo whose
territory is still pending. Those do not belong in this territory and are not retired, so
archiving hides live knowledge and keeping them mis-files it. **Write them into the other
repo's pending silo instead** — that silo stays cleanly `pending`, the facts migrate with it
later, and the invariant holds at both ends. **Check the destination first**: it may already
hold a fresher account, in which case what you are carrying is superseded and should not go.
When a **merge** replaces store memories with one new memory, the new one declares
`supersedes:` for each (`mem supersede <old> <new>`) rather than editing or deleting the
old ones; `mem history` then shows where the knowledge went.

While reading every file, actively hunt four things:

- **Descriptions that name a subject instead of a conclusion.** Rewrite them. The router
  loads every session; a hook that only names a topic forces a file open to find out
  whether it matters.
- **Filenames that now lie.** `project-postgres-unreachable.md` whose hook says
  RESOLVED is worse than no file. Rename it.
- **Snapshots that point at a live source.** A memory that says "as of <date>, phase 9C is
  landed" *and also* "re-read PLAN.md before trusting this" is two things, and only the
  second is a memory. The snapshot half rots and then gets quoted. Keep the pointer and the
  gate ("never claim this roadmap is complete — it has been wrong four times"), drop the
  dated state. The source is authoritative; that is the whole point of naming it.
- **Build diaries.** Per-phase or per-PR "what landed" blocks for shipped work are git's job.
  One real file went 14.5 KB → 4.3 KB with nothing load-bearing lost: the design rationale,
  the baked decisions, the one post-ship bug and two reusable traps stayed; five
  "Build status: Phase N done (commit X)" blocks went. Watch for `Earlier status below`
  layered two or three deep — that is a diary accreting inside one file.

Run `mem fix --write` before moving content. It normalizes slugs, inserts missing
`name:` fields, and rewrites inbound links and router references. Do not pass
`--stamp-today` unless the claims were genuinely just verified: mtime is not evidence, and
a wrong date is worse than a missing one.

## Write the `verify:` recipes DURING the migration, and run them

This is the highest-yield step in the whole procedure and it is easy to treat as paperwork.
Writing a check forces you to name what would falsify the memory, and running it then
checks the world instead of the file. Two consecutive migrations found stale claims this
way and no other way: a fix described as "uncommitted, in the working tree" had merged
weeks earlier; a status memory claimed a HEAD four PRs behind; an open question had been
answered by a CI run nobody had looked at; a memory sent readers to a log directory holding
a two-week-old run.

Three traps, all of which actually happened:

- **A recipe can fail in the reassuring direction.** One checked git history for a filename
  *guessed from prose that never named the file*. It returned empty, which the `expect:`
  line read as "already cleaned up" — when in fact three files were still there under
  different names. **Build a recipe from an identifier you have verified exists**, and write
  `expect:` so it says which result means trouble, not just which means fine.
- **A refused recipe is worse than no recipe.** `grep` is not on the allowlist and `&&` is a
  metacharacter, so those recipes are **refused outright** — the memory then advertises a
  check it does not have. `verify-refused` in the audit is that, not a lint nit.
- **Not every live memory can have one.** Say so explicitly with `unrunnable: true` plus a
  prose check in the body, rather than leaving the field off and hoping. A memory about a
  hosted page, or one needing two JSON files diffed, is honestly unrunnable.

## Does this subject want its own territory?

Comes up whenever a silo is large or its subject already has memories elsewhere. Folding in
is the default — a territory is a router, not a load unit, and splitting for size alone is
wrong. Split when **two or more** of these hold:

1. **The subject already has two homes.** Part of it migrated earlier and the rest is still
   in a silo, so one project's newest and oldest accounts sit in different files. This is the
   ambiguity the whole migration exists to end, so it must be resolved either way — and if
   the older home holds the *staler* half, that is the signal.
2. **The host territory does a different job.** A conventions territory (shared build shape,
   upstream API ground truth) and a product with its own phase stack, decision log and
   measurement corpus are not the same kind of thing. Mixing them degrades both routers.
3. **Mode mismatch.** A `parked`-dominated territory is read with a different posture than an
   `active` one. The single live project inside a cluster of shelved ones is misread by
   inheriting their framing.
4. **Size.** Last and weakest, and never sufficient alone.

When you do split, the edge usually becomes a real `consumes:` declaration rather than a
guess — which is worth checking, because `mem.py` then enforces the upstream contract.

**A territory with no members is legitimate.** If the subject is a *shape* shared by repos
that live in several other territories, there is no checkout to point at it. Give it
`members: {}` and reach it with a pointer from a standing directive — the directive carries
the routing rule, the territory carries the detail. Same pattern as a library that lives
outside the store entirely.

## Do not

- Move more than one territory per invocation.
- Delete a legacy silo. `mv` to `memory.premigration`.
- Invent facts to fill a gap. A gap goes in `RETRO.md` under Pending.
- **Add an export to `ROUTER.md`.** Only a `utility/*` export belongs there. Everything else
  is inlined into the territory that declares `consumes:` it, and an irreversible-harm rule
  goes in `GATES.md` (capped at five). See `format-spec.md`.
- **Grow the always-loaded layer without checking what it costs.** Run
  `mem budget` after touching `MACHINE.md`, `GATES.md`, `ROUTER.md` or
  `standing/`. A territory's own `MEMORY.md` is free; those four are not.
- Commit. Report what changed and leave it in the working tree.

## Finish by reporting

- the territory, and every silo whose state changed
- verdict counts: kept, merged, promoted, archived
- audit before and after, with any error that survives and why
- what you deliberately declined, appended to `RETRO.md` with the reason
