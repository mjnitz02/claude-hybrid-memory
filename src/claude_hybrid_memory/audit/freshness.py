"""Freshness: which memories are past their check-on-use window."""
from __future__ import annotations

import datetime as dt

from claude_hybrid_memory.findings import INFO, WARN, Finding
from claude_hybrid_memory.spec import STALE_AFTER
from claude_hybrid_memory.store import Memory


def age_phrase(age: int | None) -> str:
    return "never verified" if age is None else f"{age}d since last_verified"


def check_freshness(mems: list[Memory], today: dt.date,
                    superseded: frozenset = frozenset()) -> list[Finding]:
    """`superseded` is the absolute paths of superseded memories: never edited by design, so
    a staleness finding on one could never be cleared. A `tier: record` is dated history with
    no "last seen true" (format-spec), so it is never stale either."""
    out = []
    for m in mems:
        if m.path in superseded or str(m.meta.get("tier") or "") == "record":
            continue
        vol = m.volatility or "slow"
        limit = STALE_AFTER.get(vol, STALE_AFTER["slow"])
        age = m.age_days(today)
        if not (age is None or age > limit):
            continue
        if vol == "live":
            # Not a work item (nothing queues it): a count the retrospective reports. The
            # check happens when a session is about to act on the claim (verify-on-use).
            out.append(Finding(WARN, "stale-live", str(m.path),
                               f"live, {age_phrase(age)} (window {limit}d): check its claim "
                               "before acting on it, then `mem verified`"))
        else:
            out.append(Finding(INFO, "stale", str(m.path),
                               f"{vol}; {age_phrase(age)} (limit {limit}d)"))
    return out
