"""`last_verified:` - the date a memory's claims were last seen true.

Verify-on-use (docs/direction.md): nothing checks a memory in advance. A session about to act
on a claim past its volatility window checks that claim then. For that the date has to mean
"last seen true", which is what a memory's landing date is: it was written from what a
session had just seen.

`mem backfill-verified` stamps that date on every memory that has none. It is the landing
commit's date, except for files that first appear in the history's baseline commit: the store
had no history before that, so the baseline's date is when tracking began, not when the
memory landed, and stamping it would make those memories look fresher than they are. Those
need `--baseline-date TERRITORY=DATE`, read from RETRO.md's migration entries, and the command
refuses rather than guess one.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from claude_hybrid_memory import storegit
from claude_hybrid_memory.store import parse_frontmatter, scan_store

LV_RE = re.compile(r"^last_verified:[^\n]*$", re.M)


def stamp(text: str, date: dt.date) -> str | None:
    """`text` with `last_verified:` set to `date` at the top level of its frontmatter, or None
    when the result would not read back as exactly that date."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    block, line = text[4:end + 1], f"last_verified: {date.isoformat()}"
    block = LV_RE.sub(line, block, count=1) if LV_RE.search(block) else block + line + "\n"
    new = text[:4] + block + text[end + 1:]
    meta, _, problems = parse_frontmatter(new)
    if problems or str(meta.get("last_verified")) != date.isoformat():
        return None
    return new


@dataclass
class Stamp:
    rel: str
    territory: str
    date: dt.date
    source: str        # "landed <sha>" | "baseline"


@dataclass
class Plan:
    stamps: list[Stamp]
    baseline: dict[str, list[str]]    # territory -> baseline files with no date given
    no_history: list[str]             # never committed: run `mem commit` first
    bad_dates: list[str]              # --baseline-date problems


def plan(root: Path, baseline_dates: dict[str, dt.date]) -> Plan:
    from claude_hybrid_memory.audit import superseded_paths

    mems, _ = scan_store(root)
    sup = superseded_paths(root)
    base = storegit.root_commit(root)
    base_day = None
    stamps, waiting, no_hist, bad = [], defaultdict(list), [], []
    for m in mems:
        # A record is dated history, written once and never re-checked, so it has no
        # "last seen true". Most were split out of an older memory, which makes their landing
        # commit the date of the split, not of what they say.
        if (m.path in sup or m.last_verified is not None
                or str(m.meta.get("tier") or "") == "record"):
            continue
        rel = str(m.path.relative_to(root))
        got = storegit.first_added(root, rel)
        if got is None:
            no_hist.append(rel)
            continue
        sha, day = got
        if sha != base:
            stamps.append(Stamp(rel, m.container, dt.date.fromisoformat(day),
                                f"landed {sha[:7]}"))
            continue
        base_day = dt.date.fromisoformat(day)
        if m.container in baseline_dates:
            stamps.append(Stamp(rel, m.container, baseline_dates[m.container], "baseline"))
        else:
            waiting[m.container].append(rel)
    used = {s.territory for s in stamps if s.source == "baseline"}
    for terr, d in sorted(baseline_dates.items()):
        if terr not in used:
            bad.append(f"{terr}: no undated baseline file in it, so the date is unused")
        elif base_day and d > base_day:
            bad.append(f"{terr}={d}: after the baseline commit ({base_day}), and the files "
                       "were already there by then")
    return Plan(stamps, dict(waiting), no_hist, bad)


def apply(root: Path, p: Plan) -> tuple[list[str], storegit.Result | None]:
    """Stamp every file in the plan, then one store commit. Returns the files it could not
    stamp safely (left untouched) and the commit result."""
    skipped = []
    for s in p.stamps:
        f = root / s.rel
        new = stamp(f.read_text(encoding="utf-8"), s.date)
        if new is None:
            skipped.append(s.rel)
            continue
        f.write_text(new, encoding="utf-8")
    n = len(p.stamps) - len(skipped)
    if not n:
        return skipped, None
    terrs = sorted({s.territory for s in p.stamps if s.source == "baseline"})
    why = f"; baseline dates for {', '.join(terrs)}" if terrs else ""
    return skipped, storegit.commit(root, "mem backfill-verified",
                                    subject=f"backfill last_verified on {n} memories "
                                            f"(landing dates{why})")


def _describe(p: Plan, verbose: bool) -> list[str]:
    out = []
    by = defaultdict(list)
    for s in p.stamps:
        by[(s.territory, s.source == "baseline")].append(s)
    for (terr, is_base), ss in sorted(by.items()):
        days = sorted({s.date for s in ss})
        span = str(days[0]) if len(days) == 1 else f"{days[0]} .. {days[-1]}"
        how = "--baseline-date" if is_base else "landing commit"
        out.append(f"  {terr}: {len(ss)} -> {span}  ({how})")
        if verbose:
            out += [f"      {s.date}  {s.rel}  [{s.source}]" for s in ss]
    return out


def backfill_main(argv: list[str]) -> int:
    import argparse

    from claude_hybrid_memory.store import STORE

    ap = argparse.ArgumentParser(
        prog="mem backfill-verified",
        description="Stamp last_verified on every memory that has none: its landing date.",
        epilog="example: mem backfill-verified --baseline-date console/tools=2026-09-11 "
               "--baseline-date cards/archive=2026-09-11 --write")
    ap.add_argument("--baseline-date", action="append", default=[], metavar="TERRITORY=DATE",
                    help="landing date for a territory's files that predate the store's "
                         "history (see RETRO.md); repeat per territory")
    ap.add_argument("--write", action="store_true", help="apply it (default: show the plan)")
    ap.add_argument("--verbose", "-v", action="store_true", help="list every file")
    ap.add_argument("--root", type=Path, default=STORE)
    a = ap.parse_args(argv)

    if not storegit.is_repo(a.root):
        print(f"mem backfill-verified: {a.root} has no history to read landing dates from",
              file=sys.stderr)
        return 2
    dates = {}
    for spec in a.baseline_date:
        terr, _, day = spec.partition("=")
        try:
            dates[terr.strip().strip("/")] = dt.date.fromisoformat(day.strip())
        except ValueError:
            print(f"mem backfill-verified: {spec!r} is not TERRITORY=YYYY-MM-DD", file=sys.stderr)
            return 2
    if a.write and storegit.pending(a.root):
        print("mem backfill-verified: the store has uncommitted changes; `mem commit` them "
              "first so this lands as its own commit", file=sys.stderr)
        return 2

    p = plan(a.root, dates)
    print(f"{len(p.stamps)} memories to stamp:")
    print("\n".join(_describe(p, a.verbose)) or "  none")
    blocked = bool(p.baseline or p.bad_dates)
    if p.baseline:
        print("\nIn the baseline commit with no --baseline-date (their real landing date "
              "is in RETRO.md):")
        print("\n".join(f"  {t}: {len(fs)}" for t, fs in sorted(p.baseline.items())))
    if p.bad_dates:
        print("\nRefused --baseline-date:")
        print("\n".join(f"  {b}" for b in p.bad_dates))
    if p.no_history:
        print(f"\n{len(p.no_history)} never committed, skipped: "
              + ", ".join(p.no_history))
    if blocked:
        print("\nNothing written: every baseline territory needs a date, and every date "
              "must be usable.")
        return 1
    if not a.write:
        print("\nDry run. Pass --write to stamp and commit.")
        return 0
    skipped, c = apply(a.root, p)
    for s in skipped:
        print(f"  left untouched, frontmatter would not read back: {s}")
    if c:
        print(f"{c.status}: {c.detail}" + (f" ({c.sha})" if c.sha else ""))
        return 0 if c.status == "committed" else 2
    return 0
