"""PostToolUse hook (`mem hook post-tool`, matcher Read|Write|Edit|Bash): usage events.

This fires on every Read, Write, Edit and Bash call in every session, store or not, because
matchers select tools, not paths. So the hot path is the rejection: stdin is checked for the
store's own path strings before it is even parsed, and nothing heavier than `json` is
imported until the path is known to be a memory file (tests/test_import_discipline.py holds
that). Every payload carries a `transcript_path` under projects/, so projects/ alone is not
a match: a silo is reached through `projects/<p>/memory/`.

Bash matters because most memory traffic goes through it (`cat`, `sed -n`, `rg`, a python
edit), and from Read|Write|Edit alone the log saw 3 events in a day of heavy use. For a Bash
call, every store path the command names becomes an event: a file is a `write` when the
command looks like it writes (`sed -i`, a redirect, `write_text`, `mv`, ...), else a
`read`; a store directory searched with `rg`/`grep`/`find`/`ls` and no file named is a
`search`. A heuristic, by design: it counts what was touched, not exactly how. Writes are
also counted exactly from the store's git history (`mem events stats`). A command that runs
`mem` is skipped, since `mem` logs its own reads and writes.

For a memory file it appends a `read` or `write` event. A write also refreshes the cache
and may hand the session one advisory note: for a file NEW to the cache, the existing
memories it closely resembles; for an existing file carrying accretion markers, the first
time this session writes it, that it is due a split into state plus records (direction §15 Phase
3: split "when next touched", never in a bulk pass). It never changes the markdown and
never blocks.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

STORE = Path(os.environ.get("CLAUDE_MEMORY_STORE", Path.home() / ".claude" / "memory"))
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects"))
TOOLS = {"Read": "read", "Write": "write", "Edit": "write"}
SKIP = {"events", ".cache", ".git"}
MAX_BASH_EVENTS = 40     # a sweep over a whole territory is one call, not a flood


def _maybe_memory(raw: str) -> bool:
    return (str(STORE) in raw or ".claude/memory" in raw
            or (str(PROJECTS) in raw and "/memory" in raw))


def main(t0: float | None = None) -> int:
    t0 = time.perf_counter() if t0 is None else t0
    raw = sys.stdin.read()
    # Memory is reached either directly or through a silo symlink under projects/.
    if not _maybe_memory(raw):
        return 0
    import json

    data = json.loads(raw)
    if data.get("tool_name") == "Bash":
        return _bash(data, t0)
    event = TOOLS.get(data.get("tool_name", ""))
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not event or not path.endswith(".md"):
        return 0
    store = Path(os.path.realpath(STORE))
    real = Path(os.path.realpath(path))
    if store not in real.parents:
        return 0
    rel = real.relative_to(store)
    if rel.parts[0] in SKIP:
        return 0

    from claude_hybrid_memory import events

    hint = ""
    if event == "write":
        hint = _after_write(store, str(rel), data.get("session_id", ""))
    events.append(store, {"event": event, "path": str(rel), "tool": data["tool_name"],
                          "session": data.get("session_id", ""), "cwd": data.get("cwd", ""),
                          "ms": round((time.perf_counter() - t0) * 1000, 1)})
    if hint:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": hint}}))
    return 0


def _bash(data: dict, t0: float) -> int:
    from claude_hybrid_memory import events

    store = Path(os.path.realpath(STORE))
    cmd = (data.get("tool_input") or {}).get("command") or ""
    found = bash_events(cmd, data.get("cwd", ""), store)
    for event, rel in found[:MAX_BASH_EVENTS]:
        events.append(store, {"event": event, "path": rel, "tool": "Bash",
                              "session": data.get("session_id", ""), "cwd": data.get("cwd", ""),
                              "ms": round((time.perf_counter() - t0) * 1000, 1)})
    return 0


def bash_events(cmd: str, cwd: str, store: Path) -> list[tuple[str, str]]:
    """(event, store-relative path) for each store path `cmd` names, deduplicated."""
    import re

    if re.match(r"\s*(?:\S*/)?mem\s", cmd):
        return []
    home = str(Path.home())
    files, dirs = [], []
    rel_md = []
    for tok in re.findall(r"""[^\s'"`;|&()<>=,]+""", cmd):
        if any(c in tok for c in "*?["):
            continue
        t = re.sub(r"^(?:~|\$HOME|\$\{HOME\})(?=/)", home, tok)
        if not t.startswith("/"):
            if t.endswith(".md"):
                rel_md.append(t)
            continue
        real = Path(os.path.realpath(t))
        if real != store and store not in real.parents:
            continue
        if real.is_dir():
            dirs.append(real)
        elif real.suffix == ".md":
            files.append(real)
    bases = list(dirs)
    here = Path(os.path.realpath(cwd)) if cwd else None
    if here and (here == store or store in here.parents):
        bases.append(here)
    for r in rel_md:
        for b in bases:
            f = Path(os.path.realpath(b / r))
            if f.is_file() and store in f.parents:
                files.append(f)
                break
    quiet = re.sub(r"\d?>&?\s*/dev/null|\d?>&\d", "", cmd)
    writes = re.search(r"\bsed\s+(?:-\w+\s+)*-i|>|\bwrite_text\b|\bwrite_bytes\b|\btee\b|"
                       r"\bmv\b|\brm\b|\bcp\b|\btouch\b|open\([^)]*['\"][wa]", quiet)
    out: dict[str, str] = {}
    for f in files:
        rel = f.relative_to(store)
        if rel.parts and rel.parts[0] not in SKIP:
            out.setdefault(str(rel), "write" if writes else "read")
    if not out and re.search(r"\b(?:rg|grep|find|ls|bfs)\b", cmd):
        for d in dirs:
            rel = d.relative_to(store)
            if not rel.parts or rel.parts[0] not in SKIP:
                out.setdefault(str(rel), "search")
    return [(e, p) for p, e in out.items()]


def _after_write(store: Path, rel: str, session: str) -> str:
    """Refresh the cache; for a memory new to it, name its nearest existing neighbours."""
    from claude_hybrid_memory import cache

    conn = cache.connect(store)
    try:
        known = conn.execute("SELECT 1 FROM files WHERE path=?", (rel,)).fetchone()
        cache.refresh(conn, store)
        if known:
            return _accretion_hint(store, rel, session)
        near = cache.near_duplicates(conn, rel)
    finally:
        conn.close()
    if not near:
        return ""
    lines = [f"`{rel}` is new and closely resembles existing memory:"]
    for n in near:
        lines.append(f"- `{n.slug}` ({n.container}, similarity {n.ratio:.2f}): {n.description}")
    lines.append("If it replaces one of these, add `supersedes: <slug>` to its frontmatter; "
                 "if it overlaps, consider merging instead. Advisory only.")
    return "\n".join(lines)


def _accretion_hint(store: Path, rel: str, session: str) -> str:
    """Once per session per file: this memory is acting as a log, so split it now."""
    from claude_hybrid_memory.spec import ACCRETION_RE

    try:
        text = (store / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    markers = len(ACCRETION_RE.findall(text))
    if not markers or _written_this_session(store, rel, session):
        return ""
    return (f"`{rel}` carries {markers} accretion marker(s) (read bottom-up, history below, "
            "CORRECTION, SUPERSEDED): it is acting as a log. Since it is being edited anyway, "
            "consider splitting it: rewrite it as the current STATE only, and move the dated "
            "history into new `tier: record` memories that are written once and never edited. "
            "Git keeps the original. Advisory only; skip it if this edit is not the moment.")


def _written_this_session(store: Path, rel: str, session: str) -> bool:
    """Whether this month's log already has a write of `rel` from `session`. Reads one
    file, newest month only: a session spanning a month boundary hears the hint twice."""
    if not session:
        return False
    import datetime as dt
    import json

    f = store / "events" / f"{dt.datetime.now(dt.UTC):%Y-%m}.jsonl"
    try:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if rel in line and session in line:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if (e.get("event"), e.get("path"), e.get("session")) == ("write", rel, session):
                        return True
    except OSError:
        pass
    return False
