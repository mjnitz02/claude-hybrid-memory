# claude-hybrid-memory

A memory system for Claude Code. It replaces per-directory memory silos with one
machine-local store: territories with routers, an always-loaded layer with a hard budget,
freshness you can compute, and a `mem` CLI plus hooks that keep it honest.

**Hybrid** because markdown stays the source of truth for knowledge. A derived SQLite
cache, committed usage events and the store's own git history do what markdown is bad at:
search, provenance, version chains and audits over time.

This repo holds **the method**. It does not hold memories.

| | Crosses machines? | Lives where |
|---|---|---|
| Spec, setup, migration, tooling, skills | Yes, via this repo | here |
| Actual memory content | No, deliberately | `~/.claude/memory/`, local git history only, no remote |

## Why this exists

Claude Code's per-project memory works, but it is keyed on directory, and that cuts
straight through the middle of any system spanning many repos. An audit of one machine
found 186 memory files across 25 silos with 435 internal wikilinks and exactly **two** that
crossed a silo boundary, while 64 file-pairs referenced another silo's repo in prose. 104
of them were over a month cold, with no way to tell stable from rotted, and the same
"use `uv`" directive had been written into 11 separate silos.

The format was not the problem. The missing pieces were a router, cross-repo reach, and
computable freshness.

## How it works

    ~/.claude/memory/
      MACHINE.md          # machine identity + calibration      ┐
      GATES.md            # irreversible-harm rules, max 5      │ injected every session
      standing/           # directives true in every repo      │ by the SessionStart hook
      ROUTER.md           # one line per territory + PULL WHEN  ┘
      territories/<path>/
        MEMORY.md         # the territory router, auto-loaded by Claude Code
        EXPORTS.md        # the contract for territories downstream
        <slug>.md         # internals, read on demand
      archive/            # retired, never loaded
      events/             # committed usage history (JSONL)
      .cache/             # derived SQLite + FTS5 index, gitignored

- **Territories, not directories.** A repo's `~/.claude/projects/<slug>/memory` becomes a
  symlink to its territory. Several repos can share one memory home, and Claude Code's own
  auto-load picks it up with no custom loader.
- **Routers, not indexes.** Every entry says *when* to pull it, and every description
  carries the conclusion rather than the subject.
- **A budget that degrades in a declared order.** Gates are never cut. Standing directives
  collapse to their descriptions first, and the map goes last. Every degradation announces
  itself.
- **Freshness you can compute.** `status` implies a volatility window, and a memory can carry
  a `verify:` recipe that `mem fresh --run` executes under hard constraints: allowlisted
  commands, no shell, no mutating subcommands, timeouts.
- **Replace, never edit.** A newer memory declares `supersedes:`. The old one stays
  byte-identical, and git holds the history.

## Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

    git clone https://github.com/mjnitz02/claude-hybrid-memory.git
    cd claude-hybrid-memory
    make install          # installs `mem`, then sets up or repairs the store, skills and hooks

`make install` is idempotent; `make install-check` shows what it would change. Then fill
in `~/.claude/memory/MACHINE.md` and adopt your existing silos with fast adoption:

    mem migrate inventory
    mem migrate summarize
    mem migrate map        # the one checkpoint: review and approve the territory map
    mem migrate apply

Each silo lands in its own pair of commits in the store, and `mem migrate undo --silo S`
reverts one.

## Documents

| Doc | What it is |
|---|---|
| `docs/design.md` | the model, the load path, and the alternatives rejected along the way |
| `docs/format-spec.md` | the definitive format reference. `mem` enforces it. |
| `docs/setup.md` | standing up the store on a machine, step by step |
| `docs/fast-adoption.md` | bulk adoption: a Sonnet summarizer per file, one map checkpoint, land as-is, refine after |
| `docs/migration.md` | moving one territory by hand, and the invariant every migration keeps |
| `docs/self-verification.md` | the retrospective: what is mechanical, what is judgment |
| `docs/direction.md` | the hybrid store: markdown + events + SQLite cache, hooks, and the phased build log |

## Tooling

`mem` is the `claude_hybrid_memory` package in `src/`, installed as a uv tool. `make`
alone lists the other targets.

    mem audit           # everything, one report
    mem fix --write     # autofix slugs, names, links, router refs
    mem fresh --run     # execute verify: recipes under hard constraints
    mem status          # migration state per silo
    mem link --territory <path> --write   # point a restored repo back at its territory
    mem budget          # the always-loaded layer, as the hook actually renders it
    mem find <terms>    # ranked memories + the sections that matched, as path:line
    mem show <slug>     # description + opening paragraph; --meta, --section H, --full; --at REV
    mem history <slug>  # version chain both ways + the file's git log
    mem supersede <old> <new>   # write `supersedes:` into <new>; <old> is never touched
    mem index           # refresh the derived cache (find/show do this themselves); --rebuild
    mem events stats    # usage: reads/writes/searches by tool, hook cost, most-read
    mem commit          # commit the store now (the SessionEnd hook does this on its own)
    mem log / mem diff  # the store's history and uncommitted changes
    mem restore <path>  # put files back from HEAD (or --from REV); commits first, never deletes
    mem audit --at REV  # any read-only check against the store as a past commit had it
    mem render --check  # stale rendered indexes, and any MEMORY.md near the harness's 200 lines / 25 KB
    mem render <t> --adopt [--write]  # migrate a hand-written index to a rendered one
    mem install [--dry-run]  # set up or repair the store, its history, skills and hooks
    mem migrate inventory | summarize | summaries | map | apply | undo   # fast adoption

There is one dependency, `pyyaml`, for frontmatter, and it is never on the hook path.
`--json` gives machine output.

    make check               # pre-commit (ruff, whitespace, lockfile, secrets) + tests; what CI runs
    make test                # fixture stores: synthetic content, real shapes
    make test-live           # the installed `mem`, read-only, against this machine's real store
    make hooks               # git hooks: lint + secret scan on commit, tests on push

Three hooks are installed:
- `SessionStart` injects the always-loaded layer, names the territory for the current
  directory, and reports when the retrospective is overdue.
- `PostToolUse` records usage and reindexes on writes.
- `SessionEnd` re-renders indexes and commits the store.

To see exactly what a session is handed:

    mem hook session-start | jq -r .hookSpecificOutput.additionalContext | head -40

## Skills

`/memory-setup`, `/memory-migrate` and `/memory-retro` are symlinked from `skills/` into
`~/.claude/skills/`, so editing this repo changes live behavior immediately.

## Two rules worth knowing before touching anything

**The format may not make a memory more expensive to write than it is to rediscover.** The
old system's real virtue was that writing a memory was nearly free. Only four fields are
required; everything else is inferred, optional, or autofixed.

**A check that is mostly false positives gets deleted, not tuned.** The wikilink extractor
first reported 11 dangling links, of which 10 were Copier template delimiters. A
word-frequency "standing directive" detector returned words like "how" and "2026". The
first was fixed and the second removed. A category that is mostly noise trains everyone to
ignore the category.

## Status

Built in phases, each with an exit check recorded in `docs/direction.md`. The cache, hooks,
version chains, rendered indexes and fast adoption are built. The refine queue
(`/memory-refine`) is next.

## License

MIT. See `LICENSE`.
