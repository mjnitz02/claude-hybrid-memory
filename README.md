<p align="center">
  <img src="assets/banner.jpg" alt="Claude Hybrid Memory" width="800">
</p>

<p align="center">
  <a href="https://github.com/mjnitz02/claude-hybrid-memory/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mjnitz02/claude-hybrid-memory/ci.yml?branch=main&label=tests" alt="Tests"></a>
  <a href="https://github.com/mjnitz02/claude-hybrid-memory/actions/workflows/codeql.yml"><img src="https://img.shields.io/github/actions/workflow/status/mjnitz02/claude-hybrid-memory/codeql.yml?branch=main&label=codeql" alt="CodeQL"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/mjnitz02/claude-hybrid-memory" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-3670A0?logo=python&logoColor=ffdd54" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Claude%20Code-2.1.260%2B-D97757" alt="Claude Code 2.1.260+">
</p>

<p align="center">
  <a href="docs/README.md">Docs</a> ·
  <a href="docs/overview.md">How it works</a> ·
  <a href="docs/commands.md">Command reference</a> ·
  <a href="docs/setup.md">Manual setup</a>
</p>

A memory system for [Claude Code](https://docs.claude.com/en/docs/claude-code). It replaces
Claude Code's per-directory memory folders with one store per machine, organised by
*territory* instead of by folder, with a `mem` CLI and three hooks that keep it accurate.
Memories stay plain markdown.

## Is it for you?

**It probably is if:**

- your work spans many repos, and memory written in one never reaches the others
- the same instruction ("use `uv`", "never push to main") is copied into a dozen memory folders
- you can't tell which memories are still true and which went stale months ago

**What it does:**

- **Territories, not directories.** Several repos share one memory home, and Claude Code
  still auto-loads it with no custom loader.
- **An always-loaded layer.** A machine profile, up to five hard rules, standing
  directives and a one-line-per-territory router reach every session, inside a fixed budget.
- **Freshness you can check.** A memory can carry a `verify:` recipe that `mem` runs to
  confirm it is still true.
- **History, not edits.** The store is its own local git repo, committed at the end of
  every session. It never has a remote.

**It probably isn't if** you work in one or two repos, or want memory synced across
machines. Content is machine-local by design.

## Quick start

**Needs:** macOS or Linux, `git`, [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12+
if you don't have it), and Claude Code 2.1.260 or later.

```sh
git clone https://github.com/mjnitz02/claude-hybrid-memory.git
cd claude-hybrid-memory
make install
cat templates/CLAUDE-memory-import.md >> ~/.claude/CLAUDE.md
```

`make install` installs `mem`, creates the store at `~/.claude/memory/`, links the skills
and adds the hooks to `~/.claude/settings.json` (backing it up first). It is safe to re-run.
The last line imports the always-loaded layer into every session. Keep the clone: `mem` and
the skills run from it.

Then name your machine in `~/.claude/memory/MACHINE.md`, and bring in the memory you
already have:

```sh
mem migrate inventory   # find existing memory folders
mem migrate summarize   # summarise each file with Claude (calls `claude -p`)
mem migrate map         # review the proposed territories, then approve
mem migrate apply       # move everything in; `mem migrate undo --silo S` reverts one
mem audit               # check the result
```

> If your `~/.claude/CLAUDE.md` tells Claude never to commit, add
> [`templates/CLAUDE-git-exception.md`](templates/CLAUDE-git-exception.md) under that rule
> so the store can commit itself.

## Day to day

Most of it runs without you: the hooks load the layer, log usage and commit the store.
These are the things you run yourself.

**Skills** (in a Claude Code session):

| | |
|---|---|
| `/memory-refine` | work through the list of memories worth improving, one at a time |
| `/memory-retro` | monthly check that memories are still true and still findable; the session tells you when it's due |
| `/memory-restructure` | merge, split or dissolve territories |
| `/memory-migrate` | move one territory over by hand instead of in bulk |
| `/memory-setup` | stand up or repair the store from inside a session |

**Commands:**

```sh
mem audit             # everything wrong with the store, in one report
mem fix --write       # fix what can be fixed automatically
mem find <terms>      # search memories
mem show <slug>       # read one
mem log               # the store's history
mem restore <path>    # undo a change; never deletes
mem link --territory <path> --write   # reconnect a repo you cloned again
make install          # repair after an update or anything drifting
```

The full list is in [`docs/commands.md`](docs/commands.md).

## Contributing

A single-maintainer project, open in case the approach helps someone. Issues are welcome;
open one before a non-trivial PR. See [CONTRIBUTING](.github/CONTRIBUTING.md).

## License

MIT. See [`LICENSE`](LICENSE).
