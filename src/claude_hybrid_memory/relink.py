"""`mem supersede`'s second half: point every live `[[old]]` at the memory that replaced it.

A superseded memory drops out of search and out of a rendered index, but a wikilink to it
kept routing sessions there: in the 2026-11-04 eval a territory's GATE prose still pointed at
a superseded memory after `supersede` had run. So every live markdown file in the store is
scanned, and each link found is printed.

Always-loaded gate text is listed, never rewritten: GATES.md, MACHINE.md, ROUTER.md,
standing/, and the `## GATES` section of any territory MEMORY.md. A gate edit needs the
user's named go-ahead, and a `mem` subprocess rewriting it would route around the check that
enforces that (decided 2026-11-04). The session fixes those lines with Edit, where the check
applies. Everything else is rewritten.

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
PROTECTED_FILES = {"GATES.md", "MACHINE.md", "ROUTER.md"}


@dataclass
class Change:
    path: str  # store-relative
    line: int
    before: str
    after: str
    protected: bool = False  # always-loaded gate text: listed, never written


def protected_lines(rel: Path, lines: list[str]) -> set[int]:
    """0-based indexes of the lines in `rel` that are always-loaded gate text."""
    if rel.name in PROTECTED_FILES and len(rel.parts) == 1 or rel.parts[0] == "standing":
        return set(range(len(lines)))
    if rel.name != "MEMORY.md":
        return set()
    out, inside = set(), False
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            inside = ln[3:].strip().upper().startswith("GATES")
        if inside:
            out.add(i)
    return out


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


def _scan(
    root: Path,
    nodes: list[chains.Node],
    old: chains.Node,
    skip: tuple[str, ...],
    target: str | None,
) -> list[tuple[Path, list[str], list[Change]]]:
    """Every live line with a wikilink resolving to `old`, per file, and the line with
    those links renamed to `target` (unchanged when `target` is None)."""
    found = []
    for p, rel in live_files(root):
        if str(rel) in skip:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "[[" not in text:
            continue
        near = _container(rel)
        lines, changes = text.split("\n"), []
        guard = protected_lines(rel, lines)
        for i, line in enumerate(lines):
            if "[[" not in line:
                continue
            hit = False

            def swap(m: re.Match, near=near) -> str:
                nonlocal hit
                ref, bar, rest = m.group(1).partition("|")
                found_ = chains.lookup(nodes, ref.strip(), near)
                if len(found_) == 1 and found_[0].path == old.path:
                    hit = True
                    return f"[[{target}{bar}{rest}]]" if target else m.group(0)
                return m.group(0)

            after = WIKILINK_RE.sub(swap, line)
            if hit:
                changes.append(Change(str(rel), i + 1, line, after, i in guard))
                if i not in guard:
                    lines[i] = after
        if changes:
            found.append((p, lines, changes))
    return found


def backlinks(root: Path, nodes: list[chains.Node], node: chains.Node) -> list[Change]:
    """Every live line that links to `node`; `before` is the line."""
    return [c for _, _, cs in _scan(root, nodes, node, (node.path,), None) for c in cs]


def relink(
    root: Path, nodes: list[chains.Node], old: chains.Node, new: chains.Node, write: bool = True
) -> list[Change]:
    """Rewrite each wikilink that resolves to `old` so it names `new`. The new name is the
    bare slug when that is unique in the store, else container/slug."""
    unique = len(chains.lookup(nodes, new.slug)) == 1
    target = new.slug if unique else new.key
    out: list[Change] = []
    for p, lines, changes in _scan(root, nodes, old, (old.path, new.path), target):
        out += changes
        if write and any(not c.protected for c in changes):
            p.write_text("\n".join(lines), encoding="utf-8")
    return out


def drop_entry(index: Path, filename: str) -> list[str]:
    """Remove a hand-written index's entry line for `filename`; the lines removed. A rendered
    index never needs this: the render drops superseded memories itself."""
    text = index.read_text(encoding="utf-8", errors="replace")
    rx = entry_line_re(filename)
    gone = [m.group(0) for m in rx.finditer(text)]
    if gone:
        index.write_text(re.sub(rx.pattern + r"\n?", "", text, flags=re.M), encoding="utf-8")
    return gone
