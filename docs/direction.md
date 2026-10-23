# Direction: a hybrid store

Status: PROPOSED, 2026-10-21. Nothing built. This document is for aligning on direction
before any code exists; §16 lists the decisions that are Matt's to make.

Revises `design.md`. Where the two disagree, this one wins once accepted, and
`design.md` keeps its text as the record of why the first version was built the way it
was.

## 1. The short version

Markdown stays the source of truth for **knowledge**. Everything markdown is bad at moves
into tooling around it:

| Concern | Today | Proposed |
|---|---|---|
| Knowledge (gates, directives, state, records) | markdown | **markdown**, unchanged as the write format |
| History of a memory | prose inside the file ("read bottom-up") | **git** on the store, plus explicit version chains |
| Usage (reads, confirmations) | nothing | **append-only JSONL events**, committed with the store |
| Search and partial reads | `rg` + whole-file `Read` | **SQLite FTS5 cache**, derived, deletable at any time |
| Territory index (`MEMORY.md` MEMORIES section) | hand-maintained | **rendered** from frontmatter + usage, against a budget |
| Integration | one SessionStart hook | **hooks** do the work; a small **MCP** server serves reads |

One rule holds the design together: **SQLite is a cache, never a source.** Every fact in it
is rebuildable from markdown plus the event logs. That makes the database choice cheap to
reverse, makes the store recoverable from git alone, and keeps "unwrap it back into
markdown" true by construction.

## 2. Why change: the evidence

Measured on the personal Mac, 2026-10-21.

| Fact | Value | Why it matters |
|---|---|---|
| Territory internals | 296 files, 1.27 MB (~320k tokens) | never loaded wholesale, which is correct |
| Largest file | 39 KB (`ca-to-compose-migration.md`) | ~10k tokens to read for one paragraph |
| `console/tools` `MEMORY.md` | **195 lines**, 20 KB | harness auto-load cap is 200 lines / 25,000 bytes, re-verified in the 2.1.306 binary (`D$=200,kde=25000`). Past it, the tail is silently dropped — the 2026-10-02 failure again, one level down. `mem.py` does not check it. |
| `cards/archive` `MEMORY.md` | 177 lines | next |
| Files with accretion markers | 24 of 296 ("read bottom-up", CORRECTION, SUPERSEDED, "history below") | mutable files are acting as logs |
| Metadata coverage | `last_verified` 125/296, `verify:` 50/296, volatility absent on 228 | staleness is uncomputable for most of the store |
| Usage data | none | no way to know which memories earn their place |
| Legacy silos still holding content | 15 silos, 91 files | migration is two-thirds done |

The format was never the problem; `design.md` was right about that. What is missing is a
**lifecycle** (nothing ever leaves the index), **history** (so files accrete instead), a
**usage signal**, and **granular reads**.

## 3. Assumptions revisited

| `design.md` said | Now | Why |
|---|---|---|
| No MCP: tool definitions cost context every session | **Withdrawn** | the harness defers MCP tool schemas behind tool search; a dormant tool costs a name in a list. The remaining objection is infra, and a stdio server spawned per session is not a daemon. |
| No vector DB, embeddings or RAG | **Kept, with evidence** | agentmemory's own coding-agent benchmark: BM25-only P@5 95.0% vs 87.0% for its BM25+vector+graph default; grep within 0.013 P@5 of hybrid on its second corpus. Embeddings help on conversational recall (LongMemEval), which is not this workload. |
| Stdlib only, no dependencies | **Relaxed** | each dependency must earn its place (§11). Still no embedding model. |
| The store is never committed | **Dropped 2026-10-21** | history is what lets a correction replace text instead of appending to it. Content still never crosses machines: local git, no shared remote. |
| Markdown is the source of truth | **Kept for knowledge; narrowed** | usage events and indexes were never markdown-shaped. |
| Transcript mining rejected | **Kept** | claude-mem's dedup machinery shows the cost of capture-first. |
| The format may not make a write more expensive than rediscovery | **Kept, load-bearing** | no new required fields. Everything new is derived, optional, or stamped by a hook. |
| Harness auto-loads only `MEMORY.md`, 200 lines / 25 KB | **Re-verified on 2.1.306** | unchanged. |

## 4. What the three reference systems taught

`~/workspaces/claude-mem`, `~/workspaces/agentmemory`, `~/workspaces/mem0`, read 2026-10-21.

The first two are the same species as this store: local, single-user, hook-driven, built for
a coding agent. mem0 is a service for cloud agents sharing state, and is mostly a source of
counter-examples.

Where all three agree, and this store currently does not:

1. **Never destructively overwrite a memory.** mem0 is ADD-only; agentmemory keeps a version
   chain with `isLatest`; claude-mem snapshots imported notes.
2. **Never load everything.** Budgeted, ranked injection.
3. **Every memory knows where it came from.**
4. **Markdown a person wrote is never rewritten by the tool.** Both markdown bridges import
   or export and refuse to overwrite.

Where they disagree, and what this design picks:

| Question | Options seen | Pick | Why |
|---|---|---|---|
| How "current" is resolved | read-time temporal ranking (mem0, platform-only) vs write-time `isLatest` (agentmemory) | **write time** | it is decided once, by the session that knows |
| Stale memory | delete (agentmemory auto-evict) vs hide (claude-mem) | **hide** | a multi-hour hardware measurement unread for 90 days is still the only copy |
| What reinforces a memory | every read (agentmemory) vs re-confirmation (claude-mem) | **both, weighted** | a read says *relevant*; a confirmation says *still true* |
| Who writes | hooks + LLM compression (all three) | **Claude, deliberately** | this store is curated; that is its advantage |

Borrowed, in priority order: version chains; two-strength reinforcement; a write-time
near-duplicate hint; a budgeted rendered index; a secret scan; automatic provenance.
claude-mem's read gate was considered and dropped (§9). Declined: embeddings, knowledge graphs, auto-capture,
LLM-compressed bodies, auto-eviction, team and multi-agent features.

## 5. Architecture

    ┌────────────────────────── ~/.claude/memory/  (local git, no remote) ─────────────┐
    │  MACHINE.md  GATES.md  ROUTER.md  standing/*.md                                  │
    │  territories/<t>/MEMORY.md   ← hand-written head + RENDERED MEMORIES section     │
    │  territories/<t>/<slug>.md   ← source of truth for knowledge                     │
    │  archive/                    ← searchable on request, never rendered             │
    │  events/YYYY-MM.jsonl        ← source of truth for usage (append-only)           │
    │  .cache/index.sqlite         ← DERIVED. gitignored. delete any time.             │
    └──────────────────────────────────────────────────────────────────────────────────┘
          ▲ Write/Edit (Claude)        ▲ append              ▲ read/rebuild
          │                            │                     │
    ┌─────┴──────┐   ┌─────────────────┴───┐   ┌─────────────┴───────────┐
    │ Claude Code│──▶│ hooks  (`mem hook`) │   │ MCP server (`mem mcp`)  │
    │  session   │   │ stdlib-only, <50 ms │   │ stdio, per session      │
    └─────┬──────┘   └─────────────────────┘   └─────────────▲───────────┘
          └────────────── tool calls: memory_find / show / history / confirm ┘

    `mem` CLI: index, render, audit, fix, fresh, status, link, migrate, supersede, …

### The five flows

**Session start.** Unchanged in behavior: inject `MACHINE.md`, `GATES.md`, `standing/`,
`ROUTER.md` with the degradation ladder. New: ingest any events appended since the last run
and refresh the cache incrementally, so later lookups are warm.

**Read.** Claude reads a memory with `Read` as today, or through `memory_show`. A
`PostToolUse` hook appends a `read` event. Reads are never blocked or altered; a file big
enough to make whole reads expensive is a maintenance finding, not a read-time problem (§9).

**Write.** Claude writes markdown with `Write`/`Edit` as today. A `PostToolUse` hook
reindexes that one file, appends a `write` event carrying the session id (provenance, without
touching the file), and runs a near-duplicate query; a likely duplicate comes back as
advisory context: *"this resembles `switch-register-shim` (console/tools); consider
superseding it."* The hook never modifies the markdown.

**Query.** `memory_find` returns a compact list; `memory_show` returns metadata, summary or
one section. Claude only reads whole files when it chooses to.

**Confirm.** When a session relies on a memory and finds it still true, `memory_confirm`
appends a `confirm` event. This is the strong reinforcement signal, and it is also the cheap
replacement for most hand-stamped `last_verified` dates.

## 6. Format changes

The governing constraint rules out new required fields. Everything below is optional,
derived, or written by tooling the session runs deliberately.

**Version chains.** A new memory declares `supersedes: <slug>` (the field already exists in
the spec and is used once). The inverse, `superseded_by`, is **derived in the cache and never
written back** into the old file. The old file stays byte-identical, drops out of rendering
and default search, and remains readable through `memory_history`. One field, one writer.

**State vs records** is a convention, not a new `kind`:

- a **state** memory is short and rewritten in place; git holds its past.
- a **record** (postmortem, measurement, reverse-engineering notes, decision history) is
  dated, written once, and never edited afterwards. A correction is a new record plus an
  edit to the state memory it affects.

`tier: record` marks one so rendering knows to keep it out of the index unless it is hot.

**Rendered index.** Each territory `MEMORY.md` gets markers:

    <!-- mem:render begin -->
    …generated MEMORIES section…
    <!-- mem:render end -->

Everything outside the markers (frontmatter, prose, GATES, upstream contract) stays
hand-written and is never touched. Inside, an optional `group:` field on each memory places
it under a heading; adopting a territory derives `group:` once from its current hand-written
headings.

**Provenance** comes from `write` events, not frontmatter. `mem fix` may backfill
`origin_session` into frontmatter in a batch when a human-visible copy is wanted.

**Fields deliberately not added:** confidence scores, salience weights, importance,
`forgetAfter`/TTL. Each one is a judgment taxed onto every write, and every system that has
them computes or defaults them anyway.

## 7. The CLI: `mem`

One entry point, installed with `uv tool install -e` from this repo so edits are live, the
same property the skills symlink has today. Hooks, maintenance and humans use it.

| Command | Does | Notes |
|---|---|---|
| `mem hook <event>` | hook entrypoints: `session-start`, `post-tool` | stdlib-only import path; fails open |
| `mem index [--rebuild]` | refresh the cache from markdown + events | incremental by mtime + content hash |
| `mem find <terms> [--territory] [--all]` | the same compact list `memory_find` returns | for humans and skills |
| `mem show <slug> [--meta\|--summary\|--section H]` | partial reads | |
| `mem history <slug>` | version chain + `git log` of the file | |
| `mem render [<territory>] [--check] [--adopt]` | regenerate rendered sections; `--check` fails on drift or budget; `--adopt` migrates a hand-written index | |
| `mem supersede <old> <new>` | sets `supersedes:` on `<new>`, validates the chain | mechanical help only; writing the new memory is still Claude's job |
| `mem audit` | today's checks plus: 200-line/25 KB cap per `MEMORY.md`, rendered-section drift, secret scan, broken chains, accretion markers, **split candidates** | split candidates rank oversized files by size × read frequency × accretion markers, so the retro asks *why* a file is 39 KB |
| `mem fix --write` | today's autofixes, plus the provenance backfill | |
| `mem fresh [--run]` | verify recipes, unchanged | |
| `mem stale` | ranked staleness: weak reinforcement, cited paths that no longer exist, member-repo commits since last confirmation (parked repos skipped) | replaces most of the judgment pass's legwork |
| `mem status`, `mem link`, `mem budget` | unchanged | |
| `mem migrate <silo>` | the mechanical half of `/memory-migrate`, including a duplicate check against the store | |
| `mem events export\|stats` | inspect usage | feeds the retro |
| `mem commit [-m]`, `mem log`, `mem diff`, `mem restore`, `show/audit --at` | the store's own git, and nothing else's (§16.1) | the SessionEnd hook calls `commit`; sessions never run `git` on the store |
| `mem mcp` | runs the MCP server | |

## 8. The MCP server

**Four tools. Reads plus one event. No write path.**

| Tool | Returns | Size discipline |
|---|---|---|
| `memory_find(query, territory?, include_superseded=false, include_archive=false, limit=10)` | per hit: slug, territory, description, tier, status, last confirmed, matching section headings | ~60–100 tokens a hit; no body text; reports the count of hidden superseded and archive matches |
| `memory_show(slug, part="meta"\|"summary"\|"section"\|"full", section?)` | the requested slice; `summary` is the description plus the opening paragraph | defaults to `summary`; `full` is always allowed |
| `memory_history(slug)` | version chain (both directions) plus dated commits that touched the file | |
| `memory_confirm(slug, note?)` | appends a `confirm` event | the only tool with a side effect, and it only appends |

**Why MCP for these, and the CLI for everything else.** Hooks have to run a command, so the
CLI exists regardless. The model-facing read surface gets MCP because typed tools need no
per-command Bash approvals, reach subagents and other clients that lack Bash, and make
`confirm` an explicit, unmistakable act. With deferred schema loading the context cost is
negligible.

**Why no `memory_save`.** Both close relatives make the tool the save path; this design does
not, deliberately. Markdown via `Write` keeps writes free, keeps every change a reviewable
file diff in git, and means the hook path sees every write regardless of who wrote it.

**What would grow it.** A fifth tool is added only when events show Claude reaching for
something repeatedly by a clumsier route. agentmemory's 54 tools are the cautionary
example.

## 9. Hooks

| Event | Matcher | Does | Budget | On failure |
|---|---|---|---|---|
| `SessionStart` | `startup\|resume\|clear\|compact` (already set) | inject the layer; ingest events; warm the cache | 100 ms | inject what it can; never block |
| `PostToolUse` | `Read\|Write\|Edit` | exits immediately unless the path is under the store; else append event, reindex on write, near-duplicate hint on write | 50 ms p95 | silent; exit 0 |

**The hot path is process start, not throughput.** `PostToolUse` fires on every `Read`,
`Write` and `Edit` in every session, store or not, because matchers select tools, not paths.
So the hook entrypoint stays stdlib-only, with a test that asserts its import time, and exits
before importing anything when the path is outside the store.

**No read gate.** claude-mem denies whole-file reads of large files and hands back an
outline. Considered and dropped, 2026-10-21. A 39 KB memory is not a read-time problem to
intercept; it is a sign the file should have been split into separate memories, and that is
a maintenance question with a *why* behind it. So reads always go ahead untouched, and
oversized files surface as split candidates in `mem audit` and the retro. That also keeps a
second hook off the hot path.

**Known blind spot.** A memory read through `Bash` (`cat`, `rg`) is not logged. Reads through
`Read` and MCP are the overwhelming majority; a cheap parse of Bash commands for store paths
can be added if events show a gap.

## 10. Language

The workload, measured where possible:

| Path | Frequency | Cost driver | Measured today |
|---|---|---|---|
| `PostToolUse` hook | every tool call, every session | process start + imports | `uv run python -c pass` 15 ms; current SessionStart hook end to end 22 ms |
| SessionStart | once per session | file reads | 22 ms |
| Cache rebuild | rare (incremental otherwise) | parsing | **47 ms** for 296 files / 699 sections (FTS5 prototype on the real store) |
| Query | per lookup | FTS5 | **0.2–0.6 ms** |
| MCP server | once per session, long-lived | SDK import | `mcp` 2.3.0 imports in ~200 ms, once |
| `mem audit` | retro | everything | 113 ms |

The current hook runs on `/usr/bin/python3`, which starts in 48 ms; moving it under `uv`
makes it faster, and brings it in line with the uv directive.

| | Python | TypeScript (Node/Bun) | Go | Rust |
|---|---|---|---|---|
| Hook cold start | 15–22 ms measured | ~20 ms measured (Node) | low single-digit ms, expected | low single-digit ms, expected |
| MCP SDK | official, v2.3 (note the v2 `FastMCP`→`MCPServer` rename: churn exists) | official, the reference implementation | official `go-sdk` | official `rmcp` |
| SQLite + FTS5 | **stdlib**, FTS5 verified (3.50.4) | native module (`better-sqlite3`) or `bun:sqlite` | cgo driver or pure-Go port; FTS5 via build tag | `rusqlite` bundled with `fts5` |
| Author's fluency | strongest | writes it for browser extensions | one small tool | none noted |
| Edit → live | immediate with `uv tool install -e` | immediate | rebuild per change | rebuild per change |
| Two-machine install | `uv` already on both | Node toolchain + lockfile churn | one binary per machine | one binary per machine |
| Who chose it | this repo (1,268 lines) | claude-mem, agentmemory | — | — |

**Recommendation: Python.** Speed is not a reason to leave it. Its one real cost is
per-invocation startup, which is 15–22 ms against a 50 ms budget, and the throughput work
(index, query) is two orders of magnitude inside any limit this store will reach. Python is
also the fastest of the four for Matt to maintain alone, which `simplest-adequate-solution`
says is the cost that actually matters.

**The limitation, and the escape hatch.** Startup grows with every import, and a slow hook
taxes every tool call in every session. So the hook entrypoint is stdlib-only and
import-time-tested. If it still ever exceeds budget, only `mem hook` is rewritten in Go, a
few hundred lines, against the same contract: append JSONL, upsert the cache. Because the
event log and the cache schema are the interface, the language decision is per component and
reversible. TypeScript is the runner-up and the right answer if this ever becomes a Claude
Code plugin distributed to other people, which is a non-goal today.

## 11. Database

The cache has to serve three processes at once (hooks from several concurrent sessions, the
MCP server, the CLI), support BM25 over sections, walk version chains and the link graph, and
rank by reinforcement.

| Option | For | Against | Verdict |
|---|---|---|---|
| **SQLite + FTS5** | stdlib; one file; BM25 built in; WAL gives concurrent readers + one writer with a busy timeout; recursive CTEs for chains and links; JSON1; `sqlite-vec` exists if vectors ever earn a place | single writer (fine at this write rate); FTS5 tokenizer is basic (porter + unicode61 is enough here) | **chosen** |
| Plain files + in-memory index | simplest; no schema | every hook and CLI call rebuilds or loads its own index; no shared view across processes | the right *source* for events, the wrong cache |
| DuckDB | excellent for analytics over events | **one read-write process per file**: concurrent sessions' hooks would contend for the lock; FTS index is rebuilt, not incremental | no; it can attach the SQLite file read-only if retro analytics ever want it |
| Chroma / LanceDB / Qdrant | vector-first, hybrid search | embeddings are the thing the evidence says not to need; Chroma is the heaviest part of claude-mem's stack | no |
| Postgres (+ tsvector / pgvector) | best-in-class everything | a server to run for one user on one laptop | no |
| Tantivy / Meilisearch / Typesense | better ranking than FTS5 | a library or service for 700 sections | no |
| KV (LMDB, Redis, agentmemory's file KV) | fast | no query language; chains and ranking become application code | no |

**Events are JSONL, not SQLite rows.** Hooks append one line per event to
`events/YYYY-MM.jsonl`: atomic `O_APPEND` writes, no locks, no schema migration, readable with
`rg`, and committed with the store so usage history survives a deleted cache. The cache
ingests new lines lazily. Monthly files keep each one small; at a few hundred events a day
the log is on the order of 10 MB a year.

**What this buys.** Every byte in SQLite is derived, so the schema can change freely
(`mem index --rebuild`, 47 ms today), the database can be swapped without migration, and a
corrupt cache is a non-event.

## 12. Repo layout

    claude-hybrid-memory/
      pyproject.toml            # uv project; console script `mem`
      src/claude_hybrid_memory/
        cli.py                  # argument parsing only
        hooks/                  # stdlib-only: session_start, post_tool, pre_read
        store/                  # markdown + frontmatter parsing, paths, territories
        events.py               # JSONL append + ingest
        cache/                  # SQLite schema, incremental indexer, FTS queries
        render.py               # rendered MEMORY.md sections + budget
        audit/                  # today's mem.py checks, split by concern
        rank.py                 # reinforcement scoring
        mcp_server.py           # the only module that imports `mcp`
      tests/
        fixtures/               # synthetic stores built to REAL shapes, no real content
        test_*.py
        live/                   # opt-in: read-only against ~/.claude/memory (`-m live`)
      docs/  skills/  templates/
      tools/                    # the parity REFERENCE: untouched until the hook switches, then removed

Dependencies, each justified:

- **`mcp`** — the server.
- **`pyyaml`** — frontmatter is YAML and it already nests (`metadata:`). Correction,
  2026-10-21: an earlier draft blamed the hand parser for a key named `exit 1 as of
  2026-09-15 — …`; that came from a throwaway survey script, not `mem.py`. The real shape is
  a frontmatter line with **no key at all** (`tag-test-fodder-corpus.md`), which the hand
  parser skips silently and strict YAML would reject, block and all. So the swap is its own
  deliberate step after the port, with that file as a test case. Imported lazily, never on
  the hook path.
- **`pytest`** (dev).
- Nothing else. No embedding model, no search library, no ORM.

## 13. Testing

Two constraints pull against each other: the standing directive says validate against real
data, and this repo crosses machines while memory content may not.

- **Fixture stores are synthetic in content and real in shape.** Each fixture is modelled on
  a specific real case (the 195-line index, the 39 KB file, the nested `metadata:` block, the
  stray YAML key, an `EXPORTS.md` beside `MEMORY.md`), and names the case it reproduces.
- **Live tests** run read-only against the local store when asked (`uv run pytest -m live`):
  parity of `mem audit` with today's `mem.py audit --json`, render budget on every territory,
  index counts against file counts.
- **Parity first.** The port of `mem.py` and `session_start.py` must produce byte-identical
  hook output and equivalent audit JSON on the real store before anything new is added.
- **Hook budgets are tests**: import time of the hook entrypoint, and wall time on a fixture.

## 14. Growth: where each piece breaks

Rebuild times extrapolate the measured 47 ms linearly; typical runs are incremental.

| | Today | 10× (3,000 files) | 100× (30,000 files) | First real limit |
|---|---|---|---|---|
| Full cache rebuild | 47 ms | ~0.5 s | ~5 s | none practical; incremental makes it rare |
| FTS query | <1 ms | low ms | low tens of ms | none at this scale |
| Events | 0 | ~100k/yr | — | file size; monthly rotation |
| Territory `MEMORY.md` | hand, 195/200 lines | rendered to budget | rendered to budget | **harness cap is fixed**; rendering is the only answer, and collapsing must stay legible |
| `ROUTER.md` | ~250 chars per territory | 90 territories exceed the always-loaded budget | — | **the next wall**: it is hand-written and grows by design. Rendering it the same way is the expected follow-up, not in this plan |
| Hook latency | 15–22 ms | unchanged (per-file work) | unchanged | import discipline, not data size |
| Concurrent sessions | — | — | — | SQLite single writer; fine for event-rate writes; events bypass it anyway |

Additions this leaves room for without redesign: embeddings via `sqlite-vec` in the cache if
search misses ever show up in events; LLM-written summaries stored in the cache keyed by
content hash (an index aid, never a replacement body); a read-only viewer over the cache;
the same tool on the work Mac's chain topology.

## 15. Migration

### Inventory, personal Mac, 2026-10-21

| Where | State | Count |
|---|---|---|
| `~/.claude/memory/territories/` | migrated | 9 territories, 296 internals |
| `~/.claude/memory/standing/` | always loaded | 13 directives |
| `~/.claude/memory/archive/` | retired | 21 files, 8 groups |
| `~/.claude/projects/*/memory` → symlink | migrated silos | 27 |
| `~/.claude/projects/*/memory`, real dir | legacy, not reviewed | **15 silos, 91 files** |
| `~/.claude/projects/*/memory`, empty | nothing to move | 9 |

The symlink mechanism does not change: a repo's memory directory still points at its
territory and the harness still auto-loads that territory's `MEMORY.md`. Nothing about how
the harness finds memory moves.

### Phases

Each phase has an exit criterion and a rollback. No phase starts until the previous one has
exited.

**Phase 0 — Foundations.**
`git init` the store and take a baseline commit (Matt; see §16.1). Restructure the repo
(§12); port `mem.py` and `session_start.py` into the package with parity tests. Switch the
SessionStart hook from `/usr/bin/python3 tools/session_start.py` to `mem hook session-start`.
Investigate one unknown: the 2.1.306 binary contains a walker over memory directories
(`excludeBasenames:["MEMORY.md"], maxFiles:2000, maxFileBytes:1048576`, content-hashed), which
looks like a sync or indexing manifest of memory topic files. Find out what it is before
building an index beside it.
*Exit:* hook output byte-identical to today's on the real store. *Rollback:* revert the
settings line.

*Progress, 2026-10-21:*
- [x] store `git init` + baseline (Matt); documented as `setup.md` step 1b.
- [x] `src/claude_hybrid_memory/` + `tests/`; `mem.py` and `session_start.py` ported with no
  behavior change. Parity is byte-identical (stdout, stderr, exit code) against `tools/`
  on fixture stores (15 command forms, `fix --write` tree comparison, three hook cwds,
  degraded and no-store hooks) and on the real store (`uv run pytest -m live`: 10 commands,
  4 cwds).
- [x] switch the SessionStart hook, then delete `tools/`. Hook runs
  `~/.local/bin/mem hook session-start` from `uv tool install -e .` (~17 ms vs 23 ms for the old
  `/usr/bin/python3` path; options and numbers in `setup.md` step 3). Before deleting, the
  installed binary's output was byte-identical to `tools/session_start.py` in five cwds and
  `-m live` parity passed. The parity tests went with `tools/`; `-m live` now smoke-tests the
  installed `mem` on the real store, which catches an install left stale by a dependency
  change.
- [x] `pyyaml` swap. Frontmatter is read as YAML, with dates kept as text and a fallback
  so nothing is lost without a finding. Strict YAML alone, measured on the 409 real
  blocks, would have rejected 5 (an unquoted `: ` in a value, or the keyless line) and
  silently cut 4 descriptions at an unquoted ` #`. Those blocks now use the forgiving
  parser or keep the full value, and each raises a `frontmatter-not-yaml` warning. On the
  real store the audit gained exactly those 9 warnings and changed nothing else. The live
  suite failed on the stale install (`No module named 'yaml'`, CLI only, hook unaffected)
  until `uv tool install -e . --reinstall`, which is the guard working as designed.
- [x] store `.gitignore` covers `.bm25-index.json` (verified with `git check-ignore` at
  territory depth).
- [x] the binary's memory-directory walker. It is the **BM25 index behind Claude Code's
  relevant-memories recall** (`memory_recall_select`, `via_index`). Before a turn whose
  prompt has more than one word, recall picks up to 5 memory files and injects their full
  bodies as a `relevant_memories` attachment, under a 61,440-byte session budget. It picks
  them either with a side-model selector (`selectRelevantMemories`) or, when
  `tengu_mill_orange` is on, with this index. The walker covers `*.md` under the project's
  memory directory (so, through the symlink, one territory), skips `MEMORY.md` (already
  auto-loaded) and symlinks below the root, and keeps the 2,000 newest files of at most
  1 MiB each. It hashes each file with FNV-1a 64 to skip re-indexing unchanged ones.
  Fields are weighted filename 3, frontmatter 3, headings 2.5, body 1 (k1 1.2, b 0.75). It
  persists as **`.bm25-index.json` (mode 0600) inside the memory directory**, which here is
  inside the store. **Dormant on this machine:** `tengu_moth_copse` and `tengu_mill_orange`
  are both false in the cached flags, `CLAUDE_MEMORY_STORES` (JSON config for an internal
  sync service) is unset, no `.bm25-index.json` exists, and no transcript holds a
  `relevant_memories` attachment. Consequences for this plan:
  (1) it searches only the current directory's territory, so cross-territory `mem find`
  is not duplicated; (2) our cache must stay out of territory directories; (3) the store
  should gitignore `.bm25-index.json` before the flag ever flips, or `mem` will commit it;
  (4) frontmatter outweighs the body 3:1, which backs §16.4: descriptions are what get
  recalled; (5) once on, recall injects whole files, so the split candidates in §9 become a
  context-cost issue as well as a maintenance one.
- [x] **found during the port, fixed as its own change after the switch:** both tools encoded
  a directory path into a silo name differently, and **both disagree with the harness.**
  Claude Code 2.1.306 uses `replace(/[^a-zA-Z0-9]/g, "-")`, truncating past 200 chars with a
  hash suffix. `mem link` keeps `_`, so linking `console_tools` would create a silo nothing
  reads; the hook converts only `/ . _`, so paths with `~`, `@` or spaces never map to their
  territory. `Old_Vault` is a silo from an older harness that kept underscores.
  Fixed: one encoder, `claude_hybrid_memory/harness.py`, implements the harness's `D0` (truncation,
  hash and UTF-16 unit counting included). It is tested against vectors produced by running
  the binary's own code under node. The hook, `mem link` and the reverse walk all use it, and
  the two strict-xfails are gone. On the real projects dir, 31 silos round-trip exactly and
  21 are not on disk (parked). The only name 2.1.306 would not read is the empty
  `Old_Vault` silo.

**Phase 1 — Cache, read-only.**
`mem index`, `mem find`, `mem show`. No markdown changes, no hooks.
*Exit:* cache counts match the audit; a dozen real lookups spot-checked against `rg`.
*Rollback:* delete `.cache/`.

*Progress, 2026-10-21:* **exited.**
- [x] `claude_hybrid_memory/cache.py`: SQLite + FTS5 at `<store>/.cache/index.sqlite` (WAL, busy
  timeout, schema version, so a schema change means a rebuild). It indexes what `scan_store`
  reads plus `archive/`, split into sections by ATX heading (headings inside code fences
  skipped). BM25 weights follow Claude Code's recall index: slug 3, description 3,
  heading 2.5, body 1. Other frontmatter (`verify:`, `expect:`) is not indexed.
- [x] Real store: 331 files (297 territory, 13 standing, 21 archive) and 738 sections. Cold
  rebuild 62 ms; warm refresh 5 ms. `find` and `show` refresh first, then answer in about
  35 ms end to end. Rebuild was 500 ms at first: pure-Python YAML parsed twice per file.
  The libyaml loader (identical on all 410 real blocks) and a single parse brought it to
  124 ms; starting a rebuild from a fresh file instead of deleting FTS rows brought it to 62.
- [x] Counts match the audit: territory + standing = `scan_store`'s 310. Pinned by a live
  test that indexes a copy of the store, so the real one is never written.
- [x] 14 real lookups against `rg`: zero real misses. The only `rg`-only files (`WAL`,
  `Plex`) were `rg -F` substring hits ("walk", "complex"); with `-w` the sets are equal.
  The extras are stemming and tokenizing wins: "kernel panic" finds "kernel-panics",
  "Old Vault" finds `Old_Vault`.
- Behavior: all terms must match; if nothing does, it falls back to any term and says
  so. Archive matches are hidden with a count (§16.5). `show` refuses an ambiguous slug
  and lists `territory/slug` candidates. Superseded filtering waits for Phase 3.

**Phase 2 — Events and hooks.**
`PostToolUse` read/write events; near-duplicate hint, with its threshold calibrated by
querying every existing memory against the rest and choosing a cut from that real
distribution; secret scan and split candidates in `mem audit`.
*Exit:* two weeks of events; hook p95 under 50 ms measured from the event timestamps.
*Rollback:* remove the hook entries. Events stay as data.

*Progress, 2026-10-21:* **built and installed; exit due 2026-11-05** (two weeks of events,
restarted 2026-10-22 when coverage was fixed; see the last item).
- [x] `mem hook post-tool` (`hooks/post_tool.py`), matcher `Read|Write|Edit`, in
  `~/.claude/settings.json` and `setup.md` step 3b. It rejects before parsing stdin
  unless the store or projects path appears in it, resolves silo symlinks, and logs only
  `*.md` under the store, outside `events/`, `.cache/` and `.git/`. Measured as the harness
  calls it: p95 15 ms outside the store (interpreter start alone is 10), 16 ms for a memory
  read, 34 ms for a memory edit with reindex. Import budget is a test: outside the store it
  loads only the hook module; a read never loads sqlite3 or yaml. The first real event
  landed in this session.
- [x] Events (`events.py`): one `O_APPEND` write per JSONL line; `ms` is in-process time.
  Interpreter start is invisible from inside, hence measured above. `mem events stats`
  gives counts, p50/p95 and the most-read files. Committed with the store by the
  SessionEnd hook (§16.1, built 2026-10-22).
- [x] Near-duplicate hint, calibrated by querying all 310 live memories against the rest:
  similarity is a neighbour's BM25 over the file's self-score. Median 0.41, p95 0.63, max
  0.90. 0.70+ were real overlaps, 0.55-0.65 distinct memories on one topic, so the **cut is
  0.70 (9 of 310 clear it)**. **Deviation:** the hint fires only when the written file is
  NEW to the cache. Editing either side of an existing overlapping pair would otherwise
  repeat the same note on every edit, and a duplicate is created at creation.
- [x] Secret scan (`audit/secrets.py`) over every committed `*.md` plus legacy silos:
  specific key formats are errors, token-like `name = value` assignments are warnings, and
  a finding never prints the value. Real store: 0 findings. The looser first draft hit only
  code (`secret = xx_xxx[:0x10]`), which the value alphabet now excludes.
- [x] Split candidates (`audit/split.py`): over 10 KB (the p95 of 297 files), ranked by
  size x (1 + accretion markers) x (1 + reads). 14 today, led by `ca-to-compose-migration`
  (38.8 KB). The marker regex reproduces §2's 24 files exactly (phrases in any case;
  CORRECTION / SUPERSEDED only shouted). Accretion count is an `info` finding.
- [x] **Coverage fix, 2026-10-22.** A day in, the log held 3 events: the hook saw only
  Read|Write|Edit, and nearly all memory traffic goes through Bash (`cat`, `sed -n`, `rg`,
  python edits) or `mem`. A day of heavy store work, about 90 files changed, logged nothing.
  Three changes:
  - `Bash` joined the matcher. Each store path a command names is an event: `write` if the
    command looks like it writes (`sed -i`, a redirect, `write_text`, `mv`, `rm`, ...),
    else `read`; a store directory under `rg`/`grep`/`find`/`ls` with no file named is a
    `search`. Relative `*.md` resolve against a `cd` target in the command or a cwd in the
    store; globs are skipped; at most 40 events per call. A heuristic, on purpose.
  - `mem show` logs a `read`, `mem find` a `search` with its query and hits, and the hook
    skips Bash commands that run `mem`, so nothing counts twice.
  - Writes are counted exactly from the store's git: `mem events stats` reports file changes
    in commits since the first event, however they were made.
  The rejection test was also fixed. Every payload carries `transcript_path` under
  projects/, so "projects path appears" matched every call; a silo now has to appear as
  `projects/<p>/memory`. A Bash call outside the store costs 16 ms wall.
- [ ] Exit, 2026-11-05: `mem events stats`, hook p95 under 50 ms, events by tool showing
  Bash and `mem` traffic, not only Read.

**Phase 3 — Version chains and records.**
`supersedes:` semantics live in the cache; superseded memories drop out of default search.
The 24 accreted files are split into state plus records **when next touched**, not in a
bulk pass; git keeps the originals. `mem audit` reports the accretion count so the trend is
visible.
*Exit:* chains resolve; `memory_history` (CLI form) shows both directions.
*Rollback:* the field is inert without the cache.

*Progress, 2026-10-21:* **built; started before Phase 2's exit, by Matt's call.** Phase 3
reads no event data, so waiting on two weeks of events bought it nothing; the rule above
still holds for Phase 5, which does depend on them.
- [x] `claude_hybrid_memory/chains.py`: one pure graph shared by the cache, the audit and the CLI.
  A ref is a slug, `container/slug` or a path, scalar or list; a bare slug in two
  containers resolves to the one beside the newer memory. A memory is superseded when any
  memory outside `archive/` names it.
- [x] Cache schema 2: a derived `chain` table, re-derived whole on any change (a new file
  can resolve or make ambiguous a ref anywhere), plus a `tier` column. `mem find` hides
  superseded memories and counts them (`--superseded` shows them, with their successor);
  `mem show` names the successor first; the near-duplicate hint never offers a memory
  that is already superseded.
- [x] `mem history <slug>`: the chain both ways, unresolved refs shown as dead ends, and
  `git log --follow` of the file. `mem supersede <old> <new>` writes `supersedes:` into the
  newer file only, refuses loops and archive successors, logs its own `write` event (Bash
  writes are invisible to the hook; `CLAUDE_CODE_SESSION_ID` carries the provenance), and
  names the index line to drop.
- [x] **Deviation from the old spec:** `supersede-target-live` (superseded file must be
  archived or marked HISTORICAL) is gone. It contradicted §6's byte-identical rule. In its
  place: `supersede-self` and `supersede-cycle` (errors), `supersede-ambiguous` (warn),
  `supersede-target-gone` (info), and `superseded-still-indexed` (warn) for the hand-written
  index that still routes to the old file until Phase 4 renders it.
- [x] Records: `tier: state | record` in the spec vocabulary. "When next touched" has a
  mechanism: on an edit to an existing file with accretion markers, the PostToolUse hook
  suggests the state + records split, once per session per file. Hook cost of all of
  Phase 3, profiled: 0.7 ms chain derivation + 0.1 ms accretion check per write.
- Real store: one chain. `cards/cairn/cairn-phases-p0-p2` supersedes `cairn-p1-targets`,
  merged away 2026-10-02, before the store had history, so it is an honest dead end
  (`supersede-target-gone`). **Exit is not yet met on real data:** no chain on this
  store resolves end to end until a session supersedes something. The 9 near-duplicate
  pairs at 0.70+ (Phase 2) are the obvious first candidates; deciding them is judgment.

**Phase 4 — Rendered indexes.**
`mem render --adopt` per territory, starting with `console/tools`. Adoption derives `group:`
from the current headings and **reports every place the hand-written index line differs from
the file's `description`**, because the index lines carry judgment ("the CONSOLE deleted
19.83 GiB") that a flat render would lose. Reconciling those, so descriptions become where
that judgment lives, is the real cost of this phase: up to 296 small edits, done territory by
territory.
*Exit:* `console/tools` renders with its MEMORIES section within 100 lines and the file
within the harness's 200 lines / 25,000 bytes, every slug reachable through the render or
`mem find`; `mem render --check` clean.
*Rollback:* `git revert` on that `MEMORY.md`.

*Progress, 2026-10-22:* **built; `console/tools` adopted; exit met.** Started before Phase 2's exit, by Matt's call: nothing built here reads events.
- [x] `claude_hybrid_memory/render.py`. The section between `<!-- mem:render begin/end -->` is a
  function of the markdown only: each memory's `description:` is its line, `group:` places
  it, and the territory's `groups:` frontmatter (one flow-list line, since every line counts
  against the 200) orders the headings. Within a group, memories sort by slug; the
  hand-written order is not kept, and nothing persists it.
- [x] Superseded memories drop out. `tier: record` and `status: HISTORICAL` memories share
  one `Records and history:` line per group, so they stay reachable at one line per group
  instead of one each. "Unless hot" waits for reads: ranking by events would make the
  render change whenever reads do, and every such change is a commit.
- [x] `mem render [T]` re-renders adopted territories; `--check` (and `mem audit`) warns
  `render-stale` when the section differs from the memories. On every territory, rendered
  or not, it warns `memories-over-target` past 100 lines of `## MEMORIES` and errors
  `memories-over-cap` past 150. The hand-written head is not budgeted (Matt, 2026-10-22). It
  errors `index-over-cap` past 200 lines / 25,000 bytes for the whole file, since that is
  the harness truncating. Today only `console/tools` warns, at 107 memory lines.
- [x] The SessionEnd hook re-renders adopted territories before it commits, so a
  description edited in a session reaches its index line with no one running anything.
- [x] Superseded memories are exempt from `router-unlisted` and `orphan`: dropping their
  index line is what `superseded-still-indexed` asks for, so warning about the result was a
  contradiction.
- [x] `mem render <T> --adopt` dry run: groups from the `###` headings, every index line
  whose words the description lacks (plus its slug), prose and ghost links the render
  would drop, unlisted memories, and the projected line count. `--write` applies it:
  `group:` into each memory, `groups:` into MEMORY.md, the section replaced.
- `console/tools` dry run: 88 memories in 9 groups, 189 lines rendered, MEMORIES at 100.
  Matt approved the layout and slug order on 2026-10-22. **Index lines that say more than
  the description are not a problem**: the description carries the meaning, and the detail
  is one read away. The dry run still lists them, for information only.
- The first `--adopt --write` produced 26,768 bytes against the harness's 25,000, because
  descriptions run longer than the glosses they replace (15.9 KB in total, median 178
  bytes). It was rolled back with `mem restore`'s predecessor, raw git.
- [x] Index lines cut at 160 bytes of description, at a word boundary, with "…" (Matt: an
  index directs to its memory, it does not stand in for it). 180 left 33 bytes of slack;
  160 leaves about 1 KB. `index-near-cap` now warns past 24,000 bytes.
- [x] `console/tools` adopted 2026-10-22: 189 lines, 23,940 bytes, MEMORIES at 100 lines,
  52 lines cut; all 88 memories linked, no ghosts; re-render unchanged; `--check` clean.
- [ ] Follow-up, its own plan: a memory optimization pass over each territory's MEMORY.md,
  moving what does not belong in the index (long gates, contracts) into memories of its own.

**Phase 5 — MCP.**
The four tools. Measure their use against `Read` and `rg` in events.
*Exit:* used in real sessions without prompting.
*Rollback:* remove the server entry.

**Phase 6 — The remaining legacy silos.**
*Revised 2026-10-23:* runs on `fast-adoption.md` (inventory, Sonnet summaries, one map
checkpoint, land as-is, refine after) instead of `/memory-migrate` one territory at a time.
The text below is the original plan; its exit criterion stands.
The 15 silos and 91 files go through `/memory-migrate` as today, now backed by `mem migrate`,
whose duplicate check runs each incoming file against the store, which is exactly where the
old silos duplicate each other. The 9 empty silo directories go to Matt as an annotated list,
per the deletion directive. `archive/` becomes searchable on request (`include_archive`) and
is never rendered: retired, not lost.
*Exit:* `mem status` shows no unreviewed silos.

**Phase 7 — The work Mac.**
*Revised 2026-10-23:* also on `fast-adoption.md`.
Same sequence against its own store and its chain topology (`EXPORTS.md`, layered
territories). Separate store, separate git history, nothing shared but this repo.

## 16. Decisions

Settled 2026-10-21 unless marked open.

1. **The store gets an explicit git exception.** Matt's global rule (Claude touches git only
   when asked) stays in force for every repo. The one carve-out: `mem` commits
   `~/.claude/memory/` itself, automatically, with generated messages, and never pushes,
   because the store has no remote. **Why:** history only helps if it exists without anyone
   remembering to make it, and [[who-matt-is]] says never to build on a process he has to
   remember. The exception must be written into `~/.claude/CLAUDE.md` beside the rule it
   narrows, so no session reads the rule without its exception.
   *Built 2026-10-22:* `claude_hybrid_memory/storegit.py` is the only code that runs git, always
   `-C` the store and only when the store has its own `.git`. The SessionEnd hook commits
   memory and events together with a generated message; `mem commit | log | diff` are the
   only git surface, so no session needs `git` on the store and the carve-out stays
   narrow. Nothing pushes, rewrites or resets. First commit: `736feff`, the backlog since
   the baseline.
   *Extended 2026-10-22:* `mem restore`, `mem show --at` and `mem audit --at`, after a
   session reached for `git stash` to compare audits and roll back a render. The rule
   became: store git goes through `mem`, and a missing verb gets added, not worked around
   (Matt). Stash itself was left out on purpose. It takes the whole tree, can conflict
   with a SessionEnd commit landing mid-stash, and hides changes if a session dies holding
   it. `restore` commits first and names its paths; `--at` reads a past tree without
   touching the working one.
2. **No read gate.** Reads go ahead as normal. A large file is a maintenance signal — why is
   it that big, and should it have been split? — surfaced as split candidates in `mem audit`
   and the retro (§9).
3. **Events are committed** with the store.
4. **Description reconciliation is a one-off migration step, after which it disappears.**
   Today every memory carries two hand-written summaries: its `description` and its line in
   the territory index, and they drift. Adoption merges them once, per territory, with Matt
   reviewing the diff. Afterwards the description is the only summary, the index line is
   rendered from it, and keeping them in sync is no longer a task. Writing a good
   description becomes the whole job at write time, which it nominally already is.
   `mem render --check` in the audit catches a hand edit inside the rendered section.
5. **`archive/` is excluded by default, with a cheap overview.**
   - `memory_find` and `mem find` skip it unless `include_archive=true`, but **report how many
     archive matches they hid** ("3 matches in archive/ not shown"), so a session knows there
     is something to ask about without paying to read it.
   - `mem archive` (and `memory_find(scope="archive-overview")`) lists each retired group in
     one line: name, file count, date retired, the description of its largest memory. It is
     never auto-loaded, and runs on an explicit ask or when a session needs it.
6. **The store's gate is rewritten.** `territories/meta/claude-memory/MEMORY.md` now states
   the narrowed rule (content never crosses machines; local history allowed), applied on
   Matt's explicit go-ahead after auto mode refused it unprompted. The git exception is in
   `~/.claude/CLAUDE.md`.
7. **Open (TBD): what eventually happens to superseded files.** Phase 3 leaves them in
   place, byte-identical, hidden from search by derivation; the old rule that they be
   archived or marked HISTORICAL was dropped (2026-10-21, Matt agreed). Whether they should
   later move to `archive/`, get pruned once git holds them, or stay put forever is a future
   optimization. Revisit once real chains exist and the count of superseded files is
   known; nothing depends on it before then.

## 17. Risks, and when to stop

- **The fix-the-fix loop.** Every phase is shippable alone, and Phase 5 is conditional on
  Phase 2's data. If events show memory reads are rare, the MCP server is not built.
- **Tool sprawl.** Four MCP tools; a fifth needs evidence from events.
- **A slow hook taxes everything.** Budgets are tests, and every hook fails open.
- **Rendering flattens judgment.** Mitigated by the adoption diff in Phase 4. If rendered
  indexes read worse than the hand-written ones after `console/tools`, stop there and keep
  rendering as a budget check only.
- **The cache becoming a source by accident.** Any feature that would store something only in
  SQLite is a design error; it goes in markdown or the event log.
