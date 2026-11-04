# Overview: why it exists and how it works

The longer version of the README's pitch. For the full model and the alternatives rejected
along the way, see [`design.md`](design.md); for the format `mem` enforces, see
[`format-spec.md`](format-spec.md).

**Hybrid** because markdown stays the source of truth for knowledge. A derived SQLite
cache, committed usage events and the store's own git history do what markdown is bad at:
search, provenance, version chains and audits over time.

This repo holds **the method**. It does not hold memories.

| | Crosses machines? | Lives where |
|---|---|---|
| Spec, setup, migration, tooling, skills | Yes, via this repo | here |
| Actual memory content | No, deliberately | `~/.claude/memory/`, local git history only, no remote |

## Why this exists

Claude Code's per-project memory works, but it is keyed on directory, and that cuts
straight through the middle of any system spanning many repos. An audit of one machine
found 186 memory files across 25 silos with 435 internal wikilinks and exactly **two** that
crossed a silo boundary, while 64 file-pairs referenced another silo's repo in prose. 104
of them were over a month cold, with no way to tell stable from rotted, and the same
"use `uv`" directive had been written into 11 separate silos.

The format was not the problem. The missing pieces were a router, cross-repo reach, and
computable freshness.

## How it works

    ~/.claude/memory/
      MACHINE.md          # machine identity + calibration      ┐
      GATES.md            # irreversible-harm rules, max 5      │ rendered into ALWAYS.md,
      standing/           # directives true in every repo      │ which a rules file imports
      ROUTER.md           # one line per territory + PULL WHEN  ┘
      ALWAYS.md           # generated: the four above as one file, gitignored
      territories/<path>/
        MEMORY.md         # the territory router, auto-loaded by Claude Code
        EXPORTS.md        # the contract for territories downstream
        <slug>.md         # internals, read on demand
      archive/            # retired, never loaded
      events/             # committed usage history (JSONL)
      .cache/             # derived SQLite + FTS5 index, gitignored

- **Territories, not directories.** A repo's `~/.claude/projects/<slug>/memory` becomes a
  symlink to its territory. Several repos can share one memory home, and Claude Code's own
  auto-load picks it up with no custom loader.
- **Routers, not indexes.** Every entry says *when* to pull it, and every description
  carries the conclusion rather than the subject.
- **A budget that degrades in a declared order.** Gates are never cut. Standing directives
  collapse to their descriptions first, and the map goes last. Every degradation announces
  itself.
- **Freshness you can compute.** `status` implies a volatility window, and `last_verified`
  says when the claim was last seen true. A session checks a claim past its window right
  before acting on it, then stamps it with `mem verified`.
- **Replace, never edit.** A newer memory declares `supersedes:`. The old one stays
  byte-identical, and git holds the history.

The hooks that keep this running, and how to see exactly what a session is handed, are in
[`commands.md`](commands.md#hooks).

## Two rules worth knowing before touching anything

**The format may not make a memory more expensive to write than it is to rediscover.** The
old system's real virtue was that writing a memory was nearly free. Only four fields are
required; everything else is inferred, optional, or autofixed.

**A check that is mostly false positives gets deleted, not tuned.** The wikilink extractor
first reported 11 dangling links, of which 10 were Copier template delimiters. A
word-frequency "standing directive" detector returned words like "how" and "2026". The
first was fixed and the second removed. A category that is mostly noise trains everyone to
ignore the category.

## Status

Built in phases, each with an exit check recorded in [`direction.md`](direction.md). The
cache, hooks, version chains, rendered indexes and fast adoption are built. The refine
queue (`/memory-refine`) is next.
