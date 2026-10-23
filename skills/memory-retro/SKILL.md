---
name: memory-retro
description: Run a retrospective on the Claude memory store - mechanical audit plus the judgment pass on whether memories are still true, still useful, and whether the routers would actually have surfaced them. Use monthly, when the SessionStart hook says the retrospective is overdue, or when memory feels stale or wrong.
---

# memory-retro

The self-verification pass. The frame Matt gave: sitting down and asking whether your
thoughts are in order, whether you are forgetting things, and whether something should be
optimized. Same activity, faster.

## Procedure

Read `docs/self-verification.md` first; it defines the split between what the tool
decides and what you decide. Then:

    mem audit
    mem fresh --run
    mem hook session-start | jq -r .hookSpecificOutput.additionalContext | head -40
    mem events stats

`mem audit` ranks **split candidates** (files over 10 KB, weighted by accretion markers and
by how often events show them read). For each of the top few, ask *why* it is that big
and whether it should be separate memories; that is a question for Matt, not an edit to
make unprompted. The answer is often a split into one state memory plus dated
`tier: record` memories, the original kept by git (`docs/format-spec.md`, "Version
chains"). `superseded-still-indexed` means a
territory index still lists a memory a newer one replaced: drop that line.
`mem events stats` shows which memories sessions actually read; a
memory never read across months of events is a candidate for archive, with the same
caveat as parked repos: absence of use is not proof of uselessness.

`--run` executes `verify:` recipes under hard constraints (allowlisted commands, no shell
interpretation, mutating subcommands denied, 20s timeout). Report contradictions as
findings, do not silently fix a memory to match the world without saying so.

**The third command is not optional, and it is the one a retrospective skips.** Run the hook
and look at what it actually emits — length, and whether the `MEMORY STATUS` block reports a
degradation. `mem budget` tells you the layer's size; only the hook tells you what a
session is really handed. On 2026-10-02 the layer had been ~19% past `MAX_CHARS` for roughly
three weeks: the budget reported a soft warn, three retrospectives read it and reasonably
deferred, and all the while the hook was silently dropping the **end** of `ROUTER.md`, which
was where the binding gates lived. Reading the number was not enough; nobody had looked at
the output. The failure mode is fixed — degradation is now ordered and announces itself — but
the habit is the real safeguard, because the next such defect will be a different one.

**Read the Declined sections of previous `RETRO.md` runs before reporting anything.** A
finding already declined with a reason does not get re-raised unless the reason no longer
holds. This is what stops the retrospective re-litigating settled decisions every month,
which is what makes it survive past its second run.

## The judgment pass, in order

1. **Still true?** Only for what `verify:` could not settle. Check the world, not the memory.
2. **Still useful?** True is not the same as worth loading.
3. **Was the router predictive?** For memories used since the last retro: would the
   `description` have caused a session to open it at the right moment? If not, rewrite the
   description. Nothing else performs this check.
4. **Is a boundary wrong?** A territory doing two jobs wants splitting. More than about six
   exports means the boundary is misplaced.
5. **Standing directives hiding in territories?** The `uv` rule lived in 11 silos because
   it was globally true with nowhere global to live.
6. **Is anything in the always-loaded layer task state?** The inverse of 5, and the more
   expensive error, because it is paid in every session rather than missed in one. Punch
   lists, open-item tables, rescan commands and "still to do" blocks are not directives — they
   are work tracking that drifted into a file that happens to be always loaded. One such file
   grew to 23% of the entire layer and was crowding out the gates; its own closing line had
   predicted exactly that and asked for it to be cut, and three retrospectives read past it.
   **A standing directive states what is always true. The moment it starts tracking what is
   currently open, split it:** the rule stays, the state moves to a territory, and the
   directive becomes a pointer.
7. **What did I re-derive?** Answer honestly, from this session and recent ones.

## Question 7 is the important one, and it has a rule

Do NOT build or run a transcript-mining detector over `~/.claude/history.jsonl` to answer
it. Repeated file reads are also just normal work, so such a detector emits confident
nonsense, and Matt has recorded that objection twice
(`feedback-no-manufactured-insight`, `feedback_approach`).

Answer it from direct evidence instead: something re-derived that a memory should have
supplied, or a correction from Matt on something previously established. If there is no
evidence, say so. `unknown` is a legitimate answer.

Anything inferred rather than observed gets `confidence: inferred` and is labeled as
Claude's hypothesis, not a fact.

## A good run is not zero findings

A store with zero findings is either brand new or not being used. A good run resolves or
explicitly declines every error, re-dates every contradicted claim, rewrites at least one
description to carry a conclusion, and answers question 7 honestly. If nothing lands under
**Acted**, either the store is genuinely healthy or the run was not honest, and the second
is more likely.

## Finish by

Appending a dated section to `~/.claude/memory/RETRO.md` with **Acted**, **Declined, with
reasons**, and **Pending**. Update `last_retrospective:` in `ROUTER.md`, which is what
silences the hook's overdue line.

Then report to Matt: what the tool found, what you judged, what you changed, and what you
declined. Do not commit anything.
