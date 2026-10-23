# Format spec

The definitive reference for writing anything into the memory store. `mem`
enforces this document; if the two disagree, this document is wrong or the tool is stale,
and one of them gets fixed rather than worked around.

Audience note: **files in the store are written for Claude, not for humans.** Optimize for
retrievability and unambiguous tagging even where that costs readability. The docs in
*this repo* are the opposite: they are for people and Claude both, so they read normally.

## The governing constraint

> **The format may not make a memory more expensive to write than it is to rediscover.**

Four required fields. Everything else is optional, derived, or filled in by `mem.py fix`.
If a rule here ever makes writing a memory feel like paperwork, the rule is wrong.

## Store layout

    ~/.claude/memory/
      MACHINE.md               # machine identity + calibration. always loaded.
      GATES.md                 # irreversible-harm rules. always loaded, never degraded. max 5.
      ROUTER.md                # the map. always loaded, degraded last if it must be.
      RETRO.md                 # retrospective log: found / acted / declined-and-why
      standing/<slug>.md       # always loaded. capped by file count.
      territories/<path>/
        MEMORY.md              # the territory router. auto-loaded by the harness.
        EXPORTS.md             # optional. the contract for the layer below.
        <slug>.md              # internals. loaded on demand.
      archive/<name>/          # retired. never loaded.

Territory paths are `chain/*`, `utility/*`, `infra/*`, `mine/*`, `solo/*`, `reference/*`,
`meta/*`. Path grouping is for router legibility and implies nothing about shared loading.

## Memory file

### Required, and only these four

    name          kebab-slug. THE link target. MUST equal the filename minus .md.
    kind          standing | territory
    description   one line. becomes the router hook. carries the CONCLUSION, not the subject.
    volatility    stable | slow | live. omit if `status` implies it (see below).

### Optional

    status          SHIPPED | PARKED | STILL LIVE | BLOCKED | IN FLIGHT | RESOLVED | HISTORICAL
    last_verified   YYYY-MM-DD. `mem.py fix` stamps it if absent.
    verify          the literal check that settles this. constrained, see below.
    expect          what the check should show.
    role            gate | reference
    exhaustive      false = absence from a list here is NOT evidence of a negative
    source_of_facts false = anti-source. never cite as truth.
    overrides       <standing-slug>, or `CLAUDE.md` for a rule the user authored there.
    supersedes      <slug>, container/slug, or a list of them. the OLDER memory is never
                    edited; see "Version chains" below.
    tier            state | record. omit for state. record = dated, written once, never edited.
    confidence      asserted | inferred. inferred = Claude's hypothesis, unconfirmed.
    splittable      free-text hint
    owner           self | colleague | employer | third-party
    mode            active | occasional-pr | reference | dead-upstream | scratch | parked
    origin_session  uuid

### Body

The fact first, in one or two sentences. Then, where the kind warrants it:

    **Why:** the reason, so a future session can tell whether the reason still holds.
    **How to apply:** what to actually do differently.

Link related memories with `[[slug]]` liberally. A link to a slug that does not exist yet
is acceptable and marks something worth writing; the tool reports it as `pending` rather
than an error when the target name appears in a router.

### The description field carries the conclusion

    BAD:  notes on the batch command
    GOOD: SHIPPED 2026-07-30, resume dropped, not yet run against the real core-lib

The router loads every session. A hook that names only a subject forces a file open to
find out whether it matters, which defeats the point of having an index.

## Version chains, and state vs records

When a memory replaces another, the **newer** one says so: `supersedes: <slug>`. The older
file stays byte-identical. It is not edited to say HISTORICAL and it is not archived. Its
`superseded_by` is derived by `mem` from every `supersedes:` in the store and never written
back, so one field has one writer. A memory is superseded when any memory outside
`archive/` names it. Superseded memories drop out of `mem find` (counted, and shown with
`--superseded`), `mem show` says so on its first line, and `mem history <slug>` walks the
chain both ways alongside the file's git log. `mem supersede <old> <new>` writes the line.

A bare slug that exists in two containers resolves to the one beside the newer memory;
otherwise write `container/slug`. A ref that resolves to nothing (a memory merged away
before the store had history) is an `info` finding, not an error: the chain ends there,
and the newer memory is still the current word. The territory index has to drop the old
line by hand until indexes are rendered; `superseded-still-indexed` reports it.

**State vs records** is a convention, not a new kind. A **state** memory is short and
rewritten in place; git holds its past. A **record** (postmortem, measurement,
reverse-engineering notes, decision history) is dated, written once, marked
`tier: record`, and never edited. A correction is a new record plus an edit to the state
memory it affects. A file that has accreted history ("read bottom-up", CORRECTION
blocks) is split into one state memory plus records **when it is next touched**, never in
a bulk pass; the PostToolUse hook says so once per session when such a file is edited.

## `mode: parked`, and the offload cycle it exists for

A common way to work, and load-bearing enough that the format has to represent it:

1. Burn hard on a cluster of repos.
2. Get overloaded and push everything to GitHub.
3. **Delete the local checkouts to get breathing room.**
4. Re-prioritize and pull some back down to work on.

Step 3 is the one that breaks naive tooling. A repo missing from this disk looks exactly
like a repo that died, and the two demand opposite handling. Guessing wrong in the
pessimistic direction is expensive: it archives live knowledge about work that is coming
back, and it is *rediscovery* that the whole store exists to prevent.

So absence from local disk is never, on its own, evidence of anything.

    mode: parked        # pushed to its remote and deleted locally, on purpose. Coming back.

**How to apply.** Never propose archiving a parked repo's memory, never describe the
project as abandoned or dead, and never treat a missing checkout as a finding. Expect the
remote to be ahead of anything remembered locally. When work resumes, the memory is
already there and the repo re-enters at step 4 with its territory intact.

Parked is distinct from the neighbours it is easy to confuse it with: `dead-upstream` is
abandoned by someone else, `reference` was never yours to change, and `scratch` is
expected to have drifted. Parked is *healthy, deliberate, and temporary*.

**It has a runnable check**, which is the point of putting it in the format rather than in
prose:

    verify: gh repo view <owner>/<repo> --json pushedAt -q .pushedAt
    expect: a date at or after the local memory's last_verified

A parked repo answers; a deleted one 404s. That turns "is this dead or resting" from a
judgment call into a command, which is the same move `verify:` makes everywhere else.

`mem.py status` reports a silo whose directory does not resolve as `silo-not-checked-out`,
not as an archive candidate, and `mem.py link --territory <path>` re-points a restored
checkout in one command so step 4 costs nothing.
A silo linked to a territory that is gone (renamed or archived) is `silo-dangling`, an
error: the repo silently loads no memory. `mem.py link` re-points it without the
manual unlink a live link needs.

`mem mv-territory OLD NEW` renames a territory or moves it to another area. It moves the
directory and repoints every silo linked to it. It rewrites the territory's own header,
its ROUTER.md entry (moving it under the new area's section), other territories'
`consumes:`/`consumed_by:`, `container/slug` refs in `supersedes:`, and the migration
plan, keeping an approval the rename did not change. Prose that names the old path is
listed, not rewritten. Without `--write` it only shows the plan; with it, it makes a
checkpoint commit first and reports any audit error the move introduced.

`mem mv SLUG... TERRITORY` moves memories into another territory. A memory is named by
slug, by `area/name/slug` when the slug is ambiguous, or by path. Both indexes follow: a
rendered one re-renders, and a hand-written one keeps the line as written, placed after
the destination's last entry. `container/slug` refs in `supersedes:` follow too. Moving a
`role: gate` memory warns, since gate text is inlined in the territory's head. The
dry run, checkpoint and error report work as for `mv-territory`.

`mem archive TARGET... --why TEXT` retires a whole territory, or some memories, to
`archive/<area>-<name>/` (`--as` names another group). A territory goes as it is, index
included. Its ROUTER.md entry and every `consumes:`/`consumed_by:` naming it are removed,
and every silo linked to it is unlinked, so no repo keeps loading retired memory.
Bringing it back is a deliberate step: move it into `territories/`, then `mem link`.
Retired memories leave their index. A `[[slug]]` pointing at one becomes its archive path,
and `supersedes:` refs follow it. Each call adds a dated line with the reason to the
group's `WHY-ARCHIVED.md`.

## Kinds

### `standing`

A directive that would change Claude's behavior in a repo it has never opened. Always
loaded. **Capped by file count** (start at 20), so admitting one requires evicting or
merging another.

Admission test, both must hold:

1. It would change behavior in a repo Claude has never opened, and
2. violating it produces work the user rejects.

`Use uv` passes. `The eval contract lives in core-lib` fails: that is territory.

A local exception declares its parent:

    name: no-uv-in-legacy-sdk
    kind: territory
    overrides: prefer-uv
    description: STILL LIVE. `uv run` in legacy-sdk wipes .venv; it is pyenv-based.

The tool verifies every `overrides:` target exists. That turns a silent contradiction into
a structural relationship.

**`CLAUDE.md` is a layer above `standing/`.** The user authors it, it loads every session, and
it already carries rules like preferring `uv`. Mirroring those into `standing/` would be
the same copy-paste failure this store exists to end, so `standing/` holds only what
CLAUDE.md does not, and an exception to a CLAUDE.md rule declares `overrides: CLAUDE.md`.

### `territory`

Everything else. Loaded on demand through a router.

## Volatility, derived not predicted

At write time it is often genuinely unknown whether a fact is stable or live, and the
honest fallback is `live`, which floods the freshness report until it gets ignored. So
derive it from `status` when one is present:

| status | implied volatility | re-verify after |
|---|---|---|
| SHIPPED, RESOLVED, HISTORICAL | stable | 365 days |
| PARKED | slow | 90 days |
| STILL LIVE, BLOCKED, IN FLIGHT | live | 14 days |

State `volatility` explicitly only when that default is wrong.

## Verification recipes

`volatility` plus `last_verified` alone is a trap: stamping a date is cheap, re-verifying
is not. Expensive verification does not happen, dates rot, and the result is a *false*
freshness signal, which is worse than none because it gets trusted.

So carry the check itself:

    verify: gh pr view acme/core-lib#123 --json state -q .state
    expect: MERGED

**This is a code-execution surface, so it is constrained. The tool enforces all of it:**

- **Allowlisted leading command only**: `git`, `gh`, `uv`, `task`, `ls`, `test`.
- **Never shell-interpreted.** Argv is exec'd directly. No `shell=True`. A recipe
  containing any of `| & ; > < $ ` ( ) { }` or a newline is **refused**, not sanitized.
- **Mutating subcommands denied**, by explicit pattern: `push`, `merge`, `reset`,
  `checkout`, `rebase`, `commit`, `rm`, `clean`, `delete`, `close`, `create`, `edit`.
- **Timeout-bounded**, 20 seconds per recipe.
- **Off by default.** `mem.py fresh` reports what is due and validates recipes without
  running anything. Execution requires `--run`.

A check that cannot fit those limits goes in prose in the body instead, declares
`unrunnable: true`, and is reported as such rather than silently skipped. A memory about a
hosted page, or one needing two JSON files diffed on a single key, is honestly unrunnable —
say so rather than leaving the field off and hoping.

### Three rules learned by getting these wrong

- **Write `expect:` so it names which result means TROUBLE, not only which means fine.** A
  recipe whose failure mode is a false all-clear is worse than no recipe. A real one checked
  git history for a filename *guessed from prose that never named the file*; it returned
  empty, and the `expect:` line read empty as "already cleaned up" when three files were
  still there under other names. **Build the recipe from an identifier you have confirmed
  exists.**
- **A refused recipe is not a lint nit — the memory is advertising a check it does not
  have.** `grep` is not on the allowlist and `&&` is a metacharacter, so such recipes are
  rejected outright, and `mem.py fresh` can never settle that memory while its frontmatter
  implies it can. Treat `verify-refused` as a correctness error.
- **Write the recipes while migrating or writing the memory, not later.** Naming what would
  falsify a claim is most of the value, and running it checks the world instead of the file.
  Two consecutive migrations found stale claims this way and no other way — a "still
  uncommitted" fix that had merged weeks earlier, a status memory four PRs behind, an open
  question already answered by a CI run nobody had read, and a pointer to a log directory
  holding a two-week-old run.

## Gates are inlined, not linked

A file with `role: gate` accomplishes nothing if "read this first" is a soft convention,
and soft conventions are what failed here. **A gate's text is inlined into the territory
`MEMORY.md`**, inside the harness auto-load window, where it cannot be missed.

The evidence: one silo's hand-grown `READ THIS BEFORE JUDGING STATUS` worked because it was
the first line of the index, not because a file had that name.

## Exports

A territory declares two things: **internals** (the bulk, loaded only when working inside)
and **exports** (the small contract others must obey).

Where an export goes depends on its reach, and there are only two destinations:

- **A `utility/*` export cuts across every layer**, so it goes in `ROUTER.md`, which is
  always loaded. A dependency-policy repo's four binding facts reach every session this
  way while its other 42 files stay home.
- **Every other export is a cluster contract** and is inlined into the consuming
  territory's `MEMORY.md`, because that is the only place it applies. `mem.py` enforces
  this with `export-not-inlined`, matching the export's first 60 normalized characters —
  so a paraphrase fails the check; inline the wording.

**A third destination exists and it is not for exports.** `GATES.md` holds rules whose
violation **damages or exposes something that cannot be put back** — writing to a
production box, committing live credentials, overwriting the only copy of something,
publishing something private. The test is irreversibility, not importance: a correctness
fact belongs to its cluster even when it is load-bearing there, because a session working
in that cluster will load the territory anyway. A gate is different precisely because the
session **cannot know to go looking for it** — it may touch the box from a repo whose
territory it never opened.

`GATES.md` is **capped at five entries.** It is always loaded, emitted immediately after
`MACHINE.md`, and never degraded. A sixth entry means the irreversibility bar has slipped,
not that the machine got more dangerous.

**Why this is a separate file rather than a section of `ROUTER.md`:** on 2026-10-02 the
always-loaded layer was found to be ~19% past the hook's `MAX_CHARS`, and because the hook
assembled `MACHINE -> standing -> ROUTER` and then cut the tail, the part being silently
dropped every session was the END of `ROUTER.md` — which is where the exports block sat.
"Never write to the home server" and "never commit a template with live secrets" had been
dropped for weeks to make room for a CI punch list. A gate that lives at the end of a
growing file is a gate that will eventually be deleted by arithmetic.

`EXPORTS.md` in a territory is the source of truth for what it exports. The copies in
routers are generated from it, and `mem.py drift` reports when they disagree.

Keep exports brutally short. If a territory exports more than about six facts, the
boundary is probably wrong.

## ROUTER.md

Always loaded. Its job is to answer "does anything I am not currently looking at matter
right now". It is a map, never a container.

Every territory must appear in it (`router-missing-territory` is an error). The `(N)` after a
territory's name on its line is the one derived part: the count of its memory files, kept
true by `mem render` and the SessionEnd hook, and `router-count` until then. The rest is
hand-written.

The reverse holds too: an entry naming a territory with no `MEMORY.md` is
`router-unknown-territory`, an error, unless the entry says `NOT YET WRITTEN`, which
marks it planned. A territory's `consumes:` and `consumed_by:` follow the same rule
(`territory-ref-unknown`); a glob such as `home/*` passes while it matches a territory.

    # MEMORY ROUTER
    machine: work-mac
    last_retrospective: 2026-09-04
    territories: 13

    ## chain — product dependency chain. a change at a layer breaks the layer below.
    - chain/foundation — core-lib, sdk, gateway, legacy-sdk.
      PULL WHEN: touching a library the components depend on, or judging a release surface.
    - chain/components — component-* (9). PULL WHEN: template mechanics, config injection, symlink strategy.
    ...

    ## EXPORTS IN FORCE (ONLY utility/*, which binds every layer; everything
    ## else is inlined downstream, and harm rules live in GATES.md)
    - [dep-policy] merge order is dep-policy, then component-*, then the apps
    - [dep-policy] never `uv lock --upgrade`; bumps come only from core-lib or a dep-policy floor
    ...

Hard budget: `MACHINE.md` + `GATES.md` + `standing/` + `ROUTER.md` together are reported in estimated
tokens on every audit, and `standing/` is capped by file count. A budget that can be raised
the first time it trips is not a budget, so **the cap is on count, not size** — that is the
gate on admitting a new always-loaded directive, and it does not move.

**`STANDING_CAP` and `MAX_CHARS` are different things, and conflating them caused a real
failure.** `STANDING_CAP` is the admission gate: a count, deliberately unraisable, still at its
original 20. `MAX_CHARS` is the ceiling on the rendered layer (`ALWAYS.md`) and is the store's
own number, not the platform's. The platform's is `HOOK_OUTPUT_LIMIT`, 10,000 chars on any one
hook's output, which this spec missed until 2026-10-23: the layer was being injected from the
hook, the harness was reducing it to a 2 KB preview, and every check here passed (setup.md
step 3d). Treating the second as if it carried the first's "never move it"
property is why the layer was allowed to sit 19% past it for three weeks: raising it felt like
cheating, so three retrospectives trimmed nothing and raised nothing, and the hook quietly ate
the gates instead.

`MAX_CHARS` went 24,000 → 32,000 on 2026-10-02 with the user's sign-off. **The original 24,000 had no
recorded rationale at all** — `git log -S` puts it in this tool's first commit, chosen when zero
territories had been migrated. The rationale for the new one lives in `session_start.py` beside
the constant, and the rule going forward is that **this number may only be raised with a written
argument, in that comment, and only when all three of these hold**:

1. **The layer holds no slack.** The raise was preceded by removing a CI punch list from
   `standing/` and a duplicated exports block from `ROUTER.md`; the next available cut would have
   been evidence, not fat.
2. **The pressure is structural, not neglect.** `ROUTER.md` grows ~250 chars per territory by
   design, with 10 of 18 still unmigrated. A ceiling that forces a trim every third migration
   makes the system worse as it does its job.
3. **Exceeding it is not dangerous.** Degradation is ordered, bounded and announced, so the
   number sets quality rather than safety. Before that was true — when overflow silently deleted
   whatever sorted last — raising it would have been papering over a live defect, and refusing
   was correct.

The token figure beside it is a secondary signal, and two things about it are deliberate:

- **It measures what is injected, not what is on disk.** `session_start.py` renders a
  directive as `## <description>` plus its body and discards the rest of the frontmatter, so
  counting raw files over-reported the real cost by eleven frontmatter blocks. `mem.py`
  reuses the hook's own renderer; if the two disagree, the tool is what is wrong.
- **The warn is anchored to the degrade point**, `MAX_CHARS`, not set by taste. Past it the
  rendered layer starts losing content, so warning at ~83% of it means "you are approaching
  real content loss." A flat number could not survive the design: the
  un-migrated territories still have to add themselves to `ROUTER.md`, so the layer grows as
  the system works, and a warn that trips on correct behaviour gets ignored — the same failure
  this spec refuses to accept from `last_verified`.
- **And past `MAX_CHARS` it is an ERROR, not a louder warning** (`budget-truncating`). This was
  added 2026-10-02 after the layer sat ~19% over the line for roughly three weeks while the
  report still read as a soft warn. A signal that does not change when the thing it guards
  starts actually failing is worse than no signal, because the three retrospectives that saw it
  each correctly judged "a warn can wait."

**Nothing in the always-loaded layer may carry task state.** Not a punch list, an open-items
table, a rescan command or a "still to do" block. A standing directive states what is always
true; the moment it starts tracking what is currently open, split it — the rule stays, the
state moves to a territory, and the directive becomes a pointer to it. This is not tidiness:
task state in an always-loaded file is paid in every session, grows on its own schedule, and
is invisible to an audit that counts files and tokens. One directive reached 23% of the whole
layer this way, larger than `ROUTER.md`, and was crowding out the gates.

**The hook degrades in a fixed order rather than cutting its tail**, and the order runs opposite
to importance so that the cheapest thing is always what is lost:

1. `MACHINE.md` and `GATES.md` are **never** degraded. If an irreversible-harm rule cannot be
   injected, nothing else in the layer is worth protecting.
2. `standing/` bodies collapse to their `description` lines, **largest directive first and only
   as many as needed.** This is graceful because a description is required to carry the
   conclusion, so the directive still fires; only its reasoning is lost. Biggest-first matters:
   one oversized directive is usually the entire overage, so the cost is one directive's
   reasoning instead of all thirteen.
3. The `ROUTER.md` map is cut **last**, on whole-section boundaries, never mid-word. A missing
   map entry costs a lookup; a missing gate costs a mistake.

Every degradation names itself in a `LAYER NOTES` block at the end of `ALWAYS.md`, so a session is never
quietly handed less context than it believes it has.

## Territory MEMORY.md

Auto-loaded by the harness for every repo pointed at this territory. Harness limit is
200 lines / 25 KB, so this file is a router too, not a container.

**The MEMORIES section is rendered once a territory is adopted** (`mem render <t>
--adopt`). Between `<!-- mem:render begin ... -->` and `<!-- mem:render end -->`, every
line is generated: `- [slug](slug.md) — description`, with a description over 160 bytes
cut at a word boundary and ended with "…" (the line directs to the memory; the memory keeps
the whole description), under a `### heading` from the
memory's optional `group:` field, headings ordered by the territory's
`groups: ["...", "..."]` frontmatter. A superseded memory gets no line; a `tier: record`
or `status: HISTORICAL` memory shares its group's one `Records and history:` line. **Edit
the description or `group:`, never the rendered lines**: `mem render` (and the SessionEnd
hook) rewrite them, and `mem audit` flags a section that differs as `render-stale`.
Everything outside the markers stays hand-written, with one exception: an entry line for
one of the territory's own memories *below* the end marker is taken into the section
(`index-hand-entry` until then). That is where the harness's auto-memory puts the pointer it
appends after writing a file through a migrated silo's symlink, and leaving it would list
the memory twice. A memory its index does not list at all is `router-unlisted`, an error in
the store, since the index is how a session finds it. Until a territory is adopted its index
is hand-written as below. Either way `mem audit` budgets the `## MEMORIES` section, warning
past 100 lines and erroring past 150; the hand-written head above it is not counted. The
whole file still errors past 200 lines or 25,000 bytes, because the harness truncates there,
and warns past 24,000 bytes.

**A territory with no members is legitimate**, and worth knowing about because the obvious
reading is that it must be a mistake. Use it when the subject is a *shape* rather than a
repo — a CI standard shared by repos that live in five other territories, say. There is no
checkout to point at it, so nothing auto-loads it; it is reached by a pointer from a
standing directive, which carries the routing rule while the territory carries the detail.
Declare `members: {}` and say in the body why it is empty, or the next reader will try to
"fix" it. This is the same split as a directive that routes to a library living outside the
store entirely, and it is the correct home for detail that is too big for `standing/` but
too cross-cutting for any one repo's territory.

    ---
    territory: chain/components
    layer: 2
    consumes: chain/foundation
    consumed_by: chain/recipes
    members:
      component-agent: {owner: employer, mode: active}
      component-base:  {owner: employer, mode: active}
    ---
    # chain/components

    ## GATES — read before acting
    (inlined text of every role: gate memory in this territory)

    ## UPSTREAM CONTRACT — exports from chain/foundation
    (inlined)

    ## MEMORIES
    - [Config injection LANDED](config-injection-prototype.md) — two objects Config/LLMConfig, ...

## Naming

- `name:` is the only link target and must equal the filename minus `.md`.
- Slugs are kebab-case. **No underscores, ever.**
- `mem.py fix` renames offending files and rewrites inbound `[[links]]` rather than
  complaining. This is the fix for the roughly 8 currently dangling links.

## Pointing a repo at a territory

Preferred, and leaves no footprint in a repo you do not own:

    mv  ~/.claude/projects/<slug>/memory  ~/.claude/projects/<slug>/memory.premigration
    ln -s ~/.claude/memory/territories/<path>  ~/.claude/projects/<slug>/memory

Alternative, when the mapping should be explicit and reviewable in the repo. Check that
the repo gitignores the file first:

    // <repo>/.claude/settings.local.json
    { "autoMemoryDirectory": "~/.claude/memory/territories/<path>" }

Verified 2026-09-04 against CLI 2.1.260: `autoMemoryDirectory` exists, the memory
directory may itself be a symlink, and the harness auto-loads only `MEMORY.md`.

## Worked examples

### A standing directive

    ---
    name: prefer-uv
    kind: standing
    description: Use `uv run` / `uv pip`, never bare python or pip. Exceptions declare `overrides: prefer-uv`.
    volatility: stable
    last_verified: 2026-09-04
    ---
    All Python work goes through `uv`: `uv run`, `uv pip install`.

    **Why:** consistent resolution, and every project in the chain is uv-based.

    **How to apply:** never invoke bare `python`, `python -m`, or `pip`. One known
    exception exists: [[no-uv-in-legacy-sdk]].

### A gate

    ---
    name: edit-the-recipe-not-the-render
    kind: territory
    role: gate
    description: STILL LIVE. acme-community/app-* are GENERATED from template-*; edits there are lost.
    volatility: stable
    last_verified: 2026-09-04
    ---
    A harness inside `template-*` filters the repo (mainly stripping the harness
    tooling) and produces `acme-community/app-*`.

    **Why:** the community repos are render outputs, not sources. Work committed there sits
    downstream of a generator and is overwritten.

    **How to apply:** make the change in the `template-*` repo and re-render. Same trap class
    as [[dep-policy-render-wiring-missing-format]].

### A live memory with a runnable check

    ---
    name: gateway-adoption
    kind: territory
    status: BLOCKED
    description: BLOCKED 2026-09-04 on acme/gateway#123; dep-policy side merged at 0.0.55, nothing technical blocking.
    verify: gh pr view acme/gateway#123 --json state -q .state
    expect: MERGED
    last_verified: 2026-09-04
    ---

`volatility` is omitted because `status: BLOCKED` implies `live`.
