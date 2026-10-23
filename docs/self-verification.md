# Self-verification: the retrospective

Run by `/memory-retro`. The human analogy Matt used is sitting down and asking: are my
thoughts in order, am I forgetting things, should I optimize something. That is the right
frame. The difference is only speed.

Default cadence: monthly. That is a guess, and the first few runs should calibrate it.
`ROUTER.md` carries `last_retrospective:`, and the SessionStart hook prints one line when
it is overdue. That line is the trigger, so the retrospective does not depend on Matt
remembering.

## The split: what the tool decides and what Claude decides

The tool handles what is mechanically checkable. Claude handles what needs judgment. The
split is deliberate, because a script that renders verdicts it cannot support produces
confident nonsense, and the old memories had already recorded that objection twice, as
feedback against manufactured insight.

**Tool, via `mem.py audit`:**

| Check | Catches |
|---|---|
| `no-frontmatter`, `missing-*`, `bad-*` | files that do not meet spec |
| `dangling-link`, `ambiguous-slug`, `orphan` | a broken link graph |
| `router-ghost`, `router-unlisted` | a router that disagrees with its directory |
| `override-target-missing`, `supersede-self`, `supersede-cycle`, `supersede-ambiguous` | a contradiction sitting quietly |
| `superseded-still-indexed` | a hand-written index still routing to the old word |
| `stale`, `stale-live`, `verify-due` | claims past their volatility window |
| `verify-contradicted` | a claim the world now disagrees with |
| `verify-refused` | a recipe that violates the execution constraints |
| `budget-high`, `standing-cap` | an always-loaded layer near the hook's truncation limit, or past its file-count cap |
| `silo-workdir-gone` | memory for a directory that no longer exists |
| `silo-mixed-state` | a slug living in two homes |
| `possible-duplicate` | the same description in two territories. **A hint, not a verdict.** |

**Claude, reading the report:**

1. **Is it still true?** Only for what `verify:` could not settle. Check against the
   world, not against the memory.
2. **Is it still useful?** Some memories are true and will never be load-bearing again.
   True is not the same as worth loading.
3. **Was the router predictive?** For each memory used since the last retro: would its
   `description` have caused a session to open it at the right moment? If not, rewrite the
   description. This is the check that keeps the routers honest, and nothing else does it.
4. **Is a boundary wrong?** A territory doing two jobs wants splitting. A territory
   exporting more than about six facts probably has its boundary in the wrong place.
5. **Are there standing directives hiding in territories?** The `uv` rule lived in 11
   silos because it was globally true with nowhere global to live.
6. **What did I re-derive?** See below.

## "Am I forgetting things?"

The highest-value question and the hardest to answer honestly.

The tempting approach is mining `~/.claude/history.jsonl` for rediscovery signals.
Assessed honestly: that detector would be fuzzy, repeated file reads are also just normal
work, and it would emit confident nonsense. So it is not the primary mechanism.

**The primary mechanism is capture at the moment it happens.** During any session, when
either of these occurs, it is the signal:

- Claude re-derives something a memory should have supplied.
- Matt corrects Claude on something that was previously established.

`/memory-retro` asks the question directly while evidence is fresh: *what did I have to
work out this session that a memory should have told me?* An honest answer to that beats
any detector over transcripts.

Transcript analysis stays available as a labeled experiment. It makes no headline claims,
and a finding from it is `confidence: inferred` until confirmed.

## RETRO.md

The retrospective logs its own decisions, or it re-litigates them every month and stops
getting run.

    ## 2026-10-04

    Scanned: 163 files, 10 territories.
    Ran 14 verify recipes: 11 confirmed, 2 contradicted, 1 unrunnable.

    ### Acted
    - gateway-adoption: verify said MERGED, memory said BLOCKED. Re-dated, status SHIPPED.
    - Rewrote 3 descriptions that named a subject instead of a conclusion.

    ### Declined, with reasons
    - 23 `stale` findings in mine/misc. Those projects are dormant by choice, not rotted.
      Do not re-raise: dormancy is the expected state there.
    - possible-duplicate between chain/apps and chain/templates: read both, they are
      genuinely different facts about the same render. Not a duplicate.

    ### Pending
    - chain/templates still has no memory. Biggest content gap.

A later run reads the **Declined** sections and suppresses those findings. Anything
declined is declined with a reason, so a future session can tell whether the reason still
holds rather than guessing.

## What a good run looks like

Not zero findings. A store with zero findings is either brand new or not being used.

A good run means: every error resolved or explicitly declined, every contradicted claim
re-dated, at least one description rewritten to carry a conclusion, and an honest answer
to *"what did I re-derive?"* (the skill numbers it; do not cite a number here, because the
list has grown once already and a stale cross-reference is the exact failure this store is
about). If a run produces nothing under **Acted**, either the store is genuinely
healthy or the run was not honest, and the second is more likely.

## Failure modes to watch for in the system itself

- **The freshness report becomes noise.** If most memories sit `stale`, the volatility
  defaults are wrong, not the memories. Re-tune `STALE_AFTER`.
- **`standing/` creeps toward the cap.** The cap is 20 files and is hard on purpose.
  Hitting it means ranking, not raising.
- **The always-loaded layer overflows and nobody looks.** This one actually happened, on
  2026-10-02, and it is the sharpest illustration of why a retrospective must inspect
  *output* and not only reports. The layer sat ~19% past the hook's `MAX_CHARS` for roughly
  three weeks. The budget check dutifully reported a soft warn; three retrospectives read
  the warn and deferred, each reasonably, because a warn is by construction something that
  can wait. Meanwhile the hook was truncating its tail — and the tail of the injected order
  was `ROUTER.md`'s exports block, i.e. the binding gates. **Two general lessons:**
  - **A signal that does not change when the thing it guards begins to fail is worse than
    no signal**, because it converts a live defect into a recurring agenda item. The budget
    now reports an **error** past `MAX_CHARS`, not a louder warning.
  - **Never let the overflow policy be "drop whatever sorted last".** Assembly order has
    nothing to do with worth, so tail-truncation reliably sacrifices the most important
    thing if the most important thing happens to be written last. Degrade in a declared
    order, cheapest first, and make every degradation announce itself in-band.
- **Task state colonises an always-loaded file.** Directives acquire punch lists; the punch
  list outgrows the directive. It is paid in every session and is invisible in the audit,
  which only counts files and tokens. The retro's judgment pass asks about it directly.
- **A check that is mostly false positives.** Delete it. The wikilink extractor originally
  reported 11 dangling links of which 10 were Copier template delimiters, and a
  word-frequency "standing candidate" detector returned words like "how" and "2026". Both
  were fixed or removed rather than tuned. A category that is mostly noise trains everyone
  to ignore the category.
