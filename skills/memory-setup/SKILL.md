---
name: memory-setup
description: Stand up or repair the machine-local Claude memory store (~/.claude/memory) - the store's directories and history, the rules file that imports the always-loaded layer, and cleanup of pre-plugin hooks and skill links. Use when setting up a new machine, when the SessionStart hook says memory is not set up, the store has no history, or the layer is not in context, or when the store's scaffolding is broken or missing.
---

# memory-setup

Stands up `~/.claude/memory` on this machine. The store is machine-local: it
may keep a local-only git history, but never a remote shared with another machine; only the
system in the claude-hybrid-memory repo crosses machines.

## Before doing anything

Find the repo: this skill's base directory, two levels up (`<repo>/skills/memory-setup`).
It is the plugin's install path, or a checkout when the plugin is the dev link. Read, in
this order:

1. `docs/setup.md` - the procedure. Follow it, do not improvise around it.
2. `~/.claude/memory/MACHINE.md` and `ROUTER.md`, if the store exists - so territory names
   mean something here.
3. `docs/format-spec.md` - the layout and field rules you are about to instantiate.

Then check the current state before changing anything (`mem` is on the PATH in a session,
from the plugin's `bin/`):

    mem audit
    mem install --dry-run    # what `mem install` would change

`mem install` (setup.md, "The short path") does steps 1, 1b and 3d and is idempotent, so it
is also the repair for broken scaffolding. The plugin already carries the hooks and skills.
Matt runs it, or it runs on his go-ahead, because it includes step 1b and, on a machine set
up before the plugin, removes the old `mem` hooks from `~/.claude/settings.json` and the old
skill symlinks. In a checkout he works on, it is `make install` (`mem install --dev`)
instead. It writes `~/.claude/rules/claude-hybrid-memory.md` (step 3d) and never edits
`~/.claude/CLAUDE.md`. If it warns `install-imported-twice`, hand Matt the `# Memory` block
to delete from his `CLAUDE.md`; do not edit it yourself. If it warns `install-no-plugin`,
the plugin is not installed: say so and stop.

## Rules

- **Steps 1 to 3 of the setup doc are safe. Step 5 is not.** Pointing a repo's memory
  directory at a territory changes where a session reads memory from. Do it for one
  territory, confirm it works, then stop and let Matt use it for a day.
- **Never delete a legacy silo.** `mv` it to `memory.premigration`. That is the rollback,
  and it stays until a retrospective confirms nothing was lost.
- **Trust the hook checks `mem install` runs.** A broken SessionStart hook degrades every
  future session, so an `install-check-*` error is a stop, not a warning.
- **Never hand-edit `~/.claude/settings.json` hooks.** The plugin declares them; `mem
  install` only removes the pre-plugin `mem` entries, with a backup.
- **Step 1b (`git init` of the store and its baseline commit) runs only on Matt's
  go-ahead.** After setup, store history goes only through `mem`; never run `git` on the
  store. Never add a remote to the store.
- Commit nothing in any repo. Branches, commits and PRs are Matt's to make.

## Machine identity

Fill in `MACHINE.md` properly rather than leaving the template. Its purpose is that no
memory ever has to guess which machine it is on. Record what is true here and not on the
other box: corporate management, which GitHub identity is in use, and which remotes are
the authoritative push target.

## Finish by reporting

- what was created, and what was left alone
- the audit result before and after
- the single next action, which is normally migrating one territory with `/memory-migrate`
