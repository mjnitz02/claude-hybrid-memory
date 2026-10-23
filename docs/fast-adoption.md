# Fast adoption: land first, refine after

Status: ACCEPTED, 2026-10-23, on Matt's direction. Stages 1 to 4 built and run on the
first machine: every pending silo there is landed (§12). Stage 5's queue and skill are built
(§8); its exit, one session working ten items, is not yet met. Replaces the per-territory
procedure in `migration.md` for bulk adoption, and is what Phase 6 (the remaining silos)
and Phase 7 (the second machine) of `direction.md` run on.

## 1. The short version

Adoption today is one Opus session per territory that reads every file in full, in its own
context, and decides everything on the spot: five verdicts, rewritten descriptions,
`verify:` recipes, relocations. It works, and it is the most expensive thing this system
does. Most of the cost is reading: the session drags every file it reads through every
later turn, so a silo of fifteen files costs far more than fifteen times one file.

The new shape splits that one session into five stages, and gives each one to whatever
does it most cheaply:

| Stage | Done by | Reads | Produces |
|---|---|---|---|
| 1. Inventory | `mem migrate inventory` (code) | the silos | one JSON record per file, no model |
| 2. Summarize | a **Sonnet** summarizer, **one fresh process per file** | one file plus its directive | one small JSON summary per file, and one per silo index |
| 3. Map | the main session, with Matt | only the stage 1 and 2 output | `plan.yaml`: every silo and file to a territory. **The one checkpoint.** |
| 4. Land | `mem migrate apply` (code) | the plan | files moved as they are, silos linked, indexes rendered, one store commit per silo |
| 5. Refine | `mem audit` and the summaries, as a queue; `/memory-refine` works it | one queue item at a time | better descriptions, splits, compactions, `verify:` recipes, relocations |

Stages 1 to 4 get everything into the store fast and roughly right. Stage 5 makes it good,
in small pieces, for as long as that takes. The store's git history sits between the two:
everything lands as it was, in a commit, so any refinement can be rolled back to the
original.

## 2. Why the summarizer is one process per file

Matt's reasoning, 2026-10-23:

- **Context never grows.** The summarizer reads one file, writes its summary and exits. The
  thirtieth file costs what the first did.
- **No cross-contamination.** It cannot blur two files together, or carry a conclusion from
  one into the next, because it never sees more than one.
- **A narrow job is done better.** It gets a short directive and only the context that job
  needs: no router, no standing directives, no global instructions. Fewer tokens, and more
  attention on the one task.

**Sonnet, and no Haiku evaluation** (Matt, 2026-10-23). Summarizing and judging a
description is well within Sonnet, so its output is unlikely to need repair or a second
look. That reliability is itself the reason to use it: the saving Haiku might offer would
be spent checking it, and Sonnet's cost here is already trivial on a subscription.

**The comparison that motivated this.** Adopting `console/tools` by hand took two whole
Opus sessions, each past 300,000 tokens of context, and several real-world hours of
reading markdown. Summarizing all 78 remaining files on this machine took **2 minutes and
$1.64** (§12), and none of it entered the main session.

The main session's part shrinks to reading compact tables and making decisions with
Matt. It never reads a memory body during stages 1 to 4.

## 3. Decisions reversed

These were the rules in `migration.md` and `skills/memory-migrate/SKILL.md`. Reversed by
Matt, 2026-10-23.

1. **"The judgment step does not automate."** It does not need to happen at migration.
   Landing a file as it is loses nothing: its text is in a commit either way. Judgment
   moves to stage 5, where it is done per item, with only that item in view.
2. **"Write the `verify:` recipes during the migration."** They were the highest-yield step,
   because two migrations in a row found stale claims that way and no other way. That
   evidence stands, so recipes are not dropped. They are **queued**: the summarizer flags
   claims that look live, a heuristic flags the same patterns mechanically, and each flag
   becomes a stage 5 item. A recipe is written then, from an identifier the refining
   session has checked exists (migration.md's first trap still applies).
3. **"One territory per invocation."** The care that rule bought now comes from the map
   checkpoint and from landing each silo in its own commit. Once Matt approves the map, all
   silos land in one run.

What does **not** change: the silo invariant (§6), "never delete a silo", the format spec,
and `GATES.md` / `standing/` promotions staying Matt-visible decisions.

## 4. Stage 1: inventory

    mem migrate inventory [--source DIR ...] [--json]

No model. Default sources are the pending silos `mem status` reports; `--source` takes any
directory of markdown memories, which covers adopting memories from outside the store later.
Per file it records:

- source path, silo, size, sha256 of the content
- frontmatter as parsed, plus any `frontmatter-not-yaml` problems
- the silo's `MEMORY.md` index line for it, if any
- wikilinks out, and which other silos or store memories link to it
- **repos it mentions**: absolute paths and repo names matched against the silo list and the
  store's territory `members:`, so relocation candidates are found by code, not by reading
- near-duplicates in the store and in other silos, by the existing `audit/dup.py` measure
- **live-claim hits**: the heuristic half of the `verify:` decision (§8)
- size against the split-candidate threshold `audit/split.py` already uses

It writes `.cache/migrate/inventory.json` in the store. `.cache/` is derived and
gitignored, which is right: everything in it can be rebuilt. Inventory reads files
directly, so no read events are logged and Phase 2's usage data stays clean.

## 5. Stage 2: summarize

    mem migrate summarize [--silo S] [--jobs 4] [--model sonnet] [--force]

Drives the summarizer, one headless `claude -p` process per file. That keeps every summary
out of the main session's context, and makes the run parallel, resumable and the same on
both machines. Each run is isolated:

    claude -p --model sonnet --tools "" --no-session-persistence --setting-sources "" \
      --settings '{"disableAllHooks": true}' \
      --system-prompt-file <repo>/agents/memory-summarizer.md \
      --json-schema "$(cat <repo>/agents/memory-summary.schema.json)" --output-format json

started in an empty temporary directory, with the file body (and its inventory record) on
stdin:

- **`--tools ""`**: it needs no tools, since the file arrives on stdin. With no tools it can
  touch nothing, and no PostToolUse event fires for Phase 2 to count.
- **hooks off**: no SessionStart router injected (24 KB of context it does not need), and
  no SessionEnd commit of the store halfway through a run. With hooks on, a run also leaves a
  project directory behind, holding the persisted hook output.
- **`--setting-sources ""`**: keeps `~/.claude/CLAUDE.md` out, along with the user settings
  file's hooks and permissions. OAuth still works.
- **`--system-prompt-file`**: replaces the default system prompt with the directive alone.
- **`--no-session-persistence`, empty cwd**: nothing saved, so a hundred throwaway sessions do
  not each leave a project directory under `~/.claude/projects/` for `mem status` to find.

`--bare` would do most of this in one flag, but it accepts only an API key, never the OAuth
login these machines use, so it is not the plan. What still reaches the model (measured,
§12): Claude Code's one-line preamble, the account email, and the environment block. About
640 tokens, and no flag removes them without `--bare`.

Headless processes driven by `mem`, not Agent-tool subagents inside a session: Matt's
call, 2026-10-23. They are more robust and reproducible, and `--jobs` controls how many
run in parallel.

Each summary is cached at `.cache/migrate/summaries/<sha256>.json`, keyed by content, so a
re-run only summarizes files that changed, and `--force` redoes them. A failed or
schema-invalid run is retried once, then recorded as `failed` for the map to show.

**The silo summary** runs first, as a separate directive: one process per silo, reading the
silo's `MEMORY.md` (or, for a silo with no index, like `onion-kids-mode`, the file list with
descriptions), its working-directory path and whether that exists on disk, and the
store's territory list with one-line purposes from `ROUTER.md`. This is the "summary of each
project's basic memory file" that the territory map is built from.

### What a file summary says

Defined by `agents/memory-summary.schema.json`; roughly:

    {
      "conclusion": "one line, stated as a conclusion, not a topic",
      "description_verdict": "good | names-subject | stale | missing",
      "kind": "territory | standing-candidate | gate-candidate | machine-fact | record",
      "subject_repos": ["repos this file is actually about"],
      "territory_hint": "where it belongs, if not the silo's own territory",
      "shape": ["build-diary", "dated-snapshot", "accreted", "index-only"],
      "verify": [{"claim": "...", "why": "...", "identifier": "the SHA, path or PR it names"}],
      "obsolete": {"likely": false, "why": ""},
      "confidence": "high | medium | low"
    }

`index-only` is Matt's addition: the file says nothing its one-line conclusion does not, so
the refine pass may fold it into the index and archive the file. `verify` is the model's
half of the recipe decision; it names the claim and the identifier, and never writes a
recipe itself.

The directive is short and asks for nothing outside this schema. It gets the format spec's
vocabulary for `kind` and the meaning of each `shape`, and nothing else from this repo.

## 6. Stage 3: the map, the one checkpoint

    mem migrate map [--rebuild] [--approve]   # <store>/migrate/plan.yaml, and the table

Code builds a first plan from the summaries; the main session refines it with Matt, reading
only that table. Per silo:

    - silo: -Users-alice-workspaces-cbz-tagger
      territory: media/cbz-tagger        # existing, or new (with home and layer)
      new: true
      mode: active                       # parked when no checkout exists on this disk
      files:
        - file: tagging-pipeline.md
          action: land                   # land | relocate | archive
          description: keep              # keep | proposed
        - file: old-api-notes.md
          action: archive
          why: "summarizer: obsolete, API retired 2026-06"

`land` is the default for everything. `relocate` (to another territory) and `archive` come
only from a summary flag or an inventory signal, and Matt sees each one. Promotions to
`standing/` or `GATES.md` are **not** done here: a `standing-candidate` or `gate-candidate`
becomes a refine item, because those files are the always-loaded layer and cost every
session.

`description: proposed` replaces the original only where the summary says `names-subject`
or `missing`. Everywhere else the original stays, and the proposal waits in the queue.

The four `silo-not-checked-out` silos land as `mode: parked` unless their summary says
they are dead. Absence from this disk is not evidence (the offload cycle,
`format-spec.md`, "`mode: parked`"). The 9 empty silo directories are listed for Matt's deletion
decision, as direction.md Phase 6 already says, and are not touched.

Once Matt approves the map, stage 4 runs on all of it.

*Built 2026-10-23.* Where the plan lives and how approval works:
- **`<store>/migrate/plan.yaml`, not `.cache/`.** Matt's edits are decisions, not derived
  data, so the store's own commits keep every version.
- **`map` never redraws over an existing plan.** `--rebuild` redrafts and keeps the old one
  as `plan.prev.yaml`.
- **Code decides what it can check.** `new` means no `MEMORY.md` on disk yet; `in_router`
  means the name appears in `ROUTER.md`. A relocation needs a hint that resolves to a real
  territory, or to the home of a repo another silo is for. A hint naming nothing real stays
  a signal. Per file, `signals` lists what the draft saw and is never acted on.
- **`--approve` stores a hash of the decisions:** territory, mode, and each file's action,
  `to`, description and proposed text. Editing any of them afterwards voids the approval.
  Advisory fields (`signals`, `why`) do not.

## 7. Stage 4: land

    mem migrate apply [--silo S] [--dry-run]

Code only, one silo at a time, each silo atomic:

1. Create the territory if new, from `templates/territory-MEMORY.md`, already adopted by
   `mem render`, so its MEMORIES section is generated from day one.
2. Copy each `land` file in **unchanged**, except for what `mem fix` would normalize anyway
   (slug, `name:`), and the silo's index line merged into `description:` where the file
   has none, which is the merge direction.md §16 settled. A slug already taken in the territory is a
   stop for that silo, shown in the dry run: never an overwrite.
3. **Commit: "migrate: land <silo> as-is"**. This commit is the rollback point.
4. Apply `description: proposed`, relocations and archives. **Second commit**, so landing and
   rewriting can be undone separately.
5. Move the silo's memory dir to `memory.premigration` and symlink it to the territory, as
   in `setup.md` step 5. Then `mem status` must show `silo-migrated` for it, or apply
   restores the silo and stops.
6. `mem render` that territory, and `mem audit --scan store` must not report new errors. A
   new error stops the run there, with the silo's commits left for Matt to look at.

All store git goes through `storegit.py`, like everything else. The invariant holds at
every step: a silo is pending until step 5 swaps its directory in one rename, then
migrated.

Rollback for one silo is `mem migrate undo --silo S`: it reverts the silo's two commits
(new commits; history is kept, never rewritten) and puts `memory.premigration` back. A
later silo that touched the same files (a shared territory index, `ROUTER.md`) makes the
revert conflict. It is then aborted with nothing changed, and the later silo is undone
first.

*Built 2026-10-23.* How the build differs from the plan above:
- **No state file.** Which silos are landed, and by which commits, is read from the store's
  history: the commit subjects name the silo. A first version kept `migrate/applied.yaml`.
  Each write of it landed in the next silo's commit, so reverting one silo conflicted with
  the log itself.
- **Slug collisions.** A slug claimed anywhere in the store, or by two files in the plan,
  takes the territory's last segment as a prefix, since the audit treats one slug in two
  places as an error. Links within the same silo follow the rename.
- **Archiving never leaves a dangling link.** A `[[link]]` to a file being archived is
  rewritten to the file's `archive/` path, in the decisions commit.
- **Hand-written indexes are not rendered.** An existing territory whose `MEMORY.md` was
  never adopted gains a line per new memory under `## MEMORIES`, and is otherwise left as
  written. A new territory is created already adopted.
- **The router line.** A `[legacy]` line gets its count. A territory with no line gets one,
  under its area's section. Prose that mentions a territory is left for Matt.

## 8. Stage 5: refine

    mem refine queue [--territory T]   # build or refresh the queue
    /memory-refine [N]                 # work N items, default 10

The queue is the union of:

- audit findings that need judgment: `split-candidate`, `possible-duplicate`,
  `frontmatter-not-yaml`, `stale-live`, `superseded-still-indexed`, budget warnings
- every summary flag: `description_verdict` other than `good` where the original was kept,
  `build-diary`, `dated-snapshot`, `accreted`, `index-only`, `standing-candidate`,
  `gate-candidate`, `territory_hint` that disagrees with where it landed
- `verify:` candidates, which come from two places and are ranked higher when both agree:
  - **the summarizer's `verify` list**: claims it judged live, each with its identifier
  - **the heuristic**: commit SHAs, PR and issue numbers, "uncommitted", "as of <date>",
    "phase N" with a status word, branch names, "currently" or "now" next to a version, on
    any memory that is not `tier: record`

Each item is small and self-contained, so `/memory-refine` works one at a time. Where an item
needs a file re-read, it hands that file to a focused Sonnet subagent with a directive
for that item type (judge this description against this body; propose a split; draft a
`verify:` recipe from this identifier), and sees only the answer. The main session decides
and writes. Replacing a memory goes through `mem supersede`, as direction.md Phase 3 settled.

The queue lives in `.cache/migrate/queue.json`, rebuilt from audit plus summaries, so
finishing an item and re-running `queue` drops it by derivation and there is no state to
drift. An item Matt declines is recorded in `RETRO.md` with the reason, and suppressed by
its key.

**As built (2026-10-23), and where it departs from the above:**

- **The heuristic only ranks.** It flags a summarizer claim `summary+heuristic`, which moves
  it up the queue, and adds nothing by itself. Run as specified on this store it produced
  113 heuristic-only items out of 159, mostly provenance footnotes ("paths checked against
  `25983e9`", repeated across 34 cards/archive files). That is the §14 case of a source
  that is mostly noise, so it was cut at the source rather than tuned.
- **"As landed" is the file at the silo's decisions commit** (or its landing commit when
  there was nothing to decide), read with `git show`. A summary flag drops once the body
  (shape, low confidence) or the description has changed since then, or the file has left
  that path (promotions, relocations, archives, index-only). Using the landing commit
  instead would wrongly count the decisions commit's link rewrites as refinement.
- **Summaries are found by inventory id, not cache key.** After landing, a silo's memory dir
  is a symlink to the territory, so a re-computed key no longer matches.
- **Declining** is a backticked `refine:<key>` anywhere in `RETRO.md`, so the reason sits
  in the prose of the retrospective that made the call.
- **The per-type subagent directives live in the skill**, not in `agents/`, since they are
  one sentence each and only the skill uses them.

First real build, 2026-10-23: 144 items: 46 verify, 45 shape, 17 split-candidate, 16
standing-candidate, 9 frontmatter-not-yaml, 8 stale-live, 3 index-only. No description items,
because the map replaced every non-`good` description at landing.

Stage 5 has no end date. The retrospective (`/memory-retro`) starts reporting queue length
as its health number, in place of reading through territories.

## 9. The repo additions

    agents/
      memory-summarizer.md           # file directive (system prompt for stage 2)
      memory-silo-summarizer.md      # silo directive
      memory-summary.schema.json
      memory-silo-summary.schema.json
    src/claude_hybrid_memory/migrate/       # inventory, summarize, plan, apply, queue
    skills/memory-migrate/SKILL.md   # rewritten: drives stages 1 to 4, holds the checkpoint
    skills/memory-refine/SKILL.md    # new: stage 5

`agents/` holds directives that `mem` passes to `claude -p`; they are not Claude Code agent
definitions and are not symlinked anywhere. The refine subagents use the same files
through the Agent tool's prompt, with `model: sonnet`. `mem install` links the new skill
like the others.

## 10. Testing

The summarizer is a command, so tests swap in a fake one (`--runner`, or
`CLAUDE_MEMORY_SUMMARIZER`) that returns canned, schema-valid JSON per fixture file. Every
stage is then tested without a model or network: inventory against fixture silos;
summarize's caching, retry, `failed` handling and isolation flags; map from canned
summaries; apply's atomicity, slug-collision stop, two commits, symlink swap, and
restore-on-failure; queue derivation. The schema files are validated against the canned
outputs, so a schema change breaks the tests and not a real run.

A `-m live` test runs the real summarizer on one synthetic file, and is skipped when
`claude` is not on PATH.

## 11. Cost, roughly

This machine's 15 pending silos hold 78 memory files plus 14 silo indexes, about 250 KB,
so about 65,000 tokens of content. Measured in the spike: a file of 3.5 to 5 KB costs 3,600 to 4,400 input tokens
(the file, about 2,000 of directive and schema, and the 640 floor), 450 to 570 output
tokens, **$0.016 to $0.020**, and 4 to 5 seconds. **About $2 and 350,000 Sonnet input tokens
to summarize everything here**, a few minutes at `--jobs 4`. Stage 3 reads a table of a
few thousand tokens. *Measured on the real run (§12): $1.64, 575,070 tokens in, 41,077 out,
2 minutes.* Input ran above the estimate because each silo job carries the whole
`ROUTER.md`, and the files ran larger than the spike's sample.

## 12. Build order

Matt's call that this runs ahead of Phase 5, as Phases 3 and 4 did. Nothing in it reads
events, and its isolation (§5) keeps it out of Phase 2's measurements.

1. **Spike.** Run the isolation flags by hand on one file and confirm: no SessionStart
   context, no event logged, no session saved, structured output valid, input tokens per
   call. *Exit:* the measured context per call is the directive plus the file plus less
   than 2,000 tokens of anything else. If `CLAUDE.md` or a hook cannot be kept out, fix
   that first: it is the whole premise.

   *Done 2026-10-23, exit met.* Probes asked the model to list every block in its context:
   - with hooks on, the SessionStart router arrived and a project directory was left
     behind. With `disableAllHooks`, neither happened;
   - `--setting-sources ""` removed `CLAUDE.md`: the floor fell from 944 tokens to 642,
     leaving only the preamble, email and environment;
   - no events were logged, and `~/.claude/projects` gained no directory;
   - `--json-schema` returns the object in `structured_output`, enforced through a tool
     turn (`num_turns: 2`).

   Three runs on one small silo's files gave specific, correct conclusions,
   `names-subject` on descriptions that only named the card, and `accreted` and
   `dated-snapshot` where they applied. Two directive fixes came out of it: `verify` now
   asks only for state claims, at most 3 (the first draft flagged every path), and
   `territory_hint` is null unless the file is about another project (the first draft
   echoed the silo's own project). The tested directive and schema are in `agents/`.
2. **Inventory and summarize**, with the fake runner and tests. Then run on
   one small silo (7 files) and Matt reads the summaries beside the files.
   *Exit:* Matt judges the conclusions and flags right on that silo.

   *Built 2026-10-23:* `mem migrate inventory | summarize | summaries`
   (`claude_hybrid_memory/migrate/`), with 8 tests against a fake summarizer (isolation flags,
   empty cwd, caching by content, retry once, schema refusal). Run on **all 15 silos**
   rather than one, since the spike had already shown the quality: 93 jobs (15 silo, 78
   file), 93 ok, $1.64, 2 minutes, no project directory or event left behind. What it
   showed for stage 3:
   - **Territory: code decides new vs existing, not the model.** It named `solo/cbz-tagger`
     "existing" (the router plans it) but `solo/onion-kids-mode`, from the same router
     line, "new". The name was right both times; the label is not to be trusted.
   - **`territory_hint` is noisy.** It fired on sub-subjects inside the right silo ("->
     docs" in a docs repo, "-> itinerary" in a travel silo). The inventory's
     `repos` is the better relocation signal; the hint stays as a weak second signal.
   - **`standing-candidate` overcalls.** Project-specific rules (one project's writing
     style, another's safety ethos) are flagged; so is a rule `standing/` already holds
     (use uv). Promotion is a refine item anyway, never automatic, so this costs nothing at
     landing.
   - **`verify` is generous**: most live-looking files carry 2 or 3. In line with Matt's
     view that the need to verify is low, the queue ranks a claim only when the
     heuristic agrees, and treats the rest as a low tier.
   - **`description_verdict` was `names-subject` for most files**, as expected of
     auto-memory files that named a topic. Stage 4 replaces those with the conclusion.

   *Stages 3 and 4 run 2026-10-23.* Matt approved the drafted map unchanged: 12 new
   territories, 74 files to land and 4 to archive, 49 descriptions replaced. Apply landed all
   15 silos in 30 commits, in under a minute, with no new audit error. Afterwards:
   - `mem status` shows all 44 silos migrated and none pending, which is direction.md Phase 6's exit;
   - the always-loaded layer is about 6,200 tokens;
   - `mem render --check` is clean, and the SessionStart hook loads.

   Two colliding `user_profile.md` files were prefixed with their territory's leaf name,
   and links inside each silo followed. Archiving cbz-tagger's built spec rewrote 5 links into it.
   For Matt to tidy by hand: the router's solo line still says "All [legacy]", and its
   header still says "migrated: 9 of 19".

   *Stage 5 built 2026-10-23:* `mem refine queue`, `skills/memory-refine/SKILL.md`, and
   fixture tests for derivation, dropping and declining. The exit (one session works ten
   items) is still open.
3. **Map and apply**, fixture-tested, then one real silo end to end. *Exit:* `silo-migrated`,
   two commits, no new audit errors, `mem migrate undo` restores it exactly.
4. **The remaining silos here**, through the one checkpoint. *Exit:* `mem status` shows no
   pending silos (direction.md Phase 6's exit).
5. **Queue and `/memory-refine`.** *Exit:* one session works ten items and the queue shrinks
   by derivation.
6. **The second machine** (direction.md Phase 7): the same run against its own store. Its silo summaries
   also get the chain topology (layers, `consumes:`), so the map can propose `consumes:`
   edges for new territories.

## 13. Follow-ups, not now

Matt, 2026-10-23: worth evaluating later, not blocking.

- **Summarizer over-reach.** `territory_hint` firing on sub-subjects, `standing-candidate`
  on project-specific rules, and a generous `verify` list may share one cause: Sonnet is
  capable enough to reason about its task, and fills fields rather than leaving them
  empty. Candidates to try: say outright that empty and null are the expected common
  answer, give each field a sentence on when it does not apply, and compare flag rates
  before and after on the cached inputs. A directive change re-runs every file it governs,
  about $1.40 here.
- **Archive verdicts on dated plans.** The draft archives a past trip's Kakao-vs-Naver
  choice as over, though it could guide a return trip. "Past" is not "no reusable value".
  Whether the directive should say so is part of the item above.

## 14. Risks

- **A summary is wrong and nobody looks.** Mitigated by landing as-is (a wrong summary
  changes no file text except a `names-subject` description, which is in the second commit
  and the queue), and by `confidence: low` putting a file in the queue regardless.
- **Isolation leaks.** A global instruction or hook reaching the summarizer makes it less
  focused and costs tokens on every call. The spike measures it before anything is built.
- **Relocation by heuristic misfiles.** Repo mentions are a signal, not a verdict: the map
  shows each relocation for Matt, and `territory_hint` disagreement is a refine item.
- **The queue becomes the new backlog nobody works.** Its length is the retrospective's
  number, so it is looked at monthly. Items that are mostly noise get their source deleted,
  per the README's rule about checks that are mostly false positives.
- **Rate limits** with parallel jobs. `--jobs` defaults to 4; failures retry once and are
  then marked, never silently dropped.
