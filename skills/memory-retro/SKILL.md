---
name: memory-retro
description: Run a retrospective on the Claude memory store - mechanical audit plus the judgment pass on whether memories are still true, still useful, and whether the routers would actually have surfaced them. Use monthly, when the SessionStart hook says the retrospective is overdue, or when memory feels stale or wrong.
---

# memory-retro

The self-verification pass. The frame the user gave: sitting down and asking whether your
thoughts are in order, whether you are forgetting things, and whether something should be
optimized. Same activity, faster.

## Procedure

Read `docs/self-verification.md` first; it defines the split between what the tool
decides and what you decide. Then:

    mem audit
    mem events stats
    tail -5 ~/.claude/memory/ALWAYS.md

`mem audit` ranks **split candidates** (files over 10 KB, weighted by accretion markers and
by how often events show them read). For each of the top few, ask *why* it is that big
and whether it should be separate memories; that is a question for the user, not an edit to
make unprompted. The answer is often a split into one state memory plus dated
`tier: record` memories, the original kept by git (`docs/format-spec.md`, "Version
chains"). Sometimes it is that the file is fine as one piece: then `mem no-split <slug> -m
"<their reason>"`, which puts the decline on the file. Do not add a RETRO.md key for it. Files
already declined that way are one `split-declined` INFO line: that line is not a question.
A candidate that *grew past the ceiling* comes with their old reason; ask whether it still
holds. **`split-decline-legacy`** is a split declined in an earlier RETRO.md that never
reached the file. Run the command its message gives (the user already decided), and report how
many you migrated. `superseded-still-indexed` means a
territory index still lists a memory a newer one replaced: drop that line (`mem supersede`
does this itself since 2026-11-04, so a hit means the line was added by hand afterwards).
`mem events stats` shows which memories sessions actually read; a
memory never read across months of events is a candidate for archive, with the same
caveat as parked repos: absence of use is not proof of uselessness.

`obsolete-field` findings are retired `verify:`/`expect:` recipe fields. They are not
claims to check: hand the user the count and the `mem fix --write` that strips them.

**Do not verify memories in bulk.** Claims are checked when a session acts on them
(verify-on-use, format-spec). The retro measures whether that is happening, per
`docs/self-verification.md`, *Verify-on-use: what the retro measures*:

    mem events stats --since <last_retrospective>   # `mem verified` checks, then stale writes
    mem audit --scan store | grep -c stale-live

Report the `verified` count with a few of their notes, the `stale-live` count, and an
evidence-based answer to "did a session act on a stale claim?". That answer is the last
section of `mem events stats`, *written while past window, no `mem verified` from that
session*: each line is a session that edited a memory past its window (judged as of that
session, not today) and never ran `mem verified` on it. Read it; do not redo the join by
hand. Each hit is a missed check, not proof the edit was wrong; open the few `live` ones
and say whether the claim held. Zero `verified` events across two retros goes to the user as a
finding about the directive.

**The `tail` is not optional, and it is the one a retrospective skips.** The layer reaches a
session through `~/.claude/rules/claude-hybrid-memory.md`, which imports `ALWAYS.md`; the
SessionStart hook prints only the short `MEMORY STATUS` block, so its output says nothing
about the layer. `mem audit` covers the numbers: `budget-not-imported` and
`budget-imported-twice` (the import exists exactly once), `budget-always-stale` (`ALWAYS.md`
matches its sources), `budget-truncating` (it renders whole). Then look at the output: this
session is itself a fresh session, so check that the lines `tail` printed are in your own
context, once. That is the check no number can make. On 2026-10-02 the layer had been ~19%
past `MAX_CHARS` for roughly three weeks: the budget reported a soft warn, three
retrospectives read it and reasonably deferred, and all the while the **end** of `ROUTER.md`,
where the binding gates lived, never reached a session. Reading the number was not enough;
nobody had looked at the output. The failure mode is fixed, but the habit is the real
safeguard, because the next such defect will be a different one.

**Read the Declined sections of previous `RETRO.md` runs before reporting anything.** A
finding already declined with a reason does not get re-raised unless the reason no longer
holds. **When you decline, the reason must hold on its own or name a condition that will
arrive.** "Until X is done" is allowed only if X has an end; the 2026-11-03 run declined
253 findings "until the refine queue has been worked", and that queue could not be. This is what stops the retrospective re-litigating settled decisions every month,
which is what makes it survive past its second run.

## The judgment pass, in order

1. **Is verify-on-use happening?** The three numbers above. Not a truth-check of the store.
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
nonsense, and the user has recorded that objection twice
(`feedback-no-manufactured-insight`, `feedback_approach`).

Answer it from direct evidence instead: something re-derived that a memory should have
supplied, or a correction from the user on something previously established. If there is no
evidence, say so. `unknown` is a legitimate answer.

Anything inferred rather than observed gets `confidence: inferred` and is labeled as
Claude's hypothesis, not a fact.

## A good run is not zero findings

A store with zero findings is either brand new or not being used. A good run resolves or
explicitly declines every error, reports the verify-on-use numbers, rewrites at least one
description to carry a conclusion, and answers question 7 honestly. If nothing lands under
**Acted**, either the store is genuinely healthy or the run was not honest, and the second
is more likely.

## Finish by

Appending a dated section to `~/.claude/memory/RETRO.md` with **Acted**, **Declined, with
reasons**, and **Pending**. Update `last_retrospective:` in `ROUTER.md`, which is what
silences the hook's overdue line.

**Before a question goes under Pending, look for its answer in the store.** Read the owning
territory's `MEMORY.md` and search the territory for the subject. On 2026-11-03 the retro
asked the user whether the Character-Tools work had landed; `cards/clients` already recorded it
as archived and obsolete. A question the store can answer is not Pending.

Then report to the user: what the tool found, what you judged, what you changed, and what you
declined. Do not commit anything.
