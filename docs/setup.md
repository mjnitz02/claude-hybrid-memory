# Setup: standing up the store on a machine

Run once per machine. Nothing here is shared between machines except this repo.

Prerequisites: this repo cloned, `uv` available, Claude Code CLI 2.1.260 or later.

## The short path: `make install`

From the repo root:

    make install-check    # what would change; writes nothing
    make install

It runs `uv tool install -e . --reinstall` (step 3's install), then `mem install`, which
does steps 1, 1b, 2 and the settings half of 3 to 3c: it creates the store directories,
copies each template that is missing, gives the store its own history with a baseline
commit, symlinks the skills, and merges the three hooks into `~/.claude/settings.json`.
Running `make install` is the go-ahead for step 1b.

Every step looks before it changes anything, so it is also the repair: re-run it after a
`pyproject.toml` dependency change, or when anything below has drifted. What is already
right is reported and left alone. It never overwrites a store file, never replaces a skill
directory that is not a symlink, refuses to `git init` a store sitting inside another
checkout, and leaves a `settings.json` it cannot parse untouched. Before it rewrites
`settings.json` it writes `settings.json.bak-<timestamp>` beside it. Only `mem` entries are
changed; any other hook, including one sharing a group with a `mem` hook, stays as it was.

Then it runs the checks under steps 3 to 3c itself: each hook is run as Claude Code will
run it, against a throwaway copy of the store, so nothing real is logged or committed.
Every hook fails open, so each check looks for the hook's effect, not its exit code:
session-start must hand over a non-empty context under the harness's 10,000-char limit and
render `ALWAYS.md`, post-tool must log a memory read and
print nothing, and session-end must commit a probe file left in the copy. A failure is an
error, and `make install` exits non-zero. `--dry-run` runs no hook.

It also checks that `~/.claude/CLAUDE.md` carries the store's git exception beside the git
rule (`direction.md` §16.1), and warns if it does not. It never writes that file: paste
`templates/CLAUDE-git-exception.md` under the rule yourself. The same goes for the import
of the always-loaded layer (step 3d): it warns when the line is missing and never adds it.

It does not edit `MACHINE.md` (it warns when it has just copied the template), and it does
not do steps 4 and 5. Finish with `mem audit`. The manual steps stay documented below;
they are what `mem install` does.

## 1. Create the store

    mkdir -p ~/.claude/memory/{standing,territories,archive}
    cd <this repo>
    cp templates/MACHINE.md  ~/.claude/memory/MACHINE.md
    cp templates/GATES.md    ~/.claude/memory/GATES.md
    cp templates/ROUTER.md   ~/.claude/memory/ROUTER.md
    cp templates/RETRO.md    ~/.claude/memory/RETRO.md

Then edit `MACHINE.md`: set the machine name, and record any calibration that is true of
this box and not the other one. The point of the file is that a memory never has to guess
which machine it is on.

## 1b. Give the store its own history

The store is a git repository of its own: one repo at the store root, not one per
territory, so a memory that moves between territories or into `archive/` keeps its history
as a rename. It has **no remote, ever** — memory content does not cross machines. History is
what lets a correction replace text instead of piling up beside it (`direction.md` §6).

    cd ~/.claude/memory
    git init
    printf '.cache/\n.DS_Store\n.bm25-index.json\n' > .gitignore
    git add -A
    git commit -m "Baseline: store as of <date>, before mem tooling"

`.cache/` holds the SQLite index, which is always rebuildable and never committed.
`events/` is deliberately *not* ignored: usage history is committed with the store.

Check first that nothing above the store is already a repo (`git -C ~/.claude/memory
rev-parse --show-toplevel` should fail). After this, `mem` commits the store on its own
at the end of every session (step 3c); that is the one carve-out from the git rule in `~/.claude/CLAUDE.md`,
and it covers this directory only. The `init` and baseline above are a setup step, run by
the user or on their go-ahead.

## 2. Link the skills

Symlinked rather than copied, so editing this repo changes live behavior immediately.

    mkdir -p ~/.claude/skills
    for s in memory-setup memory-migrate memory-retro memory-refine memory-restructure; do
      ln -sfn "$PWD/skills/$s" ~/.claude/skills/$s
    done

Verify with `/memory-retro` appearing in the skill list. A plugin was considered and
rejected: it only buys bundled agents, MCP servers, and marketplace distribution, none of
which are wanted here.

## 3. Install the SessionStart hook

The hook is what removes the need for the user to nudge. It renders the always-loaded layer
into `ALWAYS.md` (which `~/.claude/CLAUDE.md` imports, step 3d), names the territory for the
current directory, and says when the retrospective is overdue.

Install the package as a uv tool, from the repo root. The install is editable, so code
changes take effect immediately:

    uv tool install -e .

This puts `mem` at `~/.local/bin/mem`. **An editable install does not pick up dependency
changes.** After any change to `dependencies` in `pyproject.toml`, re-run:

    uv tool install -e . --reinstall

Skipping that is silent: the hook swallows the `ImportError` and every session starts with
no router.

Add to `~/.claude/settings.json`, with the absolute path, because the hook's `PATH` may not
include `~/.local/bin`:

    "hooks": {
      "SessionStart": [
        {
          "matcher": "startup|resume|clear|compact",
          "hooks": [
            {
              "type": "command",
              "command": "<absolute path to home>/.local/bin/mem",
              "args": ["hook", "session-start"],
              "timeout": 10,
              "statusMessage": "Loading memory router"
            }
          ]
        }
      ]
    }

If `settings.json` already has a `hooks` object, merge into it rather than replacing it.

Measured on the first machine (2026-10-21): about 17 ms, against 23 ms for the old
`/usr/bin/python3 tools/session_start.py`, mostly because the tool runs on Python 3.13 rather
than the system 3.9. `uv run --project <repo>` was the self-healing alternative, at about
28 ms; the direct `.venv/bin/mem` path is as fast but lives in a directory `uv sync` rebuilds.

Check it in isolation first, because a broken SessionStart hook affects every session:

    ~/.local/bin/mem hook session-start | head -40

It must exit 0 and print the router. If the store does not exist yet it prints nothing and
exits 0, which is the correct behavior on a machine that has not been set up.

### 3b. The PostToolUse hook (usage events)

Logs a `read` or `write` event to `<store>/events/YYYY-MM.jsonl` whenever a session reads or
writes a memory, refreshes the cache on writes, and hands the session a near-duplicate
note when a NEW memory closely resembles an existing one. For a Bash call it logs every
store path the command names (`read`, `write` or `search`, by heuristic), since most memory
traffic goes through Bash. Add beside `SessionStart` in the same `hooks` object, with no
`statusMessage`, because it fires on every Read, Write, Edit and Bash call in every session:

    "PostToolUse": [
      {
        "matcher": "Read|Write|Edit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "<absolute path to home>/.local/bin/mem",
            "args": ["hook", "post-tool"],
            "timeout": 10
          }
        ]
      }
    ]

Measured on the first machine (2026-10-21), fresh process, JSON on stdin: interpreter start
alone 10 ms; a Read outside the store, which is what nearly every call pays, p95 15 ms; a
memory Read 16 ms; a memory Edit with its reindex 34 ms. A Bash call outside the store
(2026-10-22, after `Bash` joined the matcher) 16 ms p50, 19 ms max: it is rejected on a
substring check before JSON is parsed. The plan's budget is 50 ms p95.
It fails open: any error exits 0 with no output.

Check it in isolation, then confirm a real event lands:

    echo '{"tool_name":"Read","tool_input":{"file_path":"/tmp/x.md"}}' | ~/.local/bin/mem hook post-tool
    head -1 ~/.claude/memory/ROUTER.md >/dev/null    # run from a session: a Bash read
    mem events stats

The first must print nothing and exit 0. The second, run as a Bash call in a session, logs a
`read` with tool `Bash`. After that, `mem events stats` shows it, and the store's git
history provides an exact write count.

### 3c. The SessionEnd hook (the store commits itself)

First re-renders every adopted territory index (`mem render`, `direction.md` Phase 4),
so a description edited in the session reaches its index line. Then it commits everything
the store's `.gitignore` allows, memory and events together, in one
commit with a generated message: the subject counts changes per territory, the body names
the trigger, the session id and every path. It commits only into the store's own `.git`
(a store sitting inside another checkout is skipped, never committed into the parent),
never pushes, and skips when another git operation holds the index lock. A session that
dies before its SessionEnd leaves its changes for the next commit. Add beside the others:

    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "<absolute path to home>/.local/bin/mem",
            "args": ["hook", "session-end"],
            "timeout": 10
          }
        ]
      }
    ]

Measured on the first machine (2026-10-22) against a copy of the store with a day's
backlog: 181 ms, exit 0, no output. Nothing waits on it.

Every other git operation on the store goes through `mem` too, so a session never runs
`git` against it directly. A verb a session needs and `mem` lacks gets added to
`storegit.py`, not worked around:

    mem commit [-m SUBJECT]     # commit now; -m replaces the subject, the body stays generated
    mem log [PATH...] [-n N]    # the store's history, or one file's
    mem diff [PATH...] [--stat] # uncommitted changes, plus untracked new files
    mem show SPEC --at REV      # a memory or any store file as REV had it, deleted ones too
    mem restore PATH... [--from REV]  # files or directories back from REV (default HEAD)
    mem audit --at REV          # any read-only check (links, budget, ...) over REV's tree

Paths may be store-relative or territory-relative (`console/tools/MEMORY.md`). `restore`
commits the store first, so whatever it overwrites stays in history. It never deletes a
file added since REV, and if any path is missing at REV it writes nothing. `--at` exports
the tree to a temporary directory outside the store, with no checkout or worktree, and
reports the live store's paths, so the before and after compare line for line.

Check it on a copy, so the real store is not committed by the check:

    cp -R ~/.claude/memory /tmp/store-check
    echo '{}' | CLAUDE_MEMORY_STORE=/tmp/store-check ~/.local/bin/mem hook session-end
    git -C /tmp/store-check log -1 --stat; rm -rf /tmp/store-check


### 3d. Import the always-loaded layer from CLAUDE.md

**The layer reaches a session through `~/.claude/CLAUDE.md`, not through the hook.** Claude
Code saves any single hook output over 10,000 characters to a file and shows the model only
its first 2 KB (2.1.309, `yhe()`, `bri=1e4`). The layer is ~25 KB, so between 2026-10-01 and
2026-10-23 every session got the opening of `MACHINE.md` and none of the gates, standing
directives or router. A CLAUDE.md import is loaded whole (the cap there is 4 MB per file), and
it reaches subagents too.

So `mem` renders `MACHINE.md` + `GATES.md` + `standing/` + `ROUTER.md` into
`~/.claude/memory/ALWAYS.md`, in the hook's degrade order. It re-renders at every session start,
on `mem render`, and at session end. The file is generated and gitignored in the store; edit
its sources. Append `templates/CLAUDE-memory-import.md` to `~/.claude/CLAUDE.md`, which ends
with the line that matters:

    @~/.claude/memory/ALWAYS.md

The hook now prints only the `MEMORY STATUS` block, a few hundred characters. If the import is
missing, the first status line says that the layer is not in context. If `ALWAYS.md` was stale
and had to be re-rendered at session start, it says so, because CLAUDE.md may have loaded the old copy.

Verify in a fresh session, not just with `mem budget`. Ask it to quote the last bullet in
`GATES.md`, without tools:

    echo "Without tools, quote the last GATES bullet verbatim." | claude -p --tools ""

`mem budget` errors (`budget-not-imported`) when the line is missing, and
(`budget-hook-output`) when the hook's own output passes 10,000 characters. After a Claude
Code upgrade, re-read the threshold from the binary:

    strings -n 6 "$(realpath "$(which claude)")" | rg -o 'async function yhe\(.{0,80}'
    strings -n 6 "$(realpath "$(which claude)")" | rg -o '[,; ]bri=[^,;]{1,20}'

Done on the first machine 2026-10-23: the section was appended by hand, and a fresh
`claude -p` session quoted a gate and the router's last entry verbatim,
with no persisted-output preview.

## 4. Create the first territory

**Most machines should skip steps 4 and 5 and use fast adoption instead:**
`mem migrate inventory | summarize | map | apply` lands every existing silo at once, with one
checkpoint to approve the territory map (`fast-adoption.md`). The manual route below is for
standing up one territory by hand.

Pick one. A good first move is the largest self-contained silo whose exports every other
territory needs, such as a dependency-policy repo:

    T=~/.claude/memory/territories/utility/dep-policy
    mkdir -p "$T"
    cp templates/territory-MEMORY.md "$T/MEMORY.md"
    cp templates/EXPORTS.md          "$T/EXPORTS.md"

Fill in the frontmatter (`territory`, `layer`, `consumes`, `consumed_by`, `members`) and
the gates. Then migrate content into it with `/memory-migrate`, which is a separate
procedure: see `migration.md`.

## 5. Point repos at the territory

Preferred, because it leaves no footprint inside a repo you do not own:

    SILO=~/.claude/projects/-Users-alice-workspaces-dep-policy
    mv "$SILO/memory" "$SILO/memory.premigration"
    ln -s ~/.claude/memory/territories/utility/dep-policy "$SILO/memory"

Keep `memory.premigration` until the retrospective after the migration confirms nothing
was lost. It is the rollback.

The alternative, when the mapping should be explicit and reviewable in the repo, is
`autoMemoryDirectory` in that repo's `.claude/settings.local.json`. Confirm the repo
gitignores that file first.

## 6. Verify

    mem audit

Expect errors on anything not yet migrated. What matters at this stage:

- no `silo-mixed-state` findings, which would mean a slug lives in two homes at once
- `silo-migrated` lines for whatever was linked in step 5
- `budget` inside the cap

## Ordering note

Steps 1 through 3, including 1b, are safe and reversible. Step 5 changes where a session reads memory
from, so do it for one territory, work in that repo for a day, and only then continue.
