"""Usage events: append-only JSONL in <store>/events/YYYY-MM.jsonl, committed with the store.

The source of truth for usage, as markdown is for knowledge (direction §11). One line per event,
written with a single O_APPEND write so concurrent sessions never interleave a line and no
lock is needed. Imported by the PostToolUse hook, so stdlib only.

    {"ts": "2026-10-21T17:03:04.123Z", "event": "read", "path": "territories/x/y.md",
     "tool": "Read", "session": "...", "cwd": "...", "ms": 1.8}

`ms` is the hook's own time from entering `mem` to this append. Interpreter start comes
before it and is invisible from inside: ~10 ms, measured separately (setup.md step 3).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter
from pathlib import Path


def append(root: Path, event: dict) -> None:
    now = dt.datetime.now(dt.UTC)
    rec = {"ts": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z", **event}
    line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    d = root / "events"
    d.mkdir(exist_ok=True)
    fd = os.open(d / f"{now:%Y-%m}.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_all(root: Path):
    """Every event, oldest first. A torn or hand-mangled line is skipped, not fatal."""
    d = root / "events"
    if not d.is_dir():
        return
    for f in sorted(d.glob("*.jsonl")):
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def read_counts(root: Path) -> Counter:
    """Reads per store-relative path."""
    return Counter(e.get("path") for e in read_all(root) if e.get("event") == "read")


def git_writes(root: Path, since: str | None) -> dict | None:
    """Writes counted exactly, from the store's own commits since `since` (an event ts):
    every memory change lands in a commit, however it was made. None without a repo."""
    from claude_hybrid_memory import storegit

    if not storegit.is_repo(root):
        return None
    out = storegit.changed_files(root, since)
    if out is None:
        return None
    commits = [c for c in out.split("\0") if c.strip()]
    paths = [p for c in commits for p in c.splitlines() if p.endswith(".md")]
    return {"commits": len(commits), "changes": len(paths), "files": len(set(paths))}


def stale_writes(root: Path, evs: list[dict]) -> list[dict]:
    """Memories a session wrote while they were past their window, with no `mem verified` on
    them from that same session. An exact join over the store's own events, never a
    transcript heuristic.

    Judged per (session, path) and as of that session's first touch of the file, from the
    file as the store's last commit before then held it (sessions commit at their end), plus
    any `verified` events that landed since that commit. Judging as of today would turn every
    old edit into a miss; judging "any later verified" would let a retrospective's own check
    hide the session that skipped it. A file the commit lacks is new, so never stale.
    Without store history, the current file stands in, which can read fresh after the fact."""
    import datetime as dt

    from claude_hybrid_memory import storegit
    from claude_hybrid_memory.audit.freshness import past_window
    from claude_hybrid_memory.store import parse_date, parse_frontmatter

    groups: dict[tuple, list[dict]] = {}
    for e in evs:
        p = str(e.get("path") or "")
        memory = p.endswith(".md") and p.rsplit("/", 1)[-1] not in ("MEMORY.md", "EXPORTS.md")
        if p.startswith("territories/") and memory and e.get("session"):
            groups.setdefault((e["session"], p), []).append(e)
    repo = storegit.is_repo(root)
    every = list(read_all(root))
    out = []
    for (session, path), g in groups.items():
        kinds = {e.get("event") for e in g}
        if "write" not in kinds or "verified" in kinds:
            continue
        t0 = str(g[0]["ts"])
        if repo:
            rev = storegit.rev_before(root, t0)
            raw = storegit.read_at(root, rev, path) if rev else None
        else:
            f = root / path
            raw = f.read_bytes() if f.is_file() else None
        if raw is None:
            continue
        meta = parse_frontmatter(raw.decode("utf-8", errors="replace"))[0]
        checked = [
            str(e["ts"])[:10]
            for e in every
            if e.get("event") == "verified" and e.get("path") == path and str(e["ts"]) < t0
        ]
        lv = max([str(meta.get("last_verified") or ""), *checked])
        if lv:
            meta = {**meta, "last_verified": lv}
        due = past_window(meta, parse_date(t0[:10]) or dt.date.today())
        if due is None:
            continue
        out.append(
            {
                "path": path,
                "session": session,
                "cwd": g[0].get("cwd"),
                "first": t0,
                "writes": sum(e.get("event") == "write" for e in g),
                "volatility": due.volatility,
                "age": due.age,
                "limit": due.limit,
                "verified_later": [
                    str(e["ts"])[:10]
                    for e in every
                    if e.get("event") == "verified" and e.get("path") == path and str(e["ts"]) > t0
                ],
            }
        )
    return sorted(out, key=lambda r: r["first"])
