"""`mem supersede`'s second half: point every live `[[old]]` at the memory that replaced it.

A superseded memory drops out of search and out of a rendered index, but a wikilink to it
kept routing sessions there: in the 2026-11-04 eval a territory's GATE prose still pointed at
a superseded memory after `supersede` had run. So every live markdown file in the store is
rewritten, and each change is printed.

Left alone: the old memory and the new one (the new memory naming what it replaced is
deliberate), `archive/`, and the generated or historical files (ALWAYS.md is rendered from
its sources; RETRO.md and events/ are logs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from claude_hybrid_memory import chains
from claude_hybrid_memory.spec import WIKILINK_RE, entry_line_re

SKIP_DIRS = {"archive", "events", "migrate", ".cache", ".git"}
SKIP_FILES = {"ALWAYS.md", "RETRO.md"}


@dataclass
class Change:
    path: str       # store-relative
    line: int
    before: str
    after: str


def _container(rel: Path) -> str | None:
    """The container a bare `[[slug]]` in this file resolves beside."""
    if rel.parts[0] == "territories":
        return str(rel.parent.relative_to("territories"))
    if rel.parts[0] == "standing":
        return "standing"
    return None


def live_files(root: Path):
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if rel.parts[0] in SKIP_DIRS or rel.name in SKIP_FILES:
            continue
        yield p, rel


def relink(root: Path, nodes: list[chains.Node], old: chains.Node, new: chains.Node,
           write: bool = True) -> list[Change]:
    """Rewrite each wikilink that resolves to `old` so it names `new`. The new name is the
    bare slug when that is unique in the store, else container/slug."""
    unique = len(chains.lookup(nodes, new.slug)) == 1
    target = new.slug if unique else new.key
    changes: list[Change] = []
    for p, rel in live_files(root):
        if str(rel) in (old.path, new.path):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "[[" not in text:
            continue
        near = _container(rel)

        def swap(m: re.Match, near=near) -> str:
            ref, bar, rest = m.group(1).partition("|")
            hits = chains.lookup(nodes, ref.strip(), near)
            if len(hits) == 1 and hits[0].path == old.path:
                return f"[[{target}{bar}{rest}]]"
            return m.group(0)

        lines = text.split("\n")
        touched = False
        for i, line in enumerate(lines):
            if "[[" not in line:
                continue
            after = WIKILINK_RE.sub(swap, line)
            if after != line:
                changes.append(Change(str(rel), i + 1, line, after))
                lines[i] = after
                touched = True
        if touched and write:
            p.write_text("\n".join(lines), encoding="utf-8")
    return changes


def drop_entry(index: Path, filename: str) -> list[str]:
    """Remove a hand-written index's entry line for `filename`; the lines removed. A rendered
    index never needs this: the render drops superseded memories itself."""
    text = index.read_text(encoding="utf-8", errors="replace")
    rx = entry_line_re(filename)
    gone = [m.group(0) for m in rx.finditer(text)]
    if gone:
        index.write_text(re.sub(rx.pattern + r"\n?", "", text, flags=re.M), encoding="utf-8")
    return gone
