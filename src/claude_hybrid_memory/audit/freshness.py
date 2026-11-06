"""Freshness: which memories are past their check-on-use window."""

from __future__ import annotations

import datetime as dt
from typing import NamedTuple

from claude_hybrid_memory.findings import INFO, WARN, Finding
from claude_hybrid_memory.spec import STALE_AFTER, STATUS_VOLATILITY
from claude_hybrid_memory.store import Memory, parse_date


def age_phrase(age: int | None) -> str:
    return "never verified" if age is None else f"{age}d since last_verified"


class Due(NamedTuple):
    """A memory past its window: its volatility, age in days (None if never verified) and
    the window it is past."""

    volatility: str
    age: int | None
    limit: int

    def marker(self) -> str:
        """The inline flag `mem find` and `mem show` print, e.g. `PAST WINDOW 54d > 30d slow`."""
        age = "never verified" if self.age is None else f"{self.age}d > {self.limit}d"
        return f"PAST WINDOW {age} {self.volatility}"


def past_window(meta: dict, today: dt.date) -> Due | None:
    """The one window rule, for any frontmatter dict: `volatility:` (else what `status:`
    implies, else slow) against `last_verified:`. A `tier: record` is dated history with no
    "last seen true" (format-spec), so it is never due."""
    if str(meta.get("tier") or "").strip() == "record":
        return None
    vol = (
        str(meta.get("volatility") or "").strip()
        or STATUS_VOLATILITY.get(str(meta.get("status") or "").strip().upper())
        or "slow"
    )
    limit = STALE_AFTER.get(vol, STALE_AFTER["slow"])
    lv = parse_date(meta.get("last_verified"))
    age = None if lv is None else (today - lv).days
    if age is not None and age <= limit:
        return None
    return Due(vol, age, limit)


def check_freshness(
    mems: list[Memory], today: dt.date, superseded: frozenset = frozenset()
) -> list[Finding]:
    """`superseded` is the absolute paths of superseded memories: never edited by design, so
    a staleness finding on one could never be cleared."""
    out = []
    for m in mems:
        if m.path in superseded:
            continue
        due = past_window(m.meta, today)
        if due is None:
            continue
        if due.volatility == "live":
            # Not a work item (nothing queues it): a count the retrospective reports. The
            # check happens when a session is about to act on the claim (verify-on-use).
            out.append(
                Finding(
                    WARN,
                    "stale-live",
                    str(m.path),
                    f"live, {age_phrase(due.age)} (window {due.limit}d): check its "
                    "claim before acting on it, then `mem verified`",
                )
            )
        else:
            out.append(
                Finding(
                    INFO,
                    "stale",
                    str(m.path),
                    f"{due.volatility}; {age_phrase(due.age)} (limit {due.limit}d)",
                )
            )
    return out
