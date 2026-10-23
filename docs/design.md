# Design: what we are building

Status: revision 2, 2026-09-04: the original design, kept as the record of why the
format is shaped the way it is. Built since; `direction.md` is where it went next.
It responds to an audit of Claude Code's per-project memory on a real machine (see the
README), and was revised once after an adversarial review of its own weak points.

## Goals

1. One unambiguous home for a memory, so knowledge stops landing wherever the tooling put it.
2. A router, so a session knows *when* to reach for something instead of only *what exists*.
3. Cross-repo reach, because one product can be one system spread over a dozen directories.
4. Computable freshness, so a cold file can be told apart from a rotted one.
5. Self-verification that fires on its own rather than when Matt remembers to ask.

## The governing constraint

> **The format may not make a memory more expensive to write than it is to rediscover.**

The current system's real virtue is that writing a memory is nearly free, which is why
there are 186 of them. Every rule below is checked against this constraint. A design that
produces better memories and fewer of them is a net loss.

## Non-goals

- **Tuned to one workflow first.** It was built for how one developer and Claude work
  together. Generality is welcome but never bought at the cost of that fit.
- **No vector DB, embeddings, or RAG.** These files are decisions and status, not a
  corpus. Similarity search answers "what is semantically near this". What a session
  actually needs is "what is authoritative and current", which is a graph property plus a
  freshness property, and neither is a distance in embedding space. Grep plus a good
  index beats it here, and not marginally.
- **No MCP server, for now.** MCP tool definitions cost context in every session forever,
  whether used or not. Everything wanted here is reachable as a script a skill calls. If
  the script surface starts wanting to be a tool, promote it then, deliberately.
- **Not a code-structure knowledge base.** The repo already documents itself. Memory is
  for what the repo does not say.

## Machine scoping

Matt runs Claude on a work Mac and a personal Mac and keeps them independent. So:

| Layer | Crosses machines? | Lives where |
|---|---|---|
| The method: spec, setup, migration, tooling, skills | **Yes** | this git repo |
| The content: actual memories | **No** | `~/.claude/memory/`, local history only, no shared remote |

This repo is the exception the user named: it is the one thing both machines share, and it
shares *the system*, not the state. `MACHINE.md` in the store carries machine identity and
any machine-scoped calibration, so a memory never has to guess which box it is on.

## Store layout

`~/.claude/memory/` is the only place memory content lives on a machine.

    ~/.claude/memory/
      MACHINE.md                 # machine identity + machine-scope calibration. always loaded.
      ROUTER.md                  # the map: one line per territory + pull-when. always loaded.
      RETRO.md                   # retrospective log: found / acted / declined-and-why
      standing/                  # directives true regardless of repo. always loaded. capped by COUNT.
        <slug>.md
      territories/
        chain/                   # the product dependency chain, ordered by layer
          foundation/
            MEMORY.md            # the territory router. gates are INLINED here, not linked.
            EXPORTS.md           # the contract downstream layers must obey
            <slug>.md
          components/
          recipes/
          field/
          cli/
        aspect/                  # cuts across every layer of the chain
          dep-policy/
          ci/
        mine/                    # Matt's own tooling. not part of the product chain.
          ops/
          pm/
          misc/
      archive/                   # retired memories and closed projects. never loaded.

### Why the territory router is named `MEMORY.md`

Because the harness already auto-loads `MEMORY.md` from a project's memory directory, and
that directory's location is redirectable. Point a repo's memory directory at a territory
and the harness loads that territory's router for free. No hook, no custom loader, no
symlink chasing at read time.

Two supported ways to point a repo at a territory:

1. **Symlink (preferred).** Replace
   `~/.claude/projects/<git-root-slug>/memory` with a symlink to
   `~/.claude/memory/territories/<territory>`. Leaves no footprint inside a repo you do
   not own, is one command, is trivially reversible.
2. **`autoMemoryDirectory` setting.** Set it in the repo's `.claude/settings.local.json`.
   Use when the mapping should be explicit and reviewable in the repo. Requires checking
   that the repo gitignores `settings.local.json` first.

Verified 2026-09-04: `autoMemoryDirectory` exists in the 2.1.260 binary; the memory
directory may itself be a symlink; the harness auto-loads only `MEMORY.md`, capped at
200 lines / 25 KB.

### What a territory is

> **A territory is a layer: the set of repos that break *together* when something upstream
> changes. Territories are connected by directed edges, and each declares what it exports
> to the layer below.**

An earlier draft of this rule read "the unit within which a change to one member can break
another member". Applied to a real 20-plus-repo product chain, that collapses the entire
chain into one territory, because breakage is transitive: a core library release breaks a
component's lockfile, breaks a template, breaks an application built from it. One territory containing everything is the pile this project exists to
escape.

The rule was right about what matters and wrong about the shape. Breakage here is
**directional and layered**, not symmetric, so the structure is a DAG over layers rather
than a partition of repos into buckets.

### Exports: how a territory reaches the ones below it

Each territory declares two things:

- **internals**: the bulk. Loaded only when working inside that territory.
- **exports**: the small contract downstream territories must obey. Propagated along DAG
  edges and inlined into consumers' routers.

This is a package's public API versus its implementation, applied to memory. A
dependency-policy repo that holds 46 files may have only four that bind its consumers
(merge order, never `uv lock --upgrade`, and two more like them). Those four reach every
repo in the chain. The other 42 stay home.

Exports are the mechanism that replaces manually pointing Claude at the other repos.

## The load path

Exactly three things enter context, at three different times.

| When | What | Mechanism | Budget |
|---|---|---|---|
| Every session, before the first prompt | `MACHINE.md` + `GATES.md` + `standing/` + `ROUTER.md` | `SessionStart` hook | measured in **tokens**; `standing/` capped by **file count**, `GATES.md` by **five entries** |
| Every session, automatically | this cwd's territory `MEMORY.md` | harness auto-memory | 200 lines / 25 KB (harness limit) |
| On demand, during the session | individual memory files | Claude reads them, guided by the routers | none |

The always-loaded layer needs a real constraint, not a warning, because an always-loaded
layer that grows without bound becomes exactly the undifferentiated dump this exercise
exists to escape.

So the constraint is a **fixed file count on `standing/`**: admitting a new directive
requires evicting or merging an existing one. Same discipline as a fixed-size cache, and
the forced ranking is the entire point. Size is reported in tokens rather than lines,
because line length varies too much to budget honestly.

The `SessionStart` hook is cwd-aware, and does four jobs:

1. Inject the always-loaded layer.
2. Report which territory this cwd maps to, and say so loudly when a cwd maps to nothing.
   An unmapped cwd is a finding, not a silent default.
3. Print one line when the last retrospective is overdue.
4. **Degrade in a chosen order when the layer does not fit, and announce it.** Job 4 was
   added 2026-10-02, after the hook was caught doing the naive thing — assemble, then
   `text[:MAX_CHARS]`. The layer had been ~19% over for weeks, so every session lost the
   *end* of `ROUTER.md`, which was where the exports block lived: the two rules about not
   mutating a home server and not committing live credentials were being dropped,
   mid-word, to make room for a CI punch list. Tail-truncation sacrifices content in
   assembly order, which has nothing to do with worth. The order of sacrifice is now
   explicit and inverted — `GATES.md` never, `standing/` bodies first (largest first, only
   as many as needed), the map last — and `docs/format-spec.md` holds the detail.

That incident is also why the budget check reports an **error** past `MAX_CHARS` rather than
a louder warning. Three retrospectives saw "soft warn" and each correctly deferred it.

Job 3 is the whole answer to "it works when I remember to nudge you". It converts the
user's discipline into a mechanism.

## The memory file format

### Two kinds, not four

- **`standing`** — a directive that would change behavior in a repo Claude has never
  opened. Always loaded. Capped by count.
- **`territory`** — everything else. Loaded on demand through a router.

Everything else is a field. "Live status" is just `volatility: live` on a territory file.
"Gate" is a *role* a territory file plays, not a separate kind. Four buckets means a
classification argument at every single write. Two kinds plus fields means one easy
question, then metadata.

### The admission test for `standing`

A memory is `standing` only if both hold:

1. It would change Claude's behavior in a repo it has never opened, and
2. violating it produces work the user rejects.

"Use `uv`" passes. "The eval contract lives in core-lib" fails: that is territory.
Without a test, `standing/` becomes a junk drawer and the always-loaded budget blows.

Standing directives declare their own exceptions, and a local exception declares its
parent with `overrides:`. That makes "use `uv`" versus the one repo where `uv run` wipes
the environment structural instead of accidental, and lets the audit tool verify every override points at
a directive that actually exists.

### Fields

Required, and only these four:

    name          # kebab-slug. THE link target. must equal filename minus .md.
    kind          # standing | territory
    description   # one line. becomes the router hook.
    volatility    # stable | slow | live  (derived from status when status is present)

Optional, or filled in by `mem.py fix`:

    status         # SHIPPED | PARKED | STILL LIVE | BLOCKED | IN FLIGHT | RESOLVED | HISTORICAL
    last_verified  # YYYY-MM-DD. defaults to file creation date.
    verify         # the literal check that settles this. see constraints below.
    expect         # what the check should show.
    role           # gate. its text gets inlined into the territory MEMORY.md.
    exhaustive     # false = absence from lists here is not evidence of a negative.
    source_of_facts # false = anti-source. never cite as truth.
    overrides      # <standing-slug>. declares a local exception.
    supersedes     # <slug>. the superseded memory must be archived or marked HISTORICAL.
    confidence     # asserted | inferred. inferred = Claude's hypothesis, unconfirmed.
    splittable     # hint
    owner          # self | colleague | employer | third-party
    mode           # active | occasional-pr | reference | dead-upstream | scratch
    origin_session # uuid
    audience       # claude. these files are not written for human readability.

Body carries the fact, then `**Why:**` and `**How to apply:**` where the kind warrants it,
and links related memories with `[[slug]]` liberally.

`owner` and `mode` came out of the topology work and are behavioral, not decorative. A
`colleague`-owned repo should not attract casual PR proposals. A `dead-upstream` repo
should never draw a suggestion to upgrade or chase a fix. A `scratch` repo is expected to
have drifted and is never a source of truth.

### Volatility is derived, not predicted

At write time it is often genuinely unknown whether a fact is stable or live, and the
honest fallback is `live`, which floods the freshness report until both of us ignore it.
So derive it from `status` when one is present:

| status | implied volatility |
|---|---|
| `SHIPPED`, `RESOLVED`, `HISTORICAL` | `stable` |
| `PARKED` | `slow` |
| `STILL LIVE`, `BLOCKED`, `IN FLIGHT` | `live` |

State `volatility` explicitly only when that default is wrong.

### Verification recipes

`volatility` plus `last_verified` on its own is a trap. Stamping a date is cheap.
Re-verifying is expensive: it means checking git, open PRs, CI. If verification is
expensive it will not happen, the dates will rot, and the result is a *false* freshness
signal, which is worse than no signal because it will be trusted.

So a memory may carry the literal check that settles it:

    verify: gh pr view acme/core-lib#123 --json state -q .state
    expect: MERGED

The audit tool can then run the checks and re-stamp automatically, turning discipline into
a script. The difference is between a report that says "14 files are old" and one that says
"I re-ran 14 checks; 11 confirmed, 3 now contradict their memory, here they are".

**This is a code-execution surface, so it is constrained:**

- **Allowlisted leading command only**: `git`, `gh`, `uv`, `task`, `ls`, `test`. Not
  `curl`, not `sh`, not `python -c`.
- **Never shell-interpreted.** Argv is exec'd directly. No `shell=True`, no pipes, no
  `&&`, no redirection, no substitution.
- **Refused if the subcommand mutates.** Explicit deny list for `gh pr merge`, `git push`,
  `git reset`, `git checkout`, and similar.
- **Timeout-bounded**, short, per recipe.
- **Off by default.** `mem.py fresh` reports which memories are due without running
  anything; running them requires `--run`.

A memory whose check cannot fit those limits carries a prose check instead and is reported
as `unrunnable`, not silently skipped.

### Gates are inlined, not linked

A file declaring `role: gate` accomplishes nothing if "read this first" is a soft
convention, and soft conventions are what failed here. So **a gate's text is inlined into
the territory `MEMORY.md`**, which puts it inside the auto-loaded 200 lines where it cannot
be missed.

Evidence this is the right mechanism: one silo's hand-grown "READ THIS BEFORE JUDGING
STATUS" works because it is the first line of the index, not because a file exists with
that name.

### Naming, so links stop dangling

- `name:` is the only link target and must equal the filename minus `.md`.
- Slugs are kebab-case. No underscores, ever.
- `mem.py fix` renames offending files and inserts missing `name:` fields rather than
  merely complaining. This is the fix for the ~8 currently dangling links.

## Tooling

Originally one file, `tools/mem.py`, stdlib only. Since 2026-10-21 it is the `claude_hybrid_memory`
package in `src/`, run as `mem <cmd>` (`docs/setup.md` step 3). Its one dependency is
`pyyaml` for frontmatter; the hook path stays stdlib only.

| Command | What it does |
|---|---|
| `audit` | everything below, as one report |
| `fix` | **autofix**: stamp `last_verified`, normalize slugs, rename `_` files, insert `name:` |
| `links` | dangling `[[slug]]`, ambiguous slugs, orphans nothing links to |
| `fresh` | report memories due for verification; `--run` executes constrained recipes |
| `budget` | always-loaded layer in tokens **as injected**, and `standing/` against its file-count cap |
| `drift` | routers listing missing files, files no router lists, mixed-state silos |
| `dup` | same fact in two territories; `standing` candidates hiding in territory files |
| `status` | migration progress; flags unsafe mixed states |

Mechanical checks belong in the script. Judgment stays with Claude, reading the report.
The tool autofixes what is mechanical and reports what needs a decision. It never
scolds about something it could have fixed.

## Skills

Three, living in this repo under `skills/`, symlinked into `~/.claude/skills/`. Symlinked
rather than packaged as a plugin: a plugin only buys bundled agents, MCP servers, and
marketplace distribution, none of which are wanted, and a symlink means editing the repo
changes live behavior immediately.

| Skill | Job |
|---|---|
| `/memory-setup` | stand up the store on a machine that does not have one |
| `/memory-migrate` | move one silo or cluster into a territory, incrementally and safely |
| `/memory-retro` | run the tool, then do the judgment pass and act on it |

## Migration safety

186 files will take several sessions. A half-migrated store is worse than either end
state, because ambiguity about where a memory lives is the original disease.

So at any instant a silo is in exactly one of three states, and two of them are terminal:

- **Not yet reviewed.** Knowledge lives in the silo. Untouched.
- **Migrated.** The silo's memory directory is a symlink to a territory. No local knowledge.
- **Archived.** Content moved to `~/.claude/memory/archive/<silo>/`. A finished state, not
  a skipped one.

Never a mix. `mem.py status` treats a mixed silo as an error.

**Archive-in-place is a completed verdict.** Some silos should never be migrated: a
client project that is 177 days cold and over. Without a terminal state
for those, the status report shows permanent incompleteness, and permanent incompleteness
gets ignored.

## Self-verification

Mechanical checks come from `mem.py audit`. The judgment pass is Claude's, and it reads
the report rather than replacing it. Full procedure in `docs/self-verification.md`.

Two design points worth stating here:

**The retro logs its own decisions.** `RETRO.md` records each run: what was found, what was
acted on, and **what was deliberately declined and why**. Later runs suppress
known-and-accepted findings. Without this, the retro re-litigates settled decisions every
month and stops getting run. It is the "deferred / eliminated, with reasons, so they aren't
re-suggested blindly" pattern applied to the system's own maintenance.

**"Am I forgetting things?" is captured, not inferred.** The tempting version mines
`history.jsonl` for rediscovery signals. Assessed honestly, that detector would be fuzzy,
would flag normal work as rediscovery, and would emit confident nonsense. The old memories
had already recorded that objection twice, as feedback against manufactured insight. So the
v1 mechanism is a direct question asked
while the evidence is fresh: *what did I have to re-derive this session that a memory
should have told me?* Transcript mining stays as a labeled experiment with no headline
claims. On this question specifically, a weak detector is worse than none.

## Validation test for the spec

**The spec must be able to describe an existing hand-built context library without
modifying it.** That library already works, it was written under an LLM-first instruction
(a guide file with a `pull when` table, a retrieval protocol, and `[CURRENT]` /
`[HISTORICAL]` / `[RESOLVED]` tags), and it is the best existing instance of this format.
If the spec cannot express it, the spec is wrong, not the library.

Under this design it becomes a territory: its guide file becomes the territory `MEMORY.md`,
and its tag vocabulary maps onto `status:` and `volatility:`.

## Rejected alternatives

**Keep per-project silos alongside a global store.** Rejected. Two stores means every
future session guesses which one to write to, and the guess degrades the split exactly the
way the current one degraded. The current system's core failure is that knowledge landed
where the tooling put it rather than where it belonged; a two-store design reproduces that
one level up. Project silos become pointers instead.

**Symlink related silos together and stop there.** Rejected as the endpoint, though it is
the mechanism used to point repos at territories. On its own it fixes cross-repo reach and
leaves the standing-directive duplication and the freshness problem untouched.

**Router only, move nothing.** Rejected. Cheapest and fully reversible, but links still do
not resolve and "use uv" stays in 11 places.

**A vector DB or RAG layer over the memories.** Rejected, see Non-goals.

**An MCP server as the storage and retrieval layer.** Deferred, see Non-goals.

**Four memory kinds.** Rejected in favor of two kinds plus fields.

**Freshness by mtime alone.** Rejected. mtime says a file was touched, not that its claim
was checked. Hence `verify:` recipes.

**A line-count cap on the always-loaded layer, enforced by a failing audit.** Rejected. A
cap that can be raised the first time it trips is not a cap. Replaced by a fixed file count
on `standing/` plus token-based reporting.

**Transcript mining as the primary rediscovery detector.** Rejected for v1, see
Self-verification.

## Open questions

1. Territory boundaries beyond the main chain. Apply the breakage rule during migration and
   record the verdicts.
2. One project checked out in two locations has two silos with divergent memories. Merge
   or archive.
3. Whether the `Stop` hook should also nudge a memory write at the close of a chunk of
   work, or whether that is too noisy. The hook event supports it (`type: prompt` can ask
   the model to keep working). Try the `SessionStart` half first and see if it is enough.
4. Retrospective cadence. Monthly is a guess. Let the first few runs calibrate it.
5. The exact `standing/` file-count cap. Start at 20 and let eviction pressure calibrate it.
