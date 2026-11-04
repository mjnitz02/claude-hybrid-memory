---
name: mem-usability-eval
description: Scrutinize claude-hybrid-memory as an agent actually experiences it - cold sessions in real repos retrieving, writing, verifying, superseding and linking memory through `mem`, all against scratch copies of the store. Use when re-evaluating the plugin after fixes, or when `mem` feels unintuitive.
---

# mem-usability-eval

This is a usability eval, not a correctness test. pytest already checks that `mem` does what
its code says. This skill checks whether an agent dropped into some repo **reaches for the
right command, gets it right on the first try, and trusts the result**. The instrument is
the *friction log*: every command in order, whether it worked first try, the exact error
text, what had to be guessed, and every point where a hand edit felt safer than `mem`.

The four properties being judged:

- **Retrieval across silos:** can a session in one repo find what another territory knows?
- **Speed and efficiency:** few calls, little noise, no wasted tokens.
- **Intuitive to an LLM:** the first guess at a command is the right one.
- **Confidence:** after a write, the agent knows it worked without inspecting files.

**Every write goes to a scratch copy of the store.** The real store and `~/.claude/projects`
must be byte-for-byte unchanged at the end. Never put real memory content in this repo:
reports go to a location the user names, outside the checkout.

## Steps

### 1. Baseline

- **Record the version:** the repo HEAD, and `mem audit | tail -1` on the real store (the
  warning baseline).
- **Snapshot the real state to compare against at the end:**
  `mem log -n 1`, plus a listing of `~/.claude/projects/` with symlink targets.
- **Read the last report** if the user points at one. Its gap list is the starting
  regression set; `regressions.md` holds the standing one.

Done when HEAD, the audit line and both snapshots are written down.

### 2. Scratch stores

- **One copy per actor:** `cp -R ~/.claude/memory <scratchpad>/store-<x>` for yourself and
  each subagent. The copy carries the store's own history, so `mem` auto-commits land in the
  scratch history only.
- **One legacy dir per actor that tests linking:** an empty `<scratchpad>/legacy-<x>`, passed
  as `--legacy`.
- **Hand each actor the known `--root` artifacts** (below), so they don't report them as
  findings.

Done when every actor has its own store path.

### 3. Your own cold pass

- **Pick a mapped repo**, run `echo '{}' | mem hook session-start` there, and treat that plus
  the always-loaded layer as everything you know.
- **Work from `mem --help` and `mem <cmd> --help` only.** Don't read `src/` until the pass is
  finished: reading it first destroys the signal.
- **Do one real task in each category in `scenarios.md`:** retrieve, cross-territory
  retrieve, verify-on-use, add, replace, pull another territory, history.
- **Log friction as you go**, including the moments you *almost* did something else.

Done when each category has at least one logged attempt with its first-try outcome.

### 4. Subagent scenarios

- **Dispatch the scenarios in `scenarios.md` in parallel**, using its prompt template. One
  subagent per repo shape. At least one should run on a smaller model: a weaker model's first
  guess is the better test of what is intuitive.
- **Keep working while they run.** Probe the items in `regressions.md` that no scenario covers.
- **Spot-check one claim from each report** before relying on it. Re-run it on that actor's
  scratch store, and label each finding VERIFIED (reproduced by you) or REPORTED (one actor
  only).

Done when every subagent has reported and each report has one spot-checked claim.

### 5. Confirm nothing real changed

- **Compare against the step 1 snapshots:** `mem log -n 1` is unchanged, and
  `~/.claude/projects/` has no new or retargeted links.
- **Search the real store for each slug the actors created.** None should exist.

Done when both match and the search comes up empty. If anything changed, stop and tell the
user before writing the report.

### 6. Report

Write the report where the user asks, in this shape:

1. **Header:** the date, the repo HEAD, the method (actors, repo shapes, models), and the
   VERIFIED/REPORTED legend.
2. **Bottom line:** three to five bullets.
3. **Scorecard:** one row per property above, or per question the user posed.
4. **Ranked gaps:** what happens, an example with exact command and output, the cost, and the
   suggested fix. Rank by harm to a real session, not by ease of fixing.
5. **Smaller problems.**
6. **What worked well:** so a fix doesn't regress it.
7. **Regression table:** every item in `regressions.md`, marked fixed / still open / changed.
8. **Stale memory content found along the way:** this goes to the user, not into the repo.
9. **Suggested order:** the next fixes.
10. **Artifacts:** the scratch store paths.

Then update `regressions.md`. Add new gaps with a probe and a pass condition; mark fixed ones
with the date and HEAD instead of deleting them.

Done when every regression row has a status and every finding has a label.

## Known `--root` artifacts

Hand these to every actor so they aren't counted as findings. Re-test each one every run,
and delete the entry once it's fixed.

- **Territory lookup ignores `--root`.** cwd-to-territory resolution goes through the real
  `~/.claude/projects/*/memory` symlink, so `mem new --root X` says the directory "maps to no
  territory". Pass `-t <territory>`.
- **`audit --root X` reports `[ERROR] budget-not-imported`.** The rules file imports the real
  store path, not the scratch one.
- **`mem link` writes to the real `~/.claude/projects`** unless `--legacy <scratch-dir>` is
  passed as well. Never run `link --write` without `--legacy`.
- **The hook takes no `--root`.** `mem hook session-start` can only be read, not pointed at a
  scratch store.
- **Global flags only work after the subcommand.** `mem --root X find ...` fails. This is a
  real finding as well, tracked in `regressions.md`.

## Rules for every actor

- **Writes:** every write carries `--root <its scratch store>`. Any command with no `--root`
  that would touch `~/.claude` is described, not run, and the missing sandbox is logged.
- **No source:** don't read `src/`. Help text, hook output, memories, and docs that something
  points at are the only sources.
- **Machine rules:** follow the machine's own tool rules from its always-loaded layer
  (interpreter wrappers, search tools). They're part of the real session.
- **Store history:** never run `git` on the store. The store's history goes through `mem`.
