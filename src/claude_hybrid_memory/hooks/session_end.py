"""SessionEnd hook (`mem hook session-end`): re-render, then commit the store (direction §16.1).

Adopted territory indexes are re-rendered first, so a description edited this session
reaches its index line. Then whatever the session wrote to the store, plus its usage
events and those renders, goes into one generated commit. It runs after the session is
over, so nothing it prints reaches anyone; a failure leaves the changes for the next
commit and is otherwise silent.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STORE = Path(os.environ.get("CLAUDE_MEMORY_STORE", Path.home() / ".claude" / "memory"))


def main() -> int:
    from claude_hybrid_memory import storegit

    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    reason = data.get("reason") or "unknown"
    store = Path(os.path.realpath(STORE))
    try:
        from claude_hybrid_memory import render
        render.render_all(store)
    except Exception:
        pass        # a broken render must not cost the session its commit
    storegit.commit(store, f"session end ({reason})", data.get("session_id", ""))
    return 0
