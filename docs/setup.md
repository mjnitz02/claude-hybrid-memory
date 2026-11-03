# Setup: standing up the store on a machine

Run once per machine. Nothing here is shared between machines except this repo.

Prerequisites: `uv` available, Claude Code 2.1.275 or later, and the `hybrid-memory` plugin
(the plugin layout is described under "The plugin" below).

## The short path: the plugin, then `mem install`

    claude plugin install hybrid-memory --marketplace mjnitz02/claude-hybrid-memory

That installs the hooks (steps 3 to 3c) and the skills (step 2). The next session reports
that memory is not set up and offers the `memory-setup` skill, which runs `mem install`
(`--dry-run` first to show what would change). `mem install` does steps 1, 1b and 3d: it
creates the store directories, copies each template that is missing, gives the store its
own history with a baseline commit, and writes the rules file. Running it is the go-ahead
for step 1b.

To work on the repo instead, `make install` from a checkout runs `mem install --dev`. That
also symlinks the checkout to `~/.claude/skills/hybrid-memory`, which Claude Code loads as
`hybrid-memory@skills-dir`, so edits are live (`make install-check` is the dry run).

Every step looks before it changes anything, so it is also the repair: re-run it when
anything below has drifted. What is already right is reported and left alone. It never
overwrites a store file and refuses to `git init` a store sitting inside another checkout.

**A machine set up before the plugin** has `mem` hooks in `~/.claude/settings.json` and one
symlink per skill in `~/.claude/skills`. With the plugin there as well, each would run
twice, so once `mem install` sees the plugin (installed from a marketplace, or the dev link)
it removes them. It writes `settings.json.bak-<timestamp>` first, changes only `mem`
entries (any other hook, including one sharing a group with a `mem` hook, stays as it was),
leaves a `settings.json` it cannot parse untouched, and removes a skill only when it is a
symlink to a `skills/` directory. Without the plugin it leaves them alone and warns,
because removing them would leave no hooks at all.

Then it runs the checks under steps 3 to 3c itself: each hook is run as Claude Code will
run it, through `bin/mem`, against a throwaway copy of the store, so nothing real is logged
or committed. Every hook fails open, so each check looks for the hook's effect, not its
exit code: session-start must hand over a non-empty context under the harness's
10,000-char limit and render `ALWAYS.md`, post-tool must log a memory read and print
nothing, and session-end must commit a probe file left in the copy. A failure is an error,
and `mem install` exits non-zero. `--dry-run` runs no hook.

It writes `~/.claude/rules/claude-hybrid-memory.md`, the import of the always-loaded layer
(step 3d). `mem` owns that file and rewrites it if it drifts. It never writes
`~/.claude/CLAUDE.md`; it reads it only to warn when it imports the layer too, which loads
it twice. No git exception is needed there any more (`direction.md` §16.1, amended
2026-11-03): sessions never run `git` on the store, only `mem`.

It does not edit `MACHINE.md` (it warns when it has just copied the template), and it does
not do steps 4 and 5. Finish with `mem audit`. The manual steps stay documented below;
they are what `mem install` does, or what the plugin provides.

## The plugin

The repo is both the plugin and its own marketplace (`.claude-plugin/plugin.json` and
`marketplace.json`, both named `hybrid-memory`; a name starting `claude-` is reserved for
Anthropic's own, so `claude plugin validate` refuses it). The plugin has **no `version`**:
Claude Code then versions it by commit sha, so every commit on `main` is a release and
there is nothing to bump (checked 2026-11-03: `claude plugin update` moved an install from
one commit's sha to the next). Users update with `claude plugin update
hybrid-memory@hybrid-memory`, or turn on auto-update for the marketplace in `/plugin`.

- `hooks/hooks.json` declares the three hooks, each running `"${CLAUDE_PLUGIN_ROOT}/bin/mem"
  hook <name>`. `tests/test_plugin.py` holds it to `install.HOOKS`.
- `skills/` is discovered as the plugin's skills, namespaced: `/hybrid-memory:memory-setup`.
- `bin/mem` is a POSIX shim, and Claude Code puts `bin/` on the Bash tool's PATH, so
  sessions call `mem` as before. The Bash tool's shell gets no `CLAUDE_PLUGIN_*` variables,
  so the shim finds its root from `$0`. It keeps one venv at
  `${XDG_CACHE_HOME:-~/.cache}/claude-hybrid-memory/venv`: not in the store (creating that
  would make an unset-up store look set up) and not in `CLAUDE_PLUGIN_DATA` (absent in Bash
  calls, and named per install source). A stamp records the root the venv was built for;
  when it matches and `uv.lock` is not newer, the shim execs the venv's `mem` directly.
  Otherwise it runs `uv sync --frozen` first, which is also what picks up a dependency
  change, and what happens once after each plugin update. With no uv, the session-start
  hook says so and every other hook exits 0 silently.
- `prompts/` holds what `mem` hands to `claude -p`. It is not `agents/`, which a plugin
  loads as subagents.

Outside Claude Code, `mem` is not on the PATH. For a terminal `mem`, run
`uv tool install -e .` in a clone. Editable matters: `mem` finds `templates/` and `prompts/`
relative to its source.

Run `claude plugin validate .` by hand when the plugin files change; CI runs only
`tests/test_plugin.py`, so it needs no Claude CLI. The expected warnings are the missing
`version` and, on a working tree, an untracked `.DS_Store`.

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
at the end of every session (step 3c), and sessions reach its history only through `mem
commit | log | diff | restore | revert`, never `git`. The `init` and baseline above are a
setup step, run by the user or on their go-ahead.

## 2. The skills

The plugin ships `skills/`; nothing is linked. Verify with `/hybrid-memory:memory-retro`
in the skill list. Until 2026-11-03 each skill was symlinked into `~/.claude/skills`, and a
plugin had been rejected because it "only buys marketplace distribution", which was not
wanted until the repo went public. `mem install` removes those links once the plugin is
present (see the short path).

## 3. The SessionStart hook

The hook is what removes the need for the user to nudge. It renders the always-loaded layer
into `ALWAYS.md` (which the rules file imports, step 3d), names the territory for the
current directory, and says when the retrospective is overdue. When the store is missing,
has no history, or the layer is not imported, it says so in one line and points the session
at the `memory-setup` skill.

`hooks/hooks.json` declares it, with a 60 s timeout because the first call after an
install or update may build the venv (the other two hooks keep 10 s).

Measured on the first machine (2026-10-21), as a uv tool: about 17 ms, against 23 ms for the
old `/usr/bin/python3 tools/session_start.py`, mostly because the tool runs on Python 3.13
rather than the system 3.9. Through the plugin shim (2026-11-03), post-tool on a Read
outside the store: p50 17.7 ms against 14.6 ms for the uv tool binary on the same box.

Check it in isolation first, because a broken SessionStart hook affects every session:

    mem hook session-start | head -40     # from a session; or <checkout>/bin/mem

It must exit 0 and print the status. If the store does not exist yet it prints a
one-line "not set up" status and exits 0.

### 3b. The PostToolUse hook (usage events)

Logs a `read` or `write` event to `<store>/events/YYYY-MM.jsonl` whenever a session reads or
writes a memory, refreshes the cache on writes, and hands the session a near-duplicate
note when a NEW memory closely resembles an existing one. A Write or Edit into a rendered
territory re-renders its index, so a memory written the harness's way still gets its line.
For a Bash call it logs every
store path the command names (`read`, `write` or `search`, by heuristic), since most memory
traffic goes through Bash. It has no `statusMessage`, because it fires on every Read,
Write, Edit and Bash call in every session.

Measured on the first machine (2026-10-21), fresh process, JSON on stdin: interpreter start
alone 10 ms; a Read outside the store, which is what nearly every call pays, p95 15 ms; a
memory Read 16 ms; a memory Edit with its reindex 34 ms. A Bash call outside the store
(2026-10-22, after `Bash` joined the matcher) 16 ms p50, 19 ms max: it is rejected on a
substring check before JSON is parsed. The plan's budget is 50 ms p95.
It fails open: any error exits 0 with no output.

Check it in isolation, then confirm a real event lands:

    echo '{"tool_name":"Read","tool_input":{"file_path":"/tmp/x.md"}}' | mem hook post-tool
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
dies before its SessionEnd leaves its changes for the next commit.

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
    mem revert SHA...           # undo store commits as new commits, e.g. a --write checkpoint
    mem audit --at REV          # any read-only check (links, budget, ...) over REV's tree

Paths may be store-relative or territory-relative (`console/tools/MEMORY.md`). `restore`
commits the store first, so whatever it overwrites stays in history. It never deletes a
file added since REV, and if any path is missing at REV it writes nothing. `--at` exports
the tree to a temporary directory outside the store, with no checkout or worktree, and
reports the live store's paths, so the before and after compare line for line.

Check it on a copy, so the real store is not committed by the check:

    cp -R ~/.claude/memory /tmp/store-check
    echo '{}' | CLAUDE_MEMORY_STORE=/tmp/store-check mem hook session-end
    git -C /tmp/store-check log -1 --stat; rm -rf /tmp/store-check


### 3d. Import the always-loaded layer from a rules file

**The layer reaches a session through a memory-file import, not through the hook.** Claude
Code saves any single hook output over 10,000 characters to a file and shows the model only
its first 2 KB (2.1.309, `yhe()`, `bri=1e4`). The layer is ~25 KB, so between 2026-10-01 and
2026-10-23 every session got the opening of `MACHINE.md` and none of the gates, standing
directives or router. A memory-file import is loaded whole (the cap there is 4 MB per file).

So `mem` renders `MACHINE.md` + `GATES.md` + `standing/` + `ROUTER.md` into
`~/.claude/memory/ALWAYS.md`, in the hook's degrade order. It re-renders at every session start,
on `mem render`, and at session end. The file is generated and gitignored in the store; edit
its sources. `mem install` writes `~/.claude/rules/claude-hybrid-memory.md`, whose line that
matters is:

    @~/.claude/memory/ALWAYS.md

A user-level rules file with no `paths:` frontmatter loads in every session, imports included
(checked on 2.1.317, 2026-11-03), so nobody's `CLAUDE.md` is edited. Until then the line was
pasted into `~/.claude/CLAUDE.md`. That still counts, but with the rules file as well the layer
loads twice, so `mem install` and `mem budget` warn (`budget-imported-twice`): delete the
`# Memory` block from `CLAUDE.md`.
The hook now prints only the `MEMORY STATUS` block, a few hundred characters. If the import is
missing, the first status line says that the layer is not in context. If `ALWAYS.md` was stale
and had to be re-rendered at session start, it says so, because the session may have loaded the old copy.

Verify in a fresh session, not just with `mem budget`. Ask it to quote the last bullet in
`GATES.md`, without tools:

    echo "Without tools, quote the last GATES bullet verbatim." | claude -p --tools ""

`mem budget` errors (`budget-not-imported`) when nothing imports the layer, and
(`budget-hook-output`) when the hook's own output passes 10,000 characters. After a Claude
Code upgrade, re-read the threshold from the binary:

    strings -n 6 "$(realpath "$(which claude)")" | rg -o 'async function yhe\(.{0,80}'
    strings -n 6 "$(realpath "$(which claude)")" | rg -o '[,; ]bri=[^,;]{1,20}'

Done on the first machine 2026-10-23: the section was appended by hand, and a fresh
`claude -p` session quoted a gate and the router's last entry verbatim,
with no persisted-output preview. Moved to the rules file 2026-11-03.

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
