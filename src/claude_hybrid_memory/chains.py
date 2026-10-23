"""Version chains: `supersedes:` on the newer memory, its inverse derived (direction §6).

The newer memory names what it replaces; the older file is never edited, not even to mark
it HISTORICAL. `superseded_by` exists only here, computed from every `supersedes:` in the
store, so there is one field and one writer. The cache stores the edges for search, the
audit checks them, and `mem history` walks them.

A memory is superseded when any memory outside `archive/` names it. A successor that was
itself retired to the archive no longer hides anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding


@dataclass(frozen=True)
class Node:
    path: str           # store-relative
    area: str           # territory | standing | archive
    container: str
    slug: str
    refs: tuple = ()    # `supersedes:` as written

    @property
    def key(self) -> str:
        return f"{self.container}/{self.slug}"


@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)       # path -> Node
    older: dict = field(default_factory=dict)       # path -> [path it supersedes]
    newer: dict = field(default_factory=dict)       # path -> [path superseding it]
    unresolved: dict = field(default_factory=dict)  # path -> [(ref, why)]
    findings: list = field(default_factory=list)

    def superseded(self) -> set[str]:
        return {old for old, news in self.newer.items()
                if any(self.nodes[n].area != "archive" for n in news)}

    def successors(self, path: str) -> list[Node]:
        return [self.nodes[n] for n in self.newer.get(path, [])
                if self.nodes[n].area != "archive"]


def refs_of(meta: dict) -> tuple:
    """`supersedes: a`, `supersedes: [a, b]`, or a block list; empty entries dropped."""
    v = meta.get("supersedes")
    items = v if isinstance(v, list) else [v]
    return tuple(s for s in (str(x).strip() for x in items if x is not None) if s)


def lookup(nodes: list[Node], ref: str, near: str | None = None) -> list[Node]:
    """A ref is a slug, container/slug, or a store-relative path. A bare slug that exists
    in several containers resolves to the one beside `near`, if there is exactly one."""
    hits = [n for n in nodes if n.path == ref]
    if not hits and "/" in ref:
        container, _, slug = ref.rpartition("/")
        hits = [n for n in nodes if n.container == container and n.slug == slug]
    if not hits:
        hits = [n for n in nodes if n.slug == ref]
        if len(hits) > 1 and near is not None:
            beside = [n for n in hits if n.container == near]
            hits = beside if len(beside) == 1 else hits
    return hits


def build(nodes: list[Node]) -> Graph:
    g = Graph(nodes={n.path: n for n in nodes})
    for n in nodes:
        for ref in n.refs:
            hits = lookup(nodes, ref, n.container)
            if len(hits) == 1 and hits[0].path == n.path:
                g.findings.append(Finding(ERROR, "supersede-self", n.path,
                                          f"supersedes: {ref} names this memory itself"))
            elif len(hits) == 1:
                old = hits[0].path
                if old not in g.older.setdefault(n.path, []):
                    g.older[n.path].append(old)
                    g.newer.setdefault(old, []).append(n.path)
            elif hits:
                g.unresolved.setdefault(n.path, []).append((ref, "ambiguous"))
                g.findings.append(Finding(WARN, "supersede-ambiguous", n.path,
                                          f"supersedes: {ref} matches "
                                          f"{', '.join(h.key for h in hits)}; write it as "
                                          "container/slug"))
            else:
                # Not an error: a memory merged away before the store had history leaves
                # nothing to point at, and the successor is still the current word.
                g.unresolved.setdefault(n.path, []).append((ref, "not found"))
                g.findings.append(Finding(INFO, "supersede-target-gone", n.path,
                                          f"supersedes: {ref} is in neither the store nor "
                                          "archive/; the chain ends here"))
    for cycle in _cycles(g.older):
        names = " -> ".join(g.nodes[p].key for p in cycle + cycle[:1])
        g.findings.append(Finding(ERROR, "supersede-cycle", cycle[0],
                                  f"{names}: every memory in the loop is hidden as superseded"))
    return g


def _cycles(older: dict) -> list[list[str]]:
    """Each cycle once, as the path list from the first node reached on it."""
    out, state = [], {}
    for start in sorted(older):
        if start in state:
            continue
        stack = [(start, iter(older.get(start, [])))]
        trail, state[start] = [start], 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                trail.pop()
                state[node] = 2
            elif state.get(nxt) == 1:
                out.append(trail[trail.index(nxt):])
            elif nxt not in state:
                state[nxt] = 1
                trail.append(nxt)
                stack.append((nxt, iter(older.get(nxt, []))))
    return out


def walk(g: Graph, path: str, direction: str) -> list[tuple[int, Node | None, str]]:
    """Depth-first along `older` or `newer`: [(depth, node, note)]. An unresolved ref
    appears with node None and the ref as the note; a revisit is marked, never re-walked."""
    edges = g.older if direction == "older" else g.newer
    out, seen = [], {path}

    def visit(p: str, depth: int) -> None:
        for q in edges.get(p, []):
            if q in seen:
                out.append((depth, g.nodes[q], "already shown (loop)"))
                continue
            seen.add(q)
            out.append((depth, g.nodes[q], ""))
            visit(q, depth + 1)
        if direction == "older":
            for ref, why in g.unresolved.get(p, []):
                out.append((depth, None, f"{ref} ({why})"))

    visit(path, 1)
    return out


def with_refs(text: str, refs: list[str]) -> str:
    """`text` with its top-level `supersedes:` set to `refs`, any old form (scalar, flow
    or block list) removed, and every other byte of the frontmatter left as it was."""
    end = text.find("\n---", 3)
    head, rest = text[:end].split("\n"), text[end:]
    out, in_old = [], False
    for line in head:
        if in_old and line[:1] in (" ", "\t", "-") and line.strip():
            continue        # a block-list item, or a continuation, of the old value
        in_old = bool(re.match(r"supersedes\s*:", line))
        if not in_old:
            out.append(line)
    refs = list(dict.fromkeys(refs))
    out.append("supersedes: " + (refs[0] if len(refs) == 1 else "[" + ", ".join(refs) + "]"))
    return "\n".join(out) + rest
