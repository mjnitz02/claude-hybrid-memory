# Regressions

The standing list of usability gaps. Each entry has a **probe** (how to reproduce it on a
scratch store) and a **pass** condition. Every run marks each row fixed / still open /
changed. A fixed row keeps its history: add `FIXED <date> @ <HEAD>` and leave it in place, so
a later regression is recognisable.

Each entry also records where it was first seen and how severe it was: high hurts most
sessions, med hurts some, low is a papercut.

## Retrieval

### R1. `find` and `show` don't flag a memory past its window
- **First seen:** 2026-11-04, `66399d7`, high.
- **Probe:** `mem show <slug> --meta` and `mem find <term>` on a memory whose `last_verified`
  is older than its volatility window.
- **Pass:** both outputs say the memory is past its window, with the age and the limit.
  The agent does no date maths.

### R2. `find` matches each argument as an exact phrase; multi-word queries fail silently
- **First seen:** 2026-11-04, `66399d7`, high.
- **Probe:** `mem find "<two words>"` where both words appear in a memory but not adjacent;
  and `mem find a b c` with three loosely related terms.
- **Pass:** the memory is found, or the output says why not and suggests a looser query.

### R3. Dated records outrank current-state memories
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** a query whose current answer lives in a non-record memory, in a territory full
  of dated records.
- **Pass:** the current-state memory ranks first.

### R4. `find --territory T` hides matches elsewhere
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** a term that matches only outside T.
- **Pass:** "no matches in T; N elsewhere".

### R5. No command reads another territory's index
- **First seen:** 2026-11-04, `66399d7`, high.
- **Probe:** `mem show <territory>`.
- **Pass:** prints that territory's MEMORY.md, or there's an equivalent the hook or ROUTER
  names.

### R6. Default `show` truncates silently
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** `mem show <slug>` on a memory with more than 10 body lines.
- **Pass:** the output ends with a "N more lines, `--full`" hint, or prints the body.

### R7. No backlink or consumer query
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** "what links to <slug>?" or "what consumes this territory?"
- **Pass:** a `mem` command answers it.

## Writing

### W1. `mem new -g` is ignored in hand-curated indexes and reports success
- **First seen:** 2026-11-04, `66399d7`, high.
- **Probe:** `mem new ... -g "<existing heading>"` in a territory that `mem render` reports as
  not rendered.
- **Pass:** the line lands under that heading in the index's own line format. Otherwise
  `mem new` warns that it couldn't honour `-g`.

### W2. `supersede` leaves the index line and backlinks for hand edits
- **First seen:** 2026-11-04, `66399d7`, high.
- **Probe:** supersede a memory that is in the index and linked from another memory or from
  gate prose.
- **Pass:** the index line is rewritten or removed, and every backlink is rewritten or listed
  with a command to fix it.

### W3. No supported in-place edit, so drift fixes are sed and `verified` gets stamped on stale content
- **First seen:** 2026-11-04, `66399d7`, high.
- **Probe:** a drifted path or a stale description that needs fixing.
- **Pass:** a `mem` command edits the description, status or body, or the docs name the
  sanctioned route.

### W4. `mem new` leaves ROUTER counts stale, so the next `audit` warns about the session's own write
- **First seen:** 2026-11-04, `66399d7`, low.
- **Probe:** `audit`, then `mem new`, then `audit`.
- **Pass:** no new warning, or `mem new` says it will settle at the next render.

### W5. No near-duplicate nudge on `mem new`; `dup` misses near-duplicates
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** `mem new` with a description close to an existing memory's.
- **Pass:** `mem new` names the similar memory.

### W6. The harness auto-memory recipe gets past `audit`
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** a file with frontmatter nested under `metadata:`, no `kind`, and a hand-added
  index line.
- **Pass:** `audit` flags the shape at warn level or higher and names `mem new`.

## CLI surface

### C1. Two parsers: the usage line omits the main commands, and global flags fail before the subcommand
- **First seen:** 2026-11-04, `66399d7`, high.
- **Probe:** `mem --help | head -5`, `mem --root X find foo`, `mem link --help`,
  `mem audit --help`.
- **Pass:** every subcommand appears in the usage line, has its own help, and takes global
  flags in either position.

### C2. The example in `mem new --help` fails
- **First seen:** 2026-11-04, `66399d7`, low.
- **Probe:** run the help example verbatim (with `-t` and `--root`).
- **Pass:** it succeeds.

### C3. `mem log <territory>` returns nothing with no error; subjects say nothing per territory
- **First seen:** 2026-11-04, `66399d7`, low.
- **Probe:** `mem log <t> -n 3` and `mem log territories/<t> -n 3`.
- **Pass:** both narrow to the territory, or the first errors with a hint.

### C4. `audit` can't scope to a territory or a recent change
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** `mem audit --territory T`.
- **Pass:** scoped output.

## Routing

### X1. The no-territory hook points at a manual procedure instead of `mem link`, and suggests no territory
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** the hook in an unmapped repo.
- **Pass:** it prints `mem link --territory <guess> --write`.

### X2. `mem link --write` doesn't update `members:`, and `audit` doesn't notice
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** `link --write --legacy <scratch>`, then read the territory's frontmatter.
- **Pass:** a `members:` entry is added, or `audit` flags the gap.

## Sandbox (test-harness only, but it hides real risk)

### S1. `--root` doesn't isolate territory lookup, `link`, or the hook
- **First seen:** 2026-11-04, `66399d7`, med.
- **Probe:** see "Known `--root` artifacts" in `SKILL.md`.
- **Pass:** `--root` alone sandboxes every command. When this passes, delete those artifacts
  from `SKILL.md`.

## Content checks (never commit findings here)

Stale or contradictory memory content found during a run goes in the report for the user,
not into this repo. The pattern to watch for: a `stable` gate that contradicts the router or
a newer memory never comes due for a check, so the verify window can't catch it.
