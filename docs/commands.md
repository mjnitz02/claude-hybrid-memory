# Command reference

`mem` is the `claude_hybrid_memory` package in `src/`, installed as a uv tool by
`make install`. `mem --help` prints this list too. `--json` gives machine output on most
commands. There is one dependency, `pyyaml`, for frontmatter, and it is never on the hook
path.

Exit codes: 0 clean, 1 findings at error level, 2 tool error.

## Checking and repairing

    mem audit                  # everything, one report
    mem audit --refine         # plus the refine-only findings (index size, field vocabulary)
    mem audit --at REV         # any read-only check against the store as a past commit had it
    mem fix --write            # autofix slugs, names, links, router refs
    mem fresh --run            # execute verify: recipes under hard constraints
    mem budget                 # the always-loaded layer, as the hook actually renders it
    mem render --check         # stale or degraded rendered indexes, and any MEMORY.md near the cap
    mem render [TERRITORY]     # re-render territory indexes
    mem render <t> --adopt [--write]   # migrate a hand-written index to a rendered one
    mem install [--dry-run]    # set up or repair the store, its history, skills and hooks

## Reading and writing memories

    mem new <slug> -d DESC [-g GROUP] [-t TERRITORY] < body   # write a memory and index it
    mem find <terms> [--territory T] [--all] [--superseded]   # ranked memories + matching sections
    mem show <slug> [--meta | --section H | --full] [--at REV]
    mem history <slug>         # version chain both ways + the file's git log
    mem supersede <old> <new>  # write `supersedes:` into <new>; <old> is never touched
    mem index [--rebuild]      # refresh the derived cache (find/show do this themselves)
    mem events stats           # usage: reads/writes/searches by tool, hook cost, most-read

## The store's history

The store is its own git repo with no remote. Every git operation on it goes through `mem`.

    mem commit [-m SUBJECT]    # commit now (the SessionEnd hook does this on its own)
    mem log [PATH...] [-n N]   # the store's history, or one file's
    mem diff [PATH...] [--stat]
    mem restore PATH... [--from REV]   # put files back; commits first, never deletes
    mem revert SHA...                  # undo store commits as new commits; commits first

## Moving things around

    mem mv SLUG... TERRITORY [--write]
    mem mv-territory OLD NEW [--write]
    mem archive TERRITORY|SLUG... --why TEXT [--as GROUP] [--write]
    mem link --territory <path> --write   # point a restored repo back at its territory
    mem status                 # migration state per silo

`/memory-restructure` composes these for merges and splits.

## Adoption and refinement

    mem migrate inventory [--source DIR ...]
    mem migrate summarize [--silo S ...] [--jobs N] [--model M] [--force] [--dry-run]
    mem migrate summaries [--silo S ...] [--json]
    mem migrate map [--rebuild] [--approve]
    mem migrate apply [--silo S ...] [--dry-run]
    mem migrate undo --silo S
    mem refine queue [--territory T] [--limit N] [--json]

The process is in [`fast-adoption.md`](fast-adoption.md).

## Hooks

`make install` adds three hooks to `~/.claude/settings.json`:

- `SessionStart` re-renders the always-loaded layer into `ALWAYS.md`, which
  `~/.claude/rules/claude-hybrid-memory.md` imports (a hook's output is cut to a 2 KB preview
  past 10,000 chars, so the layer cannot ride in it). It also names the territory for the
  current directory, reports when the retrospective is overdue, and points at
  `/memory-setup` when the store, its history or the import is missing.
- `PostToolUse` records usage, refreshes the cache on writes, and re-renders a rendered
  territory's index after a Write or Edit into it.
- `SessionEnd` re-renders indexes and commits the store.

To see exactly what a session is handed:

    cat ~/.claude/memory/ALWAYS.md
    mem hook session-start | jq -r .hookSpecificOutput.additionalContext

## Development (`make`)

`make` alone lists the targets.

    make check        # pre-commit (ruff, whitespace, lockfile, secrets) + tests; what CI runs
    make test         # fixture stores: synthetic content, real shapes
    make test-live    # the installed `mem`, read-only, against this machine's real store
    make hooks        # git hooks: lint + secret scan on commit, tests on push
    make install-check   # what `make install` would change, writing nothing
