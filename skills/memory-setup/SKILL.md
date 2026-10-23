---
name: memory-setup
description: Stand up or repair the machine-local Claude memory store (~/.claude/memory) - the router, standing directives, territories, skills symlinks, and the SessionStart hook. Use when setting up a new machine, when the SessionStart hook reports no store, or when the store's scaffolding is broken or missing.
---

# memory-setup

Stands up `~/.claude/memory` on this machine. The store is machine-local: it
may keep a local-only git history, but never a remote shared with another machine; only the
system in the claude-hybrid-memory repo crosses machines.

## Before doing anything

Find the repo: the target of the `~/.claude/skills/memory-setup` symlink. Read, in this order:

1. `docs/setup.md` - the procedure. Follow it, do not improvise around it.
2. `~/.claude/memory/MACHINE.md` and `ROUTER.md`, if the store exists - so territory names
   mean something here.
3. `docs/format-spec.md` - the layout and field rules you are about to instantiate.

Then check the current state before changing anything:

    mem audit
    make install-check    # from the repo root: what `make install` would change

`make install` (setup.md, "The short path") does steps 1 to 3c and is idempotent, so it
is also the repair for broken scaffolding. Matt runs it, or it runs on his go-ahead,
because it includes step 1b.

## Rules

- **Steps 1 to 3 of the setup doc are safe. Step 5 is not.** Pointing a repo's memory
  directory at a territory changes where a session reads memory from. Do it for one
  territory, confirm it works, then stop and let Matt use it for a day.
- **Never delete a legacy silo.** `mv` it to `memory.premigration`. That is the rollback,
  and it stays until a retrospective confirms nothing was lost.
- **Test the SessionStart hook standalone before installing it.** A broken SessionStart
  hook degrades every future session. `mem hook session-start` must exit 0
  and print the router.
- **Merge into the existing `hooks` object** in `~/.claude/settings.json` if there is one;
  do not clobber hooks that are already there.
- **Step 1b (`git init` of the store and its baseline commit) runs only on Matt's
  go-ahead.** The `~/.claude/CLAUDE.md` exception covers `mem`'s own commits to the store,
  not setup. Never add a remote to the store.
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
