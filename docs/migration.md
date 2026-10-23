# Migration: moving memories out of the per-directory silos

> **Superseded for bulk adoption, 2026-10-23, by `fast-adoption.md`**, which reverses
> three rules here: per-file judgment at migration time, writing `verify:` recipes during
> migration, and one territory per invocation. The invariant and the traps below still
> apply, and this procedure remains the way to move one territory by hand.

Run by `/memory-migrate`, one territory at a time. The procedure exists because a
half-migrated store is worse than either end state: ambiguity about where a memory lives
is the original disease.

The corpus counts in this doc come from the first machine migrated: 163 files in 25 silos.

## The invariant

At any instant, every silo is in exactly one of three states. Two are terminal.

| State | Meaning | Detected by |
|---|---|---|
| **not yet reviewed** | knowledge lives in the silo, untouched | `silo-pending` |
| **migrated** | the silo's memory dir is a symlink to a territory; no local knowledge | `silo-migrated` |
| **archived** | content moved to `archive/`; a finished verdict, not a skip | absence |

Never a mix. `mem.py status` reports `silo-mixed-state` as an error when a slug lives both
in a pending silo and in the store.

**Archive is a completed state.** Some silos should never migrate, such as two silos for
a finished project whose directories no longer exist on disk. Without a terminal verdict for those,
the status report would show permanent incompleteness, and permanent incompleteness gets
ignored.

## Order

On a machine whose work is one dependency chain:

1. The `utility/*` territory whose exports everything else needs (a dependency-policy repo,
   say). Largest and self-contained, and doing it first means every later territory can
   reference a real EXPORTS.md.
2. Small `utility/*` territories and `archive/*` verdicts. Quick wins that prove the loop.
3. `chain/*` bottom-up: foundation, components, templates, apps. Bottom-up because a
   layer's EXPORTS.md must exist before the layer below can inline it.
4. `mine/*` and `solo/*`. Lowest stakes, so leave them until the procedure is boring.

On a machine of unrelated bodies of work there are no EXPORTS.md dependencies to sequence
around, and the rule collapses to: largest and most active first, lowest-stakes `solo/*`
last.

## Procedure per territory

### 1. Baseline

    mem audit --scan legacy --json > /tmp/before.json

Keep it. It is what proves nothing was lost.

### 2. Repair mechanics before moving anything

    mem fix --scan legacy            # dry run, read it
    mem fix --scan legacy --write

This normalizes slugs to kebab-case, inserts missing `name:` fields, renames underscore
files, and rewrites inbound `[[links]]` and router references. On the audited corpus it
took 104 errors to 1.

It deliberately does **not** stamp `last_verified`. File mtime is not evidence that a
claim was checked, and a copy or a checkout resets it. A wrong date is worse than a
missing one, because it produces a freshness signal that gets trusted. Use
`--stamp-today` only when the claims were genuinely just verified.

### 3. Create the territory

    T=~/.claude/memory/territories/<path>
    mkdir -p "$T"
    cp templates/territory-MEMORY.md "$T/MEMORY.md"

Fill in frontmatter: `territory`, `layer`, `consumes`, `consumed_by`, and `members` with
each repo's `owner` and `mode`.

### 4. Move content, deciding one of four verdicts per file

This is the judgment step and it does not get automated.

| Verdict | Action |
|---|---|
| **keep** | move into the territory; add `kind`, `volatility` or `status`, and a `verify:` recipe if it is live |
| **merge** | fold into an existing memory, re-date it, and delete the loser |
| **promote** | it is a standing directive: move to `standing/`, or make it an export |
| **archive** | move to `archive/<silo>/`; a completed state |

Two things to actively hunt while reading:

- **Descriptions that name a subject instead of a conclusion.** Rewrite them. "notes on
  the batch command" is worthless in a router; "SHIPPED 2026-07-30, resume dropped, never
  run against the real core-lib" is not.
- **Filenames that now lie.** `project-postgres-unreachable.md` with a hook saying
  RESOLVED. Rename it.

### 5. Write EXPORTS.md, and inline it downstream

Keep it brutally short. If a territory exports more than about six facts, the boundary is
probably wrong.

`utility/*` exports go into `ROUTER.md`, because they bind everywhere. `chain/*` exports
get inlined into the consuming territory's `MEMORY.md`, because they only matter one layer
down.

### 6. Inline the gates

Every memory with `role: gate` has its text copied into the territory `MEMORY.md`, not
merely linked. A gate that is only linked is a soft convention, and soft conventions are
what failed.

### 7. Point the repos, keeping the rollback

    SILO=~/.claude/projects/<slug>
    mv "$SILO/memory" "$SILO/memory.premigration"
    ln -s ~/.claude/memory/territories/<path> "$SILO/memory"

Repeat per repo in the territory. Keep `memory.premigration` until the next retrospective.

### 8. Confirm

    mem audit

Required before calling the territory done:

- zero `silo-mixed-state`
- zero `router-ghost` and zero `dangling-link` in the new territory
- the territory `MEMORY.md` is under 200 lines and 25 KB, the harness auto-load limit
- every `live` memory has a `verify:` recipe, or is explicitly `unrunnable` with a prose check

### 9. Log it

Append to `RETRO.md`: which silos resolved, the verdict counts, and anything deliberately
declined with the reason. A later retrospective reads that log to avoid re-litigating
settled decisions.

## Collisions to expect

Silos that grew independently collide the moment they share a territory. The first
migration found the same directive written twice in a tool's silo and in its predecessor's
(100% description overlap), and a second pair at ~70% overlap with possibly divergent
facts. When one repo succeeds another, the successor's version is likely authoritative.
Verify rather than assume: the older file may hold detail the newer one dropped.

A `[[link]]` to a memory that was never written is the other common find. Either write it
during the migration of its territory or drop the link.
