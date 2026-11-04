"""`mem new`: write one territory memory the way the store expects it.

The harness's auto-memory instructions are the only write recipe a session is given, and they
route around `mem`: a Write into `projects/<cwd>/memory/`, harness frontmatter, and a
pointer line hand-added to MEMORY.md (inside the rendered block, where the next render
erases it). `mem new` is the recipe that does not: correct frontmatter, then the index brought
up to date the same way a landing does (`apply.reindex`: a rendered index re-renders, a
hand-written one gains a bare `- slug: description` line), then the near-duplicate note the
PostToolUse hook gives a new file.

It stamps `last_verified:` with today. A memory is written from what the session just saw, so
the claim is as verified as it will ever be on the day it lands. And it requires `--volatility`
or `--status` (which implies one), unless the memory is a `--record`: the writing session
knows best whether it is recording state or a fact, and that is what sets how long a later
session can act on the claim before checking it (verify-on-use, docs/direction.md).

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

from claude_hybrid_memory.spec import ROLES, SLUG_RE, STATUSES, VOLATILITIES

DEFAULT_ROLE = "reference"


@dataclass
class Made:
    path: Path
    territory: str
    rel: str
    hint: str = ""
    rendered: bool = True       # False: a hand-written index, where the line was appended
    group_note: str = ""        # how -g was resolved, when it was not an exact match


class Refused(ValueError):
    pass


def frontmatter(slug: str, description: str, *, group: str | None = None,
                role: str = DEFAULT_ROLE, volatility: str | None = None,
                status: str | None = None, record: bool = False,
                today: dt.date | None = None) -> str:
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 - YAML reads JSON strings
    lines = ["---", f"name: {slug}", f"description: {q(description)}", "kind: territory",
             f"role: {role}"]
    if status:
        lines.append(f"status: {status}")
    if volatility:
        lines.append(f"volatility: {volatility}")
    lines.append(f"last_verified: {(today or dt.date.today()).isoformat()}")
    if group:
        lines.append(f"group: {q(group)}")
    if record:
        lines.append("tier: record")
    return "\n".join(lines) + "\n---\n"


def resolve_group(root: Path, territory: str, group: str,
                  new_group: bool = False) -> tuple[str, str]:
    """(the group to write, a note) for `-g` in a rendered territory. Exact (any case) wins;
    else a unique prefix of one existing group; else a new group only when asked for. The
    eval's `-g "Card identity"` beside `Card identity, naming and writes` made a second,
    near-identical heading and still said "indexed it" (independent review, 2026-11-04).
    Raises Refused, listing the groups, when it cannot tell."""
    from claude_hybrid_memory import render

    t = render.load(root, territory)
    known = list(dict.fromkeys([*t.groups, *(e.group for e in t.entries if e.group)]))
    if not known or new_group:
        return group, (f"new group {group!r}" if known and group not in known else "")
    want = " ".join(group.split()).lower()
    exact = [g for g in known if g.lower() == want]
    if exact:
        return exact[0], ""
    pre = [g for g in known if g.lower().startswith(want)]
    if len(pre) == 1:
        return pre[0], f"-g {group!r} matched the existing group {pre[0]!r}"
    listing = "\n".join(f"  {g}" for g in known)
    why = "matches several groups" if pre else "is not one of its groups"
    raise Refused(f"-g {group!r} {why} in {territory}:\n{listing}\nPass one of these (a "
                  "unique prefix is enough), or add --new-group to start a new heading")


def make(root: Path, territory: str, slug: str, description: str, body: str, *,
         group: str | None = None, role: str = DEFAULT_ROLE,
         volatility: str | None = None, status: str | None = None,
         record: bool = False, new_group: bool = False) -> Made:
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
    if volatility and volatility not in VOLATILITIES:
        raise Refused(f"--volatility {volatility!r} not in {sorted(VOLATILITIES)}")
    if status and status not in STATUSES:
        raise Refused(f"--status {status!r} not in {sorted(STATUSES)}")
    if not (volatility or status or record):
        raise Refused("pass --volatility (stable: a fact, rule or procedure that does not "
                      "drift, such as a hardware quirk or a preference; slow: changes over "
                      "weeks, such as a repo's layout or setup; live: state such as HEAD, an "
                      "open PR, what is next) or --status, which implies one")
    note = ""
    if group:
        from claude_hybrid_memory import render
        if render.markers((tdir / "MEMORY.md").read_text(encoding="utf-8", errors="replace")):
            group, note = resolve_group(root, territory, " ".join(group.split()), new_group)
    p = tdir / f"{slug}.md"
    if p.exists():
        raise Refused(f"{territory}/{slug} already exists; edit the file to update it, or "
                      "write the replacement under a new slug and `mem supersede` the old one")
    p.write_text(frontmatter(slug, description, group=group, role=role,
                             volatility=volatility, status=status, record=record)
                 + "\n" + body.strip("\n") + "\n", encoding="utf-8")
    apply.reindex(root, territory)
    from claude_hybrid_memory import render
    # ROUTER's `(N)` and the ALWAYS.md rendered from it, so the session's own audit does
    # not show a router-count warning the write just caused (eval 2026-11-04).
    if render.router_counts(root):
        from claude_hybrid_memory.hooks import session_start
        session_start.write_always(root)
    rendered = bool(render.markers((tdir / "MEMORY.md").read_text(encoding="utf-8",
                                                                   errors="replace")))
    rel = f"territories/{territory}/{p.name}"
    return Made(p, territory, rel, _near(root, rel), rendered, note)


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
        epilog="example: mem new card-reader-panics -v stable --description 'The built-in SD "
               "reader panics under sustained I/O; use the USB one' --group Hardware "
               "<<'EOF' ... EOF\n\nTo replace a memory: `mem new` the replacement first, then "
               "`mem supersede <old> <new>`.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", help="kebab-case; becomes <slug>.md")
    ap.add_argument("--description", "-d", required=True,
                    help="one line: the conclusion, as the index will show it")
    ap.add_argument("--group", "-g",
                    help="the index heading to file it under: one of the territory's groups "
                         "(a unique prefix is enough); refused otherwise, with the list")
    ap.add_argument("--new-group", action="store_true",
                    help="-g names a heading the territory does not have yet; start it")
    ap.add_argument("--territory", "-t",
                    help="e.g. console/tools (default: the territory this directory maps to)")
    ap.add_argument("--role", default=DEFAULT_ROLE, choices=sorted(ROLES))
    ap.add_argument("--volatility", "-v", choices=sorted(VOLATILITIES),
                    help="how fast its claims drift, which sets how long a later session may "
                         "act on it unchecked (stable 365d, slow 30d, live 14d). stable: a "
                         "rule, a preference, a hardware fact or procedure, why a decision "
                         "was made; slow: a repo's layout, a tool's setup, a project's plan; "
                         "live: HEAD, an open PR, what is next, a version number. Required "
                         "unless --status or --record")
    ap.add_argument("--status", "-s", choices=sorted(STATUSES),
                    help="e.g. SHIPPED or IN FLIGHT; implies the volatility")
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
                    role=a.role, volatility=a.volatility, status=a.status,
                    record=a.record, new_group=a.new_group)
    except Refused as e:
        print(f"mem new: {e}", file=sys.stderr)
        return 2
    from claude_hybrid_memory.cli import _log
    _log(a.root, "write", made.rel, "mem new")
    if made.rendered:
        print(f"wrote {made.rel} and indexed it in {territory}/MEMORY.md; the store commits it "
              "at session end")
        if made.group_note:
            print(made.group_note)
    else:
        # Said plainly: a hand-written index has no groups to honour, and "indexed it" read
        # as success when the line had landed under whatever heading came last (eval).
        print(f"wrote {made.rel}, but {territory}/MEMORY.md is hand-written: its line was "
              "appended at the end" + (f" and --group {a.group!r} was NOT honoured" if a.group
                                       else "") + f". Move the line under the right heading, "
              f"or adopt the index with `mem render {territory} --adopt`.")
    if made.hint:
        print(made.hint)
    return 0
