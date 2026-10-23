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
