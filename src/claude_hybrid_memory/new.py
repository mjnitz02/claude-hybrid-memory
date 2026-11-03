"""`mem new`: write one territory memory the way the store expects it.

The harness's auto-memory instructions are the only write recipe a session is given, and they
route around `mem`: a Write into `projects/<cwd>/memory/`, harness frontmatter, and a
pointer line hand-added to MEMORY.md (inside the rendered block, where the next render
erases it). `mem new` is the recipe that does not: correct frontmatter, then the index brought
up to date the same way a landing does (`apply.reindex`: a rendered index re-renders, a
hand-written one gains a bare `- slug: description` line), then the near-duplicate note the
PostToolUse hook gives a new file.

It stamps `last_verified:` with today. A memory is written from what the session just saw, so
the claim is as verified as it will ever be on the day it lands; without it a `live` memory
reads as `stale-live` from its first audit.

Creation only. Updating a memory is an ordinary edit to its file; replacing one is
`mem supersede`. It never commits: the session-end hook does that for the whole session.
Nothing it prints is about size. Fitting the index is render's job and fixing what render had
to cut is the refine pass's (render.py, Budget).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from claude_hybrid_memory.spec import ROLES, SLUG_RE, VOLATILITIES

DEFAULT_ROLE = "reference"
DEFAULT_VOLATILITY = "live"


@dataclass
class Made:
    path: Path
    territory: str
    rel: str
    hint: str = ""


class Refused(ValueError):
    pass


def frontmatter(slug: str, description: str, *, group: str | None = None,
                role: str = DEFAULT_ROLE, volatility: str = DEFAULT_VOLATILITY,
                record: bool = False, today: dt.date | None = None) -> str:
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 - YAML reads JSON strings
    lines = ["---", f"name: {slug}", f"description: {q(description)}", "kind: territory",
             f"role: {role}", f"volatility: {volatility}",
             f"last_verified: {(today or dt.date.today()).isoformat()}"]
    if group:
        lines.append(f"group: {q(group)}")
    if record:
        lines.append("tier: record")
    return "\n".join(lines) + "\n---\n"


def make(root: Path, territory: str, slug: str, description: str, body: str, *,
         group: str | None = None, role: str = DEFAULT_ROLE,
         volatility: str = DEFAULT_VOLATILITY, record: bool = False) -> Made:
    """Write the memory and index it. Raises Refused, writing nothing, when it can't."""
    from claude_hybrid_memory.migrate import apply

    description = " ".join(description.split())
    tdir = root / "territories" / territory
    if not (tdir / "MEMORY.md").is_file():
        raise Refused(f"no territory {territory!r} (no territories/{territory}/MEMORY.md)")
    if not SLUG_RE.match(slug):
        raise Refused(f"{slug!r} is not a kebab-case slug (a-z, 0-9, single hyphens)")
    if slug in ("MEMORY", "EXPORTS"):
        raise Refused(f"{slug} is an index name")
    if not description:
        raise Refused("--description is empty; it is the memory's line in the index")
    if not body.strip():
        raise Refused("no body on stdin; pipe the memory's text in")
    if role not in ROLES:
        raise Refused(f"--role {role!r} not in {sorted(ROLES)}")
    if volatility not in VOLATILITIES:
        raise Refused(f"--volatility {volatility!r} not in {sorted(VOLATILITIES)}")
    p = tdir / f"{slug}.md"
    if p.exists():
        raise Refused(f"{territory}/{slug} already exists; edit the file to update it, or "
                      "write the replacement under a new slug and `mem supersede` the old one")
    p.write_text(frontmatter(slug, description, group=group, role=role,
                             volatility=volatility, record=record)
                 + "\n" + body.strip("\n") + "\n", encoding="utf-8")
    apply.reindex(root, territory)
    rel = f"territories/{territory}/{p.name}"
    return Made(p, territory, rel, _near(root, rel))


def _near(root: Path, rel: str) -> str:
    """The PostToolUse hook's note for a new file: what it closely resembles."""
    try:
        from claude_hybrid_memory.hooks import post_tool
        return post_tool._after_write(root, rel, "")
    except Exception:          # advisory only; a cache problem never fails the write
        return ""


def main(argv: list[str]) -> int:
    import argparse
    import sys

    from claude_hybrid_memory.hooks.session_start import territory_for
    from claude_hybrid_memory.store import STORE

    ap = argparse.ArgumentParser(
        prog="mem new",
        description="Write a new territory memory (body on stdin) and index it.",
        epilog="example: mem new card-reader-panics --description 'The built-in SD reader "
               "panics under sustained I/O; use the USB one' --group Hardware <<'EOF' ... EOF")
    ap.add_argument("slug", help="kebab-case; becomes <slug>.md")
    ap.add_argument("--description", "-d", required=True,
                    help="one line: the conclusion, as the index will show it")
    ap.add_argument("--group", "-g", help="the index heading to file it under")
    ap.add_argument("--territory", "-t",
                    help="e.g. console/tools (default: the territory this directory maps to)")
    ap.add_argument("--role", default=DEFAULT_ROLE, choices=sorted(ROLES))
    ap.add_argument("--volatility", default=DEFAULT_VOLATILITY, choices=sorted(VOLATILITIES))
    ap.add_argument("--record", action="store_true",
                    help="a dated record, written once and never edited (tier: record)")
    ap.add_argument("--root", type=Path, default=STORE)
    a = ap.parse_args(argv)

    territory = a.territory
    if not territory:
        territory, _ = territory_for(Path.cwd(), a.root)
        if not territory:
            print("this directory maps to no territory; pass --territory (see ROUTER.md)",
                  file=sys.stderr)
            return 2
    body = "" if sys.stdin.isatty() else sys.stdin.read()
    try:
        made = make(a.root, territory, a.slug, a.description, body, group=a.group,
                    role=a.role, volatility=a.volatility, record=a.record)
    except Refused as e:
        print(f"mem new: {e}", file=sys.stderr)
        return 2
    from claude_hybrid_memory.cli import _log
    _log(a.root, "write", made.rel, "mem new")
    print(f"wrote {made.rel} and indexed it in {territory}/MEMORY.md")
    if made.hint:
        print(made.hint)
    return 0
