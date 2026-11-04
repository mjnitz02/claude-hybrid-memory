# Scenarios

Each **repo shape** below is one subagent. Pick real repos on the machine that fit each
shape; ROUTER and `mem hook session-start` show which repos map where. Each task is written
as the user would say it. Swap in topics the store actually covers, so retrieval has a real
answer to find.

## Repo shapes

### A. Mapped repo, large hand-curated territory

The territory with the biggest index, ideally one that `mem render` reports as not rendered.

1. **Retrieve.** "Before I touch <subsystem> again, what do we already know about it?"
2. **Verify-on-use.** Pick a memory you'd rely on that is past its window. Check one concrete
   claim against the repo (read-only), then record the check the way the system wants.
3. **Add.** "Remember this: <a fact that half-overlaps an existing memory>." The overlap tests
   whether anything nudges toward appending instead of a new file.
4. **Replace.** "One of those memories is wrong now; replace it." Pick a memory that has
   backlinks, whether from the index prose, a gate line or another memory.
5. **Cross-silo.** "Does anything in <another territory> depend on this repo?"

### B. Unmapped repo

A repo the hook reports as mapping to no territory, ideally one whose subject clearly
belongs to an existing territory.

1. **Orient.** What is this repo, and what does the store already know? How did you pick
   where to look?
2. **Cross-territory retrieve.** A hardware or ops question whose answer lives in a standing
   rule or in another territory.
3. **Link.** "This repo belongs under <territory>. Hook it up." Use `--legacy <scratch>`.
4. **Add.** "Remember: <a procedure fact>." Note how you chose a volatility and a group.
5. **Standing rule.** "What's my general rule for <a standing directive>?" Name the source.

### C. Mapped repo with its own in-repo docs (run on a smaller model)

A repo whose CLAUDE.md or decision log the territory says outranks it.

1. **Retrieve and upstream.** "Where did we land on <design topic>, and what's the current
   phase?" Then: "What from <the territory this one consumes> constrains this repo?"
2. **Status flip.** "We shipped the thing that was IN FLIGHT." Do the flip the system wants.
3. **Move.** "This fact belongs in <the other territory>. Move it."
4. **Add and discoverability.** Add a fact, then search for it the way a session in a
   *sibling* repo would.
5. **History.** "What changed in this territory's memory recently?" Read-only history commands
   are fine on the real store.

### Optional shapes, when the plugin grows into them

- **A brand-new machine with no store**, using `memory-setup`.
- **A repo returning from parked state**, re-linked with `mem link`.
- **A retro-driven session**, using the `memory-retro` skill end to end.

## Prompt template

Fill the angle-bracket fields and send one per shape. Paste the known `--root` artifacts
from `SKILL.md` into the harness block, word for word.

```
You are role-playing a fresh Claude Code session working in <repo path> so we can evaluate
how intuitive the `mem` memory tooling is to an LLM. This is an evaluation: change no code,
and write nothing to the real store at ~/.claude/memory.

## What you'd see at session start
<the exact `mem hook session-start` text for this repo>
The always-loaded layer is in your context via the user's rules; read <store>/ALWAYS.md
<and the territory MEMORY.md, if mapped> to see what you'd have.

## Harness
- Bash cwd resets after each call: prefix commands with `cd <repo> && ...`.
- Every write uses `--root <scratch store>` and edits files only under that path.
  <the known --root artifacts, word for word>. Don't count those as findings.
- Any command that would write to ~/.claude without a sandbox flag: describe it, don't run
  it, and log the missing sandbox as a finding.
- <the machine's interpreter and search-tool rules>. Never run git on the store.
- Don't read the plugin's src/. Use `mem --help`, `mem <cmd> --help`, the hook text, and the
  memories themselves.

## Tasks (in order, as you naturally would)
<the shape's five tasks>

## Report (the deliverable - candid and specific)
For each task: the exact commands in order, what worked first try, what failed (with error
text), and what you guessed. Then:
- Things `mem` asked of you that you wouldn't have worked out natively.
- Moments you used it and weren't confident it worked.
- Moments you were tempted to hand-edit instead of using `mem`, and why.
- Noise vs. signal in the output, and wasted tokens.
- <a shape-specific question, e.g. "is the route from unmapped to routed obvious?">
- Your top 5 gaps, ranked by how much they'd hurt a real session.
Under ~900 words.
```

## Probes no scenario covers

Run these yourself while the subagents work:

- **Window status.** `mem show <slug> --meta` and `mem find <term>` on a memory past its
  window. Does either say so?
- **Default `show`.** Compare `mem show <slug> | wc -l` with the file's length. Is the
  truncation announced?
- **Pulling a territory.** Try the natural guesses: `mem show <territory>`,
  `mem show territories/<t>/MEMORY.md`, `mem find --territory <t>` with no terms.
- **Harness-recipe write.** On scratch, write a memory the way the Claude Code system prompt
  describes: frontmatter nested under `metadata:`, plus a hand-added index line. What do
  `audit` and `render` say?
- **Render state.** `mem render <t> --root <scratch>` for every territory. Which are
  hand-curated?
- **Write side effects.** Diff `audit` before and after a single `mem new`. Is every new
  warning attributable and explained?
- **Duplicates.** `mem dup` after a deliberate near-duplicate.
- **Speed.** `/usr/bin/time -p` on `find`, `show`, `status`, and the hook.
